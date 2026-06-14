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
    "execute_phase_switch",
    "execute_tool_handler",
    "result_has_semantic_failure",
]
