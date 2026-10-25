"""Atomic history frames: what the host terminal actually receives.

The live terminal used to move output into the host scrollback through
``run_in_terminal``, which reached the terminal as five or six separate
writes with the inline block erased in between -- the flash the owner saw on
every flush.  These tests drive the real ``PersistentTerminal`` through a
``SynchronizedVt100Output`` on a recording TTY double and pin the contract on
the bytes: one write per flush, bracketed by synchronized-update mode, with
the erase and the repaint inside the same write.
"""

from __future__ import annotations

import asyncio
from io import StringIO
import re
import sys

import pytest

pytest.importorskip("prompt_toolkit")

from prompt_toolkit.data_structures import Size
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.layout import Dimension
from prompt_toolkit.layout.containers import Window

from pawnlogic import live_terminal
from pawnlogic.live_terminal import PersistentTerminal, _HeadroomContainer
from pawnlogic.terminal_frames import (
    BEGIN_SYNCHRONIZED_UPDATE,
    END_SYNCHRONIZED_UPDATE,
    SynchronizedVt100Output,
)

_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*\x07)")
_ERASE_DOWN = "\x1b[J"
_PROMPT = "▶ You >"


class _RecordingTTY(StringIO):
    """A TTY double that keeps every write call separately."""

    def __init__(self, *, fail_when: str = "", failures: int = 0) -> None:
        super().__init__()
        self.writes: list[str] = []
        self._fail_when = fail_when
        self._failures = failures

    def isatty(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if self._failures and self._fail_when and self._fail_when in text:
            self._failures -= 1
            raise OSError("transient host write failure")
        self.writes.append(text)
        return super().write(text)


def _output(stream: _RecordingTTY, rows: int = 24) -> SynchronizedVt100Output:
    return SynchronizedVt100Output(
        stream,
        lambda: Size(rows=rows, columns=80),
        term="xterm-256color",
        enable_cpr=False,
    )


def _plain(text: str) -> str:
    return _ESCAPE.sub("", text)


def _history_frames(writes: list[str], needle: str) -> list[str]:
    """Writes that moved ``needle`` into the scrollback.

    A history frame erases the block (``ESC[J``) and then writes the rows;
    an ordinary repaint that shows an undelivered row inside the live
    viewport carries the text without an erase in front of it.
    """
    return [
        write
        for write in writes
        if needle in write
        and _ERASE_DOWN in write
        and write.index(_ERASE_DOWN) < write.index(needle)
    ]


async def _wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(0.01)
    return True


# ---------------------------------------------------------------------------
# SynchronizedVt100Output
# ---------------------------------------------------------------------------


def test_each_flush_is_one_synchronized_write() -> None:
    stream = _RecordingTTY()
    output = _output(stream)

    output.write_raw("\x1b[2Ahello")
    output.flush()
    output.flush()

    assert stream.writes == [
        f"{BEGIN_SYNCHRONIZED_UPDATE}\x1b[2Ahello{END_SYNCHRONIZED_UPDATE}"
    ]


def test_frame_holds_every_nested_flush_until_it_ends() -> None:
    stream = _RecordingTTY()
    output = _output(stream)

    with output.frame():
        output.write_raw("erase")
        output.flush()
        with output.frame():
            output.write_raw("history")
            output.flush()
        output.write_raw("repaint")
        output.flush()
        assert stream.writes == []

    assert stream.writes == [
        f"{BEGIN_SYNCHRONIZED_UPDATE}erasehistoryrepaint{END_SYNCHRONIZED_UPDATE}"
    ]


# ---------------------------------------------------------------------------
# The live terminal's history frames
# ---------------------------------------------------------------------------


async def _start_terminal(stream: _RecordingTTY, **kwargs) -> tuple[PersistentTerminal, asyncio.Task[None], object]:
    pipe_cm = create_pipe_input()
    pipe = pipe_cm.__enter__()
    terminal = PersistentTerminal(input=pipe, output=_output(stream), **kwargs)
    terminal.install_output_proxy()
    run_task = asyncio.create_task(terminal.run())
    await terminal.wait_until_ready()
    return terminal, run_task, pipe_cm


async def _stop_terminal(terminal: PersistentTerminal, run_task: asyncio.Task[None], pipe_cm: object) -> None:
    terminal.close()
    await asyncio.wait_for(run_task, timeout=2.0)
    terminal.restore_output_proxy()
    pipe_cm.__exit__(None, None, None)  # type: ignore[attr-defined]


def test_history_rows_and_the_repaint_leave_as_one_write() -> None:
    """The erase, the history rows, and the repaint share one write.

    A write that erases the block and does not also repaint it is exactly
    the frame the terminal used to display between run_in_terminal's
    flushes.
    """

    async def scenario() -> None:
        stream = _RecordingTTY()
        original_stdout = sys.stdout
        sys.stdout = stream
        try:
            terminal, run_task, pipe_cm = await _start_terminal(stream)
            stream.writes.clear()

            terminal.append_output("first history line\nsecond history line\n")
            assert await _wait_for(
                lambda: any("second history line" in w for w in stream.writes)
            )

            history_writes = _history_frames(stream.writes, "history line")
            assert len(history_writes) == 1, history_writes
            assert [w for w in stream.writes if "history line" in w] == history_writes
            frame = history_writes[0]
            assert frame.startswith(BEGIN_SYNCHRONIZED_UPDATE)
            assert frame.endswith(END_SYNCHRONIZED_UPDATE)
            plain = _plain(frame)
            assert plain.index("first history line") < plain.index(
                "second history line"
            ) < plain.index(_PROMPT), "rows go above the repainted block"
            for write in stream.writes:
                if _ERASE_DOWN in write:
                    assert _PROMPT in _plain(write), (
                        "a write erased the block without repainting it: "
                        f"{write!r}"
                    )

            await _stop_terminal(terminal, run_task, pipe_cm)
            everything = _plain("".join(stream.writes))
            assert everything.count("first history line") == 1
            assert everything.count("second history line") == 1
        finally:
            sys.stdout = original_stdout

    asyncio.run(scenario())


def test_history_frame_never_asks_for_the_cursor_position_or_cooks_the_tty() -> None:
    """The old handoff issued a CPR query and toggled cooked mode per flush."""

    async def scenario() -> None:
        stream = _RecordingTTY()
        original_stdout = sys.stdout
        sys.stdout = stream
        try:
            terminal, run_task, pipe_cm = await _start_terminal(stream)
            application = terminal.application
            assert application is not None
            entered: list[bool] = []
            original_cooked = application.input.cooked_mode

            def recording_cooked_mode():
                entered.append(True)
                return original_cooked()

            application.input.cooked_mode = recording_cooked_mode  # type: ignore[method-assign]
            stream.writes.clear()

            for index in range(5):
                terminal.append_output(f"streamed row {index}\n")
                await asyncio.sleep(0.15)
            assert await _wait_for(
                lambda: any("streamed row 4" in w for w in stream.writes)
            )

            assert entered == []
            assert not any("\x1b[6n" in w for w in stream.writes)
            await _stop_terminal(terminal, run_task, pipe_cm)
        finally:
            sys.stdout = original_stdout

    asyncio.run(scenario())


def test_failed_history_frame_restores_the_cursor_and_retries_once() -> None:
    """A frame the host rejects must neither lose nor duplicate its rows.

    The rejected frame never reached the terminal, so the delivery cursor
    goes back: the row is undelivered again (the live viewport may show it)
    and exactly one later frame moves it into the scrollback.
    """

    async def scenario() -> None:
        stream = _RecordingTTY(fail_when="fragile row", failures=1)
        original_stdout = sys.stdout
        sys.stdout = stream
        try:
            terminal, run_task, pipe_cm = await _start_terminal(stream)

            terminal.append_output("fragile row\n")
            assert await _wait_for(
                lambda: any("fragile row" in w for w in stream.writes)
            )
            await _stop_terminal(terminal, run_task, pipe_cm)

            assert len(_history_frames(stream.writes, "fragile row")) == 1
            assert terminal.transcript.pending_host_flush(include_partial=True)[0] == ""
        finally:
            sys.stdout = original_stdout

    asyncio.run(scenario())


def test_history_frame_keeps_the_composer_on_its_row() -> None:
    """Rows written above the block come off its top, not off its bottom.

    Prompt Toolkit never shrinks an inline block between renders, so a
    closed preview leaves the block taller than its content.  The frame's
    repaint starts from a reset renderer; without a floor it would collapse
    to its content height and pull the composer up by the slack.
    """

    async def scenario() -> None:
        preview: list[tuple[str, str]] = [
            ("class:queue-preview", "  queued one\n"),
            ("class:queue-preview", "  queued two\n"),
            ("class:queue-preview", "  queued three"),
        ]
        stream = _RecordingTTY()
        original_stdout = sys.stdout
        sys.stdout = stream
        try:
            terminal, run_task, pipe_cm = await _start_terminal(
                stream, queue_preview=lambda: list(preview)
            )
            application = terminal.application
            assert application is not None
            terminal.refresh()
            await asyncio.sleep(0.1)
            preview.clear()
            terminal.refresh()
            await asyncio.sleep(0.1)
            screen = application.renderer.last_rendered_screen
            assert screen is not None
            block_rows = screen.height
            content_rows = application.layout.container.preferred_height(
                80, 24
            ).preferred
            assert block_rows > content_rows + 1, "test precondition: slack rows"

            terminal.append_output("one history row\n")
            assert await _wait_for(
                lambda: any("one history row" in w for w in stream.writes)
            )
            repainted = application.renderer.last_rendered_screen
            assert repainted is not None
            assert repainted.height == block_rows - 1

            await _stop_terminal(terminal, run_task, pipe_cm)
        finally:
            sys.stdout = original_stdout

    asyncio.run(scenario())


def test_live_viewport_reopens_a_color_span_begun_in_delivered_text(monkeypatch) -> None:
    """The undelivered half of a dim span must still render dim."""
    monkeypatch.setattr(live_terminal, "_HOST_FLUSH_MIN_INTERVAL_SECONDS", 0.05)

    async def scenario() -> None:
        stream = _RecordingTTY()
        original_stdout = sys.stdout
        sys.stdout = stream
        try:
            terminal, run_task, pipe_cm = await _start_terminal(stream)

            terminal.append_output("\x1b[2mfirst dim row\nstill dim")
            assert await _wait_for(
                lambda: any("first dim row" in w for w in stream.writes)
            )
            rendered = terminal._render_output()
            value = getattr(rendered, "value", rendered)
            assert value.startswith("\x1b[2m"), value
            assert "still dim" in value

            await _stop_terminal(terminal, run_task, pipe_cm)
        finally:
            sys.stdout = original_stdout

    asyncio.run(scenario())


def test_headroom_floor_raises_preferred_height_within_the_ceiling() -> None:
    floor = [0]
    container = _HeadroomContainer(
        lambda: Window(height=Dimension(min=1, max=3, preferred=2)),
        floor=lambda: floor[0],
    )

    assert container.preferred_height(80, 24).preferred == 2
    floor[0] = 9
    assert container.preferred_height(80, 24).preferred == 9
    floor[0] = 40
    assert container.preferred_height(80, 24).preferred == 23
