"""Regressions for the parked-turn recovery and live-modal routing defects.

Context (owner-reported freeze after HTTP 429 rate limiting):

1. A failed Turn parks the session (``session_status == "failed"``) and mints
   a recovered draft.  The live composer counted that draft as *queued work*,
   so a freshly typed prompt was classified ``FOLLOW_UP``.  Its implicit
   RESUME was then refused by the anti-cascade gate, the prompt was queued
   silently, and the status line still read ``Idle`` — typing appeared to do
   nothing and only a force-quit helped.

2. ``/provider fetch|update|add`` built and ran a *second* Prompt Toolkit
   ``Application`` while the persistent one was alive.  ADR 0010 and
   ``pawnlogic/selectors.py`` both forbid that: two ``Vt100_Output``
   instances competing for one PTY corrupt the cursor/escape state.

3. An Application task that ended without ``close()`` left the CLI loop
   parked in ``next_submission()`` forever.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from core.live_turn_control import (
    PARKED_SESSION_STATUSES,
    _kind_for_view,
    _reconcile_submission_kind,
    submit_session_turn,
)
from core.turn_scheduler import (
    Submission,
    SubmissionKind,
    TurnExecutionResult,
    TurnExecutionStatus,
    TurnScheduler,
)
from pawnlogic.selectors import ModelMultiSelect
from pawnlogic.live_terminal import PersistentTerminal


def _failed_scheduler() -> TurnScheduler:
    """Return a scheduler whose first Turn fails like a tripped circuit."""

    def execute(_submission: Submission) -> TurnExecutionResult:
        return TurnExecutionResult(TurnExecutionStatus.FAILED, "circuit open")

    scheduler = TurnScheduler(execute)
    scheduler.submit(Submission("hi"))
    assert scheduler.view().session_status == "failed"
    assert scheduler.view().recovered is not None
    return scheduler


# ════════════════════════════════════════════════════════
# Defect 1: a parked recovered draft must not swallow new prompts
# ════════════════════════════════════════════════════════

def test_recovered_draft_is_not_treated_as_queued_work() -> None:
    """A recovered retry offer must resolve to START, not FOLLOW_UP.

    START is what admits the replace-and-resume path.  Classifying it as
    queued work routed the prompt to FOLLOW_UP, whose implicit RESUME the
    anti-cascade gate refuses.
    """
    scheduler = _failed_scheduler()
    view = scheduler.view()

    assert view.recovered is not None
    assert not view.steer and not view.follow_up
    assert _kind_for_view(view) is SubmissionKind.START
    assert _reconcile_submission_kind(view, SubmissionKind.START) is SubmissionKind.START


def test_queued_lanes_still_resolve_to_follow_up() -> None:
    """The fix must not stop real queued work from using the follow-up lane."""
    view = SimpleNamespace(
        active=None,
        recovered=None,
        steer=(),
        follow_up=("queued",),
        session_status="idle",
    )

    assert _kind_for_view(view) is SubmissionKind.FOLLOW_UP
    assert _reconcile_submission_kind(view, SubmissionKind.START) is SubmissionKind.FOLLOW_UP


def test_prompt_after_failed_turn_is_admitted_and_runs() -> None:
    """Enter after a 429 must run the new prompt, not park it silently.

    Before the fix the prompt landed in the follow-up lane with no user
    signal while the status line kept reporting Idle.
    """
    calls: list[str] = []
    state = {"fail": True}

    def execute(submission: Submission) -> TurnExecutionResult:
        calls.append(submission.content)
        if state["fail"]:
            return TurnExecutionResult(TurnExecutionStatus.FAILED, "circuit open")
        return TurnExecutionResult(TurnExecutionStatus.COMPLETED)

    session = SimpleNamespace(_turn_scheduler=TurnScheduler(execute))
    session._turn_scheduler.submit(Submission("hi"))
    assert session._turn_scheduler.view().session_status == "failed"

    # The user switched to a healthy model and typed a new question.
    state["fail"] = False
    submit_session_turn(session, "follow-up question")

    view = session._turn_scheduler.view()
    assert calls == ["hi", "follow-up question"], calls
    assert view.session_status == "completed"
    assert view.total_unfinished_count == 0


def test_prompt_after_failed_turn_with_queued_work_uses_explicit_resume() -> None:
    """A parked session with real queued work resumes explicitly on Enter."""

    def execute(_submission: Submission) -> TurnExecutionResult:
        return TurnExecutionResult(TurnExecutionStatus.FAILED, "circuit open")

    scheduler = TurnScheduler(execute)
    scheduler.submit(Submission("hi"))
    # A queued row that the anti-cascade gate is holding back.
    scheduler.submit(
        Submission("waiting", kind=SubmissionKind.FOLLOW_UP, source="test")
    )
    assert scheduler.view().session_status == "failed"

    session = SimpleNamespace(_turn_scheduler=scheduler)
    submit_session_turn(session, "typed now")

    # The explicit resume moved one queued entry into execution; the
    # session is no longer parked with everything stranded.
    assert scheduler.view().recovered is None


def test_parked_status_vocabulary_covers_failed_and_aborted() -> None:
    assert frozenset({"failed", "aborted"}) == PARKED_SESSION_STATUSES


# ════════════════════════════════════════════════════════
# Defect 2: no second Application for live multi-select
# ════════════════════════════════════════════════════════

def test_live_model_multi_select_uses_controller_not_second_application() -> None:
    """The live path must run the selector inside the host Application."""
    from core.commands import provider as provider_cmd

    entries = [("m1", {"id": "m1"}), ("m2", {"id": "m2", "vision": True})]

    class _Controller:
        def __init__(self) -> None:
            self.selector_type: str | None = None

        async def run_selector(self, factory):
            selector = factory()
            self.selector_type = type(selector).__name__
            selector.handle_key("enter")
            return selector.result

    async def scenario() -> tuple[_Controller, list[str]]:
        controller = _Controller()
        chosen = await provider_cmd._select_models_to_register(
            entries, terminal_controller=controller
        )
        return controller, chosen

    controller, chosen = asyncio.run(scenario())
    assert controller.selector_type == "ModelMultiSelect"
    assert chosen == ["m1", "m2"]


def test_standalone_selector_is_used_only_without_a_controller(monkeypatch) -> None:
    """The readline/headless fallback keeps the standalone selector seam."""
    from core.commands import provider as provider_cmd

    entries = [("m1", {"id": "m1"})]
    seen: list[str] = []

    async def fake_standalone(entries_):
        seen.append("standalone")
        return [mid for mid, _ in entries_]

    monkeypatch.setattr(provider_cmd, "_provider_fetch_selector", fake_standalone)

    async def scenario() -> list[str]:
        return await provider_cmd._select_models_to_register(
            entries, terminal_controller=None
        )

    assert asyncio.run(scenario()) == ["m1"]
    assert seen == ["standalone"]


def test_model_multi_select_toggles_and_confirms() -> None:
    """Space toggles, A/N select all/none, Enter returns chosen ids in order."""
    selector = ModelMultiSelect([("a", {}), ("b", {}), ("c", {})])

    assert selector.chosen == {0, 1, 2}
    selector.handle_key("space")
    assert selector.chosen == {1, 2}
    selector.handle_key("n")
    assert selector.chosen == set()
    selector.handle_key("down")
    selector.handle_key("space")
    selector.handle_key("enter")

    assert selector.result == ["b"]
    assert selector.is_closed


def test_model_multi_select_cancel_returns_empty() -> None:
    selector = ModelMultiSelect([("a", {})])
    selector.handle_key("escape")
    assert selector.result == []
    assert selector.is_closed


# ════════════════════════════════════════════════════════
# Defect 3: a dead Application must not park the CLI loop
# ════════════════════════════════════════════════════════

def test_application_death_releases_next_submission() -> None:
    """next_submission() must return when the Application died.

    Previously the waiter stayed parked on an event nobody would set, so
    the only way out was a force-quit.
    """

    async def scenario() -> None:
        terminal = PersistentTerminal()
        terminal._loop = asyncio.get_running_loop()
        terminal._running = True

        waiter = asyncio.create_task(terminal.next_submission())
        await asyncio.sleep(0.05)
        assert not waiter.done(), "waiter should be parked before the death"

        # What run()'s teardown does when the Application task ends
        # without close().
        with terminal._lock:
            terminal._failed = True
            terminal._wake_submission_waiter_locked()

        assert await asyncio.wait_for(waiter, timeout=1.0) is None
        assert terminal.failed is True

    asyncio.run(scenario())


def test_application_death_resolves_a_pending_selector() -> None:
    """The controller observer must release a command awaiting a selector."""

    async def scenario() -> None:
        terminal = PersistentTerminal()
        terminal._loop = asyncio.get_running_loop()

        selector = ModelMultiSelect([("a", {})])
        future = terminal.open_selector(selector)
        assert not future.done()

        released = terminal.abandon_selectors()
        assert released is True
        assert future.done()
        assert future.result() is None
        assert terminal.selector_registry.has_active is False

    asyncio.run(scenario())


def test_normal_close_still_releases_the_waiter() -> None:
    """close() keeps its existing contract after the death-path change."""

    async def scenario() -> None:
        terminal = PersistentTerminal()
        terminal._loop = asyncio.get_running_loop()
        terminal._running = True

        waiter = asyncio.create_task(terminal.next_submission())
        await asyncio.sleep(0.05)
        assert not waiter.done()

        terminal.close()
        assert await asyncio.wait_for(waiter, timeout=1.0) is None
        # An orderly close is not a failure.
        assert terminal.failed is False

    asyncio.run(scenario())


def test_unexpected_exit_notice_reaches_the_real_stdout(capsys) -> None:
    """The death notice must bypass the dead Application's output proxy.

    A crash that raises out of the Application unwinds through asyncio.run,
    so the CLI's shutdown block never gets to print; the notice is emitted
    from the controller's task observer instead, after restoring stdout.
    Printing while the proxy is still installed writes into the dead
    terminal's sink and the user sees nothing (found under a real PTY).
    """
    terminal = PersistentTerminal()
    proxy = terminal.install_output_proxy()

    terminal.report_unexpected_exit()

    captured = capsys.readouterr()
    assert "stopped unexpectedly" in captured.out, captured.out
    # stdout must be restored, not left pointing at the dead sink.
    import sys

    assert proxy is not None
    assert sys.stdout is not proxy


def test_report_unexpected_exit_never_raises() -> None:
    """The notice runs from a done-callback: it must be exception-free."""
    terminal = PersistentTerminal()
    # No proxy installed and no frames to restore: still must not raise.
    terminal.report_unexpected_exit()
