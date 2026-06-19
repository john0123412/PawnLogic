from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3
import stat

import pytest


@pytest.fixture
def isolated_memory(monkeypatch, tmp_path):
    from core import memory

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


def _run_parallel(fn, items):
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fn, item) for item in items]
        return [future.result(timeout=10) for future in futures]


def test_connection_uses_central_busy_timeout(isolated_memory):
    memory = isolated_memory

    with memory.get_conn() as conn:
        row = conn.execute("PRAGMA busy_timeout").fetchone()

    assert row[0] == memory.SQLITE_BUSY_TIMEOUT_MS


def test_database_runtime_files_are_private(isolated_memory):
    memory = isolated_memory

    assert stat.S_IMODE(memory.DB_PATH.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(memory.DB_PATH.stat().st_mode) == 0o600


def test_save_messages_handles_concurrent_writes(isolated_memory, tmp_path):
    memory = isolated_memory
    session_ids = [f"session-save-{idx}" for idx in range(24)]
    for session_id in session_ids:
        memory.upsert_session(
            session_id=session_id,
            name="",
            model="ds-v4-flash",
            cwd=str(tmp_path),
            config_dict={},
        )

    def save_one(session_id: str) -> str:
        memory.save_messages(
            session_id,
            [
                {"role": "system", "content": "ignored"},
                {"role": "user", "content": f"prompt {session_id}"},
                {"role": "assistant", "content": f"answer {session_id}"},
            ],
        )
        return session_id

    assert set(_run_parallel(save_one, session_ids)) == set(session_ids)
    for session_id in session_ids:
        loaded = memory.load_messages(session_id)
        assert [msg["content"] for msg in loaded] == [
            f"prompt {session_id}",
            f"answer {session_id}",
        ]


def test_update_session_naming_handles_concurrent_writes(isolated_memory, tmp_path):
    memory = isolated_memory
    session_ids = [f"session-name-{idx}" for idx in range(20)]
    for session_id in session_ids:
        memory.upsert_session(
            session_id=session_id,
            name="",
            model="ds-v4-flash",
            cwd=str(tmp_path),
            config_dict={},
        )

    def name_one(session_id: str) -> str:
        assert memory.update_session_naming(
            session_id,
            title=f"Title {session_id}",
            auto_name=f"Auto {session_id}",
            workspace_dir=str(tmp_path / session_id),
            workspace_alias=session_id,
        )
        return session_id

    assert set(_run_parallel(name_one, session_ids)) == set(session_ids)
    for session_id in session_ids:
        row = memory.get_session(session_id)
        assert row["name"] == f"Title {session_id}"
        assert row["auto_name"] == f"Auto {session_id}"
        assert row["workspace_alias"] == session_id


def test_write_failure_handles_concurrent_writes(isolated_memory):
    memory = isolated_memory
    items = list(range(30))

    def write_one(idx: int) -> int:
        return memory.write_failure(
            "run_shell",
            f"nc target {idx}",
            "timed out",
            "timeout",
            f"session-failure-{idx % 4}",
        )

    row_ids = _run_parallel(write_one, items)

    assert len(row_ids) == len(items)
    assert all(isinstance(row_id, int) and row_id > 0 for row_id in row_ids)
    assert memory.count_failure("run_shell", "timeout") == len(items)


def test_write_retry_logs_session_operation_and_retry_count(monkeypatch, isolated_memory):
    memory = isolated_memory
    warnings: list[str] = []
    sleeps: list[float] = []
    attempts = {"count": 0}

    class FakeLogger:
        def warning(self, message, *args):
            warnings.append(message.format(*args))

        def error(self, message, *args):
            warnings.append(message.format(*args))

    def flaky_write():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    monkeypatch.setattr(memory, "logger", FakeLogger())
    monkeypatch.setattr(memory.time, "sleep", lambda delay: sleeps.append(delay))

    assert memory._write_with_retry("session-retry", "save_messages", flaky_write) == "ok"
    assert attempts["count"] == 2
    assert sleeps == [memory.SQLITE_WRITE_BACKOFF_SEC[0]]
    assert warnings == [
        "session-retry | save_messages | retry_count=1 | database is locked"
    ]
