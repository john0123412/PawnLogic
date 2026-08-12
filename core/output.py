"""
Output sinks for human-readable and JSON-formatted output.

Stage 2 of the main.py refactor introduces machine-readable output for
non-interactive use (`pawn --json`, `pawn --eval ...`). Command handlers
write through one of these sinks instead of calling `print()` directly,
so the same code path can produce either ANSI prose for humans or
JSON-Lines for scripts.

Both sinks preserve the original three methods:
    print(text)        — finalized text line for humans
    print_json(data)   — structured payload (always machine-readable)
    write(text)        — partial / streaming chunk, no implicit newline

They also consume typed Agent Events through ``emit(event)``. Human output
renders only user-facing text and error events; lifecycle and telemetry events
remain silent. JSON output serializes the versioned event directly, without
changing or wrapping the legacy records below.

JsonSink emits one JSON object per call to stdout, NDJSON-style:
    {"type": "text",  "content": "..."}     # from print()
    {"type": "chunk", "content": "..."}     # from write()
    {"type": "json",  "data": {...}}        # from print_json()
    {"type": "event", "data": {...}}         # from emit()

This format keeps streaming and structured payloads on the same wire,
so downstream consumers can `for line in stdout: json.loads(line)` and
demultiplex by the `type` field.
"""

from __future__ import annotations

import builtins
import json
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.agent_events import AgentEvent


class TaskOutputCollector:
    """Bounded per-task collector for delegated worker terminal output."""

    def __init__(self, *, max_chars: int = 16_000) -> None:
        if isinstance(max_chars, bool) or not isinstance(max_chars, int):
            raise TypeError("max_chars must be an integer")
        if max_chars < 1:
            raise ValueError("max_chars must be positive")
        self._max_chars = max_chars
        self._parts: list[str] = []
        self._events: list[AgentEvent] = []
        self._size = 0
        self._truncated = False
        self._lock = threading.Lock()

    @property
    def text(self) -> str:
        """Return the captured text, with a marker when it was bounded."""
        with self._lock:
            suffix = "\n...[delegated output truncated]...\n" if self._truncated else ""
            return "".join(self._parts) + suffix

    @property
    def truncated(self) -> bool:
        with self._lock:
            return self._truncated

    @property
    def events(self) -> tuple[AgentEvent, ...]:
        """Return task-local structural events for ordered parent forwarding."""
        with self._lock:
            return tuple(self._events)

    def print(self, text: str) -> None:
        self.write(f"{text}\n")

    def print_json(self, data: dict) -> None:
        self.write(json.dumps(data, ensure_ascii=False) + "\n")

    def write(self, text: str) -> int:
        value = str(text)
        with self._lock:
            remaining = self._max_chars - self._size
            if remaining <= 0:
                self._truncated = True
                return len(value)
            kept = value[:remaining]
            self._parts.append(kept)
            self._size += len(kept)
            if len(kept) != len(value):
                self._truncated = True
        return len(value)

    def flush(self) -> None:
        """Match the stdout-like sink interface without exposing worker output."""

    def emit(self, event: AgentEvent) -> None:
        """Collect typed child events without writing from a worker thread."""
        with self._lock:
            self._events.append(event)


_TASK_OUTPUT: ContextVar[TaskOutputCollector | None] = ContextVar(
    "pawnlogic_task_output",
    default=None,
)
_CAPTURE_LOCK = threading.RLock()
_CAPTURE_USERS = 0
_CAPTURE_PROXY: _TaskOutputProxy | None = None
_CAPTURE_TARGET: Any = None


class _TaskOutputProxy:
    """Route direct ``print`` calls to a task-local collector when bound."""

    def __init__(self, target: Any) -> None:
        self._target = target

    def write(self, text: str) -> int:
        collector = _TASK_OUTPUT.get()
        if collector is not None:
            return collector.write(text)
        return self._target.write(text)

    def flush(self) -> None:
        collector = _TASK_OUTPUT.get()
        if collector is not None:
            collector.flush()
            return
        self._target.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target, name)


