import sys

import pytest

from core.operation_policy import OperationAction, RiskLevel
from tools import file_ops


@pytest.fixture
def shell_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(file_ops, "_session_cwd", [str(workspace)])
    monkeypatch.setattr(file_ops, "_session_workspace_dir", [str(workspace)])
    monkeypatch.setattr(file_ops, "_emit_run_shell_warning", lambda: None)
    monkeypatch.setattr(file_ops, "_get_shell_env", lambda: {})
    return workspace


def _set_tty(monkeypatch, value: bool) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: value, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: value, raising=False)


def _install_fake_popen(monkeypatch):
    calls = []

    class FakeProc:
        returncode = 0

        def communicate(self, timeout=None):
            return b"ok\n", b""

        def terminate(self):
            return None

        def kill(self):
            return None

    def fake_popen(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeProc()

    monkeypatch.setattr(file_ops.subprocess, "Popen", fake_popen)
    return calls


def _install_fake_interactive_popen(monkeypatch):
    calls = []

    class FakeStdout:
        def __init__(self):
            self._chunks = [b"interactive ok\n", b""]

        def read(self, _size):
            if self._chunks:
                return self._chunks.pop(0)
            return b""

    class FakeStdin:
        def __init__(self):
            self.writes = []

        def write(self, data):
            self.writes.append(data)

        def flush(self):
            return None

    class FakeProc:
        def __init__(self):
            self.stdin = FakeStdin()
            self.stdout = FakeStdout()

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            return None

    def fake_popen(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeProc()

    monkeypatch.setattr(file_ops.subprocess, "Popen", fake_popen)
    return calls


def _capture_policy_audit(monkeypatch):
    records = []

    def fake_audit(decision, *, operation_type, cwd, interactive):
        records.append(
            {
                "decision": decision,
                "operation_type": operation_type,
                "cwd": cwd,
                "interactive": interactive,
            }
        )

    monkeypatch.setattr(file_ops, "audit_operation_decision", fake_audit)
    return records


def test_run_shell_low_risk_allows_before_popen(shell_workspace, monkeypatch):
    _set_tty(monkeypatch, False)
    monkeypatch.setattr(sys, "argv", ["pawn"])
    calls = _install_fake_popen(monkeypatch)
    audits = _capture_policy_audit(monkeypatch)

    output = file_ops._run("echo ok", cwd=str(shell_workspace), env={})

    assert output == "ok\n"
    assert len(calls) == 1
    decision = audits[0]["decision"]
    assert decision.action == OperationAction.ALLOW
    assert decision.risk == RiskLevel.LOW


def test_run_shell_high_risk_non_tty_fails_closed(shell_workspace, tmp_path, monkeypatch):
    _set_tty(monkeypatch, False)
    monkeypatch.setattr(sys, "argv", ["pawn"])
    calls = _install_fake_popen(monkeypatch)
    audits = _capture_policy_audit(monkeypatch)
    outside = tmp_path / "outside.txt"

    output = file_ops._run(f"echo ok > {outside}", cwd=str(shell_workspace), env={})

    assert "SECURITY BLOCK" in output
    assert "confirmation unavailable" in output.lower()
    assert calls == []
    decision = audits[0]["decision"]
    assert decision.action == OperationAction.DENY
    assert decision.risk == RiskLevel.HIGH


def test_run_shell_high_risk_eval_mode_fails_closed_even_with_tty(
    shell_workspace,
    tmp_path,
    monkeypatch,
):
    _set_tty(monkeypatch, True)
    monkeypatch.setattr(sys, "argv", ["pawn", "--eval", "write outside"])
    calls = _install_fake_popen(monkeypatch)
    outside = tmp_path / "outside.txt"

    output = file_ops._run(f"echo ok > {outside}", cwd=str(shell_workspace), env={})

    assert "SECURITY BLOCK" in output
    assert calls == []


def test_run_shell_high_risk_interactive_confirmation_allows(
    shell_workspace,
    tmp_path,
    monkeypatch,
):
    _set_tty(monkeypatch, True)
    monkeypatch.setattr(sys, "argv", ["pawn"])
    calls = _install_fake_popen(monkeypatch)
    audits = _capture_policy_audit(monkeypatch)
    prompted = []

    def fake_prompt(decision):
        prompted.append(decision)
        return True

    monkeypatch.setattr(file_ops, "prompt_for_confirmation", fake_prompt)
    outside = tmp_path / "outside.txt"

    output = file_ops._run(f"echo ok > {outside}", cwd=str(shell_workspace), env={})

    assert output == "ok\n"
    assert len(calls) == 1
    assert prompted
    decision = audits[0]["decision"]
    assert decision.action == OperationAction.CONFIRM
    assert decision.risk == RiskLevel.HIGH


def test_run_shell_critical_sensitive_path_denies_before_popen(
    shell_workspace,
    monkeypatch,
):
    _set_tty(monkeypatch, True)
    monkeypatch.setattr(sys, "argv", ["pawn"])
    calls = _install_fake_popen(monkeypatch)
    audits = _capture_policy_audit(monkeypatch)

    output = file_ops._run("cat ~/.pawnlogic/.env", cwd=str(shell_workspace), env={})

    assert "SECURITY BLOCK" in output
    assert "critical" in output.lower()
    assert calls == []
    decision = audits[0]["decision"]
    assert decision.action == OperationAction.DENY
    assert decision.risk == RiskLevel.CRITICAL


def test_run_shell_critical_docker_socket_denies_before_popen(
    shell_workspace,
    monkeypatch,
):
    _set_tty(monkeypatch, True)
    monkeypatch.setattr(sys, "argv", ["pawn"])
    calls = _install_fake_popen(monkeypatch)

    output = file_ops._run("stat /var/run/docker.sock", cwd=str(shell_workspace), env={})

    assert "SECURITY BLOCK" in output
    assert "docker" in output.lower()
    assert calls == []


def test_run_shell_dangerous_patterns_are_not_direct_blocklist(
    shell_workspace,
    monkeypatch,
):
    _set_tty(monkeypatch, False)
    monkeypatch.setattr(sys, "argv", ["pawn"])
    calls = _install_fake_popen(monkeypatch)
    audits = _capture_policy_audit(monkeypatch)

    output = file_ops._run("sudo echo ok", cwd=str(shell_workspace), env={})

    assert output == "ok\n"
    assert len(calls) == 1
    decision = audits[0]["decision"]
    assert decision.action == OperationAction.ALLOW
    assert decision.risk == RiskLevel.MEDIUM
    assert decision.matched_rule.startswith("misuse_pattern:")


def test_run_shell_policy_audit_uses_redacted_command(
    shell_workspace,
    tmp_path,
    monkeypatch,
):
    _set_tty(monkeypatch, False)
    monkeypatch.setattr(sys, "argv", ["pawn"])
    _install_fake_popen(monkeypatch)
    audits = _capture_policy_audit(monkeypatch)
    secret = "sk-proj-abcdefghijklmnop"
    outside = tmp_path / "outside.txt"

    output = file_ops._run(
        f"OPENAI_API_KEY={secret} echo password=hunter2 > {outside}",
        cwd=str(shell_workspace),
        env={},
    )

    assert "SECURITY BLOCK" in output
    redacted = audits[0]["decision"].redacted_command
    assert secret not in redacted
    assert "hunter2" not in redacted
    assert "<redacted>" in redacted


def test_run_interactive_low_risk_allows_before_popen(shell_workspace, monkeypatch):
    _set_tty(monkeypatch, False)
    monkeypatch.setattr(sys, "argv", ["pawn"])
    calls = _install_fake_interactive_popen(monkeypatch)
    audits = _capture_policy_audit(monkeypatch)

    output = file_ops.tool_run_interactive(
        {"command": "echo ok", "inputs": [], "timeout": 1, "cwd": str(shell_workspace)}
    )

    assert "interactive ok" in output
    assert len(calls) == 1
    decision = audits[0]["decision"]
    assert audits[0]["operation_type"] == "run_interactive"
    assert decision.action == OperationAction.ALLOW
    assert decision.risk == RiskLevel.LOW


def test_run_interactive_high_risk_non_tty_fails_closed(
    shell_workspace,
    tmp_path,
    monkeypatch,
):
    _set_tty(monkeypatch, False)
    monkeypatch.setattr(sys, "argv", ["pawn"])
    calls = _install_fake_interactive_popen(monkeypatch)
    audits = _capture_policy_audit(monkeypatch)
    outside = tmp_path / "outside.txt"

    output = file_ops.tool_run_interactive(
        {
            "command": f"echo ok > {outside}",
            "inputs": [],
            "timeout": 1,
            "cwd": str(shell_workspace),
        }
    )

    assert "SECURITY BLOCK" in output
    assert "confirmation unavailable" in output.lower()
    assert calls == []
    decision = audits[0]["decision"]
    assert audits[0]["operation_type"] == "run_interactive"
    assert decision.action == OperationAction.DENY
    assert decision.risk == RiskLevel.HIGH


def test_run_interactive_critical_sensitive_path_denies_before_popen(
    shell_workspace,
    monkeypatch,
):
    _set_tty(monkeypatch, True)
    monkeypatch.setattr(sys, "argv", ["pawn"])
    calls = _install_fake_interactive_popen(monkeypatch)
    audits = _capture_policy_audit(monkeypatch)

    output = file_ops.tool_run_interactive(
        {
            "command": "cat ~/.pawnlogic/.env",
            "inputs": [],
            "timeout": 1,
            "cwd": str(shell_workspace),
        }
    )

    assert "SECURITY BLOCK" in output
    assert calls == []
    decision = audits[0]["decision"]
    assert audits[0]["operation_type"] == "run_interactive"
    assert decision.action == OperationAction.DENY
    assert decision.risk == RiskLevel.CRITICAL


def test_run_interactive_policy_audit_uses_redacted_command(
    shell_workspace,
    tmp_path,
    monkeypatch,
):
    _set_tty(monkeypatch, False)
    monkeypatch.setattr(sys, "argv", ["pawn"])
    _install_fake_interactive_popen(monkeypatch)
    audits = _capture_policy_audit(monkeypatch)
    secret = "sk-proj-abcdefghijklmnop"
    outside = tmp_path / "outside.txt"

    output = file_ops.tool_run_interactive(
        {
            "command": f"OPENAI_API_KEY={secret} echo password=hunter2 > {outside}",
            "inputs": [],
            "timeout": 1,
            "cwd": str(shell_workspace),
        }
    )

    assert "SECURITY BLOCK" in output
    redacted = audits[0]["decision"].redacted_command
    assert audits[0]["operation_type"] == "run_interactive"
    assert secret not in redacted
    assert "hunter2" not in redacted
    assert "<redacted>" in redacted
