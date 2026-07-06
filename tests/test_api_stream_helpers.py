from __future__ import annotations

from core import api_client
from core import api_payloads
from core import provider_streams


class _FakeStreamResponse:
    def __init__(self, lines: list[bytes], error_after_lines: Exception | None = None):
        self._lines = list(lines)
        self._error_after_lines = error_after_lines

    def readline(self):
        if self._lines:
            return self._lines.pop(0)
        if self._error_after_lines is not None:
            raise self._error_after_lines
        return b""


def test_build_openai_payload_sanitizes_reasoning_and_attaches_tools():
    messages = [
        {"role": "user", "content": "hello", "_private": "drop"},
        {"role": "assistant", "content": "answer", "reasoning_content": "drop for non reasoning"},
    ]
    tools = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]

    payload = api_client._build_openai_payload(
        messages,
        "plain-model",
        "plain-model-id",
        123,
        tools,
        "auto",
        {"type": "json_object"},
    )

    assert payload["model"] == "plain-model-id"
    assert payload["max_tokens"] == 123
    assert payload["stream"] is True
    assert payload["tools"] == tools
    assert payload["tool_choice"] == "auto"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["stream_options"] == {"include_usage": True}
    assert "_private" not in payload["messages"][0]
    assert "reasoning_content" not in payload["messages"][1]


def test_build_openai_headers_matches_existing_stream_request_headers():
    headers = api_client._build_openai_headers("secret-key", 42)

    assert headers == {
        "Authorization": "Bearer secret-key",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
        "Content-Length": "42",
    }


def test_read_openai_sse_lines_yields_usage_and_stops_on_done():
    response = _FakeStreamResponse([
        b'data: {"choices":[{"delta":{"content":"ok"}}],"usage":{"prompt_tokens":1}}\r\n',
        b"data: [DONE]\r\n",
        b'data: {"choices":[{"delta":{"content":"ignored"}}]}\r\n',
    ])

    events = list(api_client._read_openai_sse_lines(response))

    assert events == [
        {"_usage": {"prompt_tokens": 1}},
        {"choices": [{"delta": {"content": "ok"}}], "usage": {"prompt_tokens": 1}},
    ]


def test_read_openai_sse_lines_text_delta_contract_exact_shape():
    response = _FakeStreamResponse([
        b'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":null}]}\r\n',
        b"data: [DONE]\r\n",
    ])

    events = list(provider_streams.read_openai_sse_lines(
        response,
        read_timeout=60,
        raise_if_interrupted=lambda: None,
    ))

    assert events == [
        {"choices": [{"delta": {"content": "hello"}, "finish_reason": None}]},
    ]
    assert set(events[0]) == {"choices"}
    assert set(events[0]["choices"][0]) == {"delta", "finish_reason"}


