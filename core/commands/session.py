"""
Session, persistence, knowledge-base and conversation-control commands.

Migrated verbatim from main.py's _legacy_slash_dispatch in stage-1 step 3.
Functional behavior is preserved exactly; only the dispatch plumbing
changed (each command is now an async function dispatched via the
registry instead of an elif branch).

Commands in this module:
    /chat <sub>...        session list / view / export / find / tag / untag /
                          bytag / link / unlink / related (sub-dispatched)
    /save [name]          persist current session
    /load <id|n>          load a saved session
    /resume [n]           resume last (or n-th) session, interactive if no arg
    /sessions             list saved sessions
    /rename <id> <name>   rename a session
    /del <id|n>           delete a session
    /forget <id>          remove a knowledge-base entry
    /memo [content]       archive content (or last AI reply) into GSA skills
    /memorize [topic]     summarize last N turns into knowledge entry
    /pin [n|msg <seq>]    pin recent / specific message(s)
    /unpin                clear all pins in current session
    /undo [n]             roll back last n turns
    /compact              summarize → clear (preserve pins)
    /think <prompt>       single-turn reasoning-mode invocation
    /mode                 toggle USER ↔ DEV output mode

Module-private helpers (only used by these commands; intentionally kept
out of `_common.py`):
    _resolve_session_id   resolve a numeric index or id-prefix to full id
    _memo_to_skills       /memo core; archives content into GSA skills
    _handle_chat          dispatch table for the `/chat <sub>` family
"""

from __future__ import annotations

from pathlib import Path

from config import DB_PATH, validate_api_key
from core.api_client import stream_request
from core.logger import logger
from core.memory import (
    delete_knowledge,
    export_session_to_markdown,
    find_sessions_by_tag,
    full_text_search,
    get_linked_sessions,
    get_session,
    get_session_messages_pretty,
    link_sessions,
    list_sessions,
    pin_message_by_seq,
    tag_session,
    unlink_sessions,
    untag_session,
)
from core.persistence import (
    memorize,
    session_delete,
    session_list,
    session_load,
    session_rename,
    session_save,
)
from core.session import _ctx_chars
from core.state import state as _runtime_state
from utils.ansi import (
    c, cp, BOLD, GRAY, CYAN, GREEN, YELLOW, RED, MAGENTA,
)

from core.commands import CommandContext, register
from core.commands._common import set_deferred_history


# ════════════════════════════════════════════════════════
# Module-private helpers
# ════════════════════════════════════════════════════════

def _resolve_session_id(query: str, sessions_list=None) -> str | None:
    """Resolve a user-supplied query (1-indexed sequence or id substring)
    to a full session_id. Returns None if no match.
    """
    rows = sessions_list or list_sessions(50)
    if not rows:
        return None
    query = query.strip()
    # 按序号（1-indexed）
    try:
        idx = int(query) - 1
        if 0 <= idx < len(rows):
            return rows[idx]["id"]
    except ValueError:
        pass
    # 按 id 子串
    for r in rows:
        if query.lower() in r["id"].lower() or query.lower() in (r["name"] or "").lower():
            return r["id"]
    return None


def _memo_to_skills(session, content: str, verbose: bool = True) -> str:
    """/memo core: archive `content` (or last AI reply if empty) into GSA.

    Returns a status string starting with "✓" / "⚠" / "ERROR".
    """
    try:
        from core.gsa import write_skill
    except ImportError:
        return "ERROR: core/gsa.py 未找到，请确认 GSA 模块已部署到 core/ 目录。"

    # 若无内容，提取上一轮 AI 回复
    if not content.strip():
        last_ai = next(
            (m.get("content", "") for m in reversed(session.messages)
             if m.get("role") == "assistant" and m.get("content")),
            ""
        )
        if not last_ai.strip():
            return "ERROR: 对话历史中没有可提取的 AI 回复，请在 /memo 后附上要存档的内容。"
        content = last_ai
        if verbose:
            print(c(GRAY, f"  (自动提取上一条 AI 回复，{len(content)} 字符)"))

    if verbose:
        print(c(YELLOW, f"  🧠 [GSA] 正在分类并存档（模型: {session.model_alias}）..."))

    ok, msg = write_skill(
        model_alias=session.model_alias,
        content=content,
        topic_hint="",
    )
    return msg


