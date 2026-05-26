"""
Tests for stage-2 single-shot mode (`pawn --eval ...`) and JSON output of
data-friendly slash commands (/keys, /sessions, /provider list).

Everything is mocked — no real API calls, no real session DB writes,
no real MCP subprocesses. We exercise:

  1. `_run_eval_mode` calls `session.run_turn` exactly once and exits 0.
  2. With `--json`, every line on stdout is valid NDJSON.
  3. `--session <id>` triggers `session_load` and uses the loaded session.
  4. `--session <id>` failure exits with code 2 and skips run_turn.
  5. `/keys` with JsonSink emits a `{"type":"json","data":{...}}` line.
  6. `/sessions` with JsonSink emits a `{"type":"json","data":[...]}` line.
  7. `/provider list` with JsonSink emits a `{"type":"json","data":[...]}` line.
"""

from __future__ import annotations

import asyncio
import json
import types
from unittest.mock import MagicMock

import pytest


# ════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════

@pytest.fixture
def fake_session():
    """Stand-in for AgentSession with the attributes _run_eval_mode reads."""
    s = MagicMock(spec=[
        "session_id", "model_alias", "messages",
        "total_prompt_tokens", "total_completion_tokens", "total_tool_calls",
        "run_turn",
    ])
    s.session_id = "test-session-1"
    s.model_alias = "ds-fake"
    s.messages = []
    s.total_prompt_tokens = 0
    s.total_completion_tokens = 0
    s.total_tool_calls = 0
    return s


@pytest.fixture
def make_args():
    """Factory for argparse-compatible Namespace objects with sensible defaults."""
    def _make(**overrides):
        defaults = {
            "eval":    None,
            "json":    False,
            "session": None,
            "model":   None,
            "quiet":   True,
        }
        defaults.update(overrides)
        return types.SimpleNamespace(**defaults)
    return _make


@pytest.fixture
def patched_main(monkeypatch):
    """Import main and stub out anything that would touch the outside world.

    The eval helper calls `detach_external_mcp_tools()` on every exit
    path — leaving it un-patched would attempt to shut down real MCP
    background threads.
    """
    import main as _main
    monkeypatch.setattr(_main, "detach_external_mcp_tools", lambda: None)
    return _main


@pytest.fixture
def reset_active_sink():
    """Save / restore the process-wide active sink so tests don't bleed."""
    from core.commands._common import set_active_sink, _active_sink as _module_var  # noqa: F401
    # Re-read the live value via getter to avoid stale closure capture.
    from core.commands import _common as _common_mod
    saved = _common_mod._active_sink
    yield
    _common_mod._active_sink = saved


# ════════════════════════════════════════════════════════
# 1-2. --eval single-shot path
# ════════════════════════════════════════════════════════

def test_eval_calls_run_turn_once_then_sys_exit_zero(
    patched_main, fake_session, make_args
):
    """`pawn --eval <prompt>` runs run_turn exactly once and exits with 0."""
    from core.output import HumanSink

    def _fake_run_turn(prompt: str) -> None:
        fake_session.messages.append({"role": "user", "content": prompt})
        fake_session.messages.append({"role": "assistant", "content": "mock reply"})

    fake_session.run_turn = MagicMock(side_effect=_fake_run_turn)

    with pytest.raises(SystemExit) as excinfo:
        asyncio.run(patched_main._run_eval_mode(
            fake_session, make_args(eval="hello"), HumanSink(),
        ))

    assert excinfo.value.code == 0
    fake_session.run_turn.assert_called_once_with("hello")


def test_eval_json_emits_only_valid_json_lines(
    patched_main, fake_session, make_args, capsys
):
    """In `--eval --json` mode, every stdout line must be valid JSON.

    Streaming output from `session.run_turn` (which would be ANSI-colored
    text in production) is suppressed via redirect_stdout; only the final
    structured `result` event is emitted.
    """
    from core.output import JsonSink

    def _fake_run_turn(prompt: str) -> None:
        # Simulate the noisy streaming output that production code prints.
        print("\033[32m[DS-V4-FLASH]\033[0m streaming text...")
        print("more output")
        fake_session.messages.append({
            "role": "assistant", "content": "the actual response",
        })

    fake_session.run_turn = MagicMock(side_effect=_fake_run_turn)

    with pytest.raises(SystemExit) as excinfo:
        asyncio.run(patched_main._run_eval_mode(
            fake_session, make_args(eval="hi", json=True), JsonSink(),
        ))

    assert excinfo.value.code == 0

    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) >= 1, "expected at least one output line"

    # Every line must parse as JSON, and each must carry a `type` field.
    for line in out:
        payload = json.loads(line)  # raises JSONDecodeError on garbage
        assert "type" in payload, f"line missing type field: {payload!r}"

    # The final line should be the structured result with the response text.
    final = json.loads(out[-1])
    assert final["type"] == "json"
    assert final["data"]["type"] == "result"
    assert final["data"]["response"] == "the actual response"
    assert final["data"]["prompt"] == "hi"


# ════════════════════════════════════════════════════════
# 3-4. --session loading
# ════════════════════════════════════════════════════════

