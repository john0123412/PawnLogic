"""tests/test_host_process.py - Tests for core/host_process.py."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

from core.host_process import (
    HostProcessRequest,
    HostProcessRunner,
    classify_host_process,
    run_bounded_argv,
    run_with_policy,
    scrub_environment,
)
from core.operation_policy import OperationAction, OperationDecision


class TestScrubEnvironment:
    """Tests for environment scrubbing."""

    def test_removes_api_keys(self) -> None:
        env = {"OPENAI_API_KEY": "secret", "HOME": "/home/user"}
        result = scrub_environment(env)
        assert "OPENAI_API_KEY" not in result
        assert result["HOME"] == "/home/user"

    def test_keeps_url_vars(self) -> None:
        env = {"OPENAI_BASE_URL": "https://api.openai.com", "HOME": "/home/user"}
        result = scrub_environment(env)
        assert result["OPENAI_BASE_URL"] == "https://api.openai.com"

    def test_removes_deepseek_key(self) -> None:
        env = {"DEEPSEEK_API_KEY": "sk-test"}
        result = scrub_environment(env)
        assert "DEEPSEEK_API_KEY" not in result

    def test_keeps_non_sensitive_vars(self) -> None:
        env = {"PATH": "/usr/bin", "HOME": "/home/user", "USER": "test"}
        result = scrub_environment(env)
        assert result == env

    def test_keeps_pawnlogic_home(self) -> None:
        env = {"PAWNLOGIC_HOME": "/home/user/.pawnlogic", "OPENAI_API_KEY": "secret"}
        result = scrub_environment(env)
        assert "PAWNLOGIC_HOME" in result  # _HOME suffix is non-secret config
        assert "OPENAI_API_KEY" not in result


class TestClassifyHostProcess:
    """Tests for host process classification."""

    def test_safe_command_allowed(self, tmp_path: Path) -> None:
        request = HostProcessRequest(
            command="echo hello",
            cwd=tmp_path,
            timeout_seconds=10.0,
        )
        decision = classify_host_process(request)
        assert decision.action.value in ("allow", "confirm")

    def test_dangerous_command_denied(self, tmp_path: Path) -> None:
        request = HostProcessRequest(
            command="rm -rf /",
            cwd=tmp_path,
            timeout_seconds=10.0,
        )
        decision = classify_host_process(request)
        assert decision.action.value in ("deny", "confirm")


class TestHostProcessRunner:
    """Tests for HostProcessRunner."""

    def test_run_safe_command(self, tmp_path: Path) -> None:
        runner = HostProcessRunner()
        request = HostProcessRequest(
            command="echo hello",
            cwd=tmp_path,
            timeout_seconds=10.0,
        )
        outcome = runner.run(request)
        assert outcome.returncode == 0
        assert "hello" in outcome.output
        assert not outcome.timed_out

    def test_run_timeout(self, tmp_path: Path) -> None:
        runner = HostProcessRunner()
        request = HostProcessRequest(
            command="sleep 10",
            cwd=tmp_path,
            timeout_seconds=0.1,
        )
        outcome = runner.run(request)
        assert outcome.returncode == -1
        assert outcome.timed_out

    def test_run_denied_command(self, tmp_path: Path) -> None:
        runner = HostProcessRunner()
        request = HostProcessRequest(
            command="rm -rf /",
            cwd=tmp_path,
            timeout_seconds=10.0,
        )
        outcome = runner.run(request)
        assert outcome.returncode == -1
        assert "Denied" in outcome.output

    def test_run_failing_command(self, tmp_path: Path) -> None:
        runner = HostProcessRunner()
        request = HostProcessRequest(
            command="false",
            cwd=tmp_path,
            timeout_seconds=10.0,
        )
        outcome = runner.run(request)
        assert outcome.returncode != 0
        assert not outcome.timed_out

    def test_process_group_cleanup(self, tmp_path: Path) -> None:
        """Verify start_new_session is used for process group cleanup."""
        runner = HostProcessRunner()
        request = HostProcessRequest(
            command="echo test",
            cwd=tmp_path,
            timeout_seconds=10.0,
        )
        outcome = runner.run(request)
        assert outcome.returncode == 0

    def test_confirm_non_interactive_fails_closed(self, tmp_path: Path) -> None:
        """CONFIRM in non-interactive mode must fail closed."""
        runner = HostProcessRunner()

        decision = OperationDecision(
            action=OperationAction.CONFIRM,
            risk="medium",
            reason="test confirmation",
            matched_rule="test",
            redacted_command="test",
        )

        with patch("core.host_process.classify_shell_command", return_value=decision):
            request = HostProcessRequest(
                command="test command",
                cwd=tmp_path,
                timeout_seconds=10.0,
                interactive=False,
            )
            outcome = runner.run(request)
            assert outcome.returncode == -1
            assert "Requires confirmation" in outcome.output
            assert "non-interactive" in outcome.output

    def test_confirm_interactive_fails_without_authorization(
        self, tmp_path: Path
    ) -> None:
        """CONFIRM in interactive mode must fail without explicit authorization."""
        runner = HostProcessRunner()  # Default authorizer denies.

        decision = OperationDecision(
            action=OperationAction.CONFIRM,
            risk="medium",
            reason="test confirmation",
            matched_rule="test",
            redacted_command="test",
        )

        with patch("core.host_process.classify_shell_command", return_value=decision):
            request = HostProcessRequest(
                command="test command",
                cwd=tmp_path,
                timeout_seconds=10.0,
                interactive=True,
            )
            outcome = runner.run(request)
            assert outcome.returncode == -1
            assert "confirmation not granted" in outcome.output

    def test_confirm_interactive_executes_with_authorizer(
        self, tmp_path: Path
    ) -> None:
        """CONFIRM in interactive mode executes when authorizer grants."""
        runner = HostProcessRunner(authorizer=lambda d: True)

        decision = OperationDecision(
            action=OperationAction.CONFIRM,
            risk="medium",
            reason="test confirmation",
            matched_rule="test",
            redacted_command="echo authorized",
        )

        with patch("core.host_process.classify_shell_command", return_value=decision):
            request = HostProcessRequest(
                command="echo authorized",
                cwd=tmp_path,
                timeout_seconds=10.0,
                interactive=True,
            )
            outcome = runner.run(request)
            assert outcome.returncode == 0
            assert "authorized" in outcome.output

    def test_run_with_policy_convenience(self, tmp_path: Path) -> None:
        """run_with_policy convenience function works."""
        outcome = run_with_policy("echo hello", tmp_path, 10.0)
        assert outcome.returncode == 0
        assert "hello" in outcome.output

    def test_allow_executes(self, tmp_path: Path) -> None:
        """ALLOW must execute the command."""
        runner = HostProcessRunner()

        decision = OperationDecision(
            action=OperationAction.ALLOW,
            risk="low",
            reason="safe command",
            matched_rule="test",
            redacted_command="echo hello",
        )

        with patch("core.host_process.classify_shell_command", return_value=decision):
            request = HostProcessRequest(
                command="echo hello",
                cwd=tmp_path,
                timeout_seconds=10.0,
            )
            outcome = runner.run(request)
            assert outcome.returncode == 0
            assert "hello" in outcome.output

    def test_deny_blocks_execution(self, tmp_path: Path) -> None:
        """DENY must block execution."""
        runner = HostProcessRunner()

        decision = OperationDecision(
            action=OperationAction.DENY,
            risk="high",
            reason="dangerous command",
            matched_rule="test",
            redacted_command="rm -rf /",
        )

        with patch("core.host_process.classify_shell_command", return_value=decision):
            request = HostProcessRequest(
                command="rm -rf /",
                cwd=tmp_path,
                timeout_seconds=10.0,
            )
            outcome = runner.run(request)
            assert outcome.returncode == -1
            assert "Denied" in outcome.output


class TestRunBoundedArgv:
    """run_bounded_argv must never block indefinitely on a stuck child."""

    def test_captures_stdout_of_fast_command(self) -> None:
        rc, out = run_bounded_argv([sys.executable, "-c", "print('bounded-ok')"], 15.0)

        assert rc == 0
        assert "bounded-ok" in out

    def test_escalates_to_sigkill_when_child_ignores_sigterm(self) -> None:
        code = (
            "import signal, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "print('ready', flush=True)\n"
            "time.sleep(30)\n"
        )
        started = time.monotonic()

        rc, out = run_bounded_argv([sys.executable, "-c", code], 0.5)
        elapsed = time.monotonic() - started

        assert "ready" in out
        assert rc != 0
        # SIGTERM grace (5s) + SIGKILL reaping grace must stay bounded.
        assert elapsed < 20.0, f"run_bounded_argv blocked for {elapsed:.1f}s"

    def test_survives_pipe_flood_from_stubborn_child(self) -> None:
        code = (
            "import signal, sys, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "sys.stdout.write('x' * 200000)\n"
            "sys.stdout.flush()\n"
            "time.sleep(30)\n"
        )
        started = time.monotonic()

        rc, out = run_bounded_argv([sys.executable, "-c", code], 0.5)
        elapsed = time.monotonic() - started

        assert len(out) >= 100_000
        assert rc != 0
        assert elapsed < 20.0, f"run_bounded_argv blocked for {elapsed:.1f}s"
