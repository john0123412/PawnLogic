"""Synchronous per-session scheduling for live turn-control migration.

The scheduler owns admission and lifecycle state for one session.  It is
deliberately synchronous in 0.3.6 P1: an idle submission drives the injected
executor in the caller, while submissions made during an active execution are
admitted without touching the executor.  P2 may move that drive into a worker
without changing the three-entry control surface.

``MessageQueue`` used a bounded deque that silently discarded work and mixed
future input with interrupted work.  This module keeps those concerns in
separate lanes and makes capacity, recovery, and duplicate IDs explicit.
Steering is consumed by the turn/tool loop at a Tool Call safe point. If a
text-only Turn completes before exposing a safe point, the oldest unclaimed
steer becomes the next Turn instead of leaving the scheduler permanently
stuck in ``STEER_QUEUED``.

FIFO is guaranteed within each lane, not across mixed lanes. The admission
sequence records the global order for persistence and inspection. Steer
entries take precedence over follow-up entries at safe points and when an
unclaimed steer rolls forward after natural completion.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Mapping
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, field, replace
from enum import Enum
from math import isfinite
from threading import Condition, Lock, Thread, current_thread
from types import MappingProxyType
from typing import Any, Protocol, cast

from core.turn_cancellation import (
    TurnCancellationToken,
    activate_turn_cancellation,
)


SCHEDULER_STATE_SCHEMA = 1


class SchedulerError(RuntimeError):
    """Base class for scheduler admission, control, and restore failures."""


class QueueFullError(SchedulerError):
    """Raised when admitting a queued submission would lose existing work."""


class SchedulerClosedError(SchedulerError):
    """Raised when a closed scheduler receives a new submission."""


class DuplicateSubmissionError(SchedulerError):
    """Raised when a caller reuses a submission ID."""


class InvalidSubmissionError(SchedulerError):
    """Raised when a submission kind is invalid for the current state."""


class InvalidControlError(SchedulerError):
    """Raised when a control action has invalid or incomplete arguments."""


class RestoreStateError(SchedulerError):
    """Raised when a persisted scheduler state cannot be interpreted."""


class SchedulerState(str, Enum):
    """Projected scheduler state exposed through :class:`SchedulerView`."""

    IDLE = "idle"
    RUNNING = "running"
    STEER_QUEUED = "steer_queued"
    FOLLOW_UP_QUEUED = "follow_up_queued"
    RECOVERABLE = "recoverable"


class SubmissionKind(str, Enum):
    """The protocol lane in which a submission is admitted."""

    START = "start"
    STEER = "steer"
    FOLLOW_UP = "follow_up"
    RECOVERED = "recovered"


class SubmissionStatus(str, Enum):
    """Status of an item included in a scheduler view."""

    QUEUED = "queued"
    RUNNING = "running"
    RECOVERED = "recovered"


class ControlKind(str, Enum):
    """Actions accepted by :meth:`TurnScheduler.control`."""

    INTERRUPT_ACTIVE = "interrupt_active"
    RESUME = "resume"
    REPLACE_RECOVERED = "replace_recovered"
    REMOVE = "remove"
    CONVERT = "convert"
    CLEAR = "clear"
    ABORT_ALL = "abort_all"
    CLAIM_STEER = "claim_steer"
    RESTORE = "restore"
    SHUTDOWN = "shutdown"


class TurnExecutionStatus(str, Enum):
    """Outcome returned by an injected turn executor."""

    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


def _immutable_metadata(metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    """Copy one metadata mapping so callers cannot mutate scheduler state."""
    try:
        copied = deepcopy(dict(metadata))
    except Exception:
        copied = dict(metadata)
    return MappingProxyType(copied)


def _copy_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached mapping for a snapshot or control payload."""
    try:
        return deepcopy(dict(mapping))
    except Exception:
        return dict(mapping)


