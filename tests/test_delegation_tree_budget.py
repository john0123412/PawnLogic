"""Offline tests for the delegation-tree budget ceiling (issue #177.2)."""

from __future__ import annotations

import contextvars
import threading
from dataclasses import dataclass, field

from core.agent_orchestrator import (
    BudgetLedger,
    CancellationToken,
    SerialAgentOrchestrator,
)
from core.delegation import AgentBudget, AgentResult, AgentTask, AgentUsage
from tools import delegate_tool


@dataclass
class _StubExecutor:
    usage: AgentUsage = field(default_factory=AgentUsage)

    def execute(
        self,
        task: AgentTask,
        cancellation: CancellationToken,
    ) -> AgentResult:
        return AgentResult(status="completed", summary="ok", usage=self.usage)


def _task(task_id: str, *, max_tokens: int = 10, max_tool_calls: int = 2) -> AgentTask:
    return AgentTask(
        task_id=task_id,
        objective=f"Run {task_id}",
        role=task_id,
        budget=AgentBudget(max_tokens=max_tokens, max_tool_calls=max_tool_calls),
    )


def test_shared_ledger_rejects_second_branch_when_exhausted():
    budget = AgentBudget(max_tokens=10, max_tool_calls=2)
    ledger = BudgetLedger(budget)
    spent = AgentUsage(prompt_tokens=6, completion_tokens=4, tool_calls=2)

    first = SerialAgentOrchestrator(_StubExecutor(usage=spent)).run(
        [_task("tree-root")],
        budget=budget,
        cancellation=CancellationToken(),
        ledger=ledger,
    )
    assert first.results[0].status == "completed"

    # The tree pool is spent; a further branch must be refused, not granted
    # a fresh full budget.
    second = SerialAgentOrchestrator(_StubExecutor()).run(
        [_task("tree-branch")],
        budget=budget,
        cancellation=CancellationToken(),
        ledger=ledger,
    )
    assert second.results[0].status == "budget_exhausted"


def test_run_without_ledger_keeps_historical_fresh_budget():
    budget = AgentBudget(max_tokens=10, max_tool_calls=2)
    spent = AgentUsage(prompt_tokens=6, completion_tokens=4, tool_calls=2)
    for task_id in ("t-a", "t-b"):
        out = SerialAgentOrchestrator(_StubExecutor(usage=spent)).run(
            [_task(task_id)],
            budget=budget,
            cancellation=CancellationToken(),
        )
        assert out.results[0].status == "completed"


def test_acquire_tree_ledger_reuses_existing_ledger():
    budget = AgentBudget(max_tokens=10, max_tool_calls=2)

    # Outermost delegation creates the tree ledger.
    ledger, token = delegate_tool._acquire_tree_ledger(budget)
    assert isinstance(ledger, BudgetLedger)
    assert token is not None
    assert delegate_tool._delegation_tree_ledger.get() is ledger

    # A nested delegation reuses it instead of minting a fresh budget.
    nested_ledger, nested_token = delegate_tool._acquire_tree_ledger(budget)
    assert nested_ledger is ledger
    assert nested_token is None

    # Resetting the outermost token clears the tree state.
    delegate_tool._delegation_tree_ledger.reset(token)
    assert delegate_tool._delegation_tree_ledger.get() is None


def test_depth_propagates_into_worker_thread_via_copied_context():
    # The orchestrator submits contextvars.copy_context().run(...) to its
    # pool; the depth guard must survive that hop (threading.local did not).
    depth_token = delegate_tool._delegation_depth.set(1)
    try:
        seen: list[int] = []

        def worker() -> None:
            seen.append(delegate_tool._delegation_depth.get())

        ctx = contextvars.copy_context()
        thread = threading.Thread(target=ctx.run, args=(worker,))
        thread.start()
        thread.join()
        assert seen == [1]
    finally:
        delegate_tool._delegation_depth.reset(depth_token)
    assert delegate_tool._delegation_depth.get() == 0
