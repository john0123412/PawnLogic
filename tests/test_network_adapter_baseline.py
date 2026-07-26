"""Characterize current Docker and external MCP network-policy seams.

These tests intentionally stop at pure planning and startup-gate interfaces.
They use fakes and monkeypatches only; no Docker SDK, MCP subprocess, network,
or provider is started.
"""

from __future__ import annotations

from pathlib import Path

from core import mcp_client_manager
from core.network_policy import NetworkDecision
from core.operation_policy import OperationAction
from tools import docker_sandbox
from tools.docker_plan import build_docker_execution_plan


def _fake_resolve_image(image: str) -> str:
    return f"fake-image:{image}"


def _fake_command_error(_command: str) -> str | None:
    return None


def _docker_plan(args: dict[str, object]):
    return build_docker_execution_plan(
        args,
        resolve_image=_fake_resolve_image,
        network_error=docker_sandbox._check_network_policy,
        command_error=_fake_command_error,
    )


def test_docker_plan_defaults_to_no_network_without_sdk_access():
    plan, error = _docker_plan({"language": "python", "code": "print(1)"})

    assert error is None
    assert plan is not None
    assert plan.network == "none"
    assert plan.image == "fake-image:python"


def test_docker_bridge_and_host_require_explicit_allow_network():
    for mode in ("bridge", "host"):
        plan, error = _docker_plan(
            {"language": "python", "code": "print(1)", "network": mode}
        )

        assert plan is None
        assert error is not None
        assert f"network='{mode}'" in error
        assert "allow_network=true" in error


def test_docker_explicit_allow_network_preserves_bridge_and_host_modes():
    for mode in ("bridge", "host"):
        plan, error = _docker_plan(
            {
                "language": "python",
                "code": "print(1)",
                "network": mode,
                "allow_network": True,
            }
        )

        assert error is None
        assert plan is not None
        assert plan.network == mode


def test_docker_risky_network_is_rejected_before_client_lookup(monkeypatch):
    touched = False

    def fail_if_docker_is_touched():
        nonlocal touched
        touched = True
        raise AssertionError("Docker must not be touched by a rejected plan")

    monkeypatch.setattr(docker_sandbox, "_get_docker_client", fail_if_docker_is_touched)

    for mode in ("bridge", "host"):
        result = docker_sandbox.tool_run_code_docker(
            {"language": "python", "code": "print(1)", "network": mode}
        )

        assert result.startswith(f"SECURITY BLOCK: Docker network='{mode}'")

    assert touched is False


def test_docker_environment_policy_override_is_a_separate_current_gate(monkeypatch):
    monkeypatch.setenv("PAWNLOGIC_DOCKER_ALLOW_NETWORK", "true")

    assert docker_sandbox._check_network_policy({}, "bridge") is None
    assert docker_sandbox._check_network_policy({}, "host") is None


def test_docker_network_adapter_uses_noninteractive_capability_policy(monkeypatch):
    calls = []

    class RecordingPolicy:
        def evaluate(self, operation):
            calls.append(operation)
            return NetworkDecision(
                action=OperationAction.DENY,
                reason="test denial",
                rule="test",
                normalized_target="",
            )

    monkeypatch.setattr(docker_sandbox, "NetworkPolicy", RecordingPolicy)

    result = docker_sandbox._check_network_policy(
        {"allow_network": True}, "bridge"
    )

    assert result.startswith("SECURITY BLOCK: Docker network='bridge'")
    assert len(calls) == 1
    assert calls[0].capability_only is True
    assert calls[0].action == "container_network"
    assert calls[0].explicit_authorization is True
    assert calls[0].interactive is False


def test_legacy_fetch_mcp_requires_network_install_opt_in(monkeypatch):
    legacy = {"command": "uvx", "args": ["mcp-server-fetch"]}
    monkeypatch.delenv("PAWNLOGIC_MCP_ALLOW_NETWORK_INSTALL", raising=False)

    reason = mcp_client_manager._server_skip_reason("fetch", legacy)

    assert reason is not None
    assert "may fetch from PyPI" in reason


