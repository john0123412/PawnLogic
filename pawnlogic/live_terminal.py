"""Persistent Prompt Toolkit terminal ownership for live turns.

The interactive application in this module has one owner for the terminal:
Prompt Toolkit's application loop.  Producers (model streams, tools, and the
turn worker) only append to a locked output buffer or submit typed events;
they never write directly to ``stdout`` or move the cursor.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import json
import re
import sys
from threading import RLock
from typing import Any, TextIO

from prompt_toolkit.application import Application
from prompt_toolkit.auto_suggest import AutoSuggest
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI, fragment_list_to_text, to_formatted_text
from prompt_toolkit.history import History
from prompt_toolkit.input.base import Input
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.key_binding.key_bindings import KeyBindingsBase
from prompt_toolkit.layout import Dimension, Layout
from prompt_toolkit.layout.containers import (
    ConditionalContainer,
    Float,
    FloatContainer,
    HSplit,
    Window,
)
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.output import Output
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import BaseStyle
from prompt_toolkit.data_structures import Point
from prompt_toolkit.widgets import TextArea

from core.logger import logger
from core.turn_scheduler import SubmissionKind


_ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_KEY_SEQUENCE_TIMEOUT_SECONDS = 0.1


@dataclass(frozen=True, slots=True)
class TerminalSubmission:
    """One accepted composer value and the lane in which it should run."""

    text: str
    kind: SubmissionKind = SubmissionKind.START
    recovery: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("submission text must be a non-empty string")
        if not isinstance(self.kind, SubmissionKind):
            object.__setattr__(self, "kind", SubmissionKind(self.kind))
        if not isinstance(self.recovery, bool):
            raise TypeError("recovery must be a bool")

    @property
    def content(self) -> str:
        """Expose the scheduler's content vocabulary for easy adaptation."""
        return self.text


# The shorter name is convenient for CLI adapters while the explicit name is
# useful when this object is imported alongside core.turn_scheduler.Submission.
Submission = TerminalSubmission


class _OutputControl(FormattedTextControl):
    """Formatted output control with wheel events bound to its viewport."""

    def __init__(
        self,
        terminal: PersistentTerminal,
        text: Any,
        *,
        get_cursor_position: Callable[[], Point],
    ) -> None:
        self._terminal = terminal
        super().__init__(
            text,
            show_cursor=False,
            get_cursor_position=get_cursor_position,
        )

    def mouse_handler(self, mouse_event: MouseEvent) -> Any:
        if mouse_event.event_type is MouseEventType.SCROLL_UP:
            self._terminal.scroll_output(-3)
            return None
        if mouse_event.event_type is MouseEventType.SCROLL_DOWN:
            self._terminal.scroll_output(3)
            return None
        return super().mouse_handler(mouse_event)


class _StdoutProxy:
    """A small stdout-compatible sink that cannot move the terminal cursor."""

    def __init__(self, terminal: PersistentTerminal, previous: TextIO) -> None:
        self._terminal = terminal
        self._previous = previous

    @property
    def encoding(self) -> str:
        return getattr(self._previous, "encoding", None) or "utf-8"

    @property
    def errors(self) -> str:
        return getattr(self._previous, "errors", None) or "strict"

    def write(self, text: str) -> int:
        if text:
            self._terminal.append_output(text)
        return len(text)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        try:
            return bool(self._previous.isatty())
        except Exception:
            return False

    def fileno(self) -> int:
        return self._previous.fileno()

    def writable(self) -> bool:
        return True

    def writelines(self, lines: Any) -> None:
        for line in lines:
            self.write(line)


class TerminalSink:
    """Output-sink adapter that preserves command results across modal TUIs."""

    def __init__(self, terminal: PersistentTerminal) -> None:
        self._terminal = terminal

    def print(self, text: str) -> None:
        self._terminal.append_line(str(text))

    def print_json(self, data: dict[str, Any]) -> None:
        self.print(json.dumps(data, indent=2, ensure_ascii=False))

    def write(self, text: str) -> int:
        self._terminal.append_output(str(text))
        return len(str(text))

    def emit(self, event: Any) -> None:
        event_type = getattr(getattr(event, "event_type", None), "value", None)
        payload = getattr(event, "payload", {})
        if event_type == "text.delta" and isinstance(payload.get("text"), str):
            self.write(payload["text"])
        elif event_type == "error" and isinstance(payload.get("message"), str):
            self.print(payload["message"])


