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

import asyncio
from io import StringIO

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


def test_completed_output_reaches_host_scrollback_while_application_runs() -> None:
    """A complete output line must be flushed before the app is closed.

    The inline terminal owns Prompt Toolkit's renderer, so host output must
    be written through Prompt Toolkit's ``run_in_terminal`` handoff.  This
    test deliberately waits for the host sink while the application is still
    running and records calls to ``Application.exit``.  A close-only flush
    implementation fails because the host sink remains empty until the
    ``finally`` block closes the application.
    """

    async def scenario() -> None:
        import sys
        from threading import Thread

        from prompt_toolkit.input.defaults import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        class _HostTTY(StringIO):
            def isatty(self) -> bool:
                return True

        host = _HostTTY()
        original_stdout = sys.stdout
        sys.stdout = host
        try:
            with create_pipe_input() as pipe:
                terminal = PersistentTerminal(input=pipe, output=DummyOutput())
                terminal.install_output_proxy()
                run_task = asyncio.create_task(terminal.run())
                await terminal.wait_until_ready()
                application = terminal.application
                assert application is not None
                exit_calls: list[object] = []
                original_exit = application.exit

                def record_exit(*args: object, **kwargs: object) -> None:
                    exit_calls.append((args, kwargs))
                    original_exit(*args, **kwargs)

                application.exit = record_exit  # type: ignore[method-assign]

                worker = Thread(
                    target=terminal.append_output,
                    args=("line while app is alive\n",),
                )
                worker.start()
                worker.join()

                deadline = asyncio.get_running_loop().time() + 1.0
                while "line while app is alive\n" not in host.getvalue():
                    if asyncio.get_running_loop().time() >= deadline:
                        break
                    await asyncio.sleep(0.01)

                assert terminal.is_running, (
                    "the live Application must stay running during host flush"
                )
                assert exit_calls == [], (
                    "streaming host flush must not call Application.exit"
                )
                assert "line while app is alive\n" in host.getvalue(), (
                    "a completed output line must reach host scrollback before "
                    "PersistentTerminal.close()"
                )

                terminal.close()
                await run_task
                terminal.restore_output_proxy()
        finally:
            sys.stdout = original_stdout

    asyncio.run(scenario())


def test_partial_line_waits_for_newline_and_close_does_not_duplicate() -> None:
    """Only complete lines stream live; close flushes an unfinished tail once."""

    async def scenario() -> None:
        import sys

        from prompt_toolkit.input.defaults import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        class _HostTTY(StringIO):
            def isatty(self) -> bool:
                return True

        host = _HostTTY()
        original_stdout = sys.stdout
        sys.stdout = host
        try:
            with create_pipe_input() as pipe:
                terminal = PersistentTerminal(input=pipe, output=DummyOutput())
                terminal.install_output_proxy()
                run_task = asyncio.create_task(terminal.run())
                await terminal.wait_until_ready()

                terminal.append_output("partial line")
                await asyncio.sleep(0.05)
                assert host.getvalue() == "", (
                    "an unterminated stream line must stay in the live transcript"
                )

                terminal.append_output("\n")
                deadline = asyncio.get_running_loop().time() + 1.0
                while "partial line\n" not in host.getvalue():
                    if asyncio.get_running_loop().time() >= deadline:
                        break
                    await asyncio.sleep(0.01)
                assert host.getvalue().count("partial line\n") == 1

                terminal.append_output("tail without newline")
                terminal.close()
                await run_task
                terminal.restore_output_proxy()
                assert host.getvalue().count("partial line\n") == 1, (
                    "close() must not replay lines already flushed live"
                )
                assert host.getvalue().endswith("tail without newline\n")
        finally:
            sys.stdout = original_stdout

    asyncio.run(scenario())


def test_carriage_return_and_backspace_flush_the_final_line_once() -> None:
    """CR/BS rewrites must not expose stale partial text to host scrollback."""

    async def scenario() -> None:
        import sys

        from prompt_toolkit.input.defaults import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        class _HostTTY(StringIO):
            def isatty(self) -> bool:
                return True

        host = _HostTTY()
        original_stdout = sys.stdout
        sys.stdout = host
        try:
            with create_pipe_input() as pipe:
                terminal = PersistentTerminal(input=pipe, output=DummyOutput())
                terminal.install_output_proxy()
                run_task = asyncio.create_task(terminal.run())
                await terminal.wait_until_ready()

                terminal.append_output("working\rready\nnext\b!\n")
                deadline = asyncio.get_running_loop().time() + 1.0
                while "ready\n" not in host.getvalue():
                    if asyncio.get_running_loop().time() >= deadline:
                        break
                    await asyncio.sleep(0.01)

                terminal.close()
                await run_task
                terminal.restore_output_proxy()
                output = host.getvalue()
                assert "working" not in output
                assert output.count("ready\n") == 1
                assert output.endswith("nex!\n")
        finally:
            sys.stdout = original_stdout

    asyncio.run(scenario())


