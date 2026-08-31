"""Batch ordering and outcomes for one turn's tool-call phase."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from core.tool_executor import ToolExecutionOutcome
from core.turn_cancellation import execute_cancellable_tool_batch
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
ClaimSafePoint = Callable[[], bool]
SkipCall = Callable[[int, Mapping[str, Any]], ToolExecutionOutcome]
CancellationCheck = Callable[[], bool]
InterruptCall = Callable[[int, Mapping[str, Any]], ToolExecutionOutcome]


class TurnToolLoop:
    """Own deterministic guard and tool-batch orchestration."""

    @staticmethod
    def plan_guard(
        *,
        missing_required_plan: bool,
        plan_rejected: int,
        max_soft: int,
        mode: str = "advisory",
    ) -> PlanGuardDecision:
        return decide_plan_guard(
            missing_required_plan=missing_required_plan,
            plan_rejected=plan_rejected,
            max_soft=max_soft,
            mode=mode,
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
        claim_safe_point: ClaimSafePoint | None = None,
        skip_call: SkipCall | None = None,
        cancellation_check: CancellationCheck | None = None,
        interrupt_call: InterruptCall | None = None,
    ) -> ToolBatchOutcome:
        return execute_cancellable_tool_batch(
            calls,
            current_tools=current_tools,
            execute_call=execute_call,
            plan_signal_injected=plan_signal_injected,
            inject_plan_signal=inject_plan_signal,
            claim_safe_point=claim_safe_point,
            skip_call=skip_call,
            cancellation_check=cancellation_check,
            interrupt_call=interrupt_call,
        )


__all__ = ["ToolBatchOutcome", "TurnToolLoop"]
