"""
core/session.py - AgentSession and agentic loop.
Plan-as-Key Architecture

Change summary (Plan-as-Key + coaching-mode CoT Guard):
  [1] Constant refactor:
        - Removed _PLAN_REQUIRED_MSG / _SELF_CORRECTION_MSG.
        - Added _PLAN_MISSING_SIGNAL, injected after tool results so attention
          stays close to the current reasoning layer.
        - Added _PLAN_EXEMPT_TOOLS + _is_plan_exempt() for read-only tools.
        - Added _MAX_SOFT_CORRECTIONS / _MAX_HARD_KILLS threshold constants.
  [2] _PlanRenderer upgrade:
        - Added subtag rendering for <intent> <tool> <why> <next> <anchor>
          <correction>.
        - Preserved backward compatibility with <action> <verify>.
  [3] Execution Protocol system prompt update:
        - Plan format now uses <intent>/<tool>/<why>/<next> subtags.
        - Added Self-Correction Protocol, Anti-Drift Anchor, and Long Output
          Management.
  [4] run_turn CoT Guard refactor:
        - Exempt read-only tools such as pwn_env, list_dir, and read-only git_op.
        - Soft intercepts execute tools and inject PLAN_MISSING afterward.
        - Hard stop happens only after soft intercepts are exhausted.

Existing GSA, Anti-Loop, concurrency truncation, Pwn constraints, and
auto-intuition features are preserved.
"""

import itertools
import os, json, sys, threading, time
from pathlib import Path
from config import (
    DYNAMIC_CONFIG, MODELS, DEFAULT_MODEL,
    validate_api_key, VERSION, GLOBAL_SKILLS_PATH,
    AGENT_PHASES,
    user_friendly_error,
    is_fast_model, find_fast_peer,
    SKILLS_DIR,
)
from utils.ansi import c, BOLD, DIM, GRAY, CYAN, GREEN, YELLOW, RED, MAGENTA
from core.api_client import stream_request, ensure_tool_call_id
from core.context_window import (
    _ctx_chars as _ctx_chars,
    _drop_dangling_tool_call_messages as _drop_dangling_tool_call_messages,
    _trim_and_compact_context as _trim_and_compact_context,
)
from core.state import state as _runtime_state, runtime_config
from core.runtime_context import RuntimeContext, current_runtime_context
from core.output import runtime_print as print
from core.runtime_metrics import RuntimeMetrics, RuntimeMetricsSnapshot
from core.prompt_builder import build_session_prompt
from core.tool_calls import extract_tool_calls
from core.tool_executor import (
    ToolExecutionOutcome,
    ToolExecutor,
    ToolExecutionContext,
    preview_tool_arguments,
    resolve_tool_arguments,
)
from core.session_tool_loop import TurnToolLoop
from core.tool_result import (
    ToolResultProcessor,
    compact_redundant_tool_error_messages,
)
from core.tool_registry import ToolRegistry, ToolSpec
from core.trust import TrustBoundaryKind
from core.tool_routing import select_phase_tools
from core.turn_api import TurnApiResult, consume_model_stream
from core.turn_state import TurnState
from core.turn_guards import (
    decide_empty_response_retry,
    decide_urgent_mode,
    is_empty_response,
)
from core.memory import (
    init_db, _gen_id, search_knowledge, format_knowledge_for_prompt,
    update_session_naming,
    # P0: Failure Pattern DB
    write_failure, check_failure, count_failure,
    format_failures_for_prompt,
)
from core.gsa import load_relevant_skills, bump_skill, sink_failure_to_gsa  # ★ GSA

from tools.file_ops  import (tool_read_file, tool_read_file_lines, tool_write_file,
                              tool_patch_file, tool_list_dir, tool_find_files,
                              tool_run_shell, tool_run_interactive, sync_runtime_context,
                              FILE_SCHEMAS)
from core.naming import (
    stable_workspace_dir, should_name_session, generate_session_name,
    create_workspace_alias, pick_naming_model,
)
from core import plan_guard as _plan_guard
from tools.web_ops   import tool_web_search, tool_fetch_url, tool_git_op, WEB_SCHEMAS
from tools.sandbox   import tool_run_code, SANDBOX_SCHEMAS
from tools.pwn_chain import (tool_pwn_env, tool_inspect_binary, tool_pwn_rop,
                              tool_pwn_cyclic, tool_pwn_disasm, tool_pwn_libc,
                              tool_pwn_debug, tool_pwn_one_gadget,
                              tool_pwn_timed_debug, PWN_SCHEMAS)
from tools.vision    import analyze_local_image, VISION_SCHEMAS
from core.logger import logger, audit_tool_call


def _user_mode() -> bool:
    context = current_runtime_context()
    if context is not None:
        return bool(context.user_mode)
    return bool(_runtime_state.user_mode)


def _debug_mode() -> bool:
    context = current_runtime_context()
    if context is not None:
        return bool(context.debug_mode)
    return bool(_runtime_state.debug_mode)


def _dynamic_config() -> dict:
    """Return the currently loaded mutable runtime config via the runtime interface."""
    context = current_runtime_context()
    if context is not None:
        return context.dynamic_config
    try:
        return runtime_config()
    except Exception:
        return DYNAMIC_CONFIG


def _tool_schema_snapshot() -> list[dict]:
    return _TOOL_REGISTRY.snapshot_schemas()


def _tool_map_snapshot() -> dict[str, callable]:
    return _TOOL_REGISTRY.snapshot_map()


def _tool_specs_snapshot() -> tuple[ToolSpec, ...]:
    return _TOOL_REGISTRY.snapshot_specs()


def _refresh_legacy_tool_globals() -> None:
    global TOOL_MAP, TOOLS_SCHEMA
    TOOL_MAP = _TOOL_REGISTRY.live_map()
    TOOLS_SCHEMA = _TOOL_REGISTRY.snapshot_schemas()


class _ThinkingSpinner:
    """Small terminal spinner shown while the model has not produced output."""

    def __init__(self, enabled: bool, label: str = "Thinking") -> None:
        self.enabled = enabled and sys.stdout.isatty()
        self.label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._printed = False
        self._stopped = False

    def start(self) -> None:
        if self._stopped or not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="thinking-spinner")
        self._thread.start()

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        if not self._thread:
            return
        self._stop.set()
        self._thread.join(timeout=1.0)
        if self._printed:
            sys.stdout.write("\r" + " " * (len(self.label) + 8) + "\r")
            sys.stdout.flush()
        self._thread = None

    def _run(self) -> None:
        for frame in itertools.cycle("|/-\\"):
            if self._stop.wait(0.12):
                return
            self._printed = True
            sys.stdout.write(c(GRAY, f"\r  {frame} {self.label}..."))
            sys.stdout.flush()

# P3 + P4: Docker containerization. Optional dependency; silently skip if absent.
try:
    from tools.docker_sandbox import (
        tool_run_code_docker, tool_pwn_container,
        tool_install_package, docker_prune_resources,
        DOCKER_SCHEMAS,
    )
except ImportError:
    tool_run_code_docker   = None
    tool_pwn_container     = None
    tool_install_package   = None   # P4.2
    docker_prune_resources = None   # P4.3
    DOCKER_SCHEMAS         = []

# P5: Scrapling browser toolkit. Optional dependency; silently skip if absent.
try:
    from tools.browser_ops import (
        tool_web_fetch, tool_web_click, tool_web_screenshot,
        tool_web_select, tool_web_type, tool_web_navigate,
        BROWSER_SCHEMAS,
    )
except ImportError:
    tool_web_fetch      = None
    tool_web_click      = None
    tool_web_screenshot = None
    tool_web_select     = None
    tool_web_type       = None
    tool_web_navigate   = None
    BROWSER_SCHEMAS     = []

# P6: environment reconnaissance tools. Optional dependency; silently skip if absent.
try:
    from tools.recon_ops import tool_check_service, RECON_SCHEMAS
except ImportError:
    tool_check_service = None
    RECON_SCHEMAS      = []

_TOOL_REGISTRY = ToolRegistry()

_BASE_TOOL_MAP: dict = {
    "read_file":           tool_read_file,
    "read_file_lines":     tool_read_file_lines,
    "write_file":          tool_write_file,
    "patch_file":          tool_patch_file,
    "list_dir":            tool_list_dir,
    "find_files":          tool_find_files,
    "run_shell":           tool_run_shell,
    "run_interactive":     tool_run_interactive,
    "web_search":          tool_web_search,
    "fetch_url":           tool_fetch_url,
    "git_op":              tool_git_op,
    "run_code":            tool_run_code,
    "pwn_env":             tool_pwn_env,
    "inspect_binary":      tool_inspect_binary,
    "pwn_rop":             tool_pwn_rop,
    "pwn_cyclic":          tool_pwn_cyclic,
    "pwn_disasm":          tool_pwn_disasm,
    "pwn_libc":            tool_pwn_libc,
    "pwn_debug":           tool_pwn_debug,
    "pwn_one_gadget":      tool_pwn_one_gadget,
    "pwn_timed_debug":     tool_pwn_timed_debug,
    "analyze_local_image": analyze_local_image,
}
for _tool_name, _handler in _BASE_TOOL_MAP.items():
    _TOOL_REGISTRY.register(_tool_name, _handler)

# P3 + P4: optional Docker tool registration.
if tool_run_code_docker:
    _TOOL_REGISTRY.register("run_code_docker", tool_run_code_docker)
if tool_pwn_container:
    _TOOL_REGISTRY.register("pwn_container", tool_pwn_container)
if tool_install_package:                                    # P4.2
    _TOOL_REGISTRY.register("tool_install_package", tool_install_package)
if docker_prune_resources:                                  # P4.3
    _TOOL_REGISTRY.register("docker_prune_resources", docker_prune_resources)

# P5: optional Scrapling browser tool registration.
if tool_web_fetch:
    _TOOL_REGISTRY.register("web_fetch", tool_web_fetch)
if tool_web_click:
    _TOOL_REGISTRY.register("web_click", tool_web_click)
if tool_web_screenshot:
    _TOOL_REGISTRY.register("web_screenshot", tool_web_screenshot)
if tool_web_select:
    _TOOL_REGISTRY.register("web_select", tool_web_select)
if tool_web_type:
    _TOOL_REGISTRY.register("web_type", tool_web_type)
if tool_web_navigate:
    _TOOL_REGISTRY.register("web_navigate", tool_web_navigate)

# P6: optional environment reconnaissance tool registration.
if tool_check_service:
    _TOOL_REGISTRY.register("check_service", tool_check_service)

_TOOL_REGISTRY.set_schemas(
    FILE_SCHEMAS + WEB_SCHEMAS + SANDBOX_SCHEMAS
    + PWN_SCHEMAS + VISION_SCHEMAS + DOCKER_SCHEMAS
    + BROWSER_SCHEMAS + RECON_SCHEMAS,
    phase_map=AGENT_PHASES,
)

_SHELL_CAPABILITY_TOOLS = frozenset({
    "run_shell", "run_interactive", "run_code", "pwn_debug",
    "pwn_timed_debug", "pwn_container", "run_code_docker",
    "tool_install_package", "docker_prune_resources",
})
_MUTATING_CAPABILITY_TOOLS = frozenset({
    "write_file", "patch_file", "git_op", "web_click", "web_type",
    "web_select", "web_navigate", "pwn_container", "run_code_docker",
    "tool_install_package", "docker_prune_resources",
})
_NETWORK_CAPABILITY_TOOLS = frozenset({
    "web_search", "fetch_url", "web_fetch", "web_click", "web_screenshot",
    "web_select", "web_type", "web_navigate", "check_service",
})
_CONTAINER_CAPABILITY_TOOLS = frozenset({
    "pwn_container", "run_code_docker", "tool_install_package",
    "docker_prune_resources",
})


