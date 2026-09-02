"""Single-owner transcript buffer for the persistent terminal.

The persistent terminal used to keep its own :class:`deque` of output
chunks alongside the readline fallback's stdout sink, which led to two
parallel writers and a "who flushes first" race. ADR 0010 says the
persistent transcript must have a single owner that all writers
(``TerminalSink``, the stdout/stderr proxy, the legacy output buffer)
route through. That owner is :class:`TerminalTranscript`.

The class is intentionally framework-agnostic: it knows nothing about
Prompt Toolkit, async event loops, or the readline fallback. Producers
call :meth:`append` from any thread; readers call :meth:`snapshot` or
:meth:`drain` from the render thread. A bounded in-memory buffer caps
the cost of long sessions; a pluggable sink (callable or file-like)
forwards the rendered text to the host terminal so the user keeps
their own scrollback, mouse selection, and copy-paste.
"""

from __future__ import annotations

import contextlib
import threading
from collections import deque
from collections.abc import Callable
from typing import Protocol


class TextSink(Protocol):
    """A sink that can absorb the transcript's rendered text.

    Either a callable ``(text) -> None`` or any object with the file
    protocol (``write(text) -> int`` and ``flush() -> None``) qualifies.
    The constructor normalizes both shapes via :func:`normalize_sink`.
    """

    def write(self, text: str) -> int:  # pragma: no cover - protocol
        ...

    def flush(self) -> None:  # pragma: no cover - protocol
        ...


def normalize_sink(sink: Callable[[str], None] | TextSink | None) -> TextSink | None:
    """Coerce a callable into a :class:`TextSink`; pass-through otherwise.

    A ``None`` sink means "buffer only, do not push to the host
    terminal" — useful for tests and for the readline fallback that
    already owns its own stdout.
    """
    if sink is None:
        return None
    if callable(sink):
        return _CallableSink(sink)
    return sink


class _CallableSink:
    """Adapter that lets a plain ``(text) -> None`` callable satisfy TextSink."""

    __slots__ = ("_call",)

    def __init__(self, call: Callable[[str], None]) -> None:
        self._call = call

    def write(self, text: str) -> int:
        if text:
            self._call(text)
        return len(text)

    def flush(self) -> None:
        return None


class TerminalTranscript:
    """Thread-safe bounded transcript buffer with pluggable host sink.

    The buffer keeps at most :attr:`max_chars` of the most recent text
    in memory. When a writer pushes more than the cap allows, the
    oldest chunks are dropped first; the latest tail is always
    preserved.

    The host :attr:`sink` is consulted only when :meth:`flush` is
    explicitly called. Producers that want streaming output should
    call ``append`` followed by ``flush``; the persistent terminal
    does this on every redraw so the user sees incremental progress.

    The class does not raise on a misbehaving sink. A sink that throws
    is treated as a dropped chunk: the in-memory buffer still holds the
    text, and the next redraw can try again. This keeps the live
    composer responsive even when the host terminal misbehaves.
    """

    __slots__ = (
        "_char_count",
        "_chunks",
        "_lock",
        "_max_chars",
        "_recovery_draft",
        "_sink",
    )

    def __init__(
        self,
        *,
        sink: Callable[[str], None] | TextSink | None = None,
        max_chars: int = 2_000_000,
    ) -> None:
        if max_chars < 1:
            raise ValueError("max_chars must be positive")
        self._sink: TextSink | None = normalize_sink(sink)
        self._max_chars = max_chars
        self._chunks: deque[str] = deque()
        self._char_count = 0
        self._lock = threading.Lock()
        self._recovery_draft = False

    # ------------------------------------------------------------------
    # Buffer accessors
    # ------------------------------------------------------------------

    @property
    def max_chars(self) -> int:
        """The maximum number of characters kept in the in-memory buffer."""
        return self._max_chars

    def char_count(self) -> int:
        """How many characters are currently buffered."""
        with self._lock:
            return self._char_count

    def snapshot(self) -> str:
        """Return a stable copy of the buffered text without clearing it."""
        with self._lock:
            return "".join(self._chunks)

    def drain(self) -> str:
        """Return and clear the buffered text."""
        with self._lock:
            text = "".join(self._chunks)
            self._chunks.clear()
            self._char_count = 0
            return text

    def replace(self, text: str) -> None:
        """Atomically replace the buffered text, honoring the cap.

        Used by carriage-return / backspace rewrites in the live
        output pane. The replacement is trimmed to the latest
        :attr:`max_chars` characters so a long rebuild cannot blow
        the cap.
        """
        with self._lock:
            self._chunks.clear()
            self._char_count = 0
            if not text:
                return
            if len(text) > self._max_chars:
                text = text[-self._max_chars :]
            self._chunks.append(text)
            self._char_count = len(text)

    # ------------------------------------------------------------------
    # Producer API
    # ------------------------------------------------------------------

    def append(self, text: str) -> None:
        """Add text to the buffer, trimming the oldest chunks as needed.

        Safe to call from any thread. Empty input is a no-op.
        """
        if not text:
            return
        with self._lock:
            self._chunks.append(text)
            self._char_count += len(text)
            while self._char_count > self._max_chars and self._chunks:
                removed = self._chunks.popleft()
                self._char_count -= len(removed)
            if self._char_count < 0:
                self._char_count = 0

    def flush(self) -> None:
        """Push the buffered text to the configured :attr:`sink`.

        The buffered text is preserved on success: flushing is for
        streaming, not for consuming. Tests and the readline fallback
        that want a one-shot read should use :meth:`drain`.

        A misbehaving sink is swallowed: see the class docstring.
        """
        with self._lock:
            if not self._chunks:
                return
            payload = "".join(self._chunks)
        if not payload:
            return
        sink = self._sink
        if sink is None:
            return
        try:
            sink.write(payload)
        except Exception:
            return
        with contextlib.suppress(Exception):
            sink.flush()

    # ------------------------------------------------------------------
    # Recovery-draft marker
    # ------------------------------------------------------------------

    def mark_recovery_draft(self) -> None:
        """Mark the next composable submission as a one-shot replacement."""
        with self._lock:
            self._recovery_draft = True

    def consume_recovery_draft(self) -> bool:
        """Read and clear the recovery-draft marker."""
        with self._lock:
            pending = self._recovery_draft
            self._recovery_draft = False
            return pending

    def recovery_draft_pending(self) -> bool:
        """Whether a recovery-draft marker is currently set."""
        with self._lock:
            return self._recovery_draft

    # ------------------------------------------------------------------
    # Sink management
    # ------------------------------------------------------------------

    def set_sink(self, sink: Callable[[str], None] | TextSink | None) -> None:
        """Install or replace the host sink."""
        self._sink = normalize_sink(sink)


__all__ = ["TerminalTranscript", "TextSink", "normalize_sink"]
