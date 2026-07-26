from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def isolated_memory(monkeypatch, tmp_path):
    module_path = Path(__file__).resolve().parents[1] / "core" / "memory.py"
    spec = importlib.util.spec_from_file_location(
        "pawnlogic_test_knowledge_memory",
        module_path,
    )
    assert spec is not None and spec.loader is not None
    memory = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(memory)

    old_conn = getattr(memory._tls, "conn", None)
    if old_conn is not None:
        old_conn.close()
        delattr(memory._tls, "conn")

    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "pawn.db")
    memory._last_saved_seq.clear()
    memory._pinned_snapshot.clear()
    memory.init_db()

    yield memory

    conn = getattr(memory._tls, "conn", None)
    if conn is not None:
        conn.close()
        delattr(memory._tls, "conn")
    memory._last_saved_seq.clear()
    memory._pinned_snapshot.clear()


def test_search_returns_stable_scored_provenance_rows(isolated_memory):
    memory = isolated_memory
    memory.upsert_knowledge_record(
        record_id="record:heap",
        namespace="project:alpha",
        topic="Heap exploitation",
        content="Use safe unlink checks before applying the primitive.",
        tags="pwn,heap",
        source_type="document",
        source_id="guide.md",
        source_revision="rev-7",
    )
    memory.upsert_knowledge_record(
        record_id="record:web",
        namespace="project:beta",
        topic="Web notes",
        content="Cookie handling guidance.",
    )

    hits = memory.search_knowledge_records(
        "heap unlink",
        namespaces=("project:alpha",),
        top_k=3,
        max_chars=200,
    )

    assert len(hits) == 1
    assert hits[0].record_id == "record:heap"
    assert hits[0].source_type == "document"
    assert hits[0].source_id == "guide.md"
    assert hits[0].source_revision == "rev-7"
    assert hits[0].content == (
        "Use safe unlink checks before applying the primitive."
    )
    assert hits[0].provenance["retrieval_algorithm"] in {
        "sqlite_fts5",
        "sqlite_like",
    }
    assert hits[0].provenance["content_source"] == "sqlite"


def test_search_falls_back_to_like_and_enforces_result_budgets(isolated_memory):
    memory = isolated_memory
    for record_id in ("record:a", "record:b", "record:c"):
        memory.upsert_knowledge_record(
            record_id=record_id,
            namespace="global",
            topic="Shared keyword",
            content="needle " + ("x" * 30),
        )

    with memory.get_conn() as conn:
        conn.execute("DROP TABLE knowledge_fts")

    hits = memory.search_knowledge_records(
        "needle",
        top_k=2,
        max_chars=50,
    )

    assert len(hits) == 2
    assert [hit.record_id for hit in hits] == ["record:a", "record:b"]
    assert sum(len(hit.content) for hit in hits) == 50
    assert all(
        hit.provenance["retrieval_algorithm"] == "sqlite_like" for hit in hits
    )
    assert hits[-1].provenance["truncated"] == "true"


def test_legacy_knowledge_api_uses_normalized_search(isolated_memory):
    memory = isolated_memory

    row_id = memory.add_knowledge(
        "Format strings",
        "Use positional parameters for deterministic writes.",
        "pwn",
        "session-7",
    )

    normalized = memory.search_knowledge_records("positional", top_k=1, max_chars=200)
    legacy = memory.search_knowledge("positional", limit=1)

    assert normalized[0].record_id.startswith("kr_")
    assert normalized[0].source_id == "session-7"
    assert legacy[0]["id"] == row_id


def test_indexing_outbox_supports_ack_retry_delete_and_rebuild(isolated_memory):
    memory = isolated_memory
    memory.upsert_knowledge_record(
        record_id="record:one",
        namespace="project:alpha",
        topic="One",
        content="First record.",
    )
    memory.upsert_knowledge_record(
        record_id="record:two",
        namespace="project:beta",
        topic="Two",
        content="Second record.",
    )

    pending = memory.list_knowledge_index_outbox(limit=10)
    assert [(row["record_id"], row["operation"]) for row in pending] == [
        ("record:one", "upsert"),
        ("record:two", "upsert"),
    ]

    first_id = pending[0]["id"]
    assert memory.fail_knowledge_index_outbox(first_id, "index unavailable") is True
    failed = memory.list_knowledge_index_outbox(limit=1)[0]
    assert failed["attempts"] == 1
    assert failed["last_error"] == "index unavailable"

    assert memory.ack_knowledge_index_outbox([row["id"] for row in pending]) == 2
    assert memory.list_knowledge_index_outbox() == []

    assert memory.enqueue_knowledge_rebuild(
        namespace="project:alpha",
        index_version="redis-v2",
    ) == 1
    rebuilt = memory.list_knowledge_index_outbox()
    assert rebuilt[0]["record_id"] == "record:one"
    assert rebuilt[0]["index_version"] == "redis-v2"

    assert memory.delete_knowledge_record("record:two") is True
    pending = memory.list_knowledge_index_outbox(limit=10)
    assert (pending[-1]["record_id"], pending[-1]["operation"]) == (
        "record:two",
        "delete",
    )


def test_outbox_preserves_each_source_revision_until_exact_ack(isolated_memory):
    memory = isolated_memory
    common = {
        "record_id": "record:changing",
        "namespace": "global",
        "topic": "Changing record",
    }
    memory.upsert_knowledge_record(
        **common,
        content="revision one",
        source_revision="rev-1",
    )
    memory.upsert_knowledge_record(
        **common,
        content="revision two",
        source_revision="rev-2",
    )

    pending = memory.list_knowledge_index_outbox()
    assert [row["source_revision"] for row in pending] == ["rev-1", "rev-2"]

    assert memory.ack_knowledge_index_outbox([pending[0]["id"]]) == 1
    remaining = memory.list_knowledge_index_outbox()
    assert [row["source_revision"] for row in remaining] == ["rev-2"]


def test_rebuild_uses_database_side_insert_without_corpus_materialization(
    isolated_memory,
):
    memory = isolated_memory
    with memory.get_conn() as conn:
        now = memory._now()
        conn.executemany(
            """
            INSERT INTO knowledge
                (record_id, namespace, topic, content, tags, source_session,
                 source_type, source_id, source_revision, chunk_index,
                 metadata_json, created_at, updated_at)
            VALUES (?, 'bulk', 'topic', 'content', '', '', 'document', ?,
                    'rev-1', 0, '{}', ?, ?)
            """,
            (
                (f"bulk:{index:04d}", f"source:{index:04d}", now, now)
                for index in range(1_200)
            ),
        )

    assert memory.enqueue_knowledge_rebuild(
        namespace="bulk",
        index_version="redis-rebuild-v1",
    ) == 1_200
    with memory.get_conn() as conn:
        count = conn.execute(
            """
            SELECT COUNT(*) FROM knowledge_index_outbox
            WHERE index_version='redis-rebuild-v1'
            """
        ).fetchone()[0]
    assert count == 1_200
