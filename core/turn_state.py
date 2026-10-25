"""Internal per-turn runtime state for ``AgentSession.run_turn``.

The snapshot is intentionally private to the runtime loop. It must not be
persisted, exposed through CLI surfaces, or used as a provider stream contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ToolSchema = dict[str, Any]


@dataclass(slots=True)
class TurnState:
    """Mutable state scoped to one ``run_turn`` invocation."""

    max_iter: int
    current_max_tokens: int
    current_tools: list[ToolSchema] | None
    is_vision_model: bool = False
    iteration: int = 0
    plan_rejected: int = 0
    plan_only_recoveries: int = 0
    plan_only_authorizes_next_tool_batch: bool = False
    # Plan-only replies and recovery nudges this turn appended to the history.
    # Kept by reference so a failed turn can remove exactly these (see
    # core/plan_recovery.purge_messages); they are never persisted.
    plan_only_artifacts: list[dict[str, Any]] = field(default_factory=list)
    logic_refresh_interval: int = 20
    urgent_mode_active: bool = False

    @classmethod
    def for_turn(
        cls,
        *,
        max_iter: int,
        max_tokens: int,
        is_vision_model: bool,
        current_tools: list[ToolSchema] | None,
        logic_refresh_interval: int = 20,
        urgent_mode_active: bool = False,
    ) -> TurnState:
        """Create a clean state snapshot for a new turn."""
        return cls(
            max_iter=max_iter,
            current_max_tokens=4096 if is_vision_model else max_tokens,
            current_tools=current_tools,
            is_vision_model=is_vision_model,
            logic_refresh_interval=logic_refresh_interval,
            urgent_mode_active=urgent_mode_active,
        )

    def set_iteration(self, iteration: int) -> None:
        self.iteration = iteration

    def update_tools(self, current_tools: list[ToolSchema] | None) -> None:
        self.current_tools = current_tools

    def update_max_tokens(self, current_max_tokens: int) -> None:
        self.current_max_tokens = current_max_tokens

    def replace_plan_rejected(self, plan_rejected: int) -> None:
        self.plan_rejected = plan_rejected

    def increment_plan_rejected(self) -> None:
        self.plan_rejected += 1

    def increment_plan_only_recoveries(self) -> int:
        """Record one plan-only recovery and return its updated count."""
        self.plan_only_recoveries += 1
        return self.plan_only_recoveries

    def reset_plan_only_recoveries(self) -> None:
        """Clear the consecutive plan-only recovery count after useful output."""
        self.plan_only_recoveries = 0

    def record_plan_only_artifact(self, message: dict[str, Any]) -> None:
        """Remember a message the plan-only recovery appended to the history."""
        self.plan_only_artifacts.append(message)

    def authorize_next_tool_batch_from_plan_only(self) -> None:
        """Allow one adjacent native tool batch to consume a saved plan."""
        self.plan_only_authorizes_next_tool_batch = True

    def consume_plan_only_authorization(self) -> bool:
        """Consume and return the one-shot authorization from a pure plan."""
        authorized = self.plan_only_authorizes_next_tool_batch
        self.plan_only_authorizes_next_tool_batch = False
        return authorized

    def clear_plan_only_authorization(self) -> None:
        """Discard a saved-plan authorization after a non-tool response."""
        self.plan_only_authorizes_next_tool_batch = False

    def mark_urgent_mode(self) -> None:
        self.urgent_mode_active = True


__all__ = ["ToolSchema", "TurnState"]
