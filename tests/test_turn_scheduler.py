"""Deterministic interface tests for the synchronous TurnScheduler."""

from __future__ import annotations

from dataclasses import replace
from threading import Barrier, Event, Thread
from threading import Lock
from types import SimpleNamespace
from typing import Any

import pytest

from core.turn_scheduler import (
    ControlAction,
    ControlKind,
    DuplicateSubmissionError,
    InvalidControlError,
    InvalidSubmissionError,
    QueueFullError,
    RestoreStateError,
    SchedulerClosedError,
    SchedulerState,
    Submission,
    SubmissionKind,
    SubmissionStatus,
    TurnExecutionResult,
    TurnExecutionStatus,
    TurnExecutorAdapter,
    TurnScheduler,
)
from core.turn_cancellation import (
    TurnCancellationToken,
    activate_turn_cancellation,
    current_turn_cancellation,
)


class BlockingExecutor:
    """Hold the first synchronous Turn without sleeping in the test."""

    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.calls: list[str] = []

    def execute(self, submission: Submission) -> None:
        self.calls.append(submission.content)
        if len(self.calls) == 1:
            self.started.set()
            assert self.release.wait(timeout=5), "test executor was not released"


class CooperativeCancelExecutor:
    """Release a blocked execution when the scheduler requests interruption."""

    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.calls: list[str] = []

    def execute(self, submission: Submission) -> None:
        self.calls.append(submission.content)
        self.started.set()
        assert self.release.wait(timeout=5), "test executor was not cancelled"

    def cancel(self) -> None:
        self.release.set()


def run_in_thread(scheduler: TurnScheduler, submission: Submission) -> tuple[Thread, list[BaseException]]:
    """Start one synchronous submission and retain any worker exception."""
    errors: list[BaseException] = []

    def run() -> None:
        try:
            scheduler.submit(submission)
        except BaseException as exc:  # pragma: no cover - asserted by callers when needed.
            errors.append(exc)

    worker = Thread(target=run)
    worker.start()
    return worker, errors


def finish_blocked(executor: BlockingExecutor, worker: Thread, errors: list[BaseException]) -> None:
    """Release and join a blocked executor, including on assertion failures."""
    executor.release.set()
    worker.join(timeout=5)
    assert not worker.is_alive(), "scheduler worker did not finish"
    assert errors == []


def test_idle_start_drives_executor_and_assigns_stable_id() -> None:
    calls: list[str] = []
    scheduler = TurnScheduler(lambda item: calls.append(item.content), id_prefix="turn")

    receipt = scheduler.submit(Submission("first"))

    assert calls == ["first"]
    assert receipt.submission_id == "turn-000001"
    assert receipt.sequence == 1
    assert receipt.kind is SubmissionKind.START
    assert receipt.disposition == "started"
    assert receipt.state is SchedulerState.RUNNING
    view = scheduler.view()
    assert view.state is SchedulerState.IDLE
    assert view.last_outcome is TurnExecutionStatus.COMPLETED
    assert view.next_sequence == 2


def test_follow_up_is_fifo_and_runs_after_natural_completion() -> None:
    executor = BlockingExecutor()
    scheduler = TurnScheduler(executor, id_prefix="q")
    worker, errors = run_in_thread(scheduler, Submission("first"))
    assert executor.started.wait(timeout=5)

    second = scheduler.submit(Submission("second", kind=SubmissionKind.FOLLOW_UP))
    third = scheduler.submit(Submission("third", kind=SubmissionKind.FOLLOW_UP))
    view = scheduler.view()
    assert second.disposition == "follow_up_queued"
    assert third.disposition == "follow_up_queued"
    assert [item.content for item in view.follow_up] == ["second", "third"]
    assert view.state is SchedulerState.FOLLOW_UP_QUEUED

    finish_blocked(executor, worker, errors)
    assert executor.calls == ["first", "second", "third"]
    assert scheduler.view().session_status == "completed"


def test_unclaimed_steer_runs_as_next_turn_after_natural_completion() -> None:
    executor = BlockingExecutor()
    scheduler = TurnScheduler(executor)
    worker, errors = run_in_thread(scheduler, Submission("original"))
    assert executor.started.wait(timeout=5)

    receipt = scheduler.submit(Submission("steer", kind=SubmissionKind.STEER))
    assert receipt.disposition == "steer_queued"
    assert scheduler.view().state is SchedulerState.STEER_QUEUED

    finish_blocked(executor, worker, errors)
    assert executor.calls == ["original", "steer"]
    assert scheduler.view().steer == ()
    assert scheduler.view().session_status == "completed"


def test_claim_steer_consumes_only_the_oldest_steer_at_a_safe_point() -> None:
    executor = BlockingExecutor()
    scheduler = TurnScheduler(executor)
    worker, errors = run_in_thread(scheduler, Submission("original"))
    assert executor.started.wait(timeout=5)

    scheduler.submit(Submission("steer one", kind=SubmissionKind.STEER))
    scheduler.submit(Submission("steer two", kind=SubmissionKind.STEER))

    receipt = scheduler.control(ControlAction(ControlKind.CLAIM_STEER))

    assert receipt.accepted
    assert receipt.claimed is not None
    assert receipt.claimed.content == "steer one"
    assert receipt.affected_ids == (receipt.claimed.submission_id,)
    assert [item.content for item in scheduler.view().steer] == ["steer two"]
    assert executor.calls == ["original"]

    finish_blocked(executor, worker, errors)


