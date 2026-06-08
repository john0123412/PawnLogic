"""Tests for external MCP startup configuration."""

from pathlib import Path

from core import mcp_client_manager


def test_mcp_enabled_false_skips_manager_start(monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "false")
    monkeypatch.setattr(mcp_client_manager, "_MCP_AVAILABLE", True)
    monkeypatch.setattr(mcp_client_manager, "_GLOBAL_MANAGER", None)

    class FailingManager:
        def __init__(self, config_path: Path):
            raise AssertionError("MCPClientManager should not be constructed when disabled")

    monkeypatch.setattr(mcp_client_manager, "MCPClientManager", FailingManager)

    assert mcp_client_manager.init_external_mcp() is None


def test_mcp_env_defaults_to_minimal_scrubbed_parent(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "~")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("CUSTOM_TOKEN", "token-secret")
    monkeypatch.setenv("APP_MODE", "dev")

    env = mcp_client_manager._build_mcp_env({"env": {"EXPLICIT": "${APP_MODE}"}})

    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "~"
    assert env["EXPLICIT"] == "dev"
    assert "APP_MODE" not in env
    assert "OPENAI_API_KEY" not in env
    assert "CUSTOM_TOKEN" not in env


def test_mcp_env_inherit_uses_scrubbed_parent(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("APP_MODE", "dev")
    monkeypatch.setenv("GH_TOKEN", "gh-secret")

    env = mcp_client_manager._build_mcp_env({"inherit_env": True})

    assert env["PATH"] == "/usr/bin"
    assert env["APP_MODE"] == "dev"
    assert "GH_TOKEN" not in env


def test_mcp_env_overrides_are_deliberate_even_when_sensitive(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-parent")

    env = mcp_client_manager._build_mcp_env(
        {"env": {"OPENAI_API_KEY": "${OPENAI_API_KEY}"}}
    )

    assert env["OPENAI_API_KEY"] == "sk-parent"
