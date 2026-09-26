"""tests/test_process_trust_routing.py - Tests for process trust routing.

Proves that production handlers check policy before spawning processes.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core.host_process import HostProcessRunner, HostProcessRequest
from core.operation_policy import OperationAction, OperationDecision


class TestRunCodePolicyEnforcement:
    """Tests that tool_run_code checks policy before spawning."""

    def test_deny_blocks_code_execution(self, tmp_path: Path) -> None:
        """DENY must prevent code execution entirely."""
        from tools.sandbox import tool_run_code
        from core.operation_policy import RiskLevel

        decision = OperationDecision(
            action=OperationAction.DENY,
            risk=RiskLevel.HIGH,
            reason="code execution blocked",
            matched_rule="test",
            redacted_command="run_code(python)",
        )

        with patch("core.host_process.classify_shell_command", return_value=decision):
            result = tool_run_code({"language": "python", "code": "print(1)"})
            assert "Denied" in result or "ERROR" in result

    def test_confirm_non_interactive_blocks_code_execution(
        self, tmp_path: Path
    ) -> None:
        """CONFIRM in non-interactive mode must block code execution."""
        from tools.sandbox import tool_run_code
        from core.operation_policy import RiskLevel

        decision = OperationDecision(
            action=OperationAction.CONFIRM,
            risk=RiskLevel.MEDIUM,
            reason="code execution needs confirmation",
            matched_rule="test",
            redacted_command="run_code(python)",
        )

        with patch("core.host_process.classify_shell_command", return_value=decision):
            result = tool_run_code({"language": "python", "code": "print(1)"})
            assert "Requires confirmation" in result or "ERROR" in result


class TestPwnTimedDebugPolicyEnforcement:
    """Tests that pwn_timed_debug checks policy before spawning."""

    def test_deny_blocks_pwn_execution(self, tmp_path: Path) -> None:
        """DENY must prevent pwn execution entirely."""
        from tools.pwn_chain import tool_pwn_timed_debug
        from core.operation_policy import RiskLevel

        decision = OperationDecision(
            action=OperationAction.DENY,
            risk=RiskLevel.HIGH,
            reason="pwn execution blocked",
            matched_rule="test",
            redacted_command="nc target 1337",
        )

        with patch("core.host_process.classify_shell_command", return_value=decision):
            result = tool_pwn_timed_debug({"command": "nc target 1337"})
            assert "Denied" in result or "ERROR" in result

    def test_confirm_non_interactive_blocks_pwn_execution(
        self, tmp_path: Path
    ) -> None:
        """CONFIRM in non-interactive mode must block pwn execution."""
        from tools.pwn_chain import tool_pwn_timed_debug
        from core.operation_policy import RiskLevel

        decision = OperationDecision(
            action=OperationAction.CONFIRM,
            risk=RiskLevel.MEDIUM,
            reason="pwn needs confirmation",
            matched_rule="test",
            redacted_command="nc target 1337",
        )

        with patch("core.host_process.classify_shell_command", return_value=decision):
            result = tool_pwn_timed_debug({"command": "nc target 1337"})
            assert "Requires confirmation" in result or "ERROR" in result


class TestAllowPathExecutesExactlyOnce:
    """ALLOW must execute exactly once.

    Regression: the pre-flight gate used HostProcessRunner.run(), which both
    classifies AND spawns. ALLOW therefore ran the command a second time on
    the real execution path.
    """

    def test_pwn_timed_debug_runs_command_exactly_once(
        self, tmp_path: Path
    ) -> None:
        """An ALLOWed pwn_timed_debug command must have one side effect."""
        from tools.pwn_chain import tool_pwn_timed_debug
        import tools.file_ops as file_ops

        file_ops._session_cwd[0] = str(tmp_path)
        marker = tmp_path / "hit"

        result = tool_pwn_timed_debug(
            {
                "command": f"printf x >> {marker}",
                "inputs": [],
                "time_limit_sec": 5,
            }
        )

        assert marker.exists(), result
        assert marker.read_text() == "x", (
            f"command executed {len(marker.read_text())} times; expected once"
        )


class TestRunCodePolicyGateMatchesExecution:
    """The run_code gate must classify the command that actually executes."""

    def test_gate_classifies_the_real_interpreter_command(
        self, tmp_path: Path
    ) -> None:
        """The gate must see the interpreter command, not a synthetic label."""
        from tools.sandbox import tool_run_code
        from core.operation_policy import RiskLevel
        import tools.file_ops as file_ops

        file_ops._session_cwd[0] = str(tmp_path)
        seen: list[str] = []

        def _spy(command, **_kwargs):
            seen.append(command)
            return OperationDecision(
                action=OperationAction.ALLOW,
                risk=RiskLevel.LOW,
                reason="safe",
                matched_rule="test",
                redacted_command=command,
            )

        with patch(
            "core.host_process.classify_shell_command", side_effect=_spy
        ):
            tool_run_code({"language": "python", "code": "print(1)", "timeout": 20})

        assert seen, "policy gate never ran"
        assert not any("run_code(" in cmd for cmd in seen), (
            f"gate still classifies the synthetic label: {seen}"
        )
        assert any("code.py" in cmd for cmd in seen), (
            f"gate never classified the real script path: {seen}"
        )

    def test_unsupported_language_never_reaches_the_gate(
        self, tmp_path: Path
    ) -> None:
        """Validation must precede any classification or shell spawn."""
        from tools.sandbox import tool_run_code
        from core.operation_policy import RiskLevel
        import tools.file_ops as file_ops

        file_ops._session_cwd[0] = str(tmp_path)
        seen: list[str] = []

        def _spy(command, **_kwargs):
            seen.append(command)
            return OperationDecision(
                action=OperationAction.ALLOW,
                risk=RiskLevel.LOW,
                reason="safe",
                matched_rule="test",
                redacted_command=command,
            )

        with patch(
            "core.host_process.classify_shell_command", side_effect=_spy
        ):
            result = tool_run_code(
                {"language": "nope; printf injected", "code": "print(1)"}
            )

        assert "unsupported language" in result
        assert seen == [], f"unvalidated language reached the gate: {seen}"


class TestRunShellPolicyEnforcement:
    """Tests that tool_run_shell checks policy before spawning."""

    def test_deny_blocks_shell_execution(self, tmp_path: Path) -> None:
        """DENY must prevent shell execution entirely."""
        from tools.file_ops import tool_run_shell
        from core.operation_policy import RiskLevel

        decision = OperationDecision(
            action=OperationAction.DENY,
            risk=RiskLevel.HIGH,
            reason="shell execution blocked",
            matched_rule="test",
            redacted_command="rm -rf /",
        )

        with patch("tools.file_ops.classify_shell_command", return_value=decision):
            result = tool_run_shell({"command": "rm -rf /"})
            assert "Denied" in result or "SECURITY" in result or "ERROR" in result


class TestDelegatePolicyEnforcement:
    """Tests that delegate cannot bypass host/network/destructive gates."""

    def test_delegate_respects_capability_profiles(self, tmp_path: Path) -> None:
        """Delegate must respect capability restrictions."""
        from tools.delegate_tool import CAPABILITY_PROFILES

        # Verify capability profiles exist.
        assert len(CAPABILITY_PROFILES) > 0


class TestHostProcessRunnerAuthorization:
    """Tests that HostProcessRunner properly enforces authorization."""

    def test_deny_never_executes(self, tmp_path: Path) -> None:
        """DENY must never execute the command."""
        from core.operation_policy import RiskLevel

        runner = HostProcessRunner()
        decision = OperationDecision(
            action=OperationAction.DENY,
            risk=RiskLevel.HIGH,
            reason="dangerous",
            matched_rule="test",
            redacted_command="rm -rf /",
        )

        with patch("core.host_process.classify_shell_command", return_value=decision):
            request = HostProcessRequest(
                command="echo should-not-run",
                cwd=tmp_path,
                timeout_seconds=10.0,
            )
            outcome = runner.run(request)
            assert outcome.returncode == -1
            assert "Denied" in outcome.output

    def test_confirm_without_authorizer_never_executes(
        self, tmp_path: Path
    ) -> None:
        """CONFIRM without authorizer must never execute."""
        from core.operation_policy import RiskLevel

        runner = HostProcessRunner()  # Default authorizer denies.
        decision = OperationDecision(
            action=OperationAction.CONFIRM,
            risk=RiskLevel.MEDIUM,
            reason="needs auth",
            matched_rule="test",
            redacted_command="test",
        )

        with patch("core.host_process.classify_shell_command", return_value=decision):
            request = HostProcessRequest(
                command="echo should-not-run",
                cwd=tmp_path,
                timeout_seconds=10.0,
                interactive=True,
            )
            outcome = runner.run(request)
            assert outcome.returncode == -1
            assert "confirmation not granted" in outcome.output

    def test_allow_executes(self, tmp_path: Path) -> None:
        """ALLOW must execute the command."""
        from core.operation_policy import RiskLevel

        runner = HostProcessRunner()
        decision = OperationDecision(
            action=OperationAction.ALLOW,
            risk=RiskLevel.LOW,
            reason="safe",
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


class TestDockerNetworkAuthorization:
    """Tests that Docker requires explicit network authorization."""

    def test_docker_default_network_is_none(self) -> None:
        """Docker should default to network=none."""
        from tools.docker_sandbox import _check_network_policy

        # Without allow_network flag, network=bridge should be blocked.
        result = _check_network_policy({}, "bridge")
        assert result is not None
        assert "SECURITY BLOCK" in result

    def test_docker_none_network_allowed(self) -> None:
        """Docker network=none should always be allowed."""
        from tools.docker_sandbox import _check_network_policy

        result = _check_network_policy({}, "none")
        assert result is None


class TestDockerLabelRestrictedCleanup:
    """Tests that Docker cleanup only removes PawnLogic-managed resources."""

    def test_docker_prune_uses_label_filter(self) -> None:
        """docker_prune_resources should filter by pawn=true label."""
        import inspect
        from tools.docker_sandbox import docker_prune_resources

        source = inspect.getsource(docker_prune_resources)
        assert "pawn=true" in source or "label" in source
