"""Session adapters for turn scheduling and live-control coordination.

This module keeps the scheduler boundary deep enough that ``AgentSession``
does not own queue admission policy.  It deliberately depends on a small
session-shaped object instead of importing ``core.session``; that keeps the
adapter usable by lightweight test sessions and avoids an import cycle.
"""

from __future__ import annotations

from typing import Any

from core.tool_executor import ToolExecutionOutcome
from core.turn_scheduler import (
    ControlAction,
    ControlKind,
    Submission,
    SubmissionKind,
    TurnExecutorAdapter,
    TurnScheduler,
)


def build_session_scheduler(session: Any, *, live_turns: bool) -> TurnScheduler:
    """Build the one-session scheduler without importing ``AgentSession``."""
    enabled = bool(live_turns)
    return TurnScheduler(
        TurnExecutorAdapter(
            session._run_scheduled_turn,
            cancellation_aware=enabled,
        ),
        id_prefix=f"{session.session_id[:8]}-turn",
        background=enabled,
        context_factory=(lambda _submission: session.runtime_context)
        if enabled
        else None,
        checkpoint=lambda view: _checkpoint_session_view(session, view),
    )


def _checkpoint_session_view(session: Any, view: Any) -> object:
    """Persist one scheduler transition through the session persistence seam."""
    # Keep the import lazy: persistence imports the scheduler's typed control
    # actions for restore, while the scheduler itself must remain usable in
    # memory-only tests and without a session/database import cycle.
    from core.persistence import checkpoint_scheduler_view

    return checkpoint_scheduler_view(session, view)


def _kind_for_view(view: Any) -> SubmissionKind:
    """Infer the default lane for a new prompt from one scheduler view."""
    has_work = (
        view.active is not None
        or view.recovered is not None
        or view.steer
        or view.follow_up
    )
    return SubmissionKind.FOLLOW_UP if has_work else SubmissionKind.START


def _reconcile_submission_kind(
    view: Any,
    kind: SubmissionKind,
) -> SubmissionKind:
    """Resolve a keypress intent against the latest scheduler snapshot.

    Prompt Toolkit classifies the keypress before the main loop dispatches it.
    A fast Turn can finish in that gap, so the UI's START/STEER/FOLLOW_UP hint
    must be reconciled rather than rejected as an internal scheduler error.
    """
    has_queued = bool(view.recovered or view.steer or view.follow_up)
    if kind is SubmissionKind.START:
        if view.active is not None:
            return SubmissionKind.STEER
        if has_queued:
            return SubmissionKind.FOLLOW_UP
    elif kind is SubmissionKind.STEER and view.active is None:
        return SubmissionKind.FOLLOW_UP if has_queued else SubmissionKind.START
    elif kind is SubmissionKind.FOLLOW_UP and view.active is None and not has_queued:
        return SubmissionKind.START
    return kind


def submit_session_turn(
    session: Any,
    user_input: str,
    *,
    kind: SubmissionKind | None = None,
) -> None:
    """Admit a prompt and resume an idle follow-up lane when necessary."""
    if not user_input.strip():
        return
    scheduler = session._turn_scheduler
    view = scheduler.view()
    selected_kind = _kind_for_view(view) if kind is None else kind
    if selected_kind is SubmissionKind.START and view.recovered is not None:
        replacement = scheduler.control(
            ControlAction(ControlKind.REPLACE_RECOVERED, content=user_input)
        )
        if replacement.accepted:
            scheduler.control(ControlAction(ControlKind.RESUME))
        return
    selected_kind = _reconcile_submission_kind(view, selected_kind)
    submission = Submission(user_input, kind=selected_kind, source="session")
    scheduler.submit(submission)
    if selected_kind is SubmissionKind.FOLLOW_UP and view.active is None:
        scheduler.control(ControlAction(ControlKind.RESUME))


def run_session_turn(session: Any, user_input: str) -> Any:
    """Run a prompt through live admission or the synchronous compatibility path."""
    if getattr(session, "_live_turns_enabled", False):
        return submit_session_turn(session, user_input)
    scheduler = session._turn_scheduler
    view = scheduler.view()
    submission = Submission(
        user_input,
        kind=_kind_for_view(view),
        source="session",
    )
    session._sync_runtime_context()
    with session.runtime_context.activate():
        scheduler.submit(submission)
        if submission.kind is SubmissionKind.FOLLOW_UP and view.active is None:
            scheduler.control(ControlAction(ControlKind.RESUME))
    return None


def retry_interrupted_session_turn(session: Any, user_input: str) -> bool:
    """Replace and resume a recoverable prompt without duplicating it."""
    if not user_input.strip():
        return False
    scheduler = session._turn_scheduler
    view = scheduler.view()
    if (
        view.recovered is not None
        and view.session_status in {"interrupted", "failed"}
    ):
        session._sync_runtime_context()
        with session.runtime_context.activate():
            replacement = scheduler.control(
                ControlAction(ControlKind.REPLACE_RECOVERED, content=user_input)
            )
            if replacement.accepted:
                scheduler.control(ControlAction(ControlKind.RESUME))
                return True
    run_session_turn(session, user_input)
    return False