@contextmanager
def capture_stdout(collector: TaskOutputCollector) -> Iterator[TaskOutputCollector]:
    """Capture direct stdout writes for one task without cross-thread redirects."""
    if not isinstance(collector, TaskOutputCollector):
        raise TypeError("collector must be a TaskOutputCollector")
    token = _TASK_OUTPUT.set(collector)
    global _CAPTURE_USERS, _CAPTURE_PROXY, _CAPTURE_TARGET
    with _CAPTURE_LOCK:
        if _CAPTURE_USERS == 0:
            _CAPTURE_TARGET = sys.stdout
            _CAPTURE_PROXY = _TaskOutputProxy(_CAPTURE_TARGET)
            sys.stdout = _CAPTURE_PROXY
        _CAPTURE_USERS += 1
    try:
        yield collector
    finally:
        _TASK_OUTPUT.reset(token)
        with _CAPTURE_LOCK:
            _CAPTURE_USERS -= 1
            if _CAPTURE_USERS == 0:
                if sys.stdout is _CAPTURE_PROXY:
                    sys.stdout = _CAPTURE_TARGET
                _CAPTURE_PROXY = None
                _CAPTURE_TARGET = None


# ────────────────────────────────────────────────────────
# Lazy-loaded rich primitives (rich is a hard dependency, but we still
# import inside method bodies so the module remains importable in
# minimal environments and so that test stubs can monkeypatch print).
# ────────────────────────────────────────────────────────


class HumanSink:
    """Default sink for interactive use: ANSI-colored prose to stdout."""

    def emit(self, event: AgentEvent) -> None:
        """Render the user-facing subset of a typed Agent Event.

        Event payloads are rendered directly. Lifecycle and telemetry events
        are intentionally silent so adopting events does not add terminal
        diagnostics or require parsing existing ANSI-formatted output.
        """
        event_type = getattr(event.event_type, "value", event.event_type)
        if event_type == "text.delta":
            text = event.payload.get("text")
            if isinstance(text, str):
                self.write(text)
        elif event_type == "error":
            message = event.payload.get("message")
            if isinstance(message, str):
                self.print(message)

    def print(self, text: str) -> None:
        """Write a finalized line of human-readable text."""
        print(text)

    def print_json(self, data: dict) -> None:
        """Pretty-print a structured payload using rich.print_json.

        Falls back to a plain `json.dumps(..., indent=2)` if rich is not
        importable (which should not happen — rich is a hard dependency —
        but the fallback keeps the sink usable in minimal envs).
        """
        try:
            from rich import print_json as _rprint_json
            _rprint_json(data=data)
        except Exception:
            print(json.dumps(data, indent=2, ensure_ascii=False))

    def write(self, text: str) -> None:
        """Write a partial chunk without appending a newline (streaming)."""
        sys.stdout.write(text)
        sys.stdout.flush()


class JsonSink:
    """Machine-readable sink: emits one JSON object per call (NDJSON)."""

    def emit(self, event: AgentEvent) -> None:
        """Emit a versioned Agent Event inside the additive event record."""
        self._emit({"type": "event", "data": event.to_dict()})

    def print(self, text: str) -> None:
        """Emit a finalized text line as `{"type": "text", "content": ...}`."""
        self._emit({"type": "text", "content": text})

    def print_json(self, data: dict) -> None:
        """Emit a structured payload as `{"type": "json", "data": ...}`."""
        self._emit({"type": "json", "data": data})

    def write(self, text: str) -> None:
        """Emit a streaming chunk as `{"type": "chunk", "content": ...}`."""
        self._emit({"type": "chunk", "content": text})

    @staticmethod
    def _emit(obj: dict[str, Any]) -> None:
        """Serialize one object on its own line and flush immediately."""
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def runtime_print(
    *args: Any,
    sep: str = " ",
    end: str = "\n",
    flush: bool = False,
) -> None:
    """Print through the active RuntimeContext sink when one is bound."""
    from core.runtime_context import current_runtime_context

    context = current_runtime_context()
    if context is None or context.sink is None:
        builtins.print(*args, sep=sep, end=end, flush=flush)
        return
    text = sep.join(str(arg) for arg in args)
    if end == "\n":
        context.sink.print(text)
    else:
        context.sink.write(text + end)


__all__ = [
    "HumanSink",
    "JsonSink",
    "TaskOutputCollector",
    "capture_stdout",
    "runtime_print",
]
