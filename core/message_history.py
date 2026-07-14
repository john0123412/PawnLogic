"""Message-history validation independent from turn and persistence adapters."""

from __future__ import annotations

from typing import Any


def repair_dangling_tool_calls(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop assistant tool-call groups missing any matching tool result."""
    cleaned: list[dict[str, Any]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        calls = message.get("tool_calls") or []
        if message.get("role") != "assistant" or not calls:
            cleaned.append(message)
            index += 1
            continue
        expected = [
            call.get("id")
            for call in calls
            if isinstance(call, dict) and call.get("id")
        ]
        cursor = index + 1
        actual: list[str] = []
        while cursor < len(messages) and messages[cursor].get("role") == "tool":
            tool_call_id = messages[cursor].get("tool_call_id")
            if isinstance(tool_call_id, str) and tool_call_id:
                actual.append(tool_call_id)
            cursor += 1
        if expected and all(call_id in actual for call_id in expected):
            cleaned.append(message)
            cleaned.extend(messages[index + 1 : cursor])
        index = cursor
    return cleaned


__all__ = ["repair_dangling_tool_calls"]
