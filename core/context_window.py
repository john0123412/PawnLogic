"""Context window sizing and message cleanup helpers.

The single compaction path lives in ``core.context_manager.ContextManager``:
it bounds the per-request provider view without mutating canonical history.
There is deliberately no second, history-rewriting compaction path here —
the previous ``_trim_and_compact_context`` (tool-output placeholders plus
100-character truncation merged into canonical history) was dead code that
silently disagreed with the live path and destroyed exact values (addresses,
offsets) the summary path is required to preserve.
"""

from __future__ import annotations

from core.message_history import repair_dangling_tool_calls


def _ctx_chars(msgs: list) -> int:
    # Reasoning content must count toward the real context budget.
    return sum(
        len(str(m.get("content") or "")) + len(str(m.get("reasoning_content") or ""))
        for m in msgs
    )


def _drop_dangling_tool_call_messages(msgs: list) -> list:
    """Return a copy without assistant tool calls that lack matching tool output."""
    return repair_dangling_tool_calls(msgs)
