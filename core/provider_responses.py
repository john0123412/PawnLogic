"""core/provider_responses.py - OpenAI Responses protocol adapter.

The Responses API is the third supported wire protocol. It differs from the
other two on every axis that used to be assumed:

* endpoint ``POST {base}/v1/responses`` rather than ``/chat/completions`` or
  ``/messages``;
* a request body built from ``input`` / ``instructions`` /
  ``max_output_tokens`` / ``text.format``, with tool calls and tool results as
  first-class ``function_call`` / ``function_call_output`` items rather than
  fields on a message;
* a typed event stream that terminates with ``response.completed`` and never
  sends the ``[DONE]`` sentinel the OpenAI reader keys on;
* reasoning carried as ``reasoning_summary_text.delta`` events, and
  ``reasoning: {"effort": ...}`` in the request rather than a flat
  ``reasoning_effort``.

Everything here normalizes into the delta-dict contract that
``core/turn_api.py`` consumes, so the Turn path, the session, and delegation
need no changes at all. That contract has two sharp edges which are silent
rather than loud, and which the adapter must satisfy exactly:

``turn_api.py`` keys tool calls with ``tool_delta.get("index", 0)`` and
accumulates ``args += arguments``. Responses events carry no integer index and
repeat the complete arguments in ``...arguments.done``. So the adapter assigns
each ``item_id`` its own stable integer slot, and emits only the incremental
fragments -- re-emitting the terminal arguments would double every argument
string into unparseable JSON.

``turn_api.py`` reads reasoning from ``reasoning_content``; nothing in the
repository reads a ``thinking`` spelling. So the reasoning events map onto
``reasoning_content``.

The read loop lives here rather than in ``core/provider_streams.py`` because
it imports the shared timeout/interruption helpers from that module, and the
dispatcher there imports this one.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from core.provider_streams import (
    InterruptCheck,
    StreamResponse,
    _MAX_CONSECUTIVE_EMPTY_READS,
    _read_timeout_delta,
    stream_interruption_delta,
)

RESPONSES_FORMAT = "responses"

# Reasoning arrives under two event names depending on whether the provider
# emits the summarized or the raw form. Both land on the same normalized key.
_REASONING_DELTA_EVENTS = frozenset(
    {
        "response.reasoning_summary_text.delta",
        "response.reasoning_text.delta",
    }
)

_FINISH_REASONS = {
    "max_output_tokens": "length",
    "content_filter": "content_filter",
}


def _tool_items(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return state.setdefault("tool_items", {})


def _slot_for(
    state: dict[str, Any],
    item_id: str,
    *,
    call_id: str = "",
    name: str = "",
) -> dict[str, Any]:
    """Return (creating if needed) the stable slot record for one call item.

    Responses identifies a tool call by ``item_id``, never by an integer
    index, and ``turn_api.py`` falls back to index 0 for any delta without
    one. Two parallel calls therefore need two distinct slots assigned here or
    they collapse into a single entry with both argument strings appended.
    """
    items = _tool_items(state)
    record = items.get(item_id)
    if record is None:
        record = {
            "slot": len(items),
            "call_id": call_id,
            "name": name,
            "emitted": False,
        }
        items[item_id] = record
    else:
        # A relay may open the call in one frame and identify it in another.
        if call_id and not record["call_id"]:
            record["call_id"] = call_id
        if name and not record["name"]:
            record["name"] = name
    return record


def _tool_call_delta(record: dict[str, Any], arguments: str) -> dict[str, Any] | None:
    if not arguments:
        return None
    record["emitted"] = True
    return {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": record["slot"],
                            "id": record["call_id"],
                            "function": {
                                "name": record["name"],
                                "arguments": arguments,
                            },
                        }
                    ]
                },
                "finish_reason": None,
            }
        ]
    }


def _register_output_item(state: dict[str, Any], item: dict[str, Any]) -> None:
    if not isinstance(item, dict) or item.get("type") != "function_call":
        return
    _slot_for(
        state,
        str(item.get("id") or item.get("call_id") or f"item_{len(_tool_items(state))}"),
        call_id=str(item.get("call_id") or ""),
        name=str(item.get("name") or ""),
    )


def _finish_reason(response: dict[str, Any]) -> str:
    details = response.get("incomplete_details")
    reason = details.get("reason") if isinstance(details, dict) else None
    return _FINISH_REASONS.get(str(reason), "stop")


def parse_responses_sse_event(
    event_type: str,
    data_raw: str,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    """Normalize one Responses SSE event into the unified delta dict."""
    try:
        data = json.loads(data_raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    etype = str(data.get("type") or event_type or "")

    if etype in ("response.output_item.added", "response.output_item.done"):
        _register_output_item(state, data.get("item") or {})
        return None

    if etype == "response.output_text.delta":
        delta = data.get("delta") or ""
        if not delta:
            return None
        return {"choices": [{"delta": {"content": delta}, "finish_reason": None}]}

    if etype in _REASONING_DELTA_EVENTS:
        delta = data.get("delta") or ""
        if not delta:
            return None
        return {
            "choices": [{"delta": {"reasoning_content": delta}, "finish_reason": None}]
        }

    if etype == "response.function_call_arguments.delta":
        item_id = str(data.get("item_id") or data.get("id") or "")
        record = _slot_for(
            state,
            item_id or f"item_{len(_tool_items(state))}",
            call_id=str(data.get("call_id") or ""),
            name=str(data.get("name") or ""),
        )
        return _tool_call_delta(record, str(data.get("delta") or ""))

    if etype == "response.function_call_arguments.done":
        item_id = str(data.get("item_id") or data.get("id") or "")
        record = _slot_for(state, item_id or f"item_{len(_tool_items(state))}")
        if record["emitted"]:
            # The complete arguments are a summary of what already streamed.
            # Passing them on would double the string ``turn_api.py`` appends.
            return None
        # A zero-argument call emits no .delta event at all. Without this the
        # call would never reach the Turn and the turn would end empty.
        return _tool_call_delta(record, str(data.get("arguments") or "{}"))

    if etype in ("response.completed", "response.incomplete", "response.failed"):
        response = data.get("response")
        response = response if isinstance(response, dict) else {}
        if etype == "response.failed":
            error = response.get("error")
            message = error.get("message") if isinstance(error, dict) else None
            return {"_error": f"Responses stream failed: {message or 'unknown error'}"}
        result: dict[str, Any] = {
            "choices": [{"delta": {}, "finish_reason": _finish_reason(response)}]
        }
        usage = response.get("usage")
        if isinstance(usage, dict) and usage:
            result["_usage"] = usage
        return result

    if etype == "error":
        message = data.get("message")
        error = data.get("error")
        if not message and isinstance(error, dict):
            message = error.get("message")
        return {"_error": f"Responses stream error: {message or 'unknown error'}"}

    return None


def read_responses_sse_lines(
    resp: StreamResponse,
    *,
    read_timeout: int,
    raise_if_interrupted: InterruptCheck,
) -> Iterator[dict[str, Any]]:
    """Yield normalized deltas until ``response.completed`` or EOF.

    There is no ``[DONE]`` on this protocol, so the terminal event is the only
    clean stop. Reading past it would consume the next response on a recycled
    connection.
    """
    current_event = ""
    state: dict[str, Any] = {}
    partial_text = ""
    empty_streak = 0

    while True:
        raise_if_interrupted()
        try:
            raw_line = resp.readline()
            raise_if_interrupted()
        except TimeoutError:
            raise_if_interrupted()
            yield _read_timeout_delta(read_timeout)
            return
        except OSError as exc:
            raise_if_interrupted()
            partial_event = stream_interruption_delta(exc, partial_text)
            if partial_event is not None:
                yield partial_event
                return
            raise

        if not raw_line:
            empty_streak += 1
            if empty_streak >= _MAX_CONSECUTIVE_EMPTY_READS:
                return
            continue
        empty_streak = 0

        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")

        if line.startswith("event: "):
            current_event = line[7:].strip()
            continue

        if not line.startswith("data: "):
            continue

        data_raw = line[6:].strip()
        if data_raw == "[DONE]":
            return

        parsed = parse_responses_sse_event(current_event, data_raw, state)
        if parsed is None:
            continue

        raise_if_interrupted()
        if "_error" in parsed:
            yield parsed
            return
        if "_usage" in parsed:
            yield {"_usage": parsed["_usage"]}
        if "choices" in parsed:
            choices = parsed["choices"]
            if choices:
                partial_text += choices[0].get("delta", {}).get("content") or ""
            # ``turn_api._usage_counts`` accumulates on every delta it sees, so
            # the usage half must not ride along a second time inside this one.
            yield {k: v for k, v in parsed.items() if k != "_usage"}
        if current_event == "response.completed":
            return


# ── request payload ──────────────────────────────────────────────


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for part in value:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return ""


def _convert_content(value: Any, *, assistant: bool) -> list[dict[str, Any]]:
    """Convert OpenAI message content parts to Responses input parts."""
    text_type = "output_text" if assistant else "input_text"
    if not isinstance(value, list):
        return [{"type": text_type, "text": _as_text(value)}]
    converted: list[dict[str, Any]] = []
    for part in value:
        if isinstance(part, str):
            converted.append({"type": text_type, "text": part})
            continue
        if not isinstance(part, dict):
            continue
        kind = part.get("type")
        if kind in ("text", "input_text", "output_text"):
            converted.append(
                {"type": text_type, "text": _as_text(part.get("text", ""))}
            )
        elif kind == "image_url":
            image = part.get("image_url")
            url = image.get("url") if isinstance(image, dict) else image
            if url:
                converted.append({"type": "input_image", "image_url": url})
        elif kind in ("input_text", "input_image", "input_file", "refusal"):
            converted.append(part)
    return converted


def _convert_messages(messages: list) -> tuple[list[dict[str, Any]], str]:
    """Split OpenAI-shaped messages into Responses input items + instructions."""
    instructions: list[str] = []
    items: list[dict[str, Any]] = []

    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")

        if role == "system":
            text = _as_text(content)
            if text:
                instructions.append(text)
            continue

        if role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.get("tool_call_id", ""),
                    "output": _as_text(content),
                }
            )
            continue

        text = _as_text(content)
        tool_calls = message.get("tool_calls") or []

        if role == "assistant" and tool_calls:
            if text:
                items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": _convert_content(content, assistant=True),
                    }
                )
            for call in tool_calls:
                if not isinstance(call, dict):
                    continue
                function = call.get("function") or {}
                arguments = function.get("arguments", "{}")
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments, ensure_ascii=False)
                items.append(
                    {
                        "type": "function_call",
                        "call_id": call.get("id", ""),
                        "name": function.get("name", ""),
                        "arguments": arguments,
                    }
                )
            continue

        if not text:
            continue
        items.append(
            {
                "type": "message",
                "role": role or "user",
                "content": _convert_content(content, assistant=role == "assistant"),
            }
        )

    return items, "\n\n".join(instructions)


def _convert_tools(tools_schema: list) -> list[dict[str, Any]]:
    converted = []
    for tool in tools_schema or []:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") or {}
        entry: dict[str, Any] = {
            "type": "function",
            "name": function.get("name", ""),
            "parameters": function.get("parameters")
            or {"type": "object", "properties": {}},
        }
        if function.get("description"):
            entry["description"] = function["description"]
        converted.append(entry)
    return converted


def _convert_tool_choice(tool_choice: Any) -> Any:
    if isinstance(tool_choice, dict):
        function = tool_choice.get("function") or {}
        name = function.get("name") or tool_choice.get("name") or ""
        return {"type": "function", "name": name}
    return tool_choice


def build_responses_payload(
    messages: list,
    model_alias: str,
    model_id: str,
    max_tokens: int,
    tools_schema: list | None,
    tool_choice: str,
    response_format: dict | None,
) -> dict[str, Any]:
    """Build a native Responses API request body.

    ``store`` is pinned False: the protocol's default persists the whole
    conversation provider-side, which a local agent has no reason to opt into.
    """
    from core import api_payloads

    items, instructions = _convert_messages(messages)

    payload: dict[str, Any] = {
        "model": model_id,
        "input": items,
        "max_output_tokens": max_tokens,
        "stream": True,
        "store": False,
    }
    if instructions:
        payload["instructions"] = instructions
    if tools_schema:
        payload["tools"] = _convert_tools(tools_schema)
        payload["tool_choice"] = _convert_tool_choice(tool_choice)
    if response_format:
        payload["text"] = {"format": dict(response_format)}
    reasoning_effort = api_payloads.resolve_reasoning_effort(model_alias)
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}
    return payload


# ── non-streaming response ───────────────────────────────────────


def parse_responses_nonstream(raw_body: bytes) -> tuple[str, str | None]:
    """Parse a non-streaming Responses body, returning (text, error)."""
    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        return "", f"Invalid JSON response: {exc}"

    output = data.get("output") if isinstance(data, dict) else None
    if not isinstance(output, list):
        return "", "Response missing output"

    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])

    text = "".join(parts).strip()
    if not text:
        return "", "Response output contained no text"
    return text, None


__all__ = [
    "RESPONSES_FORMAT",
    "build_responses_payload",
    "parse_responses_nonstream",
    "parse_responses_sse_event",
    "read_responses_sse_lines",
]
