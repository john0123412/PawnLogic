"""Deterministic Prompt Toolkit binding tests for live Turn controls."""

from __future__ import annotations

import asyncio
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from pawnlogic.live_repl import (
    build_bottom_toolbar,
    build_prompt_toolkit_bindings,
    requires_modal_terminal,
)


def test_only_interactive_slash_forms_pause_the_persistent_terminal():
    assert requires_modal_terminal("/planguard")
    assert requires_modal_terminal("/model")
    assert not requires_modal_terminal("/queue")
    assert requires_modal_terminal("/provider fetch custom")
    assert not requires_modal_terminal("/help")
    assert not requires_modal_terminal("/planguard status")
    assert not requires_modal_terminal("/queue clear")
    assert not requires_modal_terminal("/skills view 2")


class FakeBindings:
    def __init__(self) -> None:
        self.handlers: dict[tuple[str, ...], object] = {}

    def add(self, *keys: str, **kwargs: object):
        # ``eager`` and other keyword arguments are accepted so the
        # fake mirrors the real ``KeyBindings.add`` signature; the
        # lightweight binding tests only need to dispatch on the
        # key sequence.
        del kwargs

        def register(handler):
            self.handlers[keys] = handler
            return handler

        return register


def _build_bindings(session, *, on_interrupt_settled=None):
    bindings = FakeBindings()
    restore = MagicMock()
    built, state = build_prompt_toolkit_bindings(
        lambda: bindings,
        session=session,
        read_text_cache=lambda _path: "",
        restore_last_input_buffer=restore,
        last_input_path=Path(".last_input"),
        on_interrupt_settled=on_interrupt_settled,
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


def test_escape_while_running_with_queued_work_claims_steer():
    """Regression: live_repl.Esc binding must import ControlAction from
    ``core.turn_scheduler``, not ``core.queue``. The latter module does
    not exist; importing it inside the binding raised ModuleNotFoundError
    on every Escape keypress, which PT then rendered as
    "Press ENTER to continue..." — and the host stdout proxy routed
    that string into the in-Application transcript, scrambling the UI.
    """
    queue_control = MagicMock()

    def queue_status():
        return {"pending_count": 1, "queue_depth": 1}

    session = SimpleNamespace(
        queue_status=queue_status,
        interrupt_active=MagicMock(return_value=True),
        queue_control=queue_control,
    )
    bindings, _state = _build_bindings(session)
    event = SimpleNamespace(
        app=SimpleNamespace(current_buffer=SimpleNamespace()),
    )

    # The binding runs ``schedule_interrupt`` in a background task when
    # ``app.create_background_task`` is present. The local-import error
    # is raised synchronously in the binding body, so the assertion here
    # would fail loudly if the wrong module name regressed.
    bindings.handlers[("escape",)](event)
    queue_control.assert_called_once()
    from core.turn_scheduler import ControlAction, ControlKind  # noqa: F401
    action = queue_control.call_args[0][0]
    assert action.kind is ControlKind.CLAIM_STEER


def test_escape_interrupt_runs_off_ui_thread_and_notifies_after_settle():
    async def scenario() -> None:
        status = {"pending_count": 1}
        settled = asyncio.Event()

        def interrupt() -> bool:
            time.sleep(0.05)
            status["pending_count"] = 0
            return True

        session = SimpleNamespace(
            queue_status=lambda: status,
            interrupt_active=interrupt,
        )
        bindings, _state = _build_bindings(
            session,
            on_interrupt_settled=settled.set,
        )
        app = SimpleNamespace(
            current_buffer=SimpleNamespace(),
            create_background_task=asyncio.create_task,
        )
        bindings.handlers[("escape",)](SimpleNamespace(app=app))

        assert not settled.is_set()
        await asyncio.sleep(0.01)
        assert status["pending_count"] == 1
        await asyncio.sleep(0.1)
        assert status["pending_count"] == 0
        assert settled.is_set()

    asyncio.run(scenario())


def test_escape_waits_for_late_cooperative_settlement_before_recovery_callback():
    async def scenario() -> None:
        status = {"pending_count": 1}
        settled = asyncio.Event()

        session = SimpleNamespace(
            queue_status=lambda: status,
            # A scheduler can accept cancellation but return before a slow
            # provider or Tool reaches its cooperative cancellation point.
            interrupt_active=lambda: True,
        )
        bindings, _state = _build_bindings(
            session,
            on_interrupt_settled=settled.set,
        )
        app = SimpleNamespace(
            current_buffer=SimpleNamespace(),
            create_background_task=asyncio.create_task,
        )
        bindings.handlers[("escape",)](SimpleNamespace(app=app))

        await asyncio.sleep(0.02)
        assert not settled.is_set()
        status["pending_count"] = 0
        await asyncio.wait_for(settled.wait(), timeout=0.5)

    asyncio.run(scenario())


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


def test_enter_queues_follow_up_when_work_exists_but_no_turn_is_active():
    validated = MagicMock()
    session = SimpleNamespace(
        queue_status=lambda: {"pending_count": 0, "queue_depth": 2},
    )
    bindings, state = _build_bindings(session)
    event = SimpleNamespace(
        app=SimpleNamespace(current_buffer=SimpleNamespace()),
        current_buffer=SimpleNamespace(validate_and_handle=validated),
    )

    bindings.handlers[("enter",)](event)

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
    )
    try:
        toolbar = build_bottom_toolbar(
            session,
            {"max_tokens": 8192, "max_iter": 100, "ctx_max_chars": 1000},
            lambda text: text,
        )()

        # 0.3.7: the toolbar no longer surfaces queue counters; the
        # essential fields (model, ctx, tier, tokens) are still
        # rendered, and the running-vs-idle state is now the
        # status-line's job (see tests/test_status_line.py).
        plain = toolbar.replace("<b>", "").replace("</b>", "")
        assert "Model: model" in plain
        assert "Tier: MAX" in plain
        assert "steer:" not in plain
        assert "follow-up:" not in plain
        assert "Failed" not in plain
        assert "Queue:" not in plain
    finally:
        # Always release the worker thread and shut the scheduler
        # down so the test does not leave non-daemon threads
        # alive when an assertion fails (the test runner hangs in
        # ``threading._shutdown`` otherwise).
        release.set()
        scheduler.control(ControlAction(ControlKind.SHUTDOWN))


