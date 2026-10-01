"""Tests for the OpenAI Responses protocol adapter.

The Responses API is a third wire protocol: different endpoint, different
request body (``input`` / ``instructions`` / ``max_output_tokens`` /
``reasoning.effort``), and a typed event stream that terminates with
``response.completed`` instead of ``[DONE]``.

``core/provider_responses.py`` normalizes that stream into the delta-dict
contract ``core/turn_api.py`` already consumes, so the Turn path itself is
unchanged. These tests pin the normalization contract exactly, because two
mistakes here are silent rather than loud:

  * ``turn_api.py`` keys tool calls by ``tool_delta.get("index", 0)`` and
    appends ``arguments``. Responses events carry no integer index and repeat
    the full arguments in ``...arguments.done``, so an adapter that passes
    either through raw collapses parallel calls into one and doubles every
    argument string.
  * ``turn_api.py`` reads reasoning from ``reasoning_content`` only.
    Responses calls it ``reasoning_summary_text.delta``; mapping it to
    anything else drops the model's thinking on the floor with no error.
"""

from __future__ import annotations

import json

import pytest

from core import provider_responses
from core.provider_responses import (
    build_responses_payload,
    parse_responses_nonstream,
    parse_responses_sse_event,
    read_responses_sse_lines,
)
from core.turn_api import consume_model_stream


class _FakeStreamResponse:
    """Yields one SSE line per ``readline()``, the way ``http.client`` does."""

    def __init__(self, lines: list[bytes]):
        self._lines = list(lines)
        self.readline_calls = 0

    def readline(self):
        self.readline_calls += 1
        if self._lines:
            return self._lines.pop(0)
        return b""


def _frame(event: str, payload: dict) -> list[bytes]:
    """One SSE frame as the exact line sequence a socket would deliver."""
    return [
        f"event: {event}\n".encode(),
        f"data: {json.dumps(payload)}\n".encode(),
        b"\n",
    ]


def _stream(*frames: list[bytes]) -> list[bytes]:
    lines: list[bytes] = []
    for frame in frames:
        lines.extend(frame)
    return lines


# ── text ─────────────────────────────────────────────────────────


def test_output_text_delta_contract_exact_shape() -> None:
    state: dict = {}
    parsed = parse_responses_sse_event(
        "response.output_text.delta",
        json.dumps({"type": "response.output_text.delta", "delta": "Hello"}),
        state,
    )
    assert parsed == {
        "choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]
    }


def test_reasoning_summary_maps_onto_reasoning_content() -> None:
    # turn_api.py reads ``reasoning_content`` and nothing else in the repo
    # reads ``thinking``, so this is the only field name that works.
    state: dict = {}
    parsed = parse_responses_sse_event(
        "response.reasoning_summary_text.delta",
        json.dumps(
            {
                "type": "response.reasoning_summary_text.delta",
                "item_id": "rs_1",
                "summary_index": 0,
                "delta": "weighing options",
            }
        ),
        state,
    )
    assert parsed == {
        "choices": [
            {"delta": {"reasoning_content": "weighing options"}, "finish_reason": None}
        ]
    }


def test_malformed_json_yields_no_delta() -> None:
    assert (
        parse_responses_sse_event("response.output_text.delta", "{not json", {}) is None
    )


def test_unknown_event_type_is_ignored() -> None:
    assert (
        parse_responses_sse_event(
            "response.content_part.added", json.dumps({"type": "x"}), {}
        )
        is None
    )


# ── tool calls: the two silent-failure invariants ────────────────


def _tool_stream() -> dict:
    return parse_responses_sse_event(
        "response.output_item.added",
        json.dumps(
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_abc",
                    "name": "read_file",
                    "arguments": "",
                },
            }
        ),
        {},
    )


def test_output_item_added_registers_the_call_without_emitting_a_delta() -> None:
    # Nothing has been streamed yet; emitting a delta here would create an
    # entry whose arguments are still empty and could be double counted.
    assert _tool_stream() is None


