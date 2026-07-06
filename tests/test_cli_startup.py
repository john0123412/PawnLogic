"""CLI startup behavior tests."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import memory
from core.state import set_output_mode
from pawnlogic import cli as cli_mod


ROOT = Path(__file__).resolve().parent.parent


def test_startup_resume_prompt_warns_and_continues_on_session_lookup_failure(
    monkeypatch,
    capsys,
):
    logged: list[str] = []

    class FakeLogger:
        def warning(self, msg, *args):
            logged.append(msg.format(*args))

    def fail_list_sessions(_limit):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(memory, "list_sessions", fail_list_sessions)
    monkeypatch.setattr(cli_mod, "logger", FakeLogger())
    monkeypatch.setattr(cli_mod._runtime_state, "user_mode", True)

    resumed = cli_mod._prompt_startup_resume(SimpleNamespace(messages=[]))

    assert resumed is False
    assert "Startup session resume failed" in logged[0]
    assert "database unavailable" in logged[0]
    assert "Could not load recent sessions" in capsys.readouterr().out


def test_default_help_output_omits_runtime_diagnostics(tmp_path):
    env = os.environ.copy()
    env.update({
        "PAWNLOGIC_HOME": str(tmp_path / "home" / ".pawnlogic"),
        "PAWNLOGIC_TEST_MODE": "true",
        "MCP_ENABLED": "false",
        "PROMPT_TOOLKIT_ENABLED": "0",
        "TERM": "dumb",
        "NO_COLOR": "1",
    })

    result = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "--help"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "--debug" in result.stdout
    assert "Traceback" not in output
    assert "WARNING" not in output
    assert "Tab completion enabled" not in output
    assert "prompt_toolkit failed to load" not in output
    assert "Markdown rendering and code highlighting enabled" not in output


def test_eval_user_mode_exception_hides_traceback(monkeypatch, capsys):
    from core.output import HumanSink

    session = SimpleNamespace(
        session_id="sid",
        model_alias="ds-v4-flash",
        messages=[],
        total_prompt_tokens=0,
        total_completion_tokens=0,
        total_tool_calls=0,
        run_turn=lambda _prompt: (_ for _ in ()).throw(RuntimeError("provider exploded")),
    )
    args = SimpleNamespace(eval="hi", json=False, session=None)
    monkeypatch.setattr(cli_mod, "detach_external_mcp_tools", lambda: None)

    set_output_mode(debug_mode=False)
    try:
        with pytest.raises(SystemExit) as excinfo:
            asyncio.run(cli_mod._run_eval_mode(session, args, HumanSink()))
    finally:
        set_output_mode(debug_mode=False)

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert "provider exploded" in captured.out
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err


def test_eval_debug_mode_exception_keeps_traceback(monkeypatch, capsys):
    from core.output import HumanSink

    session = SimpleNamespace(
        session_id="sid",
        model_alias="ds-v4-flash",
        messages=[],
        total_prompt_tokens=0,
        total_completion_tokens=0,
        total_tool_calls=0,
        run_turn=lambda _prompt: (_ for _ in ()).throw(RuntimeError("debug detail")),
    )
    args = SimpleNamespace(eval="hi", json=False, session=None)
    monkeypatch.setattr(cli_mod, "detach_external_mcp_tools", lambda: None)

    set_output_mode(debug_mode=True)
    try:
        with pytest.raises(SystemExit) as excinfo:
            asyncio.run(cli_mod._run_eval_mode(session, args, HumanSink()))
    finally:
        set_output_mode(debug_mode=False)

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert "debug detail" in captured.out
    assert "Traceback" in captured.err


def test_tool_call_display_hides_argument_preview_until_debug(capsys):
    from core.session import AgentSession
    from core.tool_executor import (
        ToolExecutionResult,
        ToolFailureRecordResult,
        ToolFailurePrecheckResult,
    )
    from core.tool_result import ProcessedToolResult

    class FakeMetrics:
        def record_failure_class(self, _error_type):
            pass

    class FakeExecutor:
        def precheck_failures(self, **_kwargs):
            return ToolFailurePrecheckResult()

        def execute_handler(self, **kwargs):
            return ToolExecutionResult(
                tool_call_id=kwargs["tool_call_id"],
                tool_name=kwargs["tool_name"],
                content="ok",
            )

        def record_failure(self, **_kwargs):
            return ToolFailureRecordResult()

    class FakeProcessor:
        def process(self, **_kwargs):
            return ProcessedToolResult(content="ok")

    session = SimpleNamespace(
        current_phase="RECON",
        messages=[],
        _runtime_metrics=FakeMetrics(),
        _tool_execution_context=lambda _iteration: None,
        _record_tool_metrics=lambda **_kwargs: None,
        session_id="session123",
        model_alias="ds-v4-flash",
        workspace_dir="",
    )
    tool_call = {
        0: {
            "id": "call_1",
            "name": "run_shell",
            "args": '{"command": "echo hidden-command"}',
        }
    }

    set_output_mode(debug_mode=False)
    try:
        AgentSession._execute_tool_batch(
            session,
            tool_call,
            plan_signal_injected=False,
            iteration=0,
            max_iter=3,
            tool_executor=FakeExecutor(),
            result_processor=FakeProcessor(),
            current_tools=None,
        )
        user_output = capsys.readouterr().out

        set_output_mode(debug_mode=True)
        AgentSession._execute_tool_batch(
            session,
            tool_call,
            plan_signal_injected=False,
            iteration=0,
            max_iter=3,
            tool_executor=FakeExecutor(),
            result_processor=FakeProcessor(),
            current_tools=None,
        )
        debug_output = capsys.readouterr().out
    finally:
        set_output_mode(debug_mode=False)

    assert "Working with run_shell" in user_output
    assert "hidden-command" not in user_output
    assert "run_shell" in debug_output
    assert "hidden-command" in debug_output