def _toolbar_session(*, cwd: str = ".") -> SimpleNamespace:
    return SimpleNamespace(
        model_alias="hy3",
        total_prompt_tokens=0,
        total_completion_tokens=0,
        _toolbar_context_chars=0,
        cwd=cwd,
        current_phase="RECON",
        queue_view=lambda: None,
    )


def _toolbar_factory():
    from collections.abc import Mapping

    from pawnlogic.live_repl import build_bottom_toolbar

    cfg: Mapping[str, object] = {
        "max_tokens": 8192,
        "max_iter": 100,
        "ctx_max_chars": 1000,
        "time_budget_sec": 0,
    }
    return build_bottom_toolbar(_toolbar_session(), cfg, lambda text: text)


def test_bottom_toolbar_adapts_to_80_column_live_terminal(monkeypatch):
    """The 80-column PTY owner report: when the live Application reports
    only 80 columns, the toolbar must drop the long directory and phase
    fields so the remaining fields fit inside the visible width.

    A previous cfc86b3 fix introduced a static 100-column hard cap; that
    cap still overflows 80-column terminals because PT clips mid-field
    (the original "follow-u" regression). The cap now follows the live
    terminal's column count instead.
    """
    from prompt_toolkit.data_structures import Size

    class _FakeApp:
        class output:
            @staticmethod
            def get_size() -> Size:
                return Size(rows=24, columns=80)

    monkeypatch.setattr(
        "prompt_toolkit.application.current.get_app", lambda: _FakeApp()
    )
    long_cwd = "/" + "/".join(["segment"] * 10)
    session = _toolbar_session(cwd=long_cwd)
    from collections.abc import Mapping
    from pawnlogic.live_repl import build_bottom_toolbar

    cfg: Mapping[str, object] = {
        "max_tokens": 8192,
        "max_iter": 100,
        "ctx_max_chars": 1000,
        "time_budget_sec": 0,
    }
    toolbar = build_bottom_toolbar(session, cfg, lambda text: text)()
    # Strip the ANSI/HTML tags (the factory above passes through the
    # inner text), then count the visible columns.
    plain = toolbar.replace("<b>", "").replace("</b>", "")
    assert len(plain) <= 80, (
        f"toolbar must fit in 80 columns but was {len(plain)}: {plain!r}"
    )
    # The essential fields must still be visible
    assert "Model: hy3" in plain
    # The long fields are dropped first
    assert "Dir:" not in plain
    assert "Phase:" not in plain
    # 0.3.7: the toolbar no longer surfaces queue state. The
    # status line carries running-vs-idle (see tests/test_status_line.py).
    assert "Queue:" not in plain
    assert "steer:" not in plain
    assert "follow-up:" not in plain


