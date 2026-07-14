"""
core/mcp_client_manager.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PawnLogic as an MCP client: dynamically mounts external MCP servers and injects
their tools into native TOOL_MAP / TOOLS_SCHEMA.

Architecture: background asyncio event-loop thread plus synchronous closure bridge.
  · Main thread synchronously calls TOOL_MAP["playwright__navigate"](args).
  · The closure uses run_coroutine_threadsafe to submit work to the background loop.
  · The background loop keeps long-lived ClientSession instances for MCP subprocesses.
  · stdio_client / ClientSession resources are managed by AsyncExitStack and
    shut down in LIFO order.

Design notes:
  1. Namespace: external tools are always prefixed as `{server}__{tool}`.
  2. A single server failure logs loudly but does not affect other servers.
  3. Binary content such as screenshots is saved under
     ~/.pawnlogic/workspace/mcp_assets/ and returned as a path, never base64.
  4. include_tools / exclude_tools allowlists and blocklists prevent prompt bloat.
"""

import asyncio
import base64
import json
import os
import re
import sys
import threading
import time
import traceback
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Callable, Optional

from core.path_policy import resolve_within, safe_filename_fragment

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.types import ListRootsResult, Root
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None
    ListRootsResult = None
    Root = None

from core.logger import logger
from config.paths import PAWNLOGIC_HOME
from config.security import scrub_sensitive_env


# ════════════════════════════════════════════════════════
# Constants.
# ════════════════════════════════════════════════════════
DEFAULT_TIMEOUT = 30                       # Default call_tool timeout, seconds.
STARTUP_TIMEOUT = 60                       # Total server startup timeout.
DEFAULT_SERVER_STARTUP_TIMEOUT = 15        # Per-server initialization timeout.
MCP_STDERR_LOG_MAX_BYTES = 64 * 1024       # Keep failed-server stderr logs bounded.
NAME_SEPARATOR = "__"                      # Tool-name prefix separator.
WORKSPACE_ASSETS = PAWNLOGIC_HOME / "workspace" / "mcp_assets"
MCP_STDERR_LOG_DIR = PAWNLOGIC_HOME / "logs" / "mcp"

_ENV_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")
_warned_vars: set[str] = set()             # Avoid duplicate warnings for one var.

_MCP_BASE_ENV_KEYS = {
    "PATH", "HOME", "USER", "LOGNAME", "SHELL",
    "LANG", "LC_ALL", "LC_CTYPE", "TERM",
    "TMPDIR", "TEMP", "TMP",
    "SYSTEMROOT", "COMSPEC", "PATHEXT",
}
_TRUTHY_CONFIG_VALUES = {"1", "true", "yes", "on"}
_FALSEY_CONFIG_VALUES = {"0", "false", "no", "off"}


# ════════════════════════════════════════════════════════
# Helper functions.
# ════════════════════════════════════════════════════════
def _expand_env(s: str) -> str:
    """Expand ${VAR} from the current process environment; missing vars become empty."""
    def repl(m: re.Match) -> str:
        var = m.group(1)
        val = os.environ.get(var)
        if val is None:
            if var not in _warned_vars:
                logger.warning(f"[MCP] env var ${{{var}}} not set → expanding to empty string")
                _warned_vars.add(var)
            return ""
        return val
    return _ENV_VAR_RE.sub(repl, s)


def _config_truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in _TRUTHY_CONFIG_VALUES


def _config_enabled(value: object, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in _FALSEY_CONFIG_VALUES:
        return False
    if normalized in _TRUTHY_CONFIG_VALUES:
        return True
    return default


def _server_startup_timeout(conf: dict) -> float:
    raw = conf.get("startup_timeout", os.environ.get("MCP_SERVER_STARTUP_TIMEOUT"))
    if raw is None:
        return DEFAULT_SERVER_STARTUP_TIMEOUT
    try:
        return max(1.0, float(raw))
    except (TypeError, ValueError):
        return DEFAULT_SERVER_STARTUP_TIMEOUT


def _safe_server_log_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name).strip()).strip("._")
    return safe or "server"


def _mcp_stderr_log_path(name: str) -> Path:
    return MCP_STDERR_LOG_DIR / f"{_safe_server_log_name(name)}.stderr.log"