def test_read_openai_sse_lines_usage_chunk_contract_exact_shape():
    response = _FakeStreamResponse([
        (
            b'data: {"choices":[],"usage":{"prompt_tokens":3,'
            b'"completion_tokens":4,"total_tokens":7}}\r\n'
        ),
        b"data: [DONE]\r\n",
    ])

    events = list(provider_streams.read_openai_sse_lines(
        response,
        read_timeout=60,
        raise_if_interrupted=lambda: None,
    ))

    assert events == [
        {"_usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}},
        {
            "choices": [],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        },
    ]


def test_read_anthropic_sse_lines_yields_usage_and_text_delta():
    response = _FakeStreamResponse([
        b"event: message_start\r\n",
        b'data: {"type":"message_start","message":{"usage":{"input_tokens":2}}}\r\n',
        b"event: content_block_delta\r\n",
        b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hi"}}\r\n',
        b"event: message_stop\r\n",
        b'data: {"type":"message_stop"}\r\n',
    ])

    events = list(api_client._read_anthropic_sse_lines(response))

    assert events == [
        {"_usage": {"input_tokens": 2}},
        {"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]},
    ]


def test_read_anthropic_sse_lines_text_delta_contract_exact_shape():
    response = _FakeStreamResponse([
        b"event: content_block_delta\r\n",
        (
            b'data: {"type":"content_block_delta","index":0,'
            b'"delta":{"type":"text_delta","text":"hello"}}\r\n'
        ),
    ])

    events = list(provider_streams.read_anthropic_sse_lines(
        response,
        read_timeout=60,
        raise_if_interrupted=lambda: None,
    ))

    assert events == [
        {"choices": [{"delta": {"content": "hello"}, "finish_reason": None}]},
    ]
    assert set(events[0]) == {"choices"}
    assert set(events[0]["choices"][0]) == {"delta", "finish_reason"}


def test_anthropic_message_delta_usage_and_finish_contract_exact_shape():
    event = provider_streams.parse_anthropic_sse_event(
        "message_delta",
        (
            '{"type":"message_delta","usage":{"output_tokens":5},'
            '"delta":{"stop_reason":"end_turn"}}'
        ),
        {"tool_blocks": {}},
    )

    assert event == {
        "_usage": {"output_tokens": 5},
        "choices": [{"delta": {}, "finish_reason": "end_turn"}],
    }
    assert set(event) == {"_usage", "choices"}


def test_read_anthropic_sse_lines_yields_tool_use_deltas():
    response = _FakeStreamResponse([
        b"event: content_block_start\r\n",
        (
            b'data: {"type":"content_block_start","index":0,'
            b'"content_block":{"type":"tool_use","id":"toolu_1","name":"read_file","input":{}}}\r\n'
        ),
        b"event: content_block_delta\r\n",
        (
            b'data: {"type":"content_block_delta","index":0,'
            b'"delta":{"type":"input_json_delta","partial_json":"{\\"path\\""}}\r\n'
        ),
        b"event: content_block_delta\r\n",
        (
            b'data: {"type":"content_block_delta","index":0,'
            b'"delta":{"type":"input_json_delta","partial_json":":\\"README.md\\"}"}}\r\n'
        ),
        b"event: content_block_stop\r\n",
        b'data: {"type":"content_block_stop","index":0}\r\n',
        b"event: message_stop\r\n",
        b'data: {"type":"message_stop"}\r\n',
    ])

    events = list(api_client._read_anthropic_sse_lines(response))

    assert events == [
        {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "toolu_1",
                        "function": {"name": "read_file", "arguments": '{"path"'},
                    }],
                },
                "finish_reason": None,
            }],
        },
        {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "toolu_1",
                        "function": {"name": "read_file", "arguments": ':"README.md"}'},
                    }],
                },
                "finish_reason": None,
            }],
        },
    ]


def test_read_openai_sse_lines_preserves_tool_delta_order_and_identity():
    response = _FakeStreamResponse([
        (
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
            b'"id":"call_1","function":{"name":"read_file","arguments":"{\\"path\\""}}]},'
            b'"finish_reason":null}]}\r\n'
        ),
        (
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":1,'
            b'"id":"call_2","function":{"name":"list_dir","arguments":"{\\"path\\":\\".\\"}"}}]},'
            b'"finish_reason":null}]}\r\n'
        ),
        b"data: [DONE]\r\n",
    ])

    events = list(provider_streams.read_openai_sse_lines(
        response,
        read_timeout=60,
        raise_if_interrupted=lambda: None,
    ))

    tool_calls = [
        event["choices"][0]["delta"]["tool_calls"][0]
        for event in events
    ]
    assert [(call["index"], call["id"], call["function"]["name"]) for call in tool_calls] == [
        (0, "call_1", "read_file"),
        (1, "call_2", "list_dir"),
    ]
    assert tool_calls[0]["function"]["arguments"] == '{"path"'
    assert tool_calls[1]["function"]["arguments"] == '{"path":"."}'


def test_stream_interruption_delta_returns_none_without_partial_text():
    assert api_client._stream_interruption_delta(OSError("connection lost"), "") is None


def test_stream_interruption_delta_reports_partial_text():
    event = api_client._stream_interruption_delta(OSError("connection lost"), "partial")

    assert event == {
        "_partial_end": True,
        "_error": "Stream interrupted after partial content: connection lost",
    }