def test_arguments_delta_carries_index_id_name_and_fragment() -> None:
    state: dict = {}
    _tool_stream_with_state(state)
    parsed = parse_responses_sse_event(
        "response.function_call_arguments.delta",
        json.dumps(
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_1",
                "output_index": 0,
                "delta": '{"path":',
            }
        ),
        state,
    )
    assert parsed == {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_abc",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path":',
                            },
                        }
                    ]
                },
                "finish_reason": None,
            }
        ]
    }


def _tool_stream_with_state(state: dict) -> None:
    parse_responses_sse_event(
        "response.output_item.added",
        json.dumps(
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_abc",
                    "name": "read_file",
                    "arguments": "",
                },
            }
        ),
        state,
    )


def test_arguments_done_does_not_re_emit_the_full_arguments() -> None:
    # turn_api.py does ``args += arguments``. Re-emitting the complete string
    # here would produce '{"path":"a.py"}{"path":"a.py"}' — a JSON parse
    # failure reported as a broken tool, not as a broken adapter.
    state: dict = {}
    _tool_stream_with_state(state)
    parse_responses_sse_event(
        "response.function_call_arguments.delta",
        json.dumps(
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_1",
                "delta": '{"path": "a.py"}',
            }
        ),
        state,
    )
    replay = parse_responses_sse_event(
        "response.function_call_arguments.done",
        json.dumps(
            {
                "type": "response.function_call_arguments.done",
                "item_id": "fc_1",
                "arguments": '{"path": "a.py"}',
            }
        ),
        state,
    )
    assert replay is None


def test_arguments_done_still_registers_a_call_that_streamed_no_fragment() -> None:
    # A zero-argument call emits no .delta event at all. Without this the tool
    # call vanishes silently and the turn ends with an empty result.
    state: dict = {}
    _tool_stream_with_state(state)
    parsed = parse_responses_sse_event(
        "response.function_call_arguments.done",
        json.dumps(
            {
                "type": "response.function_call_arguments.done",
                "item_id": "fc_1",
                "arguments": "{}",
            }
        ),
        state,
    )
    assert parsed is not None
    tool_delta = parsed["choices"][0]["delta"]["tool_calls"][0]
    assert tool_delta["index"] == 0
    assert tool_delta["id"] == "call_abc"
    assert tool_delta["function"]["name"] == "read_file"
    assert tool_delta["function"]["arguments"] == "{}"


def test_parallel_function_calls_get_distinct_stable_indices() -> None:
    state: dict = {}
    for output_index, (item_id, call_id, name) in enumerate(
        [("fc_1", "call_a", "read_file"), ("fc_2", "call_b", "run_shell")]
    ):
        parse_responses_sse_event(
            "response.output_item.added",
            json.dumps(
                {
                    "type": "response.output_item.added",
                    "output_index": output_index,
                    "item": {
                        "type": "function_call",
                        "id": item_id,
                        "call_id": call_id,
                        "name": name,
                        "arguments": "",
                    },
                }
            ),
            state,
        )

    fragments = ["{", "}"]
    indices: list[int] = []
    for step, fragment in enumerate(fragments):
        parsed = parse_responses_sse_event(
            "response.function_call_arguments.delta",
            json.dumps(
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": "fc_1" if step % 2 == 0 else "fc_2",
                    "delta": fragment,
                }
            ),
            state,
        )
        indices.append(parsed["choices"][0]["delta"]["tool_calls"][0]["index"])

    # Interleaved fragments must not both collapse onto index 0, which is what
    # turn_api.py would use when no index is supplied.
    assert indices == [0, 1]


def test_a_fragment_without_a_preceding_item_added_still_gets_an_index() -> None:
    # Some relays emit arguments deltas without the opening item event.
    state: dict = {}
    parsed = parse_responses_sse_event(
        "response.function_call_arguments.delta",
        json.dumps(
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_late",
                "call_id": "call_late",
                "delta": "{}",
            }
        ),
        state,
    )
    assert parsed["choices"][0]["delta"]["tool_calls"][0]["index"] == 0


