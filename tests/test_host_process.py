"""tests/test_host_process.py - Tests for core/host_process.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core.host_process import (
    HostProcessRequest,
    HostProcessRunner,
    classify_host_process,
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
                interactive=True,
            )
            outcome = runner.run(request)
            assert outcome.returncode == -1
            assert "Requires confirmation" in outcome.output

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