def _handle_chat(arg: str, arg2: str, session) -> None:
    """Dispatch table for /chat <sub> sub-commands.

    Subcommands: list, view, export, find, tag, untag, bytag, link,
    unlink, related.
    """
    sub = arg.lower().strip() if arg else "list"
    target = arg2.strip() if arg2 else ""

    # ── /chat list [n] ──────────────────────────────────
    if sub in ("list", "ls", ""):
        n = int(target) if target.isdigit() else 20
        rows = list_sessions(n)
        if not rows:
            print(c(GRAY, "  (暂无已保存会话)"))
            return
        print(c(BOLD, f"\n  对话历史（最近 {len(rows)} 条）："))
        for i, r in enumerate(rows):
            tags_str = c(CYAN, f"  [{r['tags']}]") if r["tags"] else ""
            display_name = r["name"] or r["auto_name"] or r["workspace_alias"]
            name_str = c(YELLOW, display_name) if display_name else c(GRAY, "(未命名)")
            print(
                c(GRAY, f"  [{i + 1:2d}] ") +
                c(CYAN, f"{r['id'][:24]}") +
                f"  {name_str}{tags_str}\n"
                + c(GRAY, f"       {r['updated_at'][:16]}  {r['msg_count']}条消息  model={r['model']}")
            )

    # ── /chat view <id|n> ────────────────────────────────
    elif sub == "view":
        if not target:
            print(c(RED, "  用法: /chat view <序号 或 session_id 前缀>"))
            return
        sid = _resolve_session_id(target)
        if not sid:
            print(c(RED, f"  ✗ 找不到会话 '{target}'"))
            return
        meta = get_session(sid)
        msgs = get_session_messages_pretty(sid)
        display_name = meta["name"] or meta["auto_name"] or meta["workspace_alias"] or "(未命名)"
        print(c(BOLD, f"\n  ╔ 会话 {sid}"))
        print(c(GRAY, f"  ║ 名称  : {display_name}"))
        print(c(GRAY, f"  ║ 模型  : {meta['model']}"))
        print(c(GRAY, f"  ║ 目录  : {meta['cwd']}"))
        print(c(GRAY, f"  ║ 标签  : {meta['tags'] or '-'}"))
        print(c(GRAY, f"  ║ 更新  : {meta['updated_at']}"))
        print(c(GRAY, f"  ╚ 共 {len(msgs)} 条消息"))
        print()

        for m in msgs:
            role = m["role"]
            seq_tag = c(GRAY, f"[{m['seq']:3d}]")
            pin_tag = c(GREEN, " 📌") if m["is_pinned"] else "   "
            ts = c(GRAY, m["created_at"][11:16] if m["created_at"] else "")

            if role == "system":
                continue  # system 消息不显示（太长）
            elif role == "user":
                print(c(BOLD + "\033[96m", "  🧑 You") + f" {seq_tag}{pin_tag} {ts}")
                for line in m["content_full"].splitlines()[:10]:
                    print(f"     {line}")
                if m["content_full"].count("\n") > 10:
                    print(c(GRAY, f"     ...（共 {m['content_full'].count(chr(10)) + 1} 行）"))
            elif role == "assistant":
                print(c(BOLD + "\033[92m", "  🤖 Agent") + f" {seq_tag}{pin_tag} {ts}")
                for line in m["content_full"].splitlines()[:8]:
                    print(f"     {line}")
                if m["content_full"].count("\n") > 8:
                    print(c(GRAY, f"     ...（共 {m['content_full'].count(chr(10)) + 1} 行）"))
            elif role == "tool":
                print(c(GRAY, "  🔩 tool") + f" {seq_tag} {ts}  {m['preview']}")
            print()

    # ── /chat export <id|n> [path] ──────────────────────
    elif sub == "export":
        if not target:
            print(c(RED, "  用法: /chat export <序号 或 id> [输出文件路径]"))
            return
        parts = target.split(None, 1)
        id_part = parts[0]
        out_arg = parts[1].strip() if len(parts) > 1 else ""

        sid = _resolve_session_id(id_part)
        if not sid:
            print(c(RED, f"  ✗ 找不到会话 '{id_part}'"))
            return

        md_content = export_session_to_markdown(sid)
        if md_content.startswith("ERROR:"):
            print(c(RED, f"  {md_content}"))
            return

        if out_arg:
            out_path = Path(out_arg).expanduser()
        else:
            out_path = Path(session.cwd) / f"chat_{sid[:16]}.md"

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md_content, encoding="utf-8")
        print(c(GREEN, f"  ✓ 对话已导出 → {out_path}"))
        print(c(GRAY, f"  共 {len(md_content)} 字符 / {md_content.count(chr(10))} 行"))

    # ── /chat find <keywords> ────────────────────────────
    elif sub == "find":
        if not target:
            print(c(RED, "  用法: /chat find <搜索词（空格分隔多词）>"))
            return
        print(c(YELLOW, f"  🔍 跨会话搜索: '{target}' ..."))
        results = full_text_search(target, limit=10)
        if not results:
            print(c(GRAY, "  未找到匹配内容。"))
            return
        print(c(BOLD, f"\n  找到 {len(results)} 个会话含匹配内容："))
        for r in results:
            print(c(CYAN, f"\n  [{r['session_id'][:20]}]") +
                  c(YELLOW, f"  {r['session_name'] or '(未命名)'}") +
                  c(GRAY, f"  {r['updated_at'][:16]}  tags={r['tags'] or '-'}"))
            for hit in r["hits"]:
                role_icon = "🧑" if hit["role"] == "user" else ("🤖" if hit["role"] == "assistant" else "🔩")
                print(c(GRAY, f"    [{hit['seq']:3d}] {role_icon} ") + hit["snippet"])

    # ── /chat tag <id|n> <tags> ──────────────────────────
    elif sub == "tag":
        parts = target.split(None, 1)
        if len(parts) < 2:
            print(c(RED, "  用法: /chat tag <序号 或 id> <标签1,标签2,...>"))
            return
        sid = _resolve_session_id(parts[0])
        if not sid:
            print(c(RED, f"  ✗ 找不到会话 '{parts[0]}'"))
            return
        ok = tag_session(sid, parts[1])
        if ok:
            print(c(GREEN, f"  ✓ 已给会话 {sid[:20]}... 添加标签: {parts[1]}"))
        else:
            print(c(RED, "  ✗ 操作失败"))

    # ── /chat untag <id|n> <tags> ────────────────────────
    elif sub == "untag":
        parts = target.split(None, 1)
        if len(parts) < 2:
            print(c(RED, "  用法: /chat untag <序号 或 id> <标签1,标签2,...>"))
            return
        sid = _resolve_session_id(parts[0])
        if not sid:
            print(c(RED, f"  ✗ 找不到会话 '{parts[0]}'"))
            return
        untag_session(sid, parts[1])
        print(c(GREEN, f"  ✓ 已移除标签: {parts[1]}"))

    # ── /chat bytag <tag> ────────────────────────────────
    elif sub == "bytag":
        if not target:
            print(c(RED, "  用法: /chat bytag <标签名>"))
            return
        rows = find_sessions_by_tag(target)
        if not rows:
            print(c(GRAY, f"  未找到带标签 '{target}' 的会话。"))
            return
        print(c(BOLD, f"\n  标签 '{target}' 的会话（{len(rows)} 个）："))
        for i, r in enumerate(rows):
            print(c(GRAY, f"  [{i + 1:2d}] ") + c(CYAN, r["id"][:24]) +
                  c(GRAY, f"  {r['updated_at'][:16]}  {r['msg_count']}条  tags={r['tags']}"))

    # ── /chat link <id1> <id2> [note] ────────────────────
    elif sub == "link":
        parts = target.split(None, 2)
        if len(parts) < 2:
            print(c(RED, "  用法: /chat link <id/序号1> <id/序号2> [关联备注]"))
            return
        sid_a = _resolve_session_id(parts[0])
        sid_b = _resolve_session_id(parts[1])
        note = parts[2] if len(parts) > 2 else ""
        if not sid_a or not sid_b:
            print(c(RED, "  ✗ 无法解析会话 ID"))
            return
        if sid_a == sid_b:
            print(c(RED, "  ✗ 不能关联同一个会话"))
            return
        link_sessions(sid_a, sid_b, note)
        print(c(GREEN, "  ✓ 已关联:"))
        print(c(GRAY, f"    {sid_a[:24]}"))
        print(c(GRAY, f"    {sid_b[:24]}"))
        if note:
            print(c(GRAY, f"    备注: {note}"))

    # ── /chat unlink <id1> <id2> ─────────────────────────
    elif sub == "unlink":
        parts = target.split(None, 1)
        if len(parts) < 2:
            print(c(RED, "  用法: /chat unlink <id/序号1> <id/序号2>"))
            return
        sid_a = _resolve_session_id(parts[0])
        sid_b = _resolve_session_id(parts[1])
        if not sid_a or not sid_b:
            print(c(RED, "  ✗ 无法解析会话 ID"))
            return
        unlink_sessions(sid_a, sid_b)
        print(c(GREEN, f"  ✓ 已取消关联 {sid_a[:20]} ↔ {sid_b[:20]}"))

    # ── /chat related <id|n> ─────────────────────────────
    elif sub == "related":
        if not target:
            print(c(RED, "  用法: /chat related <序号 或 id>"))
            return
        sid = _resolve_session_id(target)
        if not sid:
            print(c(RED, f"  ✗ 找不到会话 '{target}'"))
            return
        linked = get_linked_sessions(sid)
        if not linked:
            print(c(GRAY, f"  会话 {sid[:24]} 没有关联的对话。"))
            print(c(GRAY, "  使用 /chat link 创建关联。"))
            return
        print(c(BOLD, f"\n  会话 {sid[:24]} 的关联对话（{len(linked)} 个）："))
        for item in linked:
            m = item["meta"]
            note = item["note"]
            print(c(CYAN, f"  {m['id'][:24]}") +
                  c(GRAY, f"  {m['updated_at'][:16]}  {m['msg_count']}条  model={m['model']}"))
            if note:
                print(c(GRAY, f"    备注: {note}"))
            print()

    else:
        print(c(GRAY, (
            f"  未知子命令 '{sub}'。\n"
            "  可用: list · view · export · find · tag · untag · bytag · link · unlink · related"
        )))