def test_read_anthropic_sse_lines_preserves_multiple_tool_use_delta_order():
    response = _FakeStreamResponse([
        b"event: content_block_start\r\n",
        (
            b'data: {"type":"content_block_start","index":0,'
            b'"content_block":{"type":"tool_use","id":"toolu_1","name":"read_file","input":{}}}\r\n'
        ),
        b"event: content_block_delta\r\n",
        (
            b'data: {"type":"content_block_delta","index":0,'
            b'"delta":{"type":"input_json_delta","partial_json":"{\\"path\\":\\"README.md\\"}"}}\r\n'
        ),
        b"event: content_block_start\r\n",
        (
            b'data: {"type":"content_block_start","index":1,'
            b'"content_block":{"type":"tool_use","id":"toolu_2","name":"list_dir","input":{}}}\r\n'
        ),
        b"event: content_block_delta\r\n",
        (
            b'data: {"type":"content_block_delta","index":1,'
            b'"delta":{"type":"input_json_delta","partial_json":"{\\"path\\":\\".\\"}"}}\r\n'
        ),
        b"event: message_stop\r\n",
        b'data: {"type":"message_stop"}\r\n',
    ])

    events = list(api_client._read_anthropic_sse_lines(response))

    tool_calls = [
        event["choices"][0]["delta"]["tool_calls"][0]
        for event in events
        if "tool_calls" in event["choices"][0]["delta"]
    ]
    assert [(call["index"], call["id"], call["function"]["name"]) for call in tool_calls] == [
        (0, "toolu_1", "read_file"),
        (1, "toolu_2", "list_dir"),
    ]


def test_read_openai_sse_lines_reports_partial_end_after_content_then_oserror():
    response = _FakeStreamResponse(
        [b'data: {"choices":[{"delta":{"content":"partial"}}]}\r\n'],
        error_after_lines=OSError("connection lost"),
    )

    events = list(api_client._read_openai_sse_lines(response))

    assert events == [
        {"choices": [{"delta": {"content": "partial"}}]},
        {"_partial_end": True, "_error": "Stream interrupted after partial content: connection lost"},
    ]


def test_read_openai_sse_lines_reraises_oserror_without_partial_content():
    response = _FakeStreamResponse([], error_after_lines=OSError("connection lost"))

    try:
        list(api_client._read_openai_sse_lines(response))
    except OSError as exc:
        assert str(exc) == "connection lost"
    else:
        raise AssertionError("expected OSError")


def test_read_anthropic_sse_lines_reraises_oserror_without_partial_content():
    response = _FakeStreamResponse([], error_after_lines=OSError("connection lost"))

    try:
        list(api_client._read_anthropic_sse_lines(response))
    except OSError as exc:
        assert str(exc) == "connection lost"
    else:
        raise AssertionError("expected OSError")


def test_read_sse_lines_selects_provider_reader():
    openai_response = _FakeStreamResponse([b'data: {"choices":[{"delta":{"content":"ok"}}]}\r\n'])
    anthropic_response = _FakeStreamResponse([
        b"event: content_block_delta\r\n",
        b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hi"}}\r\n',
    ])

    assert list(api_client._read_sse_lines(openai_response, "openai")) == [
        {"choices": [{"delta": {"content": "ok"}}]},
    ]
    assert list(api_client._read_sse_lines(anthropic_response, "anthropic")) == [
        {"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]},
    ]


def test_provider_streams_selector_matches_api_client_wrapper():
    openai_response = _FakeStreamResponse([b'data: {"choices":[{"delta":{"content":"ok"}}]}\r\n'])

    events = list(provider_streams.read_sse_lines(
        openai_response,
        "openai",
        read_timeout=60,
        raise_if_interrupted=lambda: None,
    ))

    assert events == [{"choices": [{"delta": {"content": "ok"}}]}]


def test_api_client_stream_helpers_are_compatibility_wrappers():
    event = api_client._anthropic_parse_sse(
        "content_block_delta",
        '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hi"}}',
        {"tool_blocks": {}},
    )

    assert event == {"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]}
    assert api_client.parse_sse_delta('{"choices":[]}') == {"choices": []}
    assert api_client._stream_interruption_delta(
        OSError("connection lost"), "partial"
    ) == provider_streams.stream_interruption_delta(
        OSError("connection lost"), "partial"
    )


def test_api_payload_builders_remain_api_client_compatibility_helpers():
    assert api_client._build_openai_payload is api_payloads._build_openai_payload
    assert api_client._build_openai_headers is api_payloads._build_openai_headers
    assert api_client._anthropic_build_payload is api_payloads._anthropic_build_payload
    assert api_client._anthropic_build_headers is api_payloads._anthropic_build_headers
    assert api_client._sanitize_messages_for_model is api_payloads._sanitize_messages_for_model
