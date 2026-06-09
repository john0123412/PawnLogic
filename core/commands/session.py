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
    # By 1-indexed sequence number.
    try:
        idx = int(query) - 1
        if 0 <= idx < len(rows):
            return rows[idx]["id"]
    except ValueError:
        pass
    # By id substring.
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
        return "ERROR: core/gsa.py was not found. Confirm the GSA module is deployed under core/."

    # If no content is supplied, use the previous assistant reply.
    if not content.strip():
        last_ai = next(
            (m.get("content", "") for m in reversed(session.messages)
             if m.get("role") == "assistant" and m.get("content")),
            ""
        )
        if not last_ai.strip():
            return "ERROR: No assistant reply is available to archive. Add content after /memo."
        content = last_ai
        if verbose:
            print(c(GRAY, f"  (Using previous assistant reply, {len(content)} characters)"))

    if verbose:
        print(c(YELLOW, f"  🧠 [GSA] Classifying and archiving (model: {session.model_alias})..."))

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
            print(c(GRAY, "  (No saved sessions.)"))
            return
        print(c(BOLD, f"\n  Conversation history (latest {len(rows)}):"))
        for i, r in enumerate(rows):
            tags_str = c(CYAN, f"  [{r['tags']}]") if r["tags"] else ""
            display_name = r["name"] or r["auto_name"] or r["workspace_alias"]
            name_str = c(YELLOW, display_name) if display_name else c(GRAY, "(untitled)")
            print(
                c(GRAY, f"  [{i + 1:2d}] ") +
                c(CYAN, f"{r['id'][:24]}") +
                f"  {name_str}{tags_str}\n"
                + c(GRAY, f"       {r['updated_at'][:16]}  {r['msg_count']} messages  model={r['model']}")
            )

    # ── /chat view <id|n> ────────────────────────────────
    elif sub == "view":
        if not target:
            print(c(RED, "  Usage: /chat view <index or session_id prefix>"))
            return
        sid = _resolve_session_id(target)
        if not sid:
            print(c(RED, f"  ✗ Session not found: '{target}'"))
            return
        meta = get_session(sid)
        msgs = get_session_messages_pretty(sid)
        display_name = meta["name"] or meta["auto_name"] or meta["workspace_alias"] or "(untitled)"
        print(c(BOLD, f"\n  ╔ Session {sid}"))
        print(c(GRAY, f"  ║ Name   : {display_name}"))
        print(c(GRAY, f"  ║ Model  : {meta['model']}"))
        print(c(GRAY, f"  ║ CWD    : {meta['cwd']}"))
        print(c(GRAY, f"  ║ Tags   : {meta['tags'] or '-'}"))
        print(c(GRAY, f"  ║ Updated: {meta['updated_at']}"))
        print(c(GRAY, f"  ╚ {len(msgs)} messages"))
        print()

        for m in msgs:
            role = m["role"]
            seq_tag = c(GRAY, f"[{m['seq']:3d}]")
            pin_tag = c(GREEN, " 📌") if m["is_pinned"] else "   "
            ts = c(GRAY, m["created_at"][11:16] if m["created_at"] else "")

            if role == "system":
                continue  # system messages are intentionally hidden because they are long
            elif role == "user":
                print(c(BOLD + "\033[96m", "  🧑 You") + f" {seq_tag}{pin_tag} {ts}")
                for line in m["content_full"].splitlines()[:10]:
                    print(f"     {line}")
                if m["content_full"].count("\n") > 10:
                    print(c(GRAY, f"     ...({m['content_full'].count(chr(10)) + 1} lines total)"))
            elif role == "assistant":
                print(c(BOLD + "\033[92m", "  🤖 Agent") + f" {seq_tag}{pin_tag} {ts}")
                for line in m["content_full"].splitlines()[:8]:
                    print(f"     {line}")
                if m["content_full"].count("\n") > 8:
                    print(c(GRAY, f"     ...({m['content_full'].count(chr(10)) + 1} lines total)"))
            elif role == "tool":
                print(c(GRAY, "  🔩 tool") + f" {seq_tag} {ts}  {m['preview']}")
            print()

    # ── /chat export <id|n> [path] ──────────────────────
    elif sub == "export":
        if not target:
            print(c(RED, "  Usage: /chat export <index or id> [output file path]"))
            return
        parts = target.split(None, 1)
        id_part = parts[0]
        out_arg = parts[1].strip() if len(parts) > 1 else ""

        sid = _resolve_session_id(id_part)
        if not sid:
            print(c(RED, f"  ✗ Session not found: '{id_part}'"))
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
        print(c(GREEN, f"  ✓ Conversation exported -> {out_path}"))
        print(c(GRAY, f"  {len(md_content)} characters / {md_content.count(chr(10))} lines"))

    # ── /chat find <keywords> ────────────────────────────
    elif sub == "find":
        if not target:
            print(c(RED, "  Usage: /chat find <search terms>"))
            return
        print(c(YELLOW, f"  🔍 Searching across sessions: '{target}' ..."))
        results = full_text_search(target, limit=10)
        if not results:
            print(c(GRAY, "  No matches found."))
            return
        print(c(BOLD, f"\n  Found matches in {len(results)} sessions:"))
        for r in results:
            print(c(CYAN, f"\n  [{r['session_id'][:20]}]") +
                  c(YELLOW, f"  {r['session_name'] or '(untitled)'}") +
                  c(GRAY, f"  {r['updated_at'][:16]}  tags={r['tags'] or '-'}"))
            for hit in r["hits"]:
                role_icon = "🧑" if hit["role"] == "user" else ("🤖" if hit["role"] == "assistant" else "🔩")
                print(c(GRAY, f"    [{hit['seq']:3d}] {role_icon} ") + hit["snippet"])

    # ── /chat tag <id|n> <tags> ──────────────────────────
    elif sub == "tag":
        parts = target.split(None, 1)
        if len(parts) < 2:
            print(c(RED, "  Usage: /chat tag <index or id> <tag1,tag2,...>"))
            return
        sid = _resolve_session_id(parts[0])
        if not sid:
            print(c(RED, f"  ✗ Session not found: '{parts[0]}'"))
            return
        ok = tag_session(sid, parts[1])
        if ok:
            print(c(GREEN, f"  ✓ Added tags to session {sid[:20]}...: {parts[1]}"))
        else:
            print(c(RED, "  ✗ Operation failed"))

    # ── /chat untag <id|n> <tags> ────────────────────────
    elif sub == "untag":
        parts = target.split(None, 1)
        if len(parts) < 2:
            print(c(RED, "  Usage: /chat untag <index or id> <tag1,tag2,...>"))
            return
        sid = _resolve_session_id(parts[0])
        if not sid:
            print(c(RED, f"  ✗ Session not found: '{parts[0]}'"))
            return
        untag_session(sid, parts[1])
        print(c(GREEN, f"  ✓ Removed tags: {parts[1]}"))

    # ── /chat bytag <tag> ────────────────────────────────
    elif sub == "bytag":
        if not target:
            print(c(RED, "  Usage: /chat bytag <tag>"))
            return
        rows = find_sessions_by_tag(target)
        if not rows:
            print(c(GRAY, f"  No sessions found with tag '{target}'."))
            return
        print(c(BOLD, f"\n  Sessions tagged '{target}' ({len(rows)}):"))
        for i, r in enumerate(rows):
            print(c(GRAY, f"  [{i + 1:2d}] ") + c(CYAN, r["id"][:24]) +
                  c(GRAY, f"  {r['updated_at'][:16]}  {r['msg_count']} msgs  tags={r['tags']}"))

    # ── /chat link <id1> <id2> [note] ────────────────────
    elif sub == "link":
        parts = target.split(None, 2)
        if len(parts) < 2:
            print(c(RED, "  Usage: /chat link <id/index1> <id/index2> [note]"))
            return
        sid_a = _resolve_session_id(parts[0])
        sid_b = _resolve_session_id(parts[1])
        note = parts[2] if len(parts) > 2 else ""
        if not sid_a or not sid_b:
            print(c(RED, "  ✗ Could not resolve session ID"))
            return
        if sid_a == sid_b:
            print(c(RED, "  ✗ Cannot link a session to itself"))
            return
        link_sessions(sid_a, sid_b, note)
        print(c(GREEN, "  ✓ Linked:"))
        print(c(GRAY, f"    {sid_a[:24]}"))
        print(c(GRAY, f"    {sid_b[:24]}"))
        if note:
            print(c(GRAY, f"    Note: {note}"))

    # ── /chat unlink <id1> <id2> ─────────────────────────
    elif sub == "unlink":
        parts = target.split(None, 1)
        if len(parts) < 2:
            print(c(RED, "  Usage: /chat unlink <id/index1> <id/index2>"))
            return
        sid_a = _resolve_session_id(parts[0])
        sid_b = _resolve_session_id(parts[1])
        if not sid_a or not sid_b:
            print(c(RED, "  ✗ Could not resolve session ID"))
            return
        unlink_sessions(sid_a, sid_b)
        print(c(GREEN, f"  ✓ Unlinked {sid_a[:20]} <-> {sid_b[:20]}"))

    # ── /chat related <id|n> ─────────────────────────────
    elif sub == "related":
        if not target:
            print(c(RED, "  Usage: /chat related <index or id>"))
            return
        sid = _resolve_session_id(target)
        if not sid:
            print(c(RED, f"  ✗ Session not found: '{target}'"))
            return
        linked = get_linked_sessions(sid)
        if not linked:
            print(c(GRAY, f"  Session {sid[:24]} has no linked conversations."))
            print(c(GRAY, "  Use /chat link to create a link."))
            return
        print(c(BOLD, f"\n  Linked conversations for session {sid[:24]} ({len(linked)}):"))
        for item in linked:
            m = item["meta"]
            note = item["note"]
            print(c(CYAN, f"  {m['id'][:24]}") +
                  c(GRAY, f"  {m['updated_at'][:16]}  {m['msg_count']} msgs  model={m['model']}"))
            if note:
                print(c(GRAY, f"    Note: {note}"))
            print()

    else:
        print(c(GRAY, (
            f"  Unknown sub-command '{sub}'.\n"
            "  Available: list · view · export · find · tag · untag · bytag · link · unlink · related"
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
    print(c(GREEN, f"  ✓ Saved session_id={sid}"))


@register("/load")
async def cmd_load(ctx: CommandContext) -> None:
    if not ctx.arg:
        print(c(RED, "  Usage: /load <name or index>"))
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
        # /resume <n> restores the specified sequence directly.
        result = session_load(session, arg)
        print(c(GREEN if result.startswith("OK") else RED, f"  {result}"))
        if result.startswith("OK"):
            logger.debug("session_load OK (resume), msgs to display: {}", len(session.messages))
            set_deferred_history(session.messages)
        return
    # /resume lists recent sessions and lets the user choose interactively.
    rows = list_sessions(10)
    if not rows:
        print(c(GRAY, "  No saved sessions."))
        return
    print(c(BOLD, "\n  Recent sessions:"))
    for i, r in enumerate(rows):
        name = r["name"] or "(untitled)"
        ts = str(r["updated_at"])[:16] if r["updated_at"] else ""
        msgs = r["msg_count"] if r["msg_count"] else 0
        model = r["model"] if r["model"] else ""
        print(
            c(GRAY, f"  [{i+1:2d}] ") +
            c(CYAN, name) +
            c(GRAY, f"  {ts}  {msgs} msgs  model={model}")
        )
    print(c(GRAY, "\n  Enter an index to resume, or press Enter to cancel."))
    try:
        pick = input(cp(BOLD, "  Select [1-" + str(len(rows)) + "]: ")).strip()
        if pick.isdigit():
            idx = int(pick) - 1
            if 0 <= idx < len(rows):
                result = session_load(session, str(idx + 1))
                print(c(GREEN if result.startswith("OK") else RED, f"  {result}"))
                if result.startswith("OK"):
                    set_deferred_history(session.messages)
            else:
                print(c(RED, "  Selection out of range"))
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
    print(c(BOLD, f"\n  Saved sessions (DB: {DB_PATH}):"))
    print(session_list())


@register("/del")
async def cmd_del(ctx: CommandContext) -> None:
    if not ctx.arg:
        print(c(RED, "  Usage: /del <name or index>"))
        return
    result = session_delete(ctx.session, ctx.arg)
    print(c(GREEN if result.startswith("OK") else RED, f"  {result}"))


@register("/rename")
async def cmd_rename(ctx: CommandContext) -> None:
    if not ctx.arg or not ctx.arg2:
        print(c(RED, "  Usage: /rename <index or name> <new name>"))
        return
    result = session_rename(ctx.session, ctx.arg, ctx.arg2)
    print(c(GREEN if result.startswith("OK") else RED, f"  {result}"))


# ── Knowledge: /memorize /forget ────────────────────────────
@register("/memorize")
async def cmd_memorize(ctx: CommandContext) -> None:
    topic = (ctx.arg + " " + ctx.arg2).strip() or "general"
    print(c(YELLOW, f"  🧠 Summarizing '{topic}'..."))
    result = memorize(ctx.session, topic)
    print(c(GREEN if result.startswith("OK") else RED, f"  {result}"))


@register("/forget")
async def cmd_forget(ctx: CommandContext) -> None:
    if not ctx.arg:
        print(c(RED, "  Usage: /forget <id>"))
        return
    try:
        delete_knowledge(int(ctx.arg))
        print(c(GREEN, f"  ✓ Deleted knowledge entry id={ctx.arg}"))
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
                print(c(GREEN, f"  ✓ Pinned message [{seq}] [{role}]: {preview}"))
            else:
                print(c(RED, f"  ✗ Index {seq} out of range ({len(non_sys)} non-system messages)"))
        except ValueError:
            print(c(RED, "  Usage: /pin msg <index>  (use /history first)"))
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
        print(c(GREEN, f"  ✓ Pinned latest {count} messages"))


@register("/unpin")
async def cmd_unpin(ctx: CommandContext) -> None:
    count = sum(1 for m in ctx.session.messages if m.pop("_pinned", None))
    print(c(GREEN, f"  ✓ Unpinned {count} messages"))


@register("/undo")
async def cmd_undo(ctx: CommandContext) -> None:
    n = int(ctx.arg) if ctx.arg.isdigit() else 1
    removed, _last_text = ctx.session.undo(n)
    if removed:
        ctx.session._autosave()
        print(c(GREEN, f"  ↩ Undid {removed} messages"))
    else:
        print(c(GRAY, "  ↩ Nothing to undo"))


# ── /compact ────────────────────────────────────────────────
@register("/compact")
async def cmd_compact(ctx: CommandContext) -> None:
    """Lightweight summary → clear (preserve pins) → summary as first msg."""
    session = ctx.session
    _summary_prompt = (
        "Summarize the following conversation in 3-5 sentences: key progress, "
        "confirmed conclusions, and remaining tasks. Preserve technical details "
        "such as offsets, addresses, and file paths. Output only the summary."
    )
    _compact_msgs = [
        m for m in session.messages
        if m.get("role") != "system" and not m.get("_pinned")
    ]
    if len(_compact_msgs) < 2:
        print(c(GRAY, "  ↕ Context is too short to compact."))
        return

    print(c(CYAN, "  🔄 Compacting context..."))
    _summarize_msgs = [
        {"role": "system", "content": "You are a conversation summarization assistant."},
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
                print(c(RED, f"  ✗ Summary generation failed: {delta['_error']}"))
                _summary_buf = ""
                break
            choices = delta.get("choices") or []
            if not choices:
                continue
            chunk = choices[0].get("delta", {}).get("content", "")
            if chunk:
                _summary_buf += chunk
    except Exception as e:
        print(c(RED, f"  ✗ Summary error: {e}"))
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
            f"  ✓ Compacted | kept {len(pinned)} pinned messages + summary | "
            f"context: {_chars//4:,} tokens"
        ))


# ── /think ──────────────────────────────────────────────────
@register("/think")
async def cmd_think(ctx: CommandContext) -> None:
    session = ctx.session
    arg = ctx.arg
    if not arg:
        print(c(RED, "  Usage: /think <prompt>  (single reasoning-mode turn)"))
        return
    # Single trigger: switch to a reasoning worker for this request when possible.
    _think_alias = None
    for _candidate in ("ds-v4-pro", "ds-v4-flash"):
        _ok, _ = validate_api_key(_candidate)
        if _ok:
            _think_alias = _candidate
            break
    if _think_alias:
        old_alias = session.model_alias
        session.model_alias = _think_alias
        print(c(MAGENTA, f"  🧠 Reasoning mode: {old_alias} -> {_think_alias}"))
        try:
            session.run_turn(arg)
        finally:
            session.model_alias = old_alias
            print(c(GRAY, f"  ↩ Restored model: {old_alias}"))
    else:
        # No reasoning worker is available; run with the current model and prefix the instruction.
        _think_prefix = (
            "[THINKING MODE] Reason carefully step by step before answering.\n\n"
        )
        session.run_turn(_think_prefix + arg)


# ── /mode ───────────────────────────────────────────────────
@register("/mode")
async def cmd_mode(ctx: CommandContext) -> None:
    import config

    _runtime_state.debug_mode = not _runtime_state.debug_mode
    _runtime_state.user_mode = not _runtime_state.debug_mode
    config.USER_MODE = _runtime_state.user_mode
    if _runtime_state.user_mode:
        print(c(GREEN, "  ✓ User-friendly mode enabled (tool details hidden)"))
    else:
        print(c(CYAN, "  ✓ Debug mode enabled (tool calls and diagnostics visible)"))
