"""Tests for tool execution helpers and data contracts."""

import pytest

from core.tool_executor import (
    ToolExecutionContext,
    ToolExecutionResult,
    execute_tool_handler,
    result_has_semantic_failure,
)


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


def test_result_has_semantic_failure_matches_existing_signals():
    assert result_has_semantic_failure("ERROR: failed") is True
    assert result_has_semantic_failure("command not found") is True
    assert result_has_semantic_failure("all good") is False


def test_execute_tool_handler_calls_handler_and_records_elapsed_time():
    context = ToolExecutionContext("session123", "model", 0, "RECON")
    ticks = iter([10.0, 10.123])

    result = execute_tool_handler(
        tool_call_id="call_1",
        tool_name="run_shell",
        fn_args={"command": "echo ok"},
        handler=lambda args: f"ran {args['command']}",
        context=context,
        args_preview="command='echo ok'",
        clock=lambda: next(ticks),
    )

    assert result.content == "ran echo ok"
    assert result.audit_ok is True
    assert result.elapsed_ms == 122
    assert result.args_preview == "command='echo ok'"


def test_execute_tool_handler_marks_unknown_tool_as_failed():
    context = ToolExecutionContext("session123", "model", 0, "RECON")

    result = execute_tool_handler(
        tool_call_id="call_missing",
        tool_name="missing_tool",
        fn_args={},
        handler=None,
        context=context,
        clock=lambda: 1.0,
    )

    assert result.content == "ERROR: Unknown tool 'missing_tool'"
    assert result.audit_ok is False
    assert result.elapsed_ms == 0


def test_execute_tool_handler_marks_semantic_failure_without_exception():
    context = ToolExecutionContext("session123", "model", 0, "RECON")

    result = execute_tool_handler(
        tool_call_id="call_fail",
        tool_name="run_shell",
        fn_args={},
        handler=lambda _args: "Segmentation fault",
        context=context,
        clock=lambda: 1.0,
    )

    assert result.content == "Segmentation fault"
    assert result.audit_ok is False


def test_execute_tool_handler_formats_exception_for_developer_mode():
    context = ToolExecutionContext("session123", "model", 0, "RECON")

    def broken(_args):
        raise ValueError("bad input")

    result = execute_tool_handler(
        tool_call_id="call_error",
        tool_name="broken",
        fn_args={},
        handler=broken,
        context=context,
        clock=lambda: 1.0,
    )

    assert result.content == "ERROR: ValueError: bad input"
    assert result.audit_ok is False


def test_execute_tool_handler_uses_user_mode_error_formatter():
    context = ToolExecutionContext("session123", "model", 0, "RECON", user_mode=True)

    def broken(_args):
        raise RuntimeError("secret detail")

    result = execute_tool_handler(
        tool_call_id="call_error",
        tool_name="broken",
        fn_args={},
        handler=broken,
        context=context,
        user_error_formatter=lambda raw: f"friendly: {raw.split(':', 1)[0]}",
        clock=lambda: 1.0,
    )

    assert result.content == "friendly: ERROR"
    assert result.audit_ok is False


def test_execute_tool_handler_does_not_catch_keyboard_interrupt():
    context = ToolExecutionContext("session123", "model", 0, "RECON")

    def interrupted(_args):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        execute_tool_handler(
            tool_call_id="call_interrupt",
            tool_name="interrupt",
            fn_args={},
            handler=interrupted,
            context=context,
        )
