"""Regression: the renderer's flush tail must ride the content-delta seam.

The plan renderer holds back trailing fragments that look like an
unfinished tag (the ``<3`` in ``a <3``). Before this fix, the flush
printed the leftover only to stdout, so every event-wire consumer
(``pawn serve``, the ratatui frontend) lost the tail: the headless
server drops stdout while a turn runs, and the ratatui client skips the
final ``result`` because it already saw stream events. The leftover
must therefore be published as one last text delta, not printed.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests.test_session_utils import (
    _PlanRenderer,
    _make_session,
)
from core.turn_api import TurnApiResult


def _wire_deltas_for_answer(session, answer: str) -> list[str]:
    """Mirror the session streaming path: stream the answer through the
    renderer (on_content_chunk semantics), then finalize, collecting
    every text delta a wire subscriber sees."""
    deltas: list[str] = []

    def sink(event):
        if getattr(event.event_type, "value", "") == "text.delta":
            deltas.append(event.payload["text"])

    session.runtime_context.event_publisher.subscribe(sink)
    renderer = _PlanRenderer()
    printable = renderer.feed(answer)
    if printable:
        session._event_emitter().content_delta(printable)
    session._finalize_api_stream_result(
        TurnApiResult(text=answer),
        renderer,
        iteration=0,
    )
    return deltas


def test_flush_tail_reaches_the_event_wire(monkeypatch, capsys):
    import core.session as session_mod

    s = _make_session()
    monkeypatch.setattr(session_mod, "_debug_mode", lambda: False)

    # Feed the streamed prefix through the renderer the way
    # on_content_chunk does, then finalize: the tail `<3` must arrive as
    # one more text delta, not only as a stdout print.
    deltas: list[str] = []

    def sink(event):
        if getattr(event.event_type, "value", "") == "text.delta":
            deltas.append(event.payload["text"])

    s.runtime_context.event_publisher.subscribe(sink)
    renderer = _PlanRenderer()
    printable = renderer.feed("a <3")
    if printable:
        s._event_emitter().content_delta(printable)

    result = TurnApiResult(text="a <3")
    s._finalize_api_stream_result(result, renderer, iteration=0)

    assert "".join(deltas) == "a <3", (
        f"wire saw {deltas!r}; the renderer tail was lost for "
        "event-wire consumers"
    )


def test_plain_answer_unaffected(monkeypatch, capsys):
    import core.session as session_mod

    s = _make_session()
    monkeypatch.setattr(session_mod, "_debug_mode", lambda: False)

    deltas = _wire_deltas_for_answer(s, "hello world")

    assert "".join(deltas) == "hello world"


def test_answer_with_comparison_operators_survives(monkeypatch, capsys):
    import core.session as session_mod

    s = _make_session()
    monkeypatch.setattr(session_mod, "_debug_mode", lambda: False)

    deltas = _wire_deltas_for_answer(s, "count: 1 < 2 but 3 > 2")

    assert "".join(deltas) == "count: 1 < 2 but 3 > 2"


def test_no_duplicate_delta_without_leftover(monkeypatch, capsys):
    """A fully drained renderer must not emit an empty trailing delta."""
    import core.session as session_mod

    s = _make_session()
    monkeypatch.setattr(session_mod, "_debug_mode", lambda: False)

    deltas = _wire_deltas_for_answer(s, "plain")

    assert deltas == ["plain"]