def test_running_start_requires_an_explicit_intent() -> None:
    executor = BlockingExecutor()
    scheduler = TurnScheduler(executor)
    worker, errors = run_in_thread(scheduler, Submission("original"))
    assert executor.started.wait(timeout=5)

    with pytest.raises(InvalidSubmissionError, match="choose STEER or FOLLOW_UP"):
        scheduler.submit(Submission("ambiguous"))

    finish_blocked(executor, worker, errors)
    assert executor.calls == ["original"]


def test_capacity_is_an_explicit_error_and_never_drops_queued_work() -> None:
    executor = BlockingExecutor()
    scheduler = TurnScheduler(executor, max_queue_size=1)
    worker, errors = run_in_thread(scheduler, Submission("original"))
    assert executor.started.wait(timeout=5)
    scheduler.submit(Submission("kept", kind=SubmissionKind.FOLLOW_UP))

    with pytest.raises(QueueFullError, match="no submission was dropped"):
        scheduler.submit(Submission("rejected", kind=SubmissionKind.FOLLOW_UP))
    assert [item.content for item in scheduler.view().follow_up] == ["kept"]

    finish_blocked(executor, worker, errors)
    assert executor.calls == ["original", "kept"]


def test_submission_ids_are_unique_even_when_a_caller_reuses_one() -> None:
    calls: list[str] = []
    scheduler = TurnScheduler(lambda item: calls.append(item.content))
    scheduler.submit(Submission("first", submission_id="client-1"))

    with pytest.raises(DuplicateSubmissionError):
        scheduler.submit(Submission("second", submission_id="client-1"))

    assert calls == ["first"]
    assert scheduler.view().next_sequence == 2


def test_interrupted_turn_becomes_recoverable_and_resume_runs_once() -> None:
    calls: list[str] = []

    def execute(item: Submission) -> TurnExecutionResult:
        calls.append(item.content)
        if len(calls) == 1:
            return TurnExecutionResult(TurnExecutionStatus.INTERRUPTED)
        return TurnExecutionResult(TurnExecutionStatus.COMPLETED)

    scheduler = TurnScheduler(execute)
    scheduler.submit(Submission("draft"))
    recovered = scheduler.view()
    assert recovered.state is SchedulerState.RECOVERABLE
    assert recovered.recovered is not None
    assert recovered.recovered.kind is SubmissionKind.RECOVERED
    assert recovered.recovered.status is SubmissionStatus.RECOVERED
    original_id = recovered.recovered.submission_id
    original_sequence = recovered.recovered.sequence
    assert recovered.interrupted_at is not None

    replacement = scheduler.control(
        ControlAction(ControlKind.REPLACE_RECOVERED, content="edited draft")
    )
    assert replacement.accepted
    assert scheduler.view().recovered is not None
    assert scheduler.view().recovered.content == "edited draft"

    resume = scheduler.control(ControlAction(ControlKind.RESUME))
    assert resume.accepted
    assert resume.affected_ids == (original_id,)
    assert calls == ["draft", "edited draft"]
    final = scheduler.view()
    assert final.state is SchedulerState.IDLE
    assert final.session_status == "completed"
    assert final.next_sequence == original_sequence + 1


def test_keyboard_interrupt_is_recovered_without_automatic_replay() -> None:
    calls: list[str] = []

    def execute(item: Submission) -> None:
        calls.append(item.content)
        raise KeyboardInterrupt

    scheduler = TurnScheduler(execute)
    with pytest.raises(KeyboardInterrupt):
        scheduler.submit(Submission("interrupt me"))

    view = scheduler.view()
    assert calls == ["interrupt me"]
    assert view.state is SchedulerState.RECOVERABLE
    assert view.recovered is not None
    assert view.session_status == "interrupted"


def test_interrupt_request_wins_over_a_normal_executor_return() -> None:
    executor = CooperativeCancelExecutor()
    scheduler = TurnScheduler(executor)
    worker, errors = run_in_thread(scheduler, Submission("cancel me"))
    assert executor.started.wait(timeout=5)

    receipt = scheduler.control(ControlAction(ControlKind.INTERRUPT_ACTIVE))

    assert receipt.accepted
    worker.join(timeout=5)
    assert not worker.is_alive(), "scheduler worker did not finish"
    assert errors == []
    view = scheduler.view()
    assert executor.calls == ["cancel me"]
    assert view.state is SchedulerState.RECOVERABLE
    assert view.recovered is not None
    assert view.recovered.content == "cancel me"
    assert view.last_outcome is TurnExecutionStatus.INTERRUPTED
    assert view.session_status == "interrupted"


def test_executor_exception_preserves_active_submission_as_recoverable() -> None:
    def execute(_submission: Submission) -> None:
        raise RuntimeError("executor failed")

    scheduler = TurnScheduler(execute)

    with pytest.raises(RuntimeError, match="executor failed"):
        scheduler.submit(Submission("keep this draft"))

    view = scheduler.view()
    assert view.state is SchedulerState.RECOVERABLE
    assert view.recovered is not None
    assert view.recovered.content == "keep this draft"
    assert view.last_outcome is TurnExecutionStatus.INTERRUPTED
    assert view.session_status == "interrupted"


def test_failed_executor_result_preserves_active_submission_as_recoverable() -> None:
    def execute(_submission: Submission) -> TurnExecutionResult:
        return TurnExecutionResult(TurnExecutionStatus.FAILED, "known failure")

    scheduler = TurnScheduler(execute)
    scheduler.submit(Submission("retry after failure"))

    view = scheduler.view()
    assert view.state is SchedulerState.RECOVERABLE
    assert view.recovered is not None
    assert view.recovered.content == "retry after failure"
    assert view.last_outcome is TurnExecutionStatus.FAILED
    assert view.session_status == "failed"