# ── terminal events ──────────────────────────────────────────────


def test_response_completed_emits_finish_reason_and_usage() -> None:
    parsed = parse_responses_sse_event(
        "response.completed",
        json.dumps(
            {
                "type": "response.completed",
                "response": {
                    "usage": {
                        "input_tokens": 11,
                        "output_tokens": 7,
                        "total_tokens": 18,
                    }
                },
            }
        ),
        {},
    )
    assert parsed["choices"] == [{"delta": {}, "finish_reason": "stop"}]
    assert parsed["_usage"] == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }


def test_response_incomplete_reports_length_finish_reason() -> None:
    parsed = parse_responses_sse_event(
        "response.incomplete",
        json.dumps(
            {
                "type": "response.incomplete",
                "response": {
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "usage": {"input_tokens": 5, "output_tokens": 100},
                },
            }
        ),
        {},
    )
    assert parsed["choices"][0]["finish_reason"] == "length"
    assert parsed["_usage"]["output_tokens"] == 100


def test_response_failed_becomes_an_error_delta() -> None:
    parsed = parse_responses_sse_event(
        "response.failed",
        json.dumps(
            {
                "type": "response.failed",
                "response": {
                    "error": {"code": "server_error", "message": "upstream exploded"}
                },
            }
        ),
        {},
    )
    assert parsed["_error"] == "Responses stream failed: upstream exploded"
    assert "choices" not in parsed


def test_bare_error_event_becomes_an_error_delta() -> None:
    parsed = parse_responses_sse_event(
        "error",
        json.dumps({"type": "error", "message": "rate limited"}),
        {},
    )
    assert parsed["_error"] == "Responses stream error: rate limited"


# ── the read loop: no [DONE] terminator exists ───────────────────


def test_read_loop_stops_at_response_completed_without_a_done_sentinel() -> None:
    leaked = _frame(
        "response.output_text.delta",
        {"type": "response.output_text.delta", "delta": "LEAKED"},
    )
    resp = _FakeStreamResponse(
        _stream(
            _frame("response.created", {"type": "response.created"}),
            _frame(
                "response.output_text.delta",
                {"type": "response.output_text.delta", "delta": "hi"},
            ),
            _frame(
                "response.completed",
                {
                    "type": "response.completed",
                    "response": {"usage": {"input_tokens": 1, "output_tokens": 2}},
                },
            ),
            # Anything after the terminal event belongs to a different
            # response and must never be consumed.
            leaked,
        )
    )
    events = list(
        read_responses_sse_lines(
            resp, read_timeout=10, raise_if_interrupted=lambda: None
        )
    )
    assert [e for e in events if "choices" in e] == [
        {"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]
    assert events[-2:] != []
    # The reader must have returned before touching the trailing frame.
    assert leaked[0] in resp._lines


def test_read_loop_ends_after_three_empty_reads() -> None:
    resp = _FakeStreamResponse(
        _stream(_frame("response.created", {"type": "response.created"}))
    )
    frame_lines = 3
    events = list(
        read_responses_sse_lines(
            resp, read_timeout=10, raise_if_interrupted=lambda: None
        )
    )
    assert events == []
    # frame lines, then two tolerated empty reads; the third terminates
    assert resp.readline_calls == frame_lines + 3


def test_read_loop_reports_a_read_timeout_as_an_error_delta() -> None:
    class _TimingOut:
        def readline(self):
            raise TimeoutError

    events = list(
        read_responses_sse_lines(
            _TimingOut(), read_timeout=7, raise_if_interrupted=lambda: None
        )
    )
    assert len(events) == 1
    assert "Read timeout (7s)" in events[0]["_error"]


def test_read_loop_marks_partial_text_when_the_connection_drops() -> None:
    class _Dying:
        def __init__(self) -> None:
            self._lines = _stream(
                _frame(
                    "response.output_text.delta",
                    {"type": "response.output_text.delta", "delta": "partial"},
                )
            )

        def readline(self):
            if self._lines:
                return self._lines.pop(0)
            raise OSError("connection reset")

    events = list(
        read_responses_sse_lines(
            _Dying(), read_timeout=10, raise_if_interrupted=lambda: None
        )
    )
    assert events[-1]["_partial_end"] is True
    assert "_error" in events[-1]


# ── end-to-end through the real Turn consumer ────────────────────


def test_normalized_stream_is_consumable_by_turn_api() -> None:
    resp = _FakeStreamResponse(
        _stream(
            _frame(
                "response.reasoning_summary_text.delta",
                {
                    "type": "response.reasoning_summary_text.delta",
                    "delta": "thinking",
                },
            ),
            _frame(
                "response.output_item.added",
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {
                        "type": "function_call",
                        "id": "fc_1",
                        "call_id": "call_abc",
                        "name": "read_file",
                        "arguments": "",
                    },
                },
            ),
            _frame(
                "response.function_call_arguments.delta",
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": "fc_1",
                    "delta": '{"path": "a.py"}',
                },
            ),
            _frame(
                "response.function_call_arguments.done",
                {
                    "type": "response.function_call_arguments.done",
                    "item_id": "fc_1",
                    "arguments": '{"path": "a.py"}',
                },
            ),
            _frame(
                "response.output_text.delta",
                {"type": "response.output_text.delta", "delta": "done"},
            ),
            _frame(
                "response.completed",
                {
                    "type": "response.completed",
                    "response": {"usage": {"input_tokens": 9, "output_tokens": 4}},
                },
            ),
        )
    )
    result = consume_model_stream(
        read_responses_sse_lines(
            resp, read_timeout=10, raise_if_interrupted=lambda: None
        ),
        ensure_tool_call_id=lambda tcd, iteration, idx: tcd.get("id") or "x",
        iteration=1,
    )
    assert result.error is None
    assert result.text == "done"
    assert result.reasoning == "thinking"
    assert result.tool_calls == {
        0: {"id": "call_abc", "name": "read_file", "args": '{"path": "a.py"}'}
    }
    assert result.usage == {"prompt_tokens": 9, "completion_tokens": 4}


