"""Pure helpers for per-turn tool result processing.

Phase 1 of the ToolResultProcessor extraction: stateless transforms lifted
out of ``AgentSession.run_turn`` so they can be unit tested in isolation. No
per-turn state (loop counters) lives here yet; that arrives in Phase 2 with a
stateful ``ToolResultProcessor``.

Side-effect free by design: these functions do not print, append to message
history, or write logs. ``compact_redundant_tool_error_messages`` mutates the
message list it is given in place, but performs no other side effect.
"""

from __future__ import annotations

from collections.abc import MutableSequence
import hashlib

from config.security import smart_truncate

# Tools whose output is shown in full (head/tail trimmed) rather than hard
# truncated to ``tool_max_chars``. Mirrors the inline set previously defined in
# ``run_turn``.
DEFAULT_VERBOSE_TOOLS: frozenset[str] = frozenset(
    {
        "read_file",
        "read_file_lines",
        "run_shell",
        "run_code",
        "pwn_debug",
        "pwn_rop",
        "pwn_disasm",
        "pwn_cyclic",
        "pwn_libc",
        "inspect_binary",
        "web_search",
        "fetch_url",
        "find_refs",
    }
)

# Ordered shell-error signals used to label a failed run_shell result. The order
# is significant: the first match wins.
SHELL_ERROR_SIGNALS: tuple[str, ...] = (
    "ERROR:",
    "Permission denied",
    "No such file",
    "command not found",
    "Segmentation fault",
    "timeout",
)

# Short, repetitive tool errors that are collapsed in history to keep context
# compact. ``REDUNDANT_PATTERNS[0]`` is also referenced in the placeholder text,
# matching the original inline behaviour.
REDUNDANT_PATTERNS: tuple[str, ...] = (
    "No such file or directory",
    "Permission denied",
    "command not found",
    "is a directory",
    "Not a directory",
)

_REDUNDANT_MAX_LEN = 300  # Only short errors are eligible for compaction.
_REDUNDANT_THRESHOLD = 3  # Compact occurrences beyond this count.


def truncate_tool_output(
    result: str,
    *,
    tool_name: str,
    user_mode: bool,
    verbose_tools: frozenset[str] = DEFAULT_VERBOSE_TOOLS,
    max_chars: int,
) -> str:
    """Trim a tool result for context.

    Verbose tools (and user mode) get head/tail trimming via ``smart_truncate``;
    everything else is hard truncated to ``max_chars`` only when it exceeds it.
    """
    if user_mode or tool_name in verbose_tools:
        return smart_truncate(result, head=30, tail=30)
    if len(result) > max_chars:
        return (
            result[: max_chars // 2]
            + f"\n...[truncated to {max_chars} chars]...\n"
            + result[-max_chars // 4 :]
        )
    return result


def output_signature(result: object) -> str:
    """Return a stable short signature of a tool output for loop detection."""
    return hashlib.md5(str(result)[:500].encode("utf-8", errors="ignore")).hexdigest()[
        :12
    ]


def detect_shell_error_signal(result: object) -> str:
    """Return the first matching shell-error signal in ``result`` or ``""``."""
    text = str(result)
    for signal in SHELL_ERROR_SIGNALS:
        if signal in text:
            return signal
    return ""


def build_directory_intuition_hint(count: int, auto_result: str = "") -> str:
    """Build the suffix appended after repeated directory searches.

    Returns the system hint followed by any auto-intuition search result, ready
    to be concatenated onto the tool output.
    """
    hint = (
        f"\n[System hint — directory search has run {count} consecutive times] "
        "Switch strategy: use /chat find <keyword> to search history, "
        "or tell the user the file path is unknown."
    )
    return hint + auto_result


def compact_redundant_tool_error_messages(
    messages: MutableSequence[dict],
) -> int:
    """Collapse repeated short tool errors in ``messages`` in place.

    Scans tool messages (skipping the system message), counts occurrences of
    each redundant pattern, and rewrites short repeats beyond the threshold into
    a one-line placeholder. Returns the number of messages compacted.
    """
    seen_errors: dict[str, int] = {}
    to_compact: list[int] = []
    for index, message in enumerate(messages[1:], 1):  # skip system
        if message.get("role") != "tool":
            continue
        content = message.get("content") or ""
        for pattern in REDUNDANT_PATTERNS:
            if pattern in content and len(content) < _REDUNDANT_MAX_LEN:
                seen_errors[pattern] = seen_errors.get(pattern, 0) + 1
                if seen_errors[pattern] > _REDUNDANT_THRESHOLD:
                    to_compact.append(index)
                break

    compacted = 0
    for index in reversed(to_compact):
        old_content = messages[index].get("content") or ""
        # Only compact short errors; preserve long output.
        if len(old_content) < _REDUNDANT_MAX_LEN:
            messages[index]["content"] = (
                f"(compacted: {old_content[:60]}...) — similar errors have appeared "
                f"{seen_errors.get(REDUNDANT_PATTERNS[0], '?')} times"
            )
            compacted += 1
    return compacted


__all__ = [
    "DEFAULT_VERBOSE_TOOLS",
    "REDUNDANT_PATTERNS",
    "SHELL_ERROR_SIGNALS",
    "build_directory_intuition_hint",
    "compact_redundant_tool_error_messages",
    "detect_shell_error_signal",
    "output_signature",
    "truncate_tool_output",
]