def test_new_snapshot_state_round_trips_all_lanes() -> None:
    state = {
        "schema": 1,
        "next_sequence": 9,
        "session_status": "interrupted",
        "interrupted_at": 12.5,
        "steer": [{"id": "s-1", "sequence": 4, "content": "steer"}],
        "follow_up": [{"id": "f-1", "sequence": 5, "content": "follow"}],
        "recovered": {"id": "r-1", "sequence": 3, "content": "recover"},
    }
    scheduler = TurnScheduler(lambda _: None)

    receipt = scheduler.control(ControlAction(ControlKind.RESTORE, restore_state=state))

    assert receipt.accepted
    view = scheduler.view()
    assert view.state is SchedulerState.RECOVERABLE
    assert [item.content for item in view.steer] == ["steer"]
    assert [item.content for item in view.follow_up] == ["follow"]
    assert view.recovered is not None
    assert view.recovered.content == "recover"
    assert view.next_sequence == 9


def test_legacy_queue_state_maps_pending_to_first_recovered_draft() -> None:
    state = {
        "queue": [{"id": "queued", "content": "later"}],
        "pending": [
            {"id": "pending-1", "content": "interrupted"},
            {"id": "pending-2", "content": "after interrupted"},
        ],
    }
    scheduler = TurnScheduler(lambda _: None)

    scheduler.control(ControlAction(ControlKind.RESTORE, restore_state=state))

    view = scheduler.view()
    assert view.recovered is not None
    assert view.recovered.content == "interrupted"
    assert [item.content for item in view.follow_up] == ["later", "after interrupted"]
    assert view.recovered.kind is SubmissionKind.RECOVERED


def test_restore_rejects_malformed_entry_without_mutating_existing_state() -> None:
    scheduler = TurnScheduler(lambda _: None)
    scheduler.control(
        ControlAction(
            ControlKind.RESTORE,
            restore_state={"follow_up": [{"id": "kept", "content": "keep"}]},
        )
    )
    before = scheduler.view()

    with pytest.raises(RestoreStateError, match="entry must be a mapping"):
        scheduler.control(
            ControlAction(
                ControlKind.RESTORE,
                restore_state={"follow_up": ["not an entry"]},
            )
        )

    assert scheduler.view() == before


def test_restore_rejects_duplicate_ids_without_mutating_existing_state() -> None:
    scheduler = TurnScheduler(lambda _: None)
    scheduler.control(
        ControlAction(
            ControlKind.RESTORE,
            restore_state={"follow_up": [{"id": "kept", "content": "keep"}]},
        )
    )
    before = scheduler.view()

    with pytest.raises(RestoreStateError, match="duplicate submission ID"):
        scheduler.control(
            ControlAction(
                ControlKind.RESTORE,
                restore_state={
                    "follow_up": [
                        {"id": "same", "content": "first"},
                        {"id": "same", "content": "second"},
                    ]
                },
            )
        )

    assert scheduler.view() == before


def test_unknown_snapshot_schema_is_rejected_atomically() -> None:
    scheduler = TurnScheduler(lambda _: None)
    scheduler.control(
        ControlAction(
            ControlKind.RESTORE,
            restore_state={"schema": 1, "next_sequence": 4},
        )
    )
    before = scheduler.view()

    with pytest.raises(RestoreStateError, match="unsupported scheduler state schema"):
        scheduler.control(
            ControlAction(
                ControlKind.RESTORE,
                restore_state={"schema": 2, "follow_up": []},
            )
        )

    after = scheduler.view()
    assert after == before


def test_active_snapshot_serializes_as_recovered_draft() -> None:
    executor = BlockingExecutor()
    scheduler = TurnScheduler(executor)
    worker, errors = run_in_thread(scheduler, Submission("side effect"))
    assert executor.started.wait(timeout=5)

    state = scheduler.view().to_state()
    assert state["recovered"] is not None
    assert state["recovered"]["content"] == "side effect"
    assert state["recovered"]["kind"] == SubmissionKind.RECOVERED.value

    finish_blocked(executor, worker, errors)


def test_scheduler_snapshot_has_explicit_schema_and_monotonic_revision() -> None:
    scheduler = TurnScheduler(lambda _: None)

    initial = scheduler.view().to_state()
    assert initial["schema"] == 1
    assert initial["revision"] == scheduler.view().revision

    scheduler.submit(Submission("first"))
    persisted = scheduler.view().to_state()
    assert persisted["schema"] == 1
    assert persisted["revision"] == scheduler.view().revision
    assert persisted["revision"] > initial["revision"]

    scheduler.control(
        ControlAction(
            ControlKind.RESTORE,
            restore_state={
                "schema": 1,
                "revision": persisted["revision"],
                "follow_up": [{"id": "next", "content": "next"}],
            },
        )
    )
    assert scheduler.view().revision > persisted["revision"]


def test_clear_removes_queued_entries_but_keeps_active_turn() -> None:
    executor = BlockingExecutor()
    scheduler = TurnScheduler(executor)
    worker, errors = run_in_thread(scheduler, Submission("active"))
    assert executor.started.wait(timeout=5)
    scheduler.submit(Submission("steer", kind=SubmissionKind.STEER))
    scheduler.submit(Submission("follow", kind=SubmissionKind.FOLLOW_UP))
    queued_ids = {
        item.submission_id
        for item in (*scheduler.view().steer, *scheduler.view().follow_up)
    }

    receipt = scheduler.control(ControlAction(ControlKind.CLEAR))

    assert receipt.accepted
    assert set(receipt.affected_ids) == queued_ids
    view = scheduler.view()
    assert view.active is not None
    assert view.queued_count == 0
    assert view.state is SchedulerState.RUNNING

    finish_blocked(executor, worker, errors)
    assert executor.calls == ["active"]


