"""
core/memory.py — SQLite database manager.

Features:
  · sessions.tags column for comma-separated tags
  · session_links table for bidirectional session relationships
  · full_text_search() for cross-session message search
  · get_session_with_stats() for single-session summaries
  · tag_session() / untag_session() / link_sessions() / get_linked_sessions()

Concurrency:
  · threading.local() per-thread connections
  · centralized busy_timeout + write retry/backoff
  · PRAGMA tuning
  · incremental message saving
"""

import sqlite3, json, re, os, hashlib, threading, time
from datetime import datetime
from config import DB_PATH
from core.file_store import ensure_private_dir, ensure_private_file
from core.logger import logger

# ════════════════════════════════════════════════════════
# Thread-local connection pool.
# ════════════════════════════════════════════════════════

_tls = threading.local()
SQLITE_BUSY_TIMEOUT_MS = 1000
SQLITE_WRITE_RETRIES = 4
SQLITE_WRITE_BACKOFF_SEC = (0.05, 0.1, 0.2, 0.4)


def _is_retryable_write_error(exc: sqlite3.OperationalError) -> bool:
    msg = str(exc).lower()
    return "locked" in msg or "busy" in msg


def _write_with_retry(session_id: str, operation: str, write_fn):
    """Run one SQLite write with the shared locked/busy retry policy."""
    sid = session_id or "-"
    for attempt in range(1, SQLITE_WRITE_RETRIES + 1):
        try:
            return write_fn()
        except sqlite3.OperationalError as exc:
            if not _is_retryable_write_error(exc):
                logger.error("{} | {} | retry_count={} | {}", sid, operation, attempt - 1, exc)
                raise
            if attempt >= SQLITE_WRITE_RETRIES:
                logger.error("{} | {} | retry_count={} | {}", sid, operation, attempt, exc)
                raise
            logger.warning("{} | {} | retry_count={} | {}", sid, operation, attempt, exc)
            delay = SQLITE_WRITE_BACKOFF_SEC[min(attempt - 1, len(SQLITE_WRITE_BACKOFF_SEC) - 1)]
            time.sleep(delay)
    return None

