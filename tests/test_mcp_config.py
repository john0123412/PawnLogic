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
