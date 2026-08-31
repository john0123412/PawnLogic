"""Deterministic Prompt Toolkit binding tests for live Turn controls."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from pawnlogic.live_repl import build_bottom_toolbar, build_prompt_toolkit_bindings


class FakeBindings:
    def __init__(self) -> None:
        self.handlers: dict[tuple[str, ...], object] = {}

    def add(self, *keys: str):
        def register(handler):
            self.handlers[keys] = handler
            return handler

        return register


def _build_bindings(session):
    bindings = FakeBindings()
    restore = MagicMock()
    built, state = build_prompt_toolkit_bindings(
        lambda: bindings,
        session=session,
        read_text_cache=lambda _path: "",
        restore_last_input_buffer=restore,
        last_input_path=Path(".last_input"),
    )
    assert built is bindings
    return bindings, state


def test_active_escape_and_ctrl_c_share_interrupt_control():
    session = SimpleNamespace(
        queue_status=lambda: {"pending_count": 1},
        interrupt_active=MagicMock(return_value=True),
    )
    bindings, _state = _build_bindings(session)
    event = SimpleNamespace(
        app=SimpleNamespace(current_buffer=SimpleNamespace()),
    )

    bindings.handlers[("escape",)](event)
    bindings.handlers[("c-c",)](event)

    assert session.interrupt_active.call_count == 2


def test_idle_ctrl_c_exits_prompt_and_does_not_call_session_control():
    session = SimpleNamespace(
        queue_status=lambda: {"pending_count": 0},
        interrupt_active=MagicMock(),
    )
    bindings, _state = _build_bindings(session)
    app = SimpleNamespace(current_buffer=SimpleNamespace(), exit=MagicMock())

    bindings.handlers[("c-c",)](SimpleNamespace(app=app))

    session.interrupt_active.assert_not_called()
    app.exit.assert_called_once()
    assert isinstance(app.exit.call_args.kwargs["exception"], KeyboardInterrupt)


def test_escape_enter_still_marks_follow_up_while_running():
    validated = MagicMock()
    session = SimpleNamespace(queue_status=lambda: {"pending_count": 1})
    bindings, state = _build_bindings(session)
    event = SimpleNamespace(
        app=SimpleNamespace(current_buffer=SimpleNamespace()),
        current_buffer=SimpleNamespace(validate_and_handle=validated),
    )

    bindings.handlers[("escape", "enter")](event)

    from core.turn_scheduler import SubmissionKind

    assert state.consume() is SubmissionKind.FOLLOW_UP
    validated.assert_called_once_with()


def test_alt_up_recalls_latest_queue_entry_without_removing_it():
    session = SimpleNamespace(
        queue_status=lambda: {"pending_count": 1},
        recall_queued_turn=MagicMock(return_value="latest queued prompt"),
    )
    bindings, _state = _build_bindings(session)
    buffer = SimpleNamespace(text="", cursor_position=0)
    event = SimpleNamespace(
        app=SimpleNamespace(current_buffer=buffer),
        current_buffer=buffer,
    )

    bindings.handlers[("escape", "up")](event)

    session.recall_queued_turn.assert_called_once_with()
    assert buffer.text == "latest queued prompt"
    assert buffer.cursor_position == len(buffer.text)


def test_bottom_toolbar_reports_immutable_queue_snapshot():
    from threading import Event

    from core.turn_scheduler import ControlAction, ControlKind, Submission, TurnScheduler

    started = Event()
    release = Event()

    def execute(_item):
        started.set()
        assert release.wait(timeout=5)

    scheduler = TurnScheduler(execute, background=True, id_prefix="bar")
    scheduler.submit(Submission("active"))
    assert started.wait(timeout=5)
    session = SimpleNamespace(
        model_alias="model",
        total_prompt_tokens=0,
        total_completion_tokens=0,
        _toolbar_context_chars=0,
        cwd=".",
        current_phase="RECON",
        queue_view=scheduler.view,
    )
    toolbar = build_bottom_toolbar(
        session,
        {"max_tokens": 8192, "max_iter": 100, "ctx_max_chars": 1000},
        lambda text: text,
    )()

    assert "Running · steer:0 · follow-up:0" in toolbar
    release.set()
    scheduler.control(ControlAction(ControlKind.SHUTDOWN))
