"""Tests for delegate capability profiles and unified tool execution."""

from types import SimpleNamespace

import pytest

from core.agent_orchestrator import CancellationToken
import core.delegation_runtime as delegation_runtime
from core.tool_registry import ToolRegistry, ToolSpec
import tools.delegate_tool as delegate_tool
from tools.delegate_tool import (
    CAPABILITY_PROFILES,
    resolve_allowed_tools,
    tool_allowed,
    _make_sub_executor,
)

_ALL_TOOLS = [
    "read_file",
    "list_dir",
    "find_files",
    "web_search",
    "write_file",
    "patch_file",
    "git_op",
    "run_shell",
    "run_code",
    "run_interactive",
    "delegate_task",
]
_CAPABILITIES = {
    "write_file": {"mutating"},
    "patch_file": {"mutating"},
    "git_op": {"mutating"},
    "run_shell": {"shell"},
    "run_code": {"shell"},
    "run_interactive": {"shell"},
}


def _schema(name):
    return {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {"type": "object"},
        },
    }


def _complete_tool_resolver(handlers, *, owner="builtin"):
    registry = ToolRegistry()
    registry.register_many_owned(
        owner,
        [
            ToolSpec(name=name, handler=handler, schema=_schema(name))
            for name, handler in handlers.items()
        ],
    )
    return registry.resolve_for_execution


# ── capability profiles ──────────────────────────────────────────────


def test_inherited_profile_keeps_all_but_delegate():
    allowed = resolve_allowed_tools("inherited", _ALL_TOOLS)
    assert "delegate_task" not in allowed
    assert allowed == set(_ALL_TOOLS) - {"delegate_task"}


def test_read_only_profile_excludes_shell_and_writes():
    allowed = resolve_allowed_tools(
        "read_only", _ALL_TOOLS, capabilities_by_name=_CAPABILITIES
    )
    for denied in ("run_shell", "run_code", "write_file", "patch_file", "git_op"):
        assert denied not in allowed
    for kept in ("read_file", "list_dir", "find_files", "web_search"):
        assert kept in allowed


def test_no_shell_profile_excludes_only_execution():
    allowed = resolve_allowed_tools(
        "no_shell", _ALL_TOOLS, capabilities_by_name=_CAPABILITIES
    )
    assert "run_shell" not in allowed
    assert "run_code" not in allowed
    # Writes are still permitted under no_shell.
    assert "write_file" in allowed
    assert "patch_file" in allowed


def test_custom_profile_uses_allowlist():
    allowed = resolve_allowed_tools(
        "custom", _ALL_TOOLS, allowlist=["read_file", "run_shell"]
    )
    assert allowed == {"read_file", "run_shell"}


def test_custom_profile_cannot_allow_delegate():
    allowed = resolve_allowed_tools(
        "custom", _ALL_TOOLS, allowlist=["delegate_task", "read_file"]
    )
    assert "delegate_task" not in allowed
    assert allowed == {"read_file"}


def test_explicit_allowlist_intersects_inherited_profile():
    allowed = resolve_allowed_tools(
        "inherited",
        _ALL_TOOLS,
        allowlist=["read_file", "run_shell", "delegate_task"],
    )

    assert allowed == {"read_file", "run_shell"}


def test_no_profile_ever_permits_nested_delegation():
    for profile in CAPABILITY_PROFILES:
        assert (
            tool_allowed("delegate_task", profile, allowlist=["delegate_task"]) is False
        )


def test_unknown_profile_defaults_to_inherited_behaviour():
    # tool_allowed treats unknown profiles as inherited (permissive) but
    # _SubAgentSession normalises unknown profiles to "inherited".
    sub = delegate_tool._SubAgentSession("task", "m", capability="bogus")
    assert sub.capability == "inherited"


# ── unified execution via ToolExecutor ───────────────────────────────


def test_sub_executor_runs_known_tool():
    executor = _make_sub_executor(
        _complete_tool_resolver(
            {"echo": lambda args: f"got {args.get('x')}"},
        )
    )
    ctx = _ctx()
    result = executor.execute_handler(
        tool_call_id="c1",
        tool_name="echo",
        fn_args={"x": 5},
        context=ctx,
    )
    assert result.content == "got 5"
    assert result.audit_ok is True


