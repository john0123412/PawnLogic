#!/usr/bin/env python3
"""Run deterministic slash-command transcripts without starting the full REPL."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from core.commands import CommandContext, dispatch
from core.commands._common import EXIT_SENTINEL, set_active_sink
from core.state import set_output_mode


class TranscriptSink:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def print(self, text: str = "") -> None:
        self.parts.append(str(text) + "\n")

    def print_json(self, data: dict[str, Any]) -> None:
        self.parts.append(str(data) + "\n")

    def write(self, text: str) -> None:
        self.parts.append(str(text))

    @property
    def text(self) -> str:
        return "".join(self.parts)


@dataclass(frozen=True)
class TranscriptResult:
    commands: list[str]
    output: str
    exit_requested: bool


class TranscriptSession(SimpleNamespace):
    def __init__(self, cwd: Path) -> None:
        super().__init__(
            cwd=str(cwd),
            workspace_dir=str(cwd),
            messages=[],
            model_alias="ds-v4-flash",
            session_id="transcript-session",
            total_prompt_tokens=0,
            total_completion_tokens=0,
            total_tool_calls=0,
            _turn_start_time=0,
            _time_budget_sec=0,
            _urgent_mode=False,
        )

    def _reset_system_prompt(self) -> None:
        return None

    def _autosave(self) -> None:
        return None


@contextmanager
def _patched_env(env: Mapping[str, str] | None):
    if not env:
        yield
        return

    sentinel = object()
    previous: dict[str, str | object] = {}
    for key, value in env.items():
        previous[key] = os.environ.get(key, sentinel)
        if value == "":
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is sentinel:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)


def _parse_command(raw: str, session: Any, sink: TranscriptSink) -> CommandContext:
    parts = raw.strip().split(None, 2)
    return CommandContext(
        verb=parts[0].lower(),
        arg=parts[1].strip() if len(parts) > 1 else "",
        arg2=parts[2].strip() if len(parts) > 2 else "",
        session=session,
        sink=sink,
    )


async def _run_commands(commands: Iterable[str], session: Any, sink: TranscriptSink) -> bool:
    exit_requested = False
    for raw in commands:
        if not raw.strip():
            continue
        result = await dispatch(_parse_command(raw, session, sink))
        if result is EXIT_SENTINEL:
            exit_requested = True
            break
    return exit_requested


def run_transcript(
    commands: Iterable[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    session: Any | None = None,
) -> TranscriptResult:
    command_list = list(commands)
    sink = TranscriptSink()
    transcript_session = session or TranscriptSession((cwd or Path.cwd()).resolve())

    with _patched_env(env):
        set_active_sink(sink)
        set_output_mode(debug_mode=False)
        try:
            exit_requested = asyncio.run(
                _run_commands(command_list, transcript_session, sink)
            )
        finally:
            set_output_mode(debug_mode=False)
            set_active_sink(None)

    return TranscriptResult(
        commands=command_list,
        output=sink.text,
        exit_requested=exit_requested,
    )


__all__ = ["TranscriptResult", "TranscriptSink", "run_transcript"]
