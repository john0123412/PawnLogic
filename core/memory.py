"""
core/memory.py — SQLite 数据库管理器（1.0 对话存储扩展版）

1.0 新增：
  · sessions 表新增 tags 列（逗号分隔标签）
  · session_links 表（双向关联两个会话）
  · full_text_search() 跨会话全文检索消息内容
  · get_session_with_stats() 获取单个会话的统计摘要
  · tag_session() / untag_session() / link_sessions() / get_linked_sessions()

并发优化（来自 concurrent_fix）：
  · threading.local() 线程本地连接
  · busy_timeout = 200ms
  · PRAGMA 性能调优
  · 增量消息保存
"""

import sqlite3, json, re, os, hashlib, threading
from datetime import datetime
from pathlib import Path
from config import DB_PATH

# ════════════════════════════════════════════════════════
# 线程本地连接池
# ════════════════════════════════════════════════════════

_tls = threading.local()

def _get_tls_conn() -> sqlite3.Connection:
    conn = getattr(_tls, "conn", None)
    if conn is not None:
        try:
            conn.execute("SELECT 1"); return conn
        except sqlite3.ProgrammingError:
            pass

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=0.2, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        PRAGMA journal_mode       = WAL;
        PRAGMA synchronous        = NORMAL;
        PRAGMA foreign_keys       = ON;
        PRAGMA cache_size         = -8000;
        PRAGMA temp_store         = MEMORY;
        PRAGMA mmap_size          = 67108864;
        PRAGMA wal_autocheckpoint = 100;
    """)
    _tls.conn = conn
    return conn

def get_conn() -> sqlite3.Connection:
    return _get_tls_conn()

# ════════════════════════════════════════════════════════
# 建表（幂等）
# ════════════════════════════════════════════════════════

def init_db():
    _create_core_tables()
    init_facts_table()

def _create_core_tables():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id         TEXT PRIMARY KEY,
            name       TEXT DEFAULT '',
            model      TEXT NOT NULL,
            cwd        TEXT NOT NULL,
            config     TEXT NOT NULL,
            tags       TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id   TEXT    NOT NULL,
            seq          INTEGER NOT NULL,
            role         TEXT    NOT NULL,
            content      TEXT,
            tool_calls   TEXT,
            tool_call_id TEXT,
            is_pinned    INTEGER DEFAULT 0,
            created_at   TEXT    NOT NULL,
            UNIQUE (session_id, seq),
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS knowledge (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            topic          TEXT NOT NULL,
            content        TEXT NOT NULL,
            tags           TEXT DEFAULT '',
            source_session TEXT,
            created_at     TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS session_links (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_a  TEXT NOT NULL,
            session_b  TEXT NOT NULL,
            note       TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE (session_a, session_b)
        );

        CREATE INDEX IF NOT EXISTS idx_msg_session   ON messages(session_id, seq);
        CREATE INDEX IF NOT EXISTS idx_knowledge_topic ON knowledge(topic);
        CREATE INDEX IF NOT EXISTS idx_msg_content   ON messages(content);
        CREATE INDEX IF NOT EXISTS idx_session_tags  ON sessions(tags);
        """)

    # 迁移旧库：给 sessions 表加 tags 列（若不存在）
    with get_conn() as conn:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()]
        if "tags" not in cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN tags TEXT DEFAULT ''")

# init_facts_table is defined later; init_db calls it after both are loaded.

# ════════════════════════════════════════════════════════
# 工具函数
# ════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")

def _gen_id(seed: str = "") -> str:
    raw = f"{datetime.now().isoformat()}{seed}{os.getpid()}"
    return datetime.now().strftime("%Y%m%d%H%M%S") + "_" + hashlib.md5(raw.encode()).hexdigest()[:6]

# ════════════════════════════════════════════════════════
# 增量保存跟踪器
# ════════════════════════════════════════════════════════

_last_saved_seq:  dict[str, int]             = {}
_pinned_snapshot: dict[str, dict[int, int]]  = {}

