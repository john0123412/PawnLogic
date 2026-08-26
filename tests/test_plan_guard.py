"""Tests for the CoT plan guard's read-only exemption behavior."""

from core.plan_guard import (
    PLAN_EXEMPT_TOOLS,
    is_plan_exempt,
    tool_call_missing_plan,
)


def _calls(*names: str) -> dict:
    return {i: {"name": name, "args": "{}"} for i, name in enumerate(names)}


def test_read_file_tools_are_plan_exempt():
    """Read-only file exploration must not require a <plan> block."""
    assert "read_file" in PLAN_EXEMPT_TOOLS
    assert "read_file_lines" in PLAN_EXEMPT_TOOLS
    assert is_plan_exempt(_calls("list_dir", "read_file", "read_file_lines"))
    assert tool_call_missing_plan("no plan text", _calls("read_file")) is False


def test_side_effect_tool_without_plan_is_flagged():
    assert tool_call_missing_plan("no plan text", _calls("run_shell")) is True


def test_mixed_calls_still_require_plan():
    """One side-effect call in the batch forces the plan requirement."""
    assert (
        tool_call_missing_plan("no plan text", _calls("read_file", "run_shell")) is True
    )


def test_plan_present_satisfies_guard_for_any_tool():
    text = "<plan><intent>x</intent></plan> rest"
    assert tool_call_missing_plan(text, _calls("run_shell")) is False


def test_empty_tool_buffer_never_requires_plan():
    assert tool_call_missing_plan("", {}) is False
