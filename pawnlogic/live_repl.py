"""Prompt Toolkit live-composer adapters.

The CLI owns startup and dispatch; this module owns the small interaction
contract that turns key presses into typed scheduler submissions.  Keeping it
separate makes the synchronous readline fallback explicit and keeps the CLI
facade below its architecture budget.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
import signal
import sys
from typing import Any

from core.queue_tui import toolbar_queue_status
from core.turn_scheduler import SubmissionKind
from utils.ansi import YELLOW, c


LIVE_SLASH_COMMANDS = frozenset({"/queue", "/abort", "/exit", "/quit"})
LIVE_SLASH_NOTICE = (
    "  ⚠ A Turn is running; only /queue, /abort [--all], or /exit controls are "
    "available until it completes."
)


@dataclass(slots=True)
class LiveSubmissionState:
    """Hold the submission kind for exactly one Prompt Toolkit submit."""

    kind: SubmissionKind | None = None

    def consume(self) -> SubmissionKind | None:
        """Return and clear the kind marked by the latest key binding."""
        kind = self.kind
        self.kind = None
        return kind


def build_prompt_toolkit_bindings(
    key_bindings_factory: Callable[[], Any],
    *,
    session: Any,
    read_text_cache: Callable[[Path], str],
    restore_last_input_buffer: Callable[[Any, str, dict[str, str]], bool],
    last_input_path: Path,
) -> tuple[Any, LiveSubmissionState]:
    """Create live key bindings and return their per-session input state."""
    bindings = key_bindings_factory()
    submission_state = LiveSubmissionState()
    ctrl_z_restore_state: dict[str, str] = {}

    def running_turn() -> bool:
        return bool(session.queue_status().get("pending_count", 0))

    def interrupt_active_turn() -> bool:
        """Use the same typed control for Escape and Ctrl+C while running."""
        interrupt = getattr(session, "interrupt_active", None)
        return bool(interrupt()) if callable(interrupt) else False

    @bindings.add("enter")
    def _(event: Any) -> None:
        """Submit idle input or mark a running input as a steering message."""
        session._live_input_buffer = event.current_buffer
        submission_state.kind = (
            SubmissionKind.STEER if running_turn() else SubmissionKind.START
        )
        event.current_buffer.validate_and_handle()

    @bindings.add("escape", "enter")
    def _(event: Any) -> None:
        """Mark Alt+Enter as a natural-completion follow-up while running."""
        session._live_input_buffer = event.current_buffer
        submission_state.kind = (
            SubmissionKind.FOLLOW_UP if running_turn() else SubmissionKind.START
        )
        event.current_buffer.validate_and_handle()

    @bindings.add("escape", "up")
    def _(event: Any) -> None:
        """Recall the newest queued or recovered entry without consuming it."""
        session._live_input_buffer = event.current_buffer
        recall = getattr(session, "recall_queued_turn", None)
        content = recall() if callable(recall) else None
        if content:
            event.current_buffer.text = content
            event.current_buffer.cursor_position = len(content)

    @bindings.add("escape")
    def _(event: Any) -> None:
        """Interrupt one active Turn without consuming the current draft."""
        if running_turn():
            interrupt_active_turn()

    @bindings.add("c-c")
    @bindings.add("<sigint>")
    def _(event: Any) -> None:
        """Interrupt active work for key and terminal SIGINT paths."""
        if running_turn() and interrupt_active_turn():
            return
        event.app.exit(exception=KeyboardInterrupt())

    @bindings.add("backspace")
    @bindings.add("c-h")
    def _(event: Any) -> None:
        """Delete one character and refresh slash-command completion."""
        buffer = event.app.current_buffer
        if buffer.text:
            buffer.delete_before_cursor(1)
        if buffer.text.startswith("/"):
            buffer.start_completion(select_first=False)

    @bindings.add("c-z")
    def _(event: Any) -> None:
        """Restore the previous cached prompt while preserving the draft."""
        last_input = read_text_cache(last_input_path)
        restore_last_input_buffer(
            event.app.current_buffer,
            last_input,
            ctrl_z_restore_state,
        )

    return bindings, submission_state


def install_live_interrupt_handler(session: Any) -> Callable[[], None]:
    """Route terminal SIGINT to the active Turn's typed cancellation control.

    A PTY delivers Ctrl+C as SIGINT before Prompt Toolkit can dispatch its
    ``c-c`` binding.  The handler only requests scheduler cancellation on the
    main thread; the worker still stops cooperatively at its Turn token.  An
    idle SIGINT raises ``KeyboardInterrupt`` so the existing double-press exit
    behavior remains unchanged.
    """
    previous = signal.getsignal(signal.SIGINT)
    restored = False

    def _handler(_signum: int, _frame: Any) -> None:
        if running_turn():
            result = interrupt_active_turn()
            if result:
                status = session.queue_status()
                pending = bool(status.get("pending_count", 0))
                message = (
                    "\n  [interrupt pending] Waiting for the active Turn to stop...\n"
                    if pending
                    else "\n  [interrupt] Stopping current response; returning to edit mode...\n"
                )
                try:
                    sys.stdout.write(message)
                    sys.stdout.flush()
                except Exception:
                    pass
                return
        raise KeyboardInterrupt

    def running_turn() -> bool:
        return bool(session.queue_status().get("pending_count", 0))

    def interrupt_active_turn() -> bool:
        interrupt = getattr(session, "interrupt_active", None)
        return bool(interrupt()) if callable(interrupt) else False

    signal.signal(signal.SIGINT, _handler)

    def restore() -> None:
        nonlocal restored
        if restored:
            return
        restored = True
        signal.signal(signal.SIGINT, previous)

    return restore


def build_bottom_toolbar(
    session: Any,
    dynamic_config: Mapping[str, Any],
    html_factory: Callable[[str], Any],
) -> Callable[[], Any]:
    """Build the live composer toolbar without coupling it to CLI startup."""
    def bottom_toolbar() -> Any:
        model = session.model_alias
        tier = "MID"
        if dynamic_config["max_tokens"] <= 4096:
            tier = "LOW"
        elif dynamic_config["max_iter"] >= 150:
            tier = "ULTRA"
        elif dynamic_config["max_iter"] >= 100:
            tier = "MAX"
        elif dynamic_config["max_tokens"] >= 32768:
            tier = "DEEP"
        time_budget = dynamic_config.get("time_budget_sec", 0)
        time_text = f"  ⏱ {time_budget}s" if time_budget > 0 else ""
        token_count = session.total_prompt_tokens + session.total_completion_tokens
        # Context size is refreshed by the session's API-message builder;
        # never traverse mutable history from the live UI thread.
        context_used = int(getattr(session, "_toolbar_context_chars", 0))
        context_max = dynamic_config["ctx_max_chars"]
        context_pct = (
            min(100, int(context_used * 100 / context_max)) if context_max else 0
        )
        if context_pct >= 90:
            context_color = "ansired"
        elif context_pct >= 70:
            context_color = "ansiyellow"
        else:
            context_color = "ansigreen"
        queue_view = getattr(session, "queue_view", None)
        view = queue_view() if callable(queue_view) else None
        queue_status = toolbar_queue_status(view) if view is not None else "Idle · steer:0 · follow-up:0"
        return html_factory(
            f" <b>Model:</b> {model}"
            f"  <b>Tier:</b> {tier}"
            f"  <b>Tk:</b> {token_count:,}"
            f"  <b>Ctx:</b> <{context_color}>{context_pct}%</{context_color}>"
            f"  <b>Dir:</b> {session.cwd}"
            f"  <b>Phase:</b> {session.current_phase}"
            f"  <b>Queue:</b> {queue_status}"
            f"{time_text}"
        )

    return bottom_toolbar


def should_defer_live_slash(session: Any, raw: str, *, enabled: bool) -> bool:
    """Return whether a slash command is unsafe while a live Turn runs."""
    if not enabled or not session.queue_status().get("pending_count", 0):
        return False
    verb = raw.split(None, 1)[0].lower() if raw.strip() else ""
    return verb not in LIVE_SLASH_COMMANDS


def is_interrupted_recovery_control(raw: str) -> bool:
    """Return whether ``raw`` manages preserved work instead of replacing it."""
    verb = raw.split(None, 1)[0].lower() if raw.strip() else ""
    return verb in {"/queue", "/abort"}


def restore_interrupted_repl_input(session: Any, fallback: str) -> str:
    """Roll back display state and explain how to resume preserved work."""
    _removed, last_text = session.undo(1)
    session._autosave()
    queue_depth = session.queue_status()["queue_depth"]
    if queue_depth:
        suffix = "" if queue_depth == 1 else "s"
        print(c(
            YELLOW,
            "  [interrupted] Saved "
            f"{queue_depth} queued message{suffix}. Press Enter to retry it, "
            "edit then press Enter to replace it, run /queue resume to run it "
            "later, or /abort to discard it.",
        ))
    else:
        print(c(YELLOW, "  [interrupted] Edit and press Enter to retry."))
    return last_text or fallback


def dispatch_live_input(
    session: Any,
    raw: str,
    *,
    live_enabled: bool,
    retry_interrupted: bool,
    kind: SubmissionKind | None,
    serial_runner: Callable[..., Any],
) -> Any:
    """Route one accepted composer value through live or serial execution."""
    if live_enabled:
        if retry_interrupted:
            return session.retry_interrupted_turn(raw)
        return session.submit_live_turn(raw, kind=kind)
    return serial_runner(session, raw, retry_interrupted=retry_interrupted)


__all__ = [
    "LIVE_SLASH_COMMANDS",
    "LIVE_SLASH_NOTICE",
    "LiveSubmissionState",
    "build_bottom_toolbar",
    "build_prompt_toolkit_bindings",
    "dispatch_live_input",
    "install_live_interrupt_handler",
    "is_interrupted_recovery_control",
    "restore_interrupted_repl_input",
    "should_defer_live_slash",
]
