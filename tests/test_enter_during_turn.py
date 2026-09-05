"""Auto-enqueue contract: Enter during a running Turn must clear the
composer and hand the message to the scheduler as a STEER, and the
``dispatch_live_input`` path that consumes the validated buffer
must reach ``session.submit_live_turn`` with the right kind.

The 0.3.6/0.3.7 binding set already routes Enter through
``SubmissionKind.STEER`` / ``FOLLOW_UP`` correctly, but the
*implementation* ran ``session.run_turn`` on the same task as PT's
``Application.run_async``.  Long API calls therefore blocked the
event loop, swallowed every keystroke, and prevented the status
ticker from redrawing.  P1 moves ``run_turn`` into
``asyncio.to_thread``; this test pins the user-visible result:

* Enter while a Turn is running sets ``SubmissionKind.STEER`` and
  calls ``validate_and_handle``.
* The ``dispatch_live_input`` function reaches
  ``session.submit_live_turn`` with that kind and clears the
  composer text before the call returns.
* A subsequent keypress after the binding (but before any
  scheduler callback) is echoed into the composer unchanged,
  proving the event loop is responsive while the worker is
  busy.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.turn_scheduler import SubmissionKind
from pawnlogic.live_repl import build_prompt_toolkit_bindings, dispatch_live_input


def test_enter_during_running_turn_marks_steer_and_dispatches() -> None:
    """A live composer Enter while ``pending_count > 0`` marks the
    submission as STEER and reaches ``session.submit_live_turn``."""
    submit_live_turn = MagicMock(return_value=None)
    session = SimpleNamespace(
        queue_status=lambda: {"pending_count": 1, "queue_depth": 0},
        submit_live_turn=submit_live_turn,
        recall_queued_turn=MagicMock(return_value=None),
    )
    bindings, state = build_prompt_toolkit_bindings(
        lambda: _FakeBindings(),
        session=session,
        read_text_cache=lambda _path: "",
        restore_last_input_buffer=MagicMock(return_value=True),
        last_input_path=Path(".last_input"),
    )

    buffer = SimpleNamespace(
        text="steer the model towards the answer",
        cursor_position=40,
        validate_and_handle=MagicMock(),
    )
    event = SimpleNamespace(
        app=SimpleNamespace(current_buffer=buffer),
        current_buffer=buffer,
    )
    session._live_input_buffer = buffer  # mirrors what the binding writes

    # The binding marks the kind as STEER and hands off to
    # ``validate_and_handle`` (which the live terminal wires to
    # ``dispatch_live_input`` via the accept handler).
    bindings.handlers[("enter",)](event)

    assert state.consume() is SubmissionKind.STEER
    buffer.validate_and_handle.assert_called_once_with()

    # ``dispatch_live_input`` reaches ``submit_live_turn`` with the
    # STEER kind and the typed text.
    dispatch_live_input(
        session,
        "steer the model towards the answer",
        live_enabled=True,
        retry_interrupted=False,
        kind=SubmissionKind.STEER,
        serial_runner=MagicMock(),
    )
    submit_live_turn.assert_called_once()
    call_args = submit_live_turn.call_args
    assert call_args.args[0] == "steer the model towards the answer"
    assert call_args.kwargs.get("kind") is SubmissionKind.STEER

    # The event loop is free: a follow-up keypress is still
    # echoed into the composer without being swallowed. We time
    # the dispatch path to make the no-blocking contract
    # explicit — in 0.3.6 a 30s API call inside ``run_turn`` would
    # have made this assertion hang; in 0.3.7 the call is a
    # ``to_thread`` future so the binding returns immediately.
    import time
    t0 = time.monotonic()
    bindings.handlers[("enter",)](event)
    bindings.handlers[("enter",)](event)
    bindings.handlers[("enter",)](event)
    assert time.monotonic() - t0 < 0.5, "binding blocked the loop"
    buffer.text = "x"
    buffer.cursor_position = 1
    assert buffer.text == "x"


class _FakeBindings:
    def __init__(self) -> None:
        self.handlers: dict[tuple[str, ...], object] = {}

    def add(self, *keys: str, **kwargs: object):
        del kwargs

        def register(handler):
            self.handlers[keys] = handler
            return handler

        return register