def test_clear_removes_steer_follow_up_and_recovered_entries() -> None:
    scheduler = TurnScheduler(lambda _: None)
    scheduler.control(
        ControlAction(
            ControlKind.RESTORE,
            restore_state={
                "steer": [{"id": "steer", "content": "steer"}],
                "follow_up": [{"id": "follow", "content": "follow"}],
                "recovered": {"id": "recover", "content": "recover"},
                "session_status": "interrupted",
            },
        )
    )

    receipt = scheduler.control(ControlAction(ControlKind.CLEAR))

    assert set(receipt.affected_ids) == {"steer", "follow", "recover"}
    view = scheduler.view()
    assert view.steer == ()
    assert view.follow_up == ()
    assert view.recovered is None


def test_convert_preserves_identity_metadata_and_sequence_order() -> None:
    executor = BlockingExecutor()
    scheduler = TurnScheduler(executor, id_prefix="convert")
    worker, errors = run_in_thread(scheduler, Submission("active"))
    assert executor.started.wait(timeout=5)

    follow = scheduler.submit(
        Submission(
            "follow-up content",
            kind=SubmissionKind.FOLLOW_UP,
            source="test",
            metadata={"origin": "menu"},
        )
    )
    steer = scheduler.submit(Submission("steer content", kind=SubmissionKind.STEER))

    receipt = scheduler.control(
        ControlAction(
            ControlKind.CONVERT,
            submission_id=follow.submission_id,
            target_kind=SubmissionKind.STEER,
        )
    )

    assert receipt.accepted
    view = scheduler.view()
    assert [item.sequence for item in view.steer] == [follow.sequence, steer.sequence]
    converted = view.steer[0]
    assert converted.submission_id == follow.submission_id
    assert converted.content == "follow-up content"
    assert converted.source == "test"
    assert converted.metadata == {"origin": "menu"}
    assert converted.kind is SubmissionKind.STEER
    assert view.follow_up == ()

    finish_blocked(executor, worker, errors)


def test_convert_rejects_active_and_recovered_entries() -> None:
    executor = BlockingExecutor()
    scheduler = TurnScheduler(executor)
    worker, errors = run_in_thread(scheduler, Submission("active"))
    assert executor.started.wait(timeout=5)

    active = scheduler.view().active
    assert active is not None
    active_receipt = scheduler.control(
        ControlAction(
            ControlKind.CONVERT,
            submission_id=active.submission_id,
            target_kind=SubmissionKind.FOLLOW_UP,
        )
    )
    assert not active_receipt.accepted
    assert "active" in active_receipt.reason
    finish_blocked(executor, worker, errors)

    scheduler.control(
        ControlAction(
            ControlKind.RESTORE,
            restore_state={
                "recovered": {"id": "recovered", "content": "draft"},
                "session_status": "interrupted",
            },
        )
    )
    recovered_receipt = scheduler.control(
        ControlAction(
            ControlKind.CONVERT,
            submission_id="recovered",
            target_kind=SubmissionKind.STEER,
        )
    )
    assert not recovered_receipt.accepted
    assert "recovered" in recovered_receipt.reason


def test_abort_all_clears_idle_work_and_marks_session_aborted() -> None:
    scheduler = TurnScheduler(lambda _: None)
    scheduler.control(
        ControlAction(
            ControlKind.RESTORE,
            restore_state={
                "follow_up": [{"id": "queued", "content": "queued"}],
            },
        )
    )

    receipt = scheduler.control(ControlAction(ControlKind.ABORT_ALL))

    assert receipt.accepted
    assert receipt.affected_ids == ("queued",)
    view = scheduler.view()
    assert view.state is SchedulerState.IDLE
    assert view.session_status == "aborted"
    assert view.total_unfinished_count == 0


def test_checkpoint_is_observational_and_cannot_break_execution() -> None:
    checkpoints: list[SchedulerState] = []

    def checkpoint(view: Any) -> None:
        checkpoints.append(view.state)
        raise RuntimeError("persistence is deliberately failing")

    scheduler = TurnScheduler(lambda _: None, checkpoint=checkpoint)
    scheduler.submit(Submission("safe"))

    assert checkpoints
    assert scheduler.view().last_outcome is TurnExecutionStatus.COMPLETED
    assert scheduler.view().checkpoint_error == (
        "RuntimeError: checkpoint callback failed"
    )


def test_production_session_adapter_wires_scheduler_checkpoint(monkeypatch) -> None:
    from core.live_turn_control import build_session_scheduler

    captured: list[Any] = []

    def checkpoint(_session: Any, view: Any) -> None:
        captured.append(view)

    monkeypatch.setattr(
        "core.live_turn_control._checkpoint_session_view",
        checkpoint,
    )
    session = SimpleNamespace(
        session_id="session-checkpoint",
        _run_scheduled_turn=lambda _content: None,
    )

    scheduler = build_session_scheduler(session, live_turns=False)
    scheduler.submit(Submission("checkpoint me"))

    assert len(captured) >= 2
    assert [view.revision for view in captured] == sorted(
        view.revision for view in captured
    )
    assert captured[-1].to_state()["schema"] == 1