def test_eval_with_session_calls_session_load(
    patched_main, fake_session, make_args, monkeypatch
):
    """`--session <id>` triggers session_load with that exact id."""
    from core.output import HumanSink

    fake_session.run_turn = MagicMock(side_effect=lambda p: fake_session.messages.append(
        {"role": "assistant", "content": "x"}
    ))

    load_calls: list[str] = []

    def _fake_load(session, query):
        load_calls.append(query)
        return f"OK loaded session '{query}'"

    monkeypatch.setattr(patched_main, "session_load", _fake_load)

    with pytest.raises(SystemExit) as excinfo:
        asyncio.run(patched_main._run_eval_mode(
            fake_session, make_args(eval="hi", session="abc123"), HumanSink(),
        ))

    assert excinfo.value.code == 0
    assert load_calls == ["abc123"]
    fake_session.run_turn.assert_called_once_with("hi")


def test_eval_with_failed_session_load_exits_2_and_skips_run_turn(
    patched_main, fake_session, make_args, monkeypatch
):
    """If session_load fails, exit code is 2 and run_turn is NOT invoked."""
    from core.output import HumanSink

    fake_session.run_turn = MagicMock()
    monkeypatch.setattr(
        patched_main, "session_load",
        lambda s, q: "ERROR session not found",
    )

    with pytest.raises(SystemExit) as excinfo:
        asyncio.run(patched_main._run_eval_mode(
            fake_session, make_args(eval="hi", session="missing-id"), HumanSink(),
        ))

    assert excinfo.value.code == 2
    fake_session.run_turn.assert_not_called()


# ════════════════════════════════════════════════════════
# 5-7. JSON output format of /keys, /sessions, /provider list
# ════════════════════════════════════════════════════════

def test_keys_json_output_is_dict(capsys):
    """`pawn --json /keys` → `{"type":"json","data": {ENV: bool, ...}}`."""
    from core.commands import CommandContext, dispatch
    from core.output import JsonSink

    class _S:
        pass

    ctx = CommandContext(verb="/keys", arg="", arg2="", session=_S(), sink=JsonSink())
    asyncio.run(dispatch(ctx))

    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1, f"expected one NDJSON line, got: {lines!r}"
    payload = json.loads(lines[0])
    assert payload["type"] == "json"
    assert isinstance(payload["data"], dict)
    for env, status in payload["data"].items():
        assert isinstance(env, str) and env
        assert isinstance(status, bool)


def test_sessions_json_output_is_list(capsys, monkeypatch):
    """`pawn --json /sessions` → `{"type":"json","data": [...sessions...]}`."""
    from core.commands import CommandContext, dispatch
    from core.output import JsonSink

    fake_rows = [
        {
            "id":              "sess-001",
            "name":            "first-session",
            "auto_name":       None,
            "workspace_alias": None,
            "updated_at":      "2026-05-26 12:00",
            "msg_count":       7,
            "model":           "ds-fake",
            "tags":            "demo",
        },
        {
            "id":              "sess-002",
            "name":            None,
            "auto_name":       "auto-named",
            "workspace_alias": None,
            "updated_at":      "2026-05-25 09:30",
            "msg_count":       3,
            "model":           "claude-haiku",
            "tags":            None,
        },
    ]
    monkeypatch.setattr("core.commands.session.list_sessions", lambda n: fake_rows)

    class _S:
        pass

    ctx = CommandContext(verb="/sessions", arg="", arg2="", session=_S(), sink=JsonSink())
    asyncio.run(dispatch(ctx))

    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1, f"expected one NDJSON line, got: {lines!r}"
    payload = json.loads(lines[0])
    assert payload["type"] == "json"
    assert isinstance(payload["data"], list)
    assert len(payload["data"]) == 2

    first = payload["data"][0]
    assert first["id"] == "sess-001"
    assert first["name"] == "first-session"
    assert first["msg_count"] == 7

    second = payload["data"][1]
    assert second["id"] == "sess-002"
    # When name is None, falls back to auto_name → workspace_alias → ""
    assert second["name"] == "auto-named"


def test_provider_list_json_output_is_list(capsys, reset_active_sink):
    """`pawn --json /provider list` → `{"type":"json","data": [...providers...]}`.

    `_provider_list` reads from the process-wide active sink (not ctx.sink),
    so we stash a JsonSink there for the duration of this test.
    """
    from core.commands import CommandContext, dispatch
    from core.commands._common import set_active_sink
    from core.output import JsonSink

    set_active_sink(JsonSink())

    class _S:
        pass

    ctx = CommandContext(
        verb="/provider", arg="list", arg2="", session=_S(), sink=JsonSink(),
    )
    asyncio.run(dispatch(ctx))

    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1, f"expected one NDJSON line, got: {lines!r}"
    payload = json.loads(lines[0])
    assert payload["type"] == "json"
    assert isinstance(payload["data"], list)
    assert len(payload["data"]) >= 1, "expected at least one provider"

    first = payload["data"][0]
    # Required schema keys per stage-2 spec.
    for required in ("name", "label", "api_format", "key_env", "key_set", "models"):
        assert required in first, f"missing key {required!r} in {first!r}"
    assert isinstance(first["models"], list)
    assert isinstance(first["key_set"], bool)