def test_worker_thread_burst_is_serialized_without_duplicate_host_lines() -> None:
    """A worker may append many lines while one PT host handoff is active."""

    async def scenario() -> None:
        import sys
        from threading import Thread

        from prompt_toolkit.input.defaults import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        class _HostTTY(StringIO):
            def isatty(self) -> bool:
                return True

        host = _HostTTY()
        original_stdout = sys.stdout
        sys.stdout = host
        try:
            with create_pipe_input() as pipe:
                terminal = PersistentTerminal(input=pipe, output=DummyOutput())
                terminal.install_output_proxy()
                run_task = asyncio.create_task(terminal.run())
                await terminal.wait_until_ready()

                def produce() -> None:
                    for index in range(40):
                        terminal.append_output(f"worker line {index}\n")

                worker = Thread(target=produce)
                worker.start()
                worker.join()
                deadline = asyncio.get_running_loop().time() + 1.0
                while "worker line 39\n" not in host.getvalue():
                    if asyncio.get_running_loop().time() >= deadline:
                        break
                    await asyncio.sleep(0.01)

                terminal.close()
                await run_task
                terminal.restore_output_proxy()
                output = host.getvalue()
                assert output.count("worker line 0\n") == 1
                assert output.count("worker line 39\n") == 1
                assert output.count("worker line ") == 40
        finally:
            sys.stdout = original_stdout

    asyncio.run(scenario())


def test_failed_host_write_retries_without_dropping_reserved_lines() -> None:
    """A transient host write failure must not advance the flush cursor."""

    async def scenario() -> None:
        import sys

        from prompt_toolkit.input.defaults import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        class _FlakyHostTTY(StringIO):
            def __init__(self) -> None:
                super().__init__()
                self.failures_remaining = 1

            def isatty(self) -> bool:
                return True

            def write(self, text: str) -> int:
                if self.failures_remaining:
                    self.failures_remaining -= 1
                    raise OSError("transient host write failure")
                return super().write(text)

        host = _FlakyHostTTY()
        original_stdout = sys.stdout
        sys.stdout = host
        try:
            with create_pipe_input() as pipe:
                terminal = PersistentTerminal(input=pipe, output=DummyOutput())
                terminal.install_output_proxy()
                run_task = asyncio.create_task(terminal.run())
                await terminal.wait_until_ready()

                terminal.append_output("first line\n")
                await asyncio.sleep(0.05)
                terminal.append_output("second line\n")

                deadline = asyncio.get_running_loop().time() + 1.0
                while not {
                    "first line\n",
                    "second line\n",
                }.issubset(set(host.getvalue().splitlines(keepends=True))):
                    if asyncio.get_running_loop().time() >= deadline:
                        break
                    await asyncio.sleep(0.01)

                live_output = host.getvalue()
                assert live_output.count("first line\n") == 1
                assert live_output.count("second line\n") == 1

                terminal.close()
                await run_task
                terminal.restore_output_proxy()
                assert host.getvalue().count("first line\n") == 1
                assert host.getvalue().count("second line\n") == 1
        finally:
            sys.stdout = original_stdout

    asyncio.run(scenario())


def test_final_partial_flush_retries_once_before_closing() -> None:
    """A transient close-time failure must not lose the partial tail."""

    async def scenario() -> None:
        import sys

        from prompt_toolkit.input.defaults import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        class _FlakyHostTTY(StringIO):
            def __init__(self) -> None:
                super().__init__()
                self.write_attempts = 0

            def isatty(self) -> bool:
                return True

            def write(self, text: str) -> int:
                self.write_attempts += 1
                if self.write_attempts == 1:
                    raise OSError("one-shot close failure")
                return super().write(text)

        host = _FlakyHostTTY()
        original_stdout = sys.stdout
        sys.stdout = host
        try:
            with create_pipe_input() as pipe:
                terminal = PersistentTerminal(input=pipe, output=DummyOutput())
                terminal.install_output_proxy()
                run_task = asyncio.create_task(terminal.run())
                await terminal.wait_until_ready()

                terminal.append_output("final partial tail")
                terminal.close()
                await asyncio.wait_for(run_task, timeout=1.0)
                terminal.restore_output_proxy()

                assert host.write_attempts == 2
                assert host.getvalue() == "final partial tail\n"
        finally:
            sys.stdout = original_stdout

    asyncio.run(scenario())


def test_persistent_host_failure_is_bounded_and_close_finishes() -> None:
    """A broken host must trip a bounded breaker instead of retrying forever."""

    async def scenario() -> None:
        import sys

        from prompt_toolkit.input.defaults import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        class _BrokenHostTTY(StringIO):
            def __init__(self) -> None:
                super().__init__()
                self.write_attempts = 0

            def isatty(self) -> bool:
                return True

            def write(self, _text: str) -> int:
                self.write_attempts += 1
                raise OSError("host unavailable")

        host = _BrokenHostTTY()
        original_stdout = sys.stdout
        sys.stdout = host
        try:
            with create_pipe_input() as pipe:
                terminal = PersistentTerminal(input=pipe, output=DummyOutput())
                terminal.install_output_proxy()
                run_task = asyncio.create_task(terminal.run())
                await terminal.wait_until_ready()

                terminal.append_output("host failure must be bounded\n")
                await asyncio.sleep(0.5)
                attempts_before_close = host.write_attempts
                assert 1 <= attempts_before_close <= 3

                terminal.close()
                await asyncio.wait_for(run_task, timeout=1.0)
                terminal.restore_output_proxy()
                attempts_after_close = host.write_attempts
                await asyncio.sleep(0.1)
                assert host.write_attempts == attempts_after_close
                assert attempts_after_close == attempts_before_close
        finally:
            sys.stdout = original_stdout

    asyncio.run(scenario())


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
