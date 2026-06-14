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

from collections.abc import Callable, MutableSequence
from dataclasses import dataclass, field
import hashlib

from config.security import smart_truncate
from core.logger import logger
from utils.ansi import GRAY, YELLOW

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


# ── Phase 2: per-turn stateful tool result processing ────────────────

# Tool names whose output participates in repeated-output loop detection.
_CODE_OUTPUT_TOOLS = ("run_shell", "run_code", "write_file", "patch_file")
# Tool names that count toward directory-search auto-intuition.
_DIRECTORY_TOOLS = ("list_dir", "find_files")

DIR_THRESHOLD = 3            # Directory searches before intuition kicks in.
REPEAT_ERROR_THRESHOLD = 3   # Identical shell errors before anti-loop fires.
REPEAT_CODE_THRESHOLD = 3    # Identical outputs before anti-code-loop fires.
_CMD_ERROR_HISTORY = 20      # Retained (cmd, error) pairs.
_CODE_OUTPUT_HISTORY = 10    # Retained output signatures.


def build_anti_loop_message(count: int) -> str:
    """Bypass-hint injection for repeated identical shell command errors."""
    return (
        "[System] The current path appears blocked: detected "
        f"{count} consecutive identical command errors. "
        "Re-evaluate the exploit logic and consider these bypass directions:\n"
        "  1. Symlink bypass (ln -s)\n"
        "  2. open_basedir bypass (php -d open_basedir=/)\n"
        "  3. Path encoding bypass (../ ./ ..%2f)\n"
        "  4. Switch tool or attack vector\n"
        "  5. Ask the user to confirm target environment details"
    )


def build_anti_code_loop_message(count: int) -> str:
    """Re-evaluation injection for repeated near-identical tool outputs."""
    return (
        f"[System] Detected {count} consecutive nearly identical tool outputs. "
        "The current path may be looping; stop and re-evaluate immediately:\n"
        "  1. Are you repeating commands already known to fail?\n"
        "  2. Do you need a different attack vector or tool?\n"
        "  3. Should you ask the user to confirm the target environment?\n"
        "Explain the new approach in <plan> before continuing."
    )


@dataclass(slots=True)
class ToolResultNotice:
    """A terminal message the caller should print, gated by display level.

    ``level`` is one of ``"always"``, ``"user"``, or ``"debug"``. The caller
    decides whether the current display mode permits the print; the processor
    never prints itself.
    """

    level: str
    color: str
    message: str


@dataclass(slots=True)
class ToolAuditEvent:
    """Audit record fields for one tool result.

    Returned by the processor instead of writing the audit log directly so the
    caller owns that side effect.
    """

    tool_name: str
    args_summary: str
    result_len: int
    elapsed_ms: int
    iteration: int
    success: bool


@dataclass(slots=True)
class ProcessedToolResult:
    """Outcome of processing one tool result.

    The caller appends ``content`` as the tool message, prints ``notices``
    (respecting their level), writes ``audit_event``, then appends each entry of
    ``injections`` as a follow-up user message.
    """

    content: str
    injections: list[str] = field(default_factory=list)
    notices: list[ToolResultNotice] = field(default_factory=list)
    audit_event: ToolAuditEvent | None = None


@dataclass(slots=True)
class AntiLoopInjection:
    """Top-of-iteration anti-loop injection consuming the repeat-error count."""

    injection: str
    notices: list[ToolResultNotice] = field(default_factory=list)