class PersistentTerminal:
    """Own one long-lived Prompt Toolkit application and its terminal state.

    ``run`` keeps the application alive after each accepted input.  A worker
    can call :meth:`append_output` from any thread and can call :meth:`submit`
    when it wants to inject a typed event.  The only code that renders output
    or mutates the live composer is the Prompt Toolkit event-loop callback.
    """

    def __init__(
        self,
        *,
        prompt: str = "▶ You > ",
        toolbar: str | Callable[[], Any] | None = None,
        queue_preview: Callable[[], Any] | None = None,
        initial_text: str = "",
        max_output_chars: int = 2_000_000,
        input: Input | None = None,
        output: Output | None = None,
        key_bindings: KeyBindingsBase | None = None,
        submission_kind: Callable[[], SubmissionKind | None] | None = None,
        completer: Completer | None = None,
        history: History | None = None,
        auto_suggest: AutoSuggest | None = None,
        style: BaseStyle | None = None,
    ) -> None:
        if max_output_chars < 1:
            raise ValueError("max_output_chars must be positive")
        self.prompt = prompt
        self._toolbar = toolbar
        self._queue_preview = queue_preview
        self._default_text = initial_text
        self._draft_is_recovery = False
        self._max_output_chars = max_output_chars
        self._input = input
        self._output = output
        self._key_bindings = key_bindings
        self._submission_kind = submission_kind
        self._completer = completer
        self._history = history
        self._auto_suggest = auto_suggest
        self._style = style
        self._lock = RLock()
        self._stdout_lock = RLock()
        self._output_chunks: deque[str] = deque()
        self._output_chars = 0
        # ``None`` follows the newest output.  An integer is a user-owned
        # viewport offset and must survive redraws and new stream chunks.
        self._output_scroll_offset: int | None = None
        # The cursor and vertical-scroll callbacks must describe the exact
        # formatted-text snapshot returned for the current render.  Reading
        # live output again can race with a streaming producer and point past
        # Prompt Toolkit's cached fragment lines.
        self._rendered_output_line_count = 1
        self._output_window: Window | None = None
        self._submissions: deque[TerminalSubmission] = deque()
        self._submission_event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._application: Application[Any] | None = None
        self._composer: TextArea | None = None
        self._ready_event = asyncio.Event()
        self._stdout_frames: list[
            tuple[TextIO, _StdoutProxy, TextIO, _StdoutProxy]
        ] = []
        self._next_kind = SubmissionKind.START
        self._sink = TerminalSink(self)
        self._invalidation_scheduled = False
        self._running = False
        self._closed = False

    @property
    def application(self) -> Application[Any] | None:
        """Return the underlying application after it has been constructed."""
        return self._application

    @property
    def sink(self) -> TerminalSink:
        """Return the interactive sink owned by this terminal application."""
        return self._sink

    @property
    def composer(self) -> TextArea | None:
        """Return the bottom editable control for CLI-specific integrations."""
        return self._composer

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def is_closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def output_text(self) -> str:
        with self._lock:
            return "".join(self._output_chunks)

    @property
    def draft(self) -> str:
        composer = self._composer
        if composer is not None:
            return composer.buffer.text
        with self._lock:
            return self._default_text

    @property
    def recovery_draft_pending(self) -> bool:
        """Whether the current composer draft replaces recoverable work."""
        with self._lock:
            return bool(self._draft_is_recovery)

    def append_output(self, text: str) -> None:
        """Append a stream chunk without writing to the process TTY."""
        if not text:
            return
        with self._lock:
            if self._closed:
                return
            if len(text) >= self._max_output_chars:
                self._output_chunks.clear()
                text = text[-self._max_output_chars :]
                self._output_chars = 0
            self._append_terminal_text_locked(text)
            while self._output_chars > self._max_output_chars and self._output_chunks:
                removed = self._output_chunks.popleft()
                self._output_chars -= len(removed)
            self._schedule_invalidation_locked()

    def _append_terminal_text_locked(self, text: str) -> None:
        """Apply carriage-return/backspace semantics inside the output pane."""
        text = text.replace("\r\n", "\n")
        for token in re.split(r"([\r\b])", text):
            if not token:
                continue
            if token == "\r":
                current = "".join(self._output_chunks)
                prefix, separator, _line = current.rpartition("\n")
                kept = f"{prefix}{separator}" if separator else ""
                self._output_chunks = deque([kept]) if kept else deque()
                self._output_chars = len(kept)
                continue
            if token == "\b":
                current = "".join(self._output_chunks)
                if current:
                    current = current[:-1]
                    self._output_chunks = deque([current]) if current else deque()
                    self._output_chars = len(current)
                continue
            self._output_chunks.append(token)
            self._output_chars += len(token)

    def append_line(self, text: str) -> None:
        """Append one line while accepting callers that already include newline."""
        self.append_output(text if text.endswith("\n") else f"{text}\n")

    def set_default(self, text: str = "") -> None:
        """Set ordinary editable composer text, even when called by a worker."""
        self._schedule_ui(lambda: self._set_draft_on_ui(text, recovery=False))

    def set_recovery_draft(self, text: str) -> None:
        """Prefill a recovered prompt for edit-and-replace submission."""
        self._schedule_ui(lambda: self._set_draft_on_ui(text, recovery=True))

    def recall(self, text: str) -> None:
        """Recall editable text without submitting or removing any queue entry."""
        self.set_default(text)

    def refresh(self) -> None:
        """Request a redraw after scheduler state changes without output."""
        self._schedule_ui(self._invalidate_on_ui)

    def set_submission_kind(self, kind: SubmissionKind) -> None:
        """Select the lane used by the next plain Enter submission."""
        if not isinstance(kind, SubmissionKind):
            kind = SubmissionKind(kind)
        with self._lock:
            self._next_kind = kind

    def submit(
        self,
        text: str,
        kind: SubmissionKind = SubmissionKind.START,
        *,
        recovery: bool = False,
    ) -> bool:
        """Queue a typed submission; return ``False`` after terminal closure."""
        submission = TerminalSubmission(text, kind, recovery=recovery)
        with self._lock:
            if self._closed:
                return False
            self._submissions.append(submission)
            self._wake_submission_waiter_locked()
        return True

    async def next_submission(self) -> TerminalSubmission | None:
        """Wait for the next accepted event without stopping the application."""
        loop = asyncio.get_running_loop()
        while True:
            with self._lock:
                if self._submissions:
                    return self._submissions.popleft()
                if self._closed:
                    return None
                if self._loop is None:
                    self._loop = loop
                if self._submission_event is None:
                    self._submission_event = asyncio.Event()
                self._submission_event.clear()
                event = self._submission_event
            await event.wait()

    async def wait_until_ready(self) -> None:
        """Wait until Prompt Toolkit has entered its persistent application."""
        await self._ready_event.wait()

    def prepare_run(self) -> None:
        """Reset the readiness handshake before scheduling a new app run."""
        self._ready_event.clear()

    async def run(self) -> None:
        """Run the persistent application until :meth:`close` is called."""
        with self._lock:
            if self._closed:
                return
            if self._running:
                raise RuntimeError("PersistentTerminal.run() is already running")
            self._loop = asyncio.get_running_loop()
            self._ready_event.clear()
            application = self._build_application_locked()
            self._running = True

        def mark_ready() -> None:
            event = self._ready_event
            if event is not None:
                event.set()

        try:
            await application.run_async(pre_run=mark_ready, handle_sigint=False)
        finally:
            with self._lock:
                self._running = False
                if self._closed:
                    self._wake_submission_waiter_locked()

    def run_sync(self) -> None:
        """Run the same application synchronously for non-async adapters."""
        with self._lock:
            if self._closed:
                return
            if self._running:
                raise RuntimeError("PersistentTerminal.run_sync() is already running")
            application = self._build_application_locked()
            self._running = True
        try:
            def mark_ready() -> None:
                with self._lock:
                    self._loop = application.loop
                self._ready_event.set()

            application.run(pre_run=mark_ready, handle_sigint=False)
        finally:
            with self._lock:
                self._running = False
                if self._closed:
                    self._wake_submission_waiter_locked()

    def pause(self) -> None:
        """Temporarily leave the alternate screen for one modal command."""
        with self._lock:
            if self._closed or not self._running:
                return
            application = self._application
            loop = self._loop
        if application is not None:
            self._schedule_on_loop(application.exit, loop=loop)

    def close(self) -> None:
        """Close the application and wake any consumer waiting for input."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._wake_submission_waiter_locked()
            application = self._application
            loop = self._loop
            running = self._running

        if application is None or not running:
            return
        callback = application.exit
        self._schedule_on_loop(callback, loop=loop)

    def install_output_proxy(self) -> _StdoutProxy:
        """Route ordinary stdout/stderr writes into the output buffer."""
        with self._stdout_lock:
            previous_stdout = sys.stdout
            previous_stderr = sys.stderr
            stdout_proxy = _StdoutProxy(self, previous_stdout)
            stderr_proxy = _StdoutProxy(self, previous_stderr)
            self._stdout_frames.append(
                (previous_stdout, stdout_proxy, previous_stderr, stderr_proxy)
            )
            sys.stdout = stdout_proxy
            sys.stderr = stderr_proxy
            return stdout_proxy

    def restore_output_proxy(self) -> None:
        """Restore the exact stdout saved by the most recent installation."""
        with self._stdout_lock:
            if not self._stdout_frames:
                return
            previous_stdout, _stdout_proxy, previous_stderr, _stderr_proxy = (
                self._stdout_frames.pop()
            )
            sys.stdout = previous_stdout
            sys.stderr = previous_stderr

    @contextmanager
    def output_proxy(self) -> Iterator[_StdoutProxy]:
        """Temporarily capture stdout and restore it even on exceptions."""
        proxy = self.install_output_proxy()
        try:
            yield proxy
        finally:
            self.restore_output_proxy()

    def screen_lines(self, *, width: int, height: int) -> tuple[str, ...]:
        """Return a deterministic screen projection used by terminal tests.

        The projection mirrors the application layout: output occupies the
        upper rows, the composer is the penultimate row, and the toolbar is
        always the final row.  Output is clipped from the top so new stream
        chunks remain visible without ever moving the composer.
        """
        width = max(1, width)
        height = max(1, height)
        output_rows = max(0, height - 2)
        output = self._wrapped_output_lines(width)
        visible = output[-output_rows:] if output_rows else []
        padded = [""] * max(0, output_rows - len(visible)) + visible
        composer = self._clip_line(f"{self.prompt}{self.draft}", width)
        toolbar = self._clip_line(self._toolbar_text(), width)
        lines = [*padded, composer, toolbar]
        return tuple(lines[-height:])

    def rendered_screen_lines(self) -> tuple[str, ...]:
        """Return the latest real Prompt Toolkit screen for E2E assertions."""
        application = self._application
        if application is None:
            return ()
        screen = application.renderer.last_rendered_screen
        if screen is None:
            return ()
        width = max(
            (max(row.keys(), default=-1) + 1 for row in screen.data_buffer.values()),
            default=0,
        )
        return tuple(
            "".join(screen.data_buffer[y][x].char for x in range(width)).rstrip()
            for y in range(screen.height)
        )

    def _build_application_locked(self) -> Application[Any]:
        if self._application is not None:
            return self._application
        bindings = self._key_bindings
        if bindings is None:
            bindings = KeyBindings()

            @bindings.add("enter")
            def _accept(event: Any) -> None:
                self.set_submission_kind(self._next_kind)
                event.current_buffer.validate_and_handle()

            @bindings.add("escape", "enter")
            def _follow_up(event: Any) -> None:
                self.set_submission_kind(SubmissionKind.FOLLOW_UP)
                event.current_buffer.validate_and_handle()

        # Some terminals and multiplexers expose wheel events without screen
        # coordinates. Prompt Toolkit's stock binding translates those into
        # Up/Down, which would navigate the focused composer history. Handle
        # them at the terminal owner instead.
        scroll_bindings = KeyBindings()

        @scroll_bindings.add(Keys.ScrollUp)
        def _scroll_up(_event: Any) -> None:
            self.scroll_output(-3)

        @scroll_bindings.add(Keys.ScrollDown)
        def _scroll_down(_event: Any) -> None:
            self.scroll_output(3)

        bindings = merge_key_bindings([bindings, scroll_bindings])

        self._composer = TextArea(
            text=self._default_text,
            multiline=False,
            wrap_lines=False,
            height=Dimension.exact(1),
            prompt=self.prompt,
            accept_handler=self._accept_handler,
            focusable=True,
            completer=self._completer,
            history=self._history,
            auto_suggest=self._auto_suggest,
            complete_while_typing=True,
        )
        # Prompt Toolkit starts a TextArea cursor at position zero even when
        # initial text is supplied.  Recovery and explicit prefilled drafts
        # must behave like an editable prompt, so place the cursor at the end.
        self._composer.buffer.cursor_position = len(self._default_text)
        output_control = _OutputControl(
            self,
            self._render_output,
            get_cursor_position=self._output_cursor_position,
        )
        output_window = Window(
            output_control,
            height=Dimension(weight=1),
            wrap_lines=True,
            allow_scroll_beyond_bottom=True,
            always_hide_cursor=True,
            get_vertical_scroll=self._get_output_vertical_scroll,
        )
        self._output_window = output_window
        toolbar_window = Window(
            FormattedTextControl(self._render_toolbar),
            height=Dimension.exact(1),
        )
        queue_preview = ConditionalContainer(
            Window(
                FormattedTextControl(self._render_queue_preview),
                height=self._queue_preview_height,
                wrap_lines=False,
                always_hide_cursor=True,
            ),
            filter=Condition(self._has_queue_preview),
        )
        body = HSplit(
            [output_window, queue_preview, self._composer.window, toolbar_window]
        )
        root = FloatContainer(
            content=body,
            floats=[
                Float(
                    xcursor=True,
                    ycursor=True,
                    content=CompletionsMenu(max_height=6, scroll_offset=1),
                )
            ],
        )
        self._application = Application(
            layout=Layout(root, focused_element=self._composer),
            key_bindings=bindings,
            full_screen=True,
            erase_when_done=False,
            input=self._input,
            output=self._output,
            style=self._style,
            mouse_support=True,
        )
        # A bare Escape shares its first byte with Alt+Enter, Alt+Up, and
        # terminal navigation sequences. Prompt Toolkit otherwise waits 0.5s
        # to decode the byte and another 1.0s to resolve the binding prefix.
        # Keep a small window for complete escape sequences while making the
        # documented active-Turn interrupt feel immediate.
        self._application.ttimeoutlen = _KEY_SEQUENCE_TIMEOUT_SECONDS
        self._application.timeoutlen = _KEY_SEQUENCE_TIMEOUT_SECONDS
        return self._application

    def _accept_handler(self, buffer: Buffer) -> None:
        text = buffer.text
        resolver = self._submission_kind
        with self._lock:
            kind = resolver() if resolver is not None else self._next_kind
            self._next_kind = SubmissionKind.START
            recovery = self._draft_is_recovery
            self._draft_is_recovery = False
        if kind is None:
            kind = SubmissionKind.START
        if text.strip():
            if kind is SubmissionKind.START:
                if self.output_text and not self.output_text.endswith("\n"):
                    self.append_output("\n")
                self.append_line(f"\x1b[1;32m▶ You >\x1b[0m {text}")
            self.submit(text, kind, recovery=recovery)
        buffer.text = ""
        buffer.cursor_position = 0

    def _render_output(self) -> Any:
        with self._lock:
            text = "".join(self._output_chunks)
            plain_text = _ANSI_ESCAPE.sub("", text)
            self._rendered_output_line_count = len(plain_text.split("\n"))
        return ANSI(text) if "\x1b[" in text else text

    def _render_toolbar(self) -> Any:
        return self._toolbar_text()

    def _render_queue_preview(self) -> Any:
        callback = self._queue_preview
        if callback is None:
            return []
        try:
            return callback() or []
        except Exception:
            return []

    def _queue_preview_text(self) -> str:
        try:
            return fragment_list_to_text(to_formatted_text(self._render_queue_preview()))
        except Exception:
            return ""

    def _has_queue_preview(self) -> bool:
        return bool(self._queue_preview_text())

    def _queue_preview_height(self) -> int:
        text = self._queue_preview_text()
        return min(4, max(1, len(text.splitlines())))

    def _toolbar_text(self) -> str:
        toolbar = self._toolbar
        if callable(toolbar):
            try:
                value = toolbar()
            except Exception:
                return "Ready"
            if value is None:
                return "Ready"
            try:
                return fragment_list_to_text(to_formatted_text(value))
            except Exception:
                return str(value)
        return toolbar or "Ready · steer:0 · follow-up:0"

    def _wrapped_output_lines(self, width: int) -> list[str]:
        text = _ANSI_ESCAPE.sub("", self.output_text)
        if not text:
            return []
        lines: list[str] = []
        for raw_line in text.splitlines() or [""]:
            if not raw_line:
                lines.append("")
                continue
            lines.extend(
                raw_line[index : index + width]
                for index in range(0, len(raw_line), width)
            )
        if text.endswith("\n"):
            lines.append("")
        return lines

    @staticmethod
    def _clip_line(line: str, width: int) -> str:
        return line[:width].ljust(width)

    def _output_line_count(self) -> int:
        """Return the line count used by Prompt Toolkit's output control."""
        text = _ANSI_ESCAPE.sub("", self.output_text)
        if not text:
            return 1
        return len(text.split("\n"))

    def _output_viewport_height(self) -> int:
        window = self._output_window
        info = window.render_info if window is not None else None
        return max(1, info.window_height if info is not None else 1)

    def _get_output_vertical_scroll(self, window: Window) -> int:
        """Return the output offset while preserving a manual scroll position."""
        with self._lock:
            line_count = self._rendered_output_line_count
        viewport_height = max(
            1,
            window.render_info.window_height if window.render_info is not None else 1,
        )
        max_offset = max(0, line_count - viewport_height)
        with self._lock:
            offset = self._output_scroll_offset
        if offset is None:
            return max_offset
        return min(max(0, offset), max_offset)

    def _output_cursor_position(self) -> Point:
        """Anchor the output cursor inside the visible output slice."""
        with self._lock:
            line_count = self._rendered_output_line_count
            offset = self._output_scroll_offset
        if offset is None:
            return Point(x=0, y=max(0, line_count - 1))
        viewport_height = self._output_viewport_height()
        return Point(
            x=0,
            y=min(line_count - 1, max(0, offset + viewport_height - 1)),
        )

    def scroll_output(self, delta: int) -> None:
        """Scroll the output viewport without changing the composer buffer."""
        if not delta:
            return
        line_count = self._output_line_count()
        viewport_height = self._output_viewport_height()
        max_offset = max(0, line_count - viewport_height)
        with self._lock:
            current = (
                max_offset
                if self._output_scroll_offset is None
                else min(max(0, self._output_scroll_offset), max_offset)
            )
            target = min(max(0, current + delta), max_offset)
            # Reaching the tail returns ownership to the live-follow mode.
            self._output_scroll_offset = None if target >= max_offset else target
            window = self._output_window
            if window is not None:
                # ``Window`` only consults get_vertical_scroll for
                # non-wrapping content.  Keep the resolved position in the
                # Window as well so wrapped output remains user-scrollable.
                window.vertical_scroll = target
                window.vertical_scroll_2 = 0
            self._schedule_invalidation_locked()

    def _set_draft_on_ui(self, text: str, *, recovery: bool = False) -> None:
        with self._lock:
            self._default_text = text
            self._draft_is_recovery = recovery
            composer = self._composer
        if composer is None:
            return
        composer.buffer.text = text
        composer.buffer.cursor_position = len(text)
        self._invalidate_on_ui()

    def _schedule_ui(self, callback: Callable[[], None]) -> None:
        with self._lock:
            loop = self._loop
            running = self._running
        if not running or loop is None:
            callback()
            return
        self._schedule_on_loop(callback, loop=loop)

    def _schedule_on_loop(
        self,
        callback: Callable[[], None],
        *,
        loop: asyncio.AbstractEventLoop | None,
    ) -> None:
        if loop is None:
            callback()
            return
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if current is loop:
            callback()
            return
        try:
            loop.call_soon_threadsafe(callback)
        except RuntimeError:
            return

    def _schedule_invalidation_locked(self) -> None:
        loop = self._loop
        if loop is None or self._invalidation_scheduled:
            return
        self._invalidation_scheduled = True
        try:
            loop.call_soon_threadsafe(self._invalidate_on_ui)
        except RuntimeError:
            self._invalidation_scheduled = False

    def _invalidate_on_ui(self) -> None:
        with self._lock:
            self._invalidation_scheduled = False
            application = self._application
        if application is not None:
            try:
                application.invalidate()
            except Exception:
                return

    def _wake_submission_waiter_locked(self) -> None:
        event = self._submission_event
        loop = self._loop
        if event is None:
            return
        if loop is None:
            event.set()
            return
        try:
            loop.call_soon_threadsafe(event.set)
        except RuntimeError:
            return