def test_sub_executor_unknown_tool_matches_main_loop_envelope():
    executor = _make_sub_executor(lambda _name: None)
    result = executor.execute_handler(
        tool_call_id="c1",
        tool_name="ghost",
        fn_args={},
        context=_ctx(),
    )
    assert result.content == "ERROR: Unknown tool 'ghost'"
    assert result.audit_ok is False


def test_sub_executor_catches_tool_exception():
    def boom(_args):
        raise ValueError("kaboom")

    executor = _make_sub_executor(_complete_tool_resolver({"boom": boom}))
    result = executor.execute_handler(
        tool_call_id="c1",
        tool_name="boom",
        fn_args={},
        context=_ctx(),
    )
    assert "kaboom" in result.content
    assert result.audit_ok is False


def test_sub_executor_does_not_invoke_handler_without_complete_tool_spec():
    registry = ToolRegistry()
    calls = []

    def pending_handler(args):
        calls.append(args)
        return "unexpected remote call"

    registry.register("pending_external", pending_handler)
    executor = _make_sub_executor(registry.resolve_for_execution)
    result = executor.execute_handler(
        tool_call_id="c_pending",
        tool_name="pending_external",
        fn_args={"target": "remote"},
        context=_ctx(),
    )

    assert result.content == "ERROR: Unknown tool 'pending_external'"
    assert result.audit_ok is False
    assert calls == []


def test_subagent_token_budget_is_shared_across_provider_iterations(monkeypatch):
    requested_limits = []
    echo_handler = lambda args: args["value"]
    resolver = _complete_tool_resolver({"echo": echo_handler})
    responses = iter(
        [
            SimpleNamespace(
                error=None,
                usage={"prompt_tokens": 4, "completion_tokens": 3},
                tool_calls={
                    0: {
                        "id": "call-1",
                        "name": "echo",
                        "args": '{"value":"ok"}',
                    }
                },
                text="",
            ),
            SimpleNamespace(
                error=None,
                usage={"prompt_tokens": 6, "completion_tokens": 2},
                tool_calls={},
                text="done",
            ),
        ]
    )
    monkeypatch.setattr(
        delegation_runtime,
        "_tool_map",
        lambda: {"echo": echo_handler},
    )
    monkeypatch.setattr(
        delegation_runtime,
        "_tools_schema",
        lambda: [{"function": {"name": "echo"}}],
    )
    monkeypatch.setattr(delegation_runtime, "_tool_capabilities", lambda: {})
    monkeypatch.setattr(
        delegation_runtime,
        "_tool_execution_resolver",
        lambda: resolver,
    )
    monkeypatch.setattr(
        delegation_runtime,
        "runtime_config",
        lambda: {"max_tokens": 100, "tool_max_chars": 6000},
    )

    def fake_stream(_messages, _model, *, tools_schema, max_tokens):
        assert tools_schema == [{"function": {"name": "echo"}}]
        requested_limits.append(max_tokens)
        return object()

    monkeypatch.setattr(delegation_runtime, "stream_request", fake_stream)
    monkeypatch.setattr(
        delegation_runtime,
        "consume_model_stream",
        lambda *_args, **_kwargs: next(responses),
    )

    sub = delegation_runtime.SubAgentSession(
        "finish a bounded task",
        "worker",
        context_mode="none",
        max_tokens=5,
    )

    assert sub.run() == "done"
    assert requested_limits == [5, 2]
    assert sub.completion_tokens == 5
    assert sub.prompt_tokens == 10
    assert sub.tool_calls == 1


