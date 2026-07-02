"""Internal provider stream readers preserving PawnLogic delta dicts."""

from __future__ import annotations

from collections.abc import Callable, Iterator
import json
import re
from typing import Any, Protocol


class StreamResponse(Protocol):
    def readline(self) -> bytes: ...


InterruptCheck = Callable[[], None]


def parse_sse_delta(raw: str) -> dict[str, Any] | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    cleaned = re.sub(r",\s*([}\]])", r"\1", raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    def _escape_inner(s: str) -> str:
        result = []
        in_str = False
        escaped = False
        for ch in s:
            if escaped:
                result.append(ch)
                escaped = False
                continue
            if ch == "\\":
                result.append(ch)
                escaped = True
                continue
            if ch == '"':
                in_str = not in_str
                result.append(ch)
                continue
            if in_str and ch == "\n":
                result.append("\\n")
                continue
            if in_str and ch == "\r":
                result.append("\\r")
                continue
            if in_str and ch == "\t":
                result.append("\\t")
                continue
            result.append(ch)
        return "".join(result)

    cleaned2 = _escape_inner(cleaned)
    try:
        return json.loads(cleaned2)
    except json.JSONDecodeError:
        pass

    result: dict[str, Any] = {"choices": [{"delta": {}, "finish_reason": None}]}
    delta = result["choices"][0]["delta"]
    m_content = re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', cleaned2)
    if m_content:
        try:
            delta["content"] = json.loads('"' + m_content.group(1) + '"')
        except Exception:
            delta["content"] = m_content.group(1)
    m_finish = re.search(r'"finish_reason"\s*:\s*"?(\w+)"?', raw)
    if m_finish:
        result["choices"][0]["finish_reason"] = m_finish.group(1)
    return result if delta else None


def stream_interruption_delta(
    error: OSError,
    partial_text: str,
) -> dict[str, object] | None:
    if not partial_text:
        return None
    return {
        "_partial_end": True,
        "_error": f"Stream interrupted after partial content: {error}",
    }


def parse_anthropic_sse_event(
    event_type: str,
    data_raw: str,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    """Parse one Anthropic SSE event into the existing unified delta dict."""
    try:
        data = json.loads(data_raw)
    except json.JSONDecodeError:
        return None

    etype = data.get("type", event_type)

    if etype == "message_start":
        usage = data.get("message", {}).get("usage", {})
        if usage:
            return {"_usage": usage}
        return None

    if etype == "content_block_start":
        block = data.get("content_block", {})
        idx = data.get("index", 0)
        if block.get("type") == "tool_use":
            state.setdefault("tool_blocks", {})[idx] = {
                "id": block.get("id", ""),
                "name": block.get("name", ""),
                "args": "",
            }
        return None

    if etype == "content_block_delta":
        delta = data.get("delta", {})
        idx = data.get("index", 0)
        delta_type = delta.get("type", "")

        if delta_type == "text_delta":
            return {
                "choices": [{
                    "delta": {"content": delta.get("text", "")},
                    "finish_reason": None,
                }],
            }

        if delta_type == "input_json_delta":
            partial = delta.get("partial_json", "")
            tb = state.get("tool_blocks", {}).get(idx, {})
            tb["args"] = tb.get("args", "") + partial
            return {
                "choices": [{
                    "delta": {
                        "tool_calls": [{
                            "index": idx,
                            "id": tb.get("id", ""),
                            "function": {
                                "name": tb.get("name", ""),
                                "arguments": partial,
                            },
                        }],
                    },
                    "finish_reason": None,
                }],
            }
        return None

    if etype == "content_block_stop":
        return None

    if etype == "message_delta":
        usage = data.get("usage", {})
        result: dict[str, Any] = {}
        if usage:
            result["_usage"] = usage
        stop = data.get("delta", {}).get("stop_reason")
        if stop:
            result["choices"] = [{"delta": {}, "finish_reason": stop}]
        return result if result else None

    if etype == "message_stop":
        return None

    return None


def _read_timeout_delta(read_timeout: int) -> dict[str, str]:
    return {
        "_error": (
            f"Read timeout ({read_timeout}s): provider stopped sending stream data. "
            "Check network, proxy settings, or switch provider."
        )
    }


def read_anthropic_sse_lines(
    resp: StreamResponse,
    *,
    read_timeout: int,
    raise_if_interrupted: InterruptCheck,
) -> Iterator[dict[str, Any]]:
    current_event = ""
    state: dict[str, Any] = {"tool_blocks": {}}
    partial_text = ""
    while True:
        raise_if_interrupted()
        try:
            raw_line = resp.readline()
            raise_if_interrupted()
        except TimeoutError:
            raise_if_interrupted()
            yield _read_timeout_delta(read_timeout)
            return
        except OSError as e:
            raise_if_interrupted()
            partial_event = stream_interruption_delta(e, partial_text)
            if partial_event is not None:
                yield partial_event
                return
            raise

        if not raw_line:
            return

        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")

        if line.startswith("event: "):
            current_event = line[7:].strip()
            continue

        if not line.startswith("data: "):
            continue

        data_raw = line[6:].strip()
        parsed = parse_anthropic_sse_event(current_event, data_raw, state)
        if parsed is not None:
            raise_if_interrupted()
            if "_usage" in parsed:
                yield {"_usage": parsed["_usage"]}
            if "choices" in parsed:
                choices = parsed["choices"]
                if choices:
                    partial_text += choices[0].get("delta", {}).get("content") or ""
                yield parsed


def read_openai_sse_lines(
    resp: StreamResponse,
    *,
    read_timeout: int,
    raise_if_interrupted: InterruptCheck,
) -> Iterator[dict[str, Any]]:
    partial_text = ""
    while True:
        raise_if_interrupted()
        try:
            raw_line = resp.readline()
            raise_if_interrupted()
        except TimeoutError:
            raise_if_interrupted()
            yield _read_timeout_delta(read_timeout)
            return
        except OSError as e:
            raise_if_interrupted()
            partial_event = stream_interruption_delta(e, partial_text)
            if partial_event is not None:
                yield partial_event
                return
            raise

        if not raw_line:
            return

        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line.startswith("data: "):
            continue

        data_raw = line[6:].strip()
        if data_raw == "[DONE]":
            return

        parsed = parse_sse_delta(data_raw)
        if parsed is not None:
            raise_if_interrupted()
            choices = parsed.get("choices", [])
            if choices:
                partial_text += choices[0].get("delta", {}).get("content") or ""
            usage = parsed.get("usage")
            if usage and isinstance(usage, dict):
                yield {"_usage": usage}
            yield parsed


def read_sse_lines(
    resp: StreamResponse,
    api_format: str,
    *,
    read_timeout: int,
    raise_if_interrupted: InterruptCheck,
) -> Iterator[dict[str, Any]]:
    if api_format == "anthropic":
        yield from read_anthropic_sse_lines(
            resp,
            read_timeout=read_timeout,
            raise_if_interrupted=raise_if_interrupted,
        )
    else:
        yield from read_openai_sse_lines(
            resp,
            read_timeout=read_timeout,
            raise_if_interrupted=raise_if_interrupted,
        )


__all__ = [
    "parse_anthropic_sse_event",
    "parse_sse_delta",
    "read_anthropic_sse_lines",
    "read_openai_sse_lines",
    "read_sse_lines",
    "stream_interruption_delta",
]