def _builtin_tool_metadata(name: str) -> tuple[TrustBoundaryKind, frozenset[str]]:
    capabilities = {"read"}
    trust = TrustBoundaryKind.LOCAL
    if name in _SHELL_CAPABILITY_TOOLS:
        capabilities.add("shell")
        trust = TrustBoundaryKind.HOST_SHELL
    if name in _MUTATING_CAPABILITY_TOOLS:
        capabilities.add("mutating")
    if name in _NETWORK_CAPABILITY_TOOLS:
        capabilities.add("network")
        trust = TrustBoundaryKind.BROWSER_NETWORK
    if name in _CONTAINER_CAPABILITY_TOOLS:
        capabilities.add("container")
        trust = TrustBoundaryKind.CONTAINER_EXEC
    return trust, frozenset(capabilities)


for _registered_spec in _TOOL_REGISTRY.snapshot_specs():
    _trust, _capabilities = _builtin_tool_metadata(_registered_spec.name)
    _TOOL_REGISTRY.register(ToolSpec(
        name=_registered_spec.name,
        handler=_registered_spec.handler,
        schema=_registered_spec.schema,
        phases=_registered_spec.phases,
        trust=_trust,
        capabilities=_capabilities,
    ))
# Legacy compatibility exports. New registration paths should use _TOOL_REGISTRY.
TOOL_MAP: dict = {}
TOOLS_SCHEMA: list = []
_refresh_legacy_tool_globals()

# switch_phase: global routing tool, always attached regardless of phase filter.
# Actual execution is intercepted in run_turn; the TOOL_MAP entry is a fallback.
_SWITCH_PHASE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "switch_phase",
        "description": (
            "Call this tool to switch work phases when the current phase's tools "
            "are insufficient or this phase is complete.\n"
            "After switching, the system loads the next specialized tool set. "
            "Choose the target phase based on task needs.\n"
            f"Available phases: {', '.join(AGENT_PHASES.keys())}\n"
            "  RECON    - reconnaissance: environment checks, directory browsing, initial binary analysis\n"
            "  VULN_DEV - vulnerability development: offsets, disassembly, ROP/libc analysis\n"
            "  EXPLOIT  - exploitation: write exploits, dynamic debugging, interactive validation\n"
            "  WEB_PEN  - web penetration: Scrapling anti-bot fetch, adaptive selectors, browser automation\n"
            "  GENERAL  - general fallback: file operations, networking, fallback scenarios"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phase": {
                    "type": "string",
                    "enum": list(AGENT_PHASES.keys()),
                    "description": "Target phase name; must be one of the available phases above.",
                },
                "reason": {
                    "type": "string",
                    "description": "One-sentence explanation of why the phase switch is needed.",
                },
            },
            "required": ["phase"],
        },
    },
}

_TOOL_REGISTRY.register(ToolSpec("switch_phase", lambda a: (
    f"[switch_phase] Phase switch request received; target: {a.get('phase', '?')}. "
    "This message should not appear; run_turn should intercept it."
), _SWITCH_PHASE_SCHEMA, frozenset({"*"})))

# bump_skill tool: GSA feedback loop.
def tool_bump_skill(args: dict) -> str:
    """
    Increase a GSA skill's hit count and refresh its timestamp after using it
    successfully. Call this proactively after <verify> passes.
    """
    skill_name = args.get("skill_name", "").strip()
    if not skill_name:
        return "ERROR: skill_name cannot be empty"
    try:
        ok, msg = bump_skill(skill_name)
        return msg
    except Exception as e:
        return f"ERROR: bump_skill failed: {e}"

_BUMP_SKILL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "bump_skill",
        "description": (
            "GSA feedback-loop tool. When you successfully use a skill from "
            "global_skills.md to solve a problem, call this to increment hits, "
            "refresh last_used, and improve confidence. Frequently validated "
            "skills receive higher priority in future retrieval.\n"
            "Call it after <verify> passes and before GSA archiving."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type":        "string",
                    "description": "Exact skill name: the ## heading text without the '## ' prefix.",
                },
            },
            "required": ["skill_name"],
        },
    },
}

_TOOL_REGISTRY.register(ToolSpec(
    "bump_skill", tool_bump_skill, _BUMP_SKILL_SCHEMA,
    frozenset({"GENERAL", "WEB_PEN"}), capabilities=frozenset({"mutating"}),
))

# P0: audit_payload tool for defensive auditing.
# Dangerous tools that require audit.
_AUDITED_TOOLS = {"run_code", "run_shell", "run_interactive"}


def tool_audit_payload(args: dict) -> str:
    """
    Pre-flight payload audit tool.
    Query historical failures for a tool and return warnings and suggestions.
    """
    tool_name   = args.get("tool_name", "").strip()
    payload_hint = args.get("payload_preview", "").strip()

    if not tool_name:
        return "ERROR: tool_name cannot be empty"

    rows = check_failure(tool_name, args_keywords=payload_hint, limit=3)
    if not rows:
        return f"✓ Audit passed: no historical failures for {tool_name}."

    warning = format_failures_for_prompt(rows)
    return (
        f"⚠ Audit warning: {tool_name} has {len(rows)} historical failure records\n\n"
        f"{warning}\n\n"
        "Suggestion: modify the payload or try a different approach before retrying."
    )


_AUDIT_PAYLOAD_SCHEMA = {
    "type": "function",
    "function": {
        "name": "audit_payload",
        "description": (
            "Pre-flight payload audit tool. Before dangerous run_code / run_shell / "
            "run_interactive operations, call this to check similar historical failures. "
            "If matches exist, the system returns failure reasons and modification advice.\n"
            "Use before exploit scripts, shellcode execution, or GDB debugging."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Target tool name: run_code / run_shell / run_interactive.",
                },
                "payload_preview": {
                    "type": "string",
                    "description": "Payload or argument summary for fuzzy matching historical failures.",
                },
            },
            "required": ["tool_name"],
        },
    },
}

_TOOL_REGISTRY.register(ToolSpec(
    "audit_payload", tool_audit_payload, _AUDIT_PAYLOAD_SCHEMA,
    frozenset({"*"}), capabilities=frozenset({"read"}),
))

# P6: search_skills tool for automated exploit-chain retrieval.
def tool_search_skills(args: dict) -> str:
    """
    Search local skill packs by detected target fingerprint such as Fastjson,
    Shiro, or Log4j. Return matching packs and script execution guidance.
    """
    query = args.get("query", "").strip()
    if not query:
        return "ERROR: query cannot be empty. Provide a target fingerprint or keyword such as 'Fastjson' or 'Shiro'."

    try:
        packs = _skill_scanner.match(query, top_k=int(args.get("top_k", 3)))
    except Exception as e:
        return f"ERROR: search_skills failed: {e}"

    if not packs:
        return f"No skill packs matched '{query}'. Try: 1. /skillpack rescan  2. Check the skills/ directory."

    # Use format_for_prompt for full guidance, including script execution commands.
    result = _skill_scanner.format_for_prompt(packs)

    # Concise user-mode output.
    if _user_mode():
        names = [p.get("name", "?") for p in packs]
        print(c(GREEN, f"  🚀 [P6] Matched {len(packs)} skill packs: {', '.join(names)}"))

    return result


_SEARCH_SKILLS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_skills",
        "description": (
            "P6 automated exploit chain: search local skill packs by target fingerprint.\n"
            "After reconnaissance detects a web framework fingerprint such as "
            "Fastjson/Shiro/Log4j/Spring, call this tool to retrieve matching "
            "automation scripts and guides.\n"
            "Results include pack name, description, guide.md path, available "
            "scripts, and execution commands.\n"
            "You must try returned scripts first; do not write long payloads before attempting them."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type":        "string",
                    "description": "Target fingerprint or keyword, e.g. 'Fastjson', 'Shiro', 'log4j', 'spring', 'sql injection'.",
                },
                "top_k": {
                    "type":        "integer",
                    "description": "Maximum number of skill packs to return; default 3.",
                    "default":     3,
                },
            },
            "required": ["query"],
        },
    },
}

_TOOL_REGISTRY.register(ToolSpec(
    "search_skills", tool_search_skills, _SEARCH_SKILLS_SCHEMA,
    frozenset({"RECON", "GENERAL", "WEB_PEN"}), capabilities=frozenset({"read"}),
))

def _try_load_delegate():
    try:
        from tools.delegate_tool import tool_delegate_task, DELEGATE_SCHEMA
        if (
            not callable(tool_delegate_task)
            or not isinstance(DELEGATE_SCHEMA, dict)
            or DELEGATE_SCHEMA.get("function", {}).get("name") != "delegate_task"
        ):
            return
        _TOOL_REGISTRY.register(ToolSpec(
            "delegate_task", tool_delegate_task, DELEGATE_SCHEMA,
            frozenset({"*"}), TrustBoundaryKind.DELEGATE,
            frozenset({"delegate", "mutating"}),
        ))
    except ImportError:
        pass

_try_load_delegate()
_refresh_legacy_tool_globals()

# ════════════════════════════════════════════════════════
# External MCP tool attachment point.
# Called once after init_db and before AgentSession creation.
# ════════════════════════════════════════════════════════

def attach_external_mcp_tools() -> None:
    """
    Merge external MCP tools discovered by mcp_client_manager into TOOL_MAP,
    TOOLS_SCHEMA, and AGENT_PHASES. If no config exists or all servers fail to
    start, this function is a no-op.
    """
    try:
        from core.mcp_client_manager import init_external_mcp
    except ImportError:
        return  # silently skip when MCP support is not installed
    from config import AGENT_PHASES

    mgr = init_external_mcp()
    if mgr is None:
        return

    # 1. Adapt complete MCP definitions at the same registry seam as built-ins.
    handlers = mgr.build_pawnlogic_handlers()
    phase_mapping = mgr.get_phase_mapping()
    for schema in mgr.build_pawnlogic_schemas():
        name = schema.get("function", {}).get("name")
        handler = handlers.get(name) if name else None
        if not name or handler is None:
            continue
        phase = phase_mapping.get(name, "GENERAL")
        if phase not in AGENT_PHASES:
            phase = "GENERAL"
        _TOOL_REGISTRY.register(ToolSpec(
            name=name,
            handler=handler,
            schema=schema,
            phases=frozenset({phase}),
            trust=TrustBoundaryKind.BROWSER_NETWORK,
            capabilities=frozenset({"external", "network"}),
        ))
    _refresh_legacy_tool_globals()

    # 2. Phase ownership: expose external tools in configured phase lists.
    for prefixed_name, phase in mgr.get_phase_mapping().items():
        target = phase if phase in AGENT_PHASES else "GENERAL"
        if phase != target:
            logger.warning(
                f"[MCP] unknown phase '{phase}' for '{prefixed_name}' → fallback to GENERAL"
            )
        bucket = AGENT_PHASES.setdefault(target, [])
        if prefixed_name not in bucket:
            bucket.append(prefixed_name)


