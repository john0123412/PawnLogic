"""Tests for context window helpers."""

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.context_window import (
    _ctx_chars,
    _drop_dangling_tool_call_messages,
    _trim_and_compact_context,
)


def _msg(role, content="", **kw):
    msg = {"role": role, "content": content}
    msg.update(kw)
    return msg


def test_ctx_chars_counts_content_and_reasoning():
    msgs = [
        _msg("user", "hello"),
        _msg("assistant", "ok", reasoning_content="thinking"),
        _msg("assistant", None),
    ]

    assert _ctx_chars(msgs) == len("hello") + len("ok") + len("thinking")


def test_trim_no_op_when_under_limit(monkeypatch):
    from config import DYNAMIC_CONFIG

    monkeypatch.setitem(DYNAMIC_CONFIG, "ctx_max_chars", 10_000)
    msgs = [_msg("system", "sys"), _msg("user", "short")]
    original = list(msgs)

    assert _trim_and_compact_context(msgs) == 0
    assert msgs == original


def test_trim_compacts_old_messages_and_preserves_tail(monkeypatch):
    from config import DYNAMIC_CONFIG

    monkeypatch.setitem(DYNAMIC_CONFIG, "ctx_max_chars", 10)
    msgs = [
        _msg("system", "sys"),
        _msg("user", "old user message " * 20),
        _msg(
            "assistant",
            "",
            tool_calls=[{"function": {"name": "run_shell"}}],
        ),
        _msg("tool", "large output", tool_call_id="call-1"),
        *[_msg("user", f"tail-{i}") for i in range(10)],
    ]

    dropped = _trim_and_compact_context(msgs)

    assert dropped == 3
    assert msgs[0] == _msg("system", "sys")
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["_pinned"] is True
    assert "Context Compacted" in msgs[1]["content"]
    assert "tool_calls: run_shell" in msgs[1]["content"]
    assert "Tool output compacted to save context" in msgs[1]["content"]
    assert [m["content"] for m in msgs[-10:]] == [f"tail-{i}" for i in range(10)]


def test_trim_returns_zero_when_too_few_messages(monkeypatch):
    from config import DYNAMIC_CONFIG

    monkeypatch.setitem(DYNAMIC_CONFIG, "ctx_max_chars", 1)
    msgs = [_msg("system", "sys"), _msg("user", "large content")]

    assert _trim_and_compact_context(msgs) == 0
    assert len(msgs) == 2


def test_drop_dangling_tool_call_messages_removes_unmatched_calls():
    msgs = [
        _msg("system", "sys"),
        _msg("assistant", "", tool_calls=[{"id": "call-a", "function": {"name": "run_shell"}}]),
        _msg("user", "next"),
    ]

    cleaned = _drop_dangling_tool_call_messages(msgs)

    assert cleaned == [_msg("system", "sys"), _msg("user", "next")]


def test_drop_dangling_tool_call_messages_keeps_matched_calls():
    assistant = _msg(
        "assistant",
        "",
        tool_calls=[
            {"id": "call-a", "function": {"name": "run_shell"}},
            {"id": "call-b", "function": {"name": "read_file"}},
        ],
    )
    tool_a = _msg("tool", "a", tool_call_id="call-a")
    tool_b = _msg("tool", "b", tool_call_id="call-b")
    msgs = [_msg("system", "sys"), assistant, tool_a, tool_b, _msg("user", "next")]

    cleaned = _drop_dangling_tool_call_messages(msgs)

    assert cleaned == msgs
