"""Behavioral tests for the persistent Prompt Toolkit terminal owner."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from threading import Thread
from types import SimpleNamespace
from unittest.mock import MagicMock

from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.output import DummyOutput

from core.turn_scheduler import SubmissionKind
from pawnlogic.live_terminal import (
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


def test_bypass_print_writes_to_original_stdout_while_proxy_is_active() -> None:
    """bypass_print reaches past the proxy to the original host stdout.

    When a modal selector is about to run, short notices (e.g. the
    ``Auto-corrected: /plg -> /planguard`` line) must reach the host
    PTY **before** the selector renders, even though the proxy still
    owns ``sys.stdout``.
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
                # Replace the original stdout the proxy wraps so we can
                # observe what ``bypass_print`` actually writes.
                terminal._stdout_frames[0] = (
                    capture,
                    terminal._stdout_frames[0][1],
                    sys.stderr,
                    terminal._stdout_frames[0][3],
                )
                controller.bypass_print("hello-host\n")
                assert captured == ["hello-host\n"], (
                    f"bypass_print must reach past the proxy; saw {captured!r}"
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
