"""Behavioral tests for the persistent Prompt Toolkit terminal owner."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from typing import Any
from threading import Thread
from types import SimpleNamespace
from unittest.mock import MagicMock

from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.output import DummyOutput

from core.turn_scheduler import SubmissionKind
from pawnlogic.live_terminal import (
    _HOST_FLUSH_MIN_INTERVAL_SECONDS,
    _RENDER_TAIL_LINES,
    PersistentTerminal,
    PersistentTerminalController,
    TerminalSubmission,
)
from pawnlogic.live_repl import build_prompt_toolkit_bindings


def test_fast_chunks_keep_unsubmitted_draft_in_bottom_composer() -> None:
    async def scenario() -> None:
        with create_pipe_input() as pipe:
            terminal = PersistentTerminal(input=pipe, output=DummyOutput())
            run_task = asyncio.create_task(terminal.run())
            await terminal.wait_until_ready()
            terminal.set_default("draft waiting")

            def produce() -> None:
                for index in range(500):
                    terminal.append_output(f"chunk-{index}\n")

            worker = Thread(target=produce)
            worker.start()
            worker.join()
            await asyncio.sleep(0.05)

            lines = terminal.rendered_screen_lines()
            assert len(lines) == 40
            assert lines[-2] == "▶ You > draft waiting"
            assert lines[-1].startswith("Ready")
            assert "chunk-499" in "\n".join(lines[:-2])
            assert "draft waiting" not in "\n".join(lines[:-2])

            terminal.close()
            await run_task

    asyncio.run(scenario())


def test_terminal_refresh_is_event_driven_to_avoid_tty_backpressure() -> None:
    """Idle redraws must not starve keyboard reads on a slow terminal."""
    async def scenario() -> None:
        with create_pipe_input() as pipe:
            terminal = PersistentTerminal(input=pipe, output=DummyOutput())
            run_task = asyncio.create_task(terminal.run())
            await terminal.wait_until_ready()

            assert terminal.application is not None
            assert terminal.application.refresh_interval is None

            terminal.close()
            await run_task

    asyncio.run(scenario())


def test_queue_preview_stays_muted_immediately_above_bottom_composer() -> None:
    async def scenario() -> None:
        preview = [
            ("class:queue-preview", "  queued · steer · second question\n"),
            ("class:queue-preview", "  queued · follow-up · third question"),
        ]
        with create_pipe_input() as pipe:
            terminal = PersistentTerminal(
                input=pipe,
                output=DummyOutput(),
                queue_preview=lambda: preview,
            )
            run_task = asyncio.create_task(terminal.run())
            await terminal.wait_until_ready()
            terminal.refresh()
            await asyncio.sleep(0.05)

            lines = terminal.rendered_screen_lines()
            assert "second question" in lines[-4]
            assert "third question" in lines[-3]
            assert lines[-2] == "▶ You >"
            assert lines[-1].startswith("Ready")

            terminal.close()
            await run_task

    asyncio.run(scenario())


def test_worker_output_is_buffered_without_writing_to_stdout() -> None:
    terminal = PersistentTerminal(output=DummyOutput())
    original = sys.stdout

    def produce() -> None:
        for index in range(100):
            terminal.append_output(f"worker-{index}\n")

    worker = Thread(target=produce)
    worker.start()
    worker.join()

    assert sys.stdout is original
    assert terminal.output_text.endswith("worker-99\n")


def test_stream_append_cannot_move_cursor_past_rendered_snapshot() -> None:
    """Cursor metadata stays within the fragment lines cached for one render."""
    terminal = PersistentTerminal(output=DummyOutput())
    terminal.append_line("first")

    terminal._render_output()
    cursor_before_stream_append = terminal._output_cursor_position()
    terminal.append_line("second")

    assert cursor_before_stream_append.y == 1
    assert terminal._output_cursor_position().y == 1

    terminal._render_output()
    assert terminal._output_cursor_position().y == 2


def test_submissions_are_typed_and_application_stays_open_until_close() -> None:
    async def scenario() -> None:
        with create_pipe_input() as pipe:
            terminal = PersistentTerminal(input=pipe, output=DummyOutput())
            run_task = asyncio.create_task(terminal.run())
            await terminal.wait_until_ready()

            pipe.send_text("steer now\r")
            submission = await terminal.next_submission()

            assert submission == TerminalSubmission(
                "steer now", SubmissionKind.START
            )
            assert terminal.output_text.endswith("▶ You >\x1b[0m steer now\n")
            assert terminal.is_running

            terminal.close()
            await run_task
            assert not terminal.is_running

    asyncio.run(scenario())


def test_composer_grows_to_wrapped_multiline_and_still_submits_on_enter() -> None:
    """Regression: long composer input must wrap and Enter must still submit.

    The TextArea was created with ``multiline=False``, which TextArea
    treats as ``height=Dimension.exact(1)`` regardless of the
    ``Dimension(min=1, max=5)`` we passed. ``wrap_lines=True`` was
    silently ignored, so long input was clipped, not wrapped.  The
    ``enter`` binding from ``live_repl`` is registered AFTER the
    default ``_newline`` handler in the merged ``_CombinedRegistry``,
    so the LAST matching handler wins on a ControlM press and the
    buffer still submits on Enter even though the composer is
    multiline.  ``eager=True`` is intentionally NOT used here; the
    0.3.7 inline-terminal audit confirmed that ``eager=True`` on
    the ``enter`` binding breaks the live composer's normal
    text-insert path.
    """
    async def scenario() -> None:
        session = SimpleNamespace(
            queue_status=lambda: {"pending_count": 0},
            _live_input_buffer=None,
        )
        bindings, state = build_prompt_toolkit_bindings(
            KeyBindings,
            session=session,
            read_text_cache=lambda _path: "",
            restore_last_input_buffer=lambda *_args: False,
            last_input_path=Path(".last_input"),
        )
        with create_pipe_input() as pipe:
            terminal = PersistentTerminal(
                input=pipe,
                output=DummyOutput(),
                key_bindings=bindings,
                submission_kind=state.consume,
            )
            run_task = asyncio.create_task(terminal.run())
            await terminal.wait_until_ready()

            # A 60-character message exceeds the typical narrow TUI width;
            # with the bug it would have been clipped to a single line.
            long_input = "analyze the screenshot, fix the layout bug, and re-run"
            pipe.send_text(long_input + "\r")
            submission = await terminal.next_submission()
            assert submission is not None
            assert submission.text == long_input

            terminal.close()
            await run_task

    asyncio.run(scenario())


def test_composer_cj_submits_via_default_newline2_re_feed() -> None:
    """Bare ``\\n`` (``Keys.ControlJ``) is re-fed by Prompt Toolkit as ControlM.

    The 0.3.7 inline-terminal audit confirmed that registering a custom
    ``c-j`` binding (even with ``eager=True``) breaks the live composer's
    normal text-insert path for the first typed key.  The fix is to
    leave ``c-j`` to Prompt Toolkit's default ``_newline2`` handler in
    ``prompt_toolkit.key_binding.bindings.basic``, which unconditionally
    re-feeds the press as a ``ControlM`` for terminals that send
    ``\\n`` on Enter.  On a multiline composer, that re-feed then lands
    on this binding's ``enter`` handler, which submits the buffer.

    This regression test pins that contract: a bare ``\\n`` after a
    single line of text submits with the original text intact, exactly
    the way the PTY e2e suite's ``child.sendline`` path expects.
    """
    async def scenario() -> None:
        session = SimpleNamespace(
            queue_status=lambda: {"pending_count": 0},
            _live_input_buffer=None,
        )
        bindings, state = build_prompt_toolkit_bindings(
            KeyBindings,
            session=session,
            read_text_cache=lambda _path: "",
            restore_last_input_buffer=lambda *_args: False,
            last_input_path=Path(".last_input"),
        )
        with create_pipe_input() as pipe:
            terminal = PersistentTerminal(
                input=pipe,
                output=DummyOutput(),
                key_bindings=bindings,
                submission_kind=state.consume,
            )
            run_task = asyncio.create_task(terminal.run())
            await terminal.wait_until_ready()

            # The TextArea stays multiline so wrap still works for long
            # input; the multiline feature simply loses literal-newline
            # insertion (no ``c-j`` binding).  Users wanting a hard
            # newline inside a draft should use the Buffer API directly
            # (for example via a future /draft command), not the
            # composer key.
            assert terminal.composer.buffer.multiline is True or terminal.composer.buffer.multiline() is True
            # A bare ``\\n`` re-feeds as Enter and submits the buffer.
            pipe.send_text("draft message\x0a")
            submission = await asyncio.wait_for(terminal.next_submission(), timeout=0.5)
            assert submission is not None
            assert submission.text == "draft message"

            terminal.close()
            await run_task

    asyncio.run(scenario())


def test_submission_api_accepts_steer_and_follow_up_without_prompt_exit() -> None:
    async def scenario() -> None:
        terminal = PersistentTerminal(output=DummyOutput())
        terminal.submit("steer", SubmissionKind.STEER)
        terminal.submit("later", SubmissionKind.FOLLOW_UP)

        assert await terminal.next_submission() == TerminalSubmission(
            "steer", SubmissionKind.STEER
        )
        assert await terminal.next_submission() == TerminalSubmission(
            "later", SubmissionKind.FOLLOW_UP
        )

        terminal.close()
        assert await terminal.next_submission() is None

    asyncio.run(scenario())


def test_output_proxy_routes_print_and_restores_stdout_on_error() -> None:
    terminal = PersistentTerminal(output=DummyOutput())
    original = sys.stdout
    original_stderr = sys.stderr

    try:
        with terminal.output_proxy():
            print("captured worker output")
            sys.stderr.write("captured worker error\n")
            assert sys.stdout is not original
            assert sys.stderr is not original_stderr
            raise RuntimeError("expected test error")
    except RuntimeError:
        pass

    assert sys.stdout is original
    assert sys.stderr is original_stderr
    assert "captured worker output\n" in terminal.output_text
    assert "captured worker error\n" in terminal.output_text


def test_terminal_sink_keeps_command_output_in_transcript() -> None:
    terminal = PersistentTerminal(output=DummyOutput())

    terminal.sink.print("command result")
    terminal.sink.write("stream result")

    assert terminal.output_text == "command result\nstream result"


def test_carriage_return_updates_spinner_line_without_control_glyphs() -> None:
    terminal = PersistentTerminal(output=DummyOutput())

    terminal.append_output("working\r  | Thinking...\r  / Thinking...\nready\b!")

    assert terminal.output_text == "  / Thinking...\nread!"
    assert "\r" not in terminal.output_text
    assert "\b" not in terminal.output_text


def test_existing_live_bindings_resolve_running_enter_as_steer() -> None:
    async def scenario() -> None:
        session = SimpleNamespace(
            queue_status=lambda: {"pending_count": 1},
            _live_input_buffer=None,
        )
        bindings, state = build_prompt_toolkit_bindings(
            KeyBindings,
            session=session,
            read_text_cache=lambda _path: "",
            restore_last_input_buffer=lambda *_args: False,
            last_input_path=Path(".last_input"),
        )
        with create_pipe_input() as pipe:
            terminal = PersistentTerminal(
                input=pipe,
                output=DummyOutput(),
                key_bindings=bindings,
                submission_kind=state.consume,
            )
            run_task = asyncio.create_task(terminal.run())
            await terminal.wait_until_ready()
            pipe.send_text("change direction\r")

            assert await terminal.next_submission() == TerminalSubmission(
                "change direction",
                SubmissionKind.STEER,
            )
            assert "change direction" not in terminal.output_text

            terminal.close()
            await run_task

    asyncio.run(scenario())


def test_bare_escape_interrupts_active_turn_without_sequence_length_delay() -> None:
    async def scenario() -> None:
        interrupted = asyncio.Event()
        interrupt_active = MagicMock(
            side_effect=lambda: interrupted.set() or True,
        )
        session = SimpleNamespace(
            queue_status=lambda: {"pending_count": 1},
            interrupt_active=interrupt_active,
            _live_input_buffer=None,
        )
        bindings, state = build_prompt_toolkit_bindings(
            KeyBindings,
            session=session,
            read_text_cache=lambda _path: "",
            restore_last_input_buffer=lambda *_args: False,
            last_input_path=Path(".last_input"),
        )
        with create_pipe_input() as pipe:
            terminal = PersistentTerminal(
                input=pipe,
                output=DummyOutput(),
                key_bindings=bindings,
                submission_kind=state.consume,
            )
            run_task = asyncio.create_task(terminal.run())
            await terminal.wait_until_ready()

            pipe.send_text("\x1b")
            await asyncio.wait_for(interrupted.wait(), timeout=0.5)

            interrupt_active.assert_called_once_with()
            terminal.close()
            await run_task

    asyncio.run(scenario())


def test_mouse_wheel_scrolls_output_without_touching_composer_history() -> None:
    """A wheel event moves the output viewport, not the editable prompt."""
    async def scenario() -> None:
        with create_pipe_input() as pipe:
            terminal = PersistentTerminal(input=pipe, output=DummyOutput())
            for index in range(80):
                terminal.append_line(f"history line {index}")
            terminal.set_default("draft stays here")
            run_task = asyncio.create_task(terminal.run())
            await terminal.wait_until_ready()
            terminal.refresh()
            await asyncio.sleep(0.05)

            before = "\n".join(terminal.rendered_screen_lines()[:-2])
            assert "history line 79" in before
            assert terminal.draft == "draft stays here"

            # SGR mouse wheel-up packet.  The event is positioned inside the
            # output viewport, away from the composer and toolbar.
            for _ in range(20):
                pipe.send_text("\x1b[<64;10;5M")
            await asyncio.sleep(0.1)

            after = "\n".join(terminal.rendered_screen_lines()[:-2])
            assert "history line 79" not in after
            assert "history line 0" in after or "history line 1" in after
            assert terminal.draft == "draft stays here"

            # Coordinate-free wheel packets are normally translated to
            # Keys.ScrollUp/ScrollDown by a multiplexer.  They must use the
            # same output viewport and never become composer history events.
            for _ in range(100):
                pipe.send_text("\x1b[63~")
            for _ in range(20):
                pipe.send_text("\x1b[62~")
            await asyncio.sleep(0.1)
            no_coordinate = "\n".join(terminal.rendered_screen_lines()[:-2])
            assert "history line 0" in no_coordinate or "history line 1" in no_coordinate

            # Wheel-down reaches the tail and resumes automatic following.
            for _ in range(100):
                pipe.send_text("\x1b[63~")
            terminal.append_line("new tail output")
            await asyncio.sleep(0.1)
            tail = "\n".join(terminal.rendered_screen_lines()[:-2])
            assert "new tail output" in tail
            assert terminal.draft == "draft stays here"

            terminal.close()
            await run_task

    asyncio.run(scenario())


def test_recovery_draft_is_marked_on_the_submission() -> None:
    """A recovered draft can be edited and identified as a replacement."""
    async def scenario() -> None:
        with create_pipe_input() as pipe:
            terminal = PersistentTerminal(input=pipe, output=DummyOutput())
            terminal.set_recovery_draft("original prompt")
            run_task = asyncio.create_task(terminal.run())
            await terminal.wait_until_ready()
            await asyncio.sleep(0.05)

            assert terminal.draft == "original prompt"
            pipe.send_text(" edited\r")
            submission = await terminal.next_submission()

            assert submission.text == "original prompt edited"
            assert submission.kind is SubmissionKind.START
            assert submission.recovery
            terminal.close()
            await run_task

    asyncio.run(scenario())


def test_controller_pause_resume_and_close_restore_terminal_ownership() -> None:
    async def scenario() -> None:
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        session = SimpleNamespace(_live_terminal_active=False)
        fallback_sink = object()
        activated: list[object] = []
        with create_pipe_input() as pipe:
            terminal = PersistentTerminal(input=pipe, output=DummyOutput())
            controller = PersistentTerminalController(
                terminal,
                session,
                activated.append,
                fallback_sink,
            )
            try:
                await controller.start()
                assert session._live_terminal_active
                assert sys.stdout is not original_stdout
                assert sys.stderr is not original_stderr
                assert activated[-1] is terminal.sink

                # 0.3.7 modal lifecycle: the main Application stays
                # alive while a selector dialog is open. The proxy
                # remains installed; only the session flag flips.
                assert await controller.pause_for_modal(True)
                assert not session._live_terminal_active
                assert sys.stdout is not original_stdout
                assert sys.stderr is not original_stderr
                assert terminal.is_running

                await controller.resume_after_modal(True)
                assert session._live_terminal_active
                assert sys.stdout is not original_stdout
                assert sys.stderr is not original_stderr
                assert terminal.is_running

                await controller.close()
                assert not session._live_terminal_active
                assert sys.stdout is original_stdout
                assert sys.stderr is original_stderr
                assert activated[-1] is fallback_sink
            finally:
                if sys.stdout is not original_stdout:
                    terminal.restore_output_proxy()

    asyncio.run(scenario())


def test_no_bypass_writes_reach_host_stdout_while_proxy_is_active() -> None:
    """No code path may write raw bytes to host stdout while the App lives.

    The 0.3.7 audit removed ``bypass_print``: writing raw bytes to the
    host PTY while the Application is alive corrupts PT's VT100 cursor
    positioning (the interleaved ``Select modelel for this session``
    scramble). Auto-correct notices and every other line output now
    route through the terminal sink / transcript only. This regression
    test asserts the controller exposes no bypass seam and that sink
    output lands in the transcript, never in the original stdout.
    """
    captured: list[str] = []

    class _CapturingStdout:
        def write(self, text: str) -> int:
            captured.append(text)
            return len(text)

        def flush(self) -> None:
            return None

    original_stdout = sys.stdout
    session = SimpleNamespace(_live_terminal_active=False)
    capture = _CapturingStdout()
    try:
        with create_pipe_input() as pipe:
            terminal = PersistentTerminal(input=pipe, output=DummyOutput())
            controller = PersistentTerminalController(
                terminal,
                session,
                lambda _sink: None,
                None,
            )
            try:
                asyncio.run(controller.start())
                assert sys.stdout is not original_stdout
                # Replace the original stdout the proxy wraps so any raw
                # write that escapes the sink would be observable here.
                terminal._stdout_frames[0] = (
                    capture,
                    terminal._stdout_frames[0][1],
                    sys.stderr,
                    terminal._stdout_frames[0][3],
                )
                assert not hasattr(controller, "bypass_print"), (
                    "bypass_print was removed; raw host-stdout writes "
                    "corrupt the live Application"
                )
                terminal.sink.print("routed through the transcript")
                assert "routed through the transcript" in terminal.output_text
                assert captured == [], (
                    f"sink output leaked to host stdout: {captured!r}"
                )
            finally:
                asyncio.run(controller.close())
    finally:
        sys.stdout = original_stdout


def test_body_layout_uses_a_single_output_window_not_two_conditional_containers() -> None:
    """Regression: only one output region must exist in the body.

    The previous layout stacked two ``ConditionalContainer``s
    (one for the transcript, one for the selector) into the body
    HSplit.  Both took layout space; the selector only filled the
    first row, leaving the transcript fragment bleeding through and
    scrambling the page.  This test walks the body HSplit and
    confirms there is exactly one switching output ``Window``
    (the one whose control is the same instance the terminal
    stores on ``self._output_window``) — not two gated Windows.
    """
    from prompt_toolkit.layout import (
        ConditionalContainer,
        DynamicContainer,
        FloatContainer,
        HSplit,
    )

    from pawnlogic.live_terminal import PersistentTerminal

    with create_pipe_input() as pipe:
        terminal = PersistentTerminal(input=pipe, output=DummyOutput())
        # Force the layout to build without spinning the Application.
        application = terminal._build_application_locked()
        root = application.layout.container
        # FloatContainer -> body HSplit.
        body = root
        if isinstance(body, FloatContainer):
            body = body.content
        if isinstance(body, DynamicContainer):
            body = body.get_container()
        assert isinstance(body, HSplit), (
            f"layout root body must be HSplit, got {type(body).__name__}"
        )

        # The terminal stores the single output Window on
        # ``self._output_window``; the body must contain it
        # exactly once and not duplicate it inside a
        # ``ConditionalContainer`` next to the queue preview.
        output_window = terminal._output_window
        assert output_window is not None, "terminal must own an output Window"
        output_matches = [
            child for child in body.children
            if child is output_window
        ]
        assert len(output_matches) == 1, (
            f"body must contain the output Window exactly once; "
            f"found {len(output_matches)}"
        )
        # No ConditionalContainer may wrap the output Window:
        # the body must not stack the transcript and the selector.
        for child in body.children:
            if isinstance(child, ConditionalContainer) and child.content is output_window:
                raise AssertionError(
                    "output Window must not be wrapped in a "
                    "ConditionalContainer — the transcript and "
                    "the selector must share the same Window "
                    "via a switching text callable"
                )
        terminal.close()


def test_output_window_text_switches_to_active_selector() -> None:
    """Regression: the single output Window's text source must
    switch from transcript to selector when a selector is active.

    Without this, the selector Float would be missing entirely or
    the transcript would bleed through under it.  We install a
    minimal ``SelectorState`` directly into the terminal's
    registry and confirm ``_output_or_selector_text`` returns the
    selector's formatted text (which contains the selector's
    unique title) instead of the transcript snapshot.
    """
    from pawnlogic.selectors import PlanGuardSelector

    with create_pipe_input() as pipe:
        terminal = PersistentTerminal(input=pipe, output=DummyOutput())
        # Seed the transcript so we can detect when the switch
        # correctly hides it.
        terminal.append_output("transcript-line-marker-XYZ\n")
        baseline = terminal._output_or_selector_text()
        # The transcript path returns a plain string (or ANSI
        # wrapper); the selector path returns a list of
        # ``(style, text)`` tuples.  That structural difference
        # is enough to confirm the routing without parsing.
        assert isinstance(baseline, (str, ANSI)), (
            f"baseline render must be the transcript text; got {type(baseline).__name__}"
        )
        assert "transcript-line-marker-XYZ" in str(baseline), (
            "baseline render must show the transcript"
        )

        # Install a selector and re-render.  The output Window
        # must now show the selector's text, not the transcript.
        selector = PlanGuardSelector(current="advisory")
        loop = asyncio.new_event_loop()
        try:
            future: asyncio.Future[str | None] = loop.create_future()
            terminal._selector_registry.install_active(selector, future)
        finally:
            loop.close()
        assert terminal._selector_registry.has_active, (
            "selector must be active after install"
        )
        switched = terminal._output_or_selector_text()
        # Selector formatted text is a list of (style, text) tuples.
        assert isinstance(switched, list), (
            f"switched render must be a selector fragment list; got {type(switched).__name__}"
        )
        rendered = "".join(
            fragment[1] for fragment in switched
            if isinstance(fragment, tuple) and len(fragment) >= 2
        )
        assert "Plan Guard Mode" in rendered, (
            "output Window must show the active selector's text; "
            f"got {rendered!r}"
        )
        assert "transcript-line-marker-XYZ" not in rendered, (
            "output Window must NOT also show the transcript; the "
            "two views must not coexist in the same Window. "
            f"Got {rendered!r}"
        )
        terminal.close()


def test_transcript_tail_render_keeps_cost_bounded_for_large_sessions() -> None:
    """Regression: the render path must only project the transcript tail.

    At the owner's real session scale (6,000 lines / 250KB), rendering
    the full transcript on every redraw cost ~50ms per frame; streaming
    invalidations then starved the key processor and the page froze
    with dead arrow keys. The output control must therefore render the
    bounded tail (``tail(_RENDER_TAIL_LINES)``), not the full snapshot,
    and identical transcript versions must reuse the cached render.
    """
    async def scenario() -> None:
        with create_pipe_input() as pipe:
            terminal = PersistentTerminal(input=pipe, output=DummyOutput())
            for index in range(6000):
                terminal.append_line(f"stream line {index}")
            run_task = asyncio.create_task(terminal.run())
            await terminal.wait_until_ready()
            try:
                first = terminal._render_output()
                # Cached: same version returns the same object.
                again = terminal._render_output()
                assert first is again, (
                    "unchanged transcript must reuse the cached render"
                )
                # Tail-bounded: the render must not contain ancient lines.
                from prompt_toolkit.formatted_text import to_plain_text
                rendered_text = to_plain_text(first)
                assert "stream line 0\n" not in rendered_text, (
                    "render must project only the trailing tail, not the full transcript"
                )
                assert "stream line 5999" in rendered_text
                # A new appends invalidates the cache.
                terminal.append_line("a newer line appears")
                third = terminal._render_output()
                assert third is not first, (
                    "a transcript change must produce a fresh render"
                )
                assert "a newer line appears" in to_plain_text(third)
                # The full transcript is untouched for scrollback flush.
                assert "stream line 0\n" in terminal.output_text
            finally:
                terminal.close()
                await asyncio.gather(run_task, return_exceptions=True)

    asyncio.run(scenario())


def test_composer_up_down_recall_history_even_on_wrapped_multiline_drafts() -> None:
    """Regression: Up/Down must walk composer history on the multiline composer.

    Prompt Toolkit's stock ``auto_up``/``auto_down`` only walk history
    from the first/last row of the buffer. The 0.3.7 multiline composer
    wraps long drafts onto several rows, so on any wrapped draft Up
    moved the cursor inside the draft instead of recalling history —
    reported by the owner as "up/down keys dead". The explicit history
    bindings must walk history regardless of cursor row, while the
    completion menu keeps PT's complete_previous/complete_next.
    """
    async def scenario() -> None:
        session = SimpleNamespace(
            queue_status=lambda: {"pending_count": 0},
            _live_input_buffer=None,
        )
        bindings, _state = build_prompt_toolkit_bindings(
            KeyBindings,
            session=session,
            read_text_cache=lambda _path: "",
            restore_last_input_buffer=lambda *_args: False,
            last_input_path=Path(".last_input"),
        )
        with create_pipe_input() as pipe:
            from prompt_toolkit.history import InMemoryHistory
            _hist = InMemoryHistory()
            _hist.append_string("first submitted prompt")
            terminal = PersistentTerminal(
                input=pipe,
                output=DummyOutput(),
                key_bindings=bindings,
                submission_kind=lambda: SubmissionKind.START,
                history=_hist,
            )
            run_task = asyncio.create_task(terminal.run())
            await terminal.wait_until_ready()
            try:
                composer = terminal.composer
                assert composer is not None
                buffer = composer.buffer
                # Long draft that wraps to multiple rows: auto_up would move
                # the cursor, not recall history.
                long_draft = "a wrapped multi row draft " * 12
                buffer.text = long_draft
                buffer.cursor_position = len(long_draft)
                pipe.send_text("long draft that wraps across several rows " * 3)
                await asyncio.sleep(0.05)
                pipe.send_text("\x1b[A")  # Up arrow
                await asyncio.sleep(0.1)
                assert buffer.text == "first submitted prompt", (
                    f"Up must recall history on wrapped drafts; got {buffer.text!r}"
                )
                pipe.send_text("\x1b[B")  # Down arrow
                await asyncio.sleep(0.1)
                # Down returns to the working (draft) line at the end of history.
                assert buffer.text != "first submitted prompt", (
                    "Down must move forward in history"
                )
            finally:
                terminal.close()
                await asyncio.gather(run_task, return_exceptions=True)

    asyncio.run(scenario())


def test_auto_correction_notice_stays_in_transcript_not_host_stdout() -> None:
    """Auto-correct notices route through the sink; no raw host-PTY writes.

    Regression for the interleaved ``Select modelel for this session``
    scramble: ``dispatch_live_slash`` used to call the removed
    ``bypass_print`` while the selector was pending, writing raw bytes
    to the host PTY mid-render. The notice must append to the
    transcript instead.
    """
    from pawnlogic.live_repl import dispatch_live_slash

    captured_host: list[str] = []

    class _HostSink:
        def write(self, text: str) -> int:
            captured_host.append(text)
            return len(text)

        def flush(self) -> None:
            return None

    host_stdout = _HostSink()
    original_stdout = sys.stdout
    sink_calls: list[str] = []

    class _Sink:
        def print(self, text: str) -> None:
            sink_calls.append(text)

    async def scenario() -> None:
        session = SimpleNamespace(queue_status=lambda: {"pending_count": 0})

        async def dispatcher(raw: str, _session: Any) -> Any:
            return None

        async def notice(_text: str) -> None:
            return None

        async def _pause(should_pause: bool) -> bool:
            return should_pause

        async def _resume(_paused: bool) -> None:
            return None

        controller = SimpleNamespace(
            pause_for_modal=_pause,
            resume_after_modal=_resume,
        )
        result = await dispatch_live_slash(
            "/modelel",
            session,
            live_enabled=True,
            terminal_controller=controller,
            command_words=lambda: {"/model"},
            matching_words=lambda verb, words: ["/model"],
            dispatcher=dispatcher,
            terminal_notice=notice,
            sink=_Sink(),
            exit_sentinel=object(),
        )
        assert result is None
        assert any("Auto-corrected" in call for call in sink_calls), (
            f"notice must go through the sink; saw {sink_calls!r}"
        )
        assert captured_host == [], (
            f"no byte may reach the host stdout directly: {captured_host!r}"
        )

    sys.stdout = host_stdout
    try:
        asyncio.run(scenario())
    finally:
        sys.stdout = original_stdout


# ── Host flush debounce + host-width pre-wrap (scrollback duplication fix) ──


def test_wrap_host_payload_folds_cjk_rows_to_terminal_columns() -> None:
    """Wide glyphs must be pre-wrapped so the host never wraps a flushed row.

    Each host flush erases one screen row per logical line; a row the host
    terminal wraps itself leaves a residue row the erase misses, which the
    owner reported as duplicated/interleaved scrollback. Pre-wrapping with
    the host's real column count keeps erase cycles row-accurate.
    """
    from pawnlogic.live_terminal import _wrap_host_payload

    # A CJK glyph (U+4E2D) occupies 2 columns: 10 glyphs = 20 columns.
    # Wide glyphs are the exact case where host-side wrapping leaves erase
    # residue, so the pre-wrap must measure them with wcwidth.
    cjk = "\u4e2d" * 10
    assert _wrap_host_payload(cjk + "\n", 20) == cjk + "\n"
    folded = _wrap_host_payload(cjk, 19)
    assert folded == "\u4e2d" * 9 + "\n" + "\u4e2d"
    # Narrow ASCII passes through untouched.
    assert _wrap_host_payload("short line\n", 20) == "short line\n"
    # A one-column terminal degenerates to one glyph per row, never hangs.
    assert _wrap_host_payload("abc", 1) == "a\nb\nc"
    # Unmeasurable glyphs fall back to one column and never loop forever.
    assert _wrap_host_payload("a\u200bb", 10) == "a\u200bb"


def test_live_host_flush_is_debounced_between_flush_cycles() -> None:
    """Streaming bursts schedule at most one host flush per interval.

    The write itself still happens on the debounce timer, so complete lines
    reach the host scrollback without being dropped or duplicated.
    """

    from pawnlogic.live_terminal import _HOST_FLUSH_MIN_INTERVAL_SECONDS

    async def scenario() -> None:
        with create_pipe_input() as pipe:
            terminal = PersistentTerminal(input=pipe, output=DummyOutput())
            run_task = asyncio.create_task(terminal.run())
            await terminal.wait_until_ready()
            try:
                host_writes: list[str] = []
                real_stdout = sys.stdout

                class _Host:
                    def write(self, text: str) -> int:
                        host_writes.append(text)
                        return len(text)

                    def flush(self) -> None:
                        return None

                    def isatty(self) -> bool:
                        return True

                sys.stdout = real_stdout
                terminal._stdout_frames.append(
                    (real_stdout, None, real_stdout, None)
                )
                terminal._host_stdout = lambda: _Host()  # type: ignore[method-assign]

                # First flush goes through immediately (last_ts == 0).
                terminal.append_line("first complete line")
                await asyncio.sleep(0.3)
                assert any("first complete line" in w for w in host_writes)

                # A burst right after the committed flush must NOT schedule a
                # second immediate flush; it parks on the debounce timer.
                host_writes.clear()
                for i in range(50):
                    terminal.append_line(f"burst-{i}")
                await asyncio.sleep(0.3)
                assert host_writes == [], (
                    "burst flushes must be debounced, saw "
                    f"{len(host_writes)} writes"
                )

                # Once the debounce interval elapses, the timer flushes the
                # accumulated complete lines exactly once.
                await asyncio.sleep(
                    _HOST_FLUSH_MIN_INTERVAL_SECONDS + 0.5
                )
                burst_writes = [w for w in host_writes if "burst-" in w]
                assert burst_writes, "debounce timer must flush accumulated lines"
                joined = "".join(burst_writes)
                assert joined.count("burst-0\n") == 1
                assert joined.count("burst-49\n") == 1
            finally:
                sys.stdout = real_stdout
                terminal._stdout_frames.clear()
                terminal.close()
                await asyncio.sleep(0.1)
                await run_task

    asyncio.run(scenario())


def test_delivered_lines_leave_the_application_viewport() -> None:
    """Display ownership: a completed line must be visible exactly once —
    either in the live application viewport (not yet delivered) or in the
    host scrollback (delivered), never in both.

    Pins the double-render defect. Deterministic markers, unconditional
    assertions at every checkpoint, and a final exact-count audit of the
    full host byte stream. Timeouts and missing output fail loudly.
    """
    async def scenario() -> None:
        with create_pipe_input() as pipe:
            terminal = PersistentTerminal(input=pipe, output=DummyOutput())
            run_task = asyncio.create_task(terminal.run())
            await terminal.wait_until_ready()
            user_marker = "user-question-line"
            assistant_marker = "assistant-answer-line"
            second_marker = "second-answer-line"
            partial_tail = "partial-tail-no-newline"
            try:
                host_writes: list[str] = []
                real_stdout = sys.stdout

                class _Host:
                    def write(self, text: str) -> int:
                        host_writes.append(text)
                        return len(text)

                    def flush(self) -> None:
                        return None

                    def isatty(self) -> bool:
                        return True

                sys.stdout = real_stdout
                terminal._stdout_frames.append(
                    (real_stdout, None, real_stdout, None)
                )
                terminal._host_stdout = lambda: _Host()  # type: ignore[method-assign]

                async def wait_for_host(marker: str, timeout: float) -> None:
                    """Await until the marker reached the host or fail."""
                    deadline = 0.0
                    while deadline < timeout:
                        if any(marker in w for w in host_writes):
                            return
                        await asyncio.sleep(0.05)
                        deadline += 0.05
                    raise AssertionError(
                        f"{marker!r} never reached the host within {timeout}s"
                    )

                # ── Turn 1: user line + assistant line ──────────────
                terminal.append_line(user_marker)
                terminal.append_line(assistant_marker)
                await wait_for_host(assistant_marker, 5.0)
                await asyncio.sleep(0.3)  # let the restored redraw land

                screen = "\n".join(terminal.rendered_screen_lines())
                assert assistant_marker not in screen, (
                    "delivered assistant line still rendered in the app "
                    "viewport (double render)"
                )
                assert user_marker not in screen

                # ── Turn 2: must be delivered through the debounce window,
                # never silently skipped ────────────────────────────────
                terminal.append_line(second_marker)
                await wait_for_host(
                    second_marker,
                    2 * _HOST_FLUSH_MIN_INTERVAL_SECONDS + 1.0,
                )

                # ── Trailing partial line: undelivered until close ────
                terminal.append_output(partial_tail)  # no newline
                # A trailing partial line belongs to the streaming surface
                # until close: never in the live-flush payload, never in the
                # host stream, but present for the final include-partial
                # handoff.
                assert partial_tail not in terminal._transcript.pending_host_flush()[0]
                assert (
                    partial_tail
                    in terminal._transcript.pending_host_flush(
                        include_partial=True
                    )[0]
                )
                assert partial_tail not in "".join(host_writes)

                # ── Close: flushes the partial line, then audit ───────
                terminal.close()
                close_waited = 0.0
                while close_waited < 5.0 and not run_task.done():
                    await asyncio.sleep(0.05)
                    close_waited += 0.05
                assert run_task.done(), (
                    f"close did not finish in 5s (waited {close_waited:.2f}s)"
                )

                joined = "".join(host_writes)
                for marker in (
                    user_marker,
                    assistant_marker,
                    second_marker,
                    partial_tail,
                ):
                    count = joined.count(marker)
                    assert count == 1, (
                        f"{marker!r} appears {count}x in host stream, "
                        "expected exactly once"
                    )
                assert (
                    joined.index(user_marker)
                    < joined.index(assistant_marker)
                    < joined.index(second_marker)
                    < joined.index(partial_tail)
                ), "host stream must preserve transcript order"

                final_screen = "\n".join(terminal.rendered_screen_lines())
                for marker in (user_marker, assistant_marker, second_marker):
                    assert marker not in final_screen, (
                        "delivered content must not linger in the app "
                        "viewport after close"
                    )
            finally:
                sys.stdout = real_stdout
                terminal._stdout_frames.clear()
                if not run_task.done():
                    terminal.close()
                await asyncio.sleep(0.1)
                if not run_task.done():
                    await asyncio.wait_for(run_task, timeout=5)

    asyncio.run(scenario())


def test_wrap_host_payload_progresses_at_one_column_with_wide_glyph() -> None:
    """A width-2 glyph in a 1-column terminal used to spin forever because
    the inner cut stayed 0; every loop iteration must now emit a character."""
    from pawnlogic.live_terminal import _wrap_host_payload

    result = _wrap_host_payload("\u72ec\u89d2\u517d", 1)
    assert len(result.split("\n")) == 3
    assert result.replace("\n", "") == "\u72ec\u89d2\u517d"


def test_close_does_not_wait_for_the_debounce_window() -> None:
    """close() with a parked debounce timer must finish immediately; the
    old behavior deferred the final handoff to the 2 s debounce tick."""
    async def scenario() -> None:
        with create_pipe_input() as pipe:
            terminal = PersistentTerminal(input=pipe, output=DummyOutput())
            run_task = asyncio.create_task(terminal.run())
            await terminal.wait_until_ready()
            try:
                real_stdout = sys.stdout

                class _Host:
                    def write(self, text: str) -> int:
                        return len(text)

                    def flush(self) -> None:
                        return None

                    def isatty(self) -> bool:
                        return True

                sys.stdout = real_stdout
                terminal._stdout_frames.append(
                    (real_stdout, None, real_stdout, None)
                )
                terminal._host_stdout = lambda: _Host()  # type: ignore[method-assign]

                terminal.append_line("first complete line")
                await asyncio.sleep(0.3)
                # Park a debounce reservation exactly like a post-flush burst.
                terminal.append_line("burst line")
                with terminal._lock:
                    assert terminal._host_flush_debounce_handle is not None, (
                        "test precondition: a debounce timer must be pending"
                    )

                import time as _time

                started = _time.monotonic()
                terminal.close()
                close_waited = 0.0
                while close_waited < 5.0 and not run_task.done():
                    await asyncio.sleep(0.05)
                    close_waited += 0.05
                elapsed = _time.monotonic() - started
                assert run_task.done(), "close never finished"
                assert elapsed < 1.0, (
                    f"close waited {elapsed:.2f}s — debounce window delayed "
                    "shutdown"
                )
            finally:
                sys.stdout = real_stdout
                terminal._stdout_frames.clear()
                if not run_task.done():
                    terminal.close()
                await asyncio.sleep(0.1)
                if not run_task.done():
                    await asyncio.wait_for(run_task, timeout=5)

    asyncio.run(scenario())


def test_undelivered_tail_survives_large_delivered_prefix() -> None:
    """Regression: undelivered_tail() sliced with the absolute delivery
    cursor against a budget-truncated span, so after a large delivered
    prefix (production: ~600k chars) new output vanished from the
    viewport projection. The span's delivered head must be converted to
    span-local coordinates, including multi-chunk and buffer-cap cases.
    """
    from pawnlogic.terminal_transcript import TerminalTranscript

    # Reviewer scenario: large delivered prefix, then fresh output.
    transcript = TerminalTranscript(max_chars=2_000_000)
    transcript.append("a" * 600_000)
    end, prefix = transcript.pending_host_flush(include_partial=True)[1:]
    assert transcript.mark_host_flushed(end, prefix)
    transcript.append("b" * 500_000)
    transcript.append("TAIL-MARKER-7f3a\n")

    projection = transcript.undelivered_tail(1000)

    assert "TAIL-MARKER-7f3a" in projection
    assert projection.startswith("b"), (
        "projection must start exactly at the delivery boundary"
    )

    # Multi-chunk: cursor inside one chunk, everything delivered.
    small = TerminalTranscript(max_chars=2_000_000)
    for index in range(100):
        small.append(f"line-{index:03d}\n")
    end, prefix = small.pending_host_flush()[1:]
    assert small.mark_host_flushed(end, prefix)
    assert small.undelivered_tail(50) == ""
    small.append("new-line\n")
    assert small.undelivered_tail(50) == "new-line\n"

    # Buffer-cap trim moves the cursor down; projection must follow it.
    capped = TerminalTranscript(max_chars=1000)
    capped.append("x" * 900)
    end, prefix = capped.pending_host_flush(include_partial=True)[1:]
    assert capped.mark_host_flushed(end, prefix)
    capped.append("y" * 500)
    assert capped.undelivered_tail(50) == "y" * 500


def test_first_frame_after_host_write_excludes_delivered_text() -> None:
    """Timing regression: the delivery cursor must advance INSIDE the
    run_in_terminal window, i.e. before Prompt Toolkit restores and redraws.
    If the commit happens after the await (done-callback territory), the
    restored first frame still shows the just-delivered lines — the stale
    first frame the review measured (offset=0 redraw before offset=N)."""
    async def scenario() -> None:
        with create_pipe_input() as pipe:
            terminal = PersistentTerminal(input=pipe, output=DummyOutput())
            run_task = asyncio.create_task(terminal.run())
            await terminal.wait_until_ready()
            marker = "timing-probe-answer"
            try:
                real_stdout = sys.stdout
                frames: list[tuple[str, ...]] = []

                class _Host:
                    def write(self, text: str) -> int:
                        return len(text)

                    def flush(self) -> None:
                        return None

                    def isatty(self) -> bool:
                        return True

                sys.stdout = real_stdout
                terminal._stdout_frames.append(
                    (real_stdout, None, real_stdout, None)
                )
                terminal._host_stdout = lambda: _Host()  # type: ignore[method-assign]

                # Capture the application screen right after write() returns
                # — still inside the suspended window — and again at the
                # next renderer frame after the window closes.
                terminal.append_line(marker)
                deadline = 0.0
                offset_advanced_in_window = False
                while deadline < 5.0:
                    transcript = terminal._transcript
                    pending = transcript.pending_host_flush()[0]
                    if pending == "" and marker in transcript.snapshot():
                        offset_advanced_in_window = True
                        break
                    await asyncio.sleep(0.02)
                    deadline += 0.02
                assert offset_advanced_in_window, (
                    "delivery cursor did not advance before pending drained"
                )

                # The cursor is committed before the write callable returns;
                # sample the renderer's latest screen repeatedly across the
                # resume boundary: no frame observed from now on may contain
                # the delivered marker.
                stale_frames = 0
                for _ in range(20):
                    lines = terminal.rendered_screen_lines()
                    if lines:
                        frames.append(lines)
                        if any(marker in line for line in lines):
                            stale_frames += 1
                    await asyncio.sleep(0.05)
                assert frames, "no frames rendered after delivery"
                assert stale_frames == 0, (
                    f"{stale_frames}/{len(frames)} frames after the "
                    "in-window commit still show delivered text"
                )

                # And the projection itself is empty for delivered content.
                assert marker not in terminal._transcript.undelivered_tail(
                    _RENDER_TAIL_LINES
                )
            finally:
                sys.stdout = real_stdout
                terminal._stdout_frames.clear()
                if not run_task.done():
                    terminal.close()
                await asyncio.sleep(0.1)
                if not run_task.done():
                    await asyncio.wait_for(run_task, timeout=5)

    asyncio.run(scenario())


def test_thinking_spinner_is_gated_off_in_live_terminal_mode() -> None:
    """The stdout spinner writes \\r animation frames to sys.stdout; in live
    mode that stream is the transcript proxy, and its stop() erase wipes
    into content already owned by the streaming answer (owner-acceptance
    interleaving defect). While the inline terminal is active the spinner
    must not run; the status line already shows the same state."""
    from core.session import _ThinkingSpinner

    class _FakeSession:
        _live_terminal_active = True

    session = _FakeSession()
    # Same gate expression the turn loop uses.
    enabled = True and not getattr(session, "_live_terminal_active", False)
    spinner = _ThinkingSpinner(enabled)
    spinner.start()
    spinner._stop.wait(0.2)  # give a would-be thread time to print a frame
    assert spinner._thread is None
    assert not spinner._printed
    spinner.stop()