def test_checkpoint_callbacks_are_serialized_and_reject_stale_revisions() -> None:
    revisions: list[int] = []
    callback_lock = Lock()
    active_callbacks = 0
    max_active_callbacks = 0

    def checkpoint(view: Any) -> None:
        nonlocal active_callbacks, max_active_callbacks
        with callback_lock:
            active_callbacks += 1
            max_active_callbacks = max(max_active_callbacks, active_callbacks)
        revisions.append(view.revision)
        with callback_lock:
            active_callbacks -= 1

    scheduler = TurnScheduler(lambda _: None, checkpoint=checkpoint)
    base = scheduler.view()
    stale = replace(base, revision=10)
    fresh = replace(base, revision=11)
    barrier = Barrier(3)

    def notify(view: Any) -> None:
        barrier.wait(timeout=5)
        scheduler._notify(view)  # type: ignore[attr-defined]

    older_thread = Thread(target=notify, args=(stale,))
    newer_thread = Thread(target=notify, args=(fresh,))
    older_thread.start()
    newer_thread.start()
    barrier.wait(timeout=5)
    older_thread.join(timeout=5)
    newer_thread.join(timeout=5)

    assert not older_thread.is_alive() and not newer_thread.is_alive()
    assert revisions == sorted(revisions)
    assert len(revisions) in (1, 2)
    assert max_active_callbacks == 1


def test_checkpoint_callback_can_reenter_scheduler_without_deadlocking() -> None:
    calls: list[str] = []
    revisions: list[int] = []
    entered = Event()
    reentered = Event()
    done = Event()
    errors: list[BaseException] = []
    holder: dict[str, TurnScheduler] = {}

    def checkpoint(view: Any) -> None:
        revisions.append(view.revision)
        if view.revision == 1:
            entered.set()
            holder["scheduler"].submit(
                Submission("nested", kind=SubmissionKind.FOLLOW_UP)
            )
            reentered.set()

    scheduler = TurnScheduler(
        lambda item: calls.append(item.content),
        checkpoint=checkpoint,
    )
    holder["scheduler"] = scheduler

    def run() -> None:
        try:
            scheduler.submit(Submission("outer"))
        except BaseException as exc:  # pragma: no cover - asserted below.
            errors.append(exc)
        finally:
            done.set()

    worker = Thread(target=run, daemon=True)
    worker.start()
    assert entered.wait(timeout=5)
    assert reentered.wait(timeout=5)
    assert done.wait(timeout=5)
    worker.join(timeout=5)

    assert not worker.is_alive(), "re-entrant scheduler callback deadlocked"
    assert errors == []
    assert calls == ["outer", "nested"]
    assert revisions == sorted(revisions)


def test_submission_metadata_is_detached_and_read_only_at_the_interface() -> None:
    metadata = {"source": "test", "nested": {"value": 1}}
    scheduler = TurnScheduler(lambda _: None)
    scheduler.submit(Submission("metadata", metadata=metadata))
    metadata["nested"]["value"] = 99

    view = scheduler.view()
    assert view.last_outcome is TurnExecutionStatus.COMPLETED
    # The active item is complete, so inspect the detached state from a restored view.
    scheduler.control(
        ControlAction(
            ControlKind.RESTORE,
            restore_state={"recovered": {"content": "draft", "metadata": metadata}},
        )
    )
    restored = scheduler.view()
    assert restored.recovered is not None
    assert restored.recovered.metadata["nested"]["value"] == 99
    with pytest.raises(TypeError):
        restored.recovered.metadata["source"] = "changed"  # type: ignore[index]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, TurnExecutionStatus.COMPLETED),
        ("failed", TurnExecutionStatus.FAILED),
        ("interrupted", TurnExecutionStatus.INTERRUPTED),
        (TurnExecutionResult(TurnExecutionStatus.FAILED), TurnExecutionStatus.FAILED),
    ],
)
def test_executor_adapter_normalizes_legacy_return_values(
    raw: object, expected: TurnExecutionStatus
) -> None:
    adapter = TurnExecutorAdapter(lambda _: raw)

    result = adapter.execute(Submission("input"))

    assert result.status is expected


def test_concurrent_follow_up_admission_is_serialized_by_sequence() -> None:
    executor = BlockingExecutor()
    scheduler = TurnScheduler(executor)
    worker, errors = run_in_thread(scheduler, Submission("active"))
    assert executor.started.wait(timeout=5)
    barrier = Barrier(3)
    receipts: list[Any] = []

    def enqueue(content: str) -> None:
        barrier.wait(timeout=5)
        receipts.append(
            scheduler.submit(Submission(content, kind=SubmissionKind.FOLLOW_UP))
        )

    first = Thread(target=enqueue, args=("one",))
    second = Thread(target=enqueue, args=("two",))
    first.start()
    second.start()
    barrier.wait(timeout=5)
    first.join(timeout=5)
    second.join(timeout=5)
    assert not first.is_alive() and not second.is_alive()
    assert len(receipts) == 2
    assert sorted(receipt.sequence for receipt in receipts) == [2, 3]
    assert sorted(item.content for item in scheduler.view().follow_up) == ["one", "two"]

    finish_blocked(executor, worker, errors)
    assert executor.calls[0] == "active"
    assert executor.calls[1:] in (["one", "two"], ["two", "one"])


def test_unclaimed_mixed_lanes_drain_steer_before_follow_up() -> None:
    executor = BlockingExecutor()
    scheduler = TurnScheduler(executor)
    worker, errors = run_in_thread(scheduler, Submission("active"))
    assert executor.started.wait(timeout=5)

    scheduler.submit(Submission("steer-1", kind=SubmissionKind.STEER))
    scheduler.submit(Submission("follow-1", kind=SubmissionKind.FOLLOW_UP))
    scheduler.submit(Submission("steer-2", kind=SubmissionKind.STEER))

    finish_blocked(executor, worker, errors)
    view = scheduler.view()
    assert executor.calls == ["active", "steer-1", "steer-2", "follow-1"]
    assert view.steer == ()
    assert view.follow_up == ()
    assert view.session_status == "completed"


