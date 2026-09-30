"""
System / runtime / config slash commands.

Migrated verbatim from main.py's _legacy_slash_dispatch in stage-1 step 2.
Functional behavior is preserved exactly — only the surrounding plumbing
changed (each command is now an independent async function dispatched via
the registry instead of an elif branch in a 933-line if/elif chain).

Commands in this module:
  /help                   show help text
  /exit /quit /q          leave the REPL (returns EXIT_SENTINEL)
  /clear                  clear context, keep pinned messages
  /context                show context utilization bar
  /history                list current message buffer
  /ping                   send a tiny request to test API + warm cache
  /state                  print State.md of the current cwd
  /stats                  show token / tool-call usage for the session
  /time [N]               show or set per-turn time budget (seconds)
  /failures [list|clear|N]  inspect / clear the failure audit log

  /effort [level|status]           select the reasoning-effort level
  /low /mid /deep /max /ultra /normal    legacy aliases for effort levels
  /limits                          show current dynamic config
  /tokens [N]    set max_tokens
  /ctx [N]       set ctx_max_chars
  /iter [N]      set max_iter
  /toolsize [N]  set tool_max_chars
  /fetchsize [N] set fetch_max_chars
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from config import (
    DEFAULT_EFFORT_LEVEL, EFFORT_LEVELS,
    effort_preset, effort_options, effort_delivery, is_effort_level,
)
from core.api_client import stream_request
from core.memory import list_failures, clear_failures
from core.session import _ctx_chars, STATE_FILENAME
from core.state import (
    state as _runtime_state,
    get_dynamic_config_value,
    runtime_config,
    set_dynamic_config_value,
    update_dynamic_config,
)
from utils.ansi import (
    c, BOLD, GRAY, CYAN, GREEN, YELLOW, RED,
)

from core.commands import CommandContext, register
from core.commands._common import EXIT_SENTINEL, fmt_config, sink_print as _print


# ════════════════════════════════════════════════════════
# Help & Exit
# ════════════════════════════════════════════════════════

@register("/help")
async def cmd_help(ctx: CommandContext) -> None:
    # HELP_TEXT lives in the CLI module because it embeds VERSION; lazy import
    # avoids a circular dependency at module load time.
    from pawnlogic.cli import HELP_TEXT
    _print(HELP_TEXT)


@register("/exit", "/quit", "/q")
async def cmd_exit(ctx: CommandContext) -> str:
    return EXIT_SENTINEL


# ════════════════════════════════════════════════════════
# Context window
# ════════════════════════════════════════════════════════

@register("/clear")
async def cmd_clear(ctx: CommandContext) -> None:
    session = ctx.session
    pinned = [m for m in session.messages if m.get("_pinned")]
    session.messages.clear()
    session._reset_system_prompt()
    session.messages.extend(pinned)
    state_exists = (Path(session.cwd) / STATE_FILENAME).exists()
    state_note = c(GREEN, "  (State.md will be injected on the next turn)") if state_exists else ""
    _print(c(GREEN, f"  ✓ Cleared context; kept {len(pinned)} pinned messages.{state_note}"))


@register("/context")
async def cmd_context(ctx: CommandContext) -> None:
    session = ctx.session
    msgs = session.messages
    chars = _ctx_chars(msgs)
    pct = chars / runtime_config()["ctx_max_chars"] * 100
    tok = chars // 4
    pinned = sum(1 for m in msgs if m.get("_pinned"))
    filled = int(min(pct, 100) / 100 * 30)
    bcol = RED if pct > 80 else (YELLOW if pct > 50 else GREEN)
    bar = c(bcol, "█" * filled) + c(GRAY, "░" * (30 - filled))
    warn = c(YELLOW, "  ⚠ Above 80%; consider /clear") if pct > 80 else ""
    _print(
        f"\n  {c(BOLD, 'Context')}  {len(msgs)} messages  Pin:{c(GREEN, str(pinned))}"
        f"  ~{tok:,} tokens\n  [{bar}] {pct:.1f}%  {warn}\n"
    )


@register("/history")
async def cmd_history(ctx: CommandContext) -> None:
    session = ctx.session
    _print(c(CYAN, f"\n  {len(session.messages)} messages (indices exclude system messages):"))
    seq = 0
    for m in session.messages:
        role = m.get("role", "?")
        content = str(m.get("content") or "")[:65].replace("\n", " ")
        pin_tag = c(GREEN, " 📌") if m.get("_pinned") else "   "
        if role == "system":
            _print(c(GRAY, f"  [{'sys':9}]     {content[:50]}"))
        else:
            _print(c(GRAY, f"  [{role:9}]") + c(CYAN, f"[{seq:3d}]") + pin_tag + f" {content}")
            seq += 1


# ════════════════════════════════════════════════════════
# Connectivity / introspection
# ════════════════════════════════════════════════════════

@register("/ping")
async def cmd_ping(ctx: CommandContext) -> None:
    session = ctx.session
    _ping_msgs = [
        {"role": "system", "content": "respond with 'pong' only."},
        {"role": "user", "content": "ping"},
    ]
    _ping_buf = ""
    _print(c(CYAN, "  🏓 ping..."), end="", flush=True)
    try:
        for delta in stream_request(
            _ping_msgs, session.model_alias,
            max_tokens=16, tools_schema=None,
        ):
            if "_error" in delta:
                _print(c(RED, f" ✗ {delta['_error']}"))
                break
            choices = delta.get("choices") or []
            if not choices:
                continue
            chunk = choices[0].get("delta", {}).get("content", "")
            _ping_buf += chunk
        if _ping_buf:
            _print(c(GREEN, f" {_ping_buf.strip()} ✓"))
        else:
            _print(c(GREEN, " pong ✓"))
    except Exception as e:
        _print(c(RED, f" ✗ {e}"))


@register("/state")
async def cmd_state(ctx: CommandContext) -> None:
    session = ctx.session
    p = Path(session.cwd) / STATE_FILENAME
    if p.exists():
        _print(c(BOLD, f"\n  {p}："))
        _print(p.read_text(encoding="utf-8"))
    else:
        _print(c(GRAY, f"  Current directory has no {STATE_FILENAME}. Create one with /init_project."))


@register("/stats")
async def cmd_stats(ctx: CommandContext) -> None:
    session = ctx.session
    snapshot_reader = getattr(session, "_runtime_metrics_snapshot", None)
    snapshot = snapshot_reader() if callable(snapshot_reader) else None
    pt = snapshot.total_prompt_tokens if snapshot else session.total_prompt_tokens
    ct = snapshot.total_completion_tokens if snapshot else session.total_completion_tokens
    tt = snapshot.total_tool_calls if snapshot else session.total_tool_calls
    tot = pt + ct
    est_usd = tot / 1_000_000 * 1.50
    if tot + tt == 0:
        _print(c(GRAY, "  (No API calls recorded in this session.)"))
    elif _runtime_state.user_mode:
        _print(c(GRAY, f"  stats: ↑{pt:,} ↓{ct:,} total={tot:,} tools={tt} ~${est_usd:.4f}"))
    else:
        _print(c(BOLD, "\n  ╔══ Session Usage Audit ═════════════════════╗"))
        _print(f"  ║  Prompt tokens    : {c(CYAN, f'{pt:>10,}')}               ║")
        _print(f"  ║  Completion tokens: {c(CYAN, f'{ct:>10,}')}               ║")
        _print(f"  ║  Total tokens     : {c(YELLOW, f'{tot:>10,}')}               ║")
        _print(f"  ║  Tool calls       : {c(GREEN, f'{tt:>10,}')}               ║")
        _print(f"  ║  Est. cost        : {c(GRAY, f'~${est_usd:.4f} USD'):>18}         ║")
        _print(c(BOLD,  "  ╚══════════════════════════════════════════════╝"))
        _print(c(GRAY, "  (Cost estimate uses a $1.50/1M tokens average; informational only.)"))


@register("/time")
async def cmd_time(ctx: CommandContext) -> None:
    session = ctx.session
    arg = ctx.arg
    budget = get_dynamic_config_value("time_budget_sec", 0)
    if arg and arg.strip().isdigit():
        new_budget = max(0, int(arg.strip()))
        set_dynamic_config_value("time_budget_sec", new_budget)
        session._time_budget_sec = new_budget
        session._reset_system_prompt()
        if new_budget > 0:
            m, s = divmod(new_budget, 60)
            _print(c(GREEN, f"  ✓ Time budget set to {m}m{s}s"))
        else:
            _print(c(GREEN, "  ✓ Time budget disabled."))
    else:
        if budget > 0:
            m, s = divmod(budget, 60)
            elapsed = time.monotonic() - session._turn_start_time if session._turn_start_time else 0
            remaining = max(0, budget - elapsed)
            rm, rs = divmod(int(remaining), 60)
            mode = c(RED, " [URGENT]") if session._urgent_mode else ""
            _print(c(BOLD, "\n  ⏱  Time budget:"))
            _print(f"  Budget   : {c(CYAN, f'{m}m{s}s')}")
            _print(f"  Elapsed  : {c(YELLOW, f'{int(elapsed)}s')}")
            _print(f"  Remaining: {c(GREEN if remaining > 30 else RED, f'{rm}m{rs}s')}{mode}")
            _print(c(GRAY, "\n  /time <seconds> to change | /time 0 to disable"))
        else:
            _print(c(GRAY, "  No time budget is set."))
            _print(c(GRAY, "  /time <seconds> to set | example: /time 300 = 5 minutes"))


@register("/failures")
async def cmd_failures(ctx: CommandContext) -> None:
    arg = ctx.arg
    sub = arg.lower().strip() if arg else "list"
    if sub == "clear":
        n = clear_failures()
        _print(c(GREEN, f"  ✓ Cleared {n} failure records"))
    elif sub == "list" or sub.isdigit():
        n = int(sub) if sub.isdigit() else 20
        rows = list_failures(n)
        if not rows:
            _print(c(GREEN, "  ✓ No failure records; defensive audit database is empty."))
        else:
            _print(c(BOLD, f"\n  Failure records (latest {len(rows)}):"))
            for i, r in enumerate(rows):
                etype = r["error_type"] or "?"
                ts = r["created_at"][:16] if r["created_at"] else ""
                tool = r["tool_name"]
                msg = r["error_msg"][:80].replace("\n", " ")
                _print(
                    c(GRAY, f"  [{i+1:2d}] ")
                    + c(RED, f"{tool:20}")
                    + c(YELLOW, f" {etype:15}")
                    + c(GRAY, f" {ts}")
                )
                _print(c(GRAY, f"       {msg}"))
    else:
        _print(c(GRAY, "  Usage: /failures [list|clear|N]"))


# ════════════════════════════════════════════════════════
# Reasoning effort
# ════════════════════════════════════════════════════════

def _effort_options(model_alias: str) -> tuple[tuple[str, str, str], ...]:
    """Build the selector rows for one model."""
    from core.api_payloads import model_effort_map

    return effort_options(model_effort_map(model_alias))


def _effort_delivery(model_alias: str, level: str) -> str:
    """Describe where the active level is actually applied."""
    from core.api_payloads import model_effort_map

    return effort_delivery(model_effort_map(model_alias), model_alias, level)


def apply_effort(ctx: CommandContext, level: str) -> bool:
    """Apply one effort level.  Return whether it was applied.

    Single write path for every entry point, so the live selector, ``/effort``
    and the legacy tier aliases cannot drift apart.

    The explicit ``preferred_worker`` is carried across deliberately.  The tier
    presets all pin it to ``"auto"``, so a blanket preset write silently undid
    a ``/worker <alias>`` lock — and because the ``/worker`` menu reads the
    on-disk policy first, the menu then disagreed with what delegation
    actually used.
    """
    if not is_effort_level(level):
        _print(c(RED, f"  ✗ Unknown effort level: {level}"))
        _print(c(GRAY, f"  Levels: {' / '.join(EFFORT_LEVELS)}"))
        return False
    preset = effort_preset(level)
    current_worker = get_dynamic_config_value("preferred_worker", "auto")
    update_dynamic_config({**preset, "preferred_worker": current_worker})
    ctx.session._reset_system_prompt()
    _print(c(
        GREEN,
        f"  ✓ effort={level}: "
        f"tokens={preset['max_tokens']:,}, "
        f"ctx={preset['ctx_max_chars']:,}, "
        f"iter={preset['max_iter']}",
    ))
    model_alias = getattr(ctx.session, "model_alias", "")
    _print(c(GRAY, f"    {_effort_delivery(model_alias, level)}"))
    _print(fmt_config())
    return True


def _effort_alias(ctx: CommandContext, legacy: str, level: str) -> None:
    """Apply a legacy tier command as an effort level, with a migration note."""
    _print(c(GRAY,
        f"  {legacy} is now an effort alias. Current level: {level}"))
    _print(c(GRAY, "  → pick a level inside /model, or set it directly with /effort"))
    apply_effort(ctx, level)


@register("/effort")
async def cmd_effort(ctx: CommandContext) -> None:
    """Show, select, or switch the reasoning-effort level."""
    current = str(runtime_config().get("effort_level") or DEFAULT_EFFORT_LEVEL)
    model_alias = getattr(ctx.session, "model_alias", "")
    arg = (ctx.arg or "").strip().lower()
    if arg == "status":
        _print(c(GRAY, f"  Current: effort={current}  ({_effort_delivery(model_alias, current)})"))
        return
    if arg:
        apply_effort(ctx, arg)
        return

    from core.output import JsonSink

    if isinstance(ctx.sink, JsonSink) or not _effort_tui_available():
        _print(c(
            GRAY,
            "  Interactive effort selector is unavailable; "
            f"current={current}. Use /effort <level>.",
        ))
        return
    try:
        controller = getattr(ctx, "terminal_controller", None)
        if controller is not None and getattr(controller, "run_selector", None) is not None:
            from pawnlogic.selectors import EffortSelector

            selected = await controller.run_selector(
                lambda: EffortSelector(current, model_alias)
            )
        else:
            selected = await _select_effort_level(current, model_alias)
    except (EOFError, KeyboardInterrupt):
        selected = None
    except Exception:
        _print(c(
            YELLOW,
            "  Interactive effort selector is unavailable; "
            f"current={current}. Use /effort <level>.",
        ))
        return
    if selected is None:
        _print(c(GRAY, f"  Effort unchanged ({current})."))
        return
    apply_effort(ctx, selected)


@register("/low")
async def cmd_low(ctx: CommandContext) -> None:
    _effort_alias(ctx, "/low", "low")


@register("/mid")
async def cmd_mid(ctx: CommandContext) -> None:
    _effort_alias(ctx, "/mid", "medium")


@register("/deep")
async def cmd_deep(ctx: CommandContext) -> None:
    _effort_alias(ctx, "/deep", "high")


@register("/max")
async def cmd_max(ctx: CommandContext) -> None:
    _effort_alias(ctx, "/max", "xhigh")


@register("/ultra")
async def cmd_ultra(ctx: CommandContext) -> None:
    _effort_alias(ctx, "/ultra", "max")


@register("/normal")
async def cmd_normal(ctx: CommandContext) -> None:
    _effort_alias(ctx, "/normal", "medium")


@register("/limits")
async def cmd_limits(ctx: CommandContext) -> None:
    _print(c(BOLD, "\n  Current runtime limits:"))
    _print(fmt_config())
    level = str(runtime_config().get("effort_level") or DEFAULT_EFFORT_LEVEL)
    _print(c(
        GRAY,
        f"  effort={level}  ({_effort_delivery(getattr(ctx.session, 'model_alias', ''), level)})",
    ))
    _print(c(GRAY, "  /effort [level]  |  /tokens /ctx /iter /toolsize /fetchsize"))


# ════════════════════════════════════════════════════════
# Fine-grained tunables
# ════════════════════════════════════════════════════════

@register("/tokens")
async def cmd_tokens(ctx: CommandContext) -> None:
    arg = ctx.arg
    if not arg:
        _print(c(GRAY, f"  Current: {runtime_config()['max_tokens']}  /tokens <n>"))
        return
    try:
        n = max(256, min(65536, int(arg)))
        set_dynamic_config_value("max_tokens", n)
        ctx.session._reset_system_prompt()
        _print(c(GREEN, f"  ✓ max_tokens={n}"))
    except ValueError:
        _print(c(RED, "  ✗ Invalid number"))


@register("/ctx")
async def cmd_ctx(ctx: CommandContext) -> None:
    arg = ctx.arg
    if not arg:
        _print(c(GRAY, f"  Current: {runtime_config()['ctx_max_chars']}  /ctx <n>"))
        return
    try:
        n = max(10_000, int(arg))
        set_dynamic_config_value("ctx_max_chars", n)
        set_dynamic_config_value("ctx_trim_to", int(n * .75))
        ctx.session._reset_system_prompt()
        _print(c(GREEN, f"  ✓ ctx_max_chars={n}"))
    except ValueError:
        _print(c(RED, "  ✗ Invalid number"))


@register("/iter")
async def cmd_iter(ctx: CommandContext) -> None:
    arg = ctx.arg
    if not arg:
        _print(c(GRAY, f"  Current: {runtime_config()['max_iter']}  /iter <n>"))
        return
    try:
        n = max(1, int(arg))
        set_dynamic_config_value("max_iter", n)
        _print(c(GREEN, f"  ✓ max_iter={n}"))
    except ValueError:
        _print(c(RED, "  ✗ Invalid number"))


@register("/toolsize")
async def cmd_toolsize(ctx: CommandContext) -> None:
    arg = ctx.arg
    if not arg:
        _print(c(GRAY, f"  Current: {runtime_config()['tool_max_chars']}"))
        return
    try:
        set_dynamic_config_value("tool_max_chars", max(1000, int(arg)))
        _print(c(GREEN, f"  ✓ tool_max_chars={runtime_config()['tool_max_chars']}"))
    except ValueError:
        _print(c(RED, "  ✗ Invalid number"))


@register("/planguard")
async def cmd_planguard(ctx: CommandContext) -> None:
    """Show, select, or switch CoT plan-guard enforcement."""
    current = str(runtime_config().get("plan_guard_mode", "advisory"))
    arg = (ctx.arg or "").strip().lower()
    if not arg:
        from core.output import JsonSink

        if isinstance(ctx.sink, JsonSink) or not _plan_guard_tui_available():
            _print(c(
                GRAY,
                "  Interactive plan-guard selector is unavailable; "
                f"current={current}. Use /planguard strict|advisory|status.",
            ))
            return
        try:
            controller = getattr(ctx, "terminal_controller", None)
            if controller is not None and getattr(controller, "run_selector", None) is not None:
                from pawnlogic.selectors import PlanGuardSelector

                selected = await controller.run_selector(
                    lambda: PlanGuardSelector(current)
                )
            else:
                selected = await _select_plan_guard_mode(current)
        except (EOFError, KeyboardInterrupt):
            selected = None
        except Exception:
            _print(c(
                YELLOW,
                "  Interactive plan-guard selector is unavailable; "
                f"current={current}. Use /planguard strict|advisory|status.",
            ))
            return
        if selected is None:
            _print(c(GRAY, f"  Plan-guard mode unchanged ({current})."))
            return
        set_dynamic_config_value("plan_guard_mode", selected)
        _print(c(GREEN, f"  ✓ plan_guard_mode={selected} (was {current})"))
        return
    if arg == "status":
        _print(c(GRAY, f"  Current: plan_guard_mode={current}"))
        return
    if arg not in ("strict", "advisory"):
        _print(c(RED, "  ✗ Usage: /planguard [strict|advisory|status]"))
        return
    set_dynamic_config_value("plan_guard_mode", arg)
    _print(c(GREEN, f"  ✓ plan_guard_mode={arg} (was {current})"))


def _effort_tui_available() -> bool:
    """Return whether the interactive effort selector can run safely."""
    disabled = os.getenv("PROMPT_TOOLKIT_ENABLED", "1").lower() in ("0", "false")
    return not disabled and sys.stdin.isatty() and sys.stdout.isatty()


async def _select_effort_level(current: str, model_alias: str) -> str | None:
    """Show a prompt_toolkit effort selector and return the chosen level."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    options = _effort_options(model_alias)
    selected_idx = next(
        (index for index, (level, _, _) in enumerate(options) if level == current),
        0,
    )

    def get_fragments():
        fragments = [
            ("class:title", "\n  Reasoning Effort\n"),
            ("class:desc", "  How hard the model thinks, and how much room it gets.\n\n"),
        ]
        for index, (level, label, description) in enumerate(options):
            cursor = "❯" if index == selected_idx else " "
            marker = "●" if index == selected_idx else "○"
            style = "class:selected" if index == selected_idx else ""
            current_marker = "  current" if level == current else ""
            fragments.append((style, f"  {cursor} {marker} {index + 1}. {label}{current_marker}\n"))
            fragments.append(("class:desc", f"      {description}\n"))
        fragments.append(("class:help", "\n  Up/Down or 1-6 select  Enter apply  Esc cancel\n"))
        return fragments

    control = FormattedTextControl(get_fragments)
    key_bindings = KeyBindings()

    @key_bindings.add("up")
    def _move_up(event):
        nonlocal selected_idx
        selected_idx = (selected_idx - 1) % len(options)
        event.app.invalidate()

    @key_bindings.add("down")
    def _move_down(event):
        nonlocal selected_idx
        selected_idx = (selected_idx + 1) % len(options)
        event.app.invalidate()

    for _digit in range(1, len(options) + 1):

        @key_bindings.add(str(_digit))
        def _select_by_number(event, _target=_digit - 1):
            nonlocal selected_idx
            selected_idx = _target
            event.app.invalidate()

    @key_bindings.add("enter")
    def _apply(event):
        event.app.exit(result=options[selected_idx][0])

    @key_bindings.add("escape")
    @key_bindings.add("c-c")
    def _cancel(event):
        event.app.exit(result=None)

    app = Application(
        layout=Layout(Window(content=control, always_hide_cursor=True)),
        key_bindings=key_bindings,
        style=Style.from_dict({
            "title": "#00afff bold",
            "desc": "#888888",
            "selected": "#00ff00 bold",
            "help": "#666666",
        }),
        full_screen=False,
        mouse_support=False,
    )
    return await app.run_async()


