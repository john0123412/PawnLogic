"""Contract tests for the inline persistent terminal.

These tests pin down the inline-terminal requirements for 0.3.7:
the persistent terminal must own a single :class:`TerminalTranscript`
that mediates all output (sink, stdout/stderr proxy, and the legacy
``_output_chunks`` buffer must route through it), and the underlying
Prompt Toolkit ``Application`` must be constructed with
``full_screen=False`` and ``mouse_support=False`` so the host terminal
keeps its own scrollback, mouse selection, and copy-paste.

The tests are written against the public ``PersistentTerminal`` API so
they keep working as the implementation is rewritten.
"""

from __future__ import annotations

import pytest

pytest.importorskip("prompt_toolkit")

from pawnlogic import live_terminal
from pawnlogic.live_terminal import PersistentTerminal

# ---------------------------------------------------------------------------
# Transcript wiring
# ---------------------------------------------------------------------------


def test_persistent_terminal_owns_a_transcript() -> None:
    """The persistent terminal must hold a TerminalTranscript instance.

    ADR 0010 says the persistent transcript has a single owner. Until
    the implementation routes through ``TerminalTranscript``, this
    test fails with AttributeError on the missing ``transcript``
    attribute.
    """
    terminal = PersistentTerminal()
    assert hasattr(terminal, "transcript"), (
        "PersistentTerminal must expose a `transcript` attribute holding "
        "the single TerminalTranscript that owns the persistent output"
    )
    transcript = terminal.transcript
    assert transcript is not None, "transcript must not be None"
    # The class must exist and live in the same module the ADR names.
    assert hasattr(
        live_terminal, "TerminalTranscript"
    ), "TerminalTranscript must be importable from pawnlogic.live_terminal"


def test_terminal_sink_writes_route_through_transcript() -> None:
    """TerminalSink.print/write/emit must feed the same transcript."""
    from prompt_toolkit.input import DummyInput
    from prompt_toolkit.output import DummyOutput

    terminal = PersistentTerminal(input=DummyInput(), output=DummyOutput())
    sink = terminal.sink
    sink.print("hello from sink.print")
    sink.write("hello from sink.write")
    transcript = terminal.transcript
    rendered = transcript.snapshot()
    assert "hello from sink.print" in rendered, (
        f"TerminalSink.print must reach the persistent transcript; "
        f"snapshot was {rendered!r}"
    )
    assert "hello from sink.write" in rendered, (
        f"TerminalSink.write must reach the persistent transcript; "
        f"snapshot was {rendered!r}"
    )


def test_stdout_proxy_writes_route_through_transcript() -> None:
    """The stdout/stderr proxy must write to the same transcript."""
    from prompt_toolkit.input import DummyInput
    from prompt_toolkit.output import DummyOutput

    terminal = PersistentTerminal(input=DummyInput(), output=DummyOutput())
    proxy = terminal.install_output_proxy()
    try:
        proxy.write("hello from stdout proxy")
    finally:
        terminal.restore_output_proxy()
    transcript = terminal.transcript
    assert (
        "hello from stdout proxy" in transcript.snapshot()
    ), "stdout/stderr proxy writes must reach the persistent transcript"


def test_transcript_caps_in_memory_buffer() -> None:
    """A transcript that grows past its cap must trim, never grow unbounded."""
    from prompt_toolkit.input import DummyInput
    from prompt_toolkit.output import DummyOutput

    terminal = PersistentTerminal(input=DummyInput(), output=DummyOutput())
    transcript = terminal.transcript
    cap = transcript.max_chars
    chunk = "x" * 1024
    # Push 4x the cap. The buffer must stay bounded.
    for _ in range((cap // len(chunk)) * 4 + 8):
        transcript.append(chunk)
    assert transcript.char_count() <= cap, (
        f"transcript buffer must respect its cap; got "
        f"{transcript.char_count()} > {cap}"
    )


def test_transcript_snapshot_does_not_drop_unflushed_tail() -> None:
    """Pushing more than the cap must keep the latest tail, not arbitrary bytes."""
    from prompt_toolkit.input import DummyInput
    from prompt_toolkit.output import DummyOutput

    terminal = PersistentTerminal(input=DummyInput(), output=DummyOutput())
    transcript = terminal.transcript
    cap = transcript.max_chars
    distinct = "MARKER-" + "A" * (cap // 4) + "-END"
    # Push enough distinct chunks to evict the very first ones.
    for _ in range(8):
        transcript.append(distinct)
    snapshot = transcript.snapshot()
    assert distinct[-64:] in snapshot, (
        f"the most recent tail of the transcript must remain visible; "
        f"snapshot was {snapshot[-200:]!r}..."
    )


# ---------------------------------------------------------------------------
# Application construction
# ---------------------------------------------------------------------------


def test_persistent_terminal_application_uses_inline_screen() -> None:
    """The persistent Application must be constructed full_screen=False.

    The legacy exit-rebuild lifecycle uses full_screen=True, which
    forces the alternate screen buffer and disables native scrollback
    / mouse selection in the host terminal. This test fails until the
    implementation is rewritten to honor ADR 0010.
    """
    from prompt_toolkit.input import DummyInput
    from prompt_toolkit.output import DummyOutput

    terminal = PersistentTerminal(input=DummyInput(), output=DummyOutput())
    application = terminal._build_application_locked()
    assert application.full_screen is False, (
        "Prompt Toolkit Application must use full_screen=False so the "
        "host terminal keeps its own scrollback and selection"
    )


def test_persistent_terminal_application_disables_mouse_tracking_per_adr() -> None:
    """The persistent Application must keep ``mouse_support=False`` (ADR 0010 §2).

    Enabling PT mouse support turns on ``?1003h`` any-motion tracking:
    on WSL/Windows Terminal the flood of motion packets freezes the UI
    and swallows the host's native wheel scrollback — reported by the
    owner as a frozen page with dead keys. With tracking off, the wheel
    scrolls the host terminal's own scrollback; multiplexers that
    re-emit wheel packets as ``Keys.ScrollUp`` / ``Keys.ScrollDown``
    still reach ``scroll_bindings`` because those keys are parsed
    unconditionally.
    """
    from prompt_toolkit.input import DummyInput
    from prompt_toolkit.output import DummyOutput

    terminal = PersistentTerminal(input=DummyInput(), output=DummyOutput())
    application = terminal._build_application_locked()
    is_on = application.mouse_support()
    assert is_on is False, (
        "Prompt Toolkit Application must use mouse_support=False (ADR 0010 §2); "
        f"got mouse_support() = {is_on!r}"
    )
    # The full_screen flag must stay False so the host terminal
    # keeps its own primary screen buffer (native scroll, selection,
    # copy) and PT does not switch into the alternate screen.
    assert application.full_screen is False