@dataclass(frozen=True, slots=True)
class Submission:
    """Immutable user input submitted to one scheduler lane.

    ``submission_id`` is normally assigned by the scheduler.  Restored
    entries carry their previous ID so retry/edit operations remain stable.
    ``START`` is the default for an idle user prompt; callers must explicitly
    choose ``STEER`` or ``FOLLOW_UP`` while a Turn is running.
    """

    content: str
    kind: SubmissionKind = SubmissionKind.START
    submission_id: str | None = None
    source: str = "repl"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("submission content must be a non-empty string")
        kind = self.kind
        if not isinstance(kind, SubmissionKind):
            try:
                kind = SubmissionKind(kind)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown submission kind: {self.kind!r}") from exc
            object.__setattr__(self, "kind", kind)
        if self.submission_id is not None:
            if not isinstance(self.submission_id, str) or not self.submission_id.strip():
                raise ValueError("submission_id must be a non-empty string or None")
            object.__setattr__(self, "submission_id", self.submission_id.strip())
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("submission source must be a non-empty string")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("submission metadata must be a mapping")
        object.__setattr__(self, "metadata", _immutable_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class _Entry:
    """Internal submission plus its monotonic admission sequence."""

    submission: Submission
    sequence: int


@dataclass(frozen=True, slots=True)
class SubmissionView:
    """Immutable presentation of one active, queued, or recovered item."""

    submission_id: str
    sequence: int
    kind: SubmissionKind
    content: str
    source: str
    status: SubmissionStatus
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.submission_id, str) or not self.submission_id:
            raise ValueError("submission view requires a submission ID")
        if isinstance(self.kind, str) and not isinstance(self.kind, SubmissionKind):
            object.__setattr__(self, "kind", SubmissionKind(self.kind))
        if isinstance(self.status, str) and not isinstance(self.status, SubmissionStatus):
            object.__setattr__(self, "status", SubmissionStatus(self.status))
        object.__setattr__(self, "metadata", _immutable_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class SchedulerView:
    """Consistent immutable snapshot returned by :meth:`TurnScheduler.view`."""

    state: SchedulerState
    active: SubmissionView | None
    steer: tuple[SubmissionView, ...]
    follow_up: tuple[SubmissionView, ...]
    recovered: SubmissionView | None
    session_status: str
    interrupted_at: float | None
    revision: int
    capacity: int
    next_sequence: int
    id_prefix: str = "s"
    last_outcome: TurnExecutionStatus | None = None
    checkpoint_error: str | None = None
    background: bool = False
    closed: bool = False
    worker_alive: bool = False
    worker_error: str | None = None

    @property
    def queued_count(self) -> int:
        """Return the number of queued steer/follow-up entries."""
        return len(self.steer) + len(self.follow_up)

    @property
    def pending_count(self) -> int:
        """Return one for an active Turn, matching the legacy view."""
        return 1 if self.active is not None else 0

    @property
    def total_unfinished_count(self) -> int:
        """Return queued plus recovered entries, excluding active execution."""
        return self.queued_count + (1 if self.recovered is not None else 0)

    def to_state(self) -> dict[str, Any]:
        """Serialize a safe scheduler state for the existing snapshot seam.

        An active item is deliberately represented as ``recovered``.  A
        restarted process must offer it as editable input and must never
        replay a side-effect Tool automatically.
        """
        recovered = self.recovered
        if recovered is None and self.active is not None:
            recovered = SubmissionView(
                submission_id=self.active.submission_id,
                sequence=self.active.sequence,
                kind=SubmissionKind.RECOVERED,
                content=self.active.content,
                source=self.active.source,
                status=SubmissionStatus.RECOVERED,
                metadata=self.active.metadata,
            )

        def encode(item: SubmissionView) -> dict[str, Any]:
            return {
                "id": item.submission_id,
                "sequence": item.sequence,
                "kind": item.kind.value,
                "content": item.content,
                "source": item.source,
                "metadata": _copy_mapping(item.metadata),
            }

        return {
            "schema": SCHEDULER_STATE_SCHEMA,
            "revision": self.revision,
            "id_prefix": self.id_prefix,
            "next_sequence": self.next_sequence,
            "session_status": self.session_status,
            "interrupted_at": self.interrupted_at,
            "steer": [encode(item) for item in self.steer],
            "follow_up": [encode(item) for item in self.follow_up],
            "recovered": encode(recovered) if recovered is not None else None,
        }


@dataclass(frozen=True, slots=True)
class SubmissionReceipt:
    """Admission result for one accepted submission."""

    submission_id: str
    sequence: int
    kind: SubmissionKind
    disposition: str
    state: SchedulerState


@dataclass(frozen=True, slots=True)
class ControlAction:
    """Typed action passed to :meth:`TurnScheduler.control`."""

    kind: ControlKind
    submission_id: str | None = None
    content: str | None = None
    target_kind: SubmissionKind | None = None
    restore_state: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        kind = self.kind
        if not isinstance(kind, ControlKind):
            try:
                kind = ControlKind(kind)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown control kind: {self.kind!r}") from exc
            object.__setattr__(self, "kind", kind)
        if self.submission_id is not None:
            if not isinstance(self.submission_id, str) or not self.submission_id.strip():
                raise ValueError("control submission_id must be non-empty or None")
            object.__setattr__(self, "submission_id", self.submission_id.strip())
        target_kind = self.target_kind
        if target_kind is not None and not isinstance(target_kind, SubmissionKind):
            try:
                target_kind = SubmissionKind(target_kind)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown target submission kind: {self.target_kind!r}") from exc
            object.__setattr__(self, "target_kind", target_kind)
        if self.restore_state is not None:
            if not isinstance(self.restore_state, Mapping):
                raise TypeError("restore_state must be a mapping or None")
            object.__setattr__(self, "restore_state", _copy_mapping(self.restore_state))


@dataclass(frozen=True, slots=True)
class ControlReceipt:
    """Result of a control action."""

    action: ControlKind
    accepted: bool
    affected_ids: tuple[str, ...]
    state: SchedulerState
    reason: str = ""
    worker_joined: bool | None = None
    claimed: Submission | None = None
    settled: bool = True


@dataclass(frozen=True, slots=True)
class TurnExecutionResult:
    """Normalized result returned by a turn executor Adapter."""

    status: TurnExecutionStatus = TurnExecutionStatus.COMPLETED
    detail: str = ""

    def __post_init__(self) -> None:
        status = self.status
        if not isinstance(status, TurnExecutionStatus):
            try:
                status = TurnExecutionStatus(status)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown execution status: {self.status!r}") from exc
            object.__setattr__(self, "status", status)


class TurnExecutor(Protocol):
    """Production or test Adapter for one synchronous Turn execution."""

    def execute(self, submission: Submission) -> TurnExecutionResult | None:
        """Execute one submission and return its normalized outcome."""


class TurnExecutorAdapter:
    """Adapt ``AgentSession._run_turn_active`` without importing AgentSession.

    The callable receives only message content, preserving the existing
    session implementation and avoiding a module import cycle.  Existing
    return values (``None`` for success and ``"failed"`` for failure) are
    normalized for the scheduler.
    """

    def __init__(
        self,
        run_turn: Callable[[str], object],
        *,
        cancellation_aware: bool = False,
    ) -> None:
        if not callable(run_turn):
            raise TypeError("run_turn must be callable")
        if not isinstance(cancellation_aware, bool):
            raise TypeError("cancellation_aware must be a boolean")
        self._run_turn = run_turn
        self._cancellation_aware = cancellation_aware

    def execute(self, submission: Submission) -> TurnExecutionResult:
        return self._normalize(self._run_turn(submission.content))

    def execute_with_cancellation(
        self,
        submission: Submission,
        cancellation: TurnCancellationToken,
    ) -> TurnExecutionResult:
        """Execute with the active Turn token when the adapter opts in.

        The ordinary ``execute`` entry point remains one-argument compatible
        for synchronous callers and existing test adapters.
        """
        if not self._cancellation_aware:
            return self.execute(submission)
        return self._normalize(
            cast(Callable[..., object], self._run_turn)(
                submission.content,
                cancellation=cancellation,
            )
        )

    @staticmethod
    def _normalize(result: object) -> TurnExecutionResult:
        if isinstance(result, TurnExecutionResult):
            return result
        if isinstance(result, str) and result.lower() == TurnExecutionStatus.FAILED.value:
            return TurnExecutionResult(TurnExecutionStatus.FAILED)
        if isinstance(result, str) and result.lower() == TurnExecutionStatus.INTERRUPTED.value:
            return TurnExecutionResult(TurnExecutionStatus.INTERRUPTED)
        return TurnExecutionResult(TurnExecutionStatus.COMPLETED)


class TurnScheduler:
    """Own one session's synchronous active Turn and submission lanes.

    Public interaction is intentionally limited to ``submit()``, ``control()``,
    and ``view()``.  All mutations are serialized by a lock, and the executor
    is always called outside that lock so a running Tool cannot block queue
    inspection or admission from another thread.
    """

    def __init__(
        self,
        executor: TurnExecutor | Callable[[Submission], object],
        *,
        max_queue_size: int = 100,
        checkpoint: Callable[[SchedulerView], object] | None = None,
        id_prefix: str = "s",
        background: bool = False,
        context_factory: Callable[[Submission], object] | None = None,
        shutdown_timeout: float = 5.0,
    ) -> None:
        if (
            not callable(getattr(executor, "execute", None))
            and not callable(getattr(executor, "execute_with_cancellation", None))
            and not callable(executor)
        ):
            raise TypeError(
                "executor must implement execute(submission), "
                "execute_with_cancellation(...), or be callable"
            )
        if isinstance(max_queue_size, bool) or not isinstance(max_queue_size, int):
            raise TypeError("max_queue_size must be an integer")
        if max_queue_size < 1:
            raise ValueError("max_queue_size must be positive")
        if not isinstance(id_prefix, str) or not id_prefix.strip():
            raise ValueError("id_prefix must be a non-empty string")
        if not isinstance(background, bool):
            raise TypeError("background must be a boolean")
        if context_factory is not None and not callable(context_factory):
            raise TypeError("context_factory must be callable or None")
        if isinstance(shutdown_timeout, bool) or not isinstance(
            shutdown_timeout, (int, float)
        ):
            raise TypeError("shutdown_timeout must be a number")
        if not isfinite(float(shutdown_timeout)) or shutdown_timeout < 0:
            raise ValueError("shutdown_timeout must be finite and non-negative")

        self._executor = executor
        self._capacity = max_queue_size
        self._checkpoint = checkpoint
        self._id_prefix = id_prefix.strip()
        self._background = background
        self._context_factory = context_factory
        self._shutdown_timeout = float(shutdown_timeout)
        self._lock = Lock()
        self._worker_condition = Condition(self._lock)
        self._worker: Thread | None = None
        self._shutdown_requested = False
        self._closed = False
        self._worker_error: str | None = None
        self._active: _Entry | None = None
        self._steer: deque[_Entry] = deque()
        self._follow_up: deque[_Entry] = deque()
        self._recovered: _Entry | None = None
        self._next_sequence = 1
        self._seen_ids: set[str] = set()
        self._revision = 0
        self._session_status = "idle"
        self._interrupted_at: float | None = None
        self._last_outcome: TurnExecutionStatus | None = None
        self._driving = False
        self._interrupt_requested = False
        self._abort_requested = False
        self._active_cancellation: TurnCancellationToken | None = None
        self._checkpoint_lock = Lock()
        self._checkpoint_revision = -1
        self._checkpoint_high_watermark = -1
        self._checkpoint_pending: dict[int, SchedulerView] = {}
        self._checkpoint_dispatching = False
        self._checkpoint_error: str | None = None

    # ------------------------------------------------------------------
    # The three-entry public Interface.
    # ------------------------------------------------------------------
    def submit(self, submission: Submission) -> SubmissionReceipt:
        """Admit a submission and drive an idle scheduler synchronously.

        A START submission is valid only when the scheduler has no active,
        queued, or recovered work.  While active, callers must explicitly
        choose STEER or FOLLOW_UP so an API client cannot accidentally change
        the user's intent.
        """
        if not isinstance(submission, Submission):
            raise TypeError("submission must be a Submission")

        start_drive = False
        with self._lock:
            if self._closed:
                raise SchedulerClosedError("scheduler is shut down")
            entry, disposition = self._admit_unlocked(submission)
            admission_state = self._state_unlocked()
            if self._background and self._active is not None:
                self._ensure_worker_unlocked()
                self._worker_condition.notify_all()
            elif disposition == "started" and not self._driving:
                self._driving = True
                start_drive = True
            view = self._view_unlocked()

        self._notify(view)
        if start_drive:
            self._drive()
        return SubmissionReceipt(
            submission_id=entry.submission.submission_id or "",
            sequence=entry.sequence,
            kind=entry.submission.kind,
            disposition=disposition,
            state=admission_state,
        )

    def control(self, action: ControlAction) -> ControlReceipt:
        """Apply one typed queue/recovery control action."""
        if not isinstance(action, ControlAction):
            raise TypeError("action must be a ControlAction")

        start_drive = False
        cancel_callback: Callable[[], object] | None = None
        cancel_token: TurnCancellationToken | None = None
        cancel_reason = "turn interrupted"
        cancelled_submission_id: str | None = None
        wait_for_cancellation = False
        join_worker: Thread | None = None
        with self._lock:
            if action.kind is ControlKind.SHUTDOWN:
                if self._closed:
                    join_worker = self._worker
                    receipt = self._receipt_unlocked(
                        action,
                        False,
                        (),
                        "scheduler is already shut down",
                    )
                else:
                    self._closed = True
                    self._shutdown_requested = True
                    affected = self._all_queued_ids_unlocked()
                    if self._active is not None:
                        self._interrupt_requested = True
                        self._abort_requested = True
                        affected = (*affected, self._active.submission.submission_id or "")
                        cancelled_submission_id = self._active.submission.submission_id
                        cancel_token = self._active_cancellation
                        cancel_reason = "scheduler shutdown"
                        cancel_callback = getattr(self._executor, "cancel", None)
                    self._touch_unlocked()
                    join_worker = self._worker
                    self._worker_condition.notify_all()
                    receipt = self._receipt_unlocked(action, True, affected, "")
            elif action.kind is ControlKind.CLAIM_STEER:
                receipt = self._claim_steer_unlocked(action)
            elif action.kind is ControlKind.INTERRUPT_ACTIVE:
                if self._active is None:
                    return self._receipt_unlocked(action, False, (), "no active Turn")
                self._interrupt_requested = True
                self._abort_requested = False
                self._touch_unlocked()
                cancelled_submission_id = self._active.submission.submission_id
                cancel_token = self._active_cancellation
                cancel_reason = "turn interrupted"
                cancel_callback = getattr(self._executor, "cancel", None)
                wait_for_cancellation = self._background
                receipt = self._receipt_unlocked(
                    action,
                    True,
                    (self._active.submission.submission_id or "",),
                    "cancellation requested; executor remains cooperative",
                )
            elif action.kind is ControlKind.ABORT_ALL:
                affected = self._all_queued_ids_unlocked()
                self._steer.clear()
                self._follow_up.clear()
                self._recovered = None
                self._session_status = "aborted"
                self._interrupted_at = None
                if self._active is not None:
                    self._interrupt_requested = True
                    self._abort_requested = True
                    cancelled_submission_id = self._active.submission.submission_id
                    cancel_token = self._active_cancellation
                    cancel_reason = "turn aborted"
                    cancel_callback = getattr(self._executor, "cancel", None)
                    affected = (*affected, self._active.submission.submission_id or "")
                    wait_for_cancellation = self._background
                else:
                    self._abort_requested = False
                self._touch_unlocked()
                receipt = self._receipt_unlocked(action, True, affected, "")
            elif action.kind is ControlKind.CLEAR:
                affected = self._all_queued_ids_unlocked()
                self._steer.clear()
                self._follow_up.clear()
                self._recovered = None
                self._touch_unlocked()
                receipt = self._receipt_unlocked(action, True, affected, "")
            elif action.kind is ControlKind.REMOVE:
                receipt = self._remove_unlocked(action)
            elif action.kind is ControlKind.CONVERT:
                receipt = self._convert_unlocked(action)
            elif action.kind is ControlKind.REPLACE_RECOVERED:
                receipt = self._replace_recovered_unlocked(action)
            elif action.kind is ControlKind.RESUME:
                start_drive = self._resume_unlocked()
                receipt = self._receipt_unlocked(
                    action,
                    start_drive,
                    (self._active.submission.submission_id or "",)
                    if start_drive and self._active is not None
                    else (),
                    "no recoverable or queued follow-up work" if not start_drive else "",
                )
            elif action.kind is ControlKind.RESTORE:
                if action.restore_state is None:
                    raise InvalidControlError("RESTORE requires restore_state")
                self._restore_unlocked(action.restore_state)
                receipt = self._receipt_unlocked(action, True, self._all_queued_ids_unlocked(), "")
            else:  # pragma: no cover - Enum validation makes this unreachable.
                raise InvalidControlError(f"unsupported control action: {action.kind.value}")

            view = self._view_unlocked()

        self._notify(view)
        if cancel_token is not None:
            cancel_token.cancel(cancel_reason)
        if cancel_callback is not None:
            with suppress(Exception):
                cancel_callback()
        if (
            wait_for_cancellation
            and cancelled_submission_id
            and self._worker is not current_thread()
        ):
            settled = self._wait_for_active_resolution(cancelled_submission_id)
            with self._lock:
                settled_view = self._view_unlocked()
            if not settled:
                receipt = replace(
                    receipt,
                    state=settled_view.state,
                    reason=(
                        "interrupt pending; executor did not acknowledge "
                        "cancellation before timeout"
                    ),
                    settled=False,
                )
            else:
                receipt = replace(
                    receipt,
                    state=settled_view.state,
                    reason="interrupt acknowledged",
                    settled=True,
                )
        if action.kind is ControlKind.SHUTDOWN:
            if join_worker is None:
                worker_joined = True
            elif join_worker is current_thread():
                worker_joined = False
                receipt = replace(
                    receipt,
                    reason="cannot join the shutdown worker from itself",
                )
            else:
                join_worker.join(timeout=self._shutdown_timeout)
                worker_joined = not join_worker.is_alive()
            if not worker_joined and not receipt.reason:
                receipt = replace(
                    receipt,
                    reason="worker did not stop before shutdown timeout",
                )
            receipt = replace(receipt, worker_joined=worker_joined)
        if start_drive and self._background:
            with self._lock:
                self._ensure_worker_unlocked()
                self._worker_condition.notify_all()
        elif start_drive:
            self._drive()
        return receipt

    def _wait_for_active_resolution(
        self,
        submission_id: str,
        *,
        timeout: float = 1.0,
    ) -> bool:
        """Wait briefly for one cancelled active entry to become recoverable.

        The condition releases the scheduler lock while the cooperative worker
        finishes.  A non-cooperative executor therefore produces an explicit
        pending receipt instead of blocking the input loop indefinitely.
        """
        deadline = time.monotonic() + timeout
        with self._worker_condition:
            while (
                self._active is not None
                and self._active.submission.submission_id == submission_id
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._worker_condition.wait(timeout=remaining)
            return True

    def view(self) -> SchedulerView:
        """Return an immutable point-in-time scheduler snapshot."""
        with self._lock:
            return self._view_unlocked()

    # ------------------------------------------------------------------
    # Admission and synchronous drive.
    # ------------------------------------------------------------------
    def _admit_unlocked(self, submission: Submission) -> tuple[_Entry, str]:
        if submission.submission_id and submission.submission_id in self._seen_ids:
            raise DuplicateSubmissionError(
                f"submission ID already exists: {submission.submission_id}"
            )
        kind = submission.kind
        has_work = bool(
            self._active or self._steer or self._follow_up or self._recovered
        )
        if kind is SubmissionKind.START:
            if has_work:
                if self._active is not None:
                    raise InvalidSubmissionError(
                        "START is invalid while a Turn is active; choose STEER or FOLLOW_UP"
                    )
                raise InvalidSubmissionError(
                    "START is invalid while queued or recovered work exists; use RESUME or CLEAR"
                )
        elif kind is SubmissionKind.STEER:
            if self._active is None:
                raise InvalidSubmissionError("STEER requires an active Turn")
            self._ensure_capacity_unlocked()
        elif kind is SubmissionKind.FOLLOW_UP:
            if self._active is None and not (self._recovered or self._steer or self._follow_up):
                raise InvalidSubmissionError(
                    "FOLLOW_UP requires an active Turn or existing queued work"
                )
            self._ensure_capacity_unlocked()
        elif kind is SubmissionKind.RECOVERED:
            raise InvalidSubmissionError("RECOVERED submissions are created only by restore")

        entry = self._new_entry_unlocked(submission)
        if kind is SubmissionKind.START:
            self._active = entry
            self._active_cancellation = TurnCancellationToken()
            self._session_status = "running"
            self._interrupted_at = None
            self._last_outcome = None
            self._worker_error = None
            disposition = "started"
        elif kind is SubmissionKind.STEER:
            self._steer.append(entry)
            disposition = "steer_queued"
        else:
            self._follow_up.append(entry)
            disposition = "follow_up_queued"
        self._touch_unlocked()
        return entry, disposition

    def _ensure_capacity_unlocked(self) -> None:
        if self._queued_count_unlocked() >= self._capacity:
            raise QueueFullError(
                f"scheduler queue is full ({self._capacity}); no submission was dropped"
            )

    def _new_entry_unlocked(self, submission: Submission, *, sequence: int | None = None) -> _Entry:
        if sequence is None:
            sequence = self._next_sequence
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise RestoreStateError("submission sequence must be a positive integer")
        submission_id = submission.submission_id or f"{self._id_prefix}-{sequence:06d}"
        if submission_id in self._seen_ids:
            raise DuplicateSubmissionError(f"submission ID already exists: {submission_id}")
        normalized = replace(submission, submission_id=submission_id)
        self._seen_ids.add(submission_id)
        self._next_sequence = max(self._next_sequence, sequence + 1)
        return _Entry(normalized, sequence)

    def _drive(self) -> None:
        """Run active work until it completes, fails, or awaits P3 steering."""
        try:
            while True:
                with self._lock:
                    active = self._active
                    if active is None:
                        queued_lane = self._steer or self._follow_up
                        if queued_lane and self._session_status not in {"failed", "aborted"}:
                            self._active = queued_lane.popleft()
                            self._active_cancellation = TurnCancellationToken()
                            self._session_status = "running"
                            self._interrupted_at = None
                            self._last_outcome = None
                            self._touch_unlocked()
                            active = self._active
                            view = self._view_unlocked()
                        else:
                            self._driving = False
                            return
                    else:
                        view = None

                if view is not None:
                    self._notify(view)
                if active is None:  # defensive; the branch above always assigns it.
                    continue

                try:
                    with self._lock:
                        cancellation = self._active_cancellation
                        if cancellation is None:
                            cancellation = TurnCancellationToken()
                            self._active_cancellation = cancellation
                    raw_result = self._execute(active.submission, cancellation)
                except KeyboardInterrupt:
                    with self._lock:
                        view = (
                            self._abort_active_unlocked()
                            if self._abort_requested
                            else self._recover_active_unlocked()
                        )
                    self._notify(view)
                    raise
                except Exception:
                    with self._lock:
                        # An executor exception means the outcome of the
                        # side-effect is unknown.  Keep the submission
                        # recoverable instead of silently dropping it.
                        view = (
                            self._abort_active_unlocked()
                            if self._abort_requested
                            else self._recover_active_unlocked()
                        )
                    self._notify(view)
                    raise

                outcome = self._normalize_result(raw_result)
                with self._lock:
                    if self._interrupt_requested:
                        view = (
                            self._abort_active_unlocked()
                            if self._abort_requested
                            else self._recover_active_unlocked()
                        )
                        should_return = True
                    elif outcome.status is TurnExecutionStatus.INTERRUPTED:
                        view = self._recover_active_unlocked()
                        should_return = True
                    elif outcome.status is TurnExecutionStatus.FAILED:
                        # A failed executor result can still leave an
                        # externally visible side effect.  Preserve the
                        # prompt for explicit retry instead of discarding it.
                        view = self._recover_active_unlocked(
                            outcome=TurnExecutionStatus.FAILED,
                            session_status="failed",
                        )
                        should_return = True
                    else:
                        view = self._complete_active_unlocked()
                        should_return = False
                self._notify(view)
                if should_return:
                    return
        finally:
            with self._lock:
                self._driving = False

    def _execute(
        self,
        submission: Submission,
        cancellation: TurnCancellationToken,
    ) -> object:
        executor = getattr(self._executor, "execute", None)
        execute_with_cancellation = getattr(
            self._executor,
            "execute_with_cancellation",
            None,
        )
        if callable(execute_with_cancellation):
            run = lambda: execute_with_cancellation(submission, cancellation)
        elif callable(executor):
            run = lambda: executor(submission)
        else:
            callback = cast(Callable[[Submission], object], self._executor)
            run = lambda: callback(submission)

        if not self._background or self._context_factory is None:
            with activate_turn_cancellation(cancellation):
                return run()

        context = self._context_factory(submission)
        snapshot = getattr(context, "snapshot_for_turn", None)
        if callable(snapshot):
            context = snapshot(turn_id=submission.submission_id)
        activate = getattr(context, "activate", None)
        if not callable(activate):
            raise TypeError("context_factory must return an activatable context")
        with activate(mirror_legacy=False), activate_turn_cancellation(cancellation):
            return run()

    def _ensure_worker_unlocked(self) -> None:
        """Start the one non-daemon worker when background mode needs it."""
        if not self._background or self._closed:
            return
        if self._worker is not None and self._worker.is_alive():
            return
        worker = Thread(
            target=self._worker_loop,
            name=f"pawnlogic-turn-{self._id_prefix}",
            daemon=False,
        )
        self._worker = worker
        worker.start()

    def _worker_loop(self) -> None:
        """Wait for work and serialize all background Turn execution."""
        while True:
            with self._worker_condition:
                while self._active is None and not self._shutdown_requested:
                    self._worker_condition.wait()
                if self._shutdown_requested:
                    return
            try:
                self._drive()
            except BaseException as exc:
                # _drive() has already converted the active entry into a
                # recoverable draft.  Keep the worker alive so RESUME can
                # explicitly retry it; background exceptions must not become
                # unobserved thread deaths.
                with self._worker_condition:
                    self._worker_error = type(exc).__name__
                    self._worker_condition.notify_all()

    @staticmethod
    def _normalize_result(raw_result: object) -> TurnExecutionResult:
        if isinstance(raw_result, TurnExecutionResult):
            return raw_result
        if isinstance(raw_result, str):
            normalized = raw_result.lower()
            if normalized == TurnExecutionStatus.FAILED.value:
                return TurnExecutionResult(TurnExecutionStatus.FAILED)
            if normalized == TurnExecutionStatus.INTERRUPTED.value:
                return TurnExecutionResult(TurnExecutionStatus.INTERRUPTED)
        return TurnExecutionResult(TurnExecutionStatus.COMPLETED)

    # ------------------------------------------------------------------
    # Controls and immutable views.
    # ------------------------------------------------------------------
    def _resume_unlocked(self) -> bool:
        if self._active is not None or self._driving:
            return False
        if self._recovered is not None:
            self._active = self._recovered
            self._recovered = None
        elif self._steer:
            self._active = self._steer.popleft()
        elif self._follow_up:
            self._active = self._follow_up.popleft()
        else:
            return False
        self._active_cancellation = TurnCancellationToken()
        self._session_status = "running"
        self._interrupted_at = None
        self._last_outcome = None
        self._interrupt_requested = False
        self._abort_requested = False
        self._worker_error = None
        self._touch_unlocked()
        self._driving = True
        return True

    def _remove_unlocked(self, action: ControlAction) -> ControlReceipt:
        submission_id = action.submission_id
        if not submission_id:
            raise InvalidControlError("REMOVE requires submission_id")
        if self._active and self._active.submission.submission_id == submission_id:
            return self._receipt_unlocked(action, False, (), "active submissions cannot be removed")
        if self._recovered and self._recovered.submission.submission_id == submission_id:
            self._recovered = None
            self._session_status = "idle"
            self._interrupted_at = None
            self._touch_unlocked()
            return self._receipt_unlocked(action, True, (submission_id,), "")
        for lane in (self._steer, self._follow_up):
            for index, entry in enumerate(lane):
                if entry.submission.submission_id == submission_id:
                    del lane[index]
                    self._touch_unlocked()
                    return self._receipt_unlocked(action, True, (submission_id,), "")
        return self._receipt_unlocked(action, False, (), "submission ID not found")

    def _convert_unlocked(self, action: ControlAction) -> ControlReceipt:
        """Move one queued entry between the steer and follow-up lanes.

        Conversion intentionally keeps the stable ID, admission sequence,
        source, and metadata.  The active and recovered slots are not queue
        lanes: neither can be converted or deleted by a queue control.
        """
        submission_id = action.submission_id
        target_kind = action.target_kind
        if not submission_id:
            raise InvalidControlError("CONVERT requires submission_id")
        if target_kind not in {SubmissionKind.STEER, SubmissionKind.FOLLOW_UP}:
            raise InvalidControlError(
                "CONVERT requires target_kind STEER or FOLLOW_UP"
            )
        if self._active and self._active.submission.submission_id == submission_id:
            return self._receipt_unlocked(
                action, False, (), "active submissions cannot be converted"
            )
        if self._recovered and self._recovered.submission.submission_id == submission_id:
            return self._receipt_unlocked(
                action, False, (), "recovered submissions cannot be converted"
            )

        source_lane: deque[_Entry] | None = None
        found: _Entry | None = None
        for lane in (self._steer, self._follow_up):
            for entry in lane:
                if entry.submission.submission_id == submission_id:
                    source_lane = lane
                    found = entry
                    break
            if found is not None:
                break
        if found is None or source_lane is None:
            return self._receipt_unlocked(action, False, (), "submission ID not found")
        if found.submission.kind is target_kind:
            return self._receipt_unlocked(
                action,
                False,
                (),
                f"submission is already {target_kind.value}",
            )

        source_lane.remove(found)
        converted = _Entry(
            replace(found.submission, kind=target_kind),
            found.sequence,
        )
        target_lane = self._steer if target_kind is SubmissionKind.STEER else self._follow_up
        self._insert_by_sequence_unlocked(target_lane, converted)
        self._touch_unlocked()
        return self._receipt_unlocked(action, True, (submission_id,), "")

    @staticmethod
    def _insert_by_sequence_unlocked(lane: deque[_Entry], entry: _Entry) -> None:
        """Insert an entry without violating FIFO-by-admission sequence."""
        for index, existing in enumerate(lane):
            if entry.sequence < existing.sequence:
                lane.insert(index, entry)
                return
        lane.append(entry)

    def _claim_steer_unlocked(self, action: ControlAction) -> ControlReceipt:
        """Claim the oldest steering entry at the current Tool safe point."""
        if self._active is None:
            return self._receipt_unlocked(action, False, (), "no active Turn")
        if not self._steer:
            return self._receipt_unlocked(action, False, (), "no queued steer")
        entry = self._steer.popleft()
        submission_id = entry.submission.submission_id or ""
        self._touch_unlocked()
        return self._receipt_unlocked(
            action,
            True,
            (submission_id,),
            "",
            claimed=entry.submission,
        )

    def _replace_recovered_unlocked(self, action: ControlAction) -> ControlReceipt:
        if self._recovered is None:
            return self._receipt_unlocked(action, False, (), "no recovered draft")
        if not action.content or not action.content.strip():
            raise InvalidControlError("REPLACE_RECOVERED requires non-empty content")
        old = self._recovered
        updated = Submission(
            content=action.content,
            kind=SubmissionKind.RECOVERED,
            submission_id=old.submission.submission_id,
            source=old.submission.source,
            metadata=old.submission.metadata,
        )
        self._recovered = _Entry(updated, old.sequence)
        self._touch_unlocked()
        return self._receipt_unlocked(action, True, (old.submission.submission_id or "",), "")

    def _receipt_unlocked(
        self,
        action: ControlAction,
        accepted: bool,
        affected_ids: tuple[str, ...],
        reason: str,
        *,
        claimed: Submission | None = None,
        worker_joined: bool | None = None,
    ) -> ControlReceipt:
        return ControlReceipt(
            action.kind,
            accepted,
            affected_ids,
            self._state_unlocked(),
            reason,
            worker_joined,
            claimed,
        )

    def _all_queued_ids_unlocked(self) -> tuple[str, ...]:
        return tuple(
            entry.submission.submission_id or ""
            for entry in (*self._steer, *self._follow_up)
        ) + ((self._recovered.submission.submission_id or "",) if self._recovered else ())

    def _queued_count_unlocked(self) -> int:
        return len(self._steer) + len(self._follow_up) + (1 if self._recovered else 0)

    def _touch_unlocked(self) -> None:
        self._revision += 1

    def _state_unlocked(self) -> SchedulerState:
        if self._recovered is not None:
            return SchedulerState.RECOVERABLE
        if self._steer:
            return SchedulerState.STEER_QUEUED
        if self._follow_up:
            return SchedulerState.FOLLOW_UP_QUEUED
        if self._active is not None:
            return SchedulerState.RUNNING
        return SchedulerState.IDLE

    @staticmethod
    def _entry_view(entry: _Entry, status: SubmissionStatus) -> SubmissionView:
        submission = entry.submission
        return SubmissionView(
            submission_id=submission.submission_id or "",
            sequence=entry.sequence,
            kind=submission.kind,
            content=submission.content,
            source=submission.source,
            status=status,
            metadata=submission.metadata,
        )

    def _view_unlocked(self) -> SchedulerView:
        return SchedulerView(
            state=self._state_unlocked(),
            active=self._entry_view(self._active, SubmissionStatus.RUNNING)
            if self._active
            else None,
            steer=tuple(self._entry_view(entry, SubmissionStatus.QUEUED) for entry in self._steer),
            follow_up=tuple(
                self._entry_view(entry, SubmissionStatus.QUEUED) for entry in self._follow_up
            ),
            recovered=self._entry_view(self._recovered, SubmissionStatus.RECOVERED)
            if self._recovered
            else None,
            session_status=self._session_status,
            interrupted_at=self._interrupted_at,
            revision=self._revision,
            capacity=self._capacity,
            next_sequence=self._next_sequence,
            id_prefix=self._id_prefix,
            last_outcome=self._last_outcome,
            checkpoint_error=self._checkpoint_error,
            background=self._background,
            closed=self._closed,
            worker_alive=bool(self._worker is not None and self._worker.is_alive()),
            worker_error=self._worker_error,
        )

    def _notify(self, view: SchedulerView) -> None:
        checkpoint = self._checkpoint
        if checkpoint is None:
            return

        # Admission can happen from more than one input thread.  Reserve one
        # dispatcher under the lock, then invoke external code with every
        # scheduler lock released.  Re-entrant callbacks enqueue their view
        # and return; the active dispatcher drains it after the callback.
        with self._checkpoint_lock:
            if view.revision <= self._checkpoint_high_watermark:
                return
            self._checkpoint_high_watermark = view.revision
            if view.revision in self._checkpoint_pending:
                return
            self._checkpoint_pending[view.revision] = view
            if self._checkpoint_dispatching:
                return
            self._checkpoint_dispatching = True

        try:
            while True:
                with self._checkpoint_lock:
                    stale = [
                        revision
                        for revision in self._checkpoint_pending
                        if revision <= self._checkpoint_revision
                    ]
                    for stale_revision in stale:
                        self._checkpoint_pending.pop(stale_revision, None)
                    eligible = [
                        revision
                        for revision in self._checkpoint_pending
                        if revision > self._checkpoint_revision
                    ]
                    if not eligible:
                        # This assignment and the empty check are atomic with
                        # respect to a concurrent notifier, so no pending view
                        # can be stranded between dispatchers.
                        self._checkpoint_dispatching = False
                        return
                    revision = min(eligible)
                    next_view = self._checkpoint_pending.pop(revision)

                try:
                    checkpoint(next_view)
                except Exception as exc:
                    # Checkpoint failure is observational: it must not corrupt
                    # or roll back in-memory state, but callers must be able to
                    # see that persistence did not succeed.
                    with self._lock:
                        self._checkpoint_error = (
                            f"{type(exc).__name__}: checkpoint callback failed"
                        )
                else:
                    with self._lock:
                        # Advance only after the callback succeeds.  A failed
                        # write must remain visible and must not make a stale
                        # revision look durable to later notifications.
                        self._checkpoint_revision = max(
                            self._checkpoint_revision,
                            revision,
                        )
                        self._checkpoint_error = None
        finally:
            # Preserve liveness if an external callback raises a BaseException
            # that is intentionally not swallowed by the scheduler.
            with self._checkpoint_lock:
                self._checkpoint_dispatching = False

    # ------------------------------------------------------------------
    # Completion and legacy state restoration.
    # ------------------------------------------------------------------
    def _complete_active_unlocked(self) -> SchedulerView:
        self._active = None
        self._active_cancellation = None
        self._interrupt_requested = False
        self._abort_requested = False
        self._last_outcome = TurnExecutionStatus.COMPLETED
        self._interrupted_at = None
        self._session_status = "completed" if not self._steer and not self._follow_up else "idle"
        self._touch_unlocked()
        self._worker_condition.notify_all()
        return self._view_unlocked()

    def _fail_active_unlocked(self) -> SchedulerView:
        self._active = None
        self._active_cancellation = None
        self._interrupt_requested = False
        self._abort_requested = False
        self._last_outcome = TurnExecutionStatus.FAILED
        self._interrupted_at = None
        self._session_status = "failed"
        self._touch_unlocked()
        self._worker_condition.notify_all()
        return self._view_unlocked()

    def _recover_active_unlocked(
        self,
        *,
        outcome: TurnExecutionStatus = TurnExecutionStatus.INTERRUPTED,
        session_status: str = "interrupted",
    ) -> SchedulerView:
        if self._active is not None:
            active = self._active
            self._recovered = _Entry(
                replace(active.submission, kind=SubmissionKind.RECOVERED),
                active.sequence,
            )
        self._active = None
        self._active_cancellation = None
        self._interrupt_requested = False
        self._abort_requested = False
        self._last_outcome = outcome
        self._session_status = session_status
        self._interrupted_at = time.time()
        self._touch_unlocked()
        self._worker_condition.notify_all()
        return self._view_unlocked()

    def _abort_active_unlocked(self) -> SchedulerView:
        """Finish a cooperatively cancelled active Turn without recovery."""
        self._active = None
        self._active_cancellation = None
        self._interrupt_requested = False
        self._abort_requested = False
        self._last_outcome = TurnExecutionStatus.INTERRUPTED
        self._session_status = "aborted"
        self._interrupted_at = None
        self._touch_unlocked()
        self._worker_condition.notify_all()
        return self._view_unlocked()

    def _restore_unlocked(self, state: Mapping[str, Any]) -> None:
        if self._active is not None or self._driving:
            raise InvalidControlError("cannot restore while a Turn is active")
        if not isinstance(state, Mapping):
            raise RestoreStateError("scheduler state must be a mapping")
        new_prefix = self._id_prefix
        raw_prefix = state.get("id_prefix")
        if raw_prefix is not None:
            if not isinstance(raw_prefix, str) or not raw_prefix.strip():
                raise RestoreStateError("id_prefix must be a non-empty string")
            new_prefix = raw_prefix.strip()
        valid_statuses = {"idle", "running", "completed", "interrupted", "failed", "aborted"}
        raw_status = state.get("session_status", "idle")
        if not isinstance(raw_status, str) or raw_status not in valid_statuses:
            raise RestoreStateError(f"invalid session status: {raw_status!r}")
        interrupted_at = state.get("interrupted_at")
        if interrupted_at is not None and (
            isinstance(interrupted_at, bool)
            or not isinstance(interrupted_at, (int, float))
        ):
            raise RestoreStateError("interrupted_at must be a number or None")
        restored_interrupted_at = (
            float(interrupted_at) if interrupted_at is not None else None
        )
        raw_revision = state.get("revision", 0)
        if (
            isinstance(raw_revision, bool)
            or not isinstance(raw_revision, int)
            or raw_revision < 0
        ):
            raise RestoreStateError("revision must be a non-negative integer")
        parsed = self._parse_state(state, id_prefix=new_prefix)
        all_entries = [*parsed[0], *parsed[1]]
        if parsed[2] is not None:
            all_entries.append(parsed[2])
        if len(all_entries) > self._capacity:
            raise QueueFullError(
                f"restored scheduler state exceeds capacity ({self._capacity})"
            )
        self._steer = deque(parsed[0])
        self._follow_up = deque(parsed[1])
        self._recovered = parsed[2]
        self._id_prefix = new_prefix
        self._next_sequence = parsed[3]
        self._seen_ids = {entry.submission.submission_id or "" for entry in all_entries}
        status = raw_status
        if self._recovered is not None and status in {"idle", "running", "completed"}:
            status = "interrupted"
        self._session_status = status
        self._interrupted_at = restored_interrupted_at
        if self._recovered is not None and self._interrupted_at is None:
            self._interrupted_at = time.time()
        self._last_outcome = None
        self._interrupt_requested = False
        self._abort_requested = False
        self._checkpoint_error = None
        self._revision = max(self._revision, raw_revision)
        self._touch_unlocked()

    def _parse_state(
        self,
        state: Mapping[str, Any],
        *,
        id_prefix: str,
    ) -> tuple[list[_Entry], list[_Entry], _Entry | None, int]:
        """Parse the new state shape and the 0.3.5 queue shape atomically."""
        if not isinstance(state, Mapping):
            raise RestoreStateError("scheduler state must be a mapping")
        schema = state.get("schema")
        if schema is not None and (
            isinstance(schema, bool)
            or not isinstance(schema, int)
            or schema != SCHEDULER_STATE_SCHEMA
        ):
            raise RestoreStateError(f"unsupported scheduler state schema: {schema!r}")
        new_shape = any(key in state for key in ("steer", "follow_up", "recovered"))
        next_sequence = state.get("next_sequence", 1)
        if (
            isinstance(next_sequence, bool)
            or not isinstance(next_sequence, int)
            or next_sequence < 1
        ):
            raise RestoreStateError("next_sequence must be a positive integer")
        used_ids: set[str] = set()
        used_sequences: set[int] = set()
        sequence_cursor = next_sequence
        parsed_steer: list[_Entry] = []
        parsed_follow_up: list[_Entry] = []
        parsed_recovered: _Entry | None = None

        def parse_item(raw: object, lane: SubmissionKind) -> _Entry:
            nonlocal sequence_cursor
            if not isinstance(raw, Mapping):
                raise RestoreStateError("scheduler entry must be a mapping")
            content = raw.get("content")
            if not isinstance(content, str) or not content.strip():
                raise RestoreStateError("scheduler entry content must be non-empty")

            has_id = "id" in raw
            has_submission_id = "submission_id" in raw
            if has_id and has_submission_id and raw["id"] != raw["submission_id"]:
                raise RestoreStateError("id and submission_id do not match")
            raw_id = raw["id"] if has_id else raw.get("submission_id")
            if (has_id or has_submission_id) and (
                raw_id is None
                or not isinstance(raw_id, str)
                or not raw_id.strip()
            ):
                raise RestoreStateError("submission ID must be a non-empty string")
            submission_id = raw_id.strip() if isinstance(raw_id, str) else None

            raw_sequence = raw.get("sequence")
            if raw_sequence is not None and (
                isinstance(raw_sequence, bool)
                or not isinstance(raw_sequence, int)
                or raw_sequence < 1
            ):
                raise RestoreStateError("submission sequence must be a positive integer")
            if raw_sequence is None:
                sequence = sequence_cursor
                while sequence in used_sequences:
                    sequence += 1
            else:
                sequence = raw_sequence
            if sequence in used_sequences:
                raise RestoreStateError(f"duplicate submission sequence: {sequence}")
            used_sequences.add(sequence)
            sequence_cursor = max(sequence_cursor, sequence + 1)

            if submission_id is None:
                submission_id = f"{id_prefix}-{sequence:06d}"
            if submission_id in used_ids:
                raise RestoreStateError(f"duplicate submission ID: {submission_id}")
            used_ids.add(submission_id)

            raw_kind = raw.get("kind")
            if raw_kind is not None and raw_kind != lane.value:
                raise RestoreStateError(
                    f"scheduler entry kind does not match {lane.value!r} lane"
                )
            source = raw.get("source", "legacy")
            if not isinstance(source, str) or not source.strip():
                raise RestoreStateError("scheduler entry source must be non-empty")
            source = source.strip()
            metadata = raw.get("metadata", {})
            if not isinstance(metadata, Mapping):
                raise RestoreStateError("scheduler entry metadata must be a mapping")
            submission = Submission(
                content=content,
                kind=lane,
                submission_id=submission_id,
                source=source,
                metadata=metadata,
            )
            return _Entry(submission, sequence)

        if new_shape:
            raw_steer = state.get("steer", [])
            raw_follow_up = state.get("follow_up", [])
            if not isinstance(raw_steer, list) or not isinstance(raw_follow_up, list):
                raise RestoreStateError("steer and follow_up must be lists")
            for raw in raw_steer:
                parsed_steer.append(parse_item(raw, SubmissionKind.STEER))
            for raw in raw_follow_up:
                parsed_follow_up.append(parse_item(raw, SubmissionKind.FOLLOW_UP))
            raw_recovered = state.get("recovered")
            if raw_recovered is not None:
                parsed_recovered = parse_item(raw_recovered, SubmissionKind.RECOVERED)
        else:
            raw_queue = state.get("queue", [])
            raw_pending = state.get("pending", [])
            if not isinstance(raw_queue, list) or not isinstance(raw_pending, list):
                raise RestoreStateError("legacy queue and pending values must be lists")
            for raw in raw_queue:
                parsed_follow_up.append(parse_item(raw, SubmissionKind.FOLLOW_UP))
            for raw in raw_pending:
                entry = parse_item(raw, SubmissionKind.FOLLOW_UP)
                if parsed_recovered is None:
                    parsed_recovered = _Entry(
                        replace(entry.submission, kind=SubmissionKind.RECOVERED),
                        entry.sequence,
                    )
                else:
                    parsed_follow_up.append(entry)

        max_sequence = max(
            [entry.sequence for entry in (*parsed_steer, *parsed_follow_up)]
            + ([parsed_recovered.sequence] if parsed_recovered else [])
            + [next_sequence - 1],
        )
        return parsed_steer, parsed_follow_up, parsed_recovered, max_sequence + 1


__all__ = [
    "SCHEDULER_STATE_SCHEMA",
    "ControlAction",
    "ControlKind",
    "ControlReceipt",
    "DuplicateSubmissionError",
    "InvalidControlError",
    "InvalidSubmissionError",
    "QueueFullError",
    "RestoreStateError",
    "SchedulerClosedError",
    "SchedulerError",
    "SchedulerState",
    "SchedulerView",
    "Submission",
    "SubmissionKind",
    "SubmissionReceipt",
    "SubmissionStatus",
    "SubmissionView",
    "TurnExecutionResult",
    "TurnExecutionStatus",
    "TurnExecutor",
    "TurnExecutorAdapter",
    "TurnScheduler",
]
