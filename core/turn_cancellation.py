"""Per-Turn cooperative cancellation primitives.

The readline fallback still has a process-level SIGINT compatibility layer,
but background Turns must never share that state.  This small token mirrors
the delegation runtime's cancellation contract without importing the whole
orchestrator into the session path.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from threading import Event, Lock
from typing import Any, cast

from core.tool_executor import ToolExecutionOutcome


_ACTIVE_TURN_CANCELLATION: ContextVar[TurnCancellationToken | None] = ContextVar(
    "pawnlogic_turn_cancellation",
    default=None,
)


class TurnCancellationToken:
    """Thread-safe, one-way cancellation state for one active Turn."""

    def __init__(self) -> None:
        self._event = Event()
        self._lock = Lock()
        self._reason: str | None = None
        self._callbacks: dict[int, Callable[[], object]] = {}

    @property
    def cancelled(self) -> bool:
        """Return whether cancellation has been requested."""
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        """Return the first cancellation reason, if one was supplied."""
        with self._lock:
            return self._reason

    def is_cancelled(self) -> bool:
        """Compatibility method for cancellation-aware adapters."""
        return self.cancelled

    def cancel(self, reason: str = "turn interrupted") -> bool:
        """Request cancellation and notify this token's callbacks once.

        Returns ``True`` only for the transition from active to cancelled.
        Callback failures are isolated from the scheduler; a failing socket
        close must not prevent the worker from observing the token.
        """
        normalized = reason.strip() if isinstance(reason, str) else ""
        callbacks: tuple[Callable[[], object], ...]
        with self._lock:
            if self._event.is_set():
                return False
            self._reason = normalized or "turn interrupted"
            self._event.set()
            callbacks = tuple(self._callbacks.values())
        for callback in callbacks:
            with suppress(Exception):
                callback()
        return True

    def register_abort(self, callback: Callable[[], object]) -> Callable[[], None]:
        """Register a callback that cancels one blocking operation.

        If this Turn was already cancelled, the callback is invoked
        immediately and is not retained.
        """
        if not callable(callback):
            raise TypeError("callback must be callable")
        callback_id = id(callback)
        invoke_now = False
        with self._lock:
            if self._event.is_set():
                invoke_now = True
            else:
                self._callbacks[callback_id] = callback
        if invoke_now:
            with suppress(Exception):
                callback()

        def unregister() -> None:
            with self._lock:
                if self._callbacks.get(callback_id) is callback:
                    del self._callbacks[callback_id]

        return unregister

    def wait(self, timeout: float | None = None) -> bool:
        """Wait until this Turn is cancelled and return the event state."""
        return self._event.wait(timeout)


def current_turn_cancellation() -> TurnCancellationToken | None:
    """Return the token active in the current worker/thread context."""
    return _ACTIVE_TURN_CANCELLATION.get()


@contextmanager
def activate_turn_cancellation(
    token: TurnCancellationToken | None,
) -> Iterator[TurnCancellationToken | None]:
    """Bind one token for nested provider and tool execution helpers."""
    marker = _ACTIVE_TURN_CANCELLATION.set(token)
    try:
        yield token
    finally:
        _ACTIVE_TURN_CANCELLATION.reset(marker)


def execute_cancellable_tool_batch(
    calls: Mapping[int, Mapping[str, Any]],
    *,
    current_tools: list[dict[str, Any]] | None,
    execute_call: Callable[
        [int, Mapping[str, Any], list[dict[str, Any]] | None],
        tuple[list[dict[str, Any]] | None, Any],
    ],
    plan_signal_injected: bool,
    inject_plan_signal: Callable[[], None],
    claim_safe_point: Callable[[], bool] | None = None,
    skip_call: Callable[[int, Mapping[str, Any]], Any] | None = None,
    cancellation_check: Callable[[], bool] | None = None,
    interrupt_call: Callable[[int, Mapping[str, Any]], Any] | None = None,
) -> Any:
    """Run one serial Tool batch with safe cancellation protocol closure.

    Kept outside the budgeted orchestration module so its cancellation
    branches do not make the stable ``TurnToolLoop`` interface harder to
    audit.  The return type is imported lazily to avoid a module cycle.
    """
    if claim_safe_point is not None and skip_call is None:
        raise ValueError("skip_call is required when claim_safe_point is enabled")
    if cancellation_check is not None and (
        interrupt_call is None or skip_call is None
    ):
        raise ValueError(
            "skip_call and interrupt_call are required when cancellation is enabled"
        )

    outcomes: list[Any] = []
    active_tools = current_tools
    safe_point_claimed = False
    ordered_calls = sorted(calls)
    for position, index in enumerate(ordered_calls):
        call = calls[index]
        if safe_point_claimed:
            assert skip_call is not None
            outcomes.append(skip_call(index, call))
            continue
        if cancellation_check is not None and cancellation_check():
            assert interrupt_call is not None and skip_call is not None
            outcomes.append(interrupt_call(index, call))
            for skipped_index in ordered_calls[position + 1 :]:
                outcomes.append(skip_call(skipped_index, calls[skipped_index]))
            break
        try:
            active_tools, outcome = execute_call(index, call, active_tools)
        except BaseException:
            if cancellation_check is None or not cancellation_check():
                raise
            assert interrupt_call is not None and skip_call is not None
            outcomes.append(interrupt_call(index, call))
            for skipped_index in ordered_calls[position + 1 :]:
                outcomes.append(skip_call(skipped_index, calls[skipped_index]))
            break
        outcomes.append(outcome)
        if cancellation_check is not None and cancellation_check():
            assert skip_call is not None
            for skipped_index in ordered_calls[position + 1 :]:
                outcomes.append(skip_call(skipped_index, calls[skipped_index]))
            break
        if claim_safe_point is not None:
            safe_point_claimed = claim_safe_point()
    if plan_signal_injected:
        inject_plan_signal()
    from core.session_tool_loop import ToolBatchOutcome

    return ToolBatchOutcome(
        outcomes=tuple(outcomes),
        current_tools=active_tools,
        plan_signal_injected=plan_signal_injected,
    )


def execute_session_tool_batch(
    session: Any,
    tc_buf: dict,
    *,
    plan_signal_injected: bool,
    iteration: int,
    max_iter: int,
    tool_executor: Any,
    result_processor: Any,
    current_tools: list[Any] | None,
) -> list[Any] | None:
    """Coordinate one session Tool batch around cancellation and safe points."""
    from core.live_turn_control import (
        claim_steer,
        record_interrupted_tool_call,
        record_skipped_tool_call,
    )
    from core.session import TurnInterrupted
    from core.session_tool_loop import TurnToolLoop

    claimed_steer: list[Any] = []
    scheduler = getattr(session, "_turn_scheduler", None)
    cancellation = current_turn_cancellation()

    def claim_safe_point() -> bool:
        claimed = claim_steer(session)
        if claimed is None:
            return False
        claimed_steer.append(claimed)
        return True

    batch = TurnToolLoop().execute_batch(
        tc_buf,
        current_tools=current_tools,
        execute_call=lambda i, tc, tools: session._execute_one_tool_call(
            i,
            dict(tc),
            iteration=iteration,
            max_iter=max_iter,
            tool_executor=tool_executor,
            result_processor=result_processor,
            current_tools=tools,
            plan_notice=plan_signal_injected,
        ),
        plan_signal_injected=plan_signal_injected,
        inject_plan_signal=session._inject_plan_missing_signal,
        claim_safe_point=claim_safe_point if scheduler is not None else None,
        skip_call=(
            cast(
                Callable[[int, Mapping[str, Any]], ToolExecutionOutcome],
                lambda i, tc: record_skipped_tool_call(
                    session,
                    dict(tc),
                    iteration=iteration,
                ),
            )
            if scheduler is not None
            else None
        ),
        cancellation_check=(
            (lambda: cancellation is not None and cancellation.cancelled)
            if cancellation is not None
            else None
        ),
        interrupt_call=(
            cast(
                Callable[[int, Mapping[str, Any]], ToolExecutionOutcome],
                lambda i, tc: record_interrupted_tool_call(
                    session,
                    dict(tc),
                    iteration=iteration,
                    reason=cancellation.reason if cancellation is not None else None,
                ),
            )
            if cancellation is not None
            else None
        ),
    )
    for submission in claimed_steer:
        session.messages.append({"role": "user", "content": submission.content})
    if cancellation is not None and cancellation.cancelled:
        raise TurnInterrupted()
    return batch.current_tools


__all__ = [
    "TurnCancellationToken",
    "activate_turn_cancellation",
    "current_turn_cancellation",
    "execute_cancellable_tool_batch",
    "execute_session_tool_batch",
]