def _get_tls_conn() -> sqlite3.Connection:
    conn = getattr(_tls, "conn", None)
    if conn is not None:
        try:
            conn.execute("SELECT 1"); return conn
        except sqlite3.ProgrammingError:
            pass

    ensure_private_dir(DB_PATH.parent)
    conn = sqlite3.connect(
        str(DB_PATH),
        timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    conn.executescript("""
        PRAGMA journal_mode       = WAL;
        PRAGMA synchronous        = NORMAL;
        PRAGMA foreign_keys       = ON;
        PRAGMA cache_size         = -8000;
        PRAGMA temp_store         = MEMORY;
        PRAGMA mmap_size          = 67108864;
        PRAGMA wal_autocheckpoint = 100;
    """)
    ensure_private_file(DB_PATH)
    ensure_private_file(DB_PATH.with_name(DB_PATH.name + "-wal"))
    ensure_private_file(DB_PATH.with_name(DB_PATH.name + "-shm"))
    _tls.conn = conn
    return conn

def get_conn() -> sqlite3.Connection:
    return _get_tls_conn()

# ════════════════════════════════════════════════════════
# Idempotent table creation.
# ════════════════════════════════════════════════════════

def init_db():
    _create_core_tables()
    init_facts_table()
    init_failures_table()

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
            auto_name  TEXT DEFAULT '',
            workspace_dir TEXT DEFAULT '',
            workspace_alias TEXT DEFAULT '',
            name_source TEXT DEFAULT 'auto',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id        TEXT    NOT NULL,
            seq               INTEGER NOT NULL,
            role              TEXT    NOT NULL,
            content           TEXT,
            tool_calls        TEXT,
            tool_call_id      TEXT,
            is_pinned         INTEGER DEFAULT 0,
            reasoning_content TEXT,
            created_at        TEXT    NOT NULL,
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

    # FTS5 full-text search engine. Uses content=messages external-content
    # mode so FTS5 can read from the messages table.
    with get_conn() as conn:
        try:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
                USING fts5(content, session_id, role, content=messages, content_rowid=id)
            """)
            # Keep FTS5 synchronized with messages through triggers.
            conn.executescript("""
                CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                    INSERT INTO messages_fts(rowid, content, session_id, role)
                    VALUES (new.id, new.content, new.session_id, new.role);
                END;

                CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, content, session_id, role)
                    VALUES ('delete', old.id, old.content, old.session_id, old.role);
                END;

                CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, content, session_id, role)
                    VALUES ('delete', old.id, old.content, old.session_id, old.role);
                    INSERT INTO messages_fts(rowid, content, session_id, role)
                    VALUES (new.id, new.content, new.session_id, new.role);
                END;
            """)
        except sqlite3.OperationalError:
            pass  # Gracefully degrade when FTS5 is unavailable.

    # Migrate old DBs. SQLite lacks ADD COLUMN IF NOT EXISTS, so inspect columns first.
    with get_conn() as conn:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()]
        migrations = {
            "tags": "ALTER TABLE sessions ADD COLUMN tags TEXT DEFAULT ''",
            "auto_name": "ALTER TABLE sessions ADD COLUMN auto_name TEXT DEFAULT ''",
            "workspace_dir": "ALTER TABLE sessions ADD COLUMN workspace_dir TEXT DEFAULT ''",
            "workspace_alias": "ALTER TABLE sessions ADD COLUMN workspace_alias TEXT DEFAULT ''",
            "name_source": "ALTER TABLE sessions ADD COLUMN name_source TEXT DEFAULT 'auto'",
        }
        for col, ddl in migrations.items():
            if col not in cols:
                conn.execute(ddl)

    # thinking-mode fix: add messages.reasoning_content for old pawn.db files.
    # Missing this field can trigger HTTP 400 after loading reasoning-model sessions.
    with get_conn() as conn:
        msg_cols = [row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()]
        msg_migrations = {
            "reasoning_content": "ALTER TABLE messages ADD COLUMN reasoning_content TEXT",
        }
        for col, ddl in msg_migrations.items():
            if col not in msg_cols:
                try:
                    conn.execute(ddl)
                except sqlite3.OperationalError:
                    # Another process may have added it concurrently.
                    pass

# init_facts_table is defined later; init_db calls it after both are loaded.

# ════════════════════════════════════════════════════════
# Helpers.
# ════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")

def _gen_id(seed: str = "") -> str:
    raw = f"{datetime.now().isoformat()}{seed}{os.getpid()}"
    return datetime.now().strftime("%Y%m%d%H%M%S") + "_" + hashlib.md5(raw.encode()).hexdigest()[:6]

# ════════════════════════════════════════════════════════
# Incremental save trackers.
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
            m.get("tool_call_id"), 1 if m.get("_pinned") else 0,
            # Persist reasoning_content so /chat load can continue reasoning-model sessions.
            m.get("reasoning_content"),
            now,
        ))
        seq += 1
    return rows

# ════════════════════════════════════════════════════════
# Sessions CRUD
# ════════════════════════════════════════════════════════

def upsert_session(
    session_id: str,
    name: str,
    model: str,
    cwd: str,
    config_dict: dict,
    tags: str = "",
    auto_name: str = "",
    workspace_dir: str = "",
    workspace_alias: str = "",
    name_source: str = "",
):
    now = _now()
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        created  = existing["created_at"] if existing else now
        old_tags = existing["tags"] if existing else ""
        final_tags = old_tags if old_tags else tags

        old_name = existing["name"] if existing else ""
        old_source = existing["name_source"] if existing and "name_source" in existing.keys() else ""
        requested_source = (name_source or "").strip()

        final_name = (name or "").strip()
        final_source = requested_source or old_source or "auto"
        if not final_name:
            final_name = old_name or ""
            final_source = old_source or final_source
        elif old_source == "manual" and requested_source != "manual":
            final_name = old_name
            final_source = "manual"

        final_auto = (auto_name or "").strip() or (existing["auto_name"] if existing else "")
        final_workspace = (workspace_dir or "").strip() or (existing["workspace_dir"] if existing else "")
        final_alias = (workspace_alias or "").strip() or (existing["workspace_alias"] if existing else "")

        if existing:
            conn.execute("""
                UPDATE sessions
                SET name=?, model=?, cwd=?, config=?, tags=?, auto_name=?,
                    workspace_dir=?, workspace_alias=?, name_source=?, updated_at=?
                WHERE id=?
            """, (
                final_name, model, cwd, json.dumps(config_dict), final_tags, final_auto,
                final_workspace, final_alias, final_source, now, session_id,
            ))
        else:
            conn.execute("""
                INSERT INTO sessions
                    (id, name, model, cwd, config, tags, auto_name, workspace_dir,
                     workspace_alias, name_source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id, final_name, model, cwd, json.dumps(config_dict), final_tags,
                final_auto, final_workspace, final_alias, final_source, created, now,
            ))

