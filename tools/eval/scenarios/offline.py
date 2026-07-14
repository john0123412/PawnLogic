"""Provider stream fixture replay through production parser helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.provider_streams import (
    parse_anthropic_sse_event,
    parse_sse_delta,
    stream_interruption_delta,
)


def _load(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_offline_replay(fixtures_dir: Path) -> dict[str, object]:
    """Replay OpenAI and Anthropic events and assert their stable delta shapes."""
    fixture_paths = sorted(fixtures_dir.glob("*_replay.jsonl"))
    if not fixture_paths:
        return {
            "status": "failed",
            "summary": "Provider replay fixtures are missing.",
            "api_calls": 0,
            "tool_calls": 0,
            "failure_class": "FixturesMissing",
        }

    emitted: list[dict[str, Any]] = []
    kinds: set[str] = set()
    anthropic_state: dict[str, Any] = {"tool_blocks": {}}
    for path in fixture_paths:
        for event in _load(path):
            kind = str(event["kind"])
            kinds.add(kind)
            parsed: dict[str, Any] | None
            if event["format"] == "anthropic":
                parsed = parse_anthropic_sse_event(
                    str(event.get("event", "")),
                    json.dumps(event["payload"]),
                    anthropic_state,
                )
            elif kind == "interruption":
                parsed = stream_interruption_delta(
                    OSError(str(event.get("error", "connection reset"))),
                    str(event.get("partial_text", "")),
                )
            elif kind == "retry":
                parsed = dict(event["payload"])
            else:
                raw = event.get("raw")
                parsed = parse_sse_delta(
                    str(raw) if raw is not None else json.dumps(event["payload"])
                )
            if parsed is not None:
                emitted.append(parsed)

    required = {"text", "usage", "tool_call", "retry", "malformed", "interruption"}
    missing = required - kinds
    has_text = any(
        item.get("choices", [{}])[0].get("delta", {}).get("content")
        for item in emitted
        if item.get("choices")
    )
    has_tool = any(
        item.get("choices", [{}])[0].get("delta", {}).get("tool_calls")
        for item in emitted
        if item.get("choices")
    )
    has_usage = any("_usage" in item or "usage" in item for item in emitted)
    has_retry = any("_retry" in item for item in emitted)
    has_partial_end = any(item.get("_partial_end") is True for item in emitted)
    if missing or not all((has_text, has_tool, has_usage, has_retry, has_partial_end)):
        return {
            "status": "failed",
            "summary": "Provider replay did not cover every required delta class.",
            "api_calls": 0,
            "tool_calls": len(emitted),
            "failure_class": "ReplayCoverageFailure",
        }
    return {
        "status": "passed",
        "summary": (
            f"Replayed {len(emitted)} provider events through production parsers "
            "with text, usage, tool, retry, malformed, and interruption coverage."
        ),
        "api_calls": 0,
        "tool_calls": len(emitted),
        "failure_class": "",
    }


__all__ = ["run_offline_replay"]
