"""Tests for external MCP startup configuration."""

import asyncio
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


def test_mcp_server_enabled_false_is_skipped():
    reason = mcp_client_manager._server_skip_reason("fetch", {"enabled": False})

    assert reason == "disabled by config (enabled=false)"


def test_legacy_fetch_uvx_is_skipped_by_default(monkeypatch):
    monkeypatch.delenv("PAWNLOGIC_MCP_ALLOW_NETWORK_INSTALL", raising=False)

    reason = mcp_client_manager._server_skip_reason(
        "fetch",
        {"command": "uvx", "args": ["mcp-server-fetch"]},
    )

    assert "may fetch from PyPI" in reason


def test_legacy_fetch_uvx_allows_explicit_network_install(monkeypatch):
    monkeypatch.delenv("PAWNLOGIC_MCP_ALLOW_NETWORK_INSTALL", raising=False)

    reason = mcp_client_manager._server_skip_reason(
        "fetch",
        {
            "command": "uvx",
            "args": ["mcp-server-fetch"],
            "allow_network_install": True,
        },
    )

    assert reason is None


def test_mcp_server_startup_timeout_defaults_and_clamps():
    assert mcp_client_manager._server_startup_timeout({}) == 15
    assert mcp_client_manager._server_startup_timeout({"startup_timeout": 0}) == 1
    assert mcp_client_manager._server_startup_timeout({"startup_timeout": "2.5"}) == 2.5


def test_mcp_stderr_log_path_sanitizes_server_name(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_client_manager, "MCP_STDERR_LOG_DIR", tmp_path)

    path = mcp_client_manager._mcp_stderr_log_path("../bad name")

    assert path == tmp_path / "bad_name.stderr.log"


def test_mcp_roots_callback_returns_cwd_and_workspace(monkeypatch, tmp_path):
    cwd = tmp_path / "project"
    home = tmp_path / "home"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(mcp_client_manager, "PAWNLOGIC_HOME", home)

    result = asyncio.run(mcp_client_manager._roots_cb(object()))
    uris = {str(root.uri) for root in result.roots}

    assert cwd.resolve().as_uri() in uris
    assert (home / "workspace").resolve().as_uri() in uris