def test_control_validates_required_arguments() -> None:
    scheduler = TurnScheduler(lambda _: None)

    with pytest.raises(InvalidControlError, match="REMOVE requires submission_id"):
        scheduler.control(ControlAction(ControlKind.REMOVE))
    scheduler.control(
        ControlAction(
            ControlKind.RESTORE,
            restore_state={"recovered": {"content": "draft"}},
        )
    )
    with pytest.raises(InvalidControlError, match="REPLACE_RECOVERED requires non-empty content"):
        scheduler.control(ControlAction(ControlKind.REPLACE_RECOVERED, content=""))
    with pytest.raises(InvalidControlError, match="RESTORE requires restore_state"):
        scheduler.control(ControlAction(ControlKind.RESTORE))


def test_background_submit_returns_while_executor_is_blocked() -> None:
    started = Event()
    release = Event()
    finished = Event()
    calls: list[str] = []

    def execute(item: Submission) -> None:
        calls.append(item.content)
        if item.content == "first":
            started.set()
            assert release.wait(timeout=5), "background executor was not released"
        if item.content == "second":
            finished.set()

    scheduler = TurnScheduler(execute, background=True, id_prefix="bg")
    try:
        receipt = scheduler.submit(Submission("first"))

        assert receipt.disposition == "started"
        assert started.wait(timeout=5)
        assert scheduler.view().active is not None

        follow_up = scheduler.submit(
            Submission("second", kind=SubmissionKind.FOLLOW_UP)
        )
        assert follow_up.disposition == "follow_up_queued"
        assert scheduler.view().follow_up[0].content == "second"

        release.set()
        assert finished.wait(timeout=5)
        assert calls == ["first", "second"]
    finally:
        scheduler.control(ControlAction(ControlKind.SHUTDOWN))


def test_background_scheduler_keeps_one_worker_and_follow_up_fifo_after_idle() -> None:
    first_started = Event()
    first_release = Event()
    all_finished = Event()
    calls: list[str] = []

    def execute(item: Submission) -> None:
        calls.append(item.content)
        if item.content == "first":
            first_started.set()
            assert first_release.wait(timeout=5), "first turn was not released"
        if item.content == "third":
            all_finished.set()

    scheduler = TurnScheduler(execute, background=True, id_prefix="fifo")
    try:
        scheduler.submit(Submission("first"))
        assert first_started.wait(timeout=5)
        scheduler.submit(Submission("second", kind=SubmissionKind.FOLLOW_UP))
        scheduler.submit(Submission("third", kind=SubmissionKind.FOLLOW_UP))
        worker = scheduler._worker  # type: ignore[attr-defined]
        assert worker is not None
        assert worker.daemon is False

        first_release.set()
        assert all_finished.wait(timeout=5)
        assert calls == ["first", "second", "third"]

        # The same non-daemon worker remains available after the queue goes idle.
        assert scheduler.view().active is None
        assert scheduler.view().worker_alive is True
        assert scheduler._worker is worker  # type: ignore[attr-defined]
    finally:
        scheduler.control(ControlAction(ControlKind.SHUTDOWN))

    assert worker is not None
    assert not worker.is_alive()
    assert scheduler.view().closed is True
    assert scheduler.view().worker_alive is False


def test_background_executor_exception_is_recoverable_and_worker_can_resume() -> None:
    first_done = Event()
    second_done = Event()
    calls: list[str] = []

    def execute(item: Submission) -> None:
        calls.append(item.content)
        if len(calls) == 1:
            first_done.set()
            raise RuntimeError("executor failed")
        second_done.set()

    scheduler = TurnScheduler(execute, background=True)
    try:
        scheduler.submit(Submission("retryable"))
        assert first_done.wait(timeout=5)

        failed = scheduler.view()
        assert failed.recovered is not None
        assert failed.recovered.content == "retryable"
        assert failed.worker_error == "RuntimeError"
        assert failed.worker_alive is True

        receipt = scheduler.control(ControlAction(ControlKind.RESUME))
        assert receipt.accepted
        assert second_done.wait(timeout=5)
        assert calls == ["retryable", "retryable"]
        assert scheduler.view().state is SchedulerState.IDLE
    finally:
        scheduler.control(ControlAction(ControlKind.SHUTDOWN))


def test_background_shutdown_rejects_future_submissions_after_join() -> None:
    completed = Event()

    def execute(_item: Submission) -> None:
        completed.set()

    scheduler = TurnScheduler(execute, background=True)
    scheduler.submit(Submission("close me"))
    assert completed.wait(timeout=5)

    receipt = scheduler.control(ControlAction(ControlKind.SHUTDOWN))

    assert receipt.accepted
    assert scheduler.view().closed is True
    assert scheduler.view().worker_alive is False
    with pytest.raises(SchedulerClosedError, match="shut down"):
        scheduler.submit(Submission("after close"))


def test_background_shutdown_reports_bounded_join_for_non_cooperative_executor() -> None:
    started = Event()
    release = Event()

    def execute(_item: Submission) -> None:
        started.set()
        release.wait(timeout=5)

    scheduler = TurnScheduler(
        execute,
        background=True,
        shutdown_timeout=0.05,
    )
    try:
        scheduler.submit(Submission("non-cooperative"))
        assert started.wait(timeout=5)

        receipt = scheduler.control(ControlAction(ControlKind.SHUTDOWN))

        assert receipt.accepted
        assert receipt.worker_joined is False
        assert "timeout" in receipt.reason
        assert scheduler.view().closed is True
        assert scheduler.view().worker_alive is True
    finally:
        release.set()
        worker = scheduler._worker  # type: ignore[attr-defined]
        if worker is not None:
            worker.join(timeout=5)


