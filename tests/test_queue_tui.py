"""Deterministic queue TUI rendering and menu-choice tests."""

from __future__ import annotations

import asyncio
from threading import Event
from types import SimpleNamespace

from core.queue_tui import open_queue_tui, queue_rows, render_queue_tui, toolbar_queue_status
from core.turn_scheduler import (
    ControlAction,
    ControlKind,
    Submission,
    TurnScheduler,
)


def _queued_session():
    scheduler = TurnScheduler(lambda _item: None, id_prefix="cmd")
    scheduler.control(
        ControlAction(
            ControlKind.RESTORE,
            restore_state={
                "steer": [{"id": "cmd-steer", "content": "steer"}],
                "follow_up": [{"id": "cmd-follow", "content": "follow"}],
            },
        )
    )
    return SimpleNamespace(
        _turn_scheduler=scheduler,
        queue_view=scheduler.view,
        queue_control=scheduler.control,
        recall_queued_turn=lambda submission_id: next(
            item.content
            for item in (*scheduler.view().steer, *scheduler.view().follow_up)
            if item.submission_id == submission_id
        ),
        _live_turns_enabled=False,
    )


def test_queue_rows_and_toolbar_use_immutable_scheduler_view() -> None:
    scheduler = TurnScheduler(lambda _item: None, id_prefix="tui")
    scheduler.control(
        ControlAction(
            ControlKind.RESTORE,
            restore_state={
                "steer": [{"id": "tui-steer", "sequence": 4, "content": "steer"}],
                "follow_up": [{"id": "tui-follow", "sequence": 5, "content": "follow"}],
                "recovered": {"id": "tui-recover", "sequence": 2, "content": "draft"},
                "session_status": "interrupted",
            },
        )
    )

    view = scheduler.view()
    rows = queue_rows(view)
    assert [row.sequence for row in rows] == [2, 4, 5]
    assert rows[0].short_id == "tui-recover"
    assert toolbar_queue_status(view) == "Recoverable · steer:1 · follow-up:1"
    rendered = render_queue_tui(view)
    assert "Seq" in rendered
    assert "tui-recover" in rendered
    assert "draft" in rendered


def test_active_queue_tui_never_reads_stdin() -> None:
    started = Event()
    release = Event()

    def execute(_item: Submission) -> None:
        started.set()
        assert release.wait(timeout=5)

    scheduler = TurnScheduler(execute, background=True)
    try:
        scheduler.submit(Submission("active"))
        assert started.wait(timeout=5)
        calls: list[str] = []
        result = open_queue_tui(
            scheduler.view(),
            input_fn=lambda prompt: calls.append(prompt) or "q",
        )
        assert calls == []
        assert result.action is None
        assert "queue controls remain available" in result.output
    finally:
        release.set()
        scheduler.control(ControlAction(ControlKind.SHUTDOWN))


def test_idle_queue_tui_supports_short_id_action_and_cancel() -> None:
    scheduler = TurnScheduler(lambda _item: None, id_prefix="menu")
    scheduler.control(
        ControlAction(
            ControlKind.RESTORE,
            restore_state={
                "follow_up": [{"id": "menu-000002", "content": "queued"}],
            },
        )
    )
    action = open_queue_tui(scheduler.view(), input_fn=lambda _prompt: "r menu-0")
    assert action.action is not None
    assert action.action.operation == "recall"
    assert action.action.submission_id == "menu-000002"

    cancelled = open_queue_tui(scheduler.view(), input_fn=lambda _prompt: "q")
    assert cancelled.cancelled
    assert cancelled.action is None


def test_queue_command_removes_and_converts_by_stable_id(capsys) -> None:
    from core.commands import CommandContext
    from core.commands.session import cmd_queue

    session = _queued_session()
    asyncio.run(cmd_queue(CommandContext(
        verb="/queue", arg="steer", arg2="cmd-f", session=session,
    )))
    assert "Converted to steer" in capsys.readouterr().out
    assert session.queue_view().follow_up == ()

    asyncio.run(cmd_queue(CommandContext(
        verb="/queue", arg="remove", arg2="cmd-s", session=session,
    )))
    assert "Removed" in capsys.readouterr().out
    assert [item.submission_id for item in session.queue_view().steer] == ["cmd-follow"]


def test_queue_command_recall_preserves_entry(capsys) -> None:
    from core.commands import CommandContext
    from core.commands.session import cmd_queue

    session = _queued_session()
    asyncio.run(cmd_queue(CommandContext(
        verb="/queue", arg="recall", arg2="cmd-s", session=session,
    )))
    assert "Recalled" in capsys.readouterr().out
    assert len(session.queue_view().steer) == 1