def _build_rows(session_id: str, messages: list) -> list[tuple]:
    now = _now(); rows = []; seq = 0
    for m in messages:
        if m.get("role") == "system": continue
        rows.append((
            session_id, seq, m.get("role",""), m.get("content") or "",
            json.dumps(m["tool_calls"]) if m.get("tool_calls") else None,
            m.get("tool_call_id"), 1 if m.get("_pinned") else 0, now,
        ))
        seq += 1
    return rows

# ════════════════════════════════════════════════════════
# Sessions CRUD
# ════════════════════════════════════════════════════════

def upsert_session(session_id: str, name: str, model: str, cwd: str, config_dict: dict,
                   tags: str = ""):
    now = _now()
    with get_conn() as conn:
        existing = conn.execute("SELECT created_at, tags FROM sessions WHERE id=?", (session_id,)).fetchone()
        created  = existing["created_at"] if existing else now
        old_tags = existing["tags"] if existing else tags
        # 保留已有 tags
        final_tags = old_tags if old_tags else tags
        conn.execute("""
            INSERT OR REPLACE INTO sessions (id, name, model, cwd, config, tags, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (session_id, name, model, cwd, json.dumps(config_dict), final_tags, created, now))

def list_sessions(limit: int = 20) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("""
            SELECT s.id, s.name, s.model, s.cwd, s.tags, s.created_at, s.updated_at,
                   COUNT(m.id) AS msg_count
            FROM sessions s
            LEFT JOIN messages m ON s.id = m.session_id
            GROUP BY s.id
            ORDER BY s.updated_at DESC
            LIMIT ?
        """, (limit,)).fetchall()

def get_session(session_id: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()

def delete_session(session_id: str):
    _last_saved_seq.pop(session_id, None)
    _pinned_snapshot.pop(session_id, None)
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))

# ════════════════════════════════════════════════════════
# 标签管理
# ════════════════════════════════════════════════════════

def tag_session(session_id: str, new_tags: str) -> bool:
    """
    给会话追加标签（不覆盖已有标签）。
    new_tags: 逗号分隔字符串，如 "pwn,ctf,heap"
    """
    with get_conn() as conn:
        row = conn.execute("SELECT tags FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not row: return False
        existing = set(t.strip() for t in (row["tags"] or "").split(",") if t.strip())
        new      = set(t.strip() for t in new_tags.split(",") if t.strip())
        merged   = ",".join(sorted(existing | new))
        conn.execute("UPDATE sessions SET tags=? WHERE id=?", (merged, session_id))
        return True

def untag_session(session_id: str, remove_tags: str) -> bool:
    """删除指定标签。"""
    with get_conn() as conn:
        row = conn.execute("SELECT tags FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not row: return False
        existing = set(t.strip() for t in (row["tags"] or "").split(",") if t.strip())
        remove   = set(t.strip() for t in remove_tags.split(",") if t.strip())
        merged   = ",".join(sorted(existing - remove))
        conn.execute("UPDATE sessions SET tags=? WHERE id=?", (merged, session_id))
        return True

def find_sessions_by_tag(tag: str) -> list[sqlite3.Row]:
    """模糊匹配 tag，返回包含该 tag 的会话列表。"""
    with get_conn() as conn:
        return conn.execute("""
            SELECT s.id, s.name, s.model, s.cwd, s.tags, s.created_at, s.updated_at,
                   COUNT(m.id) AS msg_count
            FROM sessions s
            LEFT JOIN messages m ON s.id = m.session_id
            WHERE s.tags LIKE ?
            GROUP BY s.id
            ORDER BY s.updated_at DESC
        """, (f"%{tag}%",)).fetchall()

# ════════════════════════════════════════════════════════
# 关联会话
# ════════════════════════════════════════════════════════

def link_sessions(session_a: str, session_b: str, note: str = "") -> bool:
    """双向关联两个会话（存储单向，查询时双向）。"""
    # 规范化顺序（避免 (a,b) 和 (b,a) 重复）
    a, b = sorted([session_a, session_b])
    try:
        with get_conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO session_links (session_a, session_b, note, created_at)
                VALUES (?, ?, ?, ?)
            """, (a, b, note, _now()))
        return True
    except sqlite3.OperationalError:
        return False