def test_bottom_toolbar_keeps_directory_on_160_column_live_terminal(monkeypatch):
    """Wide terminals (160 columns) keep the full toolbar: model, ctx,
    tier, tokens, phase, dir, time. The Queue segment was removed in
    0.3.7; the status line carries queue state."""
    from prompt_toolkit.data_structures import Size

    class _FakeApp:
        class output:
            @staticmethod
            def get_size() -> Size:
                return Size(rows=24, columns=160)

    monkeypatch.setattr(
        "prompt_toolkit.application.current.get_app", lambda: _FakeApp()
    )
    toolbar = _toolbar_factory()()
    plain = toolbar.replace("<b>", "").replace("</b>", "")
    assert len(plain) <= 160
    assert "Model: hy3" in plain
    assert "Phase: RECON" in plain
    assert "Dir: ." in plain
    assert "Queue:" not in plain


def test_bottom_toolbar_falls_back_to_static_cap_outside_pt_loop():
    """Outside PT's main loop ``get_app()`` raises. The toolbar must
    still produce a sane result that fits the static hard cap so
    tests and pre-loop invocations do not crash.
    """
    toolbar = _toolbar_factory()()
    plain = toolbar.replace("<b>", "").replace("</b>", "")
    # 100-column static cap, minus a 4-column margin
    assert len(plain) <= 100
    assert "Model: hy3" in plain
    assert "Queue:" not in plain


def test_bottom_toolbar_strips_dir_on_120_column_live_terminal(monkeypatch):
    """On a 120-column terminal a typical cwd of 60+ characters still
    overflows; the dir field must be dropped before the queue field is.
    The owner-reported regression was the queue counter being clipped,
    so the test pins the invariant: the queue counter is the LAST thing
    we drop, never the first.
    """
    from prompt_toolkit.data_structures import Size

    class _FakeApp:
        class output:
            @staticmethod
            def get_size() -> Size:
                return Size(rows=24, columns=120)

    monkeypatch.setattr(
        "prompt_toolkit.application.current.get_app", lambda: _FakeApp()
    )
    long_cwd = "/" + "/".join(["segment"] * 10)
    session = _toolbar_session(cwd=long_cwd)
    from collections.abc import Mapping
    from pawnlogic.live_repl import build_bottom_toolbar

    cfg: Mapping[str, object] = {
        "max_tokens": 8192,
        "max_iter": 100,
        "ctx_max_chars": 1000,
        "time_budget_sec": 0,
    }
    toolbar = build_bottom_toolbar(session, cfg, lambda text: text)()
    plain = toolbar.replace("<b>", "").replace("</b>", "")
    assert len(plain) <= 120, f"toolbar {len(plain)} cols: {plain!r}"
    # 0.3.7: no queue segment in the toolbar at all. The status
    # line carries queue state, so the toolbar is purely
    # model / ctx / tier / tokens / phase / dir / time.
    assert "Model: hy3" in plain
    assert "Queue:" not in plain


def test_queue_preview_was_removed_in_0_3_7() -> None:
    """The live composer no longer renders a queue preview above the
    input.  ``build_queue_preview`` is gone from ``pawnlogic.live_repl``;
    the live terminal renders only the status line, the output
    transcript, and the composer itself.
    """
    import pawnlogic.live_repl as live_repl

    assert not hasattr(live_repl, "build_queue_preview"), (
        "build_queue_preview should be removed in 0.3.7; the live "
        "terminal no longer surfaces queued rows above the composer"
    )
