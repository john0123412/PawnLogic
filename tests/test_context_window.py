"""Tests for context window helpers.

The only compaction path is ``core.context_manager.ContextManager`` (covered
by ``tests/test_context_manager.py``). These tests pin the surviving helpers.
"""

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import core.context_window as context_window
from core.context_window import (
    _ctx_chars,
    _drop_dangling_tool_call_messages,
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


def test_no_history_rewriting_compaction_path_is_exported():
    # The destructive compaction helper was removed on purpose: rewriting
    # canonical history with truncated placeholders lost exact values
    # (addresses, offsets) and diverged from the live ContextManager path.
    assert not hasattr(context_window, "_trim_and_compact_context")
    assert not hasattr(context_window, "_bounded_summary_content")


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
