"""Model stream consumption helpers for a single agent turn."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from core.stream_repetition import StreamRepetitionGuard, guard_enabled

# Appended to the answer, and printed, when the guard stops a repeating stream.
# It makes the truncation visible to the user and keeps the saved reply a
# non-empty text answer, so the turn ends normally instead of looking empty.
REPETITION_NOTICE = "\n\n[output stopped: the model was repeating itself]\n"


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
    #: Set when the repetition guard cut the stream short.
    repetition_stopped: bool = False


def _usage_counts(delta: dict[str, Any]) -> tuple[int, int]:
    usage = delta.get("_usage")
    if not isinstance(usage, dict):
        return 0, 0
    prompt_tokens = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0) or 0
    completion_tokens = (
        usage.get("completion_tokens", 0) or usage.get("output_tokens", 0) or 0
    )
    return int(prompt_tokens), int(completion_tokens)


def _merge_tool_name(existing: str, incoming: str) -> str:
    """Merge name fragments or a provider's repeated/cumulative snapshot."""
    if not existing or not incoming:
        return existing + incoming
    if incoming.startswith(existing):
        return incoming
    return existing + incoming


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
    # One guard per text channel: a model may loop in either the answer or the
    # reasoning side-channel, and a repeat in one must not be counted against
    # the other.  Disabled wholesale by PAWNLOGIC_STREAM_LOOP_GUARD=0.
    guarding = guard_enabled()
    content_guard = StreamRepetitionGuard() if guarding else None
    reasoning_guard = StreamRepetitionGuard() if guarding else None

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
            if reasoning_guard is not None and reasoning_guard.feed(reasoning_chunk):
                if on_reasoning:
                    on_reasoning(REPETITION_NOTICE)
                result.reasoning += REPETITION_NOTICE
                result.repetition_stopped = True
                break

        if chunk:
            result.text += chunk
            if on_content:
                on_content(chunk)
            if content_guard is not None and content_guard.feed(chunk):
                if on_content:
                    on_content(REPETITION_NOTICE)
                result.text += REPETITION_NOTICE
                result.repetition_stopped = True
                break

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
            result.tool_calls[idx]["name"] = _merge_tool_name(
                result.tool_calls[idx]["name"], fn.get("name") or ""
            )
            result.tool_calls[idx]["args"] += fn.get("arguments") or ""

    if result.repetition_stopped:
        # Stop the provider from streaming (and billing) the rest of the loop:
        # closing the generator raises GeneratorExit into stream_request, which
        # closes the socket. A plain iterator (tests) has no close(); ignore it.
        close = getattr(deltas, "close", None)
        if callable(close):
            close()

    return result


__all__ = ["TurnApiResult", "consume_model_stream"]
