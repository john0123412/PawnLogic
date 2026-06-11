"""Tests for model stream consumption during a turn."""

from __future__ import annotations

import pytest

from core.turn_api import consume_model_stream


def _ensure_id(_tool_delta, iteration, idx):
    return f"call_{iteration}_{idx}"


def test_consume_model_stream_calls_retry_callback_before_continuing():
    events = []

    def deltas():
        events.append("yield retry")
        yield {"_retry": "HTTP 502 Bad Gateway: Retrying in 1s (1/3)."}
        events.append("after retry")
        yield {"choices": [{"delta": {"content": "ok"}}]}

    result = consume_model_stream(
        deltas(),
        ensure_tool_call_id=_ensure_id,
        iteration=2,
        on_retry=lambda detail: events.append(f"callback {detail}"),
    )

    assert events[:2] == [
        "yield retry",
        "callback HTTP 502 Bad Gateway: Retrying in 1s (1/3).",
    ]
    assert events[-1] == "after retry"
    assert result.retry_events == ["HTTP 502 Bad Gateway: Retrying in 1s (1/3)."]
    assert result.text == "ok"


def test_consume_model_stream_stops_on_http_error():
    seen = []

    result = consume_model_stream(
        iter([{"_error": "HTTP 403 Forbidden: API key rejected."}]),
        ensure_tool_call_id=_ensure_id,
        iteration=0,
        on_error=seen.append,
    )

    assert result.error == "HTTP 403 Forbidden: API key rejected."
    assert seen == ["HTTP 403 Forbidden: API key rejected."]
    assert result.text == ""
    assert result.tool_calls == {}


def test_consume_model_stream_collects_usage_reasoning_text_and_tool_calls():
    result = consume_model_stream(
        iter([
            {"_usage": {"prompt_tokens": 2, "completion_tokens": 3}},
            {"choices": [{"delta": {"reasoning_content": "hidden"}}]},
            {"choices": [{"delta": {"content": "visible"}}]},
            {
                "choices": [{
                    "delta": {
                        "tool_calls": [{
                            "index": 0,
                            "function": {"name": "read_", "arguments": '{"path"'},
                        }],
                    },
                }],
            },
            {
                "choices": [{
                    "delta": {
                        "tool_calls": [{
                            "index": 0,
                            "function": {"name": "file", "arguments": ': "x"}'},
                        }],
                    },
                }],
            },
        ]),
        ensure_tool_call_id=_ensure_id,
        iteration=4,
    )

    assert result.usage == {"prompt_tokens": 2, "completion_tokens": 3}
    assert result.reasoning == "hidden"
    assert result.text == "visible"
    assert result.tool_calls[0] == {
        "id": "call_4_0",
        "name": "read_file",
        "args": '{"path": "x"}',
    }


def test_consume_model_stream_propagates_keyboard_interrupt():
    def deltas():
        raise KeyboardInterrupt
        yield {}  # pragma: no cover

    with pytest.raises(KeyboardInterrupt):
        consume_model_stream(deltas(), ensure_tool_call_id=_ensure_id, iteration=0)
