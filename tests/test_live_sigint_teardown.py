"""Teardown tests for the live SIGINT handler.

The owner's exit traceback was::

    Exception ignored in: <module 'threading'>
      File "/usr/lib/python3.12/threading.py", line 1622, in _shutdown
        lock.acquire()
      File ".../pawnlogic/live_repl.py", line 436, in _handler
        raise KeyboardInterrupt

An idle Ctrl+C raises ``KeyboardInterrupt`` inside the Application task, so
the exception unwinds through ``asyncio.run`` and the CLI shutdown block --
the only caller of ``restore()`` -- is skipped.  The handler therefore
outlived the REPL and re-raised a stray Ctrl+C inside ``threading._shutdown``.

These tests pin the seam that closes that hole: the controller disarms the
handler from its Application done-callback, which ``Runner.close()`` drives
before the loop is closed.
"""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Coroutine
from types import SimpleNamespace
from typing import Any

import pytest

from pawnlogic.live_repl import install_live_interrupt_handler
from pawnlogic.live_terminal import PersistentTerminalController


@pytest.fixture
def sigint_guard():
    """Keep a stray Ctrl+C from reaching the pytest process itself."""
    previous = signal.getsignal(signal.SIGINT)
    yield
    signal.signal(signal.SIGINT, previous)


class _IdleSession:
    """The session surface the live SIGINT handler actually touches."""

    _live_terminal_active = False

    def queue_status(self) -> dict[str, int]:
        return {"pending_count": 0}

    def interrupt_active(self) -> bool:
        return False


def _controller(session: _IdleSession) -> PersistentTerminalController:
    terminal = SimpleNamespace(
        is_closed=False,
        abandon_selectors=lambda: False,
        report_unexpected_exit=lambda: None,
    )
    return PersistentTerminalController(terminal, session, lambda _sink: None)


def _run_expecting_routed_interrupt(coro: Coroutine[Any, Any, None]) -> None:
    """Run a coroutine that signals *this* process, containing the escape.

    These probes fire a real ``SIGINT`` at the pytest process.  When the
    routing regresses, the ``KeyboardInterrupt`` unwinds out of
    ``asyncio.run`` and out of the test, and pytest treats that as a session
    abort: the run stops at exit code 2 and the remaining tests never execute.
    Measured on a full fast-suite run, 679 of 1727 tests ran and the summary
    line still read "679 passed".  Contain the exception here so the
    regression surfaces as a normal, named failure of this test instead.
    """
    try:
        asyncio.run(coro)
    except KeyboardInterrupt:
        pytest.fail(
            "idle SIGINT escaped as KeyboardInterrupt instead of routing to "
            "on_idle_interrupt"
        )


def test_idle_ctrl_c_neutralizes_sigint_before_interpreter_shutdown(sigint_guard):
    """A stray Ctrl+C after an idle-Ctrl+C exit must not raise.

    This reproduces the reported failure end to end: the handler raises
    inside the Application task, ``asyncio.run`` unwinds, the CLI shutdown
    block never runs, and only the controller's done-callback is left.
    """
    session = _IdleSession()
    controller = _controller(session)

    async def application_task() -> None:
        """Stands in for ``Application.run_async()``: the frame ^C lands in."""
        await asyncio.sleep(3600)

    async def main() -> None:
        install_live_interrupt_handler(session)
        task = asyncio.create_task(application_task())
        task.add_done_callback(controller._observe_terminal_task)
        await asyncio.sleep(0.05)
        os.kill(os.getpid(), signal.SIGINT)
        await task

    with pytest.raises(KeyboardInterrupt):
        asyncio.run(main())

    # The production shutdown block is skipped exactly as it is for the owner.
    assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN


def test_disarm_is_idempotent(sigint_guard):
    session = _IdleSession()
    install_live_interrupt_handler(session)

    session._live_sigint_disarm()
    session._live_sigint_disarm()

    assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN


def test_restore_after_disarm_reinstates_the_previous_handler(sigint_guard):
    """The normal ``/exit`` path still hands SIGINT back to the caller."""
    session = _IdleSession()
    baseline = signal.getsignal(signal.SIGINT)
    restore = install_live_interrupt_handler(session)

    session._live_sigint_disarm()
    restore()

    assert signal.getsignal(signal.SIGINT) is baseline


def test_observer_disarms_on_every_task_outcome(sigint_guard):
    """The early returns below must not skip the disarm."""
    for outcome in ("cancelled", "not_yet_finished", "clean_failure"):
        session = _IdleSession()
        controller = _controller(session)
        install_live_interrupt_handler(session)

        if outcome == "cancelled":
            task = SimpleNamespace(cancelled=lambda: True)
        elif outcome == "not_yet_finished":
            def task_exception():
                raise asyncio.InvalidStateError

            task = SimpleNamespace(
                cancelled=lambda: False, exception=task_exception
            )
        else:
            task = SimpleNamespace(
                cancelled=lambda: False, exception=lambda: None
            )

        controller._observe_terminal_task(task)

        assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN, outcome


def test_observer_is_safe_without_a_live_handler(sigint_guard):
    """A session that never installed a live handler must not break teardown."""
    session = _IdleSession()
    controller = _controller(session)
    baseline = signal.getsignal(signal.SIGINT)

    controller._observe_terminal_task(SimpleNamespace(cancelled=lambda: True))

    assert signal.getsignal(signal.SIGINT) is baseline


def test_idle_ctrl_c_routes_to_the_repl_instead_of_raising(sigint_guard):
    """An idle Ctrl+C must reach the REPL, not unwind through asyncio.run.

    Raising ``KeyboardInterrupt`` here is what skipped the CLI teardown: the
    non-daemon Turn worker was never released, so the interpreter blocked in
    ``threading._shutdown()`` with SIGINT already ignored, and the user could
    only SIGKILL the process.  With a handler installed the idle press is the
    REPL's business -- the same double-press confirm the readline path uses.
    """
    session = _IdleSession()
    seen: list[str] = []

    async def main() -> None:
        install_live_interrupt_handler(
            session, on_idle_interrupt=lambda: seen.append("idle")
        )
        await asyncio.sleep(0.05)
        os.kill(os.getpid(), signal.SIGINT)
        await asyncio.sleep(0.05)

    _run_expecting_routed_interrupt(main())

    assert seen == ["idle"]


def test_idle_ctrl_c_awaits_an_async_repl_handler(sigint_guard):
    """The confirm notice is printed through an awaited terminal handoff."""
    session = _IdleSession()
    done: list[str] = []

    async def handler() -> None:
        await asyncio.sleep(0)
        done.append("notice")

    async def main() -> None:
        install_live_interrupt_handler(session, on_idle_interrupt=handler)
        await asyncio.sleep(0.05)
        os.kill(os.getpid(), signal.SIGINT)
        await asyncio.sleep(0.1)

    _run_expecting_routed_interrupt(main())

    assert done == ["notice"]


def test_idle_ctrl_c_without_a_handler_still_raises(sigint_guard):
    """A caller that installs no idle handler keeps the raising fallback.

    The CLI teardown is now a ``finally``, so the fallback no longer strands a
    live Turn worker, but it is still the only signal available to a caller
    that has nowhere to route the press.
    """
    session = _IdleSession()

    async def main() -> None:
        install_live_interrupt_handler(session)
        await asyncio.sleep(0.05)
        os.kill(os.getpid(), signal.SIGINT)
        await asyncio.sleep(0.05)

    with pytest.raises(KeyboardInterrupt):
        asyncio.run(main())
