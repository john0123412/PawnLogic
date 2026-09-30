"""Status-line contract: persistent 1-line indicator of Turn state.

The 0.3.7 inline terminal must keep the user informed about what
the worker is doing without depending on a ``print()`` from the
session layer (which the readline path owns, but the live path
does not). This module pins the contract of the new
``live_status`` FormattedTextControl in
``pawnlogic.live_terminal.PersistentTerminal``.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from prompt_toolkit.data_structures import Size


def _fake_app(columns: int) -> SimpleNamespace:
    class _Output:
        @staticmethod
        def get_size() -> Size:
            return Size(rows=24, columns=columns)

    return SimpleNamespace(output=_Output)


def _session(
    *,
    pending: int,
    status: str = "idle",
    started_at: float | None = None,
    submitted_at: float | None = None,
    first_delta: bool = False,
    activity: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        model_alias="bai:glm-5.3-flash",
        queue_status=lambda: {"pending_count": pending, "queue_depth": 0},
        _turn_start_time=started_at,
        _turn_submitted_at=submitted_at,
        _turn_first_delta=first_delta,
        _current_tool_activity=activity,
        _last_interrupt_at=None,
        _last_interrupt_kind=None,
        _session_status=status,
    )


def _Future() -> object:
    """A stand-in for the registry's selector future.

    The status line never awaits it, and ``install_active`` only touches
    ``.done()`` when it supersedes an already-mounted selector, so a
    sentinel keeps these render tests free of a real event loop.
    """
    return SimpleNamespace(done=lambda: False, set_result=lambda _r: None)


def _MountedConfirmation():
    """A minimal selector that reports the confirmation kind."""
    from pawnlogic.confirm_selector import ConfirmOperationSelector
    from core.operation_policy import OperationAction, OperationDecision, RiskLevel

    decision = OperationDecision(
        action=OperationAction.CONFIRM,
        risk=RiskLevel.HIGH,
        reason="status line test",
        matched_rule="test",
        redacted_command="rm -rf /",
    )
    return ConfirmOperationSelector(decision)


def test_status_line_shows_running_with_elapsed_seconds(monkeypatch):
    """While a Turn is in flight the status line must show
    ``⏱ Ns · Esc to interrupt`` and the seconds counter
    must advance as wall-clock time passes.

    The previous 0.3.7 contract printed a status line from inside
    ``session.run_turn`` (the readline path).  In the live path the
    print landed in the output area but only at the start of the
    turn, and the user could not tell whether the model was still
    working.  The new contract puts a persistent line at the top
    of the composer that the 250 ms ticker keeps truthful.

    The status deliberately carries no model alias.  The toolbar's
    ``Model:`` field is never dropped from the field row, so a prefix
    here duplicated it -- and on a real alias that duplicate cost enough
    width to clip the field row mid-value at 80 columns.
    """
    from pawnlogic.live_terminal import PersistentTerminal

    started = time.monotonic() - 12.0
    session = _session(pending=1, started_at=started)
    monkeypatch.setattr(
        "prompt_toolkit.application.current.get_app",
        lambda: _fake_app(columns=120),
    )

    # We construct only the render path to avoid spinning up a real
    # Application. ``PersistentTerminal`` exposes the renderer as a
    # bound method once the app is built, so we call the same
    # callable the layout would invoke.
    terminal = PersistentTerminal.__new__(PersistentTerminal)
    terminal._session = session  # type: ignore[attr-defined]
    terminal._build_status = PersistentTerminal._build_status  # type: ignore[attr-defined]
    rendered = terminal._build_status(terminal)  # type: ignore[arg-type]

    plain = rendered.replace("<b>", "").replace("</b>", "")
    assert "bai:glm-5.3-flash" not in plain, "the Model: field already says this"
    assert "Esc to interrupt" in plain
    # The elapsed counter must be at least 10s (started 12s ago);
    # we allow a small slop for the test runtime.
    import re

    seconds = int(re.search(r"⏱\s*(\d+)s", plain).group(1))
    assert 10 <= seconds <= 20, plain


def test_status_line_recovers_to_idle_after_interrupt(monkeypatch):
    """When the user presses Esc and the Turn settles, the status
    line must briefly read ``⏸ interrupted by user`` for 1.5 s and
    then return to ``Idle``.  The previous 0.3.7 contract left the
    status frozen on whatever the last render saw, so the user had
    to press Esc a second time to confirm cancellation.
    """
    from pawnlogic.live_terminal import PersistentTerminal

    now = time.monotonic()
    session = _session(
        pending=0,
        status="idle",
        started_at=now,
    )
    session._last_interrupt_at = now - 0.5
    session._last_interrupt_kind = "user"
    monkeypatch.setattr(
        "prompt_toolkit.application.current.get_app",
        lambda: _fake_app(columns=120),
    )

    terminal = PersistentTerminal.__new__(PersistentTerminal)
    terminal._session = session  # type: ignore[attr-defined]
    rendered = PersistentTerminal._build_status(terminal)  # type: ignore[arg-type]
    plain = rendered.replace("<b>", "").replace("</b>", "")
    assert "interrupted by user" in plain, plain

    # After 2 s the interrupt marker should be gone and the status
    # should fold nothing: idle returns "" so the toolbar's own fields
    # carry the model.  (It used to return "[model]  Idle" and the
    # toolbar suppressed it with a ``"Idle" not in status`` substring
    # test -- which also silently swallowed the recovered-draft state,
    # whose text contains the word "Idle".)
    session._last_interrupt_at = now - 2.0
    rendered = PersistentTerminal._build_status(terminal)  # type: ignore[arg-type]
    plain = rendered.replace("<b>", "").replace("</b>", "")
    assert plain == ""
    assert "interrupted" not in plain


def test_status_line_does_not_show_queue_counters(monkeypatch):
    """The 0.3.7 toolbar displayed ``steer:N · follow-up:N`` and
    ``+N parked`` next to the queue label.  The 0.3.7 patch hides
    all queue counters from the user; the status line must only
    carry model + elapsed + state.
    """
    from pawnlogic.live_terminal import PersistentTerminal

    started = time.monotonic() - 5.0
    session = _session(pending=1, started_at=started)
    monkeypatch.setattr(
        "prompt_toolkit.application.current.get_app",
        lambda: _fake_app(columns=160),
    )

    terminal = PersistentTerminal.__new__(PersistentTerminal)
    terminal._session = session  # type: ignore[attr-defined]
    rendered = PersistentTerminal._build_status(terminal)  # type: ignore[arg-type]
    plain = rendered.replace("<b>", "").replace("</b>", "")
    assert "steer:" not in plain
    assert "follow-up:" not in plain
    assert "parked" not in plain
    assert "+1" not in plain and "+2" not in plain and "+3" not in plain


def test_toolbar_folds_running_status_and_tool_activity(monkeypatch):
    """Regression (owner-reported): the status line used to be its own row
    at the TOP of the app block, so every host flush left a stale copy in
    the permanent scrollback. It must render inside the fixed toolbar row
    instead, including the current tool activity."""
    from types import SimpleNamespace

    from pawnlogic.live_terminal import PersistentTerminal

    session = SimpleNamespace(
        model_alias="bai:glm-5.3-flash",
        _last_interrupt_at=None,
        _turn_start_time=time.monotonic() - 31.0,
        _current_tool_activity="list_dir [2/30]",
        queue_status=lambda: {"pending_count": 1},
    )
    terminal = PersistentTerminal.__new__(PersistentTerminal)
    terminal._session = session  # type: ignore[attr-defined]
    terminal._toolbar_text = lambda: " Model: bai:glm-5.3-flash  Ctx: 17%"  # type: ignore[attr-defined]
    terminal._build_status = lambda: PersistentTerminal._build_status(terminal)  # type: ignore[attr-defined]
    terminal._clip_line = PersistentTerminal._clip_line  # type: ignore[attr-defined]
    # Pin the width: a lingering PT app from another test must not shrink it.
    monkeypatch.setattr(
        "prompt_toolkit.application.current.get_app",
        lambda: _fake_app(columns=200),
    )

    rendered = terminal._render_toolbar()  # type: ignore[arg-type]

    assert "Esc to interrupt" in rendered
    assert "⏱ 31s" in rendered
    assert "list_dir [2/30]" in rendered
    assert "<b>" not in rendered  # plain text, no stray HTML markup


def test_toolbar_stays_clean_while_idle(monkeypatch):
    """Idle state must not append a redundant status segment to the toolbar."""
    from types import SimpleNamespace

    from pawnlogic.live_terminal import PersistentTerminal

    session = SimpleNamespace(
        model_alias="bai:glm-5.3-flash",
        _last_interrupt_at=None,
        _turn_start_time=0.0,
        _current_tool_activity=None,
        queue_status=lambda: {"pending_count": 0},
    )
    terminal = PersistentTerminal.__new__(PersistentTerminal)
    terminal._session = session  # type: ignore[attr-defined]
    terminal._toolbar_text = lambda: " Model: bai:glm-5.3-flash  Ctx: 17%"  # type: ignore[attr-defined]
    terminal._build_status = lambda: PersistentTerminal._build_status(terminal)  # type: ignore[attr-defined]
    terminal._clip_line = PersistentTerminal._clip_line  # type: ignore[attr-defined]

    monkeypatch.setattr(
        "prompt_toolkit.application.current.get_app",
        lambda: _fake_app(columns=200),
    )

    rendered = terminal._render_toolbar()  # type: ignore[arg-type]

    assert "Idle" not in rendered
    assert "Esc to interrupt" not in rendered


def test_status_line_shows_pending_confirmation(monkeypatch):
    """A mounted high-risk modal must be visible in the status line.

    0.3.12 S3/D3: while a confirmation modal owns the keyboard, the
    toolbar used to keep reporting the ordinary in-flight state (or
    ``Idle``), so a user could not tell that a tool was blocked on a
    prompt. Every keystroke they typed was being consumed by the modal.
    """
    from pawnlogic.live_terminal import PersistentTerminal
    from pawnlogic.selectors import SelectorRegistry

    session = _session(pending=1, started_at=time.monotonic() - 3.0)
    registry = SelectorRegistry()
    registry.install_active(_MountedConfirmation(), _Future())

    terminal = PersistentTerminal.__new__(PersistentTerminal)
    terminal._session = session  # type: ignore[attr-defined]
    terminal._selector_registry = registry  # type: ignore[attr-defined]
    terminal._build_status = PersistentTerminal._build_status  # type: ignore[attr-defined]

    rendered = terminal._build_status(terminal)  # type: ignore[arg-type]
    plain = rendered.replace("<b>", "").replace("</b>", "")

    assert "awaiting confirmation" in plain, plain
    assert "Esc to review" in plain, plain


def test_status_line_drops_confirmation_state_once_the_modal_closes(
    monkeypatch,
):
    """A resolved or torn-down modal must not leave the banner up."""
    from pawnlogic.live_terminal import PersistentTerminal
    from pawnlogic.selectors import SelectorRegistry

    session = _session(pending=0)
    registry = SelectorRegistry()
    selector = _MountedConfirmation()
    selector.close(result=False)
    registry.install_active(selector, _Future())

    terminal = PersistentTerminal.__new__(PersistentTerminal)
    terminal._session = session  # type: ignore[attr-defined]
    terminal._selector_registry = registry  # type: ignore[attr-defined]
    terminal._build_status = PersistentTerminal._build_status  # type: ignore[attr-defined]

    rendered = terminal._build_status(terminal)  # type: ignore[arg-type]
    assert "awaiting confirmation" not in rendered


def test_selector_escape_binding_outranks_the_turn_interrupt(monkeypatch):
    """Esc must reach the modal before it escalates to a Turn interrupt.

    The confirmation modal owns the keyboard while it is mounted, so the
    live terminal registers its selector keys with ``eager=True`` while
    the Turn-interrupt Esc in ``live_repl`` is a normal binding. Prompt
    Toolkit runs eager handlers first regardless of registration order;
    this pins that the split has not been reversed.
    """
    import inspect

    from pawnlogic import live_repl, live_terminal

    terminal_src = inspect.getsource(live_terminal)
    assert 'add("escape", filter=Condition(lambda: self._selector_registry.has_state), eager=True)' in terminal_src, (
        "the selector escape binding must stay eager"
    )
    repl_src = inspect.getsource(live_repl)
    assert 'bindings.add("escape")' in repl_src
    interrupt_block = repl_src.split('bindings.add("escape")', 1)[1][:400]
    assert "eager=True" not in interrupt_block, (
        "the Turn-interrupt Esc must not become eager and steal the modal"
    )


def _toolbar_terminal(session: SimpleNamespace, field_text: str) -> object:
    """A terminal wired for ``_render_toolbar`` without a real Application."""
    from pawnlogic.live_terminal import PersistentTerminal

    terminal = PersistentTerminal.__new__(PersistentTerminal)
    terminal._session = session  # type: ignore[attr-defined]
    terminal._toolbar_text = lambda: field_text  # type: ignore[attr-defined]
    terminal._build_status = lambda: PersistentTerminal._build_status(terminal)  # type: ignore[attr-defined]
    terminal._clip_line = PersistentTerminal._clip_line  # type: ignore[attr-defined]
    return terminal


def test_status_line_reports_sent_before_first_delta(monkeypatch):
    """After admission but before any delta, the row must say the request is out.

    Nothing else is true in this window: ``_current_tool_activity`` is empty
    until a tool runs, and ``_turn_start_time`` is stamped late inside
    ``_prepare_turn`` (after system-prompt resets and a possible blocking
    summary call).  Without an explicit state the row read as a frozen
    ``⏱ 0s``, which is indistinguishable from a request that never left.
    """
    from pawnlogic.live_terminal import PersistentTerminal

    now = time.monotonic()
    session = _session(pending=1, submitted_at=now - 3.0)
    terminal = PersistentTerminal.__new__(PersistentTerminal)
    terminal._session = session  # type: ignore[attr-defined]

    plain = PersistentTerminal._build_status(terminal)  # type: ignore[attr-type]

    assert "Sent" in plain, plain
    assert "Esc to interrupt" in plain, plain
    assert "⏱ 3s" in plain, plain


def test_status_line_reports_thinking_after_first_delta(monkeypatch):
    """Once a delta lands, the state advances from Sent to Thinking."""
    from pawnlogic.live_terminal import PersistentTerminal

    now = time.monotonic()
    session = _session(pending=1, submitted_at=now - 7.0, first_delta=True)
    terminal = PersistentTerminal.__new__(PersistentTerminal)
    terminal._session = session  # type: ignore[attr-defined]

    plain = PersistentTerminal._build_status(terminal)  # type: ignore[arg-type]

    assert "Thinking" in plain, plain
    assert "Sent" not in plain, plain
    assert "⏱ 7s" in plain, plain


def test_status_line_keeps_tool_activity_format(monkeypatch):
    """A running tool keeps the 0.3.13 ``⏱ Ns · <tool> [n/m]`` wording."""
    from pawnlogic.live_terminal import PersistentTerminal

    now = time.monotonic()
    session = _session(
        pending=1,
        submitted_at=now - 31.0,
        first_delta=True,
        activity="list_dir [2/30]",
    )
    terminal = PersistentTerminal.__new__(PersistentTerminal)
    terminal._session = session  # type: ignore[attr-defined]

    plain = PersistentTerminal._build_status(terminal)  # type: ignore[arg-type]

    assert "⏱ 31s" in plain, plain
    assert "list_dir [2/30]" in plain, plain
    assert "Esc to interrupt" in plain, plain
    # The tool name is more informative than the generic state words.
    assert "Thinking" not in plain, plain


def test_status_timer_counts_from_admission_not_prepare_turn(monkeypatch):
    """Elapsed time must come from admission, not from ``_turn_start_time``.

    ``_turn_start_time`` is stamped late inside ``_prepare_turn``. Counting
    from it left the counter pinned at 0s for the whole pre-request window,
    which is the window the Sent state exists to cover.
    """
    from pawnlogic.live_terminal import PersistentTerminal

    now = time.monotonic()
    session = _session(
        pending=1,
        submitted_at=now - 12.0,
        started_at=now,  # _prepare_turn has not reached it yet
    )
    terminal = PersistentTerminal.__new__(PersistentTerminal)
    terminal._session = session  # type: ignore[attr-defined]

    plain = PersistentTerminal._build_status(terminal)  # type: ignore[arg-type]

    assert "⏱ 12s" in plain, plain
    assert "⏱ 0s" not in plain, plain


def test_status_falls_back_to_turn_start_time_when_not_submitted(monkeypatch):
    """A session without an admission stamp still ticks off ``_turn_start_time``."""
    from pawnlogic.live_terminal import PersistentTerminal

    now = time.monotonic()
    session = _session(pending=1, submitted_at=None, started_at=now - 5.0)
    terminal = PersistentTerminal.__new__(PersistentTerminal)
    terminal._session = session  # type: ignore[attr-defined]

    plain = PersistentTerminal._build_status(terminal)  # type: ignore[arg-type]

    assert "⏱ 5s" in plain, plain


def test_recovered_draft_hint_reaches_the_rendered_row(monkeypatch):
    """The recovered-draft hint must actually render.

    ``_build_status`` has always returned this text and three places in the
    docs claim the user sees it, but the toolbar suppressed it with a
    ``"Idle" not in status`` substring test -- and this state is the one
    string that contains the word "Idle".  It has never been displayed.
    """
    now = time.monotonic()
    session = _session(pending=0)
    terminal = _toolbar_terminal(session, " Model: bai:glm-5.3-flash  Ctx: 17%")
    terminal._last_recovery_at = now  # type: ignore[attr-defined]
    terminal._draft_is_recovery = True  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "prompt_toolkit.application.current.get_app",
        lambda: _fake_app(columns=200),
    )

    rendered = terminal._render_toolbar()  # type: ignore[attr-type]

    assert "edit the draft and press Enter" in rendered, rendered
    assert "interrupted" not in rendered


def _assert_no_mid_field_clip(rendered: str, fields: str) -> None:
    """The field portion must be a whole-segment prefix, never a partial one.

    ``build_bottom_toolbar`` joins fields with a double space, so a field row
    that was cut on a boundary still shows only complete ``Label: value``
    pairs. A cut anywhere else is the mid-field clipping the Known Risks
    entry forbids. When the status claims the whole row there is no field
    portion and nothing to check.
    """
    if "  ·  " not in rendered:
        return
    head = rendered.split("  ·  ", 1)[0]
    assert fields.startswith(head), (head, fields)
    remainder = fields[len(head):]
    assert remainder == "" or remainder.startswith("  "), (head, fields)


def test_running_status_survives_a_narrow_terminal(monkeypatch):
    """Regression: the status was the first thing a narrow row threw away.

    The toolbar used to compose fields + status and clip the joined row, so
    on an 80-column terminal the status -- the only part that changes per
    render -- was cut first, exactly during the seconds a waiting user needs
    it.  The status is now reserved before the fields.
    """
    session = _session(
        pending=1,
        submitted_at=time.monotonic() - 31.0,
        first_delta=True,
        activity="list_dir [2/30]",
    )
    fields = " Model: bai:glm-5.3-flash  Ctx: 17%  Effort: xhigh  Tk: 0  Dir: /tmp/x"

    for columns in (60, 80, 100, 120):
        terminal = _toolbar_terminal(session, fields)
        monkeypatch.setattr(
            "prompt_toolkit.application.current.get_app",
            lambda c=columns: _fake_app(columns=c),
        )
        rendered = terminal._render_toolbar()  # type: ignore[attr-type]
        assert len(rendered) <= columns, (columns, len(rendered))
        # The state word sits at the head of the status, so it survives
        # every tail cut.
        assert "⏱ 31s" in rendered, (columns, rendered)
        assert "<b>" not in rendered, rendered
        # And what is left of the fields is still whole fields.
        _assert_no_mid_field_clip(rendered, fields)


def test_sent_status_survives_a_narrow_terminal(monkeypatch):
    """The new Sent state must survive the same widths as the tool state."""
    session = _session(pending=1, submitted_at=time.monotonic() - 2.0)
    fields = " Model: bai:glm-5.3-flash  Ctx: 17%  Effort: xhigh  Tk: 0"

    for columns in (60, 80, 100, 120):
        terminal = _toolbar_terminal(session, fields)
        monkeypatch.setattr(
            "prompt_toolkit.application.current.get_app",
            lambda c=columns: _fake_app(columns=c),
        )
        rendered = terminal._render_toolbar()  # type: ignore[attr-type]
        assert len(rendered) <= columns, (columns, len(rendered))
        assert "Sent" in rendered, (columns, rendered)


def test_fields_return_once_the_turn_settles(monkeypatch):
    """Reserving width for the status must not permanently cost the fields."""
    session = _session(pending=0)
    terminal = _toolbar_terminal(session, " Model: bai:glm-5.3-flash  Ctx: 17%")
    monkeypatch.setattr(
        "prompt_toolkit.application.current.get_app",
        lambda: _fake_app(columns=80),
    )

    rendered = terminal._render_toolbar()  # type: ignore[attr-type]

    assert "Model: bai:glm-5.3-flash" in rendered, rendered
    assert "Ctx: 17%" in rendered, rendered
    assert "Esc to interrupt" not in rendered