def unlink_sessions(session_a: str, session_b: str):
    """取消关联。"""
    a, b = sorted([session_a, session_b])
    with get_conn() as conn:
        conn.execute("DELETE FROM session_links WHERE session_a=? AND session_b=?", (a, b))

def get_linked_sessions(session_id: str) -> list[sqlite3.Row]:
    """获取与指定会话相关联的所有会话，含备注。"""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT CASE WHEN session_a=? THEN session_b ELSE session_a END AS other_id,
                   note, created_at
            FROM session_links
            WHERE session_a=? OR session_b=?
        """, (session_id, session_id, session_id)).fetchall()
    if not rows:
        return []
    # 补充会话元数据
    result = []
    with get_conn() as conn:
        for row in rows:
            sid  = row["other_id"]
            meta = conn.execute("""
                SELECT s.id, s.name, s.model, s.tags, s.updated_at, COUNT(m.id) AS msg_count
                FROM sessions s LEFT JOIN messages m ON s.id = m.session_id
                WHERE s.id=? GROUP BY s.id
            """, (sid,)).fetchone()
            if meta:
                result.append({"meta": meta, "note": row["note"], "linked_at": row["created_at"]})
    return result

# ════════════════════════════════════════════════════════
# 对话全文检索
# ════════════════════════════════════════════════════════

def full_text_search(query: str, limit: int = 20) -> list[dict]:
    """
    在所有会话的消息内容中搜索关键词。
    返回列表，每项含：session 元数据 + 命中的消息片段。
    支持多词搜索（空格分隔，AND 语义）。
    """
    keywords = [w.strip() for w in query.split() if w.strip()]
    if not keywords:
        return []

    # SQLite LIKE 多词 AND 过滤（不依赖 FTS5 插件）
    like_clauses = " AND ".join("content LIKE ?" for _ in keywords)
    params       = tuple(f"%{kw}%" for kw in keywords)

    with get_conn() as conn:
        hits = conn.execute(f"""
            SELECT m.session_id, m.seq, m.role, m.content, m.created_at
            FROM messages m
            WHERE {like_clauses}
            ORDER BY m.created_at DESC
            LIMIT ?
        """, (*params, limit * 3)).fetchall()   # 多拉一些，后面按 session 去重

    if not hits:
        return []

    # 按 session_id 聚合，每个 session 最多显示前 3 条命中
    session_hits: dict[str, list] = {}
    for row in hits:
        sid = row["session_id"]
        if sid not in session_hits:
            session_hits[sid] = []
        if len(session_hits[sid]) < 3:
            session_hits[sid].append(row)
        if len(session_hits) >= limit:
            break

    # 补充会话元数据
    result = []
    with get_conn() as conn:
        for sid, msg_rows in session_hits.items():
            meta = conn.execute("""
                SELECT id, name, model, tags, updated_at FROM sessions WHERE id=?
            """, (sid,)).fetchone()
            if not meta:
                continue
            result.append({
                "session_id":   sid,
                "session_name": meta["name"] or sid,
                "model":        meta["model"],
                "tags":         meta["tags"] or "",
                "updated_at":   meta["updated_at"],
                "hits": [
                    {
                        "seq":     r["seq"],
                        "role":    r["role"],
                        "snippet": _extract_snippet(r["content"] or "", keywords),
                    }
                    for r in msg_rows
                ],
            })
    return result

def _extract_snippet(content: str, keywords: list[str], window: int = 80) -> str:
    """
    提取包含关键词的上下文片段（±window 字符）。
    高亮显示（大写标记）命中的关键词。
    """
    content_lower = content.lower()
    for kw in keywords:
        pos = content_lower.find(kw.lower())
        if pos != -1:
            start = max(0, pos - window)
            end   = min(len(content), pos + len(kw) + window)
            snippet = content[start:end].replace("\n", " ")
            if start > 0:    snippet = "…" + snippet
            if end < len(content): snippet = snippet + "…"
            return snippet
    return content[:window * 2].replace("\n", " ") + "…"

# ════════════════════════════════════════════════════════
# 会话完整内容读取（用于 /chat view）
# ════════════════════════════════════════════════════════

def get_session_messages_pretty(session_id: str) -> list[dict]:
    """
    读取某个会话的所有消息，返回适合展示的格式化列表。
    每项：{seq, role, content_preview, content_full, is_pinned, created_at}
    """
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT seq, role, content, tool_calls, tool_call_id, is_pinned, created_at
            FROM messages WHERE session_id=?
            ORDER BY seq ASC
        """, (session_id,)).fetchall()

    result = []
    for r in rows:
        content = r["content"] or ""
        if not content and r["tool_calls"]:
            # assistant 工具调用消息：展示工具名列表
            try:
                calls = json.loads(r["tool_calls"])
                names = [c["function"]["name"] for c in calls if "function" in c]
                content = f"[调用工具: {', '.join(names)}]"
            except Exception:
                content = "[tool_calls]"
        if r["role"] == "tool":
            content = f"[工具结果 call_id={r['tool_call_id']}] " + content[:200]

        result.append({
            "seq":          r["seq"],
            "role":         r["role"],
            "content_full": r["content"] or "",
            "preview":      content[:120].replace("\n", " "),
            "is_pinned":    bool(r["is_pinned"]),
            "created_at":   r["created_at"],
        })
    return result