def detach_external_mcp_tools() -> None:
    """Shut down background threads and external MCP subprocesses idempotently."""
    try:
        from core.mcp_client_manager import shutdown_external_mcp
        shutdown_external_mcp()
    except Exception:  # noqa: BLE001
        pass  # never raise from shutdown/finally paths
    finally:
        _refresh_legacy_tool_globals()


# ════════════════════════════════════════════════════════
# Change [1]: _PLAN_REQUIRED_MSG -> softer coaching tone.
# It is no longer "ERROR: Rule Violation"; it is a notice printed only to the
# terminal and not injected into conversation context.
# ════════════════════════════════════════════════════════

_MAX_CONCURRENT_TOOLS  = 3
_MAX_SOFT_CORRECTIONS  = 2   # max soft intercepts; tools still run and receive correction signal
_MAX_HARD_KILLS        = 1   # hard-stop threshold after soft intercepts are exhausted

# ════════════════════════════════════════════════════════
# P1: time-aware scheduling constants for URGENT_MODE.
# ════════════════════════════════════════════════════════

_URGENT_THRESHOLD_SEC = 30   # trigger URGENT_MODE when remaining time is below 30s

# Fast model candidates used for automatic switching under time pressure.
_URGENT_MODEL_CANDIDATES = [
    "ds-v4-flash",
    "claude-haiku",
    "gpt-4.1",
]

_LOGIC_REFRESH_INTERVAL = 20   # Trigger a phase summary every 20 iterations.

_URGENT_SIGNAL = (
    "[SYSTEM: URGENT_MODE — time budget nearly exhausted]\n"
    "Time remaining is critically low. You MUST:\n"
    "  1. SKIP <plan> blocks — invoke tools directly.\n"
    "  2. Use the SHORTEST possible answers.\n"
    "  3. Do NOT invoke GSA / bump_skill / audit_payload.\n"
    "  4. Focus ONLY on the core deliverable.\n"
    "  5. If a tool call fails, do NOT retry — report partial results.\n"
)

# PLAN_MISSING signal.
# Injected after tool results rather than as a user message, keeping attention
# close to the current reasoning layer and improving correction quality.
_PLAN_MISSING_SIGNAL = (
    "[SYSTEM: PLAN_MISSING — your last tool call was intercepted by the executor]\n"
    "The tool executor requires a <plan> block to authorize tool usage.\n"
    "Recovery: output <plan><intent>your original intent</intent></plan> "
    "then re-emit your tool call. Do NOT apologize or repeat previous text."
)

_is_plan_exempt = _plan_guard.is_plan_exempt
_tool_call_missing_plan = _plan_guard.tool_call_missing_plan

# ════════════════════════════════════════════════════════
# GSA helper: read the global_skills.md table of contents.
# ════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════
# P6.5: Skill engine using SkillScanner folder-pack mode.
# ════════════════════════════════════════════════════════

from core.skill_manager import SkillScanner
_skill_scanner = SkillScanner(SKILLS_DIR)


def _load_skills_toc() -> str:
    try:
        from core.gsa import load_toc
        return load_toc(max_lines=80)
    except Exception:
        pass
    try:
        if not GLOBAL_SKILLS_PATH.exists():
            return "(global_skills.md has not been created; the agent may create the first category during archiving)"
        lines    = GLOBAL_SKILLS_PATH.read_text(encoding="utf-8").splitlines()[:80]
        headings = [l for l in lines if l.startswith("#")]
        return "\n".join(headings) if headings else "(global_skills.md has no categories yet)"
    except Exception:
        return "(failed to read global_skills.md)"

class TurnInterrupted(KeyboardInterrupt):
    """Raised when an in-flight turn is interrupted and should be rolled back."""

# ════════════════════════════════════════════════════════
# XML plan renderer.
# ════════════════════════════════════════════════════════

_TAG_PAIRS = [
    ("<plan>",       "</plan>"),
    ("<action>",     "</action>"),
    ("<verify>",     "</verify>"),
    # Additional subtags.
    ("<intent>",     "</intent>"),
    ("<tool>",       "</tool>"),
    ("<why>",        "</why>"),
    ("<next>",       "</next>"),
    ("<anchor>",     "</anchor>"),
    ("<correction>", "</correction>"),
]
_ALL_TAGS = [t for pair in _TAG_PAIRS for t in pair]
_TAG_MAX  = max(len(t) for t in _ALL_TAGS) + 2

# Subtag prefix labels and color mapping.
_SUBTAG_OPEN: dict = {
    "<action>":     (GRAY,          "  📋 "),
    "<verify>":     (CYAN,          "  🔬 Verify: "),
    "<intent>":     (MAGENTA,       "  🎯 Intent: "),
    "<tool>":       (CYAN,          "  🔧 Tool: "),
    "<why>":        (GRAY,          "  💡 Why: "),
    "<next>":       (GRAY + DIM,    "  ⏭  Next: "),
    "<anchor>":     (YELLOW,        "  ⚓ Anchor:\n"),
    "<correction>": (YELLOW,        ""),          # silent flag, no display
}

class _PlanRenderer:
    def __init__(self):
        self.in_plan       = False
        self.in_action     = False
        self.in_verify     = False
        self.in_intent     = False
        self.in_tool_tag   = False
        self.in_why        = False
        self.in_next       = False
        self.in_anchor     = False
        self.in_correction = False
        self.tail = ""

    def _in_subtag(self) -> bool:
        return (self.in_action or self.in_verify or self.in_intent
                or self.in_tool_tag or self.in_why or self.in_next
                or self.in_anchor or self.in_correction)

    def _color(self, text: str) -> str:
        if self.in_verify:     return c(CYAN,       text)
        if self.in_intent:     return c(MAGENTA,    text)
        if self.in_tool_tag:   return c(CYAN,       text)
        if self.in_why:        return c(GRAY,        text)
        if self.in_next:       return c(GRAY + DIM, text)
        if self.in_anchor:     return c(YELLOW,      text)
        if self.in_correction: return ""               # never display <correction> value
        if self.in_action:     return c(GRAY,        text)
        return c(GRAY + DIM,   text)

    def _set_subtag(self, tag: str, val: bool):
        if tag in ("<action>",     "</action>"):     self.in_action     = val
        elif tag in ("<verify>",   "</verify>"):     self.in_verify     = val
        elif tag in ("<intent>",   "</intent>"):     self.in_intent     = val
        elif tag in ("<tool>",     "</tool>"):       self.in_tool_tag   = val
        elif tag in ("<why>",      "</why>"):        self.in_why        = val
        elif tag in ("<next>",     "</next>"):       self.in_next       = val
        elif tag in ("<anchor>",   "</anchor>"):     self.in_anchor     = val
        elif tag in ("<correction>","</correction>"): self.in_correction = val

    def feed(self, chunk: str) -> str:
        self.tail += chunk
        output = ""
        while self.tail:
            if "<" not in self.tail:
                if not self.in_plan: output += self.tail
                else:
                    col = self._color(self.tail)
                    if col: sys.stdout.write(col); sys.stdout.flush()
                self.tail = ""; break

            lt = self.tail.find("<")
            if lt > 0:
                safe = self.tail[:lt]
                if not self.in_plan: output += safe
                else:
                    col = self._color(safe)
                    if col: sys.stdout.write(col); sys.stdout.flush()
                self.tail = self.tail[lt:]; continue

            ep = len(self.tail); et = None
            for tag in _ALL_TAGS:
                pos = self.tail.find(tag)
                if pos != -1 and pos < ep: ep = pos; et = tag

            if not et:
                if len(self.tail) > _TAG_MAX:
                    if not self.in_plan: output += self.tail[0]
                    else: sys.stdout.write(self._color(self.tail[0])); sys.stdout.flush()
                    self.tail = self.tail[1:]
                else: break
            elif not self.in_plan:
                output += self.tail[:ep]; self.tail = self.tail[ep:]
                if et == "<plan>":
                    sys.stdout.write(c(GRAY + DIM, "\n  💭 [plan start]\n")); sys.stdout.flush()
                    self.in_plan = True; self.tail = self.tail[len("<plan>"):]
                else:
                    output += self.tail[:len(et)]; self.tail = self.tail[len(et):]
            else:
                # inside <plan> — handle open and close subtags
                col = self._color(self.tail[:ep])
                if col: sys.stdout.write(col); sys.stdout.flush()
                self.tail = self.tail[ep:]
                if et == "</plan>":
                    sys.stdout.write(c(GRAY, "\n  [plan end]\n")); sys.stdout.flush()
                    self.in_plan = self.in_action = self.in_verify = False
                    self.in_intent = self.in_tool_tag = self.in_why = False
                    self.in_next = self.in_anchor = self.in_correction = False
                    self.tail = self.tail[len("</plan>"):]
                elif et in _SUBTAG_OPEN:
                    # opening subtag
                    color, prefix = _SUBTAG_OPEN[et]
                    if prefix:
                        sys.stdout.write(c(color, prefix)); sys.stdout.flush()
                    self._set_subtag(et, True)
                    self.tail = self.tail[len(et):]
                elif et.startswith("</"):
                    # closing subtag
                    self._set_subtag(et, False)
                    self.tail = self.tail[len(et):]
                    sys.stdout.write("\n"); sys.stdout.flush()
                else:
                    self.tail = self.tail[len(et):]
        return output

    def flush(self) -> str:
        leftover = ""
        if self.in_plan: sys.stdout.write(c(GRAY + DIM, self.tail)); sys.stdout.flush()
        else: leftover = self.tail
        self.tail = ""
        self.in_plan = self.in_action = self.in_verify = False
        self.in_intent = self.in_tool_tag = self.in_why = False
        self.in_next = self.in_anchor = self.in_correction = False
        return leftover

# ════════════════════════════════════════════════════════
# State.md
# ════════════════════════════════════════════════════════

STATE_FILENAME = ".pawn_state.md"

def _load_state_md(cwd: str) -> str:
    p = Path(cwd) / STATE_FILENAME
    if p.exists() and p.is_file():
        try: return p.read_text(encoding="utf-8").strip()
        except Exception: pass
    return ""

# ════════════════════════════════════════════════════════
# AgentSession
# ════════════════════════════════════════════════════════

