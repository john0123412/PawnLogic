"""
core/persistence.py — 会话持久化对外接口
底层改为 SQLite（core/memory.py），废弃原 JSON 文件方案。
新增：memorize() — 调用 API 总结对话片段存入 knowledge 表。
"""

import json
import urllib.request, urllib.error
from config import DYNAMIC_CONFIG, DEFAULT_MODEL, get_api_config
from core.memory import (
    init_db, upsert_session, list_sessions, get_session, delete_session,
    rename_session, save_messages, load_messages, pin_message_by_seq,
    add_knowledge, search_knowledge, format_knowledge_for_prompt, _gen_id,
)
from core.naming import stable_workspace_dir
from utils.ansi import c, CYAN, GRAY, GREEN, RED, YELLOW, BOLD

# ════════════════════════════════════════════════════════
# Session 保存 / 加载
# ════════════════════════════════════════════════════════

def session_save(session, name: str = "") -> str:
    """将当前 session 写入 SQLite。返回 session_id。"""
    init_db()
    manual_name = name.strip()
    upsert_session(
        session_id  = session.session_id,
        name        = manual_name,
        model       = session.model_alias,
        cwd         = session.cwd,
        config_dict = dict(DYNAMIC_CONFIG),
        workspace_dir = getattr(session, "workspace_dir", ""),
        name_source = "manual" if manual_name else "",
    )
    save_messages(session.session_id, session.messages)
    return session.session_id

def session_load(session, query: str) -> str:
    """按序号或名称子串加载会话。"""
    init_db()
    rows = list_sessions(50)
    if not rows:
        return "ERROR: 数据库中没有已保存的会话。"

    matched = _resolve_session(rows, query)
    if not matched:
        listing = "\n".join(
            f"  [{i+1}] {r['id']}  {r['name'] or r['auto_name'] or r['workspace_alias'] or '(unnamed)'}  {r['updated_at'][:16]}"
            for i, r in enumerate(rows[:10])
        )
        return f"ERROR: 找不到匹配 '{query}' 的会话。\n已有:\n{listing}"

    sid  = matched["id"]
    full = get_session(sid)
    if not full:
        return f"ERROR: session {sid} 元数据丢失"

    # 还原 messages
    msgs = load_messages(sid)
    session.messages.clear()
    session.model_alias = full["model"]
    session.cwd         = full["cwd"]
    session.workspace_dir = full["workspace_dir"] or stable_workspace_dir(sid)
    if not full["workspace_dir"]:
        upsert_session(
            session_id=sid,
            name="",
            model=session.model_alias,
            cwd=session.cwd,
            config_dict=dict(DYNAMIC_CONFIG),
            workspace_dir=session.workspace_dir,
        )
    try:
        cfg = json.loads(full["config"])
        DYNAMIC_CONFIG.update(cfg)
    except Exception:
        pass

    from tools.file_ops import _session_cwd, _session_workspace_dir
    _session_cwd[0] = session.cwd
    _session_workspace_dir[0] = session.workspace_dir
    session._reset_system_prompt()
    session.messages.extend(msgs)
    session.session_id = sid
    if hasattr(session, "_naming_done"):
        session._naming_done = bool(full["auto_name"])
    if hasattr(session, "_naming_attempted_at"):
        session._naming_attempted_at = 0.0

    # 显示对话历史
    _display_session_history(msgs)

    display_name = full["name"] or full["auto_name"] or matched["name"] or sid
    return f"OK: 已加载 [{sid}] {display_name} ({len(msgs)} 条消息)"

def session_list() -> str:
    init_db()
    rows = list_sessions(20)
    if not rows:
        return "  (暂无已保存会话)"
    lines = []
    for i, r in enumerate(rows):
        display_name = r["name"] or r["auto_name"] or r["workspace_alias"] or "(unnamed)"
        lines.append(
            c(GRAY, f"  [{i+1:2d}] ") +
            c(CYAN, f"{r['id']}") +
            c(GRAY, f"  '{display_name}'  "
                    f"{r['updated_at'][:16]}  {r['msg_count']}msgs  model={r['model']}")
        )
    return "\n".join(lines)

def session_delete(session, query: str) -> str:
    rows = list_sessions(50)
    matched = _resolve_session(rows, query)
    if not matched: return f"ERROR: 找不到 '{query}'"
    delete_session(matched["id"])
    return f"OK: 已删除会话 {matched['id']}"


def _resolve_session(rows, query: str):
    """从 list_sessions 结果中按序号或名称子串查找会话。返回 Row 或 None。"""
    query = query.strip()
    try:
        idx = int(query) - 1
        if 0 <= idx < len(rows):
            return rows[idx]
    except ValueError:
        pass
    q = query.lower()
    return next(
        (r for r in rows if
         q in (r["name"] or "").lower() or
         q in (r["auto_name"] or "").lower() or
         q in (r["workspace_alias"] or "").lower() or
         q in r["id"]),
        None,
    )


