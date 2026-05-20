"""
core/mcp_client_manager.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PawnLogic 作为 MCP Client：动态挂载外部 MCP Server，把它们暴露的
工具无缝注入到原生 TOOL_MAP / TOOLS_SCHEMA。

架构：背景 asyncio 事件循环线程 + 同步闭包桥接。
  · 主线程同步调用 TOOL_MAP["playwright__navigate"](args)
  · 闭包内 run_coroutine_threadsafe 投递任务到背景 loop
  · 背景 loop 内一组长驻 ClientSession 与各 MCP 子进程对话
  · 全部 stdio_client / ClientSession 由 AsyncExitStack 托管
    shutdown 时 LIFO 优雅回收 npx 子进程

设计要点：
  1. 命名空间：外部工具一律 prefixed 为 `{server}__{tool}`
  2. 单 server 失败 → loguru 显眼黄/红日志，不影响其他 server
  3. 二进制内容（截图）落盘到 ~/.pawnlogic/workspace/mcp_assets/
     返回路径字符串，绝不把 base64 塞回 LLM 上下文
  4. include_tools / exclude_tools 白黑名单 → 防止 prompt 爆炸
"""

import asyncio
import base64
import json
import os
import re
import threading
import time
import traceback
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Callable, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from core.logger import logger


# ════════════════════════════════════════════════════════
# 常量
# ════════════════════════════════════════════════════════
DEFAULT_TIMEOUT  = 120                     # 单次 call_tool 默认超时（秒）
STARTUP_TIMEOUT  = 60                      # 全体 server 启动总超时
NAME_SEPARATOR   = "__"                    # 工具名前缀分隔符
WORKSPACE_ASSETS = Path.home() / ".pawnlogic" / "workspace" / "mcp_assets"

_ENV_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")
_warned_vars: set[str] = set()             # 避免同一 var 重复告警


# ════════════════════════════════════════════════════════
# 辅助函数
# ════════════════════════════════════════════════════════
def _expand_env(s: str) -> str:
    """${VAR} → 当前进程环境变量。未定义则替换为空串并发一次黄色警告。"""
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


def _save_binary_asset(data_b64: str, mime: str, server: str) -> str:
    """把 MCP 返回的 base64 二进制数据落盘，返回绝对路径或错误说明。"""
    ext_map = {
        "image/png":  "png", "image/jpeg": "jpg", "image/gif":  "gif",
        "image/webp": "webp", "image/bmp":  "bmp", "image/svg+xml": "svg",
        "application/pdf": "pdf",
    }
    ext = ext_map.get((mime or "").lower(), "bin")
    try:
        WORKSPACE_ASSETS.mkdir(parents=True, exist_ok=True)
        fname = f"{server}_{int(time.time() * 1000)}.{ext}"
        path  = WORKSPACE_ASSETS / fname
        path.write_bytes(base64.b64decode(data_b64))
        return str(path)
    except Exception as e:
        return f"[binary save failed: {type(e).__name__}: {e}]"


