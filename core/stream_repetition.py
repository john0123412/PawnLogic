"""Detect a model that has started repeating itself inside one stream.

A weak model asked for a final answer sometimes stops making progress and
emits the same sentence again and again until it reaches ``max_tokens`` -- in
the incident that motivated this, one reply was 37 KB, 369 lines of which only
180 were distinct, the sentence ``I'll write a comprehensive analysis of the
source ...`` repeated 52 times, and it filled the whole 8192-token output
budget.  Nothing caught it: the existing anti-loop logic
(``core/tool_result.py``) counts repeated *tool* iterations, not text within a
single streamed response, so the whole wall was billed and printed.

``StreamRepetitionGuard`` watches the text as it streams and reports the moment
a substantial line has recurred too many times in a short window.  The caller
(``core.turn_api.consume_model_stream``) then stops reading the stream, so only
a few repeats leak to the terminal instead of thousands of tokens, and the
useful prefix is kept.

It is deliberately conservative, because cutting off a real answer is worse
than a little waste:

* only lines of at least ``MIN_LINE_CHARS`` visible characters count, so blank
  lines, ``---`` rules, ``| --- |`` table separators, short list bullets and
  brace-only code lines never trigger it;
* a line must recur ``MAX_LINE_REPEATS`` times within the last ``WINDOW_LINES``
  completed lines -- a table with one separator row, or a refrain used two or
  three times, stays under the bar;
* or, once the window holds at least ``MIN_WINDOW_FILL`` substantial lines, at
  most ``MAX_DUP_RATIO`` of them may be distinct -- this catches a loop that
  rotates among several filler sentences (the real incident cycled through a
  dozen, so no single line reached the count quickly), while ordinary prose and
  a table of distinct rows stay near fully distinct;
* a single line with no newline is only cut once it passes ``MAX_LINE_CHARS``
  (a pathological token-level loop), far above any real sentence or code line.

Thresholds come from the environment so a model that legitimately repeats can
be accommodated without a code change; ``PAWNLOGIC_STREAM_LOOP_GUARD=0`` turns
the guard off entirely.
"""

from __future__ import annotations

import os
from collections import Counter, deque

# A line shorter than this (after stripping) never counts toward a loop.
MIN_LINE_CHARS = 24
# How many recent completed lines the window holds.
WINDOW_LINES = 60
# Occurrences of one normalized line within the window that mean a loop.
MAX_LINE_REPEATS = 6
# Once the window holds this many substantial lines, the uniqueness ratio is
# evaluated as a second signal.
MIN_WINDOW_FILL = 40
# The largest fraction of distinct lines a full window may have; below it the
# window is too repetitive to be genuine (0.6 = at least 40% are duplicates).
MAX_DUP_RATIO = 0.6
# A single newline-free run longer than this is a token-level loop.
MAX_LINE_CHARS = 20_000


def _env_int(name: str, default: int) -> int:
    """Return a positive int from the environment, or ``default``."""
    raw = os.environ.get(name, "")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def guard_enabled() -> bool:
    """Return whether the stream repetition guard is active (default yes)."""
    return os.environ.get("PAWNLOGIC_STREAM_LOOP_GUARD", "1").strip() not in {"0", "false", "False"}


class StreamRepetitionGuard:
    """Streaming detector for a model repeating a line until ``max_tokens``.

    Feed it text chunks as they arrive; ``feed`` returns ``True`` the first
    time a loop is detected, and once tripped it stays tripped.  Only the
    current (possibly partial) trailing line is held between calls, so cost is
    O(chunk length) and memory is bounded by the window.
    """

    def __init__(
        self,
        *,
        min_line_chars: int = MIN_LINE_CHARS,
        window_lines: int = WINDOW_LINES,
        max_line_repeats: int = MAX_LINE_REPEATS,
        min_window_fill: int = MIN_WINDOW_FILL,
        max_dup_ratio: float = MAX_DUP_RATIO,
        max_line_chars: int = MAX_LINE_CHARS,
    ) -> None:
        self._min_line_chars = min_line_chars
        self._max_line_repeats = max_line_repeats
        self._min_window_fill = min_window_fill
        self._max_dup_ratio = max_dup_ratio
        self._max_line_chars = max_line_chars
        self._recent: deque[str] = deque(maxlen=window_lines)
        self._counts: Counter[str] = Counter()
        self._pending = ""  # the trailing line not yet terminated by "\n"
        self._tripped = False

    @property
    def tripped(self) -> bool:
        return self._tripped

    def feed(self, chunk: str) -> bool:
        """Accumulate ``chunk``; return ``True`` the first time a loop is seen."""
        if self._tripped or not chunk:
            return False
        self._pending += chunk
        if "\n" not in chunk:
            # No line completed; only the single-run safety net can fire.
            if len(self._pending) > self._max_line_chars:
                self._tripped = True
            return self._tripped
        *completed, self._pending = self._pending.split("\n")
        for line in completed:
            if self._add_line(line):
                self._tripped = True
                return True
        if len(self._pending) > self._max_line_chars:
            self._tripped = True
        return self._tripped

    def _add_line(self, line: str) -> bool:
        """Record one completed line; return whether it closes a loop."""
        key = " ".join(line.split())  # collapse whitespace; drop leading/trailing
        if len(key) < self._min_line_chars:
            return False
        if len(self._recent) == self._recent.maxlen:
            evicted = self._recent[0]
            remaining = self._counts[evicted] - 1
            if remaining > 0:
                self._counts[evicted] = remaining
            else:
                del self._counts[evicted]
        self._recent.append(key)
        self._counts[key] += 1
        if self._counts[key] >= self._max_line_repeats:
            return True
        total = len(self._recent)
        return total >= self._min_window_fill and len(self._counts) <= total * self._max_dup_ratio


__all__ = [
    "MAX_DUP_RATIO",
    "MAX_LINE_CHARS",
    "MAX_LINE_REPEATS",
    "MIN_LINE_CHARS",
    "MIN_WINDOW_FILL",
    "WINDOW_LINES",
    "StreamRepetitionGuard",
    "guard_enabled",
]
