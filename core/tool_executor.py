"""Data contracts for tool execution extraction."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import json
import threading
import time
from typing import Any

from core.tool_registry import ResolvedTool, ToolSpec
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


ToolExecutionPolicy = Callable[
    [ToolSpec, str, Mapping[str, Any], ToolExecutionContext], str | None
]


def allow_registered_tool_execution(
    _spec: ToolSpec,
    _owner: str,
    _arguments: Mapping[str, Any],
    _context: ToolExecutionContext,
) -> None:
    """Allow a complete, owned ToolSpec when no host policy is installed."""


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

    @property
    def outcome(self) -> ToolExecutionOutcome:
        """Return the explicit internal outcome without changing message shape."""
        return ToolExecutionOutcome(
            status="success" if self.audit_ok else "failed",
            content=self.content,
            error_type=self.error_type or None,
            side_effect=bool(self.metadata.get("side_effect", False)),
        )

    def tool_message(self) -> dict[str, str]:
        """Return the chat message shape expected by provider APIs."""
        return {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            "content": self.content,
        }


@dataclass(frozen=True, slots=True)
class ToolExecutionOutcome:
    """Stable internal success/failure contract for one tool execution."""

    status: str
    content: str
    error_type: str | None = None
    side_effect: bool = False


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


def resolve_tool_arguments(tool_call: Mapping[str, Any]) -> dict:
    """Resolve provider or hybrid-parser tool arguments into a dict."""
    if "_args_parsed" in tool_call:
        return tool_call["_args_parsed"]

    fn_args: dict = {}
    raw_args = tool_call["args"]
    if raw_args.strip():
        try:
            fn_args = json.loads(raw_args)
        except json.JSONDecodeError:
            try:
                fn_args = json.loads(raw_args.strip().lstrip("\ufeff"))
            except Exception:
                fn_args = {"_raw_args": raw_args}
    return fn_args


def preview_tool_arguments(fn_args: Mapping[str, Any]) -> str:
    """Return the compact argument preview used in tool logs and audit records."""
    return ", ".join(f"{key}={repr(value)[:40]}" for key, value in fn_args.items())


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


DEFAULT_TOOL_WATCHDOG_SECONDS = 600.0


def _run_handler_with_watchdog(
    handler: Callable[[dict], object],
    fn_args: dict,
    tool_name: str,
    timeout_seconds: float,
) -> str:
    """Run one sync handler on a daemon thread under a hard deadline.

    A wedged handler must never freeze the agent loop. Python threads cannot
    be killed, so on expiry the worker thread is abandoned (it may keep
    running in the background until process exit) and a synthetic error
    result is returned so the model can continue the task.
    """
    finished = threading.Event()
    result_holder: list[object] = []
    error_holder: list[BaseException] = []

    def _worker() -> None:
        try:
            result_holder.append(handler(fn_args))
        except BaseException as exc:  # Relay KeyboardInterrupt too.
            error_holder.append(exc)
        finally:
            finished.set()

    worker = threading.Thread(
        target=_worker,
        name=f"pawn-tool-{tool_name}",
        daemon=True,
    )
    worker.start()
    if not finished.wait(timeout_seconds):
        return (
            f"ERROR: Tool '{tool_name}' hit its hard timeout "
            f"({timeout_seconds:g}s watchdog limit) and was abandoned. Its "
            "background thread may still be running. Continue the task with "
            "other approaches; avoid re-running the same blocking call unchanged."
        )
    if error_holder:
        raise error_holder[0]
    return str(result_holder[0]) if result_holder else ""


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
    hard_timeout_seconds: float | None = None,
) -> ToolExecutionResult:
    """Execute one non-phase tool handler and return its result envelope.

    When ``hard_timeout_seconds`` is set, the handler runs on a daemon thread
    under a watchdog; a wedged handler is abandoned with an error result so
    the agent loop keeps running instead of freezing forever.
    """
    started_at = clock()
    audit_ok = True
    try:
        content: object
        if handler is None:
            content = f"ERROR: Unknown tool '{tool_name}'"
        elif hard_timeout_seconds is not None:
            content = _run_handler_with_watchdog(
                handler, fn_args, tool_name, hard_timeout_seconds
            )
        else:
            content = handler(fn_args)
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
    content_text = str(content)
    return ToolExecutionResult(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        content=content_text,
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


def _blocked_tool_execution(
    *,
    tool_call_id: str,
    tool_name: str,
    content: str,
    args_preview: str,
    error_type: str,
) -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        content=content,
        audit_ok=False,
        args_preview=args_preview,
        error_type=error_type,
    )


@dataclass(slots=True)
class ToolExecutor:
    """Thin orchestration layer over extracted tool execution helpers."""

    resolve_tool: Callable[[str], ResolvedTool | None]
    agent_phases: Mapping[str, Sequence[str]]
    schema_snapshot: Callable[[], Sequence[dict]]
    check_failure_func: Callable[..., Sequence[object]]
    format_failures_func: Callable[[Sequence[object]], str]
    write_failure_func: Callable[..., Any]
    count_failure_func: Callable[[str, str], int]
    sink_failure_func: Callable[..., tuple[bool, str]]
    user_error_formatter: Callable[[str], str] | None = None
    execution_policy: ToolExecutionPolicy = allow_registered_tool_execution
    hard_timeout_seconds: float | None = None

    def execute_phase_switch(
        self,
        *,
        fn_args: dict,
        current_phase: str,
    ) -> PhaseSwitchResult:
        return execute_phase_switch(
            fn_args=fn_args,
            current_phase=current_phase,
            agent_phases=self.agent_phases,
            schemas=self.schema_snapshot(),
        )

    def precheck_failures(
        self,
        *,
        tool_name: str,
        args_preview: str,
        is_audited: bool,
    ) -> ToolFailurePrecheckResult:
        return precheck_tool_failures(
            tool_name=tool_name,
            args_preview=args_preview,
            is_audited=is_audited,
            check_failure_func=self.check_failure_func,
            format_failures_func=self.format_failures_func,
        )

    def execute_handler(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        fn_args: dict,
        context: ToolExecutionContext,
        args_preview: str = "",
    ) -> ToolExecutionResult:
        try:
            resolved = self.resolve_tool(tool_name)
        except Exception:
            return _blocked_tool_execution(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                content=(
                    f"ERROR: Tool '{tool_name}' blocked because metadata "
                    "resolution failed."
                ),
                args_preview=args_preview,
                error_type="ToolResolutionError",
            )

        if resolved is None:
            return _blocked_tool_execution(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                content=f"ERROR: Unknown tool '{tool_name}'",
                args_preview=args_preview,
                error_type="UnknownTool",
            )

        try:
            spec, owner = resolved
        except Exception:
            return _blocked_tool_execution(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                content=(
                    f"ERROR: Tool '{tool_name}' blocked because executable "
                    "metadata is incomplete."
                ),
                args_preview=args_preview,
                error_type="ToolMetadataError",
            )

        if (
            not isinstance(spec, ToolSpec)
            or spec.name != tool_name
            or not isinstance(owner, str)
            or not owner
        ):
            return _blocked_tool_execution(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                content=(
                    f"ERROR: Tool '{tool_name}' blocked because executable "
                    "metadata is incomplete."
                ),
                args_preview=args_preview,
                error_type="ToolMetadataError",
            )

        try:
            policy_result = self.execution_policy(spec, owner, fn_args, context)
        except Exception:
            return _blocked_tool_execution(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                content=(
                    f"ERROR: Tool '{tool_name}' blocked because execution "
                    "policy failed."
                ),
                args_preview=args_preview,
                error_type="ToolExecutionPolicyError",
            )

        if policy_result is not None:
            reason = (
                policy_result
                if isinstance(policy_result, str) and policy_result
                else "policy rejected execution"
            )
            return _blocked_tool_execution(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                content=(
                    f"ERROR: Tool '{tool_name}' blocked by execution policy: "
                    f"{reason}"
                ),
                args_preview=args_preview,
                error_type="ToolExecutionPolicyDenied",
            )

        return execute_tool_handler(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            fn_args=fn_args,
            handler=spec.handler,
            context=context,
            args_preview=args_preview,
            user_error_formatter=self.user_error_formatter,
            hard_timeout_seconds=self.hard_timeout_seconds,
        )

    def record_failure(
        self,
        *,
        tool_name: str,
        args_preview: str,
        content: object,
        audit_ok: bool,
        is_audited: bool,
        session_id: str,
    ) -> ToolFailureRecordResult:
        return record_tool_failure(
            tool_name=tool_name,
            args_preview=args_preview,
            content=content,
            audit_ok=audit_ok,
            is_audited=is_audited,
            session_id=session_id,
            write_failure_func=self.write_failure_func,
            count_failure_func=self.count_failure_func,
            sink_failure_func=self.sink_failure_func,
        )


__all__ = [
    "DEFAULT_TOOL_WATCHDOG_SECONDS",
    "SEMANTIC_FAILURE_SIGNALS",
    "PhaseSwitchResult",
    "ToolExecutionContext",
    "ToolExecutionOutcome",
    "ToolExecutionPolicy",
    "ToolExecutionResult",
    "ToolExecutor",
    "ToolFailurePrecheckResult",
    "ToolFailureRecordResult",
    "allow_registered_tool_execution",
    "classify_tool_failure",
    "execute_phase_switch",
    "execute_tool_handler",
    "precheck_tool_failures",
    "preview_tool_arguments",
    "record_tool_failure",
    "resolve_tool_arguments",
    "result_has_semantic_failure",
]