def test_subagent_rejects_pending_handler_before_the_handler_runs(monkeypatch):
    calls = []

    def pending_handler(args):
        calls.append(args)
        return "unexpected remote call"

    registry = ToolRegistry()
    registry.register("pending_external", pending_handler)
    responses = iter(
        [
            SimpleNamespace(
                error=None,
                usage={"prompt_tokens": 1, "completion_tokens": 1},
                tool_calls={
                    0: {
                        "id": "call-pending",
                        "name": "pending_external",
                        "args": '{"target":"remote"}',
                    }
                },
                text="",
            ),
            SimpleNamespace(
                error=None,
                usage={"prompt_tokens": 1, "completion_tokens": 1},
                tool_calls={},
                text="done",
            ),
        ]
    )
    monkeypatch.setattr(
        delegation_runtime,
        "_tool_map",
        lambda: {"pending_external": pending_handler},
    )
    monkeypatch.setattr(
        delegation_runtime,
        "_tools_schema",
        lambda: [_schema("pending_external")],
    )
    monkeypatch.setattr(delegation_runtime, "_tool_capabilities", lambda: {})
    monkeypatch.setattr(
        delegation_runtime,
        "_tool_execution_resolver",
        lambda: registry.resolve_for_execution,
    )
    monkeypatch.setattr(
        delegation_runtime,
        "runtime_config",
        lambda: {"max_tokens": 100, "tool_max_chars": 6000},
    )
    monkeypatch.setattr(
        delegation_runtime,
        "stream_request",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        delegation_runtime,
        "consume_model_stream",
        lambda *_args, **_kwargs: next(responses),
    )

    sub = delegation_runtime.SubAgentSession(
        "do not invoke incomplete tools",
        "worker",
        context_mode="none",
    )

    assert sub.run() == "done"
    assert calls == []
    assert sub.messages[-1]["content"] == "ERROR: Unknown tool 'pending_external'"


def test_subagent_stops_before_tools_when_completion_budget_is_exhausted(
    monkeypatch,
):
    executed = []
    monkeypatch.setattr(
        delegation_runtime,
        "_tool_map",
        lambda: {"echo": lambda args: executed.append(args)},
    )
    monkeypatch.setattr(
        delegation_runtime,
        "_tools_schema",
        lambda: [{"function": {"name": "echo"}}],
    )
    monkeypatch.setattr(delegation_runtime, "_tool_capabilities", lambda: {})
    monkeypatch.setattr(
        delegation_runtime,
        "runtime_config",
        lambda: {"max_tokens": 100, "tool_max_chars": 6000},
    )
    monkeypatch.setattr(
        delegation_runtime,
        "stream_request",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        delegation_runtime,
        "consume_model_stream",
        lambda *_args, **_kwargs: SimpleNamespace(
            error=None,
            usage={"prompt_tokens": 1, "completion_tokens": 3},
            tool_calls={
                0: {
                    "id": "call-1",
                    "name": "echo",
                    "args": '{"value":"must-not-run"}',
                }
            },
            text="",
        ),
    )
    sub = delegation_runtime.SubAgentSession(
        "do not exceed the budget",
        "worker",
        context_mode="none",
        max_tokens=3,
    )

    assert sub.run() == "[Sub-agent budget exhausted] max_tokens=3"
    assert sub.status == "budget_exhausted"
    assert sub.failures[0].code == "token_budget_exhausted"
    assert executed == []
    assert sub.tool_calls == 0


def test_subagent_stops_before_provider_request_when_host_is_cancelled(
    monkeypatch,
):
    token = CancellationToken()
    token.cancel("parent stopped")
    monkeypatch.setattr(delegation_runtime, "_tool_map", lambda: {})
    monkeypatch.setattr(delegation_runtime, "_tools_schema", lambda: [])
    monkeypatch.setattr(delegation_runtime, "_tool_capabilities", lambda: {})
    monkeypatch.setattr(
        delegation_runtime,
        "stream_request",
        lambda *_args, **_kwargs: pytest.fail(
            "a cancelled delegated task must not call a provider"
        ),
    )

    sub = delegation_runtime.SubAgentSession(
        "stop before calling a provider",
        "worker",
        context_mode="none",
    )
    sub.cancellation = token

    assert sub.run() == "[Sub-agent cancelled] parent stopped"
    assert sub.status == "cancelled"
    assert sub.failures[0].code == "cancelled"


def _ctx():
    from core.tool_executor import ToolExecutionContext

    return ToolExecutionContext(
        session_id="sub_test",
        model_alias="m",
        iteration=0,
        current_phase="GENERAL",
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
