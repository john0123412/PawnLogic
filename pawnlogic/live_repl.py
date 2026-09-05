"""Prompt Toolkit live-composer adapters.

The CLI owns startup and dispatch; this module owns the small interaction
contract that turns key presses into typed scheduler submissions.  Keeping it
separate makes the synchronous readline fallback explicit and keeps the CLI
facade below its architecture budget.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
import signal
import sys
import time
from typing import Any

from core.queue_tui import queue_rows
from core.turn_scheduler import SubmissionKind
from utils.ansi import YELLOW, c


LIVE_SLASH_COMMANDS = frozenset({"/abort", "/exit", "/quit", "/queue"})
LIVE_SLASH_NOTICE = (
    "  ⚠ A Turn is running; only /abort or /exit controls are "
    "available until it completes."
)
# Bottom-toolbar width budget (visible columns, not ANSI bytes).
# _TOOLBAR_HARD_MAX: never exceed a 100-column toolbar — anything past
# that is clipped mid-field by PT on 80-120 column terminals.
# The cap adapts to the live terminal's column count (when we can
# read it from PT) so the same logic fits 80-column, 120-column, and
# 160-column hosts without overflowing.
# _TOOLBAR_HARD_MAX: the static hard cap used outside PT's main loop
# and as a floor when the live width is suspiciously small.
# _TOOLBAR_COL_MARGIN: when adapting to the live terminal width we
# leave this many columns of slack so PT's row renderer does not
# still clip the last character off the right edge.
_TOOLBAR_HARD_MAX = 100
_TOOLBAR_COL_MARGIN = 4


async def _wait_for_interrupt_settlement(
    running_turn: Callable[[], bool],
) -> None:
    """Wait without blocking the UI until cooperative cancellation settles."""
    while running_turn():
        await asyncio.sleep(0.02)


def requires_modal_terminal(raw: str) -> bool:
    """Return whether an idle slash command temporarily owns the physical TTY."""
    parts = raw.strip().split()
    if not parts:
        return False
    verb = parts[0].lower()
    arg = parts[1].lower() if len(parts) > 1 else ""
    if verb in {"/planguard", "/plg", "/model", "/resume"}:
        return not arg
    if verb == "/skills":
        return not arg
    if verb == "/provider":
        return not arg or arg in {"add", "fetch", "test"}
    return verb in {"/setkey"}


async def dispatch_live_slash(
    raw: str,
    session: Any,
    *,
    live_enabled: bool,
    terminal_controller: Any,
    command_words: Callable[[], list[str]],
    matching_words: Callable[[str, list[str]], list[str]],
    dispatcher: Callable[[str, Any], Awaitable[Any]],
    terminal_notice: Callable[[str], Awaitable[None]],
    sink: Any,
    exit_sentinel: Any,
) -> Any:
    """Normalize and dispatch one slash command around optional modal TTY use."""
    paused = False
    if terminal_controller is not None:
        paused = await terminal_controller.pause_for_modal(
            not session.queue_status().get("pending_count", 0)
            and requires_modal_terminal(raw)
        )
    result = None
    try:
        parts = raw.split(None, 1)
        verb = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        registered = command_words()
        if verb not in registered and len(verb) >= 3:
            matches = matching_words(verb, registered)
            if len(matches) == 1:
                corrected = matches[0]
                raw = f"{corrected} {rest}".strip() if rest else corrected
                notice = c(YELLOW, f"  ✔ Auto-corrected: {verb} -> {corrected}\n")
                # Always route through the sink. Writing raw bytes to the
                # host PTY while the Application is alive corrupts PT's
                # VT100 cursor positioning (the interleaved
                # "Select modelel for this session" scramble); the
                # transcript renders the notice above the selector.
                sink.print(notice.rstrip("\n"))
        if should_defer_live_slash(session, raw, enabled=live_enabled):
            await terminal_notice(LIVE_SLASH_NOTICE)
            return None
        result = await dispatcher(raw, session)
        return result
    finally:
        if terminal_controller is not None and result is not exit_sentinel:
            await terminal_controller.resume_after_modal(paused)


@dataclass(slots=True)
class LiveSubmissionState:
    """Hold the submission kind for exactly one Prompt Toolkit submit."""

    kind: SubmissionKind | None = None
    recovery_draft: bool = False

    def consume(self) -> SubmissionKind | None:
        """Return and clear the kind marked by the latest key binding."""
        kind = self.kind
        self.kind = None
        return kind

    def mark_recovery_draft(self) -> None:
        """Make the next Enter replace the recovered prompt."""
        self.recovery_draft = True
        self.kind = SubmissionKind.START

    def consume_recovery_draft(self) -> bool:
        """Return and clear the recovered-draft marker after submission."""
        marked = self.recovery_draft
        self.recovery_draft = False
        return marked


def _mark_user_interrupt(session: Any) -> None:
    """Stamp the session so the status line shows ``⏸ interrupted by user``.

    The 0.3.7 persistent status line reads ``session._last_interrupt_at``
    and renders a 1.5 s confirmation banner when the user has just
    pressed Esc / Ctrl+C.  The marker is set on every user-initiated
    interrupt (Esc binding, Ctrl+C binding, and SIGINT in the live
    terminal path) so the line is always truthful.
    """
    try:
        session._last_interrupt_at = time.monotonic()
        session._last_interrupt_kind = "user"
    except Exception:
        # The status line is a best-effort convenience; never let a
        # missing attribute on a test session break the interrupt path.
        pass


def build_prompt_toolkit_bindings(
    key_bindings_factory: Callable[[], Any],
    *,
    session: Any,
    read_text_cache: Callable[[Path], str],
    restore_last_input_buffer: Callable[[Any, str, dict[str, str]], bool],
    last_input_path: Path,
    on_interrupt_settled: Callable[[], None] | None = None,
) -> tuple[Any, LiveSubmissionState]:
    """Create live key bindings and return their per-session input state."""
    bindings = key_bindings_factory()
    submission_state = LiveSubmissionState()
    ctrl_z_restore_state: dict[str, str] = {}
    interrupt_task: asyncio.Task[None] | None = None

    def running_turn() -> bool:
        return bool(session.queue_status().get("pending_count", 0))

    def queued_work() -> bool:
        return bool(session.queue_status().get("queue_depth", 0))

    def interrupt_active_turn() -> bool:
        """Use the same typed control for Escape and Ctrl+C while running."""
        interrupt = getattr(session, "interrupt_active", None)
        accepted = bool(interrupt()) if callable(interrupt) else False
        if accepted:
            _mark_user_interrupt(session)
        return accepted

    def recovery_draft_pending() -> bool:
        return submission_state.recovery_draft

    def schedule_interrupt(event: Any) -> None:
        """Request cancellation off the Prompt Toolkit event-loop thread."""
        nonlocal interrupt_task
        if interrupt_task is not None and not interrupt_task.done():
            return

        async def settle() -> None:
            nonlocal interrupt_task
            try:
                accepted = await asyncio.to_thread(interrupt_active_turn)
                if accepted and on_interrupt_settled is not None:
                    await _wait_for_interrupt_settlement(running_turn)
                    on_interrupt_settled()
            finally:
                interrupt_task = None

        create_task = getattr(event.app, "create_background_task", None)
        if callable(create_task):
            interrupt_task = create_task(settle())
        else:
            # Lightweight binding tests use a fake app without an event loop.
            # Preserve that seam while the real application remains async.
            interrupt_active_turn()

    @bindings.add("enter")
    def _(event: Any) -> None:
        """Submit idle input or mark a running input as a steering message.

        The composer is ``TextArea(multiline=True)`` so the buffer
        can grow past one row and ``wrap_lines=True`` actually wraps
        long input.  Prompt Toolkit's default ``_newline`` binding
        is registered for ``enter`` on a multiline composer, but the
        ``_CombinedRegistry`` resolves ``enter`` to the LAST matching
        handler in the merged list, so this binding wins over
        ``_newline`` even without ``eager=True``.  (An earlier 0.3.7
        commit added ``eager=True`` here; the audit confirmed that
        the flag breaks the live composer's normal text-insert path
        for the first typed key, so it is intentionally absent.)
        """
        session._live_input_buffer = event.current_buffer
        if recovery_draft_pending():
            submission_state.kind = SubmissionKind.START
        elif running_turn():
            submission_state.kind = SubmissionKind.STEER
        elif queued_work():
            submission_state.kind = SubmissionKind.FOLLOW_UP
        else:
            submission_state.kind = SubmissionKind.START
        event.current_buffer.validate_and_handle()

    @bindings.add("escape", "enter")
    def _(event: Any) -> None:
        """Mark Alt+Enter as a natural-completion follow-up while running."""
        session._live_input_buffer = event.current_buffer
        submission_state.kind = (
            SubmissionKind.FOLLOW_UP
            if running_turn() or queued_work()
            else SubmissionKind.START
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
        """Interrupt active Turn, then steer with the first queued item."""
        if running_turn():
            schedule_interrupt(event)
            if queued_work():
                # Convert the first queued item to STEER so the scheduler
                # picks it up as a directional steer when the turn resumes.
                from core.turn_scheduler import ControlAction, ControlKind
                action = ControlAction(kind=ControlKind.CLAIM_STEER)
                queue_control = getattr(session, "queue_control", None)
                if callable(queue_control):
                    queue_control(action)

    @bindings.add("c-c")
    @bindings.add("<sigint>")
    def _(event: Any) -> None:
        """Interrupt active work for key and terminal SIGINT paths."""
        if running_turn():
            schedule_interrupt(event)
            return
        event.app.exit(exception=KeyboardInterrupt())

    # Arrow-key history recall. Prompt Toolkit's stock ``auto_up`` /
    # ``auto_down`` only walk history when the cursor sits on the first
    # (resp. last) row of the buffer. The 0.3.7 multiline composer wraps
    # long drafts onto multiple rows, so ``auto_up`` started moving the
    # cursor inside the draft instead of recalling history — reported as
    # "up/down keys dead". These bindings restore the pre-0.3.7 contract:
    # Up/Down always walk composer history while the completion menu is
    # closed. The selector-active case never reaches here (its eager
    # bindings in live_terminal.py run first).
    def _has_completion_menu(event: Any) -> bool:
        return bool(getattr(event.app.current_buffer, "complete_state", None))

    @bindings.add("up")
    def _(event: Any) -> None:
        buffer = event.app.current_buffer
        if _has_completion_menu(event):
            buffer.complete_previous()
            return
        buffer.history_backward()

    @bindings.add("down")
    def _(event: Any) -> None:
        buffer = event.app.current_buffer
        if _has_completion_menu(event):
            buffer.complete_next()
            return
        buffer.history_forward()

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


def install_live_interrupt_handler(
    session: Any,
    *,
    on_interrupt_settled: Callable[[], None] | None = None,
) -> Callable[[], None]:
    """Route terminal SIGINT to the active Turn's typed cancellation control.

    A PTY delivers Ctrl+C as SIGINT before Prompt Toolkit can dispatch its
    ``c-c`` binding.  The handler only schedules the potentially-waiting
    scheduler cancellation; the worker still stops cooperatively at its Turn
    token.  An idle SIGINT raises ``KeyboardInterrupt`` so the existing
    double-press exit behavior remains unchanged.
    """
    previous = signal.getsignal(signal.SIGINT)
    restored = False
    closing = False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    interrupt_task: asyncio.Task[None] | None = None

    async def settle_interrupt() -> None:
        nonlocal interrupt_task
        try:
            accepted = await asyncio.to_thread(interrupt_active_turn)
            if accepted and on_interrupt_settled is not None:
                await _wait_for_interrupt_settlement(running_turn)
                on_interrupt_settled()
        finally:
            interrupt_task = None

    def schedule_interrupt() -> bool:
        nonlocal interrupt_task
        if loop is None or loop.is_closed():
            return False
        if interrupt_task is not None and not interrupt_task.done():
            return True
        interrupt_task = loop.create_task(settle_interrupt())
        return True

    def _handler(_signum: int, _frame: Any) -> None:
        # During interpreter shutdown the original handler chain is gone;
        # a stray ^C here must not raise from a dead helper into
        # threading._shutdown (the traceback the owner saw on exit).
        if closing:
            return
        if running_turn():
            if schedule_interrupt():
                try:
                    sys.stdout.write(
                        "\n  [interrupt pending] Waiting for the active Turn to stop...\n"
                    )
                    sys.stdout.flush()
                except Exception:
                    pass
                return
            # Keep a synchronous compatibility fallback for callers that
            # install the handler outside an async REPL loop.
            if interrupt_active_turn():
                return
        raise KeyboardInterrupt

    def running_turn() -> bool:
        return bool(session.queue_status().get("pending_count", 0))

    def interrupt_active_turn() -> bool:
        interrupt = getattr(session, "interrupt_active", None)
        accepted = bool(interrupt()) if callable(interrupt) else False
        if accepted:
            _mark_user_interrupt(session)
        return accepted

    signal.signal(signal.SIGINT, _handler)

    def restore() -> None:
        nonlocal restored, closing
        if restored:
            return
        restored = True
        closing = True
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
        # 0.3.7: the live terminal no longer surfaces the queue. The
        # toolbar therefore drops the ``Queue:`` segment and the
        # ``queue_view`` / ``toolbar_queue_status`` lookup.  The
        # persistent status line above the composer carries
        # running-vs-idle state; the user can clear the queue with
        # ``/abort`` (the only queue control the live UI advertises).
        # Wide toolbars were clipped mid-field on 80-column terminals
        # ("... follow-u") because PT truncates the single toolbar row.
        # Render only the fields that fit, most important first:
        # model, then context, tier, tokens, and only on wide
        # terminals the long directory path. The hard cap adapts to
        # the live terminal's column count when we can read it (PT
        # exposes ``Application.output.get_size`` inside its main
        # loop); outside the loop we fall back to the 100-column
        # static cap so the field budget is still safe on wide
        # terminals and PT does not wrap the row.
        try:
            from prompt_toolkit.application.current import get_app

            live_columns = get_app().output.get_size().columns
        except Exception:
            live_columns = None
        if live_columns and live_columns > _TOOLBAR_HARD_MAX:
            # Wide terminal: drop the 100-column ceiling so phase and
            # the directory path can both join the row. The live
            # visible width minus a 4-column safety margin is the
            # budget; only the fields that actually fit are rendered.
            hard_max = live_columns - _TOOLBAR_COL_MARGIN
        elif live_columns and live_columns > _TOOLBAR_COL_MARGIN + 20:
            # Narrow terminal that still has a usable get_size():
            # the visible width minus a 4-column margin is the cap
            # so PT does not clip the row mid-field on 80-90 column
            # hosts. The 100-column static cap above is too wide
            # for these widths and was the root of the
            # ``follow-u`` regression.
            hard_max = live_columns - _TOOLBAR_COL_MARGIN
        else:
            # No usable PT app (e.g. outside the main loop): fall
            # back to the static 100-column cap so the row is still
            # safe for tests and pre-loop invocations.
            hard_max = _TOOLBAR_HARD_MAX
        segments = [
            ("model", f"<b>Model:</b> {model}"),
            ("ctx", f"<b>Ctx:</b> <{context_color}>{context_pct}%</{context_color}>"),
            ("tier", f"<b>Tier:</b> {tier}"),
            ("tk", f"<b>Tk:</b> {token_count:,}"),
            ("phase", f"<b>Phase:</b> {session.current_phase}"),
            ("dir", f"<b>Dir:</b> {session.cwd}"),
            ("time", time_text),
        ]
        plain_len = 1  # leading space
        chosen: list[str] = []
        for name, segment in segments:
            if name == "time" and not time_text:
                continue
            # ``approx`` is the visible-column width of the segment
            # excluding the <b>/</b> tags so it matches the
            # terminal's column count. PT renders the tags with
            # zero columns; the inline ANSI color (e.g. <ansigreen>)
            # IS one character each because PT does not strip them.
            approx = (
                len(segment)
                - segment.count("<b>") * 3
                - segment.count("</b>") * 4
            )
            # Phase is short and fixed (≈12 chars); on a wide enough
            # terminal (>=100 cols) it always joins. The dir path is
            # variable and is dropped first when the budget runs out.
            # Model alias, ctx, tier, and tokens are the essential
            # fields and are never dropped.
            if name == "phase" and plain_len + approx + 2 > hard_max:
                # tight column count: leave the short fields visible
                continue
            if name == "dir" and plain_len + approx > hard_max:
                continue
            if plain_len + approx > hard_max and chosen:
                continue
            chosen.append(segment)
            plain_len += approx + 2
        return html_factory(" " + "  ".join(chosen))

    return bottom_toolbar


def build_queue_preview(
    session: Any,
    *,
    max_items: int = 3,
) -> Callable[[], list[tuple[str, str]]]:
    """Build muted, read-only rows for queued input above the composer.

    Conditionally rendered: an empty queue produces no output, so the
    composer area stays clean while nothing is queued — the 0.3.7
    "hidden queue UI" goal holds for the common case. The moment the
    user queues a second message, the muted rows reappear so steering
    and follow-up input stay visible (the owner's real-usage feedback
    after 6317195: without them, Enter-while-running and the
    Esc→CLAIM_STEER handoff happen invisibly and feel like lost input).

    While the session is failed or aborted the queue is parked (the
    scheduler refuses automatic drains), so scrolling every queued row
    on each redraw would fill the composer area with the same parked
    items. A parked queue renders one summary line plus the resume
    hint instead of the per-item list.
    """
    def queue_preview() -> list[tuple[str, str]]:
        queue_view = getattr(session, "queue_view", None)
        if not callable(queue_view):
            return []
        view = queue_view()
        rows = [row for row in queue_rows(view) if row.status != "running"]
        if not rows:
            return []
        if view.session_status in {"failed", "aborted"}:
            return [(
                "class:queue-preview",
                f"  ⏸ {len(rows)} message(s) parked after the failure — "
                "/queue resume to run them, /abort to discard",
            )]
        visible = rows[:max_items]
        lines = [
            f"  ↳ queued [{row.kind.value}] {row.summary}"
            for row in visible
        ]
        remaining = len(rows) - len(visible)
        if remaining:
            lines.append(f"  … +{remaining} more queued")
        return [("class:queue-preview", "\n".join(lines))]

    return queue_preview


def build_live_style(style_factory: Any) -> Any:
    """Build the persistent composer style outside the CLI facade."""
    return style_factory.from_dict({
        "prompt": "ansigreen bold",
        "you": "bold",
        "completion-menu": "bg:default fg:#bbbbbb",
        "completion-menu.completion": "bg:default fg:#bbbbbb",
        "completion-menu.meta.completion": "bg:default fg:#666666",
        "completion-menu.completion.current": "bg:#333333 fg:#ffffff",
        "completion-menu.meta.completion.current": "bg:#333333 fg:#aaaaaa",
        "completion-menu.completion.character-match": "fg:#00d787 bold",
        "scrollbar.background": "bg:default",
        "scrollbar.button": "bg:default",
        "bottom-toolbar": "bg:#222222 fg:#cccccc",
        "queue-preview": "fg:#777777 italic",
    })


def prefill_settled_recovery(
    session: Any,
    terminal: Any,
    submission_state: LiveSubmissionState,
) -> None:
    """Present one settled recovered prompt as an editable replacement.

    0.3.7: the persistent status line now carries a 1.5 s "edit the draft
    and press Enter" hint instead of a long printed banner.  Recovery is
    silent on the user UI; the banner only fires when the interrupt
    produced no draft at all (e.g. a fast abort before the worker
    checkpointed).
    """
    if terminal is None or terminal.is_closed:
        return
    queue_view = getattr(session, "queue_view", None)
    view = queue_view() if callable(queue_view) else None
    recovered = getattr(view, "recovered", None)
    if recovered is None:
        terminal.append_line(
            "  [interrupt] Active Turn stopped; no recoverable draft was produced."
        )
        terminal.refresh()
        return
    submission_state.mark_recovery_draft()
    terminal.set_recovery_draft(recovered.content)
    terminal.refresh()
    terminal.refresh()


def should_defer_live_slash(session: Any, raw: str, *, enabled: bool) -> bool:
    """Return whether a slash command is unsafe while a live Turn runs."""
    if not enabled or not session.queue_status().get("pending_count", 0):
        return False
    verb = raw.split(None, 1)[0].lower() if raw.strip() else ""
    return verb not in LIVE_SLASH_COMMANDS


def is_interrupted_recovery_control(raw: str) -> bool:
    """Return whether ``raw`` manages preserved work instead of replacing it.

    0.3.7: ``/abort`` is the user-visible queue control; ``/queue`` is
    an internal alias that still works when the user types it.  Both
    are treated as recovery controls (allowed while
    ``_retry_interrupted`` is set) so the slash dispatcher can run
    them instead of forwarding them to the model as a prompt.
    """
    verb = raw.split(None, 1)[0].lower() if raw.strip() else ""
    return verb in {"/abort", "/queue"}


def restore_interrupted_repl_input(session: Any, fallback: str) -> str:
    """Roll back display state and explain how to resume preserved work.

    0.3.7: the readline fallback keeps a one-liner that points the
    user at the recovered draft. The queue is no longer advertised
    here; ``/abort`` is the only user-visible queue control and the
    only recovery verb the user needs to learn.
    """
    _removed, last_text = session.undo(1)
    session._autosave()
    print(c(
        YELLOW,
        "  Edit the recovered prompt and press Enter to retry, or "
        "/abort to discard.",
    ))
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
    "build_live_style",
    "build_prompt_toolkit_bindings",
    "build_queue_preview",
    "dispatch_live_input",
    "dispatch_live_slash",
    "install_live_interrupt_handler",
    "is_interrupted_recovery_control",
    "prefill_settled_recovery",
    "requires_modal_terminal",
    "restore_interrupted_repl_input",
    "should_defer_live_slash",
]