# ════════════════════════════════════════════════════════
# Command handlers
# ════════════════════════════════════════════════════════

# ── /chat ─────────────────────────────────────────────────
@register("/chat")
async def cmd_chat(ctx: CommandContext) -> None:
    _handle_chat(ctx.arg, ctx.arg2, ctx.session)


# ── Persistence: /save /load /resume /sessions /rename /del ──
@register("/save")
async def cmd_save(ctx: CommandContext) -> None:
    sid = session_save(ctx.session, ctx.arg)
    print(c(GREEN, f"  ✓ 已保存 session_id={sid}"))


@register("/load")
async def cmd_load(ctx: CommandContext) -> None:
    if not ctx.arg:
        print(c(RED, "  用法: /load <name 或 序号>"))
        return
    result = session_load(ctx.session, ctx.arg)
    print(c(GREEN if result.startswith("OK") else RED, f"  {result}"))
    if result.startswith("OK"):
        logger.debug("session_load OK, msgs to display: {}", len(ctx.session.messages))
        set_deferred_history(ctx.session.messages)


@register("/resume")
async def cmd_resume(ctx: CommandContext) -> None:
    session = ctx.session
    arg = ctx.arg
    if arg:
        # /resume <n> — 直接恢复指定序号
        result = session_load(session, arg)
        print(c(GREEN if result.startswith("OK") else RED, f"  {result}"))
        if result.startswith("OK"):
            logger.debug("session_load OK (resume), msgs to display: {}", len(session.messages))
            set_deferred_history(session.messages)
        return
    # /resume — 显示最近会话列表并交互选择
    rows = list_sessions(10)
    if not rows:
        print(c(GRAY, "  暂无已保存会话"))
        return
    print(c(BOLD, "\n  最近会话："))
    for i, r in enumerate(rows):
        name = r["name"] or "(未命名)"
        ts = str(r["updated_at"])[:16] if r["updated_at"] else ""
        msgs = r["msg_count"] if r["msg_count"] else 0
        model = r["model"] if r["model"] else ""
        print(
            c(GRAY, f"  [{i+1:2d}] ") +
            c(CYAN, name) +
            c(GRAY, f"  {ts}  {msgs}条  model={model}")
        )
    print(c(GRAY, "\n  输入序号恢复，或 Enter 取消"))
    try:
        pick = input(cp(BOLD, "  选择 [1-" + str(len(rows)) + "]: ")).strip()
        if pick.isdigit():
            idx = int(pick) - 1
            if 0 <= idx < len(rows):
                result = session_load(session, str(idx + 1))
                print(c(GREEN if result.startswith("OK") else RED, f"  {result}"))
                if result.startswith("OK"):
                    set_deferred_history(session.messages)
            else:
                print(c(RED, "  序号超出范围"))
    except (EOFError, KeyboardInterrupt):
        print()