def export_session_to_markdown(session_id: str) -> str:
    """
    将一个会话导出为 Markdown 字符串。
    可通过 /chat export 写到本地文件。
    """
    meta = get_session(session_id)
    if not meta:
        return f"ERROR: 会话 {session_id} 不存在"

    lines = [
        f"# PawnLogic 对话导出",
        f"",
        f"| 字段 | 值 |",
        f"|------|----|",
        f"| session_id | `{session_id}` |",
        f"| 名称 | {meta['name'] or '(未命名)'} |",
        f"| 模型 | {meta['model']} |",
        f"| 目录 | `{meta['cwd']}` |",
        f"| 标签 | {meta['tags'] or '-'} |",
        f"| 创建 | {meta['created_at']} |",
        f"| 更新 | {meta['updated_at']} |",
        f"",
        f"---",
        f"",
    ]

    msgs = get_session_messages_pretty(session_id)
    for m in msgs:
        role    = m["role"]
        pinned  = " 📌" if m["is_pinned"] else ""
        ts      = m["created_at"][11:16] if m["created_at"] else ""
        content = m["content_full"]

        if role == "user":
            lines.append(f"## 🧑 用户  `[{m['seq']}]`{pinned}  {ts}")
            lines.append(f"")
            lines.append(content)
            lines.append(f"")
        elif role == "assistant":
            if content.startswith("[调用工具:"):
                lines.append(f"## 🔧 工具调用  `[{m['seq']}]`  {ts}")
                lines.append(f"")
                lines.append(f"> {m['preview']}")
                lines.append(f"")
            else:
                lines.append(f"## 🤖 助手  `[{m['seq']}]`{pinned}  {ts}")
                lines.append(f"")
                lines.append(content)
                lines.append(f"")
        elif role == "tool":
            lines.append(f"<details><summary>🔩 工具结果 [{m['seq']}]</summary>")
            lines.append(f"")
            lines.append(f"```")
            lines.append(content[:1000])
            if len(content) > 1000:
                lines.append(f"...[共 {len(content)} 字符，已截断]...")
            lines.append(f"```")
            lines.append(f"</details>")
            lines.append(f"")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)

# ════════════════════════════════════════════════════════
# Messages CRUD（增量保存）
# ════════════════════════════════════════════════════════

