"""Persistent Prompt Toolkit terminal ownership for live turns.

The interactive application in this module has one owner for the terminal:
Prompt Toolkit's application loop.  Producers (model streams, tools, and the
turn worker) only append to a :class:`TerminalTranscript` or submit typed
events;
they never write directly to ``stdout`` or move the cursor.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Iterator
import contextlib
from dataclasses import dataclass
import inspect
import json
import re
import sys
from threading import RLock
import time
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

from .terminal_transcript import TerminalTranscript
from .selectors import SelectorRegistry, SelectorState, style_dict as _selector_style_dict
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
from prompt_toolkit.styles import BaseStyle, Style, merge_styles
from prompt_toolkit.data_structures import Point
from prompt_toolkit.widgets import TextArea

from core.logger import logger
from core.turn_scheduler import SubmissionKind


_ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_KEY_SEQUENCE_TIMEOUT_SECONDS = 0.1
# Only the trailing lines of the transcript are rendered in the live
# viewport. The full transcript still exists for scrollback flushing;
# this cap keeps render cost constant for very large sessions.
_RENDER_TAIL_LINES = 1000
# Upper bound on invalidation scheduling rate (frames per second) so a
# streaming producer cannot starve the key-processing loop.
_MAX_RENDER_FPS = 30


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
    """Formatted output control with wheel events bound to its viewport.

    Renders the live transcript by default; switches to the active
    selector's formatted text when a selector is registered.  Using
    a single control guarantees only one output region is visible at
    a time, which prevents the stacked-pane scramble that happens
    when two ``ConditionalContainer``s share a body slot.
    """

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
        # When a selector is active, the wheel events must not steal
        # scroll from the selector viewport; let the default handler
        # deliver them to PT's own scroll machinery.
        if self._terminal._selector_registry.has_active:
            return super().mouse_handler(mouse_event)
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
        live_status: Callable[[], str] | None = None,
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
        self._live_status = live_status
        self._default_text = initial_text
        self._draft_is_recovery = False
        # Wall-clock time of the most recent recovery prefill.  Used by
        # the status line to show a 1.5 s "edit the draft and press Enter"
        # banner without making it permanent.
        self._last_recovery_at: float | None = None
        # The 250 ms status ticker re-asks the live_status callable so the
        # user always sees a truthful "Running" / "Idle" / "⏸ interrupted by
        # user" line while the worker thread is busy.  ``_status_ticker`` is
        # scheduled in :meth:`prepare_run` and cancelled in :meth:`close`.
        self._status_ticker: asyncio.TimerHandle | None = None
        self._max_output_chars = max_output_chars
        self._input = input
        self._output = output
        self._key_bindings = key_bindings
        self._submission_kind = submission_kind
        self._completer = completer
        self._history = history
        self._auto_suggest = auto_suggest
        self._style = style
        # The session is supplied after construction by the owner (the CLI
        # builds the terminal first, then attaches the session so the
        # status line and the queue callback can read scheduler state).
        # ``None`` means no session is bound yet (e.g. unit tests that only
        # exercise rendering primitives).
        self._session: Any | None = None
        self._lock = RLock()
        self._stdout_lock = RLock()
        # The persistent transcript has a single owner: a TerminalTranscript
        # instance. All writers (TerminalSink, the stdout/stderr proxy, the
        # legacy append_output path) must route through it. See ADR 0010.
        self._transcript = TerminalTranscript(max_chars=max_output_chars)
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
        # (transcript version, rendered fragments) cache for _render_output.
        self._render_cache: tuple[int, Any] | None = None
        # Monotonic timestamp of the last scheduled invalidation, for FPS
        # throttling of streaming producers.
        self._last_invalidation_ts = 0.0
        # Pending trailing-edge throttle timer, so the final chunk of a
        # burst is always repainted.
        self._throttle_timer_handle: Any = None
        self._running = False
        self._closed = False
        self._modal_active = False
        self._modal_stack: list[Any] = []
        # In-Application selector registry (ADR 0010). The live
        # ``Application`` consults ``selector_registry`` to decide
        # whether the selector Float is visible and which key
        # bindings should dispatch to it. See ``pawnlogic/selectors.py``.
        self._selector_registry = SelectorRegistry()

    @property
    def application(self) -> Application[Any] | None:
        """Return the underlying application after it has been constructed."""
        return self._application

    @property
    def selector_registry(self) -> SelectorRegistry:
        """Return the in-Application selector registry.

        The registry is a thin per-session object that owns the
        currently-active selector state machine.  The live
        ``Application``'s key bindings consult
        ``selector_registry.has_active`` to decide whether to
        dispatch to the selector; the Float that renders the
        selector reads its formatted text from
        ``selector_registry.formatted_text()``.
        """
        return self._selector_registry

    def open_selector(self, selector: SelectorState) -> asyncio.Future[Any]:
        """Install ``selector`` as the active modal and return its future.

        The future is resolved when ``close_selector()`` is called
        (typically by the controller when the selector state
        machine has captured a result) or when the live terminal
        shuts down.  The selector Float becomes visible immediately
        and the main ``Application`` is invalidated so the new
        state is rendered on the next redraw.
        """
        loop = self._loop
        if loop is None:
            loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._selector_registry.install_active(selector, future)
        self._modal_active = True
        # Re-render and redraw so the selector Float appears and the
        # current selection is highlighted.
        self._schedule_invalidation_locked()
        return future

    def close_selector(self, result: Any = None) -> bool:
        """Resolve the active selector's future with ``result``.

        Returns True when a selector was active and resolved, False
        otherwise.  The Float disappears and the main
        ``Application`` is invalidated so the next redraw removes
        the overlay.
        """
        resolved = self._selector_registry.resolve(result)
        if resolved:
            self._modal_active = self._selector_registry.has_active
            self._schedule_invalidation_locked()
        return resolved

    def _selector_formatted_text(self) -> Any:
        """Return the FormattedText for the active selector Float.

        Reads through the registry so the live ``Application`` and
        any tests can both observe the same content.
        """
        return self._selector_registry.formatted_text()

    @property
    def transcript(self) -> TerminalTranscript:
        """Return the single TerminalTranscript that owns the persistent output."""
        return self._transcript

    def set_queue_preview(self, queue_preview: Callable[[], Any] | None) -> None:
        """Replace the queue preview callback after construction."""
        with self._lock:
            self._queue_preview = queue_preview
            self._schedule_invalidation_locked()

    def set_toolbar(self, toolbar: str | Callable[[], Any] | None) -> None:
        """Replace the toolbar source after construction."""
        with self._lock:
            self._toolbar = toolbar
            self._schedule_invalidation_locked()

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
        return self._transcript.snapshot()

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
            self._append_terminal_text_locked(text)
            self._schedule_invalidation_locked()

    def _append_terminal_text_locked(self, text: str) -> None:
        """Apply carriage-return/backspace semantics inside the output pane.

        The buffer that backs the persistent transcript is the transcript's
        own bounded deque. We still need CR/BS semantics so live output
        can overwrite the last line (spinners, progress bars). The
        transcript takes care of cap enforcement after the rewrite.
        """
        text = text.replace("\r\n", "\n")
        transcript = self._transcript
        for token in re.split(r"([\r\b])", text):
            if not token:
                continue
            if token == "\r":
                current = transcript.snapshot()
                prefix, separator, _line = current.rpartition("\n")
                kept = f"{prefix}{separator}" if separator else ""
                self._replace_transcript_locked(kept)
                continue
            if token == "\b":
                current = transcript.snapshot()
                if current:
                    self._replace_transcript_locked(current[:-1])
                continue
            transcript.append(token)

    def _replace_transcript_locked(self, text: str) -> None:
        """Replace the entire transcript content. Caller must hold the lock."""
        self._transcript.replace(text)

    def append_line(self, text: str) -> None:
        """Append one line while accepting callers that already include newline."""
        self.append_output(text if text.endswith("\n") else f"{text}\n")

    def set_default(self, text: str = "") -> None:
        """Set ordinary editable composer text, even when called by a worker."""
        self._schedule_ui(lambda: self._set_draft_on_ui(text, recovery=False))

    def set_recovery_draft(self, text: str) -> None:
        """Prefill a recovered prompt for edit-and-replace submission."""
        self._last_recovery_at = time.monotonic()
        self._schedule_ui(lambda: self._set_draft_on_ui(text, recovery=True))

    def recall(self, text: str) -> None:
        """Recall editable text without submitting or removing any queue entry."""
        self.set_default(text)

    def set_session(self, session: Any) -> None:
        """Bind a session so the status line can read scheduler state.

        The CLI builds the terminal first and then attaches the session
        after wiring the controller.  This split keeps the live terminal
        decoupled from the session lifecycle: tests that only exercise
        the rendering primitives never need a real session, and the live
        owner never needs to know about scheduler internals.
        """
        with self._lock:
            self._session = session

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

    def _start_status_ticker(self) -> None:
        """Schedule a 250 ms timer that re-asks ``live_status`` while live.

        The ticker only redraws the persistent status line; the rest of the
        layout updates naturally when transcripts change.  We schedule on
        the asyncio loop PT already owns so the render lands on the UI
        thread (the live_status callable itself is allowed to read
        session state from any thread because the session surfaces are
        either thread-local copies or guarded by locks).
        """
        with self._lock:
            if self._status_ticker is not None or self._closed:
                return
            loop = self._loop
        if loop is None or loop.is_closed():
            return

        def _tick() -> None:
            with self._lock:
                self._status_ticker = None
                if self._closed:
                    return
            try:
                self._schedule_ui(self._invalidate_on_ui)
            finally:
                self._start_status_ticker()

        with self._lock:
            self._status_ticker = loop.call_later(0.25, _tick)

    def _stop_status_ticker(self) -> None:
        """Cancel the 250 ms status ticker (no-op if not started)."""
        with self._lock:
            handle = self._status_ticker
            self._status_ticker = None
        if handle is not None:
            with contextlib.suppress(Exception):
                handle.cancel()

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
            self._start_status_ticker()

        try:
            await application.run_async(pre_run=mark_ready, handle_sigint=False)
        finally:
            self._stop_status_ticker()
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
                self._start_status_ticker()

            application.run(pre_run=mark_ready, handle_sigint=False)
        finally:
            self._stop_status_ticker()
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
        self._flush_scrollback_to_stdout()
        self._stop_status_ticker()
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

    def _flush_scrollback_to_stdout(self) -> None:
        """Flush full transcript to original stdout for terminal scrollback.

        Writes the plain-text conversation to the host terminal's scrollback
        buffer so the user can scroll up with the mouse wheel to review past
        output after the application exits. This runs only when the
        application is closing, so it never conflicts with PT's VT100
        cursor positioning.
        """
        text = self._transcript.snapshot()
        if not text:
            return
        plain = _ANSI_ESCAPE.sub("", text)
        if not plain:
            return
        with self._stdout_lock:
            original_stdout = self._stdout_frames[0][0] if self._stdout_frames else None
        if original_stdout is None:
            return
        try:
            original_stdout.write(plain)
            if not plain.endswith("\n"):
                original_stdout.write("\n")
            flush = getattr(original_stdout, "flush", None)
            if callable(flush):
                flush()
        except Exception:
            pass

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

    @contextlib.contextmanager
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

        # Selector key dispatch: when a selector is active the main
        # ``Application`` forwards the key to the active state
        # machine.  We register specific keys (``enter``, ``escape``,
        # ``c-c``, ``up``, ``down``, ``1``-``9``) rather than
        # ``Keys.Any`` because the composer's stock text-insert
        # binding also uses ``Keys.Any`` with ``eager=True``; if two
        # ``Keys.Any`` handlers are registered, the one registered
        # first wins and there is no way to install our handler
        # before the composer's.  Specific keys have unique
        # priorities and run *before* the (read-only) composer
        # absorbs the event.
        for _k in ("enter", "c-j", "c-m"):
            @bindings.add(_k, filter=Condition(lambda: self._selector_registry.has_active), eager=True)
            def _sel_enter(event: Any, _key: str = _k) -> None:
                self._selector_dispatch_key("enter")

        @bindings.add("escape", filter=Condition(lambda: self._selector_registry.has_active), eager=True)
        def _sel_escape(event: Any) -> None:
            self._selector_dispatch_key("escape")

        @bindings.add("c-c", filter=Condition(lambda: self._selector_registry.has_active), eager=True)
        def _sel_c_c(event: Any) -> None:
            self._selector_dispatch_key("c-c")

        @bindings.add("up", filter=Condition(lambda: self._selector_registry.has_active), eager=True)
        def _sel_up(event: Any) -> None:
            self._selector_dispatch_key("up")

        @bindings.add("down", filter=Condition(lambda: self._selector_registry.has_active), eager=True)
        def _sel_down(event: Any) -> None:
            self._selector_dispatch_key("down")

        for _d in range(1, 10):
            @bindings.add(str(_d), filter=Condition(lambda: self._selector_registry.has_active), eager=True)
            def _sel_digit(event: Any, _digit: int = _d) -> None:
                self._selector_dispatch_key(str(_digit))

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
            # ``multiline=True`` is required so the TextArea grows beyond
            # one row for wrapped, long input.  ``multiline=False`` forces
            # the buffer to a single row and ``wrap_lines=True`` has no
            # visible effect, so long input would be clipped, not wrapped.
            # The eager ``enter`` binding registered by
            # ``live_repl.build_prompt_toolkit_bindings`` still submits
            # the buffer; ``c-j`` (Prompt Toolkit's built-in multiline
            # newline key) inserts a literal newline.
            multiline=True,
            wrap_lines=True,
            # The composer grows on demand, bounded by ``max=5`` to keep
            # it from eating the entire output pane.  ``min=1`` keeps
            # the empty composer at a single row.  Do NOT add
            # ``weight=0``: with ``multiline=True``, a wrapped draft
            # raises the TextArea's preferred height while zero weight
            # excludes it from the growth rotation, and PT 3.0.52's
            # ``take_using_weights`` then loops forever — measured as
            # the "page freezes on long input, arrow keys dead" hang.
            # ``dont_extend_height=True`` instead keeps the weighted
            # composer from being inflated to ``max`` when empty: it
            # renders exactly its preferred (content) height.
            height=Dimension(min=1, max=5),
            dont_extend_height=True,
            prompt=self.prompt,
            accept_handler=self._accept_handler,
            focusable=True,
            completer=self._completer,
            history=self._history,
            auto_suggest=self._auto_suggest,
            complete_while_typing=True,
            read_only=Condition(lambda: self._selector_registry.has_active),
        )
        # Prompt Toolkit starts a TextArea cursor at position zero even when
        # initial text is supplied.  Recovery and explicit prefilled drafts
        # must behave like an editable prompt, so place the cursor at the end.
        self._composer.buffer.cursor_position = len(self._default_text)
        output_control = _OutputControl(
            self,
            self._output_or_selector_text,
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
        # Persistent 1-line status indicator (Idle / Running / interrupted).
        # The window only takes a row when a ``live_status`` callable was
        # supplied (e.g. via the inline terminal owner), so the readline
        # fallback (which supplies nothing) keeps the same compact layout
        # as 0.3.6.
        status_window = ConditionalContainer(
            Window(
                FormattedTextControl(self._render_status),
                height=Dimension.exact(1),
                wrap_lines=False,
                always_hide_cursor=True,
            ),
            filter=Condition(lambda: self._live_status is not None),
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
        # The active selector's formatted text replaces the live
        # transcript inside the SAME output window via a switching
        # ``text`` callable.  Using one window (instead of two
        # ``ConditionalContainer``s sharing a body slot) means only
        # one output region is ever visible at a time, which avoids
        # the "two output panes stacked" scramble on small terminals
        # and guarantees the selector sees the full body height.
        body = HSplit(
            [status_window, output_window, queue_preview, self._composer.window, toolbar_window]
        )
        root = FloatContainer(
            content=body,
            floats=[
                Float(
                    xcursor=True,
                    ycursor=True,
                    content=CompletionsMenu(max_height=6, scroll_offset=1),
                ),
            ],
        )
        self._application = Application(
            layout=Layout(root, focused_element=self._composer),
            key_bindings=bindings,
            full_screen=False,
            erase_when_done=False,
            input=self._input,
            output=self._output,
            style=merge_styles(
                [
                    Style.from_dict(_selector_style_dict()),
                    self._style,
                ]
                if self._style is not None
                else [Style.from_dict(_selector_style_dict())]
            ),
            # ADR 0010 §2: the live composer must not enable PT
            # mouse-tracking modes. ``?1003h`` (any-motion tracking) makes
            # WSL/Windows Terminal flood the input queue with motion
            # events and swallows the host's native wheel scrollback,
            # which the owner reported as a frozen page. The wheel scrolls
            # the host terminal's own scrollback instead; in-viewport
            # wheel packets that a multiplexer re-emits as ``Keys.ScrollUp``
            # / ``Keys.ScrollDown`` still reach ``scroll_bindings``.
            mouse_support=False,
        )
        # A bare Escape shares its first byte with Alt+Enter, Alt+Up, and
        # terminal navigation sequences. Prompt Toolkit otherwise waits 0.5s
        # to decode the byte and another 1.0s to resolve the binding prefix.
        # Keep a small window for complete escape sequences while making the
        # documented active-Turn interrupt feel immediate.
        self._application.ttimeoutlen = _KEY_SEQUENCE_TIMEOUT_SECONDS
        self._application.timeoutlen = _KEY_SEQUENCE_TIMEOUT_SECONDS
        return self._application

    def _selector_dispatch_key(self, key_name: str) -> None:
        """Forward a key to the active selector state machine.

        Bound to the selector FormattedTextControl so the focused
        element's key handlers run before the (read-only) composer
        absorbs the event.  Closes the selector when the state
        machine reports itself closed, and moves focus back to the
        composer.
        """
        selector = self._selector_registry.active_selector
        if selector is None:
            return
        if selector.handle_key(key_name):
            self._schedule_invalidation_locked()
        if selector.is_closed:
            self._selector_registry.resolve(selector.result)
            self._modal_active = self._selector_registry.has_active
            self._schedule_invalidation_locked()

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
        """Render the transcript tail, cached per transcript version.

        Measured on the owner's real session scale (6,000 lines /
        250KB transcript), a full-transcript re-render costs ~50ms per
        frame; streaming chunks invalidated at that rate froze the UI
        and queued key presses behind renders (reported as "page
        frozen, arrow keys dead"). Two mitigations:

        - Only the trailing :data:`_RENDER_TAIL_LINES` lines are ever
          rendered. The output viewport follows the tail anyway, and
          the full transcript is still flushed to the host scrollback
          on close, so nothing the user can see is lost.
        - The rendered value (and its line count) are cached against
          the transcript's monotonic ``version()``; redraws that do
          not change the transcript (focus changes, toolbar ticks,
          queue updates) reuse the cached fragments instead of
          re-parsing 250KB of ANSI text.
        """
        version = self._transcript.version()
        cached = self._render_cache
        if cached is not None and cached[0] == version:
            return cached[1]
        text = self._transcript.tail(_RENDER_TAIL_LINES)
        plain_text = _ANSI_ESCAPE.sub("", text)
        self._rendered_output_line_count = len(plain_text.split("\n"))
        rendered: Any = ANSI(text) if "\x1b[" in text else text
        self._render_cache = (version, rendered)
        return rendered

    def _output_or_selector_text(self) -> Any:
        """Return transcript text or the active selector's text.

        Keeping both content sources in a single ``FormattedTextControl``
        means the body HSplit only contains one output ``Window``;
        switching at render time avoids stacking the transcript and
        the selector in the same vertical slot, which previously
        scrambled the page on small terminals.
        """
        if self._selector_registry.has_active:
            return self._selector_registry.formatted_text()
        return self._render_output()

    def _render_toolbar(self) -> Any:
        return self._toolbar_text()

    def _render_status(self) -> Any:
        callback = self._live_status
        if callback is None:
            return []
        try:
            text = callback() or ""
        except Exception:
            return []
        if not text:
            return []
        # The status window is always exactly one row.  Keep the line
        # within the live terminal's visible width; on PT exception or
        # before the layout knows its size, fall back to a 120-column
        # budget so the test surface still sees a sane string.
        try:
            from prompt_toolkit.application.current import get_app

            columns = get_app().output.get_size().columns
        except Exception:
            columns = 120
        return self._clip_line(str(text), max(20, int(columns) - 1))

    def _build_status(self) -> str:
        """Return the persistent one-line status text (HTML, bold model).

        The 0.3.7 inline terminal always tells the user what the worker
        is doing so they never have to wonder whether a Turn is still
        running.  States, in priority order:

        * **Esc interrupt** — ``[model]  ⏸ interrupted by user`` for
          1.5 s after the last interrupt, then back to ``Idle``.
        * **Recovered draft** — ``[model]  Idle — edit the draft and
          press Enter`` for 1.5 s after a recovery prefill.
        * **Running** — ``[model]  ⏱ Ns · Esc to interrupt`` while
          ``pending_count > 0``; the 250 ms ticker keeps the seconds
          counter honest.
        * **Idle** — ``[model]  Idle`` otherwise.

        Failure is silent: a failed Turn parks the queue but does NOT
        surface a ``Failed · +N parked`` label here.  The user can still
        see the parked rows via ``/queue`` (internal alias) or abort
        them with ``/abort``.
        """
        import html as _html

        session = getattr(self, "_session", None)
        if session is None:
            return ""
        now = time.monotonic()
        model = str(getattr(session, "model_alias", "model") or "model")
        model_bold = f"<b>{_html.escape(model)}</b>"

        interrupt_at = getattr(session, "_last_interrupt_at", None)
        if interrupt_at is not None and (now - float(interrupt_at)) < 1.5:
            return f"{model_bold}  ⏸ interrupted by user"

        recovery_at = getattr(self, "_last_recovery_at", None)
        if (
            recovery_at is not None
            and (now - float(recovery_at)) < 1.5
            and getattr(self, "_draft_is_recovery", False)
        ):
            return f"{model_bold}  Idle — edit the draft and press Enter"

        try:
            pending = int(
                (session.queue_status() or {}).get("pending_count", 0) or 0
            )
        except Exception:
            pending = 0
        if pending > 0:
            started = float(getattr(session, "_turn_start_time", 0.0) or 0.0)
            elapsed = int(max(0, now - started)) if started > 0 else 0
            return f"{model_bold}  ⏱ {elapsed}s · Esc to interrupt"

        return f"{model_bold}  Idle"

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
        # Wrap the rendered tail, not the full transcript: the screen
        # projection is height-bounded to the viewport anyway, and the
        # full-text walk is O(transcript) on every call.
        text = _ANSI_ESCAPE.sub("", self._transcript.tail(_RENDER_TAIL_LINES))
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
        text = _ANSI_ESCAPE.sub("", self._transcript.tail(_RENDER_TAIL_LINES))
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
        # The selector renders its own cursor (active option marker);
        # the outer control's cursor must not also appear on top of it.
        if self._selector_registry.has_active:
            return Point(x=0, y=0)
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
        # Throttle cross-thread invalidation (streaming chunks, worker
        # appends). At session scale a full render takes tens of
        # milliseconds; without throttling, a fast stream schedules one
        # render per chunk and starves the key processor, which the owner
        # reported as a frozen page with dead arrow keys. Key/UI-thread
        # events are never throttled: try_get_running_loop distinguishes
        # them from producer threads.
        in_ui_thread = False
        try:
            in_ui_thread = asyncio.get_running_loop() is loop
        except RuntimeError:
            in_ui_thread = False
        if not in_ui_thread:
            now = loop.time()
            if now - self._last_invalidation_ts < 1.0 / _MAX_RENDER_FPS:
                # Skip this render; the next unthrottled event or the next
                # tick after the window elapses will repaint with the
                # accumulated tail. The very last chunk is guaranteed a
                # repaint by the trailing-edge timer below.
                if self._throttle_timer_handle is None:
                    def _trailing() -> None:
                        self._throttle_timer_handle = None
                        self._last_invalidation_ts = 0.0
                        self._schedule_invalidation_locked()

                    self._throttle_timer_handle = loop.call_later(
                        1.0 / _MAX_RENDER_FPS, _trailing
                    )
                return
            self._last_invalidation_ts = now
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
    """Own the application task, the stdout proxy, and the modal lifecycle.

    The 0.3.7 cycle reworked the modal lifecycle so that opening a
    selector does NOT tear down the main Prompt Toolkit ``Application``.
    Instead, the modal runs as a dialog inside the same ``Application``,
    and the controller flips the ``_live_terminal_active`` flag so other
    consumers can tell when a modal is on screen. The Application
    object identity is stable across a modal round trip.
    """

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
        """Mark the session as modal-occupied without tearing down the App.

        Returns True when the session is now considered modal. The
        controller does NOT call ``Application.exit()`` and does NOT
        await the main task: the persistent ``Application`` keeps
        running so the modal can run as a dialog inside it (see
        :meth:`run_selector` and ADR 0010).
        """
        if not should_pause:
            return False
        self._session._live_terminal_active = False
        return True

    async def resume_after_modal(self, paused: bool) -> None:
        """Mark the session as live again after a modal closes.

        The main ``Application`` and its proxy are still alive; this
        is just a flag flip. See :meth:`pause_for_modal` for the
        counterpart.
        """
        if not paused or self.terminal.is_closed:
            return
        self._session._live_terminal_active = True

    async def run_selector(
        self,
        selector_factory: Callable[[], Any],
    ) -> Any:
        """Open a selector dialog in the live Application.

        Two factory patterns are supported:

        1. **State-machine selector** (ADR 0010): ``selector_factory()``
           returns a :class:`~pawnlogic.selectors.SelectorState` (or any
           object that implements ``formatted_text``, ``handle_key``,
           ``is_closed``, and ``close(result)``).  The controller
           installs the selector in the
           :class:`~pawnlogic.selectors.SelectorRegistry`, the live
           ``Application``'s key bindings take over from the composer,
           the selector Float becomes visible, and the awaiting
           command blocks until the user confirms or cancels.

        2. **Nested-Application TUI** (transitional): some interactive
           TUIs (notably :func:`core.provider_tui.run_provider_tui` and
           :func:`core.skill_tui.run_skill_pack_tui`) still drive their
           own ``Application`` and only return ``None`` when the user
           exits.  ``selector_factory()`` is detected as a callable
           that returns an awaitable; the controller schedules it as
           a background task on the live ``Application`` so the main
           ``Application`` identity stays stable across the round
           trip even though the inner TUI spins up its own
           ``Application.run_async()`` and exits it.  The full
           in-Application Float rewrite for these panels is the
           documented follow-up; this branch keeps them functional in
           0.3.7 while ADR 0010 is honoured for the main
           ``Application``.

        Returns the selector's result (typically a string alias for
        ``/model`` and ``/planguard``) or ``None`` if the user
        cancelled / closed the TUI.

        The main ``Application`` object identity stays stable across
        every round trip.  See ADR 0010 and
        ``pawnlogic/selectors.py``.
        """
        application = self.terminal.application
        if application is None:
            return None
        produced = selector_factory()
        if produced is None:
            return None
        # State-machine selector path: install in the registry, await
        # the future, close the selector when the command returns.
        if isinstance(produced, SelectorState):
            future = self.terminal.open_selector(produced)
            try:
                return await future
            finally:
                self.terminal.close_selector()
        # Nested-Application TUI path: the factory returned either
        # a callable that produces an awaitable, or an awaitable
        # itself (a coroutine).  Schedule it on the live Application
        # as a background task so the main Application identity is
        # kept.
        if callable(produced) or inspect.isawaitable(produced):
            run_callable: Any
            if callable(produced):

                async def _await_factory_result() -> Any:
                    return await produced()

                run_callable = _await_factory_result()
            else:
                run_callable = produced
            # A nested ``Application.run_async()`` must be the only
            # live Application on the PTY. Running it beside the main
            # Application produced the interleaved/scrambled provider
            # and skills panels the owner reported: two VT100 render
            # loops fight over cursor positioning and both key
            # processors read the same input stream. The 0.3.6
            # pause/teardown/resume lifecycle is therefore restored for
            # this transitional path: the main Application exits (its
            # state lives on in the terminal object), the proxy is
            # restored, the nested TUI runs alone, and the main
            # Application is rebuilt afterwards. State-machine
            # selectors (ADR 0010 path above) never pause anything.
            if self._proxy_active:
                self.terminal.restore_output_proxy()
                self._proxy_active = False
            self._session._live_terminal_active = False
            if self._fallback_sink is not None:
                self._activate_sink(self._fallback_sink)
            if self._task is not None and not self._task.done():
                self.terminal.pause()
                await asyncio.gather(self._task, return_exceptions=True)
            try:
                result = await run_callable
            finally:
                if not self.terminal.is_closed:
                    self._session._live_terminal_active = True
                    self._activate_sink(self.terminal.sink)
                    self.terminal.install_output_proxy()
                    self._proxy_active = True
                    self.terminal.prepare_run()
                    self._task = asyncio.create_task(self.terminal.run())
                    self._task.add_done_callback(self._observe_terminal_task)
                    await self.terminal.wait_until_ready()
            return result
        # Last resort: treat the produced object itself as a
        # SelectorState-like object.  Fall back to the state-machine
        # path so future selectors that don't subclass
        # ``SelectorState`` still work.
        future = self.terminal.open_selector(produced)
        try:
            return await future
        finally:
            self.terminal.close_selector()

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
        # Only ask the terminal to close if its Application is still
        # alive. The terminal's ``close()`` triggers
        # ``Application.exit()``, which raises if the future has
        # already been resolved (for example after a test pipe hit
        # EOF). Swallow that specific case so the controller's own
        # cleanup still runs to completion.
        try:
            self.terminal.close()
        except Exception as exc:
            logger.debug("Persistent terminal close swallowed: {!r}", exc)
        if self._task is not None and not self._task.done():
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
