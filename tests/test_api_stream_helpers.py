from __future__ import annotations

from core import api_client


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
