"""Turn feedback contract: reasoning visible in user-friendly mode.

The live terminal's ``Sent`` / ``Thinking`` states are only meaningful if the
user can also see that the model is working.  ``on_reasoning_chunk`` was
gated behind ``_debug_mode()``, so in the default user-friendly mode the
reasoning stream was dropped on the floor: the row said nothing, the
transcript showed nothing, and a long time-to-first-token was
indistinguishable from a dead connection.

These tests drive the real callback pair through
``AgentSession._consume_api_stream_attempt`` with the provider stream faked,
so they cover the seam rather than a reimplementation of it.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from core.turn_api import TurnApiResult


@pytest.fixture
def user_friendly_mode():
    """Pin user-friendly, non-debug mode for the duration of a test."""
    from core.state import state

    previous = (state.user_mode, state.debug_mode)
    state.user_mode = True
    state.debug_mode = False
    try:
        yield
    finally:
        state.user_mode, state.debug_mode = previous


def _plain(text: str) -> str:
    """Strip SGR colour codes so assertions can match the text itself.

    Each streamed chunk is wrapped in its own colour pair, so the payload
    bytes of two adjacent chunks are not contiguous in the raw capture.
    """
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _session_stub() -> object:
    """A session with only the attributes one stream attempt touches."""
    from core.session import AgentSession

    session = AgentSession.__new__(AgentSession)
    session.model_alias = "ds-v4-pro"
    session.session_id = "abcdef123456"
    session.last_turn_api_error = None
    session._turn_first_delta = False
    session._live_terminal_active = True
    session._event_emitter = lambda: SimpleNamespace(  # type: ignore[method-assign]
        content_delta=lambda printable: None
    )
    session._runtime_metrics = SimpleNamespace(  # type: ignore[attr-defined]
        record_provider_retries=lambda count: None
    )
    session._record_turn_usage = lambda usage: None  # type: ignore[method-assign]
    return session


def _renderer_stub() -> object:
    return SimpleNamespace(feed=lambda chunk: chunk, flush=lambda: "")


def _drive(monkeypatch, session, *, reasoning: str, content: str) -> None:
    """Run one stream attempt, replaying the given deltas through the callbacks."""
    from core import session as session_mod

    def fake_consume(request, **kwargs):
        kwargs["on_reasoning"](reasoning)
        kwargs["on_content"](content)
        return TurnApiResult(text=content, reasoning=reasoning)

    monkeypatch.setattr(session_mod, "consume_model_stream", fake_consume)
    monkeypatch.setattr(session_mod, "stream_request", lambda *a, **k: object())

    session._consume_api_stream_attempt(  # type: ignore[attr-defined]
        api_msgs=[],
        current_tools=None,
        current_max_tokens=256,
        renderer=_renderer_stub(),
        iteration=0,
    )


def test_reasoning_reaches_the_transcript_in_user_friendly_mode(
    monkeypatch, capsys, user_friendly_mode
):
    """Regression: reasoning was dropped unless --debug was set.

    The user asked for visible proof that the request landed and the model
    is working.  ``_debug_mode()`` gating made that impossible in the default
    startup mode, which is the only mode most users ever run.
    """
    session = _session_stub()
    _drive(monkeypatch, session, reasoning="let me work through this", content="done")

    out = capsys.readouterr().out
    assert "[thinking]" in out, out
    assert "let me work through this" in out, out


def test_reasoning_never_emits_destructive_control_characters(
    monkeypatch, capsys, user_friendly_mode
):
    """The live transcript gives ``\\r`` and ``\\b`` erase semantics.

    That is exactly why the ``\\r``-framed ``_ThinkingSpinner`` is disabled
    in live mode: a spinner frame or a carriage return here would wipe into
    content the transcript already owns.
    """
    session = _session_stub()
    _drive(monkeypatch, session, reasoning="step one\nstep two", content="answer")

    out = capsys.readouterr().out
    assert "\r" not in out, repr(out)
    assert "\b" not in out, repr(out)


def test_reasoning_prints_its_header_once_across_chunks(
    monkeypatch, capsys, user_friendly_mode
):
    """Streamed reasoning must not repeat the ``[thinking]`` header per chunk."""
    from core import session as session_mod

    def fake_consume(request, **kwargs):
        for piece in ("first ", "second ", "third"):
            kwargs["on_reasoning"](piece)
        kwargs["on_content"]("answer")
        return TurnApiResult(text="answer", reasoning="first second third")

    monkeypatch.setattr(session_mod, "consume_model_stream", fake_consume)
    monkeypatch.setattr(session_mod, "stream_request", lambda *a, **k: object())

    session = _session_stub()
    session._consume_api_stream_attempt(  # type: ignore[attr-defined]
        api_msgs=[],
        current_tools=None,
        current_max_tokens=256,
        renderer=_renderer_stub(),
        iteration=0,
    )

    out = capsys.readouterr().out
    assert out.count("[thinking]") == 1, out
    assert "first second third" in _plain(out), out


def test_first_delta_flag_is_set_by_reasoning_and_by_content(
    monkeypatch, capsys, user_friendly_mode
):
    """Both streams must set the flag the ``Thinking`` state reads.

    Reasoning-only models never emit a content delta before they finish
    thinking, so gating this on content alone would leave the row reading
    ``Sent`` for the entire reasoning phase.
    """

    session = _session_stub()
    assert session._turn_first_delta is False

    _drive(monkeypatch, session, reasoning="thinking...", content="")
    assert session._turn_first_delta is True, "a reasoning delta must count"

    session._turn_first_delta = False
    monkeypatch.undo()
    _drive(monkeypatch, session, reasoning="", content="answer")
    assert session._turn_first_delta is True, "a content delta must count"


def test_admission_stamps_the_submission_time_and_clears_the_flag(monkeypatch):
    """Enter must reset the first-delta flag at admission, not in _prepare_turn.

    ``_prepare_turn`` runs system-prompt resets and may issue a blocking
    summary provider call before it stamps ``_turn_start_time``.  Resetting
    later would leave the toolbar reading the previous Turn's ``Thinking``
    for exactly the window the ``Sent`` state exists to cover.
    """
    import time

    from core.live_turn_control import submit_session_turn
    from core.turn_scheduler import ControlAction, Submission

    submitted: list[Submission] = []

    class _Scheduler:
        def view(self):
            return SimpleNamespace(
                active=None,
                steer=[],
                follow_up=[],
                recovered=None,
                session_status="idle",
            )

        def submit(self, submission):
            submitted.append(submission)

        def control(self, action: ControlAction):
            return SimpleNamespace(accepted=True, affected_ids=[], claimed=None)

    session = SimpleNamespace(
        _turn_scheduler=_Scheduler(),
        _turn_submitted_at=0.0,
        _turn_first_delta=True,  # left over from a previous Turn
    )

    before = time.monotonic()
    submit_session_turn(session, "hello")
    after = time.monotonic()

    assert submitted, "the prompt must actually be admitted"
    assert session._turn_first_delta is False, "the stale flag must be cleared"
    assert before <= session._turn_submitted_at <= after