def _flatten_mcp_content(content_blocks: list, server: str) -> str:
    """
    把 CallToolResult.content 数组合并为单一文本，二进制写盘后只返回路径。
    支持 TextContent / ImageContent / EmbeddedResource。
    """
    parts: list[str] = []
    for block in (content_blocks or []):
        btype = getattr(block, "type", "")

        # 文本
        if btype == "text" or hasattr(block, "text"):
            parts.append(getattr(block, "text", "") or "")
            continue

        # 图片 / 二进制
        if btype == "image" or (hasattr(block, "data") and hasattr(block, "mimeType")):
            saved_path = _save_binary_asset(
                getattr(block, "data", ""),
                getattr(block, "mimeType", ""),
                server,
            )
            parts.append(f"[Binary saved to: {saved_path}]")
            continue

        # 资源嵌入
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
    外部 MCP Server 总管。生命周期：
        start() → 工具被反复调用 → shutdown()
    """

    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)
        # 背景 loop / 线程
        self._loop:   Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        # async 资源（仅在 bg loop 内访问）
        self._stack:        Optional[AsyncExitStack] = None
        self._shutdown_evt: Optional[asyncio.Event]  = None
        self._sessions: dict[str, ClientSession] = {}
        # 工具元数据（bg loop 写一次，主线程之后只读）
        # prefixed_name → {server, original_name, description, input_schema, timeout, phase}
        self.discovered_tools: dict[str, dict] = {}
        # 启动同步
        self._ready  = threading.Event()
        self._failed = threading.Event()
        self._start_error: Optional[BaseException] = None

    # ── 公共 API（主线程同步）──────────────────────────
    def start(self) -> bool:
        """
        启背景线程 + 连接全部 server。阻塞至所有 server 就绪或超时。
        返回 True 表示至少有一个 server 成功就绪；False 表示完全失败/无配置。
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
        """通知背景 task 退出 AsyncExitStack，回收子进程；阻塞至线程结束。"""
        if self._loop is None or self._loop.is_closed():
            return
        if self._shutdown_evt is None:
            # 背景 task 还没创建 event；强行 stop loop
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
        """转 OpenAI function-call schema，可直接 extend 到 TOOLS_SCHEMA。"""
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
        """每个外部工具一份 sync 闭包，可直接 update 到 TOOL_MAP。"""
        return {name: self._make_handler(name) for name in self.discovered_tools}

    def get_phase_mapping(self) -> dict[str, str]:
        """prefixed_name → phase。供调用方写入 AGENT_PHASES。"""
        return {name: info.get("phase", "GENERAL")
                for name, info in self.discovered_tools.items()}

    # ── 背景线程主循环 ────────────────────────────────
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
            self._ready.set()                      # 兜底唤醒 start() 等待者
            try:
                loop.close()
            except Exception:
                pass

    async def _serve_forever(self) -> None:
        """
        关键设计：AsyncExitStack 的进入与退出必须在同一 task 内（anyio
        cancel scope 限制）。所以这个 coroutine 既负责初始化，又长驻等待
        shutdown 信号，最后在 async with 退出时统一回收。
        """
        self._shutdown_evt = asyncio.Event()
        async with AsyncExitStack() as stack:
            self._stack = stack
            await self._connect_all()
            self._ready.set()                      # 通知主线程：可以开干
            await self._shutdown_evt.wait()        # 长驻
        # stack 在此处的同一 task 内被退出 → 子进程优雅回收

    async def _connect_all(self) -> None:
        try:
            raw = self.config_path.read_text(encoding="utf-8", errors="ignore")
            config = json.loads(raw)
        except Exception as e:
            logger.error(f"[MCP] failed to parse {self.config_path}: {e}")
            return

        servers = config.get("mcpServers", {}) or {}
        if not servers:
            logger.warning(f"[MCP] config has empty mcpServers map")
            return

        for name, conf in servers.items():
            if not isinstance(conf, dict):
                logger.warning(f"[MCP] skip '{name}': entry is not an object")
                continue
            try:
                await self._connect_one(name, conf)
            except Exception as e:
                # 单 server 失败 → 不影响其他 server，但日志要醒目
                logger.warning(
                    f"[MCP] ⚠ server '{name}' INIT FAILED → tools unavailable. "
                    f"reason: {type(e).__name__}: {e}"
                )

    async def _connect_one(self, name: str, conf: dict) -> None:
        cmd = conf.get("command")
        if not cmd:
            raise ValueError(f"missing 'command' field")

        args = [_expand_env(str(a)) for a in (conf.get("args") or [])]
        env_overrides = {
            k: _expand_env(str(v)) for k, v in (conf.get("env") or {}).items()
        }
        # 合并系统 env，让用户配置覆盖
        full_env = ({**os.environ, **env_overrides} if env_overrides else None)

        params = StdioServerParameters(command=cmd, args=args, env=full_env)

        # 每个 server 一个子 stack：失败时局部清理，成功后嫁接全局
        sub = AsyncExitStack()
        try:
            read, write = await sub.enter_async_context(stdio_client(params))
            session = await sub.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except BaseException:
            await sub.aclose()                 # 干净回收 npx 子进程
            raise

        await self._stack.enter_async_context(sub)
        self._sessions[name] = session

        # 抓工具清单 + 白黑名单过滤
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

    # ── handler 工厂 + dispatch ────────────────────────
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
                return fut.result(timeout=timeout)
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
        try:
            result = await session.call_tool(tool_name, args)
        except Exception as e:
            return f"[MCP] call_tool failed: {type(e).__name__}: {e}"

        text = _flatten_mcp_content(result.content, server)
        if getattr(result, "isError", False):
            return f"[MCP tool error from {server}] {text}"
        return text


# ════════════════════════════════════════════════════════
# 模块级单例 + 便捷入口（main.py / session.py 调用此组合）
# ════════════════════════════════════════════════════════
_GLOBAL_MANAGER: Optional[MCPClientManager] = None


def get_manager() -> Optional[MCPClientManager]:
    return _GLOBAL_MANAGER


def init_external_mcp(config_path: Optional[Path] = None) -> Optional[MCPClientManager]:
    """
    在 main.py 启动早期调用一次：拉起背景线程 + 全部外部 server。
    返回已就绪的 manager（无配置/全部失败 → None）。
    """
    global _GLOBAL_MANAGER
    if _GLOBAL_MANAGER is not None:
        return _GLOBAL_MANAGER

    cfg = config_path or (Path.home() / ".pawnlogic" / "mcp_configs.json")
    mgr = MCPClientManager(cfg)
    if not mgr.start():
        return None
    _GLOBAL_MANAGER = mgr
    return mgr


def shutdown_external_mcp() -> None:
    """在 main.py 主循环退出后 finally 中调用。"""
    global _GLOBAL_MANAGER
    if _GLOBAL_MANAGER is not None:
        _GLOBAL_MANAGER.shutdown()
        _GLOBAL_MANAGER = None
