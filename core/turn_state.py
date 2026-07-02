"""Internal per-turn runtime state for ``AgentSession.run_turn``.

The snapshot is intentionally private to the runtime loop. It must not be
persisted, exposed through CLI surfaces, or used as a provider stream contract.
"""

from __future__ import annotations

from dataclasses import dataclass
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

    def mark_urgent_mode(self) -> None:
        self.urgent_mode_active = True


__all__ = ["ToolSchema", "TurnState"]