@dataclass(slots=True)
class ToolResultProcessor:
    """Per-turn stateful processor for tool results.

    Owns the loop-detection counters that previously lived as locals inside
    ``run_turn``. It performs no side effects of its own: it never prints,
    appends to message history, or writes the audit log. Instead it returns
    decisions (content, injections, notices, audit_event) for the caller to
    apply. Internal loguru diagnostics are emitted for parity with the original
    inline behaviour.

    Cross-iteration contract: ``process`` accumulates ``_repeat_error_count``
    from shell failures; the next iteration's ``maybe_anti_loop_injection``
    consumes and resets it.
    """

    auto_intuitive_search: Callable[[str], str]
    session_label: str = ""
    verbose_tools: frozenset[str] = DEFAULT_VERBOSE_TOOLS
    dir_threshold: int = DIR_THRESHOLD
    repeat_error_threshold: int = REPEAT_ERROR_THRESHOLD
    repeat_code_threshold: int = REPEAT_CODE_THRESHOLD

    # Per-turn mutable state (migrated from run_turn locals).
    _dir_search_count: int = 0
    _recent_cmd_errors: list[tuple[str, str]] = field(default_factory=list)
    _repeat_error_count: int = 0
    _recent_code_outputs: list[str] = field(default_factory=list)
    _repeat_code_count: int = 0

    def maybe_anti_loop_injection(self, iteration: int) -> AntiLoopInjection | None:
        """Return an anti-loop injection when repeated shell errors pile up.

        Consumes and resets the repeat-error count. Returns ``None`` when below
        threshold.
        """
        if self._repeat_error_count < self.repeat_error_threshold:
            return None
        count = self._repeat_error_count
        logger.warning(
            "Anti-Loop: repeated error detected | session={} iteration={} count={}",
            self.session_label, iteration, count,
        )
        self._repeat_error_count = 0  # Reset to avoid repeated injection.
        return AntiLoopInjection(
            injection=build_anti_loop_message(count),
            notices=[ToolResultNotice(
                "debug", YELLOW,
                f"  🔁 [Anti-Loop] Detected {count} repeated errors; injected bypass hint",
            )],
        )

    def reset_directory_counter(self) -> None:
        """Reset the directory-search counter (non-directory tool was used)."""
        self._dir_search_count = 0

    def process(
        self,
        *,
        result: str,
        tool_name: str,
        fn_args: dict,
        args_preview: str,
        audit_ok: bool,
        elapsed_ms: int,
        failure_warning: str,
        iteration: int,
        user_mode: bool,
        max_chars: int,
    ) -> ProcessedToolResult:
        """Process one executed (non-phase) tool result.

        Order mirrors the original inline logic exactly: append failure warning,
        snapshot the pre-truncation length for audit, truncate, apply directory
        auto-intuition, then update shell-error and code-output loop counters.
        """
        notices: list[ToolResultNotice] = []
        injections: list[str] = []
        content = result

        # 1. Append pre-flight audit warnings to the tool result.
        if failure_warning:
            content = content + "\n\n" + failure_warning

        # 2. Snapshot audit fields before truncation (parity with original).
        audit_event = ToolAuditEvent(
            tool_name=tool_name,
            args_summary=args_preview,
            result_len=len(content),
            elapsed_ms=elapsed_ms,
            iteration=iteration,
            success=audit_ok,
        )

        # 3. Truncate for context.
        content = truncate_tool_output(
            content,
            tool_name=tool_name,
            user_mode=user_mode,
            verbose_tools=self.verbose_tools,
            max_chars=max_chars,
        )

        # 4. Directory-search count and auto-intuition retrieval.
        if tool_name in _DIRECTORY_TOOLS:
            self._dir_search_count += 1
            if self._dir_search_count >= self.dir_threshold:
                search_query = (
                    fn_args.get("pattern") or fn_args.get("path") or ""
                ).strip().strip("*./")
                auto_result = ""
                if search_query:
                    notices.append(ToolResultNotice(
                        "always", GRAY,
                        f"  🧠 [Auto-Intuition] Directory search count {self._dir_search_count}; "
                        f"searching history for: '{search_query}'",
                    ))
                    auto_result = self.auto_intuitive_search(search_query)
                content = content + build_directory_intuition_hint(
                    self._dir_search_count, auto_result
                )
        else:
            self._dir_search_count = 0

        # 5. Repeated shell-error tracking.
        if tool_name == "run_shell" and not audit_ok:
            cmd_key = fn_args.get("command", "") or args_preview[:80]
            err_sig = detect_shell_error_signal(content)
            if err_sig:
                pair = (cmd_key[:60], err_sig)
                if self._recent_cmd_errors and self._recent_cmd_errors[-1] == pair:
                    self._repeat_error_count += 1
                else:
                    self._repeat_error_count = 1
                self._recent_cmd_errors.append(pair)
                if len(self._recent_cmd_errors) > _CMD_ERROR_HISTORY:
                    self._recent_cmd_errors = self._recent_cmd_errors[-_CMD_ERROR_HISTORY:]

        # 6. Repeated identical code-output detection to prevent loops.
        if tool_name in _CODE_OUTPUT_TOOLS:
            result_hash = output_signature(content)
            if self._recent_code_outputs and self._recent_code_outputs[-1] == result_hash:
                self._repeat_code_count += 1
            else:
                self._repeat_code_count = 1
            self._recent_code_outputs.append(result_hash)
            if len(self._recent_code_outputs) > _CODE_OUTPUT_HISTORY:
                self._recent_code_outputs = self._recent_code_outputs[-_CODE_OUTPUT_HISTORY:]

            if self._repeat_code_count >= self.repeat_code_threshold:
                count = self._repeat_code_count
                injections.append(build_anti_code_loop_message(count))
                notices.append(ToolResultNotice(
                    "always", YELLOW,
                    f"  🔁 [Anti-Code-Loop] {count} identical outputs detected; injected re-evaluation hint",
                ))
                logger.warning(
                    "Anti-Code-Loop: repeated output | "
                    "session={} iteration={} count={} tool={}",
                    self.session_label, iteration, count, tool_name,
                )
                self._repeat_code_count = 0

        return ProcessedToolResult(
            content=content,
            injections=injections,
            notices=notices,
            audit_event=audit_event,
        )


__all__ = [
    "DEFAULT_VERBOSE_TOOLS",
    "DIR_THRESHOLD",
    "REDUNDANT_PATTERNS",
    "REPEAT_CODE_THRESHOLD",
    "REPEAT_ERROR_THRESHOLD",
    "SHELL_ERROR_SIGNALS",
    "AntiLoopInjection",
    "ProcessedToolResult",
    "ToolAuditEvent",
    "ToolResultNotice",
    "ToolResultProcessor",
    "build_anti_code_loop_message",
    "build_anti_loop_message",
    "build_directory_intuition_hint",
    "compact_redundant_tool_error_messages",
    "detect_shell_error_signal",
    "output_signature",
    "truncate_tool_output",
]