class AgentSession:
    def __init__(self):
        self.session_id  = _gen_id()
        self.model_alias = DEFAULT_MODEL
        self.messages: list = []
        self.cwd         = os.getcwd()
        self.workspace_dir = stable_workspace_dir(self.session_id)
        self.runtime_context = RuntimeContext.from_current(
            cwd=self.cwd,
            workspace_dir=self.workspace_dir,
        )
        self._sync_runtime_context()
        self.current_phase = "RECON"   # initial MoE phase
        init_db()
        # P1: time-aware scheduling state. Must exist before _reset_system_prompt.
        self._turn_start_time        = 0.0
        self._time_budget_sec        = 0   # 0 = unlimited
        self._urgent_mode            = False
        self._save_lock = threading.Lock()
        self._naming_lock = threading.Lock()
        self._naming_done = False
        self._naming_attempted_at = 0.0
        # Session auto-naming: count completed turns; threshold is 2.
        self._turn_count = 0
        # Dynamic workspace swap: protect the three-step rename, reverse
        # symlink, and pointer switch with a short local-FS-only lock.
        self._workspace_swap_lock = threading.Lock()
        # ── Usage & audit counters (cumulative across all turns) ──
        self.total_prompt_tokens     = 0
        self.total_completion_tokens = 0
        self.total_tool_calls        = 0
        # Per-turn snapshots, reset at start of each run_turn
        self._turn_prompt_tokens     = 0
        self._turn_completion_tokens = 0
        self._turn_tool_calls        = 0
        self._runtime_metrics = RuntimeMetrics()
        # P6.5: matched skill-pack cache.
        self._loaded_skill_packs: list = []
        # Sliding window + history summary state.
        self._history_summary: str = ""          # current effective history summary
        self._summary_turn_count: int = 0        # turn count when summary was last generated
        # Call last because it depends on all attributes above.
        self._reset_system_prompt()

    def _sync_runtime_context(self) -> None:
        """Keep this session's RuntimeContext and legacy tool pointers aligned."""
        ctx = getattr(self, "runtime_context", None)
        if ctx is None:
            ctx = RuntimeContext.from_current(
                cwd=self.cwd,
                workspace_dir=self.workspace_dir,
            )
            self.runtime_context = ctx
        else:
            ctx.update_paths(cwd=self.cwd, workspace_dir=self.workspace_dir)
        ctx.sync_legacy_state()
        sync_runtime_context(ctx)

    def _time_remaining(self) -> float:
        """Return seconds remaining for the current turn; inf when budget is 0."""
        if self._time_budget_sec <= 0:
            return float("inf")
        elapsed = time.monotonic() - self._turn_start_time
        return max(0.0, self._time_budget_sec - elapsed)

    def undo(self, n: int = 1) -> tuple[int, str]:
        """Physically remove trailing user/assistant message pairs, preserving pinned messages.

        Returns ``(removed_count, last_user_text)``. ``last_user_text`` is used as
        the default prompt value when Ctrl+C rolls the prompt back for editing.
        """
        removed = 0
        last_user_text = ""
        for _ in range(n):
            # Scan backward from the tail, skipping system and pinned messages.
            while self.messages:
                tail = self.messages[-1]
                if tail.get("role") == "system" or tail.get("_pinned"):
                    break
                # Remember the user text being removed.
                if tail.get("role") == "user":
                    last_user_text = str(tail.get("content") or "")
                self.messages.pop()
                removed += 1
                # If an assistant was removed, also remove the matching user message.
                if tail.get("role") == "assistant":
                    while self.messages:
                        prev = self.messages[-1]
                        if prev.get("role") == "system" or prev.get("_pinned"):
                            break
                        if prev.get("role") == "user":
                            last_user_text = str(prev.get("content") or "")
                            self.messages.pop()
                            removed += 1
                            break
                        elif prev.get("role") == "assistant":
                            # Consecutive assistant messages can happen across tool loops.
                            self.messages.pop()
                            removed += 1
                        else:
                            break
                    break
                # If a user message was removed, this undo round is complete.
                elif tail.get("role") == "user":
                    break
        return removed, last_user_text

    # ════════════════════════════════════════════════════
    # Dynamic workspace swap (rename + reverse symlink + atomic pointer update)
    # ════════════════════════════════════════════════════

    def _swap_workspace_dir(self, slug: str) -> tuple[str, str]:
        """Rename ``session_<id>/`` → ``<slug>/`` under ``~/.pawnlogic/workspace``,
        create a reverse symlink so pre-swap absolute paths still resolve,
        then atomically update ``self.workspace_dir`` and the file-tool
        runtime pointers.

        Collision handling mirrors ``create_workspace_alias``:
        try ``<slug>``, then ``<slug>-<id_tail>``, then ``<slug>-<id_tail>-N``.

        Concurrency: the whole operation is guarded by
        ``self._workspace_swap_lock`` — no other thread can interleave a
        second swap. File writes on other threads read the pointer atomically
        (CPython list-index assignment) and paths resolve through the reverse
        symlink even if they captured the pre-swap path.

        Returns ``(final_dirname, new_absolute_path)``. On failure, keeps
        the old state intact and returns ``("", "")``.
        """
        from config import WORKSPACE_DIR, WORKSPACE_ROOT

        with self._workspace_swap_lock:
            # Keep boundary validation broad while forcing the final target narrow:
            #   · boundary_root = ~/.pawnlogic allows sessions under archive/,
            #     workspace/, and sibling directories to pass relative_to checks.
            #   · workspace_target = ~/.pawnlogic/workspace forces the final slug
            #     back into the sandbox so sessions do not remain in archive.
            boundary_root    = Path(WORKSPACE_ROOT).expanduser().resolve()
            workspace_target = Path(WORKSPACE_DIR).expanduser().resolve()
            workspace_target.mkdir(parents=True, exist_ok=True)

            current_path = Path(self.workspace_dir).expanduser().resolve()
            # Defense: only swap current workspaces under ~/.pawnlogic, including archive/.
            try:
                current_path.relative_to(boundary_root)
            except ValueError:
                logger.warning(
                    "Workspace swap aborted: current_path outside boundary | "
                    "current={} boundary={}",
                    current_path, boundary_root,
                )
                return "", ""

            # If already named and placed correctly, return the current state.
            if current_path.name == slug and current_path.parent == workspace_target:
                return current_path.name, str(current_path)

            # Collision probing: slug -> slug-<id_tail> -> slug-<id_tail>-N.
            id_tail = self.session_id[-4:] if len(self.session_id) >= 4 else self.session_id
            candidates = [slug, f"{slug}-{id_tail}"]
            candidates.extend(f"{slug}-{id_tail}-{i}" for i in range(2, 100))

            final_name = ""
            for cand in candidates:
                target = workspace_target / cand
                if not target.exists() and not target.is_symlink():
                    final_name = cand
                    break
            if not final_name:
                logger.warning(
                    "Workspace swap aborted: 100 candidates exhausted | slug={}",
                    slug,
                )
                return "", ""

            new_path = workspace_target / final_name
            try:
                # 1. Rename the real directory. POSIX rename is atomic on one FS.
                os.rename(str(current_path), str(new_path))
            except OSError as exc:
                logger.warning(
                    "Workspace rename failed | from={} to={} exc={!r}",
                    current_path, new_path, exc,
                )
                return "", ""

            # 2. Reverse fallback symlink: old path -> new <slug>, when applicable.
            try:
                old_name = current_path.name
                if current_path.parent == workspace_target:
                    old_link = workspace_target / old_name
                    if not old_link.exists() and not old_link.is_symlink():
                        # Use a relative symlink so the workspace tree stays movable.
                        os.symlink(final_name, str(old_link))
                # archive -> workspace moves do not benefit from a reverse symlink.
            except OSError as exc:
                # Reverse symlink failure is non-fatal after rename succeeds.
                logger.warning(
                    "Reverse symlink failed (non-fatal) | old={} new={} exc={!r}",
                    current_path.name, final_name, exc,
                )

            # 3. Atomic pointer update; CPython list-index assignment is atomic.
            new_abs = str(new_path.resolve())
            self.workspace_dir = new_abs
            self._sync_runtime_context()

            logger.info(
                "Workspace swapped | session={} {} → {} | path={}",
                self.session_id[:8], current_path.name, final_name, new_abs,
            )
            return final_name, new_abs

    def _print_naming_banner(
        self, title: str, slug: str, final_dirname: str, new_abs: str,
    ) -> None:
        """Pretty-print the auto-naming result to stdout.

        User mode prints one concise line; debug mode prints full paths.
        Any error is swallowed (UI never blocks naming persistence).
        """
        try:
            if _user_mode():
                if final_dirname:
                    print(c(CYAN, f"  🏷  Session auto-named -> {title} · Workspace: {final_dirname}/"))
                else:
                    print(c(CYAN, f"  🏷  Session auto-named -> {title}"))
            else:
                id_tail = self.session_id[-8:] if len(self.session_id) >= 8 else self.session_id
                if final_dirname and new_abs:
                    print(c(MAGENTA, f"\n  🏷  [Auto-Name] session_{id_tail} → {final_dirname}"))
                    print(c(GRAY,    f"      title      : {title}"))
                    print(c(GRAY,    f"      slug       : {slug}"))
                    print(c(GRAY,    f"      workspace  : {new_abs}"))
                else:
                    print(c(YELLOW,  f"\n  ⚠ [Auto-Name] Name saved, but workspace swap failed (kept session_{id_tail}/)"))
                    print(c(GRAY,    f"      title      : {title}"))
                    print(c(GRAY,    f"      slug       : {slug}"))
        except Exception:
            pass

    @property
    def model(self) -> dict:
        # Defensive .get(): stale aliases restored from old sessions fall back to
        # DEFAULT_MODEL instead of crashing with KeyError.
        return MODELS.get(self.model_alias, MODELS[DEFAULT_MODEL])

    def _reset_system_prompt(self, knowledge_query: str = ""):
        result = build_session_prompt(
            cfg=_dynamic_config(),
            cwd=self.cwd,
            current_phase=self.current_phase,
            model_alias=self.model_alias,
            model=self.model,
            urgent_mode=self._urgent_mode,
            knowledge_query=knowledge_query,
            version=VERSION,
            global_skills_path=GLOBAL_SKILLS_PATH,
            agent_phases=AGENT_PHASES,
            load_state_md=_load_state_md,
            load_skills_toc=_load_skills_toc,
            search_knowledge=search_knowledge,
            format_knowledge_for_prompt=format_knowledge_for_prompt,
            load_relevant_skills=load_relevant_skills,
            skill_scanner=_skill_scanner,
        )
        if result.loaded_skill_packs is not None:
            self._loaded_skill_packs = result.loaded_skill_packs

        if self.messages and self.messages[0]["role"] == "system":
            self.messages[0]["content"] = result.prompt
        else:
            self.messages.insert(0, {"role": "system", "content": result.prompt})

    # ════════════════════════════════════════════════════
    # Sliding window context construction with history summary.
    # ════════════════════════════════════════════════════

    def _count_turns(self, msgs: list) -> list[tuple[int, int]]:
        """Group msgs[1:] into iteration units and return [(start_idx, end_idx), ...].

        An iteration unit is one user message plus all following assistant/tool
        messages until the next user message. The system message at index 0 is
        not included in grouping.
        """
        turns: list[tuple[int, int]] = []
        i = 1  # skip system
        while i < len(msgs):
            if msgs[i].get("role") == "user":
                start = i
                i += 1
                # Absorb following assistant/tool messages until the next user or end.
                while i < len(msgs) and msgs[i].get("role") != "user":
                    i += 1
                turns.append((start, i))
            else:
                i += 1
        return turns

    def _maybe_update_summary(self, msgs: list, current_turn_count: int) -> None:
        """Synchronously refresh history summary when turn thresholds are reached.

        The summary covers only old history outside the sliding window and never
        includes the latest N turns.
        """
        cfg = _dynamic_config()
        threshold   = cfg.get("ctx_summary_threshold", 8)
        sliding     = cfg.get("ctx_sliding_turns", 5)
        refresh_gap = max(threshold // 2, 3)

        if current_turn_count < threshold:
            return
        if current_turn_count - self._summary_turn_count < refresh_gap:
            return

        turns = self._count_turns(msgs)
        # Summarize only old turns outside the sliding window.
        old_turns = turns[:-sliding] if len(turns) > sliding else []
        if not old_turns:
            return

        # Collect message text to summarize.
        lines: list[str] = []
        for start, end in old_turns:
            for m in msgs[start:end]:
                role    = m.get("role", "")
                content = str(m.get("content") or "")[:600]
                if role == "tool":
                    lines.append(f"[Tool Output]: {content}")
                elif role == "assistant":
                    # Keep only non-plan text by stripping XML tags.
                    import re as _re
                    clean = _re.sub(r"<[^>]+>", " ", content).strip()[:400]
                    if clean:
                        lines.append(f"[Assistant]: {clean}")
                elif role == "user" and not content.startswith("[SYSTEM:") and not content.startswith("[System]"):
                    lines.append(f"[User]: {content[:200]}")

        if not lines:
            return

        history_text = "\n".join(lines)

        summary_prompt = (
            "You are a security research assistant. Summarize the following agent conversation history "
            "into a concise background context (≤400 words). "
            "You MUST preserve ALL of the following if present:\n"
            "  • Stack overflow offset / buffer size (e.g. offset=72)\n"
            "  • Canary status and bypass method\n"
            "  • PIE/ASLR status, libc base address, binary base address\n"
            "  • PLT/GOT addresses of key functions (e.g. puts@plt=0x401030)\n"
            "  • Vulnerability type and location (e.g. gets() in vuln() → stack overflow)\n"
            "  • ROP gadgets found (e.g. pop rdi; ret @ 0x4011ab)\n"
            "  • Paths already tried and ruled out (e.g. shellcode injection failed due to NX)\n"
            "  • Current exploit stage and what remains\n"
            "Output ONLY the summary text, no headers, no markdown.\n\n"
            f"--- HISTORY ---\n{history_text}\n--- END ---"
        )

        # Pick a lightweight summarization model, reusing NAMING_MODEL_CHAIN.
        from core.naming import pick_naming_model
        try:
            summary_alias = pick_naming_model(self.model_alias)
        except Exception:
            summary_alias = self.model_alias

        try:
            summary_chunks: list[str] = []
            for delta in stream_request(
                [
                    {"role": "system", "content": "You are a concise technical summarizer."},
                    {"role": "user",   "content": summary_prompt},
                ],
                summary_alias,
                tools_schema=None,
                max_tokens=600,
            ):
                choices = delta.get("choices") or []
                if not choices:
                    continue
                chunk = (choices[0].get("delta") or {}).get("content") or ""
                if chunk:
                    summary_chunks.append(chunk)

            summary_text = "".join(summary_chunks).strip()
            if summary_text:
                self._history_summary = summary_text
                self._summary_turn_count = current_turn_count
                logger.info(
                    "[PawnLogic] Context pruning triggered. Summary updated. "
                    "Current dynamic window turns: {} | model={}",
                    sliding, summary_alias,
                )
                if _debug_mode():
                    print(c(CYAN,
                        f"  🗜  [Context Pruning] History summary updated (kept latest {sliding} turns)"
                    ))
        except Exception as exc:
            logger.debug(
                "History summary generation failed (non-fatal) | exc={!r}", exc
            )

    def _build_api_messages(self) -> list:
        """Build the message list sent to the LLM as a sliding-window view.

        Does not mutate the original ``self.messages`` list; returns a trimmed copy.

        Structure:
          [0] system prompt
          [1..2] original task goal (first 1-2 user+assistant turns, never trimmed)
          [3] assistant: history summary block, when present
          [4..] latest ctx_sliding_turns full iterations
        """
        msgs = self.messages
        if len(msgs) <= 1:
            return list(msgs)

        cfg     = _dynamic_config()
        sliding = cfg.get("ctx_sliding_turns", 5)

        turns = self._count_turns(msgs)
        total_turns = len(turns)

        # No trimming needed when turn count is below the threshold.
        if total_turns <= sliding + 2:
            return _drop_dangling_tool_call_messages(msgs)

        # Anchor: always keep the first 2 turns as the task goal.
        anchor_end = turns[1][1] if len(turns) >= 2 else (turns[0][1] if turns else 1)
        anchor_msgs = msgs[:anchor_end]  # system + first 2 turns

        # Sliding window: latest N turns.
        window_start_idx = turns[-sliding][0] if total_turns >= sliding else turns[0][0]

        # Assemble.
        result = list(anchor_msgs)

        if self._history_summary:
            result.append({
                "role":    "assistant",
                "content": f"📝 [History Summary — earlier iterations compressed]\n{self._history_summary}",
                "_pinned": True,
            })

        # Append sliding-window messages and skip the middle span.
        for i, m in enumerate(msgs[anchor_end:], start=anchor_end):
            if i >= window_start_idx:
                result.append(m)

        return _drop_dangling_tool_call_messages(result)

    # ════════════════════════════════════════════════════
    # Module 2: auto-intuition retrieval helper.
    # ════════════════════════════════════════════════════

    @staticmethod
    def _auto_intuitive_search(query: str) -> str:
        try:
            rows = search_knowledge(query, limit=3)
            if not rows:
                return ""
            lines = [
                f"\n[🧠 Auto-Intuition — knowledge search for '{query}']\n"
                f"  Found {len(rows)} relevant entries from past sessions:\n"
            ]
            for row in rows:
                topic   = row.get("topic", "")
                snippet = str(row.get("content", ""))[:200]
                src     = row.get("source_session", "")
                lines.append(
                    f"  • [{topic}]  {snippet}{'...' if len(str(row.get('content','')))>200 else ''}\n"
                    f"    (from session: {src})\n"
                )
            lines.append(
                "  → If the above entries solve your search, stop directory traversal.\n"
            )
            return "".join(lines)
        except Exception:
            return ""

    # ════════════════════════════════════════════════════
    # Hybrid v2 dual-protocol parser.
    # ════════════════════════════════════════════════════

    def _extract_calls(self, text_buf: str) -> list:
        """
        Hybrid v2 dual-protocol parser.

        Priority:
          1. XML <call name="...">...</call>   — no escaping, works with multiline text
          2. JSON <tool_call>{...}</tool_call> — compact, for single-line ASCII args

        Returns:
          [{"name": str, "args": dict, "_source": "xml"|"json"}, ...]

        Tolerance:
          · If XML misses </call>, parse through the end of the string.
          · JSON uses strict=False to allow real newline characters in arguments.
        """
        def on_partial_xml() -> None:
            print(
                c(
                    GRAY,
                    "  ⚙ [XML Parser] Unclosed </call> detected; tolerant completion enabled",
                )
            )

        def on_dirty_json_rescued() -> None:
            print(c(YELLOW, "  ⚠ [Hybrid Parser] Dirty JSON detected and rescued with regex"))

        def on_json_error(exc: json.JSONDecodeError, json_str: str) -> None:
            logger.error(
                "Hybrid Parser: JSON fallback corrupted | "
                "model={} session={} exc={!r}\n"
                "--- RAW (truncated 4096) ---\n{}\n--- END ---",
                self.model_alias,
                self.session_id[:8],
                exc,
                json_str[:4096],
            )
            if _user_mode():
                print(c(RED, "  ❌ Model tool-call output could not be parsed. Details were logged; use /mode debug for diagnostics."))
            else:
                print(c(RED, f"  ✗ [Hybrid Parser] JSON fallback parse failed: {exc}"))

        return extract_tool_calls(
            text_buf,
            on_partial_xml=on_partial_xml,
            on_dirty_json_rescued=on_dirty_json_rescued,
            on_json_error=on_json_error,
        )

    def _make_tool_executor(self) -> ToolExecutor:
        return ToolExecutor(
            get_handler=_TOOL_REGISTRY.get_handler,
            agent_phases=AGENT_PHASES,
            schema_snapshot=_tool_schema_snapshot,
            check_failure_func=check_failure,
            format_failures_func=format_failures_for_prompt,
            write_failure_func=write_failure,
            count_failure_func=count_failure,
            sink_failure_func=sink_failure_to_gsa,
            user_error_formatter=user_friendly_error,
        )

    def _make_result_processor(self) -> ToolResultProcessor:
        return ToolResultProcessor(
            auto_intuitive_search=self._auto_intuitive_search,
            session_label=self.session_id[:8],
        )

    def _tool_execution_context(self, iteration: int) -> ToolExecutionContext:
        return ToolExecutionContext(
            session_id=self.session_id,
            model_alias=self.model_alias,
            iteration=iteration,
            current_phase=self.current_phase,
            user_mode=_user_mode(),
            debug_mode=_debug_mode(),
        )

    def _record_turn_usage(self, usage: dict[str, int]) -> None:
        pt = usage.get("prompt_tokens", 0)
        ct = usage.get("completion_tokens", 0)
        self._turn_prompt_tokens     += pt
        self._turn_completion_tokens += ct
        self.total_prompt_tokens     += pt
        self.total_completion_tokens += ct
        self._runtime_metrics.record_usage(
            prompt_tokens=pt,
            completion_tokens=ct,
        )

    def _record_tool_metrics(self, *, elapsed_ms: int = 0) -> None:
        self._turn_tool_calls += 1
        self.total_tool_calls += 1
        self._runtime_metrics.record_tool_call(elapsed_ms=elapsed_ms)

    def _runtime_metrics_snapshot(self) -> RuntimeMetricsSnapshot:
        """Return an internal snapshot of runtime counters."""
        return self._runtime_metrics.snapshot()

    def _consume_api_stream_attempt(
        self,
        api_msgs: list,
        current_tools: list | None,
        current_max_tokens: int,
        renderer: _PlanRenderer,
        iteration: int,
    ) -> TurnApiResult:
        reasoning_printed = False
        spinner = _ThinkingSpinner(_user_mode())
        spinner.start()

        def on_api_retry(retry_detail: str) -> None:
            spinner.stop()
            if _user_mode():
                print(c(YELLOW, f"\n  {user_friendly_error(retry_detail)}"))
            else:
                print(c(YELLOW, f"\nAPI retry: {retry_detail}"))
            logger.warning(
                "API stream retry | model={} session={} iteration={} detail={}",
                self.model_alias, self.session_id[:8], iteration, retry_detail,
            )

        def on_api_error(err_detail: str) -> None:
            spinner.stop()
            if _user_mode():
                print(c(RED, f"\n  {user_friendly_error(err_detail)}"))
            else:
                print(c(RED, f"\nAPI Error: {err_detail}"))
            logger.error(
                "API stream error | model={} session={} iteration={} raw_error={}",
                self.model_alias, self.session_id[:8], iteration, err_detail,
            )

        def on_reasoning_chunk(r_chunk: str) -> None:
            nonlocal reasoning_printed
            if not _debug_mode():
                return
            spinner.stop()
            if not reasoning_printed:
                sys.stdout.write(c(GRAY + DIM, "\n  🧠 [thinking] "))
                reasoning_printed = True
            sys.stdout.write(c(GRAY + DIM, r_chunk))
            sys.stdout.flush()

        def on_content_chunk(chunk: str) -> None:
            nonlocal reasoning_printed
            spinner.stop()
            # Add a newline when switching from thinking to normal output.
            if reasoning_printed and _debug_mode():
                sys.stdout.write("\n")
                sys.stdout.flush()
                reasoning_printed = False
            printable = renderer.feed(chunk)
            if printable:
                sys.stdout.write(printable)
                sys.stdout.flush()

        try:
            result = consume_model_stream(
                stream_request(
                    api_msgs, self.model_alias,
                    tools_schema=current_tools,
                    max_tokens=current_max_tokens,
                ),
                ensure_tool_call_id=ensure_tool_call_id,
                iteration=iteration,
                on_retry=on_api_retry,
                on_error=on_api_error,
                on_reasoning=on_reasoning_chunk,
                on_content=on_content_chunk,
                on_tool_delta=spinner.stop,
            )
        finally:
            spinner.stop()

        self._runtime_metrics.record_provider_retries(len(result.retry_events))
        self._record_turn_usage(result.usage)
        return result

    def _finalize_api_stream_result(
        self,
        result: TurnApiResult,
        renderer: _PlanRenderer,
        iteration: int,
    ) -> tuple[str, dict, str]:
        text_buf = result.text
        tc_buf = result.tool_calls
        reasoning_buf = result.reasoning

        leftover = renderer.flush()

        # P7: raw tool_call argument logging for driver escaping diagnostics.
        if tc_buf and _debug_mode():
            for idx, tc in tc_buf.items():
                raw_name = tc["name"]
                raw_args = tc["args"]
                logger.debug(
                    "RAW tool_call | session={} iter={} idx={} "
                    "name={!r} args_preview={!r}",
                    self.session_id[:8], iteration, idx,
                    raw_name, raw_args[:200],
                )

        # P2: rich Markdown rendering for non-plan text.
        if leftover:
            try:
                from pawnlogic.cli import render_agent_output
                render_agent_output(leftover)
            except (ImportError, Exception):
                sys.stdout.write(leftover)
                sys.stdout.flush()
        print()

        # Hybrid v2 parser: XML first, JSON fallback.
        if not tc_buf and (
            '<call name="' in text_buf or "<tool_call>" in text_buf
        ):
            extracted = self._extract_calls(text_buf)
            for i, call in enumerate(extracted):
                source = call["_source"]
                call_id = (
                    f"call_xml_{iteration}_{i}"
                    if source == "xml"
                    else f"call_fallback_{iteration}_{i}"
                )
                tc_buf[i] = {
                    "id":           call_id,
                    "name":         call["name"],
                    "args":         json.dumps(call["args"], ensure_ascii=False),
                    "_args_parsed": call["args"],
                }
                label = "XML" if source == "xml" else "JSON"
                if _debug_mode():
                    print(c(GRAY,
                        f"  ⚙ [Hybrid Parser/{label}] Intercepted tool call: {call['name']} "
                        f"(params: {list(call['args'].keys())})"
                    ))
                logger.info(
                    "Hybrid Parser/{} intercepted | "
                    "model={} session={} iteration={} tool={}",
                    label, self.model_alias, self.session_id[:8],
                    iteration, call["name"],
                )
            import re as _re
            trim = _re.search(r'<call\s+name="|<tool_call>', text_buf)
            if trim and extracted:
                text_buf = text_buf[:trim.start()]

        return text_buf, tc_buf, reasoning_buf

    def _prepare_turn(self, user_input: str) -> dict | None:
        self._reset_system_prompt(knowledge_query=user_input)
        self.messages.append({"role": "user", "content": user_input})

        # Sliding window: compute turn count and update history summary when needed.
        _current_turns = len(self._count_turns(self.messages))
        self._maybe_update_summary(self.messages, _current_turns)

        dropped = _trim_and_compact_context(self.messages)
        if dropped:
            print(c(YELLOW,
                    f"  ⚠ Context too long; compacted oldest {dropped} messages into a summary (Tool Clearing)"
                    ))
            logger.warning(
                "Context compacted (Tool Clearing) | session={} compacted={} model={}",
                self.session_id[:8], dropped, self.model_alias,
            )

        ok, env_name = validate_api_key(self.model_alias)
        if not ok:
            print(c(RED, f"  ✗ {self.model_alias} requires {env_name}; please export {env_name}=sk-..."))
            logger.error(
                "API key missing | model={} required_env={}",
                self.model_alias, env_name,
            )
            return None

        cfg = self.model
        print(c(cfg["color"] + BOLD, f"[{self.model_alias.upper()}]"), end=" ", flush=True)

        # Reset per-turn accounting.
        self._turn_prompt_tokens     = 0
        self._turn_completion_tokens = 0
        self._turn_tool_calls        = 0
        self._runtime_metrics.reset_turn()

        dynamic_cfg = _dynamic_config()
        self._turn_start_time = time.monotonic()
        self._time_budget_sec = dynamic_cfg.get("time_budget_sec", 0)
        self._urgent_mode     = False
        if self._time_budget_sec > 0:
            _mins = self._time_budget_sec // 60
            _secs = self._time_budget_sec % 60
            print(c(GRAY, f"  ⏱  Time budget: {_mins}m{_secs}s"))
        return dynamic_cfg

    def _run_model_with_empty_response_recovery(
        self,
        api_msgs: list,
        current_tools: list | None,
        current_max_tokens: int,
        renderer: _PlanRenderer,
        iteration: int,
    ) -> tuple[str, dict, str] | None:
        _api_retry = 0
        _API_RETRY_MAX = 3

        while True:
            _api_result = self._consume_api_stream_attempt(
                api_msgs, current_tools, current_max_tokens, renderer, iteration
            )
            if _api_result.error:
                self.messages.pop()
                return None

            text_buf, tc_buf, reasoning_buf = self._finalize_api_stream_result(
                _api_result, renderer, iteration
            )

            # Empty-response detection with exponential-backoff retry.
            # Usage-only and hidden reasoning-only deltas are not user-visible
            # answers, even when the provider reports completion tokens.
            _empty_response = is_empty_response(text_buf, tc_buf)

            if not _empty_response:
                return text_buf, tc_buf, reasoning_buf

            _api_retry += 1
            _retry_decision = decide_empty_response_retry(
                api_retry=_api_retry, max_retries=_API_RETRY_MAX
            )
            if _retry_decision.action == "giveup":
                if _debug_mode():
                    print(c(YELLOW,
                        f"\n  ⚠ [API Recovery] Received {_api_retry} consecutive empty responses; "
                        "injecting recovery hint and continuing..."
                    ))
                logger.warning(
                    "API empty response: retries exhausted | "
                    "model={} session={} iteration={} retries={}",
                    self.model_alias, self.session_id[:8], iteration, _api_retry,
                )
                self.messages.append({
                    "role": "user",
                    "content": (
                        "[System] Received an invalid response (empty content / 0 tokens). "
                        "Re-check the task objective and continue. "
                        "If this repeats, consider switching models (/model) or checking the API key."
                    ),
                })
                return "", {}, ""

            _wait = _retry_decision.wait_seconds
            if _debug_mode():
                print(c(YELLOW,
                    f"\n  ⚠ [API Recovery] Invalid response received; attempting recovery... "
                    f"({_api_retry}/{_API_RETRY_MAX}, waiting {_wait}s)"
                ))
            logger.warning(
                "API empty response detected, retrying | "
                "model={} session={} iteration={} attempt={} wait={}s",
                self.model_alias, self.session_id[:8], iteration, _api_retry, _wait,
            )
            time.sleep(_wait)

    def _append_assistant_or_tool_call_message(
        self,
        text_buf: str,
        tc_buf: dict,
        reasoning_buf: str,
    ) -> bool:
        if not tc_buf:
            # thinking-mode fix: store reasoning_content with the assistant
            # message so the next API call can send it back unchanged.
            _asst_msg: dict = {"role": "assistant", "content": text_buf}
            if reasoning_buf:
                _asst_msg["reasoning_content"] = reasoning_buf
            self.messages.append(_asst_msg)
            self._print_turn_summary()
            self._autosave(turn_status="completed")
            return False

        # thinking-mode fix: persist reasoning_content with the assistant
        # message so strict reasoning models can receive it back unchanged.
        _asst_msg = {
            "role":    "assistant",
            "content": text_buf or None,
            "tool_calls": [
                {"id": tc_buf[i]["id"], "type": "function",
                 "function": {"name": tc_buf[i]["name"], "arguments": tc_buf[i]["args"]}}
                for i in sorted(tc_buf)
            ],
        }
        if reasoning_buf:
            _asst_msg["reasoning_content"] = reasoning_buf
        self.messages.append(_asst_msg)
        return True

    def _apply_plan_guard(
        self,
        text_buf: str,
        tc_buf: dict,
        plan_rejected: int,
        iteration: int,
    ) -> tuple[str, int, bool]:
        plan_decision = TurnToolLoop.plan_guard(
            missing_required_plan=_tool_call_missing_plan(text_buf, tc_buf),
            plan_rejected=plan_rejected,
            max_soft=_MAX_SOFT_CORRECTIONS,
        )
        plan_rejected = plan_decision.plan_rejected

        if plan_decision.action == "hard":
            print(c(RED,
                    f"  ⛔ [CoT Guard] Missing <plan> for {plan_rejected} consecutive attempts; task stopped."
                    ))
            print(c(GRAY,
                    "  Suggestions: 1. Simplify the instruction  2. Switch to a stronger model (/model ds-v4-pro)"
                    ))
            logger.warning(
                "CoT Guard: hard kill triggered | "
                "model={} session={} iteration={} plan_rejected={}",
                self.model_alias, self.session_id[:8],
                iteration, plan_rejected,
            )
            return "hard", plan_rejected, False

        if plan_decision.action == "soft":
            if _debug_mode():
                print(c(YELLOW,
                    f"  💭 [CoT Soft #{plan_rejected}/{_MAX_SOFT_CORRECTIONS}] "
                    "Missing <plan> detected; tools will run and the correction signal will be injected after results..."
                ))
            logger.debug(
                "CoT Guard: soft intercept #{} | model={} session={} iteration={}",
                plan_rejected, self.model_alias, self.session_id[:8], iteration,
            )
            return "soft", plan_rejected, True

        return "ok", plan_rejected, False

    def _apply_concurrency_limit(self, tc_buf: dict) -> dict:
        concurrency = TurnToolLoop.concurrency_limit(
            tc_buf.keys(), _MAX_CONCURRENT_TOOLS
        )
        if not concurrency.truncated:
            return tc_buf

        orig = concurrency.original_count
        limited = {k: tc_buf[k] for k in concurrency.kept_keys}
        if _debug_mode():
            print(c(YELLOW, f"  ✂ [Concurrency Limit] Truncated {orig} tool calls to the first {_MAX_CONCURRENT_TOOLS}."))
        logger.warning(
            "Concurrent tool limit | model={} session={} original={} kept={}",
            self.model_alias, self.session_id[:8], orig, _MAX_CONCURRENT_TOOLS,
        )
        return limited

    def _execute_one_tool_call(
        self,
        i: int,
        tc: dict,
        *,
        iteration: int,
        max_iter: int,
        tool_executor: ToolExecutor,
        result_processor: ToolResultProcessor,
        current_tools: list | None,
    ) -> tuple[list | None, ToolExecutionOutcome]:
        name = tc["name"]

        fn_args = resolve_tool_arguments(tc)
        preview = preview_tool_arguments(fn_args)
        iter_tag = c(GRAY, f"[{iteration+1}/{max_iter}]")

        # In user mode, detect skill-pack script calls and simplify output.
        _is_skill_call = False
        if _user_mode() and name == "run_shell":
            _cmd = fn_args.get("command", "") or fn_args.get("_raw_args", "")
            _skills_dir_str = str(SKILLS_DIR).replace("\\", "/")
            if _skills_dir_str in _cmd.replace("\\", "/") and any(
                _cmd.strip().endswith(ext) or f"python3 {_skills_dir_str}" in _cmd.replace("\\", "/")
                for ext in (".py", ".sh")
            ):
                _is_skill_call = True
                # Extract the skill-pack name from the command path.
                _parts = _cmd.replace("\\", "/").split("/skills/")
                _pack_hint = _parts[1].split("/")[0] if len(_parts) > 1 else "unknown"
                print(c(GREEN, f"  🚀 [P6] Running automated validation script for {_pack_hint}...") + f" {iter_tag}")

        if not _is_skill_call:
            if _debug_mode():
                print(c(YELLOW, f"  🔧 {name}") + c(GRAY, f"({preview[:80]})") + f" {iter_tag}")
            else:
                print(c(YELLOW, f"  Working with {name}...") + f" {iter_tag}")

        # switch_phase intercept; mutate instance state directly.
        if name == "switch_phase":
            phase_result = tool_executor.execute_phase_switch(
                fn_args=fn_args,
                current_phase=self.current_phase,
            )
            result = phase_result.content
            if phase_result.switched:
                self.current_phase = phase_result.target_phase
                # Rebuild the dynamic tool list for the next iteration.
                current_tools = phase_result.active_tools
                print(c(MAGENTA,
                    f"  🔀 [Phase Switch] {phase_result.old_phase} → "
                    f"{phase_result.target_phase}  ({phase_result.reason[:60]})"
                ))
                logger.info(
                    "Phase switch | model={} session={} {} → {} reason={}",
                    self.model_alias, self.session_id[:8],
                    phase_result.old_phase,
                    phase_result.target_phase,
                    phase_result.reason,
                )
                # Refresh the phase-awareness block in the system prompt.
                self._reset_system_prompt()

            # Phase results are not audited or truncated. A non-directory
            # tool ran, so reset the directory counter, then record.
            result_processor.reset_directory_counter()
            self._record_tool_metrics()
            self.messages.append({
                "role": "tool", "tool_call_id": tc["id"], "content": result,
            })

        else:
            precheck = tool_executor.precheck_failures(
                tool_name=name,
                args_preview=preview[:200],
                is_audited=name in _AUDITED_TOOLS,
            )
            _failure_warning = precheck.warning
            if precheck.failure_count and _debug_mode():
                print(c(YELLOW,
                    f"  ⚠ [Anti-Pattern] {name} has "
                    f"{precheck.failure_count} historical failure records"
                ))

            execution = tool_executor.execute_handler(
                tool_call_id=tc["id"],
                tool_name=name,
                fn_args=fn_args,
                context=self._tool_execution_context(iteration),
                args_preview=preview[:200],
            )
            result = execution.content
            _audit_ok = execution.audit_ok
            _elapsed_ms = execution.elapsed_ms

            record_result = tool_executor.record_failure(
                tool_name=name,
                args_preview=preview[:200],
                content=result,
                audit_ok=_audit_ok,
                is_audited=name in _AUDITED_TOOLS,
                session_id=self.session_id,
            )
            if record_result.gsa_sunk and _debug_mode():
                print(c(YELLOW, f"  📝 [GSA Sink] {record_result.gsa_message}"))
            self._runtime_metrics.record_failure_class(record_result.error_type)

            processed = result_processor.process(
                result=result,
                tool_name=name,
                fn_args=fn_args,
                args_preview=preview[:200],
                audit_ok=_audit_ok,
                elapsed_ms=_elapsed_ms,
                failure_warning=_failure_warning,
                iteration=iteration,
                user_mode=_user_mode(),
                max_chars=_dynamic_config()["tool_max_chars"],
            )

            # Print processor notices, gated by display level.
            for _notice in processed.notices:
                if _notice.level == "debug" and not _debug_mode():
                    continue
                if _notice.level == "user" and not _user_mode():
                    continue
                print(c(_notice.color, _notice.message))

            # Write audit log (side effect kept in the caller).
            _audit_event = processed.audit_event
            if _audit_event is not None:
                try:
                    _audit_metadata = None
                    try:
                        from core.ctf_workspace import ctf_audit_metadata
                        _ctf_meta = ctf_audit_metadata(self.workspace_dir)
                        if _ctf_meta:
                            _audit_metadata = {"ctf": _ctf_meta}
                    except Exception:
                        _audit_metadata = None
                    audit_tool_call(
                        tool_name    = _audit_event.tool_name,
                        args_summary = _audit_event.args_summary,
                        result_len   = _audit_event.result_len,
                        elapsed_ms   = _audit_event.elapsed_ms,
                        session_id   = self.session_id,
                        model_alias  = self.model_alias,
                        iteration    = _audit_event.iteration,
                        success      = _audit_event.success,
                        metadata     = _audit_metadata,
                    )
                except Exception:
                    pass  # Audit logging must not block the main flow.

            self._record_tool_metrics(elapsed_ms=_elapsed_ms)
            self.messages.append({
                "role": "tool", "tool_call_id": tc["id"], "content": processed.content,
            })
            for _injection in processed.injections:
                self.messages.append({"role": "user", "content": _injection})


        visible_content = result if name == "switch_phase" else processed.content
        audit_ok = not str(result).startswith("ERROR:") if name == "switch_phase" else _audit_ok
        error_type = None if name == "switch_phase" else (record_result.error_type or None)
        capabilities = _TOOL_REGISTRY.get_capabilities(name)
        outcome = ToolExecutionOutcome(
            status="success" if audit_ok else "failed",
            content=visible_content,
            error_type=error_type,
            side_effect=bool(
                capabilities.intersection({"mutating", "shell", "network", "container"})
            ),
        )
        return current_tools, outcome

    def _inject_plan_missing_signal(self) -> None:
        self.messages.append({"role": "user", "content": _PLAN_MISSING_SIGNAL})
        print(c(
            GRAY,
            "  🔄 [CoT Self-Correction] PLAN_MISSING correction signal injected; "
            "the model will self-correct next iteration.",
        ))

    def _execute_tool_batch(
        self,
        tc_buf: dict,
        *,
        plan_signal_injected: bool,
        iteration: int,
        max_iter: int,
        tool_executor: ToolExecutor,
        result_processor: ToolResultProcessor,
        current_tools: list | None,
    ) -> list | None:
        batch = TurnToolLoop().execute_batch(
            tc_buf,
            current_tools=current_tools,
            execute_call=lambda i, tc, tools: self._execute_one_tool_call(
                i,
                dict(tc),
                iteration=iteration,
                max_iter=max_iter,
                tool_executor=tool_executor,
                result_processor=result_processor,
                current_tools=tools,
            ),
            plan_signal_injected=plan_signal_injected,
            inject_plan_signal=self._inject_plan_missing_signal,
        )
        return batch.current_tools

    def _autosave_iteration_checkpoint(self, iteration: int) -> None:
        if iteration > 0 and iteration % 5 == 0:
            self._autosave()

    def _maybe_append_anti_loop_injection(self, result_processor, iteration: int) -> None:
        anti_loop = result_processor.maybe_anti_loop_injection(iteration)
        if anti_loop is None:
            return
        self.messages.append({"role": "user", "content": anti_loop.injection})
        for notice in anti_loop.notices:
            if notice.level == "debug" and not _debug_mode():
                continue
            if notice.level == "user" and not _user_mode():
                continue
            print(c(notice.color, notice.message))

    def _maybe_show_loaded_skill_packs(self, iteration: int) -> None:
        if iteration != 0 or not self._loaded_skill_packs:
            return
        if _user_mode():
            print(c(GREEN, _skill_scanner.format_user_message(self._loaded_skill_packs)))
            return
        for skill_pack in self._loaded_skill_packs:
            print(c(
                CYAN,
                f"  📦 [Skill Pack] {skill_pack.get('name', '?')} "
                f"v{skill_pack.get('version', '1.0')}",
            ))
            skill_pack_path = skill_pack.get("_path", "")
            if skill_pack.get("guide"):
                print(c(GRAY, f"     guide: {skill_pack_path}/{skill_pack['guide']}"))
            if skill_pack.get("scripts"):
                print(c(GRAY, f"     scripts: {', '.join(skill_pack['scripts'])}"))

    def _time_budget_exhausted(self, remaining: float) -> bool:
        if remaining > 0:
            return False
        print(c(RED,
            f"\n  ⏰ [Time Budget] Budget exhausted ({self._time_budget_sec}s); stopping task."
        ))
        logger.warning(
            "Time budget exhausted | session={} budget={}s",
            self.session_id[:8], self._time_budget_sec,
        )
        return True

    def _apply_urgent_mode_if_needed(
        self,
        remaining: float,
        state: TurnState,
    ) -> None:
        urgent_decision = decide_urgent_mode(
            remaining=remaining,
            already_urgent=self._urgent_mode,
            threshold=_URGENT_THRESHOLD_SEC,
            model_alias=self.model_alias,
            is_fast_model=is_fast_model,
            find_fast_peer=find_fast_peer,
            candidates=_URGENT_MODEL_CANDIDATES,
            available_models=MODELS,
            validate_api_key=validate_api_key,
        )
        if not urgent_decision.activate:
            return

        self._urgent_mode = True
        state.mark_urgent_mode()
        print(c(RED,
            f"  🚨 [URGENT_MODE] {remaining:.0f}s remaining — "
            f"switching to fast mode"
        ))
        logger.info(
            "URGENT_MODE activated | session={} remaining={:.1f}s",
            self.session_id[:8], remaining,
        )

        self.messages.append({
            "role": "user",
            "content": _URGENT_SIGNAL,
        })

        if urgent_decision.target_model:
            old_model = self.model_alias
            self.model_alias = urgent_decision.target_model
            print(c(MAGENTA,
                f"  🚨 [URGENT] Model switched: "
                f"{old_model} -> {urgent_decision.target_model} (fast response)"
            ))
            current_tools = select_phase_tools(
                _tool_schema_snapshot(), AGENT_PHASES, self.current_phase
            )
            state.update_tools(current_tools)
            state.update_max_tokens(min(state.current_max_tokens, 4096))

    def _maybe_trigger_logic_refresh(self, state: TurnState) -> None:
        if (
            state.iteration <= 0
            or state.iteration % state.logic_refresh_interval != 0
        ):
            return
        recent_observations = []
        for message in self.messages[-20:]:
            if message.get("role") == "tool" and message.get("content"):
                recent_observations.append(message["content"][:200])
        if not recent_observations:
            return

        observations_text = "\n".join(recent_observations[-10:])
        summary_prompt = (
            f"[Logic Refresh — Iteration {state.iteration}]\n"
            f"Summarize the recent exploration path below in at most 5 sentences. "
            f"Extract key findings, paths already ruled out, and the current best direction:\n\n{observations_text}"
        )
        self.messages.append({"role": "user", "content": summary_prompt})
        if _debug_mode():
            print(c(CYAN,
                f"  🔄 [Logic Refresh] Phase summary triggered (iteration={state.iteration})"
            ))
        logger.info(
            "Logic Refresh: phase summary triggered | "
            "session={} iteration={} obs_count={}",
            self.session_id[:8], state.iteration, len(recent_observations),
        )

    def _run_iteration_bookkeeping(
        self,
        *,
        state: TurnState,
        result_processor: ToolResultProcessor,
    ) -> bool:
        self._autosave_iteration_checkpoint(state.iteration)
        self._maybe_show_loaded_skill_packs(state.iteration)

        remaining = self._time_remaining()
        if self._time_budget_exhausted(remaining):
            return True

        self._apply_urgent_mode_if_needed(remaining, state)
        self._maybe_trigger_logic_refresh(state)
        compact_redundant_tool_error_messages(self.messages)
        self._maybe_append_anti_loop_injection(result_processor, state.iteration)
        return False

    # Main turn loop.
    def run_turn(self, user_input: str):
        self._sync_runtime_context()
        with self.runtime_context.activate():
            return self._run_turn_active(user_input)

    def _run_turn_active(self, user_input: str):
        dynamic_cfg = self._prepare_turn(user_input)
        if dynamic_cfg is None:
            return

        renderer           = _PlanRenderer()
        is_vision_model    = self.model.get("vision", False)
        if is_vision_model:
            print(c(YELLOW, "  ℹ Tool calls are disabled for vision models"))
            initial_tools = None
        else:
            # MoE dynamic tool pruning.
            initial_tools = select_phase_tools(
                _tool_schema_snapshot(), AGENT_PHASES, self.current_phase
            )
            if _debug_mode():
                print(c(GRAY,
                    f"  📡 [Phase:{self.current_phase}] "
                    f"Loaded {len(initial_tools)} tools "
                    f"({', '.join(s['function']['name'] for s in initial_tools)})"
                ))
        turn_state = TurnState.for_turn(
            max_iter=dynamic_cfg["max_iter"],
            max_tokens=dynamic_cfg["max_tokens"],
            is_vision_model=is_vision_model,
            current_tools=initial_tools,
            logic_refresh_interval=_LOGIC_REFRESH_INTERVAL,
            urgent_mode_active=self._urgent_mode,
        )

        tool_executor = self._make_tool_executor()
        # Per-turn tool result processing: owns directory/anti-loop/anti-code-loop
        # counters previously kept as locals here.
        result_processor = self._make_result_processor()

        for iteration in range(turn_state.max_iter):
            try:
                turn_state.set_iteration(iteration)
                should_stop = self._run_iteration_bookkeeping(
                    state=turn_state,
                    result_processor=result_processor,
                )
                if should_stop:
                    break

                # Sliding-window view: send trimmed messages without mutating self.messages.
                _api_msgs = self._build_api_messages()
                model_response = self._run_model_with_empty_response_recovery(
                    _api_msgs,
                    turn_state.current_tools,
                    turn_state.current_max_tokens,
                    renderer,
                    turn_state.iteration,
                )
                if model_response is None:
                    return
                text_buf, tc_buf, reasoning_buf = model_response
                if is_empty_response(text_buf, tc_buf):
                    continue

                if not tc_buf:
                    self._append_assistant_or_tool_call_message(
                        text_buf, tc_buf, reasoning_buf
                    )
                    return

                # ════════════════════════════════════════════════
                # CoT Guard refactor: coaching mode.
                #
                # Decision order:
                #   1. Exemption check (read-only tools do not require plans)
                #   2. Soft intercept x MAX_SOFT_CORRECTIONS (tools still run, signal appended)
                #   3. Hard stop x 1 (only after soft intercepts are exhausted)
                #
                # Signal injection:
                #   · Does not block tool execution; the model sees results first.
                #   · Appends the signal as a "user" role after tool results.
                # ════════════════════════════════════════════════
                _plan_action, plan_rejected, _plan_signal_injected = self._apply_plan_guard(
                    text_buf, tc_buf, turn_state.plan_rejected, turn_state.iteration
                )
                turn_state.replace_plan_rejected(plan_rejected)
                if _plan_action == "hard":
                    # Hard stop after soft intercepts are exhausted.
                    if self.messages and self.messages[-1]["role"] == "user":
                        self.messages.pop()  # Remove the latest user message to keep context clean.
                    return

                # Module 1B: concurrent call truncation.
                tc_buf = self._apply_concurrency_limit(tc_buf)
                self._append_assistant_or_tool_call_message(
                    text_buf, tc_buf, reasoning_buf
                )
                current_tools = self._execute_tool_batch(
                    tc_buf,
                    plan_signal_injected=_plan_signal_injected,
                    iteration=turn_state.iteration,
                    max_iter=turn_state.max_iter,
                    tool_executor=tool_executor,
                    result_processor=result_processor,
                    current_tools=turn_state.current_tools,
                )
                turn_state.update_tools(current_tools)

            except KeyboardInterrupt:
                self._autosave(turn_status="interrupted")
                raise TurnInterrupted()

        print(c(RED, f"\n[Reached max_iter={turn_state.max_iter}; use /mid, /deep, or /iter <n> to raise it]"))
        logger.warning(
            "max_iter reached | model={} session={} max_iter={}",
            self.model_alias, self.session_id[:8], turn_state.max_iter,
        )
        self._print_turn_summary()
        self._autosave(turn_status="failed")

    # ── Per-turn usage summary ───────────────────────────
    def _print_turn_summary(self):
        """Print token and tool-call summary after each turn."""
        snapshot = self._runtime_metrics_snapshot()
        pt = snapshot.turn_prompt_tokens
        ct = snapshot.turn_completion_tokens
        tt = snapshot.turn_tool_calls
        if pt + ct + tt == 0:
            return   # nothing to show (no usage data from this provider)
        tot_pt = snapshot.total_prompt_tokens
        tot_ct = snapshot.total_completion_tokens
        tot_tt = snapshot.total_tool_calls
        if _user_mode():
            cum = (f"  cum:↑{tot_pt:,}↓{tot_ct:,}🔧{tot_tt}"
                   if tot_pt != pt or tot_tt != tt else "")
            print(c(GRAY, f"  [↑{pt:,}tok ↓{ct:,}tok 🔧{tt}]{cum}"))
        else:
            total_turn = pt + ct
            cum_total  = tot_pt + tot_ct
            lines = [
                "",
                "  ┌─ Turn Usage ──────────────────────────────",
                f"  │  Prompt tokens    : {pt:>8,}" +
                (f"   (session: {tot_pt:,})" if tot_pt != pt else ""),
                f"  │  Completion tokens: {ct:>8,}" +
                (f"   (session: {tot_ct:,})" if tot_ct != ct else ""),
                f"  │  Total this turn  : {total_turn:>8,}" +
                (f"   (session: {cum_total:,})" if cum_total != total_turn else ""),
                f"  │  Tool calls       : {tt:>8,}" +
                (f"   (session: {tot_tt:,})" if tot_tt != tt else ""),
                "  └───────────────────────────────────────────",
            ]
            print(c(GRAY, "\n".join(lines)))

    # Background async autosave.
    def _autosave(self, *, turn_status: str | None = None):
        if turn_status == "completed":
            self._turn_count += 1
            self._runtime_metrics.record_turn_completed()
        elif turn_status == "interrupted":
            self._runtime_metrics.record_turn_interrupted()
        elif turn_status == "failed":
            self._runtime_metrics.record_turn_failed()
        self._runtime_metrics.record_autosave()
        from core.session_snapshot import SessionSnapshot
        snapshot = SessionSnapshot.capture(
            session_id=self.session_id,
            model_alias=self.model_alias,
            messages=self.messages,
            cwd=self.cwd,
            workspace_dir=self.workspace_dir,
            config=dict(_dynamic_config()),
        )
        msgs_snapshot = list(snapshot.messages)
        sid = snapshot.session_id
        def _do():
            if not self._save_lock.acquire(blocking=False): return
            try:
                from core.persistence import save_snapshot
                save_snapshot(snapshot)
            except Exception as _autosave_exc:
                # Log autosave failures instead of silently dropping them.
                logger.error(
                    "Autosave failed | session={} model={} exc={!r}",
                    sid[:8], snapshot.model_alias, _autosave_exc,
                )
            finally:
                self._save_lock.release()

        t = threading.Thread(target=_do, daemon=True, name=f"save-{sid[:8]}")
        t.start()
        t.join(timeout=3.0)
        self._maybe_autoname(msgs_snapshot)

    def _maybe_autoname(self, msgs_snapshot: list):
        if self._naming_done:
            return
        if self._turn_count < 2:
            return
        if not should_name_session(msgs_snapshot):
            return
        sid, model_alias, cwd, workspace_dir = (
            self.session_id, self.model_alias, self.cwd, self.workspace_dir
        )

        def _do():
            if not self._naming_lock.acquire(blocking=False):
                return
            try:
                # Keep the cooldown gate inside the lock. Failures do not block
                # the next retry once the lock is released.
                now = time.monotonic()
                if now - self._naming_attempted_at < 10:
                    return
                self._naming_attempted_at = now
                try:
                    naming_alias = pick_naming_model(model_alias)
                except Exception as exc:
                    logger.warning(
                        "pick_naming_model fallback | session={} exc={!r}",
                        sid[:8], exc,
                    )
                    naming_alias = model_alias

                # 2. Call the LLM to generate {title, slug}.
                result = generate_session_name(
                    messages=msgs_snapshot,
                    model_alias=naming_alias,
                    session_id=sid,
                    cwd=cwd,
                )
                title = result.get("title", "").strip()
                slug  = result.get("slug", "").strip()
                if not slug:
                    logger.warning(
                        "Auto naming produced empty slug | session={} model={}",
                        sid[:8], naming_alias,
                    )
                    return

                # 3. Swap the real workspace directory.
                try:
                    final_dirname, new_abs = self._swap_workspace_dir(slug)
                except Exception as exc:
                    logger.warning(
                        "Workspace swap threw unexpected | session={} exc={!r}",
                        sid[:8], exc,
                    )
                    final_dirname, new_abs = "", ""

                # 4. Decide which workspace metadata to persist:
                #    · swap success -> use new path + final_dirname as alias
                #    · swap failure -> use old path and still create by-name/<slug>
                if new_abs:
                    persist_workspace_dir = new_abs
                    persist_alias = final_dirname
                else:
                    persist_workspace_dir = workspace_dir
                    try:
                        persist_alias = create_workspace_alias(sid, slug, workspace_dir)
                    except Exception as exc:
                        logger.warning(
                            "create_workspace_alias fallback failed | exc={!r}", exc,
                        )
                        persist_alias = slug

                # 5. Write pawn.db separately so transient DB locks do not affect
                # previous filesystem changes.
                try:
                    update_session_naming(
                        sid,
                        title=title,
                        auto_name=slug,
                        workspace_dir=persist_workspace_dir,
                        workspace_alias=persist_alias,
                        name_source="auto",
                    )
                except Exception as exc:
                    logger.warning(
                        "update_session_naming failed | session={} exc={!r}",
                        sid[:8], exc,
                    )

                # 6. Mark done even if DB write failed to avoid repeated renames.
                # The next autosave upsert_session writes the latest workspace_dir.
                self._naming_done = True

                # 7. Terminal UX feedback.
                try:
                    self._print_naming_banner(title, slug, final_dirname, new_abs)
                except Exception:
                    pass   # UI feedback failure is non-critical.

            except Exception as exc:
                # Top-level fallback: swallow unexpected errors and log a warning.
                logger.warning(
                    "Auto naming top-level failure (non-fatal) | session={} exc={!r}",
                    sid[:8], exc,
                )
            except BaseException as exc:
                logger.warning(
                    "Auto naming interrupted (non-fatal) | session={} exc={!r}",
                    sid[:8], exc,
                )
            finally:
                try:
                    self._naming_lock.release()
                except Exception:
                    pass   # Ignore rare cases where the lock was already released.

        threading.Thread(target=_do, daemon=True, name=f"name-{sid[:8]}").start()