@register("/sessions")
async def cmd_sessions(ctx: CommandContext) -> None:
    from core.output import JsonSink
    if isinstance(ctx.sink, JsonSink):
        rows = list_sessions(20)
        data = [
            {
                "id":         r["id"],
                "name":       r["name"] or r["auto_name"] or r["workspace_alias"] or "",
                "updated_at": r["updated_at"],
                "msg_count":  r["msg_count"],
                "model":      r["model"],
                "tags":       r["tags"] or "",
            }
            for r in rows
        ]
        ctx.sink.print_json(data)
        return
    print(c(BOLD, f"\n  已保存会话 (DB: {DB_PATH})："))
    print(session_list())


@register("/del")
async def cmd_del(ctx: CommandContext) -> None:
    if not ctx.arg:
        print(c(RED, "  用法: /del <name 或 序号>"))
        return
    result = session_delete(ctx.session, ctx.arg)
    print(c(GREEN if result.startswith("OK") else RED, f"  {result}"))


@register("/rename")
async def cmd_rename(ctx: CommandContext) -> None:
    if not ctx.arg or not ctx.arg2:
        print(c(RED, "  用法: /rename <序号或名称> <新名称>"))
        return
    result = session_rename(ctx.session, ctx.arg, ctx.arg2)
    print(c(GREEN if result.startswith("OK") else RED, f"  {result}"))


