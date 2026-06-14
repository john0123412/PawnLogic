"""Tests for delegate capability profiles and unified tool execution."""

import pytest

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


# ── capability profiles ──────────────────────────────────────────────


def test_inherited_profile_keeps_all_but_delegate():
    allowed = resolve_allowed_tools("inherited", _ALL_TOOLS)
    assert "delegate_task" not in allowed
    assert allowed == set(_ALL_TOOLS) - {"delegate_task"}


def test_read_only_profile_excludes_shell_and_writes():
    allowed = resolve_allowed_tools("read_only", _ALL_TOOLS)
    for denied in ("run_shell", "run_code", "write_file", "patch_file", "git_op"):
        assert denied not in allowed
    for kept in ("read_file", "list_dir", "find_files", "web_search"):
        assert kept in allowed


def test_no_shell_profile_excludes_only_execution():
    allowed = resolve_allowed_tools("no_shell", _ALL_TOOLS)
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
    executor = _make_sub_executor({"echo": lambda args: f"got {args.get('x')}"}.get)
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
    executor = _make_sub_executor({}.get)
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

    executor = _make_sub_executor({"boom": boom}.get)
    result = executor.execute_handler(
        tool_call_id="c1",
        tool_name="boom",
        fn_args={},
        context=_ctx(),
    )
    assert "kaboom" in result.content
    assert result.audit_ok is False


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
