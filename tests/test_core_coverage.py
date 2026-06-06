"""Focused coverage for core persistence, memory, API, and file helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys

import pytest

ROOT = str(Path(__file__).resolve().parent.parent)


def _drop_project_modules(*module_names: str, force: bool = False) -> None:
    for key in list(sys.modules):
        if not any(key == name or key.startswith(f"{name}.") for name in module_names):
            continue
        module_file = getattr(sys.modules[key], "__file__", "") or ""
        if force or not module_file or ROOT not in module_file:
            del sys.modules[key]
            if "." in key:
                parent_name, attr = key.rsplit(".", 1)
                parent = sys.modules.get(parent_name)
                if parent is not None and hasattr(parent, attr):
                    delattr(parent, attr)


@pytest.fixture
def isolated_memory(monkeypatch, tmp_path):
    _drop_project_modules("config", "core.memory", "core.logger")
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


@dataclass
class FakeSession:
    session_id: str
    model_alias: str = "ds-v4-flash"
    cwd: str = ""
    workspace_dir: str = ""
    messages: list[dict] = field(default_factory=list)
    reset_called: bool = False

    def _reset_system_prompt(self):
        self.reset_called = True


def test_memory_round_trips_messages_search_and_knowledge(isolated_memory, tmp_path):
    memory = isolated_memory
    session_id = "session-memory"
    memory.upsert_session(
        session_id=session_id,
        name="Memory Test",
        model="ds-v4-flash",
        cwd=str(tmp_path),
        config_dict={"max_tokens": 123},
        tags="ctf",
    )
    memory.save_messages(
        session_id,
        [
            {"role": "system", "content": "ignored"},
            {"role": "user", "content": "find the heap overflow"},
            {
                "role": "assistant",
                "content": "analysis",
                "tool_calls": [{"function": {"name": "read_file"}}],
                "reasoning_content": "private chain",
                "_pinned": True,
            },
        ],
    )

    loaded = memory.load_messages(session_id)
    assert [m["role"] for m in loaded] == ["user", "assistant"]
    assert loaded[1]["tool_calls"][0]["function"]["name"] == "read_file"
    assert loaded[1]["reasoning_content"] == "private chain"
    assert loaded[1]["_pinned"] is True

    hits = memory.full_text_search("heap overflow")
    assert hits and hits[0]["session_id"] == session_id
    assert "heap overflow" in hits[0]["hits"][0]["snippet"]

    kid = memory.add_knowledge("heap", "unlink mitigation notes", "pwn", session_id)
    rows = memory.search_knowledge("unlink")
    assert rows and rows[0]["id"] == kid
    memory.delete_knowledge(kid)
    assert memory.search_knowledge("unlink") == []


def test_persistence_save_load_restores_session(isolated_memory, monkeypatch, tmp_path):
    _drop_project_modules("core.persistence", force=True)
    from core import persistence

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(persistence, "init_db", isolated_memory.init_db)

    source = FakeSession(
        session_id="session-persist",
        cwd=str(tmp_path),
        workspace_dir=str(tmp_path / "workspace"),
        messages=[
            {"role": "user", "content": "remember this"},
            {"role": "assistant", "content": "stored"},
        ],
    )

    assert persistence.session_save(source, "Manual Name") == "session-persist"

    target = FakeSession(session_id="empty")
    result = persistence.session_load(target, "Manual")

    assert result.startswith("OK: 已加载 [session-persist]")
    assert target.session_id == "session-persist"
    assert target.model_alias == "ds-v4-flash"
    assert target.cwd == str(tmp_path)
    assert target.workspace_dir == str(tmp_path / "workspace")
    assert [m["content"] for m in target.messages] == ["remember this", "stored"]
    assert target.reset_called is True


def test_api_client_sse_sanitizer_and_circuit_breaker(monkeypatch):
    _drop_project_modules("config")
    _drop_project_modules("core.api_client", force=True)
    from core import api_client

    parsed = api_client.parse_sse_delta(
        '{"choices":[{"delta":{"content":"hello"},"finish_reason":null,}],}'
    )
    assert parsed["choices"][0]["delta"]["content"] == "hello"

    raw_messages = [
        {
            "role": "assistant",
            "content": "answer",
            "reasoning_content": "keep only for reasoning models",
            "_pinned": True,
        }
    ]
    stripped = api_client._sanitize_messages_for_model(raw_messages, "gpt-4.1")
    assert "reasoning_content" not in stripped[0]
    assert "_pinned" not in stripped[0]
    assert "reasoning_content" in raw_messages[0]

    kept = api_client._sanitize_messages_for_model(raw_messages, "ds-v4-flash")
    assert kept[0]["reasoning_content"] == "keep only for reasoning models"

    provider = "unit-provider"
    api_client._CIRCUIT_BREAKERS.clear()
    for _ in range(api_client._CB_TRIP_AT):
        api_client._cb_record_failure(provider)
    assert api_client._cb_allow(provider) is False

    opened_at = api_client._CIRCUIT_BREAKERS[provider]["opened_at"]
    monkeypatch.setattr(api_client.time, "monotonic", lambda: opened_at + api_client._CB_RESET_SEC + 1)
    assert api_client._cb_allow(provider) is True
    assert api_client._CIRCUIT_BREAKERS[provider]["state"] == "half_open"

    api_client._cb_record_success(provider)
    assert api_client._CIRCUIT_BREAKERS[provider]["state"] == "closed"
    assert api_client._CIRCUIT_BREAKERS[provider]["failures"] == 0


def test_file_ops_resolve_and_patch_are_workspace_bound(monkeypatch, tmp_path):
    _drop_project_modules("config", "utils.ansi", "core.logger")
    _drop_project_modules("tools.file_ops", force=True)
    from tools import file_ops

    workspace = tmp_path / "workspace"
    session_workspace = workspace / "session"
    monkeypatch.setattr(file_ops, "WORKSPACE_DIR", str(workspace))
    monkeypatch.setattr(file_ops, "_session_workspace_dir", [str(session_workspace)])

    resolved, err = file_ops._resolve_write_path("nested/demo.py")
    assert err == ""
    assert resolved == str((session_workspace / "nested/demo.py").resolve())

    outside, err = file_ops._resolve_write_path(str(tmp_path / "outside.txt"))
    assert outside == ""
    assert "SECURITY BLOCK" in err

    target = session_workspace / "demo.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("print('old')\n", encoding="utf-8")

    result = file_ops.tool_patch_file({
        "path": "demo.py",
        "patch_blocks": "<<<<<<< SEARCH\nprint('old')\n=======\nprint('new')\n>>>>>>> REPLACE",
    })

    assert result.startswith("OK: 1/1")
    assert target.read_text(encoding="utf-8") == "print('new')\n"