# ── Knowledge: /memorize /forget ────────────────────────────
@register("/memorize")
async def cmd_memorize(ctx: CommandContext) -> None:
    topic = (ctx.arg + " " + ctx.arg2).strip() or "general"
    print(c(YELLOW, f"  🧠 正在总结「{topic}」..."))
    result = memorize(ctx.session, topic)
    print(c(GREEN if result.startswith("OK") else RED, f"  {result}"))


@register("/forget")
async def cmd_forget(ctx: CommandContext) -> None:
    if not ctx.arg:
        print(c(RED, "  用法: /forget <id>"))
        return
    try:
        delete_knowledge(int(ctx.arg))
        print(c(GREEN, f"  ✓ 已删除知识条目 id={ctx.arg}"))
    except Exception as e:
        print(c(RED, f"  ✗ {e}"))


# ── /memo ───────────────────────────────────────────────────
@register("/memo")
async def cmd_memo(ctx: CommandContext) -> None:
    raw_content = (ctx.arg + " " + ctx.arg2).strip()
    result = _memo_to_skills(ctx.session, raw_content, verbose=True)
    col = GREEN if result.startswith("✓") else (YELLOW if result.startswith("⚠") else RED)
    print(c(col, f"  {result}"))


# ── Pin / Unpin / Undo ──────────────────────────────────────
@register("/pin")
async def cmd_pin(ctx: CommandContext) -> None:
    session = ctx.session
    arg = ctx.arg
    arg2 = ctx.arg2
    if arg == "msg":
        try:
            seq = int(arg2)
            non_sys = [m for m in session.messages if m.get("role") != "system"]
            if 0 <= seq < len(non_sys):
                non_sys[seq]["_pinned"] = True
                pin_message_by_seq(session.session_id, seq, True)
                role = non_sys[seq].get("role", "?")
                preview = str(non_sys[seq].get("content", ""))[:50].replace("\n", " ")
                print(c(GREEN, f"  ✓ 精准 Pin [{seq}] [{role}]: {preview}"))
            else:
                print(c(RED, f"  ✗ 序号 {seq} 超出范围（共 {len(non_sys)} 条非 system 消息）"))
        except ValueError:
            print(c(RED, "  用法: /pin msg <序号>  (先 /history 查看序号)"))
    else:
        n = int(arg) if arg.isdigit() else 2
        count = 0
        for m in reversed(session.messages):
            if m.get("role") == "system":
                break
            if not m.get("_pinned"):
                m["_pinned"] = True
                count += 1
                if count >= n:
                    break
        print(c(GREEN, f"  ✓ 已 Pin 最近 {count} 条"))


@register("/unpin")
async def cmd_unpin(ctx: CommandContext) -> None:
    count = sum(1 for m in ctx.session.messages if m.pop("_pinned", None))
    print(c(GREEN, f"  ✓ 已解除 {count} 条 Pin"))


