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
    save_messages, load_messages, pin_message_by_seq,
    add_knowledge, search_knowledge, format_knowledge_for_prompt, _gen_id,
)
from utils.ansi import c, CYAN, GRAY, GREEN, RED, YELLOW, BOLD

# ════════════════════════════════════════════════════════
# Session 保存 / 加载
# ════════════════════════════════════════════════════════

def session_save(session, name: str = "") -> str:
    """将当前 session 写入 SQLite。返回 session_id。"""
    init_db()
    upsert_session(
        session_id  = session.session_id,
        name        = name.strip() or session.session_id,
        model       = session.model_alias,
        cwd         = session.cwd,
        config_dict = dict(DYNAMIC_CONFIG),
    )
    save_messages(session.session_id, session.messages)
    return session.session_id

def session_load(session, query: str) -> str:
    """按序号或名称子串加载会话。"""
    init_db()
    rows = list_sessions(50)
    if not rows:
        return "ERROR: 数据库中没有已保存的会话。"

    query = query.strip()
    matched = None

    # 按序号（1-indexed）
    try:
        idx     = int(query) - 1
        matched = rows[idx] if 0 <= idx < len(rows) else None
    except ValueError:
        pass

    # 按名称子串
    if not matched:
        for r in rows:
            if query.lower() in (r["name"] or "").lower() or query.lower() in r["id"]:
                matched = r; break

    if not matched:
        listing = "\n".join(
            f"  [{i+1}] {r['id']}  {r['name'] or '(unnamed)'}  {r['updated_at'][:16]}"
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
    try:
        cfg = json.loads(full["config"])
        DYNAMIC_CONFIG.update(cfg)
    except Exception:
        pass

    from tools.file_ops import _session_cwd
    _session_cwd[0] = session.cwd
    session._reset_system_prompt()
    session.messages.extend(msgs)
    session.session_id = sid

    return f"OK: 已加载 [{sid}] {matched['name']} ({len(msgs)} 条消息)"

def session_list() -> str:
    init_db()
    rows = list_sessions(20)
    if not rows:
        return "  (暂无已保存会话)"
    lines = []
    for i, r in enumerate(rows):
        lines.append(
            c(GRAY, f"  [{i+1:2d}] ") +
            c(CYAN, f"{r['id']}") +
            c(GRAY, f"  '{r['name'] or '(unnamed)'}'  "
                    f"{r['updated_at'][:16]}  {r['msg_count']}msgs  model={r['model']}")
        )
    return "\n".join(lines)

def session_delete(session, query: str) -> str:
    rows = list_sessions(50)
    try:    idx = int(query) - 1; sid = rows[idx]["id"]
    except (ValueError, IndexError):
        matched = next((r for r in rows if query.lower() in r["id"]), None)
        if not matched: return f"ERROR: 找不到 '{query}'"
        sid = matched["id"]
    delete_session(sid)
    return f"OK: 已删除会话 {sid}"

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
