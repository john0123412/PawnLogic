"""Failure-path tests for the external MCP client manager."""

from __future__ import annotations

import asyncio
import json
import threading

from core import mcp_client_manager


def test_startup_timeout_returns_false_and_logs(monkeypatch, tmp_path):
    config_path = tmp_path / "mcp_configs.json"
    config_path.write_text('{"mcpServers": {"slow": {"command": "slow"}}}', encoding="utf-8")
    monkeypatch.setattr(mcp_client_manager, "STARTUP_TIMEOUT", 0.01)
    logged = []
    monkeypatch.setattr(mcp_client_manager.logger, "error", lambda msg: logged.append(str(msg)))

    class NonStartingThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(mcp_client_manager.threading, "Thread", NonStartingThread)
    manager = mcp_client_manager.MCPClientManager(config_path)

    assert manager.start() is False
    assert any("startup timed out" in msg for msg in logged)


def test_startup_failure_returns_false_and_logs(monkeypatch, tmp_path):
    config_path = tmp_path / "mcp_configs.json"
    config_path.write_text('{"mcpServers": {"bad": {"command": "bad"}}}', encoding="utf-8")
    logged = []
    monkeypatch.setattr(mcp_client_manager.logger, "error", lambda msg: logged.append(str(msg)))

    class FailingThread:
        def __init__(self, *, target, **_kwargs):
            self._target = target

        def start(self):
            self._target()

    def fake_run_loop(self):
        self._start_error = RuntimeError("boom")
        self._failed.set()
        self._ready.set()

    monkeypatch.setattr(mcp_client_manager.threading, "Thread", FailingThread)
    monkeypatch.setattr(mcp_client_manager.MCPClientManager, "_run_loop", fake_run_loop)
    manager = mcp_client_manager.MCPClientManager(config_path)

    assert manager.start() is False
    assert any("startup crashed" in msg and "boom" in msg for msg in logged)


def test_connect_all_logs_server_timeout_and_failure(monkeypatch, tmp_path):
    config_path = tmp_path / "mcp_configs.json"
    config_path.write_text(
        json.dumps({
            "mcpServers": {
                "slow": {"command": "slow", "startup_timeout": 1},
                "bad": {"command": "bad", "startup_timeout": 1},
            }
        }),
        encoding="utf-8",
    )
    logged = []
    monkeypatch.setattr(mcp_client_manager.logger, "warning", lambda msg: logged.append(str(msg)))

    async def fake_connect_one(_self, name, _conf):
        if name == "slow":
            raise asyncio.TimeoutError()
        raise RuntimeError("startup failed")

    async def fake_wait_for(coro, timeout):
        del timeout
        return await coro

    monkeypatch.setattr(mcp_client_manager.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(mcp_client_manager.MCPClientManager, "_connect_one", fake_connect_one)
    manager = mcp_client_manager.MCPClientManager(config_path)

    asyncio.run(manager._connect_all())

    assert any("server 'slow' INIT TIMEOUT" in msg for msg in logged)
    assert any("server 'bad' INIT FAILED" in msg for msg in logged)


def test_stderr_log_truncation_keeps_latest_bytes(tmp_path):
    path = tmp_path / "server.stderr.log"
    path.write_bytes(b"a" * 20 + b"latest")

    mcp_client_manager._truncate_stderr_log(path, max_bytes=6)

    content = path.read_bytes()
    assert content.startswith(b"[stderr truncated; keeping latest bytes]\n")
    assert content.endswith(b"latest")


def test_resolve_roots_skips_invalid_and_missing_candidates(monkeypatch, tmp_path):
    cwd = tmp_path / "project"
    cwd.mkdir()
    home = tmp_path / "home"
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(mcp_client_manager, "PAWNLOGIC_HOME", home)

    original_resolve = mcp_client_manager.Path.resolve

    def flaky_resolve(self, *args, **kwargs):
        if self == home / "workspace":
            raise OSError("invalid root")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(mcp_client_manager.Path, "resolve", flaky_resolve)

    roots = mcp_client_manager._resolve_roots()

    assert roots == [cwd.resolve()]


def test_mcp_enabled_false_keeps_global_manager_unconstructed(monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_ENABLED", "false")
    monkeypatch.setattr(mcp_client_manager, "_MCP_AVAILABLE", True)
    monkeypatch.setattr(mcp_client_manager, "_GLOBAL_MANAGER", None)
    constructed = threading.Event()

    class Manager:
        def __init__(self, _config_path):
            constructed.set()

    monkeypatch.setattr(mcp_client_manager, "MCPClientManager", Manager)

    assert mcp_client_manager.init_external_mcp(tmp_path / "mcp_configs.json") is None
    assert constructed.is_set() is False
