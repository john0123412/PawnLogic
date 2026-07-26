"""Offline tests for bounded serial Agent orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from core.agent_orchestrator import (
    CancellationToken,
    SerialAgentOrchestrator,
)
from core.delegation import AgentBudget, AgentResult, AgentTask, AgentUsage


@dataclass
class RecordingExecutor:
    usage: AgentUsage = field(default_factory=AgentUsage)
    cancellation_after: int | None = None
    raises: bool = False

    def __post_init__(self) -> None:
        self.calls: list[str] = []
        self.active = 0
        self.peak_active = 0

    def execute(
        self,
        task: AgentTask,
        cancellation: CancellationToken,
    ) -> AgentResult:
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        self.calls.append(task.task_id)
        try:
            if self.raises:
                raise RuntimeError("provider secret must not escape")
            if self.cancellation_after == len(self.calls):
                cancellation.cancel("parent stopped")
            return AgentResult(
                status="completed",
                summary=f"finished {task.role}",
                usage=self.usage,
            )
        finally:
            self.active -= 1


def _task(
    task_id: str,
    *,
    parent_task_id: str | None = None,
    deadline: float | None = None,
    budget: AgentBudget | None = None,
) -> AgentTask:
    return AgentTask(
        task_id=task_id,
        parent_task_id=parent_task_id,
        deadline=deadline,
        objective=f"Run {task_id}",
        role=task_id,
        budget=budget or AgentBudget(max_tokens=5, max_tool_calls=1),
    )


def test_serial_orchestration_is_deterministic_and_attributes_lineage():
    executor = RecordingExecutor(
        usage=AgentUsage(
            prompt_tokens=1,
            completion_tokens=2,
            tool_calls=1,
            cost=0.1,
        )
    )
    tasks = (
        _task(
            "task-a",
            parent_task_id="root",
            budget=AgentBudget(max_tokens=5, max_tool_calls=1, max_cost=0.2),
        ),
        _task(
            "task-b",
            parent_task_id="root",
            budget=AgentBudget(max_tokens=5, max_tool_calls=1, max_cost=0.2),
        ),
    )

    result = SerialAgentOrchestrator(executor).run(
        tasks,
        budget=AgentBudget(max_tokens=10, max_tool_calls=2, max_cost=0.4),
    )

    assert result.status == "completed"
    assert executor.calls == ["task-a", "task-b"]
    assert executor.peak_active == 1
    assert [item.task_id for item in result.results] == ["task-a", "task-b"]
    assert {item.parent_task_id for item in result.results} == {"root"}
    assert result.budget.consumed_tokens == 6
    assert result.budget.consumed_tool_calls == 2
    assert result.budget.consumed_cost == pytest.approx(0.2)


def test_pre_cancelled_batch_returns_structured_results_without_execution():
    executor = RecordingExecutor()
    token = CancellationToken()
    token.cancel("user cancelled")

    result = SerialAgentOrchestrator(executor).run(
        (_task("task-a"), _task("task-b")),
        budget=AgentBudget(max_tokens=10, max_tool_calls=2),
        cancellation=token,
    )

    assert result.status == "cancelled"
    assert executor.calls == []
    assert [item.status for item in result.results] == ["cancelled", "cancelled"]
    assert all(item.failures[0].code == "cancelled" for item in result.results)


def test_cooperative_cancellation_stops_later_tasks():
    executor = RecordingExecutor(cancellation_after=1)

    result = SerialAgentOrchestrator(executor).run(
        (_task("task-a"), _task("task-b")),
        budget=AgentBudget(max_tokens=10, max_tool_calls=2),
    )

    assert result.status == "cancelled"
    assert executor.calls == ["task-a"]
    assert [item.status for item in result.results] == ["cancelled", "cancelled"]


def test_deadlines_are_checked_before_and_after_execution():
    expired_executor = RecordingExecutor()
    expired = SerialAgentOrchestrator(
        expired_executor,
        clock=lambda: 10.0,
    ).run(
        (_task("expired", deadline=10.0),),
        budget=AgentBudget(max_tokens=5, max_tool_calls=1),
    )
    clock_values = iter((9.0, 11.0))
    elapsed_executor = RecordingExecutor()
    elapsed = SerialAgentOrchestrator(
        elapsed_executor,
        clock=lambda: next(clock_values),
    ).run(
        (_task("elapsed", deadline=10.0),),
        budget=AgentBudget(max_tokens=5, max_tool_calls=1),
    )

    assert expired.status == "timed_out"
    assert expired_executor.calls == []
    assert elapsed.status == "timed_out"
    assert elapsed_executor.calls == ["elapsed"]


def test_shared_budget_admission_is_atomic_and_structured():
    executor = RecordingExecutor(
        usage=AgentUsage(prompt_tokens=2, completion_tokens=1, tool_calls=1)
    )

    result = SerialAgentOrchestrator(executor).run(
        (_task("task-a"), _task("task-b")),
        budget=AgentBudget(max_tokens=6, max_tool_calls=1),
    )

    assert result.status == "partial"
    assert executor.calls == ["task-a"]
    assert result.results[0].status == "completed"
    assert result.results[1].status == "budget_exhausted"
    assert result.results[1].failures[0].code == "shared_budget_exhausted"


def test_overreported_usage_fails_closed_and_releases_reservation():
    executor = RecordingExecutor(
        usage=AgentUsage(prompt_tokens=4, completion_tokens=4, tool_calls=1)
    )

    result = SerialAgentOrchestrator(executor).run(
        (_task("task-a"),),
        budget=AgentBudget(max_tokens=5, max_tool_calls=1),
    )

    assert result.status == "budget_exhausted"
    assert result.results[0].failures[0].code == (
        "reported_usage_exceeded_reservation"
    )
    assert result.budget.available_tokens == 5
    assert result.budget.reserved_tokens == 0


def test_executor_failures_are_safe_and_do_not_leak_exception_text():
    result = SerialAgentOrchestrator(RecordingExecutor(raises=True)).run(
        (_task("task-a"),),
        budget=AgentBudget(max_tokens=5, max_tool_calls=1),
    )

    assert result.status == "failed"
    assert result.results[0].failures[0].code == "executor_error"
    assert "secret" not in result.results[0].summary


def test_duplicate_ids_and_unsafe_concurrency_are_rejected():
    executor = RecordingExecutor()

    with pytest.raises(ValueError, match="unique"):
        SerialAgentOrchestrator(executor).run(
            (_task("same"), _task("same")),
            budget=AgentBudget(max_tokens=10, max_tool_calls=2),
        )
    with pytest.raises(ValueError, match="Workspace"):
        SerialAgentOrchestrator(executor, max_concurrency=2)


def test_structured_result_contains_budget_and_task_results():
    result = SerialAgentOrchestrator(RecordingExecutor()).run(
        (_task("task-a"),),
        budget=AgentBudget(max_tokens=5, max_tool_calls=1),
    )

    payload = result.to_dict()
    assert payload["status"] == "completed"
    assert payload["results"][0]["task_id"] == "task-a"
    assert payload["budget"]["available_tokens"] == 5
