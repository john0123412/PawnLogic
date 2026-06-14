"""Data contracts for tool execution extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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


__all__ = ["ToolExecutionContext", "ToolExecutionResult"]