def _truncate_stderr_log(path: Path, max_bytes: int = MCP_STDERR_LOG_MAX_BYTES) -> None:
    """Keep an MCP stderr log bounded after a startup failure."""
    try:
        if max_bytes <= 0 or not path.exists() or path.stat().st_size <= max_bytes:
            return
        with path.open("rb") as fh:
            fh.seek(-max_bytes, os.SEEK_END)
            tail = fh.read()
        path.write_bytes(
            b"[stderr truncated; keeping latest bytes]\n" + tail
        )
    except Exception as exc:
        logger.debug(f"[MCP] failed to truncate stderr log {path}: {exc}")


def _resolve_roots() -> list[Path]:
    roots: list[Path] = []
    candidates = []
    try:
        candidates.append(Path.cwd())
    except Exception:
        pass
    workspace = PAWNLOGIC_HOME / "workspace"
    try:
        workspace.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    candidates.append(workspace)

    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except Exception:
            continue
        key = str(resolved)
        if key in seen or not resolved.exists() or not resolved.is_dir():
            continue
        seen.add(key)
        roots.append(resolved)
    return roots


async def _roots_cb(_context: object) -> "ListRootsResult":
    if ListRootsResult is None or Root is None:
        raise RuntimeError("MCP root types are unavailable")
    return ListRootsResult(
        roots=[
            Root(uri=path.as_uri(), name=path.name or str(path))
            for path in _resolve_roots()
        ]
    )


def _is_legacy_fetch_uvx(name: str, conf: dict) -> bool:
    cmd = Path(str(conf.get("command", ""))).name
    args = [str(a) for a in (conf.get("args") or [])]
    return name == "fetch" and cmd == "uvx" and bool(args) and args[0] == "mcp-server-fetch"


def _server_skip_reason(name: str, conf: dict) -> str | None:
    if not _config_enabled(conf.get("enabled"), default=True):
        return "disabled by config (enabled=false)"

    allow_network_install = (
        _config_truthy(conf.get("allow_network_install"))
        or _config_truthy(os.environ.get("PAWNLOGIC_MCP_ALLOW_NETWORK_INSTALL"))
    )
    if _is_legacy_fetch_uvx(name, conf) and not allow_network_install:
        return (
            "skipped legacy 'uvx mcp-server-fetch' startup because it may fetch "
            "from PyPI and block Pawn startup; use built-in fetch_url or set "
            "allow_network_install=true to opt in"
        )
    return None


def _minimal_mcp_env(source_env: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in source_env.items()
        if key in _MCP_BASE_ENV_KEYS or key.startswith("LC_")
    }


def _build_mcp_env(conf: dict) -> dict[str, str]:
    """
    Build an explicit environment for MCP subprocesses.

    Default: pass only non-sensitive runtime basics such as PATH/HOME/TMP.
    Opt-in: `inherit_env: true` passes the parent environment after secret
    scrubbing. In both modes, `env` config entries are deliberate overrides and
    may reference `${VAR}` from the current process.
    """
    parent_env = scrub_sensitive_env(os.environ)
    base_env = (
        parent_env
        if _config_truthy(conf.get("inherit_env"))
        else _minimal_mcp_env(parent_env)
    )
    env_overrides = {
        str(k): _expand_env(str(v)) for k, v in (conf.get("env") or {}).items()
    }
    return {**base_env, **env_overrides}


def _save_binary_asset(data_b64: str, mime: str, server: str) -> str:
    """Save base64 binary data returned by MCP and return an absolute path or error."""
    ext_map = {
        "image/png":  "png", "image/jpeg": "jpg", "image/gif":  "gif",
        "image/webp": "webp", "image/bmp":  "bmp", "image/svg+xml": "svg",
        "application/pdf": "pdf",
    }
    ext = ext_map.get((mime or "").lower(), "bin")
    try:
        WORKSPACE_ASSETS.mkdir(parents=True, exist_ok=True)
        safe_server = safe_filename_fragment(server, fallback="mcp")
        fname = f"{safe_server}_{int(time.time() * 1000)}.{ext}"
        # Verify the final path stays inside the assets directory.
        resolved = resolve_within(WORKSPACE_ASSETS, fname)
        resolved.write_bytes(base64.b64decode(data_b64))
        return str(resolved)
    except ValueError as e:
        return f"[binary save failed: {e}]"
    except Exception as e:
        return f"[binary save failed: {type(e).__name__}: {e}]"