class PersistentTerminalController:
    """Own the application task, stdout proxy, and modal pause lifecycle."""

    def __init__(
        self,
        terminal: PersistentTerminal,
        session: Any,
        activate_sink: Callable[[Any], None],
        fallback_sink: Any | None = None,
    ) -> None:
        self.terminal = terminal
        self._session = session
        self._activate_sink = activate_sink
        self._fallback_sink = fallback_sink
        self._task: asyncio.Task[None] | None = None
        self._proxy_active = False

    async def start(self) -> None:
        self._session._live_terminal_active = True
        self._activate_sink(self.terminal.sink)
        self.terminal.install_output_proxy()
        self._proxy_active = True
        try:
            self.terminal.prepare_run()
            self._task = asyncio.create_task(self.terminal.run())
            self._task.add_done_callback(self._observe_terminal_task)
            await self.terminal.wait_until_ready()
        except BaseException:
            if self._proxy_active:
                self.terminal.restore_output_proxy()
                self._proxy_active = False
            self._session._live_terminal_active = False
            if self._fallback_sink is not None:
                self._activate_sink(self._fallback_sink)
            raise

    async def pause_for_modal(self, should_pause: bool) -> bool:
        if not should_pause:
            return False
        self._session._live_terminal_active = False
        self.terminal.pause()
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
        if self._proxy_active:
            self.terminal.restore_output_proxy()
            self._proxy_active = False
        return True

    async def resume_after_modal(self, paused: bool) -> None:
        if not paused or self.terminal.is_closed:
            return
        self._session._live_terminal_active = True
        self.terminal.install_output_proxy()
        self._proxy_active = True
        self.terminal.prepare_run()
        self._task = asyncio.create_task(self.terminal.run())
        self._task.add_done_callback(self._observe_terminal_task)
        await self.terminal.wait_until_ready()

    def _observe_terminal_task(self, task: asyncio.Task[None]) -> None:
        """Log an unexpected Prompt Toolkit exit instead of hiding its cause."""
        if task.cancelled():
            return
        try:
            error = task.exception()
        except asyncio.InvalidStateError:
            return
        if error is not None:
            logger.error("Persistent terminal application failed: {!r}", error)
        elif not self.terminal.is_closed and self._session._live_terminal_active:
            logger.warning("Persistent terminal application exited unexpectedly")

    async def close(self) -> None:
        self.terminal.close()
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
        if self._proxy_active:
            self.terminal.restore_output_proxy()
            self._proxy_active = False
        self._session._live_terminal_active = False
        if self._fallback_sink is not None:
            self._activate_sink(self._fallback_sink)


LiveTerminalApp = PersistentTerminal


__all__ = [
    "LiveTerminalApp",
    "PersistentTerminal",
    "PersistentTerminalController",
    "Submission",
    "SubmissionKind",
    "TerminalSink",
    "TerminalSubmission",
]