def save_messages(session_id: str, messages: list):
    all_rows      = _build_rows(session_id, messages)
    current_total = len(all_rows)
    last_seq      = _last_saved_seq.get(session_id, -1)
    prev_pins     = _pinned_snapshot.get(session_id, {})
    needs_full    = (last_seq == -1 or current_total < last_seq + 1)

    try:
        with get_conn() as conn:
            if needs_full:
                conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
                if all_rows:
                    conn.executemany("""
                        INSERT INTO messages
                            (session_id, seq, role, content, tool_calls, tool_call_id, is_pinned, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, all_rows)
            else:
                new_rows = [r for r in all_rows if r[1] > last_seq]
                if new_rows:
                    conn.executemany("""
                        INSERT OR REPLACE INTO messages
                            (session_id, seq, role, content, tool_calls, tool_call_id, is_pinned, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, new_rows)
                cur_pins = {r[1]: r[6] for r in all_rows}
                for seq_idx, pinned in cur_pins.items():
                    if prev_pins.get(seq_idx, 0) != pinned:
                        conn.execute(
                            "UPDATE messages SET is_pinned=? WHERE session_id=? AND seq=?",
                            (pinned, session_id, seq_idx),
                        )
        _last_saved_seq[session_id]  = current_total - 1
        _pinned_snapshot[session_id] = {r[1]: r[6] for r in all_rows}
    except sqlite3.OperationalError:
        pass   # busy → 静默，下次重试

def load_messages(session_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id=? ORDER BY seq ASC", (session_id,)
        ).fetchall()
    result = []
    for r in rows:
        m: dict = {"role": r["role"], "content": r["content"]}
        if r["tool_calls"]:
            try: m["tool_calls"] = json.loads(r["tool_calls"])
            except: pass
        if r["tool_call_id"]: m["tool_call_id"] = r["tool_call_id"]
        if r["is_pinned"]:    m["_pinned"] = True
        result.append(m)
    _last_saved_seq[session_id]  = len(result) - 1
    _pinned_snapshot[session_id] = {}
    return result

def pin_message_by_seq(session_id: str, seq: int, pinned: bool = True) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE messages SET is_pinned=? WHERE session_id=? AND seq=?",
            (1 if pinned else 0, session_id, seq),
        )
        if session_id in _pinned_snapshot:
            _pinned_snapshot[session_id][seq] = 1 if pinned else 0
        return cur.rowcount > 0

def reset_incremental_tracker(session_id: str):
    _last_saved_seq.pop(session_id, None)
    _pinned_snapshot.pop(session_id, None)

# ════════════════════════════════════════════════════════
# Knowledge CRUD + RAG
# ════════════════════════════════════════════════════════

def add_knowledge(topic: str, content: str, tags: str = "", source_session: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO knowledge (topic, content, tags, source_session, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (topic, content, tags, source_session, _now()))
        return cur.lastrowid

def list_knowledge(limit: int = 30) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM knowledge ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()

def delete_knowledge(kid: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM knowledge WHERE id=?", (kid,))

def search_knowledge(query: str, limit: int = 5) -> list[sqlite3.Row]:
    keywords = list(set(re.findall(r'[a-zA-Z\u4e00-\u9fff]\w*', query.lower())))
    if not keywords: return list_knowledge(limit)
    with get_conn() as conn:
        all_rows = conn.execute("SELECT * FROM knowledge ORDER BY created_at DESC").fetchall()
    scored = []
    for row in all_rows:
        text  = (row["topic"] + " " + row["content"] + " " + (row["tags"] or "")).lower()
        score = sum(1 for kw in keywords if kw in text)
        if score > 0: scored.append((score, row))
    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:limit]]

def format_knowledge_for_prompt(rows: list[sqlite3.Row]) -> str:
    if not rows: return ""
    lines = ["[Persistent Knowledge — auto-loaded from your knowledge base]"]
    for r in rows:
        lines.append(f"• [{r['topic']}] {r['content']}")
        if r["tags"]: lines.append(f"  tags: {r['tags']}")
    return "\n".join(lines)

# ════════════════════════════════════════════════════════
# Persistent Agent Facts — Key-Value MemoryStore (2.1.0 新增)
#
# 用途：跨会话、跨 delegate_task 的持久化事实存储。
# 解决"上下文失忆"问题——即使 /clear 或新 delegate_task 启动，
# 之前 save_fact 的内容仍然可以被 query_fact 取出。
#
# API 摘要：
#   save_fact(key, value, namespace)  → 写入/更新一条事实
#   query_fact(key, namespace)        → 精确读取单条（返回 str | None）
#   search_facts(query_text, ...)     → 关键词模糊搜索多条
#   delete_fact(key, namespace)       → 删除单条
#   list_facts(namespace, limit)      → 列出所有事实
#   format_facts_for_prompt(rows)     → 格式化为注入 Prompt 的文本块
# ════════════════════════════════════════════════════════

