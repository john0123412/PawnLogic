"""Authoritative SQLite adapter for durable knowledge retrieval."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from core.knowledge import (
    KnowledgeQuery,
    RetrievalBatch,
    RetrievalHit,
    stable_record_id,
)


KNOWLEDGE_INDEX_VERSION = "sqlite-knowledge-v1"
MAX_CANDIDATES = 1_000
MAX_LEGACY_LIMIT = 100
MAX_OUTBOX_BATCH = 1_000


class SQLiteKnowledgeAdapter:
    """Store and retrieve bounded knowledge chunks from the canonical database."""

    def __init__(
        self,
        connection_factory: Callable[[], sqlite3.Connection],
        now: Callable[[], str],
    ) -> None:
        self._connection_factory = connection_factory
        self._now = now

    def init_schema(self) -> None:
        with self._connection_factory() as conn:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(knowledge)").fetchall()
            }
            migrations = {
                "record_id": "ALTER TABLE knowledge ADD COLUMN record_id TEXT DEFAULT ''",
                "namespace": (
                    "ALTER TABLE knowledge ADD COLUMN namespace TEXT NOT NULL "
                    "DEFAULT 'global'"
                ),
                "source_type": (
                    "ALTER TABLE knowledge ADD COLUMN source_type TEXT NOT NULL "
                    "DEFAULT 'knowledge'"
                ),
                "source_id": (
                    "ALTER TABLE knowledge ADD COLUMN source_id TEXT NOT NULL DEFAULT ''"
                ),
                "source_revision": (
                    "ALTER TABLE knowledge ADD COLUMN source_revision TEXT NOT NULL "
                    "DEFAULT '1'"
                ),
                "chunk_index": (
                    "ALTER TABLE knowledge ADD COLUMN chunk_index INTEGER NOT NULL "
                    "DEFAULT 0"
                ),
                "metadata_json": (
                    "ALTER TABLE knowledge ADD COLUMN metadata_json TEXT NOT NULL "
                    "DEFAULT '{}'"
                ),
                "updated_at": (
                    "ALTER TABLE knowledge ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"
                ),
            }
            for column, ddl in migrations.items():
                if column not in columns:
                    conn.execute(ddl)
            conn.executescript("""
                UPDATE knowledge
                SET record_id='knowledge:' || id
                WHERE record_id IS NULL OR record_id='';
                UPDATE knowledge
                SET source_id=COALESCE(NULLIF(source_id, ''), source_session, record_id)
                WHERE source_id IS NULL OR source_id='';
                UPDATE knowledge
                SET source_revision='1'
                WHERE source_revision IS NULL OR source_revision='';
                UPDATE knowledge
                SET updated_at=created_at
                WHERE updated_at IS NULL OR updated_at='';
                CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_record_id
                    ON knowledge(record_id);
                CREATE INDEX IF NOT EXISTS idx_knowledge_namespace
                    ON knowledge(namespace);
            """)
            self._init_outbox(conn)
        self._init_fts()

    def _init_outbox(self, conn: sqlite3.Connection) -> None:
        existing = conn.execute("""
            SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='knowledge_index_outbox'
        """).fetchone()
        if existing:
            columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(knowledge_index_outbox)"
                ).fetchall()
            }
            if "source_revision" not in columns:
                conn.executescript("""
                    ALTER TABLE knowledge_index_outbox
                        RENAME TO knowledge_index_outbox_legacy;
                    CREATE TABLE knowledge_index_outbox (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        record_id       TEXT NOT NULL,
                        source_revision TEXT NOT NULL,
                        operation       TEXT NOT NULL,
                        index_version   TEXT NOT NULL,
                        attempts        INTEGER NOT NULL DEFAULT 0,
                        last_error      TEXT NOT NULL DEFAULT '',
                        created_at      TEXT NOT NULL,
                        updated_at      TEXT NOT NULL,
                        UNIQUE(record_id, source_revision, operation, index_version)
                    );
                    INSERT INTO knowledge_index_outbox
                        (id, record_id, source_revision, operation, index_version,
                         attempts, last_error, created_at, updated_at)
                    SELECT id, record_id, '1', operation, index_version,
                           attempts, last_error, created_at, updated_at
                    FROM knowledge_index_outbox_legacy;
                    DROP TABLE knowledge_index_outbox_legacy;
                """)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS knowledge_index_outbox (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id       TEXT NOT NULL,
                source_revision TEXT NOT NULL,
                operation       TEXT NOT NULL,
                index_version   TEXT NOT NULL,
                attempts        INTEGER NOT NULL DEFAULT 0,
                last_error      TEXT NOT NULL DEFAULT '',
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL,
                UNIQUE(record_id, source_revision, operation, index_version)
            );
            CREATE INDEX IF NOT EXISTS idx_knowledge_outbox_pending
                ON knowledge_index_outbox(id);
        """)

    def _init_fts(self) -> None:
        with self._connection_factory() as conn:
            existed = conn.execute("""
                SELECT 1 FROM sqlite_master
                WHERE type='table' AND name='knowledge_fts'
            """).fetchone()
            try:
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
                    USING fts5(
                        topic, content, tags,
                        content=knowledge, content_rowid=id
                    )
                """)
                conn.executescript("""
                    CREATE TRIGGER IF NOT EXISTS knowledge_ai
                    AFTER INSERT ON knowledge BEGIN
                        INSERT INTO knowledge_fts(rowid, topic, content, tags)
                        VALUES (new.id, new.topic, new.content, new.tags);
                    END;
                    CREATE TRIGGER IF NOT EXISTS knowledge_ad
                    AFTER DELETE ON knowledge BEGIN
                        INSERT INTO knowledge_fts(
                            knowledge_fts, rowid, topic, content, tags
                        )
                        VALUES ('delete', old.id, old.topic, old.content, old.tags);
                    END;
                    CREATE TRIGGER IF NOT EXISTS knowledge_au
                    AFTER UPDATE ON knowledge BEGIN
                        INSERT INTO knowledge_fts(
                            knowledge_fts, rowid, topic, content, tags
                        )
                        VALUES ('delete', old.id, old.topic, old.content, old.tags);
                        INSERT INTO knowledge_fts(rowid, topic, content, tags)
                        VALUES (new.id, new.topic, new.content, new.tags);
                    END;
                """)
                if not existed:
                    conn.execute(
                        "INSERT INTO knowledge_fts(knowledge_fts) VALUES ('rebuild')"
                    )
            except sqlite3.OperationalError:
                pass

    def add_legacy(
        self,
        topic: str,
        content: str,
        tags: str = "",
        source_session: str = "",
    ) -> int:
        now = self._now()
        record_id = stable_record_id(
            "global",
            "knowledge",
            f"{source_session}:{topic}:{now}",
        )
        with self._connection_factory() as conn:
            cursor = conn.execute("""
                INSERT INTO knowledge
                    (record_id, namespace, topic, content, tags, source_session,
                     source_type, source_id, source_revision, chunk_index,
                     metadata_json, created_at, updated_at)
                VALUES (?, 'global', ?, ?, ?, ?, 'knowledge', ?, '1', 0, '{}', ?, ?)
            """, (
                record_id,
                topic,
                content,
                tags,
                source_session,
                source_session or record_id,
                now,
                now,
            ))
            self._enqueue(
                conn,
                record_id,
                "1",
                "upsert",
                KNOWLEDGE_INDEX_VERSION,
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return a knowledge row ID")
            return int(cursor.lastrowid)

    def upsert(
        self,
        *,
        record_id: str,
        namespace: str,
        topic: str,
        content: str,
        tags: str = "",
        source_type: str = "knowledge",
        source_id: str = "",
        source_revision: str = "1",
        chunk_index: int = 0,
        metadata: dict[str, str] | None = None,
    ) -> str:
        values = {
            "record_id": record_id.strip(),
            "namespace": namespace.strip(),
            "topic": topic.strip(),
            "source_type": source_type.strip() or "knowledge",
            "source_id": source_id.strip() or record_id.strip(),
            "source_revision": source_revision.strip() or "1",
        }
        if (
            not values["record_id"]
            or not values["namespace"]
            or not values["topic"]
            or not content
        ):
            raise ValueError("record_id, namespace, topic, and content are required")
        if isinstance(chunk_index, bool) or not isinstance(chunk_index, int):
            raise TypeError("chunk_index must be an integer")
        if chunk_index < 0:
            raise ValueError("chunk_index must be non-negative")
        metadata_json = json.dumps(
            metadata or {},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        now = self._now()
        with self._connection_factory() as conn:
            conn.execute("""
                INSERT INTO knowledge
                    (record_id, namespace, topic, content, tags, source_session,
                     source_type, source_id, source_revision, chunk_index,
                     metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                    namespace=excluded.namespace,
                    topic=excluded.topic,
                    content=excluded.content,
                    tags=excluded.tags,
                    source_type=excluded.source_type,
                    source_id=excluded.source_id,
                    source_revision=excluded.source_revision,
                    chunk_index=excluded.chunk_index,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
            """, (
                values["record_id"],
                values["namespace"],
                values["topic"],
                content,
                tags,
                values["source_type"],
                values["source_id"],
                values["source_revision"],
                chunk_index,
                metadata_json,
                now,
                now,
            ))
            self._enqueue(
                conn,
                values["record_id"],
                values["source_revision"],
                "upsert",
                KNOWLEDGE_INDEX_VERSION,
            )
        return values["record_id"]

    def list_legacy(self, limit: int = 30) -> list[sqlite3.Row]:
        bounded = min(max(int(limit), 1), MAX_LEGACY_LIMIT)
        with self._connection_factory() as conn:
            return conn.execute(
                "SELECT * FROM knowledge ORDER BY created_at DESC LIMIT ?",
                (bounded,),
            ).fetchall()

    def delete_legacy(self, row_id: int) -> bool:
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT record_id, source_revision FROM knowledge WHERE id=?",
                (row_id,),
            ).fetchone()
            if row is None:
                return False
            conn.execute("DELETE FROM knowledge WHERE id=?", (row_id,))
            self._enqueue(
                conn,
                row["record_id"],
                row["source_revision"],
                "delete",
                KNOWLEDGE_INDEX_VERSION,
            )
        return True

    def delete(self, record_id: str) -> bool:
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT source_revision FROM knowledge WHERE record_id=?",
                (record_id,),
            ).fetchone()
            if row is None:
                return False
            conn.execute("DELETE FROM knowledge WHERE record_id=?", (record_id,))
            self._enqueue(
                conn,
                record_id,
                row["source_revision"],
                "delete",
                KNOWLEDGE_INDEX_VERSION,
            )
        return True

    def query(self, request: KnowledgeQuery) -> RetrievalBatch:
        keywords = _keywords(request.text)
        if not keywords:
            return RetrievalBatch(
                adapter="sqlite",
                algorithm="keyword_empty",
                index_version=KNOWLEDGE_INDEX_VERSION,
            )
        candidate_limit = min(
            max(request.top_k * 20, request.top_k),
            MAX_CANDIDATES,
        )
        algorithm = "sqlite_fts5"
        try:
            rows = self._search_fts(keywords, request.namespaces, candidate_limit)
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            rows = []
        if not rows:
            algorithm = "sqlite_like"
            rows = self._search_like(keywords, request.namespaces, candidate_limit)
        scored = self._score_rows(rows, keywords)
        return RetrievalBatch(
            hits=tuple(scored[: request.top_k]),
            adapter="sqlite",
            algorithm=algorithm,
            index_version=KNOWLEDGE_INDEX_VERSION,
        )

    def hydrate(self, record_ids: Sequence[str]) -> tuple[RetrievalHit, ...]:
        bounded_ids = tuple(dict.fromkeys(record_ids))[:MAX_LEGACY_LIMIT]
        if not bounded_ids:
            return ()
        placeholders = ",".join("?" for _ in bounded_ids)
        with self._connection_factory() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM knowledge
                WHERE record_id IN ({placeholders})
                ORDER BY record_id
                """,
                bounded_ids,
            ).fetchall()
        return tuple(self._row_to_hit(row, 1.0, "sqlite_hydrate") for row in rows)

    def search_legacy(self, query: str, limit: int = 5) -> list[sqlite3.Row]:
        bounded = min(max(int(limit), 1), MAX_LEGACY_LIMIT)
        if not _keywords(query):
            return self.list_legacy(bounded)
        batch = self.query(
            KnowledgeQuery(
                text=query,
                top_k=bounded,
                max_chars=65_536,
            )
        )
        ids = tuple(hit.record_id for hit in batch.hits)
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self._connection_factory() as conn:
            rows = conn.execute(
                f"SELECT * FROM knowledge WHERE record_id IN ({placeholders})",
                ids,
            ).fetchall()
        by_id = {row["record_id"]: row for row in rows}
        return [by_id[record_id] for record_id in ids if record_id in by_id]

    def enqueue(
        self,
        record_id: str,
        operation: str = "upsert",
        index_version: str = KNOWLEDGE_INDEX_VERSION,
        source_revision: str | None = None,
    ) -> int:
        with self._connection_factory() as conn:
            revision = source_revision
            if not revision:
                row = conn.execute(
                    "SELECT source_revision FROM knowledge WHERE record_id=?",
                    (record_id,),
                ).fetchone()
                revision = row["source_revision"] if row else "1"
            return self._enqueue(
                conn,
                record_id,
                revision,
                operation,
                index_version,
            )

    def _enqueue(
        self,
        conn: sqlite3.Connection,
        record_id: str,
        source_revision: str,
        operation: str,
        index_version: str,
    ) -> int:
        if operation not in {"upsert", "delete"}:
            raise ValueError("operation must be 'upsert' or 'delete'")
        if not record_id or not source_revision or not index_version:
            raise ValueError(
                "record_id, source_revision, and index_version are required"
            )
        now = self._now()
        conn.execute("""
            INSERT INTO knowledge_index_outbox
                (record_id, source_revision, operation, index_version,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(record_id, source_revision, operation, index_version)
            DO UPDATE SET updated_at=excluded.updated_at
        """, (
            record_id,
            source_revision,
            operation,
            index_version,
            now,
            now,
        ))
        row = conn.execute("""
            SELECT id FROM knowledge_index_outbox
            WHERE record_id=? AND source_revision=? AND operation=?
                  AND index_version=?
        """, (record_id, source_revision, operation, index_version)).fetchone()
        return int(row["id"])

    def pending(self, limit: int = 100) -> list[dict[str, Any]]:
        bounded = min(max(int(limit), 1), MAX_OUTBOX_BATCH)
        with self._connection_factory() as conn:
            rows = conn.execute("""
                SELECT id, record_id, source_revision, operation, index_version,
                       attempts, last_error, created_at, updated_at
                FROM knowledge_index_outbox
                ORDER BY id
                LIMIT ?
            """, (bounded,)).fetchall()
        return [dict(row) for row in rows]

    def acknowledge(self, entry_ids: Iterable[int]) -> int:
        ids = tuple(dict.fromkeys(int(entry_id) for entry_id in entry_ids))
        if not ids:
            return 0
        if len(ids) > MAX_OUTBOX_BATCH:
            raise ValueError(f"cannot acknowledge more than {MAX_OUTBOX_BATCH} entries")
        placeholders = ",".join("?" for _ in ids)
        with self._connection_factory() as conn:
            cursor = conn.execute(
                f"DELETE FROM knowledge_index_outbox WHERE id IN ({placeholders})",
                ids,
            )
            return cursor.rowcount

    def fail(self, entry_id: int, error: str) -> bool:
        with self._connection_factory() as conn:
            cursor = conn.execute("""
                UPDATE knowledge_index_outbox
                SET attempts=attempts + 1, last_error=?, updated_at=?
                WHERE id=?
            """, (error[:1_000], self._now(), int(entry_id)))
            return cursor.rowcount > 0

    def enqueue_rebuild(
        self,
        *,
        namespace: str | None = None,
        index_version: str = KNOWLEDGE_INDEX_VERSION,
    ) -> int:
        """Queue a rebuild with one SQL insert-select and no corpus materialization."""
        now = self._now()
        with self._connection_factory() as conn:
            before = conn.total_changes
            if namespace:
                conn.execute("""
                    INSERT OR IGNORE INTO knowledge_index_outbox
                        (record_id, source_revision, operation, index_version,
                         created_at, updated_at)
                    SELECT record_id, source_revision, 'upsert', ?, ?, ?
                    FROM knowledge
                    WHERE namespace=?
                """, (index_version, now, now, namespace))
            else:
                conn.execute("""
                    INSERT OR IGNORE INTO knowledge_index_outbox
                        (record_id, source_revision, operation, index_version,
                         created_at, updated_at)
                    SELECT record_id, source_revision, 'upsert', ?, ?, ?
                    FROM knowledge
                """, (index_version, now, now))
            return conn.total_changes - before

    def _search_fts(
        self,
        keywords: list[str],
        namespaces: tuple[str, ...],
        limit: int,
    ) -> list[sqlite3.Row]:
        match_query = " OR ".join(
            f'"{keyword.replace(chr(34), chr(34) * 2)}"' for keyword in keywords
        )
        namespace_sql, namespace_params = _namespace_sql(namespaces, prefix="k.")
        namespace_clause = f" AND {namespace_sql}" if namespace_sql else ""
        with self._connection_factory() as conn:
            return conn.execute(f"""
                SELECT k.*
                FROM knowledge_fts
                JOIN knowledge k ON k.id=knowledge_fts.rowid
                WHERE knowledge_fts MATCH ?{namespace_clause}
                ORDER BY bm25(knowledge_fts), k.record_id
                LIMIT ?
            """, (match_query, *namespace_params, limit)).fetchall()

    def _search_like(
        self,
        keywords: list[str],
        namespaces: tuple[str, ...],
        limit: int,
    ) -> list[sqlite3.Row]:
        keyword_clauses = []
        params: list[str | int] = []
        for keyword in keywords:
            keyword_clauses.append(
                "(LOWER(topic) LIKE ? OR LOWER(content) LIKE ? OR LOWER(tags) LIKE ?)"
            )
            like = f"%{keyword}%"
            params.extend((like, like, like))
        namespace_sql, namespace_params = _namespace_sql(namespaces)
        conditions = ["(" + " OR ".join(keyword_clauses) + ")"]
        if namespace_sql:
            conditions.append(namespace_sql)
            params.extend(namespace_params)
        with self._connection_factory() as conn:
            return conn.execute(f"""
                SELECT * FROM knowledge
                WHERE {" AND ".join(conditions)}
                ORDER BY updated_at DESC, record_id
                LIMIT ?
            """, (*params, limit)).fetchall()

    def _score_rows(
        self,
        rows: Sequence[sqlite3.Row],
        keywords: list[str],
    ) -> list[RetrievalHit]:
        scored = []
        for row in rows:
            searchable = (
                f"{row['topic']} {row['content']} {row['tags'] or ''}".lower()
            )
            matched = sum(keyword in searchable for keyword in keywords)
            if matched:
                scored.append(
                    self._row_to_hit(
                        row,
                        matched / len(keywords),
                        "keyword_overlap",
                    )
                )
        return sorted(scored, key=lambda hit: (-hit.score, hit.record_id))

    @staticmethod
    def _row_to_hit(
        row: sqlite3.Row,
        score: float,
        score_kind: str,
    ) -> RetrievalHit:
        return RetrievalHit(
            record_id=row["record_id"],
            namespace=row["namespace"] or "global",
            source_type=row["source_type"] or "knowledge",
            source_id=row["source_id"] or row["record_id"],
            source_revision=row["source_revision"] or "1",
            content=row["content"],
            score=score,
            score_kind=score_kind,
            provenance={
                "namespace": row["namespace"] or "global",
                "topic": row["topic"],
                "tags": row["tags"] or "",
                "source_session": row["source_session"] or "",
                "source_revision": row["source_revision"] or "1",
                "retrieval_algorithm": score_kind,
                "index_version": KNOWLEDGE_INDEX_VERSION,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "content_source": "sqlite",
            },
        )


def _keywords(query: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"[a-zA-Z\u4e00-\u9fff]\w*", query.lower())))


def _namespace_sql(
    namespaces: tuple[str, ...],
    *,
    prefix: str = "",
) -> tuple[str, list[str]]:
    if not namespaces:
        return "", []
    placeholders = ",".join("?" for _ in namespaces)
    return f"{prefix}namespace IN ({placeholders})", list(namespaces)


__all__ = ["KNOWLEDGE_INDEX_VERSION", "SQLiteKnowledgeAdapter"]