def list_sessions(limit: int = 20) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("""
            SELECT s.id, s.name, s.model, s.cwd, s.tags, s.auto_name,
                   s.workspace_dir, s.workspace_alias, s.name_source,
                   s.created_at, s.updated_at,
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

def rename_session(session_id: str, new_name: str, name_source: str = "manual") -> bool:
    """Rename a session."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE sessions SET name=?, name_source=?, updated_at=? WHERE id=?",
            (new_name, name_source, _now(), session_id),
        )
        return cur.rowcount > 0

def update_session_naming(
    session_id: str,
    *,
    title: str = "",
    auto_name: str = "",
    workspace_dir: str = "",
    workspace_alias: str = "",
    name_source: str = "auto",
) -> bool:
    """Update generated naming metadata without overriding manual names."""
    def _write() -> bool:
        with get_conn() as conn:
            row = conn.execute("SELECT name, name_source FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not row:
                return False
            current_source = row["name_source"] or ""
            current_name = row["name"] or ""
            final_name = current_name
            final_source = current_source or name_source
            if current_source != "manual" and title.strip():
                final_name = title.strip()
                final_source = name_source
            cur = conn.execute("""
                UPDATE sessions
                SET name=?, auto_name=COALESCE(NULLIF(?, ''), auto_name),
                    workspace_dir=COALESCE(NULLIF(?, ''), workspace_dir),
                    workspace_alias=COALESCE(NULLIF(?, ''), workspace_alias),
                    name_source=?, updated_at=?
                WHERE id=?
            """, (
                final_name, auto_name.strip(), workspace_dir.strip(), workspace_alias.strip(),
                final_source or "auto", _now(), session_id,
            ))
            return cur.rowcount > 0

    return _write_with_retry(session_id, "update_session_naming", _write)

# ════════════════════════════════════════════════════════
# Tag management.
# ════════════════════════════════════════════════════════

def tag_session(session_id: str, new_tags: str) -> bool:
    """
    Append tags to a session without overwriting existing tags.
    new_tags is a comma-separated string, e.g. "pwn,ctf,heap".
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
    """Remove specified tags."""
    with get_conn() as conn:
        row = conn.execute("SELECT tags FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not row: return False
        existing = set(t.strip() for t in (row["tags"] or "").split(",") if t.strip())
        remove   = set(t.strip() for t in remove_tags.split(",") if t.strip())
        merged   = ",".join(sorted(existing - remove))
        conn.execute("UPDATE sessions SET tags=? WHERE id=?", (merged, session_id))
        return True

def find_sessions_by_tag(tag: str) -> list[sqlite3.Row]:
    """Fuzzy-match a tag and return sessions containing it."""
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
# Session links.
# ════════════════════════════════════════════════════════

def link_sessions(session_a: str, session_b: str, note: str = "") -> bool:
    """Bidirectionally link two sessions; storage is one-way, queries are two-way."""
    # Normalize order to avoid duplicate (a,b) and (b,a) rows.
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
    """Remove a session link."""
    a, b = sorted([session_a, session_b])
    with get_conn() as conn:
        conn.execute("DELETE FROM session_links WHERE session_a=? AND session_b=?", (a, b))

def get_linked_sessions(session_id: str) -> list[sqlite3.Row]:
    """Return all sessions linked to a given session, including notes."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT CASE WHEN session_a=? THEN session_b ELSE session_a END AS other_id,
                   note, created_at
            FROM session_links
            WHERE session_a=? OR session_b=?
        """, (session_id, session_id, session_id)).fetchall()

        if not rows:
            return []

        linked_ids = [row["other_id"] for row in rows]
        placeholders = ",".join("?" for _ in linked_ids)
        meta_rows = conn.execute(f"""
            SELECT s.id, s.name, s.model, s.tags, s.updated_at, COUNT(m.id) AS msg_count
            FROM sessions s LEFT JOIN messages m ON s.id = m.session_id
            WHERE s.id IN ({placeholders})
            GROUP BY s.id
        """, linked_ids).fetchall()

    meta_by_id = {row["id"]: row for row in meta_rows}
    result = []
    for row in rows:
        meta = meta_by_id.get(row["other_id"])
        if meta:
            result.append({"meta": meta, "note": row["note"], "linked_at": row["created_at"]})
    return result

# ════════════════════════════════════════════════════════
# Conversation full-text search.
# ════════════════════════════════════════════════════════

def full_text_search(query: str, limit: int = 20) -> list[dict]:
    """
    Search message content across all sessions.
    Returns session metadata plus matching snippets.
    Supports multi-word search separated by spaces with AND semantics.

    Uses FTS5 first, then falls back to a LIKE full-table scan when unavailable.
    """
    keywords = [w.strip() for w in query.split() if w.strip()]
    if not keywords:
        return []

    hits = []

    # Strategy 1: FTS5 full-text search.
    try:
        fts_query = " AND ".join(f'"{kw}"' for kw in keywords)
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT m.session_id, m.seq, m.role, m.content, m.created_at
                FROM messages_fts fts
                JOIN messages m ON m.id = fts.rowid
                WHERE messages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (fts_query, limit * 3)).fetchall()
            hits = rows
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        hits = []  # FTS5 unavailable; fall back.

    # Strategy 2: LIKE full-table scan fallback.
    if not hits:
        like_clauses = " AND ".join("content LIKE ?" for _ in keywords)
        params       = tuple(f"%{kw}%" for kw in keywords)
        with get_conn() as conn:
            hits = conn.execute(f"""
                SELECT m.session_id, m.seq, m.role, m.content, m.created_at
                FROM messages m
                WHERE {like_clauses}
                ORDER BY m.created_at DESC
                LIMIT ?
            """, (*params, limit * 3)).fetchall()

    if not hits:
        return []

    # Group by session_id; show at most 3 hits per session.
    session_hits: dict[str, list] = {}
    for row in hits:
        sid = row["session_id"]
        if sid not in session_hits:
            session_hits[sid] = []
        if len(session_hits[sid]) < 3:
            session_hits[sid].append(row)
        if len(session_hits) >= limit:
            break

    # Add session metadata.
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
    Extract a context snippet around the first keyword hit.
    Keyword highlighting is handled by callers when needed.
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
# Full session content read for /chat view.
# ════════════════════════════════════════════════════════

def get_session_messages_pretty(session_id: str) -> list[dict]:
    """
    Read all messages from a session and return display-friendly entries.
    Each entry: {seq, role, content_preview, content_full, is_pinned, created_at}
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
            # Assistant tool-call message: show tool names.
            try:
                calls = json.loads(r["tool_calls"])
                names = [c["function"]["name"] for c in calls if "function" in c]
                content = f"[Tool calls: {', '.join(names)}]"
            except Exception:
                content = "[tool_calls]"
        if r["role"] == "tool":
            content = f"[Tool result call_id={r['tool_call_id']}] " + content[:200]

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
    Export a session to a Markdown string.
    /chat export can write it to a local file.
    """
    meta = get_session(session_id)
    if not meta:
        return f"ERROR: session {session_id} does not exist"

    lines = [
        f"# PawnLogic Conversation Export",
        f"",
        f"| Field | Value |",
        f"|------|----|",
        f"| session_id | `{session_id}` |",
        f"| Name | {meta['name'] or meta['auto_name'] or meta['workspace_alias'] or '(unnamed)'} |",
        f"| Model | {meta['model']} |",
        f"| Directory | `{meta['cwd']}` |",
        f"| Tags | {meta['tags'] or '-'} |",
        f"| Created | {meta['created_at']} |",
        f"| Updated | {meta['updated_at']} |",
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
            lines.append(f"## 🧑 User  `[{m['seq']}]`{pinned}  {ts}")
            lines.append(f"")
            lines.append(content)
            lines.append(f"")
        elif role == "assistant":
            if content.startswith("[Tool calls:"):
                lines.append(f"## 🔧 Tool Call  `[{m['seq']}]`  {ts}")
                lines.append(f"")
                lines.append(f"> {m['preview']}")
                lines.append(f"")
            else:
                lines.append(f"## 🤖 Assistant  `[{m['seq']}]`{pinned}  {ts}")
                lines.append(f"")
                lines.append(content)
                lines.append(f"")
        elif role == "tool":
            lines.append(f"<details><summary>🔩 Tool Result [{m['seq']}]</summary>")
            lines.append(f"")
            lines.append(f"```")
            lines.append(content[:1000])
            if len(content) > 1000:
                lines.append(f"...[{len(content)} chars total, truncated]...")
            lines.append(f"```")
            lines.append(f"</details>")
            lines.append(f"")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)

# ════════════════════════════════════════════════════════
# Messages CRUD with incremental saving.
# ════════════════════════════════════════════════════════

def save_messages(session_id: str, messages: list):
    all_rows      = _build_rows(session_id, messages)
    current_total = len(all_rows)
    last_seq      = _last_saved_seq.get(session_id, -1)
    prev_pins     = _pinned_snapshot.get(session_id, {})
    needs_full    = (last_seq == -1 or current_total < last_seq + 1)

    def _write() -> None:
        with get_conn() as conn:
            if needs_full:
                conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
                if all_rows:
                    conn.executemany("""
                        INSERT INTO messages
                            (session_id, seq, role, content, tool_calls, tool_call_id,
                             is_pinned, reasoning_content, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, all_rows)
            else:
                new_rows = [r for r in all_rows if r[1] > last_seq]
                if new_rows:
                    conn.executemany("""
                        INSERT OR REPLACE INTO messages
                            (session_id, seq, role, content, tool_calls, tool_call_id,
                             is_pinned, reasoning_content, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, new_rows)
                cur_pins = {r[1]: r[6] for r in all_rows}
                for seq_idx, pinned in cur_pins.items():
                    if prev_pins.get(seq_idx, 0) != pinned:
                        conn.execute(
                            "UPDATE messages SET is_pinned=? WHERE session_id=? AND seq=?",
                            (pinned, session_id, seq_idx),
                        )

    _write_with_retry(session_id, "save_messages", _write)
    _last_saved_seq[session_id]  = current_total - 1
    _pinned_snapshot[session_id] = {r[1]: r[6] for r in all_rows}

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
            except Exception: pass
        if r["tool_call_id"]: m["tool_call_id"] = r["tool_call_id"]
        if r["is_pinned"]:    m["_pinned"] = True
        # Restore reasoning_content. Old DBs may not have this column.
        try:
            rc = r["reasoning_content"]
            if rc:
                m["reasoning_content"] = rc
        except (IndexError, KeyError):
            pass
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
    # Use SQL LIKE to filter at the DB level instead of loading all rows
    like_clauses = " OR ".join(
        "(topic LIKE ? OR content LIKE ? OR tags LIKE ?)" for _ in keywords
    )
    params = []
    for kw in keywords:
        params.extend([f"%{kw}%", f"%{kw}%", f"%{kw}%"])
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM knowledge WHERE {like_clauses} ORDER BY created_at DESC",
            params,
        ).fetchall()
    # Score by keyword hit count for ranking
    scored = []
    for row in rows:
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
# Persistent Agent Facts — Key-Value MemoryStore
#
# Purpose: persistent fact storage across sessions and delegate_task calls.
# Solves context amnesia: facts saved by save_fact remain queryable even after
# /clear or a new delegate_task starts.
#
# API summary:
#   save_fact(key, value, namespace)  → write/update one fact
#   query_fact(key, namespace)        → exact-read one fact (str | None)
#   search_facts(query_text, ...)     → fuzzy keyword search
#   delete_fact(key, namespace)       → delete one fact
#   list_facts(namespace, limit)      → list facts
#   format_facts_for_prompt(rows)     → format prompt-injection block
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
        # Migration: add namespace to old DBs when missing.
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
    query_text: str = "",
    namespace: str | None = None,
    limit: int = 10,
    **legacy_filters,
) -> list[sqlite3.Row]:
    """
    Keyword search across fact keys and values.
    Used by session._reset_system_prompt to auto-inject relevant facts.
    """
    if not query_text and "query" in legacy_filters:
        query_text = str(legacy_filters["query"])
    init_facts_table()
    keywords = list(set(re.findall(r'[a-zA-Z\u4e00-\u9fff]\w*', query_text.lower())))
    with get_conn() as conn:
        limit = max(1, int(limit))
        if namespace:
            base_where = ["namespace=?"]
            params: list[str | int] = [namespace]
        else:
            base_where = []
            params = []

        if keywords:
            keyword_clauses = []
            for kw in keywords:
                like = f"%{kw}%"
                keyword_clauses.append(
                    "(LOWER(key) LIKE ? OR LOWER(value) LIKE ? OR LOWER(namespace) LIKE ?)"
                )
                params.extend([like, like, like])
            base_where.append("(" + " OR ".join(keyword_clauses) + ")")

        where_sql = f"WHERE {' AND '.join(base_where)}" if base_where else ""
        rows = conn.execute(
            f"SELECT * FROM agent_facts {where_sql} ORDER BY updated_at DESC LIMIT ?",
            (*params, limit if not keywords else max(limit * 10, limit)),
        ).fetchall()

    if not keywords:
        return list(rows)
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


# ════════════════════════════════════════════════════════
# P0: Failure Patterns — defensive audit database.
#
# Purpose: record tool-call failure history for pre-flight payload audits.
# When the agent is about to call run_code / run_shell / run_interactive,
# it checks for similar historical failures and injects a warning if any exist.
#
# API summary:
#   write_failure(tool_name, args_summary, error_msg, error_type, session_id)
#       → write one failure record
#   check_failure(tool_name, args_keywords, limit)
#       → query similar historical failures (list[sqlite3.Row])
#   list_failures(limit)
#       → list latest N failure records
#   count_failure(tool_name, error_type)
#       → count same-class failures for automatic sinking thresholds
#   clear_failures()
#       → clear all failure records
# ════════════════════════════════════════════════════════

def init_failures_table():
    """Create agent_failures table (idempotent). Called automatically by init_db()."""
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_failures (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name   TEXT    NOT NULL,
            args_hash   TEXT    NOT NULL DEFAULT '',
            args_preview TEXT   NOT NULL DEFAULT '',
            error_msg   TEXT    NOT NULL DEFAULT '',
            error_type  TEXT    NOT NULL DEFAULT '',
            session_id  TEXT    NOT NULL DEFAULT '',
            created_at  TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_failures_tool ON agent_failures(tool_name);
        CREATE INDEX IF NOT EXISTS idx_failures_type ON agent_failures(error_type);
        CREATE INDEX IF NOT EXISTS idx_failures_time ON agent_failures(created_at);
        """)


def write_failure(
    tool_name: str,
    args_summary: str,
    error_msg: str,
    error_type: str = "",
    session_id: str = "",
) -> int:
    """
    Write one tool-call failure record.
    """
    import hashlib
    args_hash = hashlib.md5(args_summary[:100].encode()).hexdigest()[:12]

    def _write() -> int:
        with get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO agent_failures
                    (tool_name, args_hash, args_preview, error_msg, error_type, session_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                tool_name, args_hash, args_summary[:200],
                error_msg[:500], error_type, session_id, _now(),
            ))
            return cur.lastrowid

    return _write_with_retry(session_id, "write_failure", _write)


