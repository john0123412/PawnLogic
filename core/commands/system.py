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

  /low /mid /deep /max /normal    apply a tier preset
  /limits                          show current dynamic config
  /tokens [N]    set max_tokens
  /ctx [N]       set ctx_max_chars
  /iter [N]      set max_iter
  /toolsize [N]  set tool_max_chars
  /fetchsize [N] set fetch_max_chars
"""

from __future__ import annotations

import time
from pathlib import Path

from config import (
    DYNAMIC_CONFIG, NORMAL_CONFIG,
    TIER_LOW, TIER_MID, TIER_DEEP, TIER_MAX,
)
from core.api_client import stream_request
from core.memory import list_failures, clear_failures
from core.session import _ctx_chars, STATE_FILENAME
from core.state import state as _runtime_state
from utils.ansi import (
    c, BOLD, GRAY, CYAN, GREEN, YELLOW, RED, MAGENTA,
)

from core.commands import CommandContext, register
from core.commands._common import EXIT_SENTINEL, fmt_config


# ════════════════════════════════════════════════════════
# Help & Exit
# ════════════════════════════════════════════════════════

@register("/help")
async def cmd_help(ctx: CommandContext) -> None:
    # HELP_TEXT lives in main.py because it embeds VERSION; lazy import
    # avoids a circular dependency at module load time.
    from main import HELP_TEXT
    print(HELP_TEXT)


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
    state_note = c(GREEN, "  (State.md 将在下轮自动注入)") if state_exists else ""
    print(c(GREEN, f"  ✓ 已清空（保留 {len(pinned)} 条 Pin 消息）{state_note}"))


@register("/context")
async def cmd_context(ctx: CommandContext) -> None:
    session = ctx.session
    msgs = session.messages
    chars = _ctx_chars(msgs)
    pct = chars / DYNAMIC_CONFIG["ctx_max_chars"] * 100
    tok = chars // 4
    pinned = sum(1 for m in msgs if m.get("_pinned"))
    filled = int(min(pct, 100) / 100 * 30)
    bcol = RED if pct > 80 else (YELLOW if pct > 50 else GREEN)
    bar = c(bcol, "█" * filled) + c(GRAY, "░" * (30 - filled))
    warn = c(YELLOW, "  ⚠ 超80%，建议 /clear") if pct > 80 else ""
    print(
        f"\n  {c(BOLD, '上下文')}  {len(msgs)}条  Pin:{c(GREEN, str(pinned))}"
        f"  ~{tok:,} tokens\n  [{bar}] {pct:.1f}%  {warn}\n"
    )


@register("/history")
async def cmd_history(ctx: CommandContext) -> None:
    session = ctx.session
    print(c(CYAN, f"\n  {len(session.messages)} 条消息（序号不含 system）："))
    seq = 0
    for m in session.messages:
        role = m.get("role", "?")
        content = str(m.get("content") or "")[:65].replace("\n", " ")
        pin_tag = c(GREEN, " 📌") if m.get("_pinned") else "   "
        if role == "system":
            print(c(GRAY, f"  [{'sys':9}]     {content[:50]}"))
        else:
            print(c(GRAY, f"  [{role:9}]") + c(CYAN, f"[{seq:3d}]") + pin_tag + f" {content}")
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
    print(c(CYAN, "  🏓 ping..."), end="", flush=True)
    try:
        for delta in stream_request(
            _ping_msgs, session.model_alias,
            max_tokens=16, tools_schema=None,
        ):
            if "_error" in delta:
                print(c(RED, f" ✗ {delta['_error']}"))
                break
            choices = delta.get("choices") or []
            if not choices:
                continue
            chunk = choices[0].get("delta", {}).get("content", "")
            _ping_buf += chunk
        if _ping_buf:
            print(c(GREEN, f" {_ping_buf.strip()} ✓"))
        else:
            print(c(GREEN, " pong ✓"))
    except Exception as e:
        print(c(RED, f" ✗ {e}"))


@register("/state")
async def cmd_state(ctx: CommandContext) -> None:
    session = ctx.session
    p = Path(session.cwd) / STATE_FILENAME
    if p.exists():
        print(c(BOLD, f"\n  {p}："))
        print(p.read_text(encoding="utf-8"))
    else:
        print(c(GRAY, f"  当前目录没有 {STATE_FILENAME}。用 /init_project 创建。"))


@register("/stats")
async def cmd_stats(ctx: CommandContext) -> None:
    session = ctx.session
    pt = session.total_prompt_tokens
    ct = session.total_completion_tokens
    tt = session.total_tool_calls
    tot = pt + ct
    est_usd = tot / 1_000_000 * 1.50
    if tot + tt == 0:
        print(c(GRAY, "  (本次会话暂无 API 调用记录)"))
    elif _runtime_state.quiet_mode:
        print(c(GRAY, f"  stats: ↑{pt:,} ↓{ct:,} total={tot:,} tools={tt} ~${est_usd:.4f}"))
    else:
        print(c(BOLD, "\n  ╔══ 会话用量审计 ════════════════════════════╗"))
        print(f"  ║  Prompt tokens    : {c(CYAN, f'{pt:>10,}')}               ║")
        print(f"  ║  Completion tokens: {c(CYAN, f'{ct:>10,}')}               ║")
        print(f"  ║  Total tokens     : {c(YELLOW, f'{tot:>10,}')}               ║")
        print(f"  ║  Tool calls       : {c(GREEN, f'{tt:>10,}')}               ║")
        print(f"  ║  Est. cost        : {c(GRAY, f'~${est_usd:.4f} USD'):>18}         ║")
        print(c(BOLD,  "  ╚══════════════════════════════════════════════╝"))
        print(c(GRAY, "  (成本估算基于 $1.50/1M tokens 均值，仅供参考)"))


@register("/time")
async def cmd_time(ctx: CommandContext) -> None:
    session = ctx.session
    arg = ctx.arg
    budget = DYNAMIC_CONFIG.get("time_budget_sec", 0)
    if arg and arg.strip().isdigit():
        new_budget = max(0, int(arg.strip()))
        DYNAMIC_CONFIG["time_budget_sec"] = new_budget
        session._time_budget_sec = new_budget
        session._reset_system_prompt()
        if new_budget > 0:
            m, s = divmod(new_budget, 60)
            print(c(GREEN, f"  ✓ 时间预算已设为 {m}m{s}s"))
        else:
            print(c(GREEN, "  ✓ 时间预算已关闭（不限时）"))
    else:
        if budget > 0:
            m, s = divmod(budget, 60)
            elapsed = time.monotonic() - session._turn_start_time if session._turn_start_time else 0
            remaining = max(0, budget - elapsed)
            rm, rs = divmod(int(remaining), 60)
            mode = c(RED, " [URGENT]") if session._urgent_mode else ""
            print(c(BOLD, "\n  ⏱  时间预算："))
            print(f"  预算: {c(CYAN, f'{m}m{s}s')}")
            print(f"  已用: {c(YELLOW, f'{int(elapsed)}s')}")
            print(f"  剩余: {c(GREEN if remaining > 30 else RED, f'{rm}m{rs}s')}{mode}")
            print(c(GRAY, "\n  /time <秒数> 修改 | /time 0 关闭"))
        else:
            print(c(GRAY, "  时间预算未设置（不限时）"))
            print(c(GRAY, "  /time <秒数> 设置 | 例: /time 300 = 5分钟"))


@register("/failures")
async def cmd_failures(ctx: CommandContext) -> None:
    arg = ctx.arg
    sub = arg.lower().strip() if arg else "list"
    if sub == "clear":
        n = clear_failures()
        print(c(GREEN, f"  ✓ 已清空 {n} 条失败记录"))
    elif sub == "list" or sub.isdigit():
        n = int(sub) if sub.isdigit() else 20
        rows = list_failures(n)
        if not rows:
            print(c(GREEN, "  ✓ 暂无失败记录（防御性审计数据库为空）"))
        else:
            print(c(BOLD, f"\n  失败记录（最近 {len(rows)} 条）："))
            for i, r in enumerate(rows):
                etype = r["error_type"] or "?"
                ts = r["created_at"][:16] if r["created_at"] else ""
                tool = r["tool_name"]
                msg = r["error_msg"][:80].replace("\n", " ")
                print(
                    c(GRAY, f"  [{i+1:2d}] ")
                    + c(RED, f"{tool:20}")
                    + c(YELLOW, f" {etype:15}")
                    + c(GRAY, f" {ts}")
                )
                print(c(GRAY, f"       {msg}"))
    else:
        print(c(GRAY, "  用法: /failures [list|clear|N]"))


# ════════════════════════════════════════════════════════
# Tier presets
# ════════════════════════════════════════════════════════

@register("/low")
async def cmd_low(ctx: CommandContext) -> None:
    DYNAMIC_CONFIG.update(TIER_LOW)
    ctx.session._reset_system_prompt()
    print(c(GREEN, "  ✓ /low 模式（日常 / 算法）"))
    print(fmt_config())


@register("/mid")
async def cmd_mid(ctx: CommandContext) -> None:
    DYNAMIC_CONFIG.update(TIER_MID)
    ctx.session._reset_system_prompt()
    print(c(YELLOW, "  ✓ /mid 模式（开发 / Pwn）"))
    print(fmt_config())


@register("/deep")
async def cmd_deep(ctx: CommandContext) -> None:
    DYNAMIC_CONFIG.update(TIER_DEEP)
    ctx.session._reset_system_prompt()
    print(c(BOLD + MAGENTA, "  🔥 /deep 全火力"))
    print(fmt_config())


@register("/max")
async def cmd_max(ctx: CommandContext) -> None:
    DYNAMIC_CONFIG.update(TIER_MAX)
    ctx.session._reset_system_prompt()
    print(c(BOLD + RED, "  💀 /max 极限火力（iter=100, ctx=600k, 60min）"))
    print(fmt_config())


@register("/normal")
async def cmd_normal(ctx: CommandContext) -> None:
    DYNAMIC_CONFIG.update(NORMAL_CONFIG)
    ctx.session._reset_system_prompt()
    print(c(GREEN, "  ✓ 已重置到 /mid"))
    print(fmt_config())


@register("/limits")
async def cmd_limits(ctx: CommandContext) -> None:
    print(c(BOLD, "\n  当前运行时限制："))
    print(fmt_config())
    print(c(GRAY, "  /low /mid /deep /max  |  /tokens /ctx /iter /toolsize /fetchsize"))


# ════════════════════════════════════════════════════════
# Fine-grained tunables
# ════════════════════════════════════════════════════════

@register("/tokens")
async def cmd_tokens(ctx: CommandContext) -> None:
    arg = ctx.arg
    if not arg:
        print(c(GRAY, f"  当前: {DYNAMIC_CONFIG['max_tokens']}  /tokens <n>"))
        return
    try:
        n = max(256, min(65536, int(arg)))
        DYNAMIC_CONFIG["max_tokens"] = n
        ctx.session._reset_system_prompt()
        print(c(GREEN, f"  ✓ max_tokens={n}"))
    except ValueError:
        print(c(RED, "  ✗ 无效数字"))


@register("/ctx")
async def cmd_ctx(ctx: CommandContext) -> None:
    arg = ctx.arg
    if not arg:
        print(c(GRAY, f"  当前: {DYNAMIC_CONFIG['ctx_max_chars']}  /ctx <n>"))
        return
    try:
        n = max(10_000, int(arg))
        DYNAMIC_CONFIG["ctx_max_chars"] = n
        DYNAMIC_CONFIG["ctx_trim_to"] = int(n * .75)
        ctx.session._reset_system_prompt()
        print(c(GREEN, f"  ✓ ctx_max_chars={n}"))
    except ValueError:
        print(c(RED, "  ✗ 无效数字"))


@register("/iter")
async def cmd_iter(ctx: CommandContext) -> None:
    arg = ctx.arg
    if not arg:
        print(c(GRAY, f"  当前: {DYNAMIC_CONFIG['max_iter']}  /iter <n>"))
        return
    try:
        n = max(1, int(arg))
        DYNAMIC_CONFIG["max_iter"] = n
        print(c(GREEN, f"  ✓ max_iter={n}"))
    except ValueError:
        print(c(RED, "  ✗ 无效数字"))


@register("/toolsize")
async def cmd_toolsize(ctx: CommandContext) -> None:
    arg = ctx.arg
    if not arg:
        print(c(GRAY, f"  当前: {DYNAMIC_CONFIG['tool_max_chars']}"))
        return
    try:
        DYNAMIC_CONFIG["tool_max_chars"] = max(1000, int(arg))
        print(c(GREEN, f"  ✓ tool_max_chars={DYNAMIC_CONFIG['tool_max_chars']}"))
    except ValueError:
        print(c(RED, "  ✗ 无效数字"))


@register("/fetchsize")
async def cmd_fetchsize(ctx: CommandContext) -> None:
    arg = ctx.arg
    if not arg:
        print(c(GRAY, f"  当前: {DYNAMIC_CONFIG['fetch_max_chars']}"))
        return
    try:
        DYNAMIC_CONFIG["fetch_max_chars"] = max(1000, int(arg))
        print(c(GREEN, f"  ✓ fetch_max_chars={DYNAMIC_CONFIG['fetch_max_chars']}"))
    except ValueError:
        print(c(RED, "  ✗ 无效数字"))
