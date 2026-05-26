"""
Output sinks for human-readable and JSON-formatted output.

Stage 2 of the main.py refactor introduces machine-readable output for
non-interactive use (`pawn --json`, `pawn --eval ...`). This module
defines the abstract sink interface that command handlers will write
through. Implementation comes in a later step; for now these are
skeletons so the import graph and tests can be wired up incrementally.

Usage (planned, not yet enforced):
    sink: HumanSink | JsonSink = JsonSink() if args.json else HumanSink()
    sink.print("hello")               # prose for humans
    sink.print_json({"status": "ok"}) # structured for scripts

Both sinks accept the same call shape so command handlers can stay
agnostic about which format is active.
"""

from __future__ import annotations


class HumanSink:
    """Default sink: writes ANSI-colored prose to stdout."""

    def print(self, text: str) -> None:  # noqa: D401
        ...

    def print_json(self, data: dict) -> None:
        ...


class JsonSink:
    """Machine-readable sink: emits one JSON object per call."""

    def print(self, text: str) -> None:
        ...

    def print_json(self, data: dict) -> None:
        ...


__all__ = ["HumanSink", "JsonSink"]