def _flatten_mcp_content(content_blocks: list, server: str) -> str:
    """
    Flatten CallToolResult.content into one text string.
    Binary blocks are saved to disk and represented by paths.
    Supports TextContent / ImageContent / EmbeddedResource.
    """
    parts: list[str] = []
    for block in (content_blocks or []):
        btype = getattr(block, "type", "")

        # Text.
        if btype == "text" or hasattr(block, "text"):
            parts.append(getattr(block, "text", "") or "")
            continue

        # Image / binary.
        if btype == "image" or (hasattr(block, "data") and hasattr(block, "mimeType")):
            saved_path = _save_binary_asset(
                getattr(block, "data", ""),
                getattr(block, "mimeType", ""),
                server,
            )
            parts.append(f"[Binary saved to: {saved_path}]")
            continue

        # Embedded resource.
        if btype == "resource" or hasattr(block, "resource"):
            res = getattr(block, "resource", None)
            uri = getattr(res, "uri", "?") if res else "?"
            parts.append(f"[Embedded resource: {uri}]")
            continue

        parts.append(f"[Unknown content block type: {btype}]")

    return "\n".join(parts) if parts else "(empty result)"


# ════════════════════════════════════════════════════════
# Manager
# ════════════════════════════════════════════════════════
class MCPClientManager:
    """
    External MCP server manager.

    Lifecycle: start() -> tools are called repeatedly -> shutdown()
    """

    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)
        # Background loop / thread.
        self._loop:   Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        # Async resources, accessed only inside the background loop.
        self._stack:        Optional[AsyncExitStack] = None
        self._shutdown_evt: Optional[asyncio.Event]  = None
        self._sessions: dict[str, ClientSession] = {}
        # Tool metadata. Written once by bg loop, then read-only from main thread.
        # prefixed_name -> {server, original_name, description, input_schema, timeout, phase}
        self.discovered_tools: dict[str, dict] = {}
        # Startup synchronization.
        self._ready  = threading.Event()
        self._failed = threading.Event()
        self._start_error: Optional[BaseException] = None
        self._debug_stderr = False

    # Public API, synchronous from main thread.
    def start(self) -> bool:
        """
        Start the background thread and connect all servers.
        Blocks until servers are ready or timeout. Returns True if at least one
        server is online; False means full failure or no config.
        """
        if self._thread is not None:
            return bool(self._sessions)

        if not self.config_path.exists():
            logger.info(f"[MCP] no config at {self.config_path}, skip external servers")
            return False

        self._thread = threading.Thread(
            target=self._run_loop,
            name="pawnlogic-mcp-loop",
            daemon=True,
        )
        self._thread.start()

        if not self._ready.wait(timeout=STARTUP_TIMEOUT):
            logger.error(f"[MCP] startup timed out after {STARTUP_TIMEOUT}s")
            return False
        if self._failed.is_set():
            logger.error(f"[MCP] startup crashed: {self._start_error}")
            return False

        n_srv = len(self._sessions)
        n_tools = len(self.discovered_tools)
        if n_srv == 0:
            logger.warning("[MCP] config parsed but no server connected")
            return False
        logger.info(f"[MCP] ✔ {n_srv} server(s) online, {n_tools} tool(s) discovered")
        return True

    def shutdown(self) -> None:
        """Signal the background task to exit AsyncExitStack and wait for thread end."""
        if self._loop is None or self._loop.is_closed():
            return
        if self._shutdown_evt is None:
            # Background task has not created the event; force-stop the loop.
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass
        else:
            try:
                self._loop.call_soon_threadsafe(self._shutdown_evt.set)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                logger.warning("[MCP] background thread did not exit cleanly")

    def build_pawnlogic_schemas(self) -> list[dict]:
        """Convert to OpenAI function-call schema that can extend TOOLS_SCHEMA."""
        out: list[dict] = []
        for name, info in self.discovered_tools.items():
            params = info.get("input_schema") or {"type": "object", "properties": {}}
            out.append({
                "type": "function",
                "function": {
                    "name":        name,
                    "description": f"[MCP·{info['server']}] {info.get('description', '')}".strip(),
                    "parameters":  params,
                },
            })
        return out

    def build_pawnlogic_handlers(self) -> dict[str, Callable[[dict], str]]:
        """Return one sync closure per external tool, ready to update TOOL_MAP."""
        return {name: self._make_handler(name) for name in self.discovered_tools}

    def get_phase_mapping(self) -> dict[str, str]:
        """Return prefixed_name -> phase for callers to write into AGENT_PHASES."""
        return {name: info.get("phase", "GENERAL")
                for name, info in self.discovered_tools.items()}

    # Background thread main loop.
    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve_forever())
        except BaseException as e:
            self._start_error = e
            self._failed.set()
            logger.error(f"[MCP] serve_forever crashed: {e}\n{traceback.format_exc()}")
        finally:
            self._ready.set()                      # Fallback wakeup for start() waiters.
            try:
                loop.close()
            except Exception:
                pass

    async def _serve_forever(self) -> None:
        """
        Key design: AsyncExitStack enter/exit must happen in the same task due
        to anyio cancel-scope constraints. This coroutine initializes resources,
        waits for shutdown, then releases everything on async-with exit.
        """
        self._shutdown_evt = asyncio.Event()
        async with AsyncExitStack() as stack:
            self._stack = stack
            await self._connect_all()
            self._ready.set()                      # Notify main thread that work can start.
            await self._shutdown_evt.wait()        # Stay resident.
        # The stack exits in the same task here, so subprocesses are cleaned up.

    async def _connect_all(self) -> None:
        try:
            raw = self.config_path.read_text(encoding="utf-8", errors="ignore")
            config = json.loads(raw)
        except Exception as e:
            logger.error(f"[MCP] failed to parse {self.config_path}: {e}")
            return

        servers = config.get("mcpServers", {}) or {}
        self._debug_stderr = _config_truthy(config.get("debug_stderr"))
        if not servers:
            logger.warning(f"[MCP] config has empty mcpServers map")
            return

        for name, conf in servers.items():
            if not isinstance(conf, dict):
                logger.warning(f"[MCP] skip '{name}': entry is not an object")
                continue
            skip_reason = _server_skip_reason(name, conf)
            if skip_reason:
                logger.info(f"[MCP] skip '{name}': {skip_reason}")
                continue
            try:
                await asyncio.wait_for(
                    self._connect_one(name, conf),
                    timeout=_server_startup_timeout(conf),
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"[MCP] ⚠ server '{name}' INIT TIMEOUT after "
                    f"{_server_startup_timeout(conf):g}s → tools unavailable"
                )
            except Exception as e:
                # One server failing must not affect other servers, but log loudly.
                logger.warning(
                    f"[MCP] ⚠ server '{name}' INIT FAILED → tools unavailable. "
                    f"reason: {type(e).__name__}: {e}"
                )

    async def _connect_one(self, name: str, conf: dict) -> None:
        cmd = conf.get("command")
        if not cmd:
            raise ValueError(f"missing 'command' field")

        args = [_expand_env(str(a)) for a in (conf.get("args") or [])]
        full_env = _build_mcp_env(conf)

        params = StdioServerParameters(command=cmd, args=args, env=full_env)

        # One sub-stack per server: local cleanup on failure, graft into global on success.
        sub = AsyncExitStack()
        errlog_path: Path | None = None
        try:
            if self._debug_stderr:
                errlog = sys.stderr
            else:
                MCP_STDERR_LOG_DIR.mkdir(parents=True, exist_ok=True)
                errlog_path = _mcp_stderr_log_path(name)
                errlog = sub.enter_context(
                    errlog_path.open("a", encoding="utf-8")
                )
            read, write = await sub.enter_async_context(stdio_client(params, errlog=errlog))
            session = await sub.enter_async_context(
                ClientSession(read, write, list_roots_callback=_roots_cb)
            )
            await session.initialize()
        except BaseException:
            await sub.aclose()                 # Clean up subprocess.
            if errlog_path is not None:
                _truncate_stderr_log(errlog_path)
            raise

        if self._stack is None:
            raise RuntimeError("MCP client manager is not running")
        await self._stack.enter_async_context(sub)
        self._sessions[name] = session

        # Fetch tool list and apply include/exclude filters.
        try:
            listed = await session.list_tools()
        except Exception as e:
            logger.warning(f"[MCP] '{name}' list_tools failed: {e}")
            return

        include = set(conf.get("include_tools") or [])
        exclude = set(conf.get("exclude_tools") or [])
        timeout = int(conf.get("timeout", DEFAULT_TIMEOUT))
        phase   = str(conf.get("phase", "GENERAL"))

        total = len(listed.tools)
        kept  = 0
        for tool in listed.tools:
            tname = tool.name
            if include and tname not in include:
                continue
            if tname in exclude:
                continue
            prefixed = f"{name}{NAME_SEPARATOR}{tname}"
            if prefixed in self.discovered_tools:
                logger.warning(f"[MCP] tool '{prefixed}' already registered, overwriting")
            self.discovered_tools[prefixed] = {
                "server":        name,
                "original_name": tname,
                "description":   tool.description or "",
                "input_schema":  tool.inputSchema or {"type": "object", "properties": {}},
                "timeout":       timeout,
                "phase":         phase,
            }
            kept += 1

        logger.info(
            f"[MCP] ✔ '{name}': {kept}/{total} tools registered "
            f"(phase={phase}, timeout={timeout}s)"
        )

    # Handler factory and dispatch.
    def _make_handler(self, prefixed_name: str) -> Callable[[dict], str]:
        info     = self.discovered_tools[prefixed_name]
        server   = info["server"]
        original = info["original_name"]
        timeout  = info["timeout"]

        def handler(args: dict) -> str:
            if self._loop is None or self._loop.is_closed():
                return f"[MCP error] event loop is dead for {prefixed_name}"
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    self._call_async(server, original, args or {}),
                    self._loop,
                )
                # Allow headroom for up to 3 attempts + backoff waits
                return fut.result(timeout=timeout * 3 + 12)
            except asyncio.TimeoutError:
                return f"[MCP error] {prefixed_name} timed out after {timeout}s"
            except Exception as e:
                return f"[MCP error] {prefixed_name}: {type(e).__name__}: {e}"

        handler.__name__ = f"mcp_handler_{prefixed_name}"
        return handler

    async def _call_async(self, server: str, tool_name: str, args: dict) -> str:
        session = self._sessions.get(server)
        if session is None:
            return f"[MCP] server '{server}' not connected"
        last_err: BaseException | None = None
        for attempt in range(3):
            try:
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, args),
                    timeout=self.discovered_tools.get(
                        f"{server}{NAME_SEPARATOR}{tool_name}", {}
                    ).get("timeout", DEFAULT_TIMEOUT),
                )
            except (asyncio.TimeoutError, ConnectionError, OSError) as e:
                last_err = e
                if attempt < 2:
                    wait = min(2 ** attempt, 8)
                    logger.warning(
                        f"[MCP] {server}/{tool_name} attempt {attempt+1} failed, "
                        f"retrying in {wait}s: {e}"
                    )
                    await asyncio.sleep(wait)
                continue
            except Exception as e:
                return f"[MCP] call_tool failed: {type(e).__name__}: {e}"

            text = _flatten_mcp_content(result.content, server)
            if getattr(result, "isError", False):
                return f"[MCP tool error from {server}] {text}"
            return text

        return f"[MCP] {server}/{tool_name} failed after 3 attempts: {type(last_err).__name__}: {last_err}"