# ── request payload ──────────────────────────────────────────────


def test_payload_uses_responses_field_names() -> None:
    payload = build_responses_payload(
        [{"role": "user", "content": "hello"}],
        "plain-model",
        "plain-model-id",
        321,
        None,
        "auto",
        None,
    )
    assert payload["model"] == "plain-model-id"
    assert payload["max_output_tokens"] == 321
    assert payload["stream"] is True
    assert payload["store"] is False
    assert "max_tokens" not in payload
    assert "messages" not in payload


def test_payload_does_not_send_flat_reasoning_effort() -> None:
    payload = build_responses_payload(
        [{"role": "user", "content": "hello"}],
        "plain-model",
        "plain-model-id",
        100,
        None,
        "auto",
        None,
    )
    # A model with no declared effort map must get no reasoning field at all.
    assert "reasoning_effort" not in payload
    assert "reasoning" not in payload


def test_payload_nests_reasoning_effort_when_the_model_declares_one() -> None:
    from core import api_payloads

    original = api_payloads.resolve_reasoning_effort
    api_payloads.resolve_reasoning_effort = lambda alias: "high"
    try:
        payload = build_responses_payload(
            [{"role": "user", "content": "hello"}],
            "plain-model",
            "plain-model-id",
            100,
            None,
            "auto",
            None,
        )
    finally:
        api_payloads.resolve_reasoning_effort = original
    assert payload["reasoning"] == {"effort": "high"}


def test_payload_lifts_system_messages_into_instructions() -> None:
    payload = build_responses_payload(
        [
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": "hi"},
        ],
        "plain-model",
        "plain-model-id",
        100,
        None,
        "auto",
        None,
    )
    assert payload["instructions"] == "be terse"
    assert [item["role"] for item in payload["input"]] == ["user"]


