"""Tests for immutable session snapshots and message repair."""

from core.message_history import repair_dangling_tool_calls
from core.session_snapshot import SessionSnapshot


def test_snapshot_capture_copies_messages_and_runtime():
    messages = [{"role": "assistant", "content": "answer", "reasoning_content": "r"}]
    config = {"max_tokens": 10}
    snapshot = SessionSnapshot.capture(
        session_id="s1",
        model_alias="model",
        messages=messages,
        cwd="/work",
        workspace_dir="/workspace",
        config=config,
    )
    messages[0]["content"] = "changed"
    config["max_tokens"] = 20
    assert snapshot.messages[0]["content"] == "answer"
    assert snapshot.messages[0]["reasoning_content"] == "r"
    assert snapshot.runtime["config"] == {"max_tokens": 10}


def test_message_repair_preserves_complete_tool_groups_and_drops_dangling():
    complete = [
        {"role": "assistant", "tool_calls": [{"id": "ok"}]},
        {"role": "tool", "tool_call_id": "ok", "content": "done"},
    ]
    dangling = {"role": "assistant", "tool_calls": [{"id": "missing"}]}
    repaired = repair_dangling_tool_calls(
        [{"role": "user", "content": "start"}, *complete, dangling]
    )
    assert [message["role"] for message in repaired] == ["user", "assistant", "tool"]