def init_facts_table():
    """Create agent_facts table (idempotent). Called automatically by init_db()."""
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_facts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            namespace   TEXT    NOT NULL DEFAULT 'global',
            key         TEXT    NOT NULL,
            value       TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL,
            UNIQUE (namespace, key)
        );
        CREATE INDEX IF NOT EXISTS idx_facts_ns_key ON agent_facts(namespace, key);
        """)
        # 迁移：为旧库加 namespace 列（若不存在）
        cols = [row[1] for row in conn.execute("PRAGMA table_info(agent_facts)").fetchall()]
        if cols and "namespace" not in cols:
            conn.execute("ALTER TABLE agent_facts ADD COLUMN namespace TEXT NOT NULL DEFAULT 'global'")


def save_fact(key: str, value: str, namespace: str = "global") -> str:
    """
    Upsert a fact into the persistent K/V store.
    Survives /clear, session switches, and delegate_task re-spawns.

    Args:
        key:       Identifier, e.g. "libc_version", "target_arch", "last_offset"
        value:     String value (serialize complex objects as JSON before calling)
        namespace: Logical bucket, e.g. "global", "project:heap_exploit", session_id
    """
    init_facts_table()
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO agent_facts (namespace, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(namespace, key)
            DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """, (namespace, key, str(value), _now()))
    return f"OK: fact saved  [{namespace}] {key!r} = {str(value)[:80]}"


def query_fact(key: str, namespace: str = "global") -> str | None:
    """
    Retrieve a single fact by exact key.
    Returns the value string, or None if not found.
    """
    init_facts_table()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM agent_facts WHERE namespace=? AND key=?",
            (namespace, key),
        ).fetchone()
    return row["value"] if row else None


def search_facts(
    query_text: str,
    namespace: str | None = None,
    limit: int = 10,
) -> list[sqlite3.Row]:
    """
    Keyword search across fact keys and values.
    Used by session._reset_system_prompt to auto-inject relevant facts.
    """
    init_facts_table()
    keywords = list(set(re.findall(r'[a-zA-Z\u4e00-\u9fff]\w*', query_text.lower())))
    with get_conn() as conn:
        if namespace:
            rows = conn.execute(
                "SELECT * FROM agent_facts WHERE namespace=? ORDER BY updated_at DESC",
                (namespace,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agent_facts ORDER BY updated_at DESC"
            ).fetchall()
    if not keywords:
        return list(rows[:limit])
    scored = []
    for row in rows:
        text  = (row["key"] + " " + row["value"] + " " + row["namespace"]).lower()
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:limit]]


def delete_fact(key: str, namespace: str = "global") -> bool:
    """Delete a fact. Returns True if it existed."""
    init_facts_table()
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM agent_facts WHERE namespace=? AND key=?",
            (namespace, key),
        )
    return cur.rowcount > 0


def list_facts(
    namespace: str | None = None,
    limit: int = 50,
) -> list[sqlite3.Row]:
    """List facts, optionally filtered by namespace."""
    init_facts_table()
    with get_conn() as conn:
        if namespace:
            return conn.execute(
                "SELECT * FROM agent_facts WHERE namespace=? ORDER BY updated_at DESC LIMIT ?",
                (namespace, limit),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM agent_facts ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()


def format_facts_for_prompt(rows: list[sqlite3.Row], max_chars: int = 600) -> str:
    """
    Format fact rows for injection into System Prompt.
    Hard-limited to max_chars to prevent token budget overrun.
    """
    if not rows:
        return ""
    lines = ["[Agent Memory Facts — persistent across sessions]"]
    total = len(lines[0])
    for r in rows:
        entry = f"  [{r['namespace']}] {r['key']} = {str(r['value'])[:120]}"
        if total + len(entry) + 1 > max_chars:
            lines.append(f"  ... ({len(rows) - (len(lines) - 1)} more facts omitted)")
            break
        lines.append(entry)
        total += len(entry) + 1
    return "\n".join(lines)
