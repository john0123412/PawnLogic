"""Status-line contract: persistent 1-line indicator of Turn state.

The 0.3.7 inline terminal must keep the user informed about what
the worker is doing without depending on a ``print()`` from the
session layer (which the readline path owns, but the live path
does not). This module pins the contract of the new
``live_status`` FormattedTextControl in
``pawnlogic.live_terminal.PersistentTerminal``.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import patch

from prompt_toolkit.data_structures import Size


def _fake_app(columns: int) -> SimpleNamespace:
    class _Output:
        @staticmethod
        def get_size() -> Size:
            return Size(rows=24, columns=columns)

    return SimpleNamespace(output=_Output)


def _session(
    *, pending: int, status: str = "idle", started_at: float | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        model_alias="bai:glm-5.3-flash",
        queue_status=lambda: {"pending_count": pending, "queue_depth": 0},
        _turn_start_time=started_at,
        _last_interrupt_at=None,
        _last_interrupt_kind=None,
        _session_status=status,
    )


def test_status_line_shows_running_with_elapsed_seconds(monkeypatch):
    """While a Turn is in flight the status line must show
    ``[model]  ⏱ Ns · Esc to interrupt`` and the seconds counter
    must advance as wall-clock time passes.

    The previous 0.3.7 contract printed a status line from inside
    ``session.run_turn`` (the readline path).  In the live path the
    print landed in the output area but only at the start of the
    turn, and the user could not tell whether the model was still
    working.  The new contract puts a persistent line at the top
    of the composer that the 250 ms ticker keeps truthful.
    """
    from pawnlogic.live_terminal import PersistentTerminal

    started = time.monotonic() - 12.0
    session = _session(pending=1, started_at=started)
    monkeypatch.setattr(
        "prompt_toolkit.application.current.get_app",
        lambda: _fake_app(columns=120),
    )

    # We construct only the render path to avoid spinning up a real
    # Application. ``PersistentTerminal`` exposes the renderer as a
    # bound method once the app is built, so we call the same
    # callable the layout would invoke.
    terminal = PersistentTerminal.__new__(PersistentTerminal)
    terminal._session = session  # type: ignore[attr-defined]
    terminal._build_status = PersistentTerminal._build_status  # type: ignore[attr-defined]
    rendered = terminal._build_status(terminal)  # type: ignore[arg-type]

    plain = rendered.replace("<b>", "").replace("</b>", "")
    assert "bai:glm-5.3-flash" in plain
    assert "Esc to interrupt" in plain
    # The elapsed counter must be at least 10s (started 12s ago);
    # we allow a small slop for the test runtime.
    import re

    seconds = int(re.search(r"⏱\s*(\d+)s", plain).group(1))
    assert 10 <= seconds <= 20, plain


def test_status_line_recovers_to_idle_after_interrupt(monkeypatch):
    """When the user presses Esc and the Turn settles, the status
    line must briefly read ``⏸ interrupted by user`` for 1.5 s and
    then return to ``Idle``.  The previous 0.3.7 contract left the
    status frozen on whatever the last render saw, so the user had
    to press Esc a second time to confirm cancellation.
    """
    from pawnlogic.live_terminal import PersistentTerminal

    now = time.monotonic()
    session = _session(
        pending=0,
        status="idle",
        started_at=now,
    )
    session._last_interrupt_at = now - 0.5
    session._last_interrupt_kind = "user"
    monkeypatch.setattr(
        "prompt_toolkit.application.current.get_app",
        lambda: _fake_app(columns=120),
    )

    terminal = PersistentTerminal.__new__(PersistentTerminal)
    terminal._session = session  # type: ignore[attr-defined]
    rendered = PersistentTerminal._build_status(terminal)  # type: ignore[arg-type]
    plain = rendered.replace("<b>", "").replace("</b>", "")
    assert "interrupted by user" in plain, plain

    # After 2 s the interrupt marker should be gone and the line
    # should read Idle.
    session._last_interrupt_at = now - 2.0
    rendered = PersistentTerminal._build_status(terminal)  # type: ignore[arg-type]
    plain = rendered.replace("<b>", "").replace("</b>", "")
    assert "Idle" in plain
    assert "interrupted" not in plain


def test_status_line_does_not_show_queue_counters(monkeypatch):
    """The 0.3.7 toolbar displayed ``steer:N · follow-up:N`` and
    ``+N parked`` next to the queue label.  The 0.3.7 patch hides
    all queue counters from the user; the status line must only
    carry model + elapsed + state.
    """
    from pawnlogic.live_terminal import PersistentTerminal

    started = time.monotonic() - 5.0
    session = _session(pending=1, started_at=started)
    monkeypatch.setattr(
        "prompt_toolkit.application.current.get_app",
        lambda: _fake_app(columns=160),
    )

    terminal = PersistentTerminal.__new__(PersistentTerminal)
    terminal._session = session  # type: ignore[attr-defined]
    rendered = PersistentTerminal._build_status(terminal)  # type: ignore[arg-type]
    plain = rendered.replace("<b>", "").replace("</b>", "")
    assert "steer:" not in plain
    assert "follow-up:" not in plain
    assert "parked" not in plain
    assert "+1" not in plain and "+2" not in plain and "+3" not in plain
