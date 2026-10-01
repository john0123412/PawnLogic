"""Persistence contract for token budgets and turn-context markers."""

from __future__ import annotations

import sys
from pathlib import Path
from types import MethodType, SimpleNamespace

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests.test_memory_reliability import isolated_memory  # noqa: F401


def test_load_snapshot_converts_legacy_character_budget(isolated_memory):
    # A snapshot saved before token budgeting carries character-denominated
    # keys. The runtime config is already seeded with token defaults when the
    # snapshot merges, so the conversion must happen at load time — otherwise
    # the preset defaults (48k/36k) would mask the saved 90k/60k characters.
    memory = isolated_memory
    from core import persistence

    sid = "sess_legacy_budget"
    memory.upsert_session(
        session_id=sid,
        name="",
        model="ds-v4-flash",
        cwd="/tmp",
        config_dict={"ctx_max_chars": 90_000, "ctx_trim_to": 60_000},
        workspace_dir="/tmp/ws",
    )

    snapshot = persistence.load_snapshot(sid)

    assert snapshot is not None
    config = snapshot.runtime["config"]
    assert config["ctx_max_tokens"] == 30_000
    assert config["ctx_trim_tokens"] == 20_000
    # Legacy keys must not survive: a later /ctx token write would otherwise
    # be shadowed by a stale character value.
    assert "ctx_max_chars" not in config
    assert "ctx_trim_to" not in config


def test_load_snapshot_keeps_explicit_token_budget_over_stale_legacy_keys(isolated_memory):
    # A snapshot saved by an intermediate version can carry BOTH the user's
    # explicit token budget and stale legacy character keys. The token keys
    # are what the user last set; the migration must not rewrite them.
    memory = isolated_memory
    from core import persistence

    sid = "sess_mixed_budget"
    memory.upsert_session(
        session_id=sid,
        name="",
        model="ds-v4-flash",
        cwd="/tmp",
        config_dict={
            "ctx_max_tokens": 8_000,
            "ctx_trim_tokens": 6_000,
            "ctx_max_chars": 90_000,
            "ctx_trim_to": 60_000,
        },
        workspace_dir="/tmp/ws",
    )

    snapshot = persistence.load_snapshot(sid)

    assert snapshot is not None
    config = snapshot.runtime["config"]
    assert config["ctx_max_tokens"] == 8_000
    assert config["ctx_trim_tokens"] == 6_000
    assert "ctx_max_chars" not in config
    assert "ctx_trim_to" not in config


def test_load_snapshot_fills_none_token_keys_from_legacy_character_keys(isolated_memory):
    # A snapshot whose token keys are None (explicitly saved as absent) with
    # stale character keys must recover the character budget, not the preset
    # defaults: None/None + 90k/60k chars -> 30k/20k tokens.
    memory = isolated_memory
    from core import persistence

    sid = "sess_none_token_keys"
    memory.upsert_session(
        session_id=sid,
        name="",
        model="ds-v4-flash",
        cwd="/tmp",
        config_dict={
            "ctx_max_tokens": None,
            "ctx_trim_tokens": None,
            "ctx_max_chars": 90_000,
            "ctx_trim_to": 60_000,
        },
        workspace_dir="/tmp/ws",
    )

    snapshot = persistence.load_snapshot(sid)

    assert snapshot is not None
    config = snapshot.runtime["config"]
    assert config["ctx_max_tokens"] == 30_000
    assert config["ctx_trim_tokens"] == 20_000
    assert "ctx_max_chars" not in config
    assert "ctx_trim_to" not in config


def test_turn_context_marker_survives_save_and_load(isolated_memory):
    # The retrieval block is recognized by its `_turn_context` flag; if the
    # flag is lost across save/load, undo after a reload strands the block.
    memory = isolated_memory
    sid = "sess_turn_context"
    memory.upsert_session(
        session_id=sid, name="", model="ds-v4-flash", cwd="/tmp",
        config_dict={}, workspace_dir="/tmp/ws",
    )

    messages = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "[Retrieved Context]", "_turn_context": True},
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
    ]
    memory.save_messages(sid, messages)
    loaded = memory.load_messages(sid)

    # save_messages skips the system message.
    assert [m["role"] for m in loaded] == ["assistant", "user", "assistant"]
    assert loaded[0]["_turn_context"] is True


def test_undo_after_reload_removes_retrieval_block_with_its_turn(isolated_memory):
    # Full save -> load -> undo roundtrip: undo(1) must remove the answer,
    # the user message, AND the injected retrieval block of that turn.
    memory = isolated_memory
    from core.session import AgentSession

    sid = "sess_turn_context_undo"
    memory.upsert_session(
        session_id=sid, name="", model="ds-v4-flash", cwd="/tmp",
        config_dict={}, workspace_dir="/tmp/ws",
    )

    messages = [
        {"role": "assistant", "content": "[Retrieved Context]", "_turn_context": True},
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
    ]
    memory.save_messages(sid, messages)
    loaded = memory.load_messages(sid)

    stub = SimpleNamespace(messages=loaded)
    stub._pop_orphan_turn_context_block = MethodType(
        AgentSession._pop_orphan_turn_context_block, stub
    )
    removed, last_user_text = AgentSession.undo(stub, 1)

    assert removed == 3
    assert last_user_text == "question"
    assert stub.messages == []
