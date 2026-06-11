"""Model stream consumption helpers for a single agent turn."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TurnApiResult:
    """Parsed output from one model stream attempt."""

    text: str = ""
    tool_calls: dict[int, dict[str, Any]] = field(default_factory=dict)
    reasoning: str = ""
    usage: dict[str, int] = field(
        default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0}
    )
    error: str | None = None
    retry_events: list[str] = field(default_factory=list)


def _usage_counts(delta: dict[str, Any]) -> tuple[int, int]:
    usage = delta.get("_usage")
    if not isinstance(usage, dict):
        return 0, 0
    prompt_tokens = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0) or 0
    completion_tokens = (
        usage.get("completion_tokens", 0) or usage.get("output_tokens", 0) or 0
    )
    return int(prompt_tokens), int(completion_tokens)


def consume_model_stream(
    deltas: Iterable[dict[str, Any]],
    *,
    ensure_tool_call_id: Callable[[dict[str, Any], int, int], str],
    iteration: int,
    on_retry: Callable[[str], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    on_reasoning: Callable[[str], None] | None = None,
    on_content: Callable[[str], None] | None = None,
    on_tool_delta: Callable[[], None] | None = None,
) -> TurnApiResult:
    """Consume provider stream deltas and return turn-level parsed state.

    Callbacks fire synchronously while iterating, so retry notices are surfaced
    before the provider retry sleep resumes.
    """
    result = TurnApiResult()

    for delta in deltas:
        if "_retry" in delta:
            retry_detail = str(delta["_retry"])
            result.retry_events.append(retry_detail)
            if on_retry:
                on_retry(retry_detail)
            continue

        if "_error" in delta:
            error_detail = str(delta["_error"])
            result.error = error_detail
            if on_error:
                on_error(error_detail)
            return result

        prompt_tokens, completion_tokens = _usage_counts(delta)
        if prompt_tokens or completion_tokens:
            result.usage["prompt_tokens"] += prompt_tokens
            result.usage["completion_tokens"] += completion_tokens

        choices = delta.get("choices", [])
        if not choices:
            continue

        choice = choices[0]
        data = choice.get("delta") or choice.get("message") or {}
        chunk = data.get("content") or ""

        reasoning_chunk = data.get("reasoning_content") or ""
        if reasoning_chunk:
            result.reasoning += reasoning_chunk
            if on_reasoning:
                on_reasoning(reasoning_chunk)

        if chunk:
            result.text += chunk
            if on_content:
                on_content(chunk)

        for tool_delta in data.get("tool_calls") or []:
            if on_tool_delta:
                on_tool_delta()
            idx = tool_delta.get("index", 0)
            if idx not in result.tool_calls:
                result.tool_calls[idx] = {
                    "id": ensure_tool_call_id(tool_delta, iteration, idx),
                    "name": "",
                    "args": "",
                }
            fn = tool_delta.get("function", {})
            result.tool_calls[idx]["name"] += fn.get("name") or ""
            result.tool_calls[idx]["args"] += fn.get("arguments") or ""

    return result


__all__ = ["TurnApiResult", "consume_model_stream"]
