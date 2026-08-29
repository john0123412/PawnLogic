"""Tests for the CoT plan guard's read-only exemption behavior."""

from core.plan_guard import (
    MAX_PLAN_ONLY_RECOVERIES,
    PLAN_EXEMPT_TOOLS,
    is_plan_only_response,
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


def test_complete_plan_only_response_requires_recovery():
    assert MAX_PLAN_ONLY_RECOVERIES > 0
    assert is_plan_only_response(
        "\n<plan><intent>Continue the pending command.</intent></plan>\n", {}
    )


def test_plan_only_detection_does_not_capture_final_text_or_tool_calls():
    plan = "<plan><intent>Continue the pending command.</intent></plan>"

    assert is_plan_only_response(f"{plan}\nThe command completed.", {}) is False
    assert is_plan_only_response("I will explain how plans work: " + plan, {}) is False
    assert is_plan_only_response(f"{plan}\nVisible text\n{plan}", {}) is False
    assert is_plan_only_response("<plan><intent>Incomplete", {}) is False
    assert is_plan_only_response(plan, _calls("run_shell")) is False


def test_web_retrieval_tools_are_plan_exempt():
    """Information retrieval has no local side effects, like check_service."""
    assert "web_search" in PLAN_EXEMPT_TOOLS
    assert "web_fetch" in PLAN_EXEMPT_TOOLS
    assert is_plan_exempt(_calls("web_search", "search_skills"))
    assert tool_call_missing_plan("no plan text", _calls("web_fetch")) is False


def test_web_tools_still_require_plan_when_mixed_with_side_effects():
    assert tool_call_missing_plan(
        "no plan text", _calls("web_search", "run_shell")
    ) is True


def test_with_plan_notice_appends_only_when_flagged():
    from core.plan_guard import TOOL_PLAN_NOTICE, with_plan_notice

    assert with_plan_notice("result body", flagged=False) == "result body"
    noticed = with_plan_notice("result body", flagged=True)
    assert noticed.startswith("result body\n\n")
    assert noticed.endswith(TOOL_PLAN_NOTICE)


def test_plan_signals_never_claim_interception():
    """Soft mode really executes tools; the signal must not contradict that."""
    from core.session import _PLAN_MISSING_SIGNAL
    from core.plan_guard import TOOL_PLAN_NOTICE

    for text in (_PLAN_MISSING_SIGNAL, TOOL_PLAN_NOTICE):
        assert "intercept" not in text.lower()
        assert "<plan>" in text
        assert "current provider's tool interface" in text
        assert "only a plan" in text
