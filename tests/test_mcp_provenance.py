"""Tests for MCP tool-result provenance (issue #177.1).

Every MCP tool result must carry an attestation binding it to the server
that produced it: a model-visible header line plus structured provenance
in the result envelope metadata.
"""

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.mcp_client_manager import (
    MCPClientManager,
    MCPToolProvenance,
    _ProvenancedStr,
)
from core.tool_executor import ToolExecutionContext, execute_tool_handler


def _manager() -> MCPClientManager:
    # No servers started; _attest_result only needs config_path + the dict.
    return MCPClientManager(Path("/nonexistent/mcp_configs.json"))


def _context() -> ToolExecutionContext:
    return ToolExecutionContext("session123", "model", 0, "RECON")


class _FakeMCPSession:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, tool_name: str, args: dict) -> object:
        self.calls.append((tool_name, args))
        return self.result


class _FailingMCPSession:
    async def call_tool(self, tool_name: str, args: dict) -> object:
        raise RuntimeError("fake server failure")


def _async_mcp_handler(mgr: MCPClientManager, server: str, tool_name: str):
    def handler(args: dict) -> object:
        return asyncio.run(mgr._call_async(server, tool_name, args))

    return handler


def test_provenance_header_is_model_visible():
    mgr = _manager()
    attested = mgr._attest_result("tavily", "tavily-search", "some result text")

    assert isinstance(attested, str)
    assert isinstance(attested, _ProvenancedStr)
    first_line = attested.splitlines()[0]
    assert first_line.startswith("[MCP provenance:")
    assert "server=tavily" in first_line
    assert "transport=stdio" in first_line
    assert "call_id=" in first_line
    assert attested.endswith("some result text")


def test_provenance_binds_content_hash():
    mgr = _manager()
    text = "result body"
    attested = mgr._attest_result("srv", "tool", text)

    prov = attested.provenance
    assert isinstance(prov, MCPToolProvenance)
    assert prov.server == "srv"
    assert prov.tool_name == "tool"
    assert prov.transport == "stdio"
    assert len(prov.call_id) == 16
    assert all(c in "0123456789abcdef" for c in prov.call_id)
    assert prov.content_sha256 == hashlib.sha256(text.encode()).hexdigest()
    assert prov.config_sha256 == "unavailable"  # no config file in test
    assert prov.server_command_sha256 == "unavailable"  # not registered


def test_provenance_call_ids_are_unique():
    mgr = _manager()
    a = mgr._attest_result("srv", "tool", "x")
    b = mgr._attest_result("srv", "tool", "x")
    assert a.provenance.call_id != b.provenance.call_id


def test_provenance_survives_executor_into_metadata():
    mgr = _manager()

    def handler(args):
        return mgr._attest_result("tavily", "tavily-search", "answer")

    result = execute_tool_handler(
        tool_call_id="call_1",
        tool_name="tavily__tavily-search",
        fn_args={},
        handler=handler,
        context=_context(),
    )

    assert "[MCP provenance:" in result.content
    assert result.content.endswith("answer")
    prov = result.metadata.get("mcp_provenance")
    assert prov is not None
    assert prov["server"] == "tavily"
    assert prov["transport"] == "stdio"
    assert len(prov["content_sha256"]) == 64


def test_provenance_survives_watchdog_path():
    mgr = _manager()

    def handler(args):
        return mgr._attest_result("srv", "tool", "answer")

    result = execute_tool_handler(
        tool_call_id="call_1",
        tool_name="srv__tool",
        fn_args={},
        handler=handler,
        context=_context(),
        hard_timeout_seconds=5,
    )

    assert "[MCP provenance:" in result.content
    assert result.metadata.get("mcp_provenance", {}).get("server") == "srv"


@pytest.mark.parametrize("is_error", [False, True])
def test_call_async_server_results_attest_and_reach_executor_metadata(is_error: bool):
    mgr = _manager()
    session = _FakeMCPSession(
        SimpleNamespace(
            content=[SimpleNamespace(type="text", text="server body")],
            isError=is_error,
        )
    )
    mgr._sessions["srv"] = session
    mgr.discovered_tools["srv__tool"] = {
        "timeout": 1,
        "server_command_sha256": "command-hash",
    }

    direct = asyncio.run(mgr._call_async("srv", "tool", {"q": "x"}))
    expected_body = (
        "[MCP tool error from srv] server body" if is_error else "server body"
    )
    assert isinstance(direct, _ProvenancedStr)
    assert direct.endswith(expected_body)
    assert direct.provenance.server == "srv"

    result = execute_tool_handler(
        tool_call_id="call_1",
        tool_name="srv__tool",
        fn_args={"q": "x"},
        handler=_async_mcp_handler(mgr, "srv", "tool"),
        context=_context(),
    )

    assert result.content.endswith(expected_body)
    provenance = result.metadata.get("mcp_provenance")
    assert provenance is not None
    assert provenance["server"] == "srv"
    assert provenance["tool_name"] == "tool"
    assert provenance["content_sha256"] == hashlib.sha256(
        expected_body.encode()
    ).hexdigest()
    assert session.calls == [("tool", {"q": "x"}), ("tool", {"q": "x"})]


@pytest.mark.parametrize("failing_session", [False, True])
def test_call_async_manager_errors_do_not_gain_provenance(failing_session: bool):
    mgr = _manager()
    server = "srv"
    if failing_session:
        mgr._sessions[server] = _FailingMCPSession()

    result = execute_tool_handler(
        tool_call_id="call_1",
        tool_name="srv__tool",
        fn_args={},
        handler=_async_mcp_handler(mgr, server, "tool"),
        context=_context(),
    )

    assert result.content.startswith("[MCP]")
    assert "mcp_provenance" not in result.metadata


def test_plain_results_gain_no_provenance_metadata():
    result = execute_tool_handler(
        tool_call_id="call_1",
        tool_name="run_shell",
        fn_args={},
        handler=lambda args: "plain output",
        context=_context(),
    )

    assert result.content == "plain output"
    assert "mcp_provenance" not in result.metadata
