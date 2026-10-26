"""Atomic terminal frames for the inline live terminal.

Prompt Toolkit renders an inline application by diffing two screens and
writing the result with one flush, so an ordinary repaint already reaches the
host terminal as a single write.  Moving output into the host's native
scrollback did not: ``run_in_terminal`` erased the block and flushed, switched
the TTY to cooked mode, let the caller write, reset the renderer and flushed,
asked for the cursor position, and only then redrew -- five or six separate
writes, between which the terminal displayed the erased block.  That gap is
the flash the owner saw every time output moved into the scrollback.

This module replaces the handoff with the approach Codex's TUI uses on
Windows Terminal: erase the block, write the history rows, and repaint the
block in ONE write, bracketed by synchronized-update mode (DEC private mode
2026) so terminals that implement it -- recent Windows Terminal, kitty,
WezTerm, iTerm2, foot, Ghostty, Alacritty -- present the frame atomically.
Terminals without mode 2026 ignore the private mode and still receive one
write instead of six.  A full-screen scroll (rather than a DECSTBM scroll
region) moves the old rows into the scrollback, because partial scroll
regions discard rows instead of saving them on Windows Terminal.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from typing import Any, TextIO, cast

from prompt_toolkit.application import Application
from prompt_toolkit.output import Output
from prompt_toolkit.output.color_depth import ColorDepth
from prompt_toolkit.output.defaults import create_output
from prompt_toolkit.output.vt100 import Vt100_Output
from prompt_toolkit.utils import (
    get_bell_environment_variable,
    get_term_environment_variable,
)


BEGIN_SYNCHRONIZED_UPDATE = "\x1b[?2026h"
END_SYNCHRONIZED_UPDATE = "\x1b[?2026l"


class SynchronizedVt100Output(Vt100_Output):
    """Vt100 output that sends every flush as one synchronized-update frame.

    The first byte written after a flush opens the update and the next flush
    closes it, so each write the process makes is a complete frame.
    :meth:`frame` defers flushes, letting several renderer operations -- an
    erase, history rows, and a full repaint -- leave as one write.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._frame_depth = 0
        self._update_open = False

    def _open_update(self) -> None:
        if not self._update_open:
            self._update_open = True
            super().write_raw(BEGIN_SYNCHRONIZED_UPDATE)

    def write_raw(self, data: str) -> None:
        if data:
            self._open_update()
        super().write_raw(data)

    def write(self, data: str) -> None:
        if data:
            self._open_update()
        super().write(data)

    def flush(self) -> None:
        if self._frame_depth:
            return
        if self._update_open:
            self._update_open = False
            super().write_raw(END_SYNCHRONIZED_UPDATE)
        super().flush()

    @contextmanager
    def frame(self) -> Iterator[None]:
        """Hold every flush inside the block and write once when it ends."""
        self._frame_depth += 1
        try:
            yield
        finally:
            self._frame_depth -= 1
            if not self._frame_depth:
                self.flush()


def create_live_output(stdout: TextIO) -> Output:
    """Return the output the live terminal renders through.

    A TTY on a POSIX host gets :class:`SynchronizedVt100Output`, configured
    exactly as Prompt Toolkit's ``create_output`` would configure its plain
    ``Vt100_Output``.  Anything else (a pipe, a file, Windows) keeps Prompt
    Toolkit's own choice.
    """
    try:
        is_tty = bool(stdout.isatty())
    except Exception:
        is_tty = False
    if sys.platform == "win32" or not is_tty:
        return create_output(stdout=stdout)
    return SynchronizedVt100Output.from_pty(
        stdout,
        term=get_term_environment_variable(),
        default_color_depth=ColorDepth.from_env(),
        enable_bell=get_bell_environment_variable(),
    )


def output_frame(output: Output) -> AbstractContextManager[None]:
    """Return a context that turns ``output``'s writes into one frame.

    Outputs without frame support (``DummyOutput`` in tests, a plain
    ``Vt100_Output`` passed by a caller) get a no-op context: the writes
    still happen, only not as one atomic frame.
    """
    frame = getattr(output, "frame", None)
    if callable(frame):
        return cast(AbstractContextManager[None], frame())
    return nullcontext()


def write_history_frame(application: Application[Any], text: str) -> None:
    """Move ``text`` above the live block and repaint the block, atomically.

    ``text`` is pre-wrapped host text: whole rows separated by ``\\n``.
    The renderer erases its block from the block's first row, the rows are
    written where the block was (scrolling the screen, and so the host
    scrollback, once they reach the bottom), and the block is repainted
    below them from a fresh renderer state.  Every flush inside is held by
    :func:`output_frame`, so the terminal receives one write and never
    shows the erased block.  A write failure propagates to the caller.
    """
    output = application.output
    with output_frame(output):
        application.renderer.erase(leave_alternate_screen=False)
        # Raw mode leaves OPOST on, so a bare LF would also return the
        # carriage; CRLF states it instead of relying on the TTY flags, the
        # same way Prompt Toolkit's own renderer moves between rows.
        output.write_raw(text.replace("\n", "\r\n"))
        redraw = getattr(application, "_redraw", None)
        if callable(redraw):
            # Application._redraw renders synchronously into the held
            # buffer; invalidate() would paint in a later loop iteration,
            # after the frame had already been written without the block.
            redraw()
        else:
            application.invalidate()


class FramedApplication(Application[Any]):
    """Application whose resize repaint is one frame instead of three.

    Prompt Toolkit answers SIGWINCH by erasing the block (flush), asking for
    the cursor position (flush), and redrawing (flush); the terminal shows
    the erased block between the first and the last.  Holding the flushes
    makes the resize repaint a single write as well.
    """

    def _on_resize(self) -> None:
        with output_frame(self.output):
            super()._on_resize()