def test_background_context_factory_is_applied_once_per_turn() -> None:
    started = Event()
    release = Event()
    finished = Event()
    contexts: list[object] = []
    calls: list[str] = []

    class Context:
        def __init__(self, name: str) -> None:
            self.name = name
            self.active = False

        def activate(self, *, mirror_legacy: bool | None = None):
            class Scope:
                def __enter__(_scope):
                    assert mirror_legacy is False
                    self.active = True
                    return self

                def __exit__(_scope, *_exc):
                    self.active = False
                    return False

            return Scope()

    def make_context(item: Submission) -> Context:
        context = Context(item.content)
        contexts.append(context)
        return context

    def execute(item: Submission) -> None:
        calls.append(item.content)
        assert contexts[-1].active  # type: ignore[attr-defined]
        if item.content == "first":
            started.set()
            assert release.wait(timeout=5), "context test executor was not released"
        elif item.content == "second":
            finished.set()

    scheduler = TurnScheduler(
        execute,
        background=True,
        context_factory=make_context,
    )
    try:
        scheduler.submit(Submission("first"))
        assert started.wait(timeout=5)
        scheduler.submit(Submission("second", kind=SubmissionKind.FOLLOW_UP))
        release.set()
        assert finished.wait(timeout=5)
        assert calls == ["first", "second"]
        assert len(contexts) == 2
        assert contexts[0] is not contexts[1]
    finally:
        scheduler.control(ControlAction(ControlKind.SHUTDOWN))


def test_background_runtime_contexts_are_detached_and_do_not_mirror_legacy_state(
    tmp_path,
) -> None:
    from core.runtime_context import (
        RuntimeContext,
        active_runtime_context_mirrors_legacy,
        current_runtime_context,
    )
    from core.state import state

    parent = RuntimeContext.for_test(
        cwd=tmp_path,
        workspace_dir=tmp_path / "workspace",
        dynamic_config={"marker": "first"},
    )
    old_legacy_config = state.dynamic_config
    started = Event()
    release = Event()
    finished = Event()
    observations: list[tuple[str, bool, bool]] = []

    def execute(item: Submission) -> None:
        context = current_runtime_context()
        assert context is not None
        observations.append(
            (
                str(context.dynamic_config["marker"]),
                context.dynamic_config is parent.dynamic_config,
                active_runtime_context_mirrors_legacy(),
            )
        )
        if item.content == "first":
            started.set()
            assert release.wait(timeout=5), "context test executor was not released"
        else:
            finished.set()

    scheduler = TurnScheduler(
        execute,
        background=True,
        context_factory=lambda _item: parent,
    )
    try:
        scheduler.submit(Submission("first"))
        assert started.wait(timeout=5)
        parent.dynamic_config["marker"] = "second"
        scheduler.submit(Submission("second", kind=SubmissionKind.FOLLOW_UP))
        release.set()
        assert finished.wait(timeout=5)
        assert observations == [
            ("first", False, False),
            ("second", False, False),
        ]
        assert state.dynamic_config is old_legacy_config
    finally:
        scheduler.control(ControlAction(ControlKind.SHUTDOWN))


def test_background_turns_receive_independent_cancellation_tokens() -> None:
    started = Event()
    cancelled = Event()
    second_done = Event()
    tokens: list[TurnCancellationToken] = []
    calls: list[str] = []

    class Executor:
        def execute_with_cancellation(
            self,
            item: Submission,
            token: TurnCancellationToken,
        ) -> None:
            calls.append(item.content)
            tokens.append(token)
            if len(tokens) == 1:
                started.set()
                assert token.wait(timeout=5)
                cancelled.set()
            else:
                second_done.set()

    scheduler = TurnScheduler(Executor(), background=True)
    try:
        scheduler.submit(Submission("first"))
        assert started.wait(timeout=5)
        receipt = scheduler.control(ControlAction(ControlKind.INTERRUPT_ACTIVE))
        assert receipt.accepted
        assert receipt.settled is True
        assert receipt.state is SchedulerState.RECOVERABLE
        assert cancelled.wait(timeout=5)

        first = scheduler.view()
        assert first.recovered is not None
        assert tokens[0].cancelled
        assert tokens[0].reason == "turn interrupted"

        resumed = scheduler.control(ControlAction(ControlKind.RESUME))
        assert resumed.accepted
        assert second_done.wait(timeout=5)
        assert calls == ["first", "first"]
        assert len(tokens) == 2
        assert tokens[1] is not tokens[0]
        assert not tokens[1].cancelled
    finally:
        scheduler.control(ControlAction(ControlKind.SHUTDOWN))


def test_interrupt_active_preserves_follow_up_but_abort_all_clears_it() -> None:
    started = Event()
    release = Event()

    class Executor:
        def execute_with_cancellation(
            self,
            _item: Submission,
            token: TurnCancellationToken,
        ) -> None:
            started.set()
            token.wait(timeout=5)
            release.set()

    scheduler = TurnScheduler(Executor(), background=True)
    try:
        scheduler.submit(Submission("active"))
        assert started.wait(timeout=5)
        queued = scheduler.submit(
            Submission("later", kind=SubmissionKind.FOLLOW_UP)
        )
        assert queued.disposition == "follow_up_queued"

        interrupted = scheduler.control(ControlAction(ControlKind.INTERRUPT_ACTIVE))
        assert interrupted.accepted
        assert interrupted.settled is True
        assert interrupted.state is SchedulerState.RECOVERABLE
        assert release.wait(timeout=5)
        view = scheduler.view()
        assert view.recovered is not None
        assert [entry.content for entry in view.follow_up] == ["later"]

        aborted = scheduler.control(ControlAction(ControlKind.ABORT_ALL))
        assert aborted.accepted
        assert scheduler.view().recovered is None
        assert scheduler.view().follow_up == ()
    finally:
        scheduler.control(ControlAction(ControlKind.SHUTDOWN))