# ════════════════════════════════════════════════════════
# Module-level singleton and convenience entry points for main.py / session.py.
# ════════════════════════════════════════════════════════
_GLOBAL_MANAGER: Optional[MCPClientManager] = None


def _is_mcp_disabled() -> bool:
    return os.environ.get("MCP_ENABLED", "").strip().lower() in {"0", "false", "no", "off"}


def get_manager() -> Optional[MCPClientManager]:
    return _GLOBAL_MANAGER


def init_external_mcp(config_path: Optional[Path] = None) -> Optional["MCPClientManager"]:
    """
    Call once during early main.py startup to launch the background thread and
    connect external servers. Returns a ready manager, or None for no config,
    full failure, or missing MCP package.
    """
    if _is_mcp_disabled():
        return None
    if not _MCP_AVAILABLE:
        return None
    global _GLOBAL_MANAGER
    if _GLOBAL_MANAGER is not None:
        return _GLOBAL_MANAGER

    cfg = config_path or (PAWNLOGIC_HOME / "mcp_configs.json")
    mgr = MCPClientManager(cfg)
    if not mgr.start():
        return None
    _GLOBAL_MANAGER = mgr
    return mgr


def shutdown_external_mcp() -> None:
    """Call from main.py finally after the main loop exits."""
    global _GLOBAL_MANAGER
    if _GLOBAL_MANAGER is not None:
        _GLOBAL_MANAGER.shutdown()
        _GLOBAL_MANAGER = None