def _plan_guard_tui_available() -> bool:
    """Return whether the interactive plan-guard selector can run safely."""
    disabled = os.getenv("PROMPT_TOOLKIT_ENABLED", "1").lower() in ("0", "false")
    return not disabled and sys.stdin.isatty() and sys.stdout.isatty()


async def _select_plan_guard_mode(current: str) -> str | None:
    """Show a two-mode prompt_toolkit selector and return the chosen mode."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    options = (
        (
            "advisory",
            "Advisory (recommended)",
            "Warn after missing plan blocks; tool calls continue.",
        ),
        (
            "strict",
            "Strict",
            "Stop the third tool-call attempt without a plan before tools run.",
        ),
    )
    selected_idx = next(
        (index for index, (mode, _, _) in enumerate(options) if mode == current),
        0,
    )

    def get_fragments():
        fragments = [
            ("class:title", "\n  Plan Guard Mode\n"),
            ("class:desc", "  Choose how missing <plan> blocks are handled.\n\n"),
        ]
        for index, (mode, label, description) in enumerate(options):
            cursor = "❯" if index == selected_idx else " "
            marker = "●" if index == selected_idx else "○"
            style = "class:selected" if index == selected_idx else ""
            current_marker = "  current" if mode == current else ""
            fragments.append((style, f"  {cursor} {marker} {index + 1}. {label}{current_marker}\n"))
            fragments.append(("class:desc", f"      {description}\n"))
        fragments.append(("class:help", "\n  Up/Down or 1/2 select  Enter apply  Esc cancel\n"))
        return fragments

    control = FormattedTextControl(get_fragments)
    key_bindings = KeyBindings()

    @key_bindings.add("up")
    def _move_up(event):
        nonlocal selected_idx
        selected_idx = (selected_idx - 1) % len(options)
        event.app.invalidate()

    @key_bindings.add("down")
    def _move_down(event):
        nonlocal selected_idx
        selected_idx = (selected_idx + 1) % len(options)
        event.app.invalidate()

    @key_bindings.add("1")
    @key_bindings.add("2")
    def _select_by_number(event):
        nonlocal selected_idx
        selected_idx = int(event.key_sequence[-1].key) - 1
        event.app.invalidate()

    @key_bindings.add("enter")
    def _apply(event):
        event.app.exit(result=options[selected_idx][0])

    @key_bindings.add("escape")
    @key_bindings.add("c-c")
    def _cancel(event):
        event.app.exit(result=None)

    app = Application(
        layout=Layout(Window(content=control, always_hide_cursor=True)),
        key_bindings=key_bindings,
        style=Style.from_dict({
            "title": "#00afff bold",
            "desc": "#888888",
            "selected": "#00ff00 bold",
            "help": "#666666",
        }),
        full_screen=False,
        mouse_support=False,
    )
    return await app.run_async()


@register("/fetchsize")
async def cmd_fetchsize(ctx: CommandContext) -> None:
    arg = ctx.arg
    if not arg:
        _print(c(GRAY, f"  Current: {runtime_config()['fetch_max_chars']}"))
        return
    try:
        set_dynamic_config_value("fetch_max_chars", max(1000, int(arg)))
        _print(c(GREEN, f"  ✓ fetch_max_chars={runtime_config()['fetch_max_chars']}"))
    except ValueError:
        _print(c(RED, "  ✗ Invalid number"))
