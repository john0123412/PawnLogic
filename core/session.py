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
import importlib
import os, json, sys, threading, time
from datetime import datetime
from pathlib import Path
from config import (
    DYNAMIC_CONFIG, MODELS, DEFAULT_MODEL,
    validate_api_key, VERSION, GLOBAL_SKILLS_PATH,
    smart_truncate,
    AGENT_PHASES,
    user_friendly_error,
    is_fast_model, find_fast_peer,
    SKILLS_DIR,
)
from utils.ansi import c, BOLD, DIM, GRAY, CYAN, GREEN, YELLOW, RED, MAGENTA
from core.api_client import stream_request, ensure_tool_call_id
from core.state import state as _runtime_state
from core.turn_api import TurnApiResult, consume_model_stream
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
                              tool_run_shell, _session_cwd, _session_workspace_dir,
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
    return bool(_runtime_state.user_mode)


def _debug_mode() -> bool:
    return bool(_runtime_state.debug_mode)


def _dynamic_config() -> dict:
    """Return the currently loaded mutable runtime config."""
    try:
        return importlib.import_module("config").DYNAMIC_CONFIG
    except Exception:
        return DYNAMIC_CONFIG


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

TOOL_MAP: dict = {
    "read_file":           tool_read_file,
    "read_file_lines":     tool_read_file_lines,
    "write_file":          tool_write_file,
    "patch_file":          tool_patch_file,
    "list_dir":            tool_list_dir,
    "find_files":          tool_find_files,
    "run_shell":           tool_run_shell,
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

# P3 + P4: optional Docker tool registration.
if tool_run_code_docker:
    TOOL_MAP["run_code_docker"]    = tool_run_code_docker
if tool_pwn_container:
    TOOL_MAP["pwn_container"]      = tool_pwn_container
if tool_install_package:                                    # P4.2
    TOOL_MAP["tool_install_package"] = tool_install_package
if docker_prune_resources:                                  # P4.3
    TOOL_MAP["docker_prune_resources"] = docker_prune_resources

# P5: optional Scrapling browser tool registration.
if tool_web_fetch:
    TOOL_MAP["web_fetch"]      = tool_web_fetch
if tool_web_click:
    TOOL_MAP["web_click"]      = tool_web_click
if tool_web_screenshot:
    TOOL_MAP["web_screenshot"] = tool_web_screenshot
if tool_web_select:
    TOOL_MAP["web_select"]     = tool_web_select
if tool_web_type:
    TOOL_MAP["web_type"]       = tool_web_type
if tool_web_navigate:
    TOOL_MAP["web_navigate"]   = tool_web_navigate

# P6: optional environment reconnaissance tool registration.
if tool_check_service:
    TOOL_MAP["check_service"]  = tool_check_service

TOOLS_SCHEMA: list = (
    FILE_SCHEMAS + WEB_SCHEMAS + SANDBOX_SCHEMAS
    + PWN_SCHEMAS + VISION_SCHEMAS + DOCKER_SCHEMAS
    + BROWSER_SCHEMAS + RECON_SCHEMAS
)

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

TOOL_MAP["switch_phase"] = lambda a: (
    f"[switch_phase] Phase switch request received; target: {a.get('phase', '?')}. "
    "This message should not appear; run_turn should intercept it."
)
TOOLS_SCHEMA.append(_SWITCH_PHASE_SCHEMA)

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

TOOL_MAP["bump_skill"] = tool_bump_skill
TOOLS_SCHEMA.append(_BUMP_SKILL_SCHEMA)

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

TOOL_MAP["audit_payload"] = tool_audit_payload
TOOLS_SCHEMA.append(_AUDIT_PAYLOAD_SCHEMA)

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

TOOL_MAP["search_skills"] = tool_search_skills
TOOLS_SCHEMA.append(_SEARCH_SKILLS_SCHEMA)

def _try_load_delegate():
    try:
        from tools.delegate_tool import tool_delegate_task, DELEGATE_SCHEMA
        TOOL_MAP["delegate_task"] = tool_delegate_task
        TOOLS_SCHEMA.append(DELEGATE_SCHEMA)
    except ImportError:
        pass

_try_load_delegate()

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

    # 1. Tool tables: update / extend for transparent main-loop consumption.
    TOOL_MAP.update(mgr.build_pawnlogic_handlers())
    TOOLS_SCHEMA.extend(mgr.build_pawnlogic_schemas())

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

# ════════════════════════════════════════════════════════
# Context management.
# ════════════════════════════════════════════════════════

def _ctx_chars(msgs: list) -> int:
    # thinking-mode fix: reasoning_content must count toward context budget,
    # otherwise reasoning blocks from models such as MiMo undercount true tokens.
    return sum(
        len(str(m.get("content") or "")) + len(str(m.get("reasoning_content") or ""))
        for m in msgs
    )

def _trim_and_compact_context(msgs: list) -> int:
    """
    Context compaction (Tool Clearing).
    When the token budget overflows, keep the system prompt and latest 10
    messages. Older messages are not dropped directly:
      - role=tool content is replaced by a placeholder
      - role=user/assistant content is truncated to the first 100 characters
    Then the compacted content is merged into one assistant summary inserted
    after the system message.
    """
    cfg = _dynamic_config()
    if _ctx_chars(msgs) <= cfg["ctx_max_chars"]:
        return 0

    KEEP_TAIL = 10
    # system occupies index 0; require enough room to compact.
    if len(msgs) <= KEEP_TAIL + 1:
        return 0

    cutoff = len(msgs) - KEEP_TAIL   # [1:cutoff] is the compaction range

    old_msgs = msgs[1:cutoff]

    compacted_lines: list[str] = []
    for m in old_msgs:
        role    = m.get("role", "unknown")
        content = m.get("content") or ""
        if role == "tool":
            compacted_lines.append(f"[tool/{m.get('tool_call_id', '')}]: "
                                   "(Tool output compacted to save context)")
        elif role in ("user", "assistant"):
            snippet = str(content)[:100]
            ellipsis = "…" if len(str(content)) > 100 else ""
            compacted_lines.append(f"[{role}]: {snippet}{ellipsis}")
        # assistant with tool_calls: note the call names only
        if role == "assistant" and m.get("tool_calls"):
            names = [tc.get("function", {}).get("name", "?")
                     for tc in (m.get("tool_calls") or [])]
            compacted_lines.append(f"  └─ tool_calls: {', '.join(names)}")

    summary_content = (
        "📝 [Context Compacted]:\n"
        + "\n".join(compacted_lines)
    )
    summary_msg = {
        "role":     "assistant",
        "content":  summary_content,
        "_pinned":  True,   # keep the summary from being compacted again next time
    }

    # Replace the old message range with the summary.
    del msgs[1:cutoff]
    msgs.insert(1, summary_msg)

    return len(old_msgs)


class TurnInterrupted(KeyboardInterrupt):
    """Raised when an in-flight turn is interrupted and should be rolled back."""


def _drop_dangling_tool_call_messages(msgs: list) -> list:
    """Return a copy without assistant tool calls that lack matching tool output."""
    cleaned: list = []
    i = 0
    while i < len(msgs):
        msg = msgs[i]
        calls = msg.get("tool_calls") or []
        if msg.get("role") != "assistant" or not calls:
            cleaned.append(msg)
            i += 1
            continue

        expected_ids = [
            call.get("id")
            for call in calls
            if isinstance(call, dict) and call.get("id")
        ]
        j = i + 1
        actual_ids: list[str] = []
        while j < len(msgs) and msgs[j].get("role") == "tool":
            tool_call_id = msgs[j].get("tool_call_id")
            if tool_call_id:
                actual_ids.append(tool_call_id)
            j += 1

        if expected_ids and all(call_id in actual_ids for call_id in expected_ids):
            cleaned.append(msg)
            cleaned.extend(msgs[i + 1:j])
        i = j
    return cleaned

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
        _session_cwd[0]  = self.cwd
        self.workspace_dir = stable_workspace_dir(self.session_id)
        _session_workspace_dir[0] = self.workspace_dir
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
        # P6.5: matched skill-pack cache.
        self._loaded_skill_packs: list = []
        # Sliding window + history summary state.
        self._history_summary: str = ""          # current effective history summary
        self._summary_turn_count: int = 0        # turn count when summary was last generated
        # Call last because it depends on all attributes above.
        self._reset_system_prompt()

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
        then atomically update ``_session_workspace_dir[0]`` and
        ``self.workspace_dir``.

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
            _session_workspace_dir[0] = new_abs
            self.workspace_dir = new_abs

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
        cfg = _dynamic_config()
        knowledge_block = ""
        if knowledge_query:
            rows = search_knowledge(knowledge_query, limit=3)
            knowledge_block = format_knowledge_for_prompt(rows)
        state_block  = _load_state_md(self.cwd)

        # P1.8: URGENT_MODE skips GSA injection to save tokens.
        if self._urgent_mode:
            skills_toc = ""
            _relevant_skills_md = ""
            _conflict_warning = ""
            _local_skills_md = ""
            self._loaded_skill_packs = []
        else:
            skills_toc   = _load_skills_toc()

            # Dynamic retrieval of GSA skills with decayed scoring.
            _relevant_skills_md  = ""
            _conflict_warning    = ""
            _local_skills_md     = ""
            if knowledge_query:
                try:
                    _relevant_skills_md, _conflict_warning = load_relevant_skills(
                        knowledge_query, top_k=3
                    )
                except Exception:
                    pass   # Degrade without relevant skill injection.

            # P6.5: Local skill retrieval through SkillScanner directory packages.
            # Always attempt matching. Empty knowledge_query may produce no keyword
            # matches, but manifest.json triggers can still match through metadata.
            try:
                _query = knowledge_query or ""
                _matched_packs = _skill_scanner.match(_query, top_k=3)
                _local_skills_md = _skill_scanner.format_for_prompt(_matched_packs)
                self._loaded_skill_packs = _matched_packs
            except Exception:
                pass   # Degrade without local skill injection.

        # MoE phase-awareness block.
        phase_tools  = AGENT_PHASES.get(self.current_phase, [])
        other_phases = [p for p in AGENT_PHASES if p != self.current_phase]
        phase_block  = (
            f"=== Current Agent Phase: {self.current_phase} ===\n"
            f"You are currently in the '{self.current_phase}' phase. "
            f"Only the following tools are available this phase:\n"
            f"  {', '.join(phase_tools)}\n"
            f"  (+ switch_phase is always available)\n"
            f"If these tools are insufficient, call switch_phase(phase=<target>) to unlock others.\n"
            f"Other available phases: {', '.join(other_phases)}\n\n"
        )

        prompt = (
            f"You are PawnLogic {VERSION}, an expert AI assistant running in Linux/WSL2.\n"
            "Core Expertise: C/C++ development, Python, Cybersecurity (Pwn/CTF reverse engineering), "
            "and academic paper processing.\n\n"

            + phase_block +

            "=== Pwn/Security Expert Mindset ===\n"
            "When analyzing binaries or writing exploits, follow this Security Researcher paradigm:\n"
            "  Phase 1 — Recon    : pwn_env (check tools) → inspect_binary (checksec, file, strings)\n"
            "  Phase 2 — Offset   : pwn_cyclic gen → pwn_debug (feed pattern, read crash offset)\n"
            "  Phase 3 — Weaponize: pwn_rop (find gadgets) → pwn_libc (leak & resolve) → build payload\n"
            "  Phase 4 — Exploit  : run_code (use_venv=true, install_deps='pwntools') → test\n\n"
            "RULE: ALL pwntools code MUST run inside run_code sandbox with use_venv=true.\n"
            "RULE: If process() or any binary execution fails with PermissionError / 'Permission denied' / exit code 126, "
            "IMMEDIATELY run_shell('chmod +x <binary_path>') to fix permissions, then retry. Do NOT ask the user.\n"
            "RULE: NEVER skip a phase. If Phase 2 gives no offset, debug before proceeding.\n"
            "RULE: You MUST NOT guess the overflow vector. Always confirm it with pwn_cyclic + pwn_debug.\n"
            "RULE: If tool 'inspect_binary' shows 'NX enabled', do NOT attempt shellcode injection on "
            "the stack. Use ROP chains (pwn_rop) or one_gadget (pwn_one_gadget) instead.\n"
            "RULE: If 'inspect_binary' shows 'Canary found', you MUST find a canary leak path before "
            "attempting any stack smashing exploit.\n\n"
            "=== VULN_DEV Exploit Discipline ===\n"
            "You are running in a headless terminal. NEVER run interactive commands such as "
            "gdb or nc directly when they may wait for input.\n"
            "Best practice: during exploit development, write an exploit.py script with "
            "pwntools. Use cyclic() to generate offset data, process() to start the target, "
            "corefile to inspect crash memory, then test with run_shell('python3 exploit.py'). "
            "This is the most stable workflow.\n\n"

            "=== Memory & History Awareness ===\n"
            "You have a persistent conversation database. While you have no spontaneous memory,\n"
            "you CAN and SHOULD use /chat commands when the user asks about past sessions.\n"
            "NEVER claim you have no memory — you have History tools.\n\n"

            "=== Available Tools ===\n"
            "  File     : read_file · read_file_lines · write_file · patch_file · list_dir · find_files\n"
            "  Shell    : run_shell · git_op\n"
            "  Web      : web_search → fetch_url (Jina / Pandoc / regex fallback)\n"
            "  Browser  : web_fetch (StealthyFetcher / anti-bot) · web_click · web_screenshot\n"
            "             web_select (adaptive CSS) · web_type · web_navigate\n"
            "  Sandbox  : run_code  (python / c / cpp / javascript / bash / rust / go / java)\n"
            "  Docker   : run_code_docker (one-shot container) · pwn_container (persistent container)\n"
            "  Vision   : analyze_local_image  (jpg/png/gif/webp — glm-4v / gpt-4o)\n"
            "  CTF/Pwn  : pwn_env · inspect_binary · pwn_rop · pwn_cyclic · pwn_disasm\n"
            "             pwn_libc · pwn_debug · pwn_one_gadget · pwn_timed_debug\n"
            "  Recon    : check_service (port -> PID/process/path/environment/shared libraries)\n"
            "  Advanced : delegate_task  (fresh context sub-agent)\n"
            "  Skills   : search_skills (P6: retrieve local skill packs by target fingerprint)\n"
            "  History  : /chat list · /chat view · /chat find · /chat tag · /chat related\n\n"

            "=== Scrapling Web Penetration (WEB_PEN Phase) ===\n"
            "Cloudflare / dynamic pages -> Scrapling adaptive bypass:\n"
            "  · web_fetch automatically uses StealthyFetcher + solve_cloudflare.\n"
            "  · web_select uses adaptive CSS targeting for DOM changes.\n"
            "  · Screenshots/downloads go to ~/.pawnlogic/workspace/screenshots/.\n"
            "  · Interaction flow: web_navigate -> web_type -> web_click -> web_screenshot.\n\n"

            "=== Auto-Exploit (P6) Protocol ===\n"
            "Web targets must follow this closed loop:\n\n"
            "  1. Recon fingerprint — web_fetch extracts Server/X-Powered-By/Cookie/HTML traits and identifies the framework.\n"
            "  2. Confirm environment — check_service(port) obtains PID/path/environment/shared libraries.\n"
            "  3. Retrieve weaponry — search_skills(query='<framework>'); try variant keywords when empty.\n"
            "  4. Sync/install — /sp sync for latest packs, /sp install <url> for new packs.\n"
            "  5. Read the guide — read_file(guide.md), then understand conditions and parameters.\n"
            "  6. Execute scripts — prefer run_shell(pack_path/script); use run_code_docker for isolation.\n"
            "  7. Verify finish — confirm Flag/Shell/echo; after success call bump_skill to raise weight.\n\n"
            "  Muscle memory: recon -> check_service -> search_skills -> install/sync -> execute\n\n"
            "  RULE: Do not skip search_skills and write an exploit directly.\n"
            "  RULE: If a script fails, read guide.md, adjust parameters, and retry; write from scratch only when no pack matches.\n"
            "  RULE: All files produced by write_file must be written under ~/.pawnlogic/workspace/.\n"
            "       Relative paths are automatically redirected; absolute paths must stay inside the workspace.\n"
            "       Example: write_file(path='exploit.py', content=...) writes to ~/.pawnlogic/workspace/exploit.py\n\n"

            f"Working dir : {self.cwd}\n"
            f"Time        : {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"Model       : {self.model_alias} ({self.model['id']})\n"
            f"Limits      : max_tokens={cfg['max_tokens']}  max_iter={cfg['max_iter']}  "
            f"ctx={cfg['ctx_max_chars']//1000}k  tool_out={cfg['tool_max_chars']}\n\n"

            # ════════════════════════════════════════════════
            # Execution protocol: current plan format.
            # ════════════════════════════════════════════════
            "=== Execution Protocol (MANDATORY) ===\n"

            "ARCHITECTURE NOTE: You are the 'Brain' in a pipeline:\n"
            "  User Input → [YOU] → <plan> parser → tool executor → result injector → [YOU again]\n"
            "The <plan> tag is NOT a formality. It is the KEY that unlocks the tool executor.\n"
            "Without <plan>, the executor cannot receive your intent and will return an error.\n\n"

            "Thinking Process: You are an autonomous agent. Like a human expert, you MUST think\n"
            "step-by-step. Before any tool_use or code block, output a <plan> to decompose\n"
            "the problem into concrete, ordered steps.\n\n"

            "BEFORE invoking ANY tool, output your thought process using the full plan format:\n\n"
            "<plan>\n"
            "  <intent>One sentence: what am I trying to accomplish right now?</intent>\n"
            "  <tool>Tool name I will call</tool>\n"
            "  <why>Why this specific tool? What do I expect to find?</why>\n"
            "  <next>If this succeeds, my next action will be: ...</next>\n"
            "</plan>\n\n"
            "Minimal plan (for simple single-tool calls):\n"
            "  <plan><intent>Check binary protections before analysis.</intent></plan>\n\n"
            "  · For pure conversation (no tools), a plan is optional.\n"
            "  · For even a single tool call, output AT MINIMUM: <plan><intent>reason</intent></plan>\n\n"
            # ════════════════════════════════════════════════
            # Final defense: break JSON inertia and reinforce XML requirements.
            # ════════════════════════════════════════════════
            "### === TOOL CALLING PROTOCOL (CRITICAL) ===\n"
            "You have TWO output formats. Choosing the wrong format will cause system crash.\n\n"
            "[RULE 1: COMPACT JSON]\n"
            "Use ONLY for simple parameters (short strings, numbers, NO newlines, NO quotes).\n"
            "Format: {\"name\":\"tool_name\",\"arguments\":{\"key\":\"val\"}}\n\n"
            "[RULE 2: XML TAGS (MANDATORY FOR CODE/TEXT)]\n"
            "You MUST use XML tags if your argument contains:\n"
            "- Bash scripts, Python code, or JSON payloads.\n"
            "- Multi-line text (newlines).\n"
            "- Quotes (\" or ').\n"
            "- Chinese characters.\n"
            "Specifically, tools like `write_file`, `patch_file`, `web_search` MUST use XML.\n\n"
            "Format:\n"
            "<call name=\"write_file\">\n"
            "  <path>report.md</path>\n"
            "  <content>\n"
            "# Write raw unescaped text here\n"
            "watch -n 1 \"grep -rnw /proc/net\"\n"
            "  </content>\n"
            "</call>\n\n"
            "🚨 DO NOT WRAP XML IN <tool_call> TAGS. JUST OUTPUT <call>.\n"
            "🚨 NEVER output JSON with unescaped quotes. Use XML to bypass escaping.\n\n"
            "⚠ NO WAITING RULE: Output the <plan> block AND invoke the tool in the EXACT SAME\n"
            "response. Do NOT output a plan then wait for user confirmation.\n\n"

            "Self-Correction Protocol (when you see PLAN_MISSING signal):\n"
            "  Do NOT apologize. Do NOT repeat failed call text.\n"
            "  Respond with ONLY:\n"
            "    <plan>\n"
            "      <intent>[your original intent]</intent>\n"
            "      <tool>[original tool name]</tool>\n"
            "      <why>[brief justification]</why>\n"
            "      <correction>true</correction>\n"
            "    </plan>\n"
            "    [re-emit the original tool call]\n\n"

            "Anti-Drift Anchor (use when iteration count > 15):\n"
            "  Prepend to your <plan>:\n"
            "    <anchor>\n"
            "      Current phase: [PHASE N — description]\n"
            "      Confirmed so far: [offset=X, NX=enabled/disabled, libc=X]\n"
            "      Still needed: [what remains for gate pass]\n"
            "    </anchor>\n\n"

            "Long Output Management:\n"
            "  When a tool result > 100 lines:\n"
            "    · EXTRACT only what is needed for the current phase.\n"
            "    · SUMMARIZE the rest in one sentence.\n"
            "    · Issue targeted follow-ups: run_shell('ROPgadget ... | grep pop rdi') rather than full dump.\n\n"

            "=== NEGATIVE CONSTRAINTS — DO NOT VIOLATE ===\n"
            "NEVER do the following (violations will be intercepted and cancelled by the system):\n\n"
            "  ✗  NEVER use 'sudo' in run_shell. The host is NOT your playground.\n"
            "       If you need root privileges, spin up a Docker container:\n"
            "       pwn_container(action='create', image='ubuntu22') → "
            "the container runs as root by default.\n\n"
            "  ✗  RW (read-write) mount is ONLY allowed inside ~/.pawnlogic/workspace.\n"
            "       Any path outside that directory MUST use mode='ro'.\n"
            "       The system will reject rw mounts to host paths outside the workspace.\n\n"
            "  ✗  NEVER blindly guess file paths.\n"
            "       Wrong: list_dir('.') → list_dir('src') → list_dir('src/lib') → ...\n"
            "       Right: find_files('target_name.c', root='.') once, then read directly.\n\n"
            "  ✗  NEVER call find_files or list_dir more than twice in succession.\n"
            "       If you still cannot find the file after 2 attempts, ASK the user for the path.\n\n"
            "  ✗  NEVER read a file > 2MB in one call. Use read_file_lines for large files.\n\n"
            "  ✗  NEVER use write_file to overwrite existing code files.\n"
            "       Use patch_file with SEARCH/REPLACE blocks for ALL code modifications.\n\n"
            "  ✗  NEVER write generated files to the project source directory.\n"
            "       All artifacts (exploits, scripts, configs) go to ~/.pawnlogic/workspace/.\n"
            "       Relative paths are auto-redirected. Absolute paths outside workspace are blocked.\n\n"
            "  ✗  NEVER call more than 3 tools concurrently. Plan them sequentially.\n\n"
            "  ✗  If list_dir or find_files has been called 2+ times without finding the target,\n"
            "       STOP and use /chat find <keyword> to check if you solved it in a past session.\n\n"

            "=== Workflow Guides ===\n"
            "Coding:\n"
            "  plan → find_files (max 1-2×) → read_file → patch_file → run_shell (verify) → git_op commit\n\n"
            "Code Search & Analysis:\n"
            "  · To find function calls/references, prefer run_shell('grep -rn <keyword> .') "
            "or a dedicated code-search tool.\n"
            "  · Never write a hard-coded Python search script and run it with run_code just "
            "to search text. That is inefficient and prone to hallucinated file content.\n\n"
            "Pwn/CTF:\n"
            "  pwn_env → inspect_binary → pwn_cyclic gen → pwn_debug (find offset) "
            "→ pwn_rop (gadgets) → pwn_libc → write exploit (run_code, use_venv=true) → test\n"
            "  NX enabled path: skip shellcode → use pwn_rop + pwn_one_gadget instead.\n\n"
            "Research:\n"
            "  web_search → fetch_url (full page) → synthesize → write_file\n\n"
            "History:\n"
            "  /chat find <keywords>  →  /chat view <id>  →  answer user\n\n"
            "Delegation (Smart Routing):\n"
            "  When reading more than 500 lines of code, analyzing huge logs, or doing deep "
            "web-wide search, MUST use delegate_task. Do not force it through your own context.\n\n"
            "Environment & Files:\n"
            "  WSL Paths: Windows Desktop in WSL is '/mnt/c/Users/<username>/Desktop'.\n"
            "    ALWAYS start paths with '/'. 'mnt/c/...' (no leading slash) is WRONG.\n"
            "  Binary Files: read_file is ONLY for plain text / source code.\n"
            "    For .doc / .docx → run_shell: 'pandoc -t plain file.docx' or 'catdoc file.doc'\n"
            "    For .pdf         → run_shell: 'pandoc -t plain file.pdf' or 'pdftotext file.pdf -'\n"
            "    NEVER call read_file on binary formats — it produces garbage output.\n\n"

            "=== ATOMIC COMMITS ===\n"
            "After every patch_file / write_file that passes <verify>:\n"
            "  run_shell (verify) → if PASS → git_op action='commit' message='feat/fix/refactor: ...'\n\n"

            "=== Global Skills Archive (GSA) Protocol ===\n"
            f"Skills file: {GLOBAL_SKILLS_PATH}\n\n"
            "WHEN TO TRIGGER: After a task is fully solved AND the <verify> command passed.\n"
            "Only trigger GSA if the solution involved non-trivial technical insight "
            "(not for trivial lookups).\n\n"
            "GSA CONSOLIDATION STEPS (execute in order, no skipping):\n\n"
            "  Step 1 — Read current skill categories:\n"
            f"    read_file_lines(path='{GLOBAL_SKILLS_PATH}', start_line=1, end_line=50)\n"
            "    → Extract all # level-1 headings you see.\n\n"
            "  Step 2 — Semantic classification (DYNAMIC, no fixed categories):\n"
            "    Look at the existing # headings you just read.\n"
            "    Ask: which heading does this solution belong to semantically?\n"
            "      · MATCH → use that existing heading (exact text).\n"
            "      · NO MATCH → create a new heading with format: 'EMOJI Domain/Subdomain'\n"
            "        Examples: '🛡️ Pwn/Stack', '🔗 ROP/Ret2Libc', '🐍 Python/Decorators',\n"
            "                  '📐 Algo/DP', '🏗️ C++/Templates', '🔑 Crypto/RSA'\n"
            "        The emoji must semantically reflect the domain.\n\n"
            "  Step 3 — Draft the skill block:\n"
            "    Write a ## Skill Name block with:\n"
            "      · What: one-line technical summary\n"
            "      · When: trigger condition\n"
            "      · How: key commands/code snippet (fenced, ≤ 20 lines)\n"
            "      · Gotcha: one critical pitfall (optional)\n\n"
            "  Step 4 — Duplicate check:\n"
            "    Search for '## <your skill name>' in the file content you already read.\n"
            "    · Found once → rename to '## <Skill Name> Case 2'\n"
            "    · Found as 'Case N' → use 'Case N+1'\n\n"
            "  Step 5 — Write to file:\n"
            "    Use patch_file with a SEARCH/REPLACE block:\n"
            "      · To append under existing category: SEARCH = last non-empty line of that section\n"
            "        REPLACE = original_line + '\\n\\n' + skill_block\n"
            "      · To create new category: SEARCH = last line of entire file\n"
            "        REPLACE = original_line + '\\n\\n# NEW_CATEGORY\\n\\n' + skill_block\n\n"
            "IMPORTANT: GSA is OPTIONAL and SILENT. Do NOT announce it to the user unless asked.\n"
            "Just execute it after task completion. If it fails, log internally and continue.\n\n"

            f"=== Current GSA Categories (from global_skills.md) ===\n"
            f"{skills_toc}\n"
            "(Use these headings for semantic matching in Step 2 above.)\n\n"

            # Dynamic injection: full text of skills relevant to the current task.
            + (
                f"=== GSA Relevant Skills (ranked by recency × usage × similarity) ===\n"
                f"{_relevant_skills_md}\n"
                "(Above skills were auto-retrieved for this query. "
                "If one solves your problem, call bump_skill(skill_name=...) after <verify> passes.)\n\n"
                if _relevant_skills_md else ""
            )

            # P6: Local skill engine retrieves relevant skills from ./skills/.
            + (
                f"=== Local Skills (from ./skills/ directory) ===\n"
                f"{_local_skills_md}\n"
                "(Above skills were auto-retrieved from local skill files. "
                "Follow their instructions if relevant to the current task.)\n\n"
                if _local_skills_md else ""
            )

            # Conflict warning injection.
            + (
                f"{_conflict_warning}\n\n"
                if _conflict_warning else ""
            )

            # ════════════════════════════════════════════════
            # Language lock: dynamic matching and anti-drift.
            # ════════════════════════════════════════════════
            + "<language_rule>\n"
            "DYNAMIC LANGUAGE MATCHING & ANTI-DRIFT:\n"
            "1. You MUST respond in the EXACT language used by the user in their latest prompt "
            "(Simplified Chinese or English).\n"
            "2. Your internal <plan> tags MAY use English for technical precision, "
            "regardless of the user's language.\n"
            "3. ANTI-DRIFT CRITICAL: The Pwn context contains heavy English terminology. "
            "Do NOT let this cause language drift. "
            "NEVER output Korean, Japanese, or any other unprompted languages.\n"
            "</language_rule>\n"
        )

        if knowledge_block:
            prompt += f"\n{knowledge_block}\n"
        if state_block:
            prompt += (
                f"\n=== Project State (.pawn_state.md) ===\n{state_block}\n"
                "=== End of Project State ===\n"
                "(Keep the above goals in mind even after /clear)\n"
            )

        if self.messages and self.messages[0]["role"] == "system":
            self.messages[0]["content"] = prompt
        else:
            self.messages.insert(0, {"role": "system", "content": prompt})

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
        import re
        results = []

        # 1. XML path: prefer complete <call>...</call> matches.
        _XML_FULL = re.compile(
            r'<call\s+name="(?P<name>[^"]+)">(?P<args_block>.*?)</call>',
            re.DOTALL,
        )
        # Tolerance: parse to string end when the model omits </call>.
        _XML_PARTIAL = re.compile(
            r'<call\s+name="(?P<name>[^"]+)">(?P<args_block>.*)',
            re.DOTALL,
        )
        # Match child tags inside XML argument blocks.
        _XML_PARAM = re.compile(
            r'<(?P<key>[a-zA-Z_][a-zA-Z0-9_]*)>(?P<val>.*?)</(?P=key)>',
            re.DOTALL,
        )

        xml_matches = list(_XML_FULL.finditer(text_buf))
        _used_partial = False
        if not xml_matches:
            xml_matches = list(_XML_PARTIAL.finditer(text_buf))
            _used_partial = bool(xml_matches)

        if xml_matches:
            for m in xml_matches:
                name = m.group("name").strip()
                args_block = m.group("args_block")
                if _used_partial:
                    print(c(GRAY, "  ⚙ [XML Parser] Unclosed </call> detected; tolerant completion enabled"))

                args: dict = {}
                for pm in _XML_PARAM.finditer(args_block):
                    key = pm.group("key").strip()
                    # No escaping: only strip surrounding whitespace.
                    val_raw = pm.group("val").strip()

                    # Basic type coercion.
                    if val_raw.lstrip("-").isdigit():
                        val: object = int(val_raw)
                    elif val_raw.lower() == "true":
                        val = True
                    elif val_raw.lower() == "false":
                        val = False
                    else:
                        val = val_raw   # Preserve raw strings, including newlines.

                    args[key] = val

                if name and args:
                    results.append({"name": name, "args": args, "_source": "xml"})

            if results:
                return results

        # 2. JSON fallback: tolerate hallucinated <tool_call>{...}</tool_call>.
        if "<tool_call>" in text_buf:
            match = re.search(r"<tool_call>\s*(\{.*)", text_buf, re.DOTALL)
            if match:
                json_str = match.group(1)
                json_str = re.sub(
                    r"</tool_call>.*$", "", json_str, flags=re.DOTALL
                ).strip()
                try:
                    # strict=False allows real newlines inside argument strings.
                    parsed_tc = json.loads(json_str, strict=False)
                    if "name" in parsed_tc and "arguments" in parsed_tc:
                        raw_args = parsed_tc["arguments"]
                        args_dict = (
                            raw_args
                            if isinstance(raw_args, dict)
                            else {"_raw_args": str(raw_args)}
                        )
                        results.append({
                            "name":    parsed_tc["name"],
                            "args":    args_dict,
                            "_source": "json",
                        })
                except json.JSONDecodeError as e:
                        # Dirty JSON rescue: try escaping unescaped inner quotes.
                        rescued = False
                        try:
                            import re as _re
                            # Greedily match the whole content field.
                            content_match = _re.search(r'"content"\s*:\s*"(.*)"\s*\}', json_str, _re.DOTALL)
                            if content_match:
                                bad_content = content_match.group(1)
                                # Escape inner quotes without double-escaping existing ones.
                                fixed_content = _re.sub(r'(?<!\\)"', r'\"', bad_content)
                                fixed_j_str = json_str.replace(bad_content, fixed_content)

                                parsed_tc = json.loads(fixed_j_str, strict=False)
                                if "name" in parsed_tc and "arguments" in parsed_tc:
                                    raw_args = parsed_tc["arguments"]
                                    args_dict = (
                                        raw_args
                                        if isinstance(raw_args, dict)
                                        else {"_raw_args": str(raw_args)}
                                    )
                                    results.append({
                                        "name": parsed_tc["name"],
                                        "args": args_dict,
                                        "_source": "json_rescued",
                                    })
                                    rescued = True
                        except Exception:
                            pass

                        if not rescued:
                            logger.error(
                                "Hybrid Parser: JSON fallback corrupted | "
                                "model={} session={} exc={!r}\n"
                                "--- RAW (truncated 4096) ---\n{}\n--- END ---",
                                self.model_alias, self.session_id[:8], e, json_str[:4096],
                            )
                            if _user_mode():
                                print(c(RED, "  ❌ System is busy. Please try again later."))
                            else:
                                print(c(RED, f"  ✗ [Hybrid Parser] JSON fallback parse failed: {e}"))
                        else:
                            print(c(YELLOW, "  ⚠ [Hybrid Parser] Dirty JSON detected and rescued with regex"))

        return results

    def _record_turn_usage(self, usage: dict[str, int]) -> None:
        pt = usage.get("prompt_tokens", 0)
        ct = usage.get("completion_tokens", 0)
        self._turn_prompt_tokens     += pt
        self._turn_completion_tokens += ct
        self.total_prompt_tokens     += pt
        self.total_completion_tokens += ct

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

    # Main turn loop.
    def run_turn(self, user_input: str):
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
            return

        cfg = self.model
        print(c(cfg["color"] + BOLD, f"[{self.model_alias.upper()}]"), end=" ", flush=True)

        # Reset per-turn accounting
        self._turn_prompt_tokens     = 0
        self._turn_completion_tokens = 0
        self._turn_tool_calls        = 0

        # P1: Time-aware initialization.
        dynamic_cfg = _dynamic_config()
        self._turn_start_time = time.monotonic()
        self._time_budget_sec = dynamic_cfg.get("time_budget_sec", 0)
        self._urgent_mode     = False
        if self._time_budget_sec > 0:
            _mins = self._time_budget_sec // 60
            _secs = self._time_budget_sec % 60
            print(c(GRAY, f"  ⏱  Time budget: {_mins}m{_secs}s"))

        max_iter           = dynamic_cfg["max_iter"]
        renderer           = _PlanRenderer()
        is_vision_model    = self.model.get("vision", False)
        current_max_tokens = 4096 if is_vision_model else dynamic_cfg["max_tokens"]
        if is_vision_model:
            print(c(YELLOW, "  ℹ Tool calls are disabled for vision models"))
            current_tools = None
        else:
            # MoE dynamic tool pruning.
            phase_whitelist = set(AGENT_PHASES.get(self.current_phase, []))
            current_tools = [
                s for s in TOOLS_SCHEMA
                if s.get("function", {}).get("name") in phase_whitelist
                or s.get("function", {}).get("name") in ("switch_phase", "bump_skill")  # ★
            ]
            if _debug_mode():
                print(c(GRAY,
                    f"  📡 [Phase:{self.current_phase}] "
                    f"Loaded {len(current_tools)} tools "
                    f"({', '.join(s['function']['name'] for s in current_tools)})"
                ))

        _plan_rejected    = 0
        _dir_search_count = 0
        _DIR_THRESHOLD    = 3

        # Logic Refresh module state.
        _LOGIC_REFRESH_INTERVAL = 20   # Trigger a phase summary every 20 iterations.
        _REPEAT_ERROR_THRESHOLD = 3    # Threshold for consecutive identical errors.
        _recent_cmd_errors: list[tuple[str, str]] = []  # (cmd, error) history.
        _repeat_error_count   = 0      # Current consecutive identical error count.

        # Repeated identical code-output detection.
        _REPEAT_CODE_THRESHOLD = 3     # Threshold for consecutive identical outputs.
        _recent_code_outputs: list[str] = []   # Recent tool-output hashes.
        _repeat_code_count    = 0      # Current consecutive identical output count.

        for iteration in range(max_iter):
            try:
                # Mid-turn checkpoint: save intermediate state every 5 iterations.
                if iteration > 0 and iteration % 5 == 0:
                    self._autosave()

                # P6.5: show loaded skill-pack status on the first iteration.
                if iteration == 0 and self._loaded_skill_packs:
                    if _user_mode():
                        print(c(GREEN, _skill_scanner.format_user_message(self._loaded_skill_packs)))
                    else:
                        for _sp in self._loaded_skill_packs:
                            print(c(CYAN, f"  📦 [Skill Pack] {_sp.get('name', '?')} v{_sp.get('version', '1.0')}"))
                            _sp_path = _sp.get("_path", "")
                            if _sp.get("guide"):
                                print(c(GRAY, f"     guide: {_sp_path}/{_sp['guide']}"))
                            if _sp.get("scripts"):
                                print(c(GRAY, f"     scripts: {', '.join(_sp['scripts'])}"))

                # P1: per-iteration time check.
                _remaining = self._time_remaining()
                if _remaining <= 0:
                    print(c(RED,
                        f"\n  ⏰ [Time Budget] Budget exhausted ({self._time_budget_sec}s); stopping task."
                    ))
                    logger.warning(
                        "Time budget exhausted | session={} budget={}s",
                        self.session_id[:8], self._time_budget_sec,
                    )
                    break

                if not self._urgent_mode and _remaining < _URGENT_THRESHOLD_SEC:
                    # Activate URGENT_MODE.
                    self._urgent_mode = True
                    print(c(RED,
                        f"  🚨 [URGENT_MODE] {_remaining:.0f}s remaining — "
                        f"switching to fast mode"
                    ))
                    logger.info(
                        "URGENT_MODE activated | session={} remaining={:.1f}s",
                        self.session_id[:8], _remaining,
                    )

                    # Inject the URGENT signal into context.
                    self.messages.append({
                        "role": "user",
                        "content": _URGENT_SIGNAL,
                    })

                    # Auto-switch to a fast model, preferring the same provider.
                    _urgent_target = None
                    if not is_fast_model(self.model_alias):
                        _urgent_target = find_fast_peer(self.model_alias)
                    if _urgent_target is None:
                        for _u_alias in _URGENT_MODEL_CANDIDATES:
                            if _u_alias in MODELS and _u_alias != self.model_alias:
                                _u_ok, _ = validate_api_key(_u_alias)
                                if _u_ok:
                                    _urgent_target = _u_alias
                                    break
                    if _urgent_target:
                        old_model = self.model_alias
                        self.model_alias = _urgent_target
                        print(c(MAGENTA,
                            f"  🚨 [URGENT] Model switched: "
                            f"{old_model} -> {_urgent_target} (fast response)"
                        ))
                        # Rebuild the tool list.
                        phase_whitelist = set(AGENT_PHASES.get(self.current_phase, []))
                        current_tools = [
                            s for s in TOOLS_SCHEMA
                            if s.get("function", {}).get("name") in phase_whitelist
                            or s.get("function", {}).get("name") in ("switch_phase", "bump_skill")
                        ]
                        current_max_tokens = min(current_max_tokens, 4096)

                # ════════════════════════════════════════════════
                # Logic Refresh: phase summary, redundancy cleanup, and error detection.
                # ════════════════════════════════════════════════

                # 1. Phase summary, triggered every N iterations.
                if iteration > 0 and iteration % _LOGIC_REFRESH_INTERVAL == 0:
                    # Collect recent tool observations.
                    _recent_obs = []
                    for _m in self.messages[-20:]:
                        if _m.get("role") == "tool" and _m.get("content"):
                            _recent_obs.append(_m["content"][:200])
                    if _recent_obs:
                        _obs_text = "\n".join(_recent_obs[-10:])
                        _summary_prompt = (
                            f"[Logic Refresh — Iteration {iteration}]\n"
                            f"Summarize the recent exploration path below in at most 5 sentences. "
                            f"Extract key findings, paths already ruled out, and the current best direction:\n\n{_obs_text}"
                        )
                        self.messages.append({"role": "user", "content": _summary_prompt})
                        if _debug_mode():
                            print(c(CYAN,
                                f"  🔄 [Logic Refresh] Phase summary triggered (iteration={iteration})"
                            ))
                        logger.info(
                            "Logic Refresh: phase summary triggered | "
                            "session={} iteration={} obs_count={}",
                            self.session_id[:8], iteration, len(_recent_obs),
                        )

                # 2. Redundant data cleanup: merge repeated ls/cat-style errors.
                _REDUNDANT_PATTERNS = (
                    "No such file or directory",
                    "Permission denied",
                    "command not found",
                    "is a directory",
                    "Not a directory",
                )
                _seen_errors: dict[str, int] = {}
                _msgs_to_compact = []
                for _mi, _m in enumerate(self.messages[1:], 1):  # skip system
                    if _m.get("role") != "tool":
                        continue
                    _content = _m.get("content") or ""
                    for _rp in _REDUNDANT_PATTERNS:
                        if _rp in _content and len(_content) < 300:
                            _key = _rp
                            _seen_errors[_key] = _seen_errors.get(_key, 0) + 1
                            if _seen_errors[_key] > 3:
                                _msgs_to_compact.append(_mi)
                            break
                # Compact repeated errors into one-line placeholders.
                for _mi in reversed(_msgs_to_compact):
                    _old = self.messages[_mi]
                    _old_content = _old.get("content") or ""
                    # Only compact short errors; preserve long output.
                    if len(_old_content) < 300:
                        self.messages[_mi]["content"] = (
                            f"(compacted: {_old_content[:60]}...) — similar errors have appeared "
                            f"{_seen_errors.get(_REDUNDANT_PATTERNS[0], '?')} times"
                        )

                # 3. Repeated error detection: identical command and error 3 times.
                if _repeat_error_count >= _REPEAT_ERROR_THRESHOLD:
                    _anti_loop_msg = (
                        "[System] The current path appears blocked: detected "
                        f"{_repeat_error_count} consecutive identical command errors. "
                        "Re-evaluate the exploit logic and consider these bypass directions:\n"
                        "  1. Symlink bypass (ln -s)\n"
                        "  2. open_basedir bypass (php -d open_basedir=/)\n"
                        "  3. Path encoding bypass (../ ./ ..%2f)\n"
                        "  4. Switch tool or attack vector\n"
                        "  5. Ask the user to confirm target environment details"
                    )
                    self.messages.append({"role": "user", "content": _anti_loop_msg})
                    if _debug_mode():
                        print(c(YELLOW,
                            f"  🔁 [Anti-Loop] Detected {_repeat_error_count} repeated errors; injected bypass hint"
                        ))
                    logger.warning(
                        "Anti-Loop: repeated error detected | "
                        "session={} iteration={} count={}",
                        self.session_id[:8], iteration, _repeat_error_count,
                    )
                    _repeat_error_count = 0  # Reset to avoid repeated injection.

                # API call with empty-response retry and exponential backoff.
                _api_retry = 0
                _API_RETRY_MAX = 3
                text_buf = ""; tc_buf = {}

                # Sliding-window view: send trimmed messages without mutating self.messages.
                _api_msgs = self._build_api_messages()

                while True:
                    _api_result = self._consume_api_stream_attempt(
                        _api_msgs, current_tools, current_max_tokens, renderer, iteration
                    )
                    if _api_result.error:
                        self.messages.pop(); return

                    text_buf, tc_buf, reasoning_buf = self._finalize_api_stream_result(
                        _api_result, renderer, iteration
                    )

                    # Empty-response detection with exponential-backoff retry.
                    # Usage-only and hidden reasoning-only deltas are not user-visible
                    # answers, even when the provider reports completion tokens.
                    _empty_response = not text_buf.strip() and not tc_buf

                    if not _empty_response:
                        break   # Valid response; exit retry loop.

                    _api_retry += 1
                    if _api_retry >= _API_RETRY_MAX:
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
                        break   # Exit retry loop and proceed to the next iteration.

                    _wait = min(2 ** _api_retry, 8)
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
                    continue   # Retry the API call.

                # If retries are exhausted and the response is still empty, skip tool execution.
                if _empty_response and _api_retry >= _API_RETRY_MAX:
                    continue   # Proceed to the next iteration.

                if not tc_buf:
                    # thinking-mode fix: store reasoning_content with the assistant
                    # message so the next API call can send it back unchanged.
                    _asst_msg: dict = {"role": "assistant", "content": text_buf}
                    if reasoning_buf:
                        _asst_msg["reasoning_content"] = reasoning_buf
                    self.messages.append(_asst_msg)
                    self._print_turn_summary()
                    self._autosave(); return

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
                _plan_signal_injected = False
                _missing_required_plan = _tool_call_missing_plan(text_buf, tc_buf)

                if _missing_required_plan:
                    _plan_rejected += 1
                else:
                    _plan_rejected = 0

                if _plan_rejected > _MAX_SOFT_CORRECTIONS:
                    # Hard stop after soft intercepts are exhausted.
                    print(c(RED,
                            f"  ⛔ [CoT Guard] Missing <plan> for {_plan_rejected} consecutive attempts; task stopped."
                            ))
                    print(c(GRAY,
                            "  Suggestions: 1. Simplify the instruction  2. Switch to a stronger model (/model ds-v4-pro)"
                            ))
                    logger.warning(
                        "CoT Guard: hard kill triggered | "
                        "model={} session={} iteration={} plan_rejected={}",
                        self.model_alias, self.session_id[:8],
                        iteration, _plan_rejected,
                    )
                    if self.messages and self.messages[-1]["role"] == "user":
                        self.messages.pop()  # Remove the latest user message to keep context clean.
                    return

                elif _plan_rejected > 0:
                    # Soft intercept: tools still run; inject correction signal after results.
                    if _debug_mode():
                        print(c(YELLOW,
                            f"  💭 [CoT Soft #{_plan_rejected}/{_MAX_SOFT_CORRECTIONS}] "
                            "Missing <plan> detected; tools will run and the correction signal will be injected after results..."
                        ))
                    logger.debug(
                        "CoT Guard: soft intercept #{} | model={} session={} iteration={}",
                        _plan_rejected, self.model_alias, self.session_id[:8], iteration,
                    )
                    _plan_signal_injected = True

                # Module 1B: concurrent call truncation.
                if len(tc_buf) > _MAX_CONCURRENT_TOOLS:
                    orig = len(tc_buf)
                    kept = sorted(tc_buf.keys())[:_MAX_CONCURRENT_TOOLS]
                    tc_buf = {k: tc_buf[k] for k in kept}
                    if _debug_mode():
                        print(c(YELLOW, f"  ✂ [Concurrency Limit] Truncated {orig} tool calls to the first {_MAX_CONCURRENT_TOOLS}."))
                    logger.warning(
                        "Concurrent tool limit | model={} session={} original={} kept={}",
                        self.model_alias, self.session_id[:8], orig, _MAX_CONCURRENT_TOOLS,
                    )


                # thinking-mode fix: persist reasoning_content with the assistant
                # message so strict reasoning models can receive it back unchanged.
                _asst_msg: dict = {
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

                # Execute all tools.
                for i in sorted(tc_buf):
                    tc = tc_buf[i];
                    name = tc["name"]

                    # Prefer the zero-escape dict passed through by XML/Hybrid Parser.
                    if "_args_parsed" in tc:
                        fn_args = tc["_args_parsed"]
                    else:
                        fn_args = {}
                        if tc["args"].strip():
                            try:
                                fn_args = json.loads(tc["args"])
                            except json.JSONDecodeError:
                                try:
                                    fn_args = json.loads(tc["args"].strip().lstrip("\ufeff"))
                                except Exception:
                                    fn_args = {"_raw_args": tc["args"]}

                    preview  = ", ".join(f"{k}={repr(v)[:40]}" for k, v in fn_args.items())
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
                        target = fn_args.get("phase", "").upper()
                        reason = fn_args.get("reason", "(no reason provided)")
                        if target in AGENT_PHASES:
                            old_phase = self.current_phase
                            self.current_phase = target
                            # Rebuild the dynamic tool list for the next iteration.
                            phase_whitelist = set(AGENT_PHASES[target])
                            current_tools = [
                                s for s in TOOLS_SCHEMA
                                if s.get("function", {}).get("name") in phase_whitelist
                                or s.get("function", {}).get("name") in ("switch_phase", "bump_skill")  # ★
                            ]
                            result = (
                                f"[Phase Switch] {old_phase} → {target}\n"
                                f"Reason: {reason}\n"
                                f"Now available: {', '.join(phase_whitelist)}\n"
                                f"switch_phase is always available.\n"
                                f"Reload: {len(current_tools)} tools active."
                            )
                            print(c(MAGENTA,
                                f"  🔀 [Phase Switch] {old_phase} → {target}  ({reason[:60]})"
                            ))
                            logger.info(
                                "Phase switch | model={} session={} {} → {} reason={}",
                                self.model_alias, self.session_id[:8],
                                old_phase, target, reason,
                            )
                            # Refresh the phase-awareness block in the system prompt.
                            self._reset_system_prompt()
                        else:
                            result = (
                                f"ERROR: Unknown phase '{target}'. "
                                f"Available: {', '.join(AGENT_PHASES.keys())}"
                            )

                    else:
                        _VERBOSE_TOOLS = {
                            "read_file", "read_file_lines",
                            "run_shell", "run_code",
                            "pwn_debug", "pwn_rop", "pwn_disasm", "pwn_cyclic", "pwn_libc",
                            "inspect_binary", "web_search", "fetch_url", "find_refs",
                        }

                        # P0.6: pre-flight failure audit for dangerous tools.
                        _failure_warning = ""
                        if name in _AUDITED_TOOLS:
                            try:
                                _fail_rows = check_failure(name, args_keywords=preview[:200], limit=3)
                                if _fail_rows:
                                    _failure_warning = format_failures_for_prompt(_fail_rows)
                                    if _debug_mode():
                                        print(c(YELLOW,
                                            f"  ⚠ [Anti-Pattern] {name} has "
                                            f"{len(_fail_rows)} historical failure records"
                                        ))
                            except Exception:
                                pass

                        # Audit timing.
                        _t0 = time.monotonic()
                        _audit_ok = True
                        try:
                            result = TOOL_MAP[name](fn_args) if name in TOOL_MAP else f"ERROR: Unknown tool '{name}'"

                            # P0.7: semantic failure detection. The tool may not raise,
                            # but result content can still indicate failure.
                            _SEMANTIC_FAILURE_SIGNALS = (
                                "ERROR:", "Traceback", "Segmentation fault", "SIGSEGV",
                                "NameError", "SyntaxError", "TypeError", "AttributeError",
                                "ImportError", "ModuleNotFoundError", "FileNotFoundError",
                                "PermissionError", "RuntimeError", "ValueError",
                                "panic", "FATAL", "core dumped", "Aborted",
                                "Compile failed", "Compilation failed", "exit 1", "exit 2", "exit 126", "exit 127",
                                "exit 134", "exit 139", "command not found",
                            )
                            if any(sig in str(result) for sig in _SEMANTIC_FAILURE_SIGNALS):
                                _audit_ok = False

                        except Exception as _tool_exc:
                            _raw_err = f"ERROR: {type(_tool_exc).__name__}: {_tool_exc}"
                            result = user_friendly_error(_raw_err) if _user_mode() else _raw_err
                            _audit_ok = False
                        _elapsed_ms = int((time.monotonic() - _t0) * 1000)

                        # P0.7: automatic failure recording.
                        if not _audit_ok and name in _AUDITED_TOOLS:
                            try:
                                _error_type = ""
                                _r = str(result)
                                _rl = _r.lower()
                                if "timeoutexpired" in _rl or "timeout" in _rl:
                                    _error_type = "Timeout"
                                elif "segmentation fault" in _rl or "sigsegv" in _rl or "core dumped" in _rl:
                                    _error_type = "Segfault"
                                elif "compile failed" in _rl or "compilation failed" in _rl or "compileerror" in _rl:
                                    _error_type = "CompileError"
                                elif "memoryerror" in _rl or "memory limit" in _rl:
                                    _error_type = "MemoryError"
                                elif "syntaxerror" in _rl or "indentationerror" in _rl:
                                    _error_type = "SyntaxError"
                                elif "nameerror" in _rl or "attributeerror" in _rl or "typeerror" in _rl:
                                    _error_type = "LogicError"
                                elif "importerror" in _rl or "modulenotfounderror" in _rl:
                                    _error_type = "MissingModule"
                                elif "filenotfounderror" in _rl or "command not found" in _rl:
                                    _error_type = "NotFound"
                                elif "permissionerror" in _rl:
                                    _error_type = "Permission"
                                elif "panic" in _rl or "fatal" in _rl:
                                    _error_type = "Panic"
                                elif "exit 139" in _r or "aborted" in _rl:
                                    _error_type = "Crash"
                                elif "traceback" in _rl:
                                    _error_type = "PythonError"
                                elif "ERROR" in _r:
                                    _error_type = "RuntimeError"
                                else:
                                    _error_type = "UnknownFailure"

                                _fid = write_failure(
                                    tool_name    = name,
                                    args_summary = preview[:200],
                                    error_msg    = result[:500],
                                    error_type   = _error_type,
                                    session_id   = self.session_id,
                                )

                                # P0.9: sink repeated same-class failures to GSA.
                                if _error_type:
                                    _fail_count = count_failure(name, _error_type)
                                    if _fail_count >= 3:
                                        _ok, _msg = sink_failure_to_gsa(
                                            tool_name   = name,
                                            error_type  = _error_type,
                                            error_msg   = result[:300],
                                            args_preview= preview[:200],
                                        )
                                        if _ok and _debug_mode():
                                            print(c(YELLOW, f"  📝 [GSA Sink] {_msg}"))
                            except Exception:
                                pass  # Failure recording must not block the main flow.

                        # Append pre-flight audit warnings to the tool result.
                        if _failure_warning:
                            result = result + "\n\n" + _failure_warning

                        # Write audit log.
                        try:
                            audit_tool_call(
                                tool_name    = name,
                                args_summary = preview[:200],
                                result_len   = len(result),
                                elapsed_ms   = _elapsed_ms,
                                session_id   = self.session_id,
                                model_alias  = self.model_alias,
                                iteration    = iteration,
                                success      = _audit_ok,
                            )
                        except Exception:
                            pass  # Audit logging must not block the main flow.

                        if _user_mode() or name in _VERBOSE_TOOLS:
                            result = smart_truncate(result, head=30, tail=30)
                        else:
                            limit = _dynamic_config()["tool_max_chars"]
                            if len(result) > limit:
                                result = result[:limit//2] + f"\n...[truncated to {limit} chars]...\n" + result[-limit//4:]

                    # Audit counter
                    self._turn_tool_calls  += 1
                    self.total_tool_calls  += 1

                    # Directory-search count and auto-intuition retrieval.
                    if name in ("list_dir", "find_files"):
                        _dir_search_count += 1
                        if _dir_search_count >= _DIR_THRESHOLD:
                            search_query = (
                                fn_args.get("pattern") or fn_args.get("path") or ""
                            ).strip().strip("*./")
                            auto_result = ""
                            if search_query:
                                print(c(GRAY,
                                    f"  🧠 [Auto-Intuition] Directory search count {_dir_search_count}; "
                                    f"searching history for: '{search_query}'"
                                ))
                                auto_result = self._auto_intuitive_search(search_query)
                            hint = (
                                f"\n[System hint — directory search has run {_dir_search_count} consecutive times] "
                                "Switch strategy: use /chat find <keyword> to search history, "
                                "or tell the user the file path is unknown."
                            )
                            result = result + hint + auto_result
                    else:
                        _dir_search_count = 0

                    self.messages.append({
                        "role": "tool", "tool_call_id": tc["id"], "content": result,
                    })

                    # Logic Refresh: repeated error tracking.
                    if name == "run_shell" and not _audit_ok:
                        _cmd_key = fn_args.get("command", "") or preview[:80]
                        _err_sig = ""
                        for _sig in ("ERROR:", "Permission denied", "No such file",
                                     "command not found", "Segmentation fault",
                                     "timeout"):
                            if _sig in str(result):
                                _err_sig = _sig
                                break
                        if _err_sig:
                            _pair = (_cmd_key[:60], _err_sig)
                            if _recent_cmd_errors and _recent_cmd_errors[-1] == _pair:
                                _repeat_error_count += 1
                            else:
                                _repeat_error_count = 1
                            _recent_cmd_errors.append(_pair)
                            # Keep the latest 20 entries.
                            if len(_recent_cmd_errors) > 20:
                                _recent_cmd_errors = _recent_cmd_errors[-20:]

                    # Repeated identical code-output detection to prevent loops.
                    if name in ("run_shell", "run_code", "write_file", "patch_file"):
                        import hashlib
                        _result_hash = hashlib.md5(
                            str(result)[:500].encode("utf-8", errors="ignore")
                        ).hexdigest()[:12]
                        if _recent_code_outputs and _recent_code_outputs[-1] == _result_hash:
                            _repeat_code_count += 1
                        else:
                            _repeat_code_count = 1
                        _recent_code_outputs.append(_result_hash)
                        if len(_recent_code_outputs) > 10:
                            _recent_code_outputs = _recent_code_outputs[-10:]

                        if _repeat_code_count >= _REPEAT_CODE_THRESHOLD:
                            _anti_code_loop = (
                                f"[System] Detected {_repeat_code_count} consecutive nearly identical tool outputs. "
                                "The current path may be looping; stop and re-evaluate immediately:\n"
                                "  1. Are you repeating commands already known to fail?\n"
                                "  2. Do you need a different attack vector or tool?\n"
                                "  3. Should you ask the user to confirm the target environment?\n"
                                "Explain the new approach in <plan> before continuing."
                            )
                            self.messages.append({"role": "user", "content": _anti_code_loop})
                            print(c(YELLOW,
                                f"  🔁 [Anti-Code-Loop] {_repeat_code_count} identical outputs detected; injected re-evaluation hint"
                            ))
                            logger.warning(
                                "Anti-Code-Loop: repeated output | "
                                "session={} iteration={} count={} tool={}",
                                self.session_id[:8], iteration, _repeat_code_count, name,
                            )
                            _repeat_code_count = 0

                # ════════════════════════════════════════════════
                # After all tool results are appended, inject PLAN_MISSING if a
                # soft intercept fired. The model sees results first, then corrects.
                # ════════════════════════════════════════════════
                if _plan_signal_injected:
                    self.messages.append({
                        "role":    "user",
                        "content": _PLAN_MISSING_SIGNAL,
                    })
                    print(c(GRAY,
                        "  🔄 [CoT Self-Correction] PLAN_MISSING correction signal injected; "
                        "the model will self-correct next iteration."
                    ))

            except KeyboardInterrupt:
                self._autosave()
                raise TurnInterrupted()

        print(c(RED, f"\n[Reached max_iter={max_iter}; use /mid, /deep, or /iter <n> to raise it]"))
        logger.warning(
            "max_iter reached | model={} session={} max_iter={}",
            self.model_alias, self.session_id[:8], max_iter,
        )
        self._print_turn_summary()
        self._autosave()

    # ── Per-turn usage summary ───────────────────────────
    def _print_turn_summary(self):
        """Print token and tool-call summary after each turn."""
        pt = self._turn_prompt_tokens
        ct = self._turn_completion_tokens
        tt = self._turn_tool_calls
        if pt + ct + tt == 0:
            return   # nothing to show (no usage data from this provider)
        tot_pt = self.total_prompt_tokens
        tot_ct = self.total_completion_tokens
        tot_tt = self.total_tool_calls
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
    def _autosave(self):
        # Turn count increments on every call, regardless of success, interrupt,
        # or max_iter exhaustion. _maybe_autoname requires at least 2 turns.
        self._turn_count += 1
        msgs_snapshot = [dict(m) for m in self.messages]
        sid, model_alias, cwd, workspace_dir, cfg_snap = (
            self.session_id, self.model_alias, self.cwd, self.workspace_dir,
            dict(_dynamic_config())
        )
        def _do():
            if not self._save_lock.acquire(blocking=False): return
            try:
                from core.memory import upsert_session, save_messages
                upsert_session(
                    sid, "", model_alias, cwd, cfg_snap,
                    workspace_dir=workspace_dir,
                )
                save_messages(sid, msgs_snapshot)
            except Exception as _autosave_exc:
                # Log autosave failures instead of silently dropping them.
                logger.error(
                    "Autosave failed | session={} model={} exc={!r}",
                    sid[:8], model_alias, _autosave_exc,
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
            finally:
                try:
                    self._naming_lock.release()
                except Exception:
                    pass   # Ignore rare cases where the lock was already released.

        threading.Thread(target=_do, daemon=True, name=f"name-{sid[:8]}").start()