def resume_session_turn(session: Any) -> bool:
    """Resume recovered or queued work without adding a new prompt."""
    scheduler = session._turn_scheduler
    view = scheduler.view()
    if view.active is not None:
        return bool(view.follow_up)
    if view.recovered is None and not view.follow_up:
        return False
    if getattr(session, "_live_turns_enabled", False):
        return scheduler.control(ControlAction(ControlKind.RESUME)).accepted
    session._sync_runtime_context()
    with session.runtime_context.activate():
        return scheduler.control(ControlAction(ControlKind.RESUME)).accepted


def shutdown_session(session: Any) -> bool:
    """Close and join the optional worker through the typed scheduler control."""
    scheduler = getattr(session, "_turn_scheduler", None)
    if scheduler is None:
        return True
    receipt = scheduler.control(ControlAction(ControlKind.SHUTDOWN))
    return receipt.accepted


def interrupt_session(session: Any) -> bool:
    """Request cancellation for the active Turn without clearing queues."""
    receipt = session._turn_scheduler.control(
        ControlAction(ControlKind.INTERRUPT_ACTIVE)
    )
    return receipt.accepted


def abort_session(session: Any, *, clear_queued: bool = False) -> int:
    """Cancel the active Turn, optionally clearing queued/recovered work."""
    action = ControlKind.ABORT_ALL if clear_queued else ControlKind.INTERRUPT_ACTIVE
    receipt = session._turn_scheduler.control(ControlAction(action))
    return len(receipt.affected_ids)


def clear_session_queue(session: Any) -> int:
    """Clear queued and recovered work while keeping an active Turn."""
    receipt = session._turn_scheduler.control(ControlAction(ControlKind.CLEAR))
    return len(receipt.affected_ids)


def remove_session_queue(session: Any, submission_id: str) -> Any:
    """Remove one queued submission by its stable scheduler ID."""
    return session._turn_scheduler.control(
        ControlAction(ControlKind.REMOVE, submission_id=submission_id)
    )


def convert_session_queue(
    session: Any,
    submission_id: str,
    target_kind: SubmissionKind,
) -> Any:
    """Convert one queued submission while preserving its identity."""
    return session._turn_scheduler.control(
        ControlAction(
            ControlKind.CONVERT,
            submission_id=submission_id,
            target_kind=target_kind,
        )
    )


def recall_session_queue(session: Any, submission_id: str | None = None) -> str | None:
    """Return queued/recovered content for editor recall without consuming it."""
    view = session._turn_scheduler.view()
    entries = [item for item in (*view.steer, *view.follow_up)]
    if view.recovered is not None:
        entries.append(view.recovered)
    if submission_id is not None:
        entries = [item for item in entries if item.submission_id == submission_id]
    if not entries:
        return None
    return max(entries, key=lambda item: item.sequence).content


def claim_steer(session: Any) -> Submission | None:
    """Claim the oldest steer at a Tool safe point, if a scheduler is present."""
    scheduler = getattr(session, "_turn_scheduler", None)
    if scheduler is None:
        return None
    receipt = scheduler.control(ControlAction(ControlKind.CLAIM_STEER))
    if not receipt.accepted:
        return None
    return receipt.claimed


def record_skipped_tool_call(
    session: Any,
    tc: dict,
    *,
    iteration: int,
) -> ToolExecutionOutcome:
    """Append a protocol-complete skipped result without running side effects."""
    tool_call_id = str(tc.get("id", ""))
    content = (
        "SKIPPED: tool call was not executed because a steering message "
        "was accepted at the Tool safe point."
    )
    session.messages.append({
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": content,
    })
    outcome = ToolExecutionOutcome(
        status="skipped",
        content=content,
        side_effect=False,
    )
    session._event_emitter().tool_result(tc, outcome, iteration)
    return outcome


def record_interrupted_tool_call(
    session: Any,
    tc: dict,
    *,
    iteration: int,
    reason: str | None = None,
) -> ToolExecutionOutcome:
    """Close one unfinished Tool Call pair without replaying its side effect."""
    tool_call_id = str(tc.get("id", ""))
    detail = reason.strip() if isinstance(reason, str) and reason.strip() else "turn interrupted"
    content = (
        "INTERRUPTED: tool call did not produce a complete result because "
        f"the Turn was cancelled ({detail}); side effects will not be replayed automatically."
    )
    session.messages.append({
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": content,
    })
    outcome = ToolExecutionOutcome(
        status="interrupted",
        content=content,
        side_effect=True,
    )
    session._event_emitter().tool_result(tc, outcome, iteration)
    return outcome


__all__ = [
    "abort_session",
    "build_session_scheduler",
    "claim_steer",
    "clear_session_queue",
    "convert_session_queue",
    "interrupt_session",
    "recall_session_queue",
    "record_interrupted_tool_call",
    "record_skipped_tool_call",
    "remove_session_queue",
    "resume_session_turn",
    "retry_interrupted_session_turn",
    "run_session_turn",
    "shutdown_session",
    "submit_session_turn",
]