def check_failure(tool_name: str, args_keywords: str = "", limit: int = 3) -> list[sqlite3.Row]:
    """
    Query historical failure records for a tool.
    """
    with get_conn() as conn:
        if args_keywords:
            keywords = [w.strip() for w in args_keywords.split() if w.strip()]
            conditions = ["tool_name = ?"]
            params: list = [tool_name]
            for kw in keywords[:3]:
                conditions.append("(args_preview LIKE ? OR error_msg LIKE ?)")
                params.extend([f"%{kw}%", f"%{kw}%"])
            where = " AND ".join(conditions)
            params.append(limit)
            return conn.execute(f"""
                SELECT * FROM agent_failures WHERE {where} ORDER BY created_at DESC LIMIT ?
            """, params).fetchall()
        else:
            return conn.execute("""
                SELECT * FROM agent_failures WHERE tool_name=? ORDER BY created_at DESC LIMIT ?
            """, (tool_name, limit)).fetchall()


def count_failure(tool_name: str, error_type: str = "") -> int:
    """Count failures for a tool, optionally filtered by error type."""
    with get_conn() as conn:
        if error_type:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM agent_failures WHERE tool_name=? AND error_type=?",
                (tool_name, error_type),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM agent_failures WHERE tool_name=?",
                (tool_name,),
            ).fetchone()
    return row["cnt"] if row else 0


def list_failures(limit: int = 20) -> list[sqlite3.Row]:
    """List the latest limit failure records."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM agent_failures ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()


def clear_failures() -> int:
    """Clear all failure records and return deleted row count."""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM agent_failures")
        return cur.rowcount


def format_failures_for_prompt(rows: list[sqlite3.Row], max_chars: int = 800) -> str:
    """Format failure records as a warning block for System Prompt injection."""
    if not rows:
        return ""
    lines = ["⚠ [FAILURE WARNING — Historical failures detected for this tool/operation]"]
    total = len(lines[0])
    for r in rows:
        entry = (
            f"  · [{r['tool_name']}] {r['error_type'] or 'Unknown'}: "
            f"{r['error_msg'][:120]}{'...' if len(r['error_msg']) > 120 else ''}\n"
            f"    args: {r['args_preview'][:80]}"
        )
        if total + len(entry) + 1 > max_chars:
            lines.append(f"  ... ({len(rows) - (len(lines) - 1)} more failures omitted)")
            break
        lines.append(entry)
        total += len(entry) + 1
    lines.append("→ Review these failures before proceeding. Consider a different approach.")
    return "\n".join(lines)
