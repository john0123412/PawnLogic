"""Contract tests for the single-Application selector modal.

These tests pin down [ADR 0010](../adr/0010-inline-terminal-modal.md):
opening a selector must NOT tear down the main Prompt Toolkit
``Application`` and must NOT spawn a second ``Application``. The main
task must remain alive, the ``Application`` object identity must be
stable across the round trip, the recovered-draft marker must
survive, and the queue preview callback must keep working.

They are written against the public ``PersistentTerminal`` and
``PersistentTerminalController`` contract, so they keep working as the
implementation is rewritten to honor the ADR.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("prompt_toolkit")

from prompt_toolkit.input import DummyInput  # noqa: E402
from prompt_toolkit.output import DummyOutput  # noqa: E402

from pawnlogic.live_terminal import (  # noqa: E402
    PersistentTerminal,
    PersistentTerminalController,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubSession:
    """Minimal stand-in for the session object the controller holds."""

    def __init__(self) -> None:
        self._live_terminal_active = False
        self.sink_history: list[Any] = []

    def activate_sink(self, sink: Any) -> None:
        self.sink_history.append(sink)
        self._live_terminal_active = True


def _make_terminal() -> PersistentTerminal:
    return PersistentTerminal(
        input=DummyInput(),
        output=DummyOutput(),
    )


def _make_controller(
    terminal: PersistentTerminal,
    session: _StubSession,
) -> PersistentTerminalController:
    return PersistentTerminalController(
        terminal=terminal,
        session=session,
        activate_sink=session.activate_sink,
        fallback_sink=None,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_pause_for_modal_does_not_exit_main_application() -> None:
    """pause_for_modal must not call Application.exit() on the live app.

    Under the exit-rebuild lifecycle this is violated: pause_for_modal
    awaits the main task to completion, which only finishes once the
    Application loop has terminated. The new contract is a single,
    continuously running Application, so this test fails until the
    lifecycle is rewritten.
    """
    terminal = _make_terminal()
    session = _StubSession()
    controller = _make_controller(terminal, session)
    terminal.prepare_run()

    exit_calls: list[dict[str, Any]] = []

    async def _drive() -> None:
        await controller.start()
        before_app = terminal.application
        assert (
            before_app is not None
        ), "PersistentTerminal must have a live Application after start()"

        def _spy_exit(*args: Any, **kwargs: Any) -> None:
            # Record the call and DO NOT delegate to the real exit.
            # The contract forbids calling Application.exit() at all
            # while a modal is open.
            exit_calls.append({"args": args, "kwargs": kwargs})
            return None

        before_app.exit = _spy_exit  # type: ignore[method-assign]

        try:
            paused = await controller.pause_for_modal(True)
            assert paused is True, "modal host should report it was entered"
            assert exit_calls == [], (
                "Application.exit() must not be called while opening a "
                "selector; saw %r" % exit_calls
            )
            assert (
                terminal.is_running is True
            ), "terminal must still be running while the modal is open"
            assert terminal.application is before_app, (
                "Application object identity must not change while the " "modal is open"
            )
        finally:
            await controller.resume_after_modal(paused)
            await controller.close()

    asyncio.run(_drive())


def test_resume_after_modal_preserves_recovered_draft_marker() -> None:
    """The recovered-draft marker must survive the modal round trip."""
    terminal = _make_terminal()
    session = _StubSession()
    controller = _make_controller(terminal, session)
    terminal.prepare_run()
    terminal.set_recovery_draft("recovered body")

    async def _drive() -> None:
        await controller.start()
        assert (
            terminal.recovery_draft_pending is True
        ), "recovered draft should be marked pre-modal"

        paused = await controller.pause_for_modal(True)
        try:
            assert terminal.recovery_draft_pending is True
        finally:
            await controller.resume_after_modal(paused)
            assert (
                terminal.recovery_draft_pending is True
            ), "recovered-draft marker must survive modal round trip"
            await controller.close()

    asyncio.run(_drive())


def test_resume_after_modal_preserves_application_identity() -> None:
    """Same Application instance must serve before and after the modal."""
    terminal = _make_terminal()
    session = _StubSession()
    controller = _make_controller(terminal, session)
    terminal.prepare_run()

    async def _drive() -> None:
        await controller.start()
        before = terminal.application
        assert before is not None

        paused = await controller.pause_for_modal(True)
        try:
            await controller.resume_after_modal(paused)
            after = terminal.application
            assert (
                after is before
            ), "modal round trip must not rebuild the main Application"
        finally:
            await controller.close()

    asyncio.run(_drive())
