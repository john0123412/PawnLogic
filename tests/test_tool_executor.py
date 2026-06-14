"""Tests for tool execution data contracts."""

from core.tool_executor import ToolExecutionContext, ToolExecutionResult


def test_tool_execution_context_exposes_short_session_label():
    context = ToolExecutionContext(
        session_id="1234567890abcdef",
        model_alias="test-model",
        iteration=2,
        current_phase="RECON",
        user_mode=True,
    )

    assert context.session_label == "12345678"
    assert context.model_alias == "test-model"
    assert context.iteration == 2
    assert context.current_phase == "RECON"
    assert context.user_mode is True
    assert context.debug_mode is False


def test_tool_execution_result_defaults_are_success_oriented():
    result = ToolExecutionResult(
        tool_call_id="call_1",
        tool_name="read_file",
        content="ok",
    )

    assert result.audit_ok is True
    assert result.elapsed_ms == 0
    assert result.args_preview == ""
    assert result.failure_warning == ""
    assert result.error_type == ""
    assert result.metadata == {}


def test_tool_execution_result_metadata_is_not_shared():
    first = ToolExecutionResult("call_1", "run_shell", "one")
    second = ToolExecutionResult("call_2", "run_shell", "two")

    first.metadata["exit_code"] = 1

    assert second.metadata == {}


def test_tool_execution_result_builds_tool_message_shape():
    result = ToolExecutionResult(
        tool_call_id="call_abc",
        tool_name="run_shell",
        content="done",
        audit_ok=False,
        elapsed_ms=12,
    )

    assert result.tool_message() == {
        "role": "tool",
        "tool_call_id": "call_abc",
        "content": "done",
    }
