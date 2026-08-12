"""Offline tests for bounded FIFO Agent orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time

import pytest

import core.agent_orchestrator as agent_orchestrator
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


def test_cancellation_abort_callbacks_are_unregistered_and_propagate_to_children():
    parent = CancellationToken()
    child = parent.child()
    calls: list[str | None] = []

    unregister = parent.register_abort(lambda: calls.append(parent.reason))
    removed = parent.register_abort(lambda: pytest.fail("must be unregistered"))
    removed()
    child.register_abort(lambda: calls.append(child.reason))

    assert parent.cancel("parent stopped") is True
    unregister()

    assert calls == ["parent stopped", "parent stopped"]

    already_cancelled: list[str | None] = []
    parent.register_abort(lambda: already_cancelled.append(parent.reason))

    assert already_cancelled == ["parent stopped"]


def test_child_cancellation_does_not_reach_its_parent_or_sibling():
    parent = CancellationToken()
    child = parent.child()
    sibling = CancellationToken(parent=parent)

    assert child.cancel("child stopped") is True
    assert parent.cancelled is False
    assert sibling.cancelled is False

    assert parent.cancel("parent stopped") is True
    assert child.reason == "child stopped"
    assert sibling.reason == "parent stopped"


def test_completed_child_token_detaches_from_parent_fan_out():
    parent = CancellationToken()
    child = parent.child()

    child.detach()
    parent.cancel("later parent cancellation")

    assert child.cancelled is False


def test_child_cancellation_is_scoped_to_its_own_task():
    executor = RecordingExecutor(cancellation_after=1)

    result = SerialAgentOrchestrator(executor).run(
        (_task("task-a"), _task("task-b")),
        budget=AgentBudget(max_tokens=10, max_tool_calls=2),
    )

    assert result.status == "partial"
    assert executor.calls == ["task-a", "task-b"]
    assert [item.status for item in result.results] == ["cancelled", "completed"]


def test_parent_cancellation_stops_queued_tasks_and_settles_running_claim():
    class ParentAwareExecutor:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.calls: list[str] = []

        def execute(
            self,
            task: AgentTask,
            cancellation: CancellationToken,
        ) -> AgentResult:
            self.calls.append(task.task_id)
            self.started.set()
            assert cancellation.wait(timeout=0.5)
            return AgentResult(
                status="cancelled",
                summary="parent cancellation observed",
                usage=AgentUsage(prompt_tokens=1),
            )

    parent = CancellationToken()
    executor = ParentAwareExecutor()
    outcomes = []
    errors = []

    def run() -> None:
        try:
            outcomes.append(
                SerialAgentOrchestrator(executor).run(
                    (_task("task-a"), _task("task-b")),
                    budget=AgentBudget(max_tokens=10, max_tool_calls=2),
                    cancellation=parent,
                )
            )
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=run)
    worker.start()
    assert executor.started.wait(timeout=0.5)
    assert parent.cancel("parent stopped") is True
    worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert errors == []
    assert executor.calls == ["task-a"]
    assert [item.status for item in outcomes[0].results] == ["cancelled", "cancelled"]
    assert outcomes[0].budget.consumed_tokens == 1
    assert outcomes[0].budget.reserved_tokens == 0


def test_host_interrupt_cancels_parent_and_skips_queued_tasks(monkeypatch):
    class InterruptAwareExecutor:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.calls: list[str] = []
            self.token: CancellationToken | None = None

        def execute(
            self,
            task: AgentTask,
            cancellation: CancellationToken,
        ) -> AgentResult:
            self.calls.append(task.task_id)
            self.token = cancellation
            self.started.set()
            assert cancellation.wait(timeout=0.5)
            return AgentResult(
                status="cancelled",
                summary="host interrupt observed",
                usage=AgentUsage(prompt_tokens=1),
            )

    parent = CancellationToken()
    executor = InterruptAwareExecutor()
    monkeypatch.setattr(
        agent_orchestrator,
        "_host_interrupt_requested",
        lambda: executor.started.is_set(),
    )

    result = SerialAgentOrchestrator(executor).run(
        (_task("task-a"), _task("task-b")),
        budget=AgentBudget(max_tokens=10, max_tool_calls=2),
        cancellation=parent,
    )

    assert executor.calls == ["task-a"]
    assert parent.reason == "parent turn interrupted"
    assert executor.token is not None
    assert executor.token.reason == "parent turn interrupted"
    assert [item.status for item in result.results] == ["cancelled", "cancelled"]
    assert result.budget.consumed_tokens == 1
    assert result.budget.reserved_tokens == 0


def test_deadlines_are_checked_before_and_after_execution():
    expired_executor = RecordingExecutor()
    expired = SerialAgentOrchestrator(
        expired_executor,
        clock=lambda: 10.0,
    ).run(
        (_task("expired", deadline=10.0),),
        budget=AgentBudget(max_tokens=5, max_tool_calls=1),
    )
    clock_values = iter((9.0, 9.0, 11.0))
    elapsed_executor = RecordingExecutor()
    elapsed = SerialAgentOrchestrator(
        elapsed_executor,
        clock=lambda: next(clock_values, 11.0),
    ).run(
        (_task("elapsed", deadline=10.0),),
        budget=AgentBudget(max_tokens=5, max_tool_calls=1),
    )

    assert expired.status == "timed_out"
    assert expired_executor.calls == []
    assert elapsed.status == "timed_out"
    assert elapsed_executor.calls == ["elapsed"]


def test_queued_deadline_is_checked_before_retrying_budget_admission():
    now = [0.0]

    class AdvancingExecutor:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def execute(
            self,
            task: AgentTask,
            cancellation: CancellationToken,
        ) -> AgentResult:
            self.calls.append(task.task_id)
            now[0] = 10.0
            return AgentResult(
                status="completed",
                summary=task.task_id,
                usage=AgentUsage(prompt_tokens=1),
            )

    executor = AdvancingExecutor()
    result = SerialAgentOrchestrator(
        executor,
        max_concurrency=2,
        clock=lambda: now[0],
    ).run(
        (
            _task("task-a", budget=AgentBudget(max_tokens=5, max_tool_calls=1)),
            _task(
                "task-b",
                deadline=5.0,
                budget=AgentBudget(max_tokens=5, max_tool_calls=1),
            ),
        ),
        budget=AgentBudget(max_tokens=6, max_tool_calls=2),
    )

    assert executor.calls == ["task-a"]
    assert [item.status for item in result.results] == ["completed", "timed_out"]
    assert result.results[1].failures[0].code == "deadline_exceeded"
    assert result.budget.reserved_tokens == 0


def test_running_deadline_returns_timed_out_after_settling_usage():
    now = [0.0]

    class ExpiringExecutor:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def execute(
            self,
            task: AgentTask,
            cancellation: CancellationToken,
        ) -> AgentResult:
            self.calls.append(task.task_id)
            now[0] = 10.0
            return AgentResult(
                status="completed",
                summary=task.task_id,
                usage=AgentUsage(prompt_tokens=2),
            )

    executor = ExpiringExecutor()
    result = SerialAgentOrchestrator(executor, clock=lambda: now[0]).run(
        (_task("task-a", deadline=5.0),),
        budget=AgentBudget(max_tokens=5, max_tool_calls=1),
    )

    assert executor.calls == ["task-a"]
    assert result.status == "timed_out"
    assert result.results[0].failures[0].code == "deadline_exceeded"
    assert result.budget.consumed_tokens == 2
    assert result.budget.reserved_tokens == 0


def test_running_task_deadline_cancels_only_that_task_and_settles_its_claim():
    class DeadlineAwareExecutor:
        def __init__(self) -> None:
            self._task_a_started = threading.Event()
            self.tokens: dict[str, CancellationToken] = {}
            self.calls: list[str] = []

        def execute(
            self,
            task: AgentTask,
            cancellation: CancellationToken,
        ) -> AgentResult:
            self.tokens[task.task_id] = cancellation
            self.calls.append(task.task_id)
            if task.task_id == "task-a":
                self._task_a_started.set()
                assert cancellation.wait(timeout=0.5)
                return AgentResult(
                    status="cancelled",
                    summary="deadline observed",
                    usage=AgentUsage(prompt_tokens=1),
                )
            assert self._task_a_started.wait(timeout=0.5)
            return AgentResult(
                status="completed",
                summary="sibling completed",
                usage=AgentUsage(prompt_tokens=1),
            )

    parent = CancellationToken()
    executor = DeadlineAwareExecutor()
    result = SerialAgentOrchestrator(executor, max_concurrency=2).run(
        (
            _task("task-a", deadline=time.monotonic() + 0.1),
            _task("task-b"),
        ),
        budget=AgentBudget(max_tokens=10, max_tool_calls=2),
        cancellation=parent,
    )

    assert set(executor.calls) == {"task-a", "task-b"}
    assert executor.tokens["task-a"].reason == "deadline exceeded"
    assert executor.tokens["task-b"].cancelled is False
    assert parent.cancelled is False
    assert [item.status for item in result.results] == ["timed_out", "completed"]
    assert result.results[0].failures[0].code == "deadline_exceeded"
    assert result.budget.consumed_tokens == 2
    assert result.budget.reserved_tokens == 0


def test_deadline_does_not_hide_overreported_usage():
    class OverreportingDeadlineExecutor:
        def execute(
            self,
            task: AgentTask,
            cancellation: CancellationToken,
        ) -> AgentResult:
            assert cancellation.wait(timeout=0.5)
            return AgentResult(
                status="cancelled",
                summary="deadline observed",
                usage=AgentUsage(prompt_tokens=6),
            )

    result = SerialAgentOrchestrator(OverreportingDeadlineExecutor()).run(
        (_task("task-a", deadline=time.monotonic() + 0.1),),
        budget=AgentBudget(max_tokens=5, max_tool_calls=1),
    )

    assert result.status == "budget_exhausted"
    assert result.results[0].failures[0].code == (
        "reported_usage_exceeded_reservation"
    )
    assert result.budget.reserved_tokens == 0


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


def test_budget_admission_retries_after_an_inflight_claim_settles():
    executor = RecordingExecutor(usage=AgentUsage(prompt_tokens=1))

    result = SerialAgentOrchestrator(executor, max_concurrency=2).run(
        (_task("task-a"), _task("task-b")),
        budget=AgentBudget(max_tokens=6, max_tool_calls=2),
    )

    assert result.status == "completed"
    assert executor.calls == ["task-a", "task-b"]
    assert [item.status for item in result.results] == ["completed", "completed"]
    assert result.budget.consumed_tokens == 2
    assert result.budget.reserved_tokens == 0


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
    assert result.budget.reserved_tokens == 0
    assert result.budget.reserved_tool_calls == 0


def test_submit_failure_releases_the_admission_reservation(monkeypatch):
    class SubmitFailingPool:
        def __init__(self, *, max_workers: int) -> None:
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def submit(self, *args, **kwargs):
            raise RuntimeError("executor stopped")

    monkeypatch.setattr(
        agent_orchestrator,
        "ThreadPoolExecutor",
        SubmitFailingPool,
    )

    result = SerialAgentOrchestrator(RecordingExecutor(), max_concurrency=2).run(
        (_task("task-a"),),
        budget=AgentBudget(max_tokens=5, max_tool_calls=1),
    )

    assert result.status == "failed"
    assert result.results[0].failures[0].code == "executor_submit_error"
    assert result.budget.reserved_tokens == 0
    assert result.budget.reserved_tool_calls == 0


def test_duplicate_ids_and_invalid_concurrency_are_rejected():
    executor = RecordingExecutor()

    with pytest.raises(ValueError, match="unique"):
        SerialAgentOrchestrator(executor).run(
            (_task("same"), _task("same")),
            budget=AgentBudget(max_tokens=10, max_tool_calls=2),
        )
    with pytest.raises(ValueError, match="max_concurrency"):
        SerialAgentOrchestrator(executor, max_concurrency=3)


@pytest.mark.parametrize("invalid", (True, 1.0, 2.0))
def test_max_concurrency_rejects_boolean_and_float_values(invalid):
    with pytest.raises(TypeError, match="max_concurrency"):
        SerialAgentOrchestrator(RecordingExecutor(), max_concurrency=invalid)


@pytest.mark.parametrize("invalid", (0, -1, 3))
def test_max_concurrency_accepts_only_one_or_two(invalid):
    with pytest.raises(ValueError, match="max_concurrency"):
        SerialAgentOrchestrator(RecordingExecutor(), max_concurrency=invalid)


def test_concurrency_two_runs_at_most_two_sync_executors_at_once():
    class BlockingExecutor:
        def __init__(self) -> None:
            self._lock = threading.Lock()
            self._started = threading.Event()
            self._release = threading.Event()
            self.calls: list[str] = []
            self.active = 0
            self.peak_active = 0

        def execute(
            self,
            task: AgentTask,
            cancellation: CancellationToken,
        ) -> AgentResult:
            with self._lock:
                self.active += 1
                self.peak_active = max(self.peak_active, self.active)
                self.calls.append(task.task_id)
                if self.active == 2:
                    self._started.set()
            try:
                assert self._release.wait(timeout=1.0)
                return AgentResult(status="completed", summary=task.task_id)
            finally:
                with self._lock:
                    self.active -= 1

    executor = BlockingExecutor()
    orchestrator = SerialAgentOrchestrator(executor, max_concurrency=2)
    outcomes = []
    errors = []

    def run() -> None:
        try:
            outcomes.append(
                orchestrator.run(
                    (_task("task-a"), _task("task-b"), _task("task-c")),
                    budget=AgentBudget(max_tokens=15, max_tool_calls=3),
                )
            )
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert executor._started.wait(timeout=1.0)
        assert executor.peak_active == 2
        assert len(executor.calls) == 2
    finally:
        executor._release.set()
    worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert errors == []
    assert [item.task_id for item in outcomes[0].results] == [
        "task-a",
        "task-b",
        "task-c",
    ]


def test_concurrency_two_returns_results_in_input_order_after_out_of_order_completion():
    class OutOfOrderExecutor:
        def __init__(self) -> None:
            self._first_started = threading.Event()
            self._second_started = threading.Event()
            self._second_finished = threading.Event()
            self._lock = threading.Lock()
            self.completion_order: list[str] = []

        def execute(
            self,
            task: AgentTask,
            cancellation: CancellationToken,
        ) -> AgentResult:
            if task.task_id == "task-a":
                self._first_started.set()
                assert self._second_started.wait(timeout=1.0)
                assert self._second_finished.wait(timeout=1.0)
            else:
                self._second_started.set()
                assert self._first_started.wait(timeout=1.0)
                with self._lock:
                    self.completion_order.append(task.task_id)
                self._second_finished.set()
                return AgentResult(status="completed", summary=task.task_id)
            with self._lock:
                self.completion_order.append(task.task_id)
            return AgentResult(status="completed", summary=task.task_id)

    executor = OutOfOrderExecutor()

    result = SerialAgentOrchestrator(executor, max_concurrency=2).run(
        (_task("task-a"), _task("task-b")),
        budget=AgentBudget(max_tokens=10, max_tool_calls=2),
    )

    assert executor.completion_order == ["task-b", "task-a"]
    assert [item.task_id for item in result.results] == ["task-a", "task-b"]


def test_structured_result_contains_budget_and_task_results():
    result = SerialAgentOrchestrator(RecordingExecutor()).run(
        (_task("task-a"),),
        budget=AgentBudget(max_tokens=5, max_tool_calls=1),
    )

    payload = result.to_dict()
    assert payload["status"] == "completed"
    assert payload["results"][0]["task_id"] == "task-a"
    assert payload["budget"]["available_tokens"] == 5