def test_payload_converts_tools_and_tool_results_to_function_items() -> None:
    payload = build_responses_payload(
        [
            {"role": "user", "content": "read a.py"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_abc",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path": "a.py"}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_abc", "content": "print(1)"},
        ],
        "plain-model",
        "plain-model-id",
        100,
        [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "read",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        "auto",
        None,
    )
    assert payload["tools"] == [
        {
            "type": "function",
            "name": "read_file",
            "description": "read",
            "parameters": {"type": "object", "properties": {}},
        }
    ]
    kinds = [item.get("type") for item in payload["input"]]
    assert kinds == ["message", "function_call", "function_call_output"]
    assert payload["input"][1]["call_id"] == "call_abc"
    assert payload["input"][1]["arguments"] == '{"path": "a.py"}'
    assert payload["input"][2] == {
        "type": "function_call_output",
        "call_id": "call_abc",
        "output": "print(1)",
    }


def test_payload_keeps_assistant_text_alongside_its_tool_calls() -> None:
    payload = build_responses_payload(
        [
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": "on it",
                "reasoning_content": "dropped",
                "tool_calls": [
                    {
                        "id": "call_a",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                    }
                ],
            },
        ],
        "plain-model",
        "plain-model-id",
        100,
        None,
        "auto",
        None,
    )
    assert payload["input"][1] == {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "on it"}],
    }
    # reasoning_content has no Responses equivalent in the request body.
    assert "reasoning_content" not in json.dumps(payload)


def test_payload_maps_tool_choice_object_form() -> None:
    payload = build_responses_payload(
        [{"role": "user", "content": "go"}],
        "plain-model",
        "plain-model-id",
        100,
        [
            {
                "type": "function",
                "function": {"name": "read_file", "parameters": {}},
            }
        ],
        {"type": "function", "function": {"name": "read_file"}},
        None,
    )
    assert payload["tool_choice"] == {"type": "function", "name": "read_file"}


def test_payload_maps_json_response_format_into_text_format() -> None:
    payload = build_responses_payload(
        [{"role": "user", "content": "go"}],
        "plain-model",
        "plain-model-id",
        100,
        None,
        "auto",
        {"type": "json_object"},
    )
    assert payload["text"] == {"format": {"type": "json_object"}}


# ── non-streaming response ───────────────────────────────────────


def test_nonstream_parses_output_text() -> None:
    raw = json.dumps(
        {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "hello world"}],
                }
            ]
        }
    ).encode()
    assert parse_responses_nonstream(raw) == ("hello world", None)


def test_nonstream_reports_a_missing_output_array() -> None:
    text, error = parse_responses_nonstream(b'{"id": "resp_1"}')
    assert text == ""
    assert error is not None and "output" in error


def test_nonstream_reports_invalid_json() -> None:
    text, error = parse_responses_nonstream(b"{not json")
    assert text == ""
    assert error is not None and "Invalid JSON" in error


# ── registration ─────────────────────────────────────────────────


def test_stream_dispatcher_selects_the_responses_reader() -> None:
    from core import provider_streams

    resp = _FakeStreamResponse(
        _stream(
            _frame(
                "response.output_text.delta",
                {"type": "response.output_text.delta", "delta": "x"},
            ),
            _frame(
                "response.completed",
                {
                    "type": "response.completed",
                    "response": {"usage": {"input_tokens": 1, "output_tokens": 1}},
                },
            ),
        )
    )
    events = list(
        provider_streams.read_sse_lines(
            resp, "responses", read_timeout=10, raise_if_interrupted=lambda: None
        )
    )
    assert events[0]["choices"][0]["delta"] == {"content": "x"}


def test_stream_dispatcher_refuses_an_unregistered_format() -> None:
    from core import provider_streams

    with pytest.raises(ValueError, match="Unsupported API format"):
        list(
            provider_streams.read_sse_lines(
                _FakeStreamResponse([]),
                "gemini",
                read_timeout=10,
                raise_if_interrupted=lambda: None,
            )
        )


def test_responses_is_a_registered_format() -> None:
    from core.provider_formats import VALID_API_FORMATS

    assert "responses" in VALID_API_FORMATS
    assert provider_responses.RESPONSES_FORMAT == "responses"
