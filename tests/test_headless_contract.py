"""Contract tests for the headless core protocol (ADR 0011).

These pin the v1 wire: NDJSON over stdio, a `{"v": 1, "type": ...}`
envelope on every message, the minimal request surface (prompt /
command / shutdown), and the event vocabulary (status / result / error /
command_result). Schema-level and mock-driven — no real API calls.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from pawnlogic import headless
from pawnlogic.headless import HeadlessServer, make_event

from config.providers import DEFAULT_MODEL

ROOT = Path(__file__).resolve().parent.parent


# ════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════

class FakeSession:
    """Stand-in for AgentSession with the attributes the server reads."""

    def __init__(self, *, model_alias: str = "test-fake-model"):
        self.session_id = "sess-headless-1"
        self.model_alias = model_alias
        self.messages: list[dict] = []
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tool_calls = 0
        self.last_turn_api_error: str | None = None
        self.shutdown_calls = 0
        self.run_turn_calls: list[str] = []

    def run_turn(self, prompt: str) -> None:
        self.run_turn_calls.append(prompt)

    def shutdown(self) -> bool:
        self.shutdown_calls += 1
        return True


def make_server(lines: list[str], session: FakeSession):
    """Build a server over scripted stdin, collecting emitted events."""
    stream = io.StringIO("".join(line + "\n" for line in lines))
    events: list[dict] = []

    def read_line() -> str | None:
        raw = stream.readline()
        return raw if raw else None

    server = HeadlessServer(session, read_line=read_line, emit=events.append)
    return server, events


def line_request(payload: dict | list | str) -> str:
    if isinstance(payload, str):
        return payload
    return json.dumps(payload)


# ════════════════════════════════════════════════════════
# Envelope contract
# ════════════════════════════════════════════════════════

def test_make_event_always_carries_version_envelope():
    event = make_event("result", prompt="hi")
    assert event["v"] == headless.PROTOCOL_VERSION == 1
    assert event["type"] == "result"
    assert event["prompt"] == "hi"


def test_every_emitted_message_carries_envelope():
    session = FakeSession()

    def _fake_run_turn(prompt: str) -> None:
        session.messages.append({"role": "assistant", "content": "ok"})

    session.run_turn = _fake_run_turn
    server, events = make_server(
        [
            line_request({"v": 1, "type": "prompt", "text": "hello"}),
            line_request({"type": "shutdown"}),
        ],
        session,
    )
    code = server.serve()
    assert code == 0
    assert events
    for event in events:
        assert event["v"] == 1, event
        assert isinstance(event.get("type"), str) and event["type"], event


# ════════════════════════════════════════════════════════
# Request surface
# ════════════════════════════════════════════════════════

def test_ready_status_is_first_event():
    session = FakeSession()
    server, events = make_server([line_request({"type": "shutdown"})], session)
    server.serve()
    assert events[0]["type"] == "status"
    assert events[0]["stage"] == "ready"
    assert events[0]["model"] == "test-fake-model"
    assert events[0]["session_id"] == "sess-headless-1"


def test_prompt_runs_turn_and_emits_result():
    session = FakeSession()

    def _fake_run_turn(prompt: str) -> None:
        session.run_turn_calls.append(prompt)
        session.messages.append({"role": "assistant", "content": "mock reply"})
        session.total_prompt_tokens = 10
        session.total_completion_tokens = 3

    session.run_turn = _fake_run_turn
    server, events = make_server(
        [
            line_request({"v": 1, "type": "prompt", "text": "hello"}),
            line_request({"type": "shutdown"}),
        ],
        session,
    )
    code = server.serve()
    assert code == 0
    assert session.run_turn_calls == ["hello"]
    result = next(e for e in events if e["type"] == "result")
    assert result["prompt"] == "hello"
    assert result["response"] == "mock reply"
    assert result["session_id"] == "sess-headless-1"
    assert result["model"] == "test-fake-model"
    assert result["prompt_tokens"] == 10
    assert result["completion_tokens"] == 3
    assert result["tool_calls"] == 0


def test_prompt_api_failure_emits_error_and_keeps_serving():
    session = FakeSession()

    def _fake_failed_run_turn(prompt: str) -> None:
        session.last_turn_api_error = "circuit open"

    session.run_turn = _fake_failed_run_turn
    server, events = make_server(
        [
            line_request({"type": "prompt", "text": "hi"}),
            line_request({"type": "shutdown"}),
        ],
        session,
    )
    code = server.serve()
    assert code == 0  # serve keeps accepting requests after a failed turn
    error = next(e for e in events if e["type"] == "error")
    assert error["stage"] == "run_turn"
    assert "circuit open" in error["detail"]


def test_prompt_missing_api_key_fails_fast_without_turn():
    session = FakeSession(model_alias=DEFAULT_MODEL)
    server, events = make_server(
        [
            line_request({"type": "prompt", "text": "hi"}),
            line_request({"type": "shutdown"}),
        ],
        session,
    )
    code = server.serve()
    assert code == 0
    assert session.run_turn_calls == []
    error = next(e for e in events if e["type"] == "error")
    assert error["stage"] == "api_key"
    assert "DEEPSEEK_API_KEY" in error["detail"]


def test_empty_prompt_text_rejected():
    session = FakeSession()
    server, events = make_server(
        [
            line_request({"type": "prompt"}),
            line_request({"type": "shutdown"}),
        ],
        session,
    )
    server.serve()
    assert session.run_turn_calls == []
    error = next(e for e in events if e["type"] == "error")
    assert error["stage"] == "prompt"


def test_command_dispatches_and_emits_command_result():
    session = FakeSession()
    server, events = make_server(
        [
            line_request({"type": "command", "line": "/keys"}),
            line_request({"type": "shutdown"}),
        ],
        session,
    )
    code = server.serve()
    assert code == 0
    result = next(e for e in events if e["type"] == "command_result")
    assert result["verb"] == "/keys"
    assert isinstance(result["output"], list) and result["output"]


def test_shutdown_stops_session_and_emits_status():
    session = FakeSession()
    server, events = make_server([line_request({"type": "shutdown"})], session)
    code = server.serve()
    assert code == 0
    assert session.shutdown_calls == 1
    assert events[-1]["type"] == "status"
    assert events[-1]["stage"] == "shutdown"


def test_eof_shuts_down_gracefully():
    session = FakeSession()
    server, events = make_server([], session)
    code = server.serve()
    assert code == 0
    assert session.shutdown_calls == 1
    assert events[-1]["stage"] == "shutdown"


# ════════════════════════════════════════════════════════
# Protocol robustness
# ════════════════════════════════════════════════════════

def test_malformed_json_line_emits_protocol_error_and_continues():
    session = FakeSession()
    server, events = make_server(
        [
            "{not json",
            line_request({"type": "shutdown"}),
        ],
        session,
    )
    code = server.serve()
    assert code == 0
    error = next(e for e in events if e["type"] == "error")
    assert error["stage"] == "protocol"
    assert session.shutdown_calls == 1


def test_non_object_request_rejected():
    session = FakeSession()
    server, events = make_server(
        [
            line_request([1, 2, 3]),
            line_request({"type": "shutdown"}),
        ],
        session,
    )
    code = server.serve()
    assert code == 0
    error = next(e for e in events if e["type"] == "error")
    assert error["stage"] == "protocol"


def test_unknown_request_type_is_ignored():
    session = FakeSession()
    server, events = make_server(
        [
            line_request({"type": "hover_widget", "x": 3}),
            line_request({"type": "shutdown"}),
        ],
        session,
    )
    code = server.serve()
    assert code == 0
    assert not any(e["type"] == "error" for e in events)
    assert session.shutdown_calls == 1


def test_blank_lines_are_skipped():
    session = FakeSession()
    server, events = make_server(
        [
            "",
            "   ",
            line_request({"type": "shutdown"}),
        ],
        session,
    )
    code = server.serve()
    assert code == 0
    assert not any(e["type"] == "error" for e in events)


# ════════════════════════════════════════════════════════
# Shared --eval pre-flight helper
# ════════════════════════════════════════════════════════

def test_missing_key_detail_helper_matches_pre_flight(monkeypatch):
    session = FakeSession(model_alias=DEFAULT_MODEL)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    detail = headless.missing_key_detail(session)
    assert detail is not None
    assert "DEEPSEEK_API_KEY" in detail

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-dummy-value")
    assert headless.missing_key_detail(session) is None


def test_missing_key_detail_skips_unknown_aliases():
    session = FakeSession(model_alias="totally-unknown-alias")
    assert headless.missing_key_detail(session) is None


# ════════════════════════════════════════════════════════
# CLI surface: parser validation and real-process wire
# ════════════════════════════════════════════════════════

def test_parser_accepts_serve_and_rejects_session_arg(monkeypatch):
    import argparse
    import sys

    from pawnlogic.restart_recovery import parse_cli_arguments

    monkeypatch.setattr(sys, "argv", ["pawn", "serve"])
    parser = argparse.ArgumentParser(prog="pawn")
    parser.add_argument("--eval", "-e", default=None)
    parser.add_argument("--session", "-s", default=None)
    parser.add_argument("--json", action="store_true", default=False)
    args = parse_cli_arguments(parser)
    assert args.command == "serve"

    monkeypatch.setattr(sys, "argv", ["pawn", "serve", "sid"])
    parser = argparse.ArgumentParser(prog="pawn")
    parser.add_argument("--eval", "-e", default=None)
    parser.add_argument("--session", "-s", default=None)
    parser.add_argument("--json", action="store_true", default=False)
    with pytest.raises(SystemExit) as excinfo:
        parse_cli_arguments(parser)
    assert excinfo.value.code == 2


def test_serve_end_to_end_over_real_stdin(tmp_path):
    """`pawn serve` speaks the real wire: ready status, prompt pre-flight
    error (no key in this env), graceful shutdown, exit 0."""
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if not k.endswith("API_KEY")}
    env.update({
        "PAWNLOGIC_HOME": str(tmp_path / "home"),
        "PAWNLOGIC_TEST_MODE": "true",
        "MCP_ENABLED": "false",
        "PROMPT_TOOLKIT_ENABLED": "0",
        "TERM": "dumb",
        "NO_COLOR": "1",
    })
    stdin_data = (
        line_request({"v": 1, "type": "prompt", "text": "hi"})
        + "\n"
        + line_request({"type": "shutdown"})
        + "\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "pawnlogic", "serve"],
        input=stdin_data,
        text=True,
        capture_output=True,
        env=env,
        cwd=str(ROOT),
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert events, "expected at least one event on the wire"
    for event in events:
        assert event["v"] == 1 and event["type"], event
    assert events[0]["type"] == "status" and events[0]["stage"] == "ready"
    api_key_errors = [e for e in events if e["type"] == "error" and e["stage"] == "api_key"]
    assert api_key_errors, f"expected api_key pre-flight error, got: {events!r}"
    assert events[-1]["type"] == "status" and events[-1]["stage"] == "shutdown"
