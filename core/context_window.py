"""Context window sizing, compaction, and message cleanup helpers."""

from __future__ import annotations

from config import DYNAMIC_CONFIG
from core.state import runtime_config
from core.message_history import repair_dangling_tool_calls


def _dynamic_config() -> dict:
    try:
        return runtime_config()
    except Exception:
        return DYNAMIC_CONFIG


def _ctx_chars(msgs: list) -> int:
    # Reasoning content must count toward the real context budget.
    return sum(
        len(str(m.get("content") or "")) + len(str(m.get("reasoning_content") or ""))
        for m in msgs
    )


def _trim_and_compact_context(msgs: list) -> int:
    """
    Context compaction (Tool Clearing).
    When the token budget overflows, keep the system prompt and latest 10
    messages. Older messages are not dropped directly:
      - role=tool content is replaced by a placeholder
      - role=user/assistant content is truncated to the first 100 characters
    Then the compacted content is merged into one assistant summary inserted
    after the system message.
    """
    cfg = _dynamic_config()
    if _ctx_chars(msgs) <= cfg["ctx_max_chars"]:
        return 0

    keep_tail = 10
    if len(msgs) <= keep_tail + 1:
        return 0

    cutoff = len(msgs) - keep_tail
    old_msgs = msgs[1:cutoff]

    compacted_lines: list[str] = []
    for m in old_msgs:
        role = m.get("role", "unknown")
        content = m.get("content") or ""
        if role == "tool":
            compacted_lines.append(
                f"[tool/{m.get('tool_call_id', '')}]: "
                "(Tool output compacted to save context)"
            )
        elif role in ("user", "assistant"):
            snippet = str(content)[:100]
            ellipsis = "…" if len(str(content)) > 100 else ""
            compacted_lines.append(f"[{role}]: {snippet}{ellipsis}")
        if role == "assistant" and m.get("tool_calls"):
            names = [
                tc.get("function", {}).get("name", "?")
                for tc in (m.get("tool_calls") or [])
            ]
            compacted_lines.append(f"  └─ tool_calls: {', '.join(names)}")

    summary_content = "📝 [Context Compacted]:\n" + "\n".join(compacted_lines)
    summary_msg = {
        "role": "assistant",
        "content": summary_content,
        "_pinned": True,
    }

    del msgs[1:cutoff]
    msgs.insert(1, summary_msg)

    return len(old_msgs)


def _drop_dangling_tool_call_messages(msgs: list) -> list:
    """Return a copy without assistant tool calls that lack matching tool output."""
    return repair_dangling_tool_calls(msgs)