def test_legacy_fetch_mcp_accepts_config_or_environment_opt_in(monkeypatch):
    legacy = {"command": "uvx", "args": ["mcp-server-fetch"]}
    monkeypatch.delenv("PAWNLOGIC_MCP_ALLOW_NETWORK_INSTALL", raising=False)

    assert (
        mcp_client_manager._server_skip_reason(
            "fetch", {**legacy, "allow_network_install": True}
        )
        is None
    )

    monkeypatch.setenv("PAWNLOGIC_MCP_ALLOW_NETWORK_INSTALL", "1")
    assert mcp_client_manager._server_skip_reason("fetch", legacy) is None


def test_mcp_legacy_install_adapter_uses_noninteractive_capability_policy(monkeypatch):
    calls = []

    class RecordingPolicy:
        def evaluate(self, operation):
            calls.append(operation)
            return NetworkDecision(
                action=OperationAction.DENY,
                reason="test denial",
                rule="test",
                normalized_target="",
            )

    monkeypatch.setattr(mcp_client_manager, "NetworkPolicy", RecordingPolicy)

    reason = mcp_client_manager._server_skip_reason(
        "fetch",
        {"command": "uvx", "args": ["mcp-server-fetch"], "allow_network_install": True},
    )

    assert reason is not None
    assert "may fetch from PyPI" in reason
    assert len(calls) == 1
    assert calls[0].capability_only is True
    assert calls[0].action == "network_install"
    assert calls[0].explicit_authorization is True
    assert calls[0].interactive is False


def test_mcp_runtime_server_does_not_auto_authorize_network_capability(monkeypatch):
    calls = []

    class RecordingPolicy:
        def evaluate(self, operation):
            calls.append(operation)
            return NetworkDecision(
                action=OperationAction.DENY,
                reason="test denial",
                rule="test",
                normalized_target="",
            )

    monkeypatch.setattr(mcp_client_manager, "NetworkPolicy", RecordingPolicy)

    reason = mcp_client_manager._server_skip_reason(
        "other", {"command": "python", "args": ["server.py"]}
    )

    assert reason is None
    assert calls == []


def test_disabled_mcp_is_nonfatal_and_does_not_construct_manager(monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_ENABLED", "false")
    monkeypatch.setattr(mcp_client_manager, "_MCP_AVAILABLE", True)
    monkeypatch.setattr(mcp_client_manager, "_GLOBAL_MANAGER", None)

    class UnexpectedManager:
        def __init__(self, _config_path: Path):
            raise AssertionError("disabled MCP must not construct a manager")

    monkeypatch.setattr(mcp_client_manager, "MCPClientManager", UnexpectedManager)

    assert mcp_client_manager.init_external_mcp(tmp_path / "missing.json") is None
    assert mcp_client_manager.get_manager() is None


def test_missing_mcp_config_is_nonfatal_with_fake_manager(monkeypatch, tmp_path):
    monkeypatch.delenv("MCP_ENABLED", raising=False)
    monkeypatch.setattr(mcp_client_manager, "_MCP_AVAILABLE", True)
    monkeypatch.setattr(mcp_client_manager, "_GLOBAL_MANAGER", None)
    calls: list[str] = []

    class FakeManager:
        def __init__(self, config_path: Path):
            calls.append(f"construct:{config_path.name}")

        def start(self) -> bool:
            calls.append("start")
            return False

    monkeypatch.setattr(mcp_client_manager, "MCPClientManager", FakeManager)

    assert mcp_client_manager.init_external_mcp(tmp_path / "missing.json") is None
    assert calls == ["construct:missing.json", "start"]
    assert mcp_client_manager.get_manager() is None


def test_disabled_mcp_takes_precedence_over_missing_config(monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_ENABLED", "off")
    monkeypatch.setattr(mcp_client_manager, "_MCP_AVAILABLE", True)
    monkeypatch.setattr(mcp_client_manager, "_GLOBAL_MANAGER", None)
    starts: list[str] = []

    class FakeManager:
        def __init__(self, _config_path: Path):
            starts.append("constructed")

    monkeypatch.setattr(mcp_client_manager, "MCPClientManager", FakeManager)

    assert mcp_client_manager.init_external_mcp(tmp_path / "missing.json") is None
    assert starts == []
