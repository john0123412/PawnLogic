"""Data contracts for tool execution extraction."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import time
from typing import Any

from core.tool_routing import phase_tool_names, select_phase_tools


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    """Runtime context passed to extracted tool execution helpers."""

    session_id: str
    model_alias: str
    iteration: int
    current_phase: str
    user_mode: bool = False
    debug_mode: bool = False

    @property
    def session_label(self) -> str:
        """Return the short session id used by existing logs."""
        return self.session_id[:8]


@dataclass(slots=True)
class ToolExecutionResult:
    """Result envelope returned by one executed tool call."""

    tool_call_id: str
    tool_name: str
    content: str
    audit_ok: bool = True
    elapsed_ms: int = 0
    args_preview: str = ""
    failure_warning: str = ""
    error_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def tool_message(self) -> dict[str, str]:
        """Return the chat message shape expected by provider APIs."""
        return {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            "content": self.content,
        }


@dataclass(slots=True)
class PhaseSwitchResult:
    """Result envelope for a switch_phase tool call."""

    switched: bool
    old_phase: str
    target_phase: str
    reason: str
    content: str
    active_tools: list[dict] = field(default_factory=list)
    available_tool_names: set[str] = field(default_factory=set)


@dataclass(slots=True)
class ToolFailurePrecheckResult:
    """Historical failure precheck result for a tool call."""

    warning: str = ""
    failure_count: int = 0


@dataclass(slots=True)
class ToolFailureRecordResult:
    """Persistence result for a failed tool call."""

    error_type: str = ""
    recorded: bool = False
    failure_id: Any = None
    gsa_sunk: bool = False
    gsa_message: str = ""


SEMANTIC_FAILURE_SIGNALS = (
    "ERROR:",
    "Traceback",
    "Segmentation fault",
    "SIGSEGV",
    "NameError",
    "SyntaxError",
    "TypeError",
    "AttributeError",
    "ImportError",
    "ModuleNotFoundError",
    "FileNotFoundError",
    "PermissionError",
    "RuntimeError",
    "ValueError",
    "panic",
    "FATAL",
    "core dumped",
    "Aborted",
    "Compile failed",
    "Compilation failed",
    "exit 1",
    "exit 2",
    "exit 126",
    "exit 127",
    "exit 134",
    "exit 139",
    "command not found",
)


def result_has_semantic_failure(content: object) -> bool:
    """Return whether tool output text indicates a failed execution."""
    text = str(content)
    return any(signal in text for signal in SEMANTIC_FAILURE_SIGNALS)


def classify_tool_failure(content: object) -> str:
    """Classify a failed tool result using the existing heuristic order."""
    text = str(content)
    lowered = text.lower()
    if "timeoutexpired" in lowered or "timeout" in lowered:
        return "Timeout"
    if "segmentation fault" in lowered or "sigsegv" in lowered or "core dumped" in lowered:
        return "Segfault"
    if "compile failed" in lowered or "compilation failed" in lowered or "compileerror" in lowered:
        return "CompileError"
    if "memoryerror" in lowered or "memory limit" in lowered:
        return "MemoryError"
    if "syntaxerror" in lowered or "indentationerror" in lowered:
        return "SyntaxError"
    if "nameerror" in lowered or "attributeerror" in lowered or "typeerror" in lowered:
        return "LogicError"
    if "importerror" in lowered or "modulenotfounderror" in lowered:
        return "MissingModule"
    if "filenotfounderror" in lowered or "command not found" in lowered:
        return "NotFound"
    if "permissionerror" in lowered:
        return "Permission"
    if "panic" in lowered or "fatal" in lowered:
        return "Panic"
    if "exit 139" in text or "aborted" in lowered:
        return "Crash"
    if "traceback" in lowered:
        return "PythonError"
    if "ERROR" in text:
        return "RuntimeError"
    return "UnknownFailure"


def precheck_tool_failures(
    *,
    tool_name: str,
    args_preview: str,
    is_audited: bool,
    check_failure_func: Callable[..., Sequence[object]],
    format_failures_func: Callable[[Sequence[object]], str],
    limit: int = 3,
) -> ToolFailurePrecheckResult:
    """Look up historical failures for audited tools."""
    if not is_audited:
        return ToolFailurePrecheckResult()

    try:
        rows = check_failure_func(tool_name, args_keywords=args_preview[:200], limit=limit)
        if not rows:
            return ToolFailurePrecheckResult()
        return ToolFailurePrecheckResult(
            warning=format_failures_func(rows),
            failure_count=len(rows),
        )
    except Exception:
        return ToolFailurePrecheckResult()


def execute_tool_handler(
    *,
    tool_call_id: str,
    tool_name: str,
    fn_args: dict,
    handler: Callable[[dict], object] | None,
    context: ToolExecutionContext,
    args_preview: str = "",
    user_error_formatter: Callable[[str], str] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ToolExecutionResult:
    """Execute one non-phase tool handler and return its result envelope."""
    started_at = clock()
    audit_ok = True
    try:
        content = handler(fn_args) if handler else f"ERROR: Unknown tool '{tool_name}'"
        if result_has_semantic_failure(content):
            audit_ok = False
    except Exception as exc:
        raw_error = f"ERROR: {type(exc).__name__}: {exc}"
        if context.user_mode and user_error_formatter is not None:
            content = user_error_formatter(raw_error)
        else:
            content = raw_error
        audit_ok = False

    elapsed_ms = int((clock() - started_at) * 1000)
    return ToolExecutionResult(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        content=content,
        audit_ok=audit_ok,
        elapsed_ms=elapsed_ms,
        args_preview=args_preview,
    )


def record_tool_failure(
    *,
    tool_name: str,
    args_preview: str,
    content: object,
    audit_ok: bool,
    is_audited: bool,
    session_id: str,
    write_failure_func: Callable[..., Any],
    count_failure_func: Callable[[str, str], int],
    sink_failure_func: Callable[..., tuple[bool, str]],
) -> ToolFailureRecordResult:
    """Persist semantic failures and sink repeated failures to GSA."""
    if audit_ok or not is_audited:
        return ToolFailureRecordResult()

    content_text = str(content)
    error_type = classify_tool_failure(content_text)
    record = ToolFailureRecordResult(error_type=error_type)

    try:
        record.failure_id = write_failure_func(
            tool_name=tool_name,
            args_summary=args_preview[:200],
            error_msg=content_text[:500],
            error_type=error_type,
            session_id=session_id,
        )
        record.recorded = True
    except Exception:
        return record

    try:
        fail_count = count_failure_func(tool_name, error_type)
        if fail_count >= 3:
            ok, message = sink_failure_func(
                tool_name=tool_name,
                error_type=error_type,
                error_msg=content_text[:300],
                args_preview=args_preview[:200],
            )
            record.gsa_sunk = bool(ok)
            record.gsa_message = message if ok else ""
    except Exception:
        pass

    return record


def execute_phase_switch(
    *,
    fn_args: dict,
    current_phase: str,
    agent_phases: Mapping[str, Sequence[str]],
    schemas: Sequence[dict],
) -> PhaseSwitchResult:
    """Resolve a switch_phase request without mutating session state."""
    target = fn_args.get("phase", "").upper()
    reason = fn_args.get("reason", "(no reason provided)")

    if target not in agent_phases:
        return PhaseSwitchResult(
            switched=False,
            old_phase=current_phase,
            target_phase=target,
            reason=reason,
            content=(
                f"ERROR: Unknown phase '{target}'. "
                f"Available: {', '.join(agent_phases.keys())}"
            ),
        )

    available_tool_names = phase_tool_names(agent_phases, target)
    active_tools = select_phase_tools(schemas, agent_phases, target)
    return PhaseSwitchResult(
        switched=True,
        old_phase=current_phase,
        target_phase=target,
        reason=reason,
        content=(
            f"[Phase Switch] {current_phase} → {target}\n"
            f"Reason: {reason}\n"
            f"Now available: {', '.join(available_tool_names)}\n"
            f"switch_phase is always available.\n"
            f"Reload: {len(active_tools)} tools active."
        ),
        active_tools=active_tools,
        available_tool_names=available_tool_names,
    )


__all__ = [
    "SEMANTIC_FAILURE_SIGNALS",
    "PhaseSwitchResult",
    "ToolExecutionContext",
    "ToolExecutionResult",
    "ToolFailurePrecheckResult",
    "ToolFailureRecordResult",
    "classify_tool_failure",
    "execute_phase_switch",
    "execute_tool_handler",
    "precheck_tool_failures",
    "record_tool_failure",
    "result_has_semantic_failure",
]