def test_scheduler_binds_each_token_only_for_its_executor() -> None:
    observed: list[TurnCancellationToken | None] = []

    def execute(_item: Submission) -> None:
        observed.append(current_turn_cancellation())

    scheduler = TurnScheduler(execute)
    scheduler.submit(Submission("bound"))

    assert len(observed) == 1
    assert observed[0] is not None
    assert not observed[0].cancelled


def test_turn_cancellation_callbacks_are_scoped_and_one_shot() -> None:
    first = TurnCancellationToken()
    second = TurnCancellationToken()
    callbacks: list[str] = []
    first.register_abort(lambda: callbacks.append("first"))
    second.register_abort(lambda: callbacks.append("second"))

    assert first.cancel("only first")
    assert not first.cancel("ignored")
    assert callbacks == ["first"]
    assert first.reason == "only first"
    assert not second.cancelled
    assert second.reason is None

    with activate_turn_cancellation(second):
        assert current_turn_cancellation() is second
    assert current_turn_cancellation() is None


def test_two_session_workers_cancel_only_their_own_active_turn() -> None:
    class Executor:
        def __init__(self) -> None:
            self.started = Event()
            self.cancelled = Event()
            self.tokens: list[TurnCancellationToken] = []

        def execute_with_cancellation(
            self,
            _item: Submission,
            token: TurnCancellationToken,
        ) -> None:
            self.tokens.append(token)
            self.started.set()
            if token.wait(timeout=5):
                self.cancelled.set()

    first_executor = Executor()
    second_executor = Executor()
    first = TurnScheduler(first_executor, background=True, id_prefix="first")
    second = TurnScheduler(second_executor, background=True, id_prefix="second")
    try:
        first.submit(Submission("first"))
        second.submit(Submission("second"))
        assert first_executor.started.wait(timeout=5)
        assert second_executor.started.wait(timeout=5)

        first.control(ControlAction(ControlKind.INTERRUPT_ACTIVE))
        assert first_executor.cancelled.wait(timeout=5)
        assert not second_executor.cancelled.is_set()
        assert second.view().active is not None
    finally:
        first.control(ControlAction(ControlKind.SHUTDOWN))
        second.control(ControlAction(ControlKind.INTERRUPT_ACTIVE))
        second.control(ControlAction(ControlKind.SHUTDOWN))


def test_background_interrupt_receipt_reports_pending_for_non_cooperative_executor() -> None:
    started = Event()
    release = Event()

    class Executor:
        def execute_with_cancellation(
            self,
            _item: Submission,
            _token: TurnCancellationToken,
        ) -> None:
            started.set()
            release.wait(timeout=5)

    scheduler = TurnScheduler(Executor(), background=True)
    try:
        scheduler.submit(Submission("non-cooperative interrupt"))
        assert started.wait(timeout=5)

        receipt = scheduler.control(ControlAction(ControlKind.INTERRUPT_ACTIVE))

        assert receipt.accepted
        assert receipt.settled is False
        assert "interrupt pending" in receipt.reason
        assert scheduler.view().active is not None
    finally:
        release.set()
        scheduler.control(ControlAction(ControlKind.SHUTDOWN))


def test_failed_session_parks_implicit_resume_but_allows_explicit() -> None:
    """Regression: a failed Turn must not auto-drain the queue.

    The owner reported the cascade: with a dead provider (rate limit /
    circuit open), every queued prompt re-ran into the same failure and
    identical error lines piled onto the page. The implicit RESUME that
    a new FOLLOW_UP submission triggers must be rejected while the
    session is failed; an explicit RESUME (``/queue resume``) is the
    user taking responsibility and proceeds.
    """
    calls: list[str] = []

    def execute(submission: Submission) -> TurnExecutionResult:
        calls.append(submission.content)
        return TurnExecutionResult(TurnExecutionStatus.FAILED, "circuit open")

    scheduler = TurnScheduler(execute)
    scheduler.submit(Submission("first prompt"))
    assert scheduler.view().session_status == "failed"

    # Queue a follow-up; its automatic resume must be parked.
    scheduler.submit(
        Submission("second prompt", kind=SubmissionKind.FOLLOW_UP, source="test")
    )
    implicit = scheduler.control(ControlAction(ControlKind.RESUME))
    assert not implicit.accepted
    assert calls == ["first prompt"], "no queued prompt may re-run while failed"

    # The explicit /queue resume passes the gate and re-runs the work.
    # The executor keeps failing, so exactly ONE queued item is retried
    # and the session parks again — a second implicit cascade must not
    # drain the remaining queue on its own.
    explicit = scheduler.control(ControlAction(ControlKind.RESUME, explicit=True))
    assert explicit.accepted
    assert calls == ["first prompt", "first prompt"], calls
    assert scheduler.view().session_status == "failed"
    still_parked = scheduler.control(ControlAction(ControlKind.RESUME))
    assert not still_parked.accepted
    assert calls == ["first prompt", "first prompt"], "no cascade"


def test_failed_session_toolbar_and_preview_park_the_queue() -> None:
    """The toolbar leads with Failed and the preview collapses parked items."""
    from core.queue_tui import toolbar_queue_status

    class _View:
        active = None
        recovered = object()
        steer: tuple = ()
        follow_up = (("q1",), ("q2",), ("q3",))
        session_status = "failed"

    status = toolbar_queue_status(_View())
    assert status.startswith("Failed"), status
    assert "+3 parked" in status, status
