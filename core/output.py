"""
Output sinks for human-readable and JSON-formatted output.

Stage 2 of the main.py refactor introduces machine-readable output for
non-interactive use (`pawn --json`, `pawn --eval ...`). Command handlers
write through one of these sinks instead of calling `print()` directly,
so the same code path can produce either ANSI prose for humans or
JSON-Lines for scripts.

Both sinks expose the same three methods:
    print(text)        — finalized text line for humans
    print_json(data)   — structured payload (always machine-readable)
    write(text)        — partial / streaming chunk, no implicit newline

JsonSink emits one JSON object per call to stdout, NDJSON-style:
    {"type": "text",  "content": "..."}     # from print()
    {"type": "chunk", "content": "..."}     # from write()
    {"type": "json",  "data": {...}}        # from print_json()

This format keeps streaming and structured payloads on the same wire,
so downstream consumers can `for line in stdout: json.loads(line)` and
demultiplex by the `type` field.
"""

from __future__ import annotations

import json
import sys
from typing import Any


# ────────────────────────────────────────────────────────
# Lazy-loaded rich primitives (rich is a hard dependency, but we still
# import inside method bodies so the module remains importable in
# minimal environments and so that test stubs can monkeypatch print).
# ────────────────────────────────────────────────────────


class HumanSink:
    """Default sink for interactive use: ANSI-colored prose to stdout."""

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


__all__ = ["HumanSink", "JsonSink"]