def session_rename(session, query: str, new_name: str) -> str:
    """按序号或名称子串找到会话并重命名。"""
    init_db()
    rows = list_sessions(50)
    matched = _resolve_session(rows, query)
    if not matched:
        return f"ERROR: 找不到匹配 '{query}' 的会话"
    rename_session(matched["id"], new_name.strip())
    return f"OK: 已重命名 [{matched['id']}] → '{new_name.strip()}'"


def _display_session_history(msgs: list, show_recent: int = 6):
    """在终端显示会话对话历史。最近 show_recent 条完整显示，更早的折叠。"""
    from config import smart_truncate

    # 过滤出 user/assistant 消息用于显示
    displayable = []
    for i, m in enumerate(msgs):
        role = m.get("role", "")
        if role in ("user", "assistant", "tool"):
            displayable.append((i, m))

    total = len(displayable)
    if total == 0:
        print(c(GRAY, "\n  (空会话)\n"))
        return

    sep = "─" * 44
    print(c(GRAY, f"\n  ── 对话历史 ({total} 条) {sep}"))

    # 分割：折叠部分 + 显示部分
    if total > show_recent:
        folded_count = total - show_recent
        print(c(GRAY, f"  │ ... 更早 {folded_count} 条消息（数据已完整加载，共 {total} 条）..."))
        display_slice = displayable[-show_recent:]
    else:
        display_slice = displayable

    for j, (orig_idx, m) in enumerate(display_slice):
        role = m.get("role", "")
        content = m.get("content") or ""
        is_last = (j == len(display_slice) - 1)
        branch = "└" if is_last else "├"

        if role == "user":
            preview = content[:120].replace("\n", " ")
            print(f"  {branch} {c(CYAN, '[user]'):14} {preview}")

        elif role == "assistant":
            tool_calls = m.get("tool_calls")
            if tool_calls and not content:
                names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
                print(f"  {branch} {c(GREEN, '[assistant]'):14} {c(GRAY, f'[调用工具: {chr(44).join(names)}]')}")
            elif content:
                preview = content[:150].replace("\n", " ")
                print(f"  {branch} {c(GREEN, '[assistant]'):14} {preview}")
            else:
                print(f"  {branch} {c(GREEN, '[assistant]'):14} {c(GRAY, '(空)')}")

        elif role == "tool":
            preview = content[:100].replace("\n", " ")
            print(f"  {branch} {c(YELLOW, '[tool]'):14} {c(GRAY, f'[工具结果] {preview}')}")

    print(c(GRAY, f"  {sep}\n"))


# ════════════════════════════════════════════════════════
# /memorize — AI 摘要 → knowledge 表
# ════════════════════════════════════════════════════════

def memorize(session, topic: str, n_turns: int = 6) -> str:
    """
    取最近 n_turns 条 user/assistant 消息，调用 API 让模型总结，
    存入 knowledge 表。返回操作结果说明。
    """
    # 取最近若干轮对话
    relevant = [
        m for m in session.messages
        if m.get("role") in ("user", "assistant") and m.get("content")
    ][-n_turns * 2:]

    if not relevant:
        return "ERROR: 上下文中没有可供总结的对话。"

    history_text = "\n".join(
        f"[{m['role'].upper()}]: {str(m.get('content',''))[:500]}"
        for m in relevant
    )

    prompt = (
        f"以下是一段对话片段，请从中提取关于主题「{topic}」的核心知识点，"
        f"用简洁的中文（或英文，视内容而定）输出，不超过300字。\n\n"
        f"--- 对话 ---\n{history_text}\n--- 结束 ---\n\n"
        f"只输出知识内容本身，不要解释你在做什么，不要输出标题。"
    )

    base_url, api_key = get_api_config(session.model_alias)
    payload = {
        "model":      session.model["id"],
        "messages":   [{"role": "user", "content": prompt}],
        "max_tokens": 512,
        "stream":     False,
    }
    try:
        req = urllib.request.Request(
            base_url,
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data    = json.loads(resp.read())
            summary = data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"ERROR: 摘要 API 调用失败: {e}"

    # 自动提取简单 tags（取 topic 的词 + 会话 cwd 最后一节）
    tags_parts = [w.lower() for w in topic.split() if len(w) > 2]
    cwd_tag    = session.cwd.rstrip("/").split("/")[-1]
    tags       = ",".join(tags_parts + [cwd_tag])

    kid = add_knowledge(topic, summary, tags, source_session=session.session_id)
    return (
        f"OK: 知识已保存 (id={kid})\n"
        f"  topic : {topic}\n"
        f"  tags  : {tags}\n"
        f"  摘要  : {summary[:120]}{'...' if len(summary)>120 else ''}"
    )
