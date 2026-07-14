"""Batch ordering and outcomes for one turn's tool-call phase."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from core.tool_executor import ToolExecutionOutcome
from core.turn_guards import (
    ConcurrencyDecision,
    PlanGuardDecision,
    decide_concurrency_truncation,
    decide_plan_guard,
)


@dataclass(frozen=True, slots=True)
class ToolBatchOutcome:
    outcomes: tuple[ToolExecutionOutcome, ...]
    current_tools: list[dict[str, Any]] | None
    plan_signal_injected: bool


ExecuteCall = Callable[
    [int, Mapping[str, Any], list[dict[str, Any]] | None],
    tuple[list[dict[str, Any]] | None, ToolExecutionOutcome],
]


class TurnToolLoop:
    """Own deterministic guard and tool-batch orchestration."""

    @staticmethod
    def plan_guard(
        *,
        missing_required_plan: bool,
        plan_rejected: int,
        max_soft: int,
    ) -> PlanGuardDecision:
        return decide_plan_guard(
            missing_required_plan=missing_required_plan,
            plan_rejected=plan_rejected,
            max_soft=max_soft,
        )

    @staticmethod
    def concurrency_limit(keys: Iterable[Any], maximum: int) -> ConcurrencyDecision:
        return decide_concurrency_truncation(keys, maximum)

    def execute_batch(
        self,
        calls: Mapping[int, Mapping[str, Any]],
        *,
        current_tools: list[dict[str, Any]] | None,
        execute_call: ExecuteCall,
        plan_signal_injected: bool,
        inject_plan_signal: Callable[[], None],
    ) -> ToolBatchOutcome:
        outcomes: list[ToolExecutionOutcome] = []
        active_tools = current_tools
        for index in sorted(calls):
            active_tools, outcome = execute_call(index, calls[index], active_tools)
            outcomes.append(outcome)
        if plan_signal_injected:
            inject_plan_signal()
        return ToolBatchOutcome(
            outcomes=tuple(outcomes),
            current_tools=active_tools,
            plan_signal_injected=plan_signal_injected,
        )


__all__ = ["ToolBatchOutcome", "TurnToolLoop"]