@register("/undo")
async def cmd_undo(ctx: CommandContext) -> None:
    n = int(ctx.arg) if ctx.arg.isdigit() else 1
    removed, _last_text = ctx.session.undo(n)
    if removed:
        print(c(GREEN, f"  ↩ 已撤回 {removed} 条消息"))
    else:
        print(c(GRAY, "  ↩ 无可撤回的消息"))


# ── /compact ────────────────────────────────────────────────
@register("/compact")
async def cmd_compact(ctx: CommandContext) -> None:
    """Lightweight summary → clear (preserve pins) → summary as first msg."""
    session = ctx.session
    _summary_prompt = (
        "请用 3-5 句话总结以下对话的关键进展、已确认的结论和待办事项。"
        "保持技术细节（如偏移量、地址、文件路径）。仅输出总结，不要寒暄。"
    )
    _compact_msgs = [
        m for m in session.messages
        if m.get("role") != "system" and not m.get("_pinned")
    ]
    if len(_compact_msgs) < 2:
        print(c(GRAY, "  ↕ 上下文太短，无需压缩"))
        return

    print(c(CYAN, "  🔄 正在压缩上下文..."))
    _summarize_msgs = [
        {"role": "system", "content": "你是一个对话摘要助手。"},
        *_compact_msgs,
        {"role": "user", "content": _summary_prompt},
    ]
    _summary_buf = ""
    try:
        for delta in stream_request(
            _summarize_msgs, session.model_alias,
            max_tokens=1024, tools_schema=None,
        ):
            if "_error" in delta:
                print(c(RED, f"  ✗ 摘要生成失败: {delta['_error']}"))
                _summary_buf = ""
                break
            choices = delta.get("choices") or []
            if not choices:
                continue
            chunk = choices[0].get("delta", {}).get("content", "")
            if chunk:
                _summary_buf += chunk
    except Exception as e:
        print(c(RED, f"  ✗ 摘要异常: {e}"))
        _summary_buf = ""

    if _summary_buf:
        pinned = [m for m in session.messages if m.get("_pinned")]
        session.messages.clear()
        session._reset_system_prompt()
        session.messages.extend(pinned)
        session.messages.append({
            "role": "assistant",
            "content": f"📝 [Compact Summary]\n{_summary_buf}",
            "_pinned": True,
        })
        _chars = _ctx_chars(session.messages)
        print(c(GREEN,
            f"  ✓ 已压缩 | 保留 {len(pinned)} 条 Pin + 摘要 | "
            f"上下文: {_chars//4:,} tokens"
        ))


# ── /think ──────────────────────────────────────────────────
@register("/think")
async def cmd_think(ctx: CommandContext) -> None:
    session = ctx.session
    arg = ctx.arg
    if not arg:
        print(c(RED, "  用法: /think <prompt>  (单次触发推理模式)"))
        return
    # 单次触发：在本次请求中切换到推理 Worker 或增加 thinking 预算
    _think_alias = None
    for _candidate in ("ds-v4-pro", "ds-v4-flash"):
        _ok, _ = validate_api_key(_candidate)
        if _ok:
            _think_alias = _candidate
            break
    if _think_alias:
        old_alias = session.model_alias
        session.model_alias = _think_alias
        print(c(MAGENTA, f"  🧠 推理模式: {old_alias} → {_think_alias}"))
        try:
            session.run_turn(arg)
        finally:
            session.model_alias = old_alias
            print(c(GRAY, f"  ↩ 已恢复模型: {old_alias}"))
    else:
        # 无推理 Worker，直接以当前模型执行（注入 thinking 指令）
        _think_prefix = (
            "[THINKING MODE] 请逐步推理，展示完整思维链。\n\n"
        )
        session.run_turn(_think_prefix + arg)


# ── /mode ───────────────────────────────────────────────────
@register("/mode")
async def cmd_mode(ctx: CommandContext) -> None:
    _runtime_state.user_mode = not _runtime_state.user_mode
    if _runtime_state.user_mode:
        print(c(GREEN, "  ✓ 已切换到 USER 模式（简洁输出，屏蔽底层错误）"))
    else:
        print(c(CYAN, "  ✓ 已切换到 DEV 模式（极致透明，显示所有细节）"))
