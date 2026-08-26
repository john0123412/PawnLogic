"""Tests for tool execution helpers and data contracts."""

import pytest

from core.tool_executor import (
    ToolExecutor,
    ToolExecutionContext,
    ToolExecutionResult,
    classify_tool_failure,
    execute_phase_switch,
    execute_tool_handler,
    precheck_tool_failures,
    preview_tool_arguments,
    record_tool_failure,
    result_has_semantic_failure,
    resolve_tool_arguments,
)
from core.tool_registry import ToolRegistry, ToolSpec
from core.trust import TrustBoundaryKind


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


def test_resolve_tool_arguments_prefers_preparsed_hybrid_args():
    args = {"path": "x.py"}

    assert resolve_tool_arguments({"args": "{}", "_args_parsed": args}) is args


def test_resolve_tool_arguments_loads_json_args():
    assert resolve_tool_arguments({"args": '{"path": "/tmp"}'}) == {"path": "/tmp"}


def test_resolve_tool_arguments_retries_after_bom_prefix():
    assert resolve_tool_arguments({"args": "\ufeff{\"path\": \"/tmp\"}"}) == {
        "path": "/tmp"
    }


def test_resolve_tool_arguments_preserves_raw_invalid_json():
    assert resolve_tool_arguments({"args": "{bad"}) == {"_raw_args": "{bad"}


def test_preview_tool_arguments_matches_session_preview_format():
    preview = preview_tool_arguments(
        {"command": "echo hello", "long": "x" * 80}
    )

    assert preview == "command='echo hello', long='xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


def test_classify_tool_failure_uses_existing_heuristic_order():
    assert classify_tool_failure("TimeoutExpired after 10s") == "Timeout"
    assert classify_tool_failure("Segmentation fault") == "Segfault"
    assert classify_tool_failure("Compile failed") == "CompileError"
    assert classify_tool_failure("MemoryError") == "MemoryError"
    assert classify_tool_failure("SyntaxError") == "SyntaxError"
    assert classify_tool_failure("NameError") == "LogicError"
    assert classify_tool_failure("ModuleNotFoundError") == "MissingModule"
    assert classify_tool_failure("command not found") == "NotFound"
    assert classify_tool_failure("PermissionError") == "Permission"
    assert classify_tool_failure("panic") == "Panic"
    assert classify_tool_failure("exit 139") == "Crash"
    assert classify_tool_failure("Traceback") == "PythonError"
    assert classify_tool_failure("ERROR: bad") == "RuntimeError"
    assert classify_tool_failure("failed") == "UnknownFailure"


def test_precheck_tool_failures_skips_non_audited_tool():
    called = False

    def check_failure_func(*_args, **_kwargs):
        nonlocal called
        called = True
        return []

    result = precheck_tool_failures(
        tool_name="read_file",
        args_preview="path='x'",
        is_audited=False,
        check_failure_func=check_failure_func,
        format_failures_func=lambda rows: str(rows),
    )

    assert result.warning == ""
    assert result.failure_count == 0
    assert called is False


def test_precheck_tool_failures_formats_history_rows():
    rows = [{"error_type": "Timeout"}, {"error_type": "Timeout"}]

    result = precheck_tool_failures(
        tool_name="run_shell",
        args_preview="command='./target'",
        is_audited=True,
        check_failure_func=lambda *args, **kwargs: rows,
        format_failures_func=lambda found: f"warning: {len(found)}",
    )

    assert result.warning == "warning: 2"
    assert result.failure_count == 2


def test_precheck_tool_failures_swallows_lookup_errors():
    def broken_lookup(*_args, **_kwargs):
        raise RuntimeError("db unavailable")

    result = precheck_tool_failures(
        tool_name="run_shell",
        args_preview="command='./target'",
        is_audited=True,
        check_failure_func=broken_lookup,
        format_failures_func=lambda rows: str(rows),
    )

    assert result.warning == ""
    assert result.failure_count == 0


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


def test_record_tool_failure_skips_successful_or_non_audited_results():
    calls = []

    result = record_tool_failure(
        tool_name="read_file",
        args_preview="path='x'",
        content="ERROR: ignored",
        audit_ok=True,
        is_audited=True,
        session_id="session123",
        write_failure_func=lambda **kwargs: calls.append(kwargs),
        count_failure_func=lambda _tool, _error: 0,
        sink_failure_func=lambda **_kwargs: (False, ""),
    )

    assert result.recorded is False
    assert calls == []

    result = record_tool_failure(
        tool_name="read_file",
        args_preview="path='x'",
        content="ERROR: ignored",
        audit_ok=False,
        is_audited=False,
        session_id="session123",
        write_failure_func=lambda **kwargs: calls.append(kwargs),
        count_failure_func=lambda _tool, _error: 0,
        sink_failure_func=lambda **_kwargs: (False, ""),
    )

    assert result.recorded is False
    assert calls == []


def test_record_tool_failure_writes_failure_and_sinks_repeated_error():
    writes = []
    sinks = []

    result = record_tool_failure(
        tool_name="run_shell",
        args_preview="command='./target'",
        content="Segmentation fault with long detail",
        audit_ok=False,
        is_audited=True,
        session_id="session123",
        write_failure_func=lambda **kwargs: writes.append(kwargs) or "fid-1",
        count_failure_func=lambda tool_name, error_type: 3,
        sink_failure_func=lambda **kwargs: sinks.append(kwargs) or (True, "sunk"),
    )

    assert result.recorded is True
    assert result.failure_id == "fid-1"
    assert result.error_type == "Segfault"
    assert result.gsa_sunk is True
    assert result.gsa_message == "sunk"
    assert writes == [
        {
            "tool_name": "run_shell",
            "args_summary": "command='./target'",
            "error_msg": "Segmentation fault with long detail",
            "error_type": "Segfault",
            "session_id": "session123",
        }
    ]
    assert sinks == [
        {
            "tool_name": "run_shell",
            "error_type": "Segfault",
            "error_msg": "Segmentation fault with long detail",
            "args_preview": "command='./target'",
        }
    ]


def test_record_tool_failure_preserves_error_type_when_write_fails():
    result = record_tool_failure(
        tool_name="run_shell",
        args_preview="command='./target'",
        content="ERROR: bad",
        audit_ok=False,
        is_audited=True,
        session_id="session123",
        write_failure_func=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("db")),
        count_failure_func=lambda _tool, _error: 3,
        sink_failure_func=lambda **_kwargs: (True, "sunk"),
    )

    assert result.error_type == "RuntimeError"
    assert result.recorded is False
    assert result.gsa_sunk is False


def _make_tool_executor(**overrides) -> ToolExecutor:
    defaults = {
        "resolve_tool": lambda _name: None,
        "agent_phases": {"RECON": ["read_file"], "EXPLOIT": ["run_shell"]},
        "schema_snapshot": lambda: [_schema("read_file"), _schema("run_shell")],
        "check_failure_func": lambda *_args, **_kwargs: [],
        "format_failures_func": lambda rows: f"warning: {len(rows)}",
        "write_failure_func": lambda **_kwargs: "fid-1",
        "count_failure_func": lambda _tool, _error: 0,
        "sink_failure_func": lambda **_kwargs: (False, ""),
        "user_error_formatter": None,
    }
    defaults.update(overrides)
    return ToolExecutor(**defaults)


def test_tool_executor_runs_complete_external_tool_spec_by_default():
    calls = []

    def handler(args):
        calls.append(args)
        return f"custom_tool:{args['value']}"

    spec = ToolSpec(
        name="custom_tool",
        handler=handler,
        schema=_schema("custom_tool"),
        trust=TrustBoundaryKind.BROWSER_NETWORK,
        capabilities=frozenset({"external", "network"}),
    )
    executor = _make_tool_executor(
        resolve_tool=lambda name: (spec, "mcp:example")
        if name == "custom_tool"
        else None,
    )

    result = executor.execute_handler(
        tool_call_id="call_1",
        tool_name="custom_tool",
        fn_args={"value": "ok"},
        context=ToolExecutionContext("session123", "model", 0, "RECON"),
    )

    assert result.content == "custom_tool:ok"
    assert result.audit_ok is True
    assert calls == [{"value": "ok"}]


def test_tool_executor_does_not_invoke_handler_without_complete_tool_spec():
    registry = ToolRegistry()
    calls = []

    def pending_external_handler(args):
        calls.append(args)
        return "unexpected remote call"

    # The legacy adapter can hold a handler before its matching schema creates
    # a complete ToolSpec. That handler must never cross the host execution
    # boundary.
    registry.register("pending_external", pending_external_handler)
    executor = _make_tool_executor(
        resolve_tool=registry.resolve_for_execution,
    )

    result = executor.execute_handler(
        tool_call_id="call_pending",
        tool_name="pending_external",
        fn_args={"target": "remote"},
        context=ToolExecutionContext("session123", "model", 0, "RECON"),
    )

    assert result.content == "ERROR: Unknown tool 'pending_external'"
    assert result.audit_ok is False
    assert calls == []


def test_tool_executor_passes_spec_and_owner_to_policy_before_handler():
    registry = ToolRegistry()
    calls = []
    seen = []

    def handler(args):
        calls.append(args)
        return "unexpected remote call"

    spec = ToolSpec(
        name="mcp_network_tool",
        handler=handler,
        schema=_schema("mcp_network_tool"),
        trust=TrustBoundaryKind.BROWSER_NETWORK,
        capabilities=frozenset({"external", "network"}),
    )
    registry.register_many_owned("mcp:example", [spec])

    def reject(spec, owner, arguments, context):
        seen.append((spec, owner, arguments, context))
        return "host approval required"

    executor = _make_tool_executor(
        resolve_tool=registry.resolve_for_execution,
        execution_policy=reject,
    )
    context = ToolExecutionContext("session123", "model", 0, "RECON")
    result = executor.execute_handler(
        tool_call_id="call_mcp",
        tool_name="mcp_network_tool",
        fn_args={"target": "remote"},
        context=context,
    )

    assert result.content == (
        "ERROR: Tool 'mcp_network_tool' blocked by execution policy: "
        "host approval required"
    )
    assert result.error_type == "ToolExecutionPolicyDenied"
    assert calls == []
    assert seen == [(spec, "mcp:example", {"target": "remote"}, context)]


def test_tool_executor_fails_closed_when_execution_policy_raises():
    calls = []

    def handler(args):
        calls.append(args)
        return "unexpected tool call"

    spec = ToolSpec(
        name="guarded_tool",
        handler=handler,
        schema=_schema("guarded_tool"),
    )

    def broken_policy(*_args):
        raise RuntimeError("unavailable")

    executor = _make_tool_executor(
        resolve_tool=lambda _name: (spec, "extension:example"),
        execution_policy=broken_policy,
    )
    result = executor.execute_handler(
        tool_call_id="call_guarded",
        tool_name="guarded_tool",
        fn_args={},
        context=ToolExecutionContext("session123", "model", 0, "RECON"),
    )

    assert result.content == (
        "ERROR: Tool 'guarded_tool' blocked because execution policy failed."
    )
    assert result.error_type == "ToolExecutionPolicyError"
    assert calls == []


def test_tool_executor_does_not_invoke_spec_without_an_owner():
    calls = []

    def handler(args):
        calls.append(args)
        return "unexpected tool call"

    spec = ToolSpec(
        name="ownerless_tool",
        handler=handler,
        schema=_schema("ownerless_tool"),
    )
    executor = _make_tool_executor(
        resolve_tool=lambda _name: (spec, ""),
    )
    result = executor.execute_handler(
        tool_call_id="call_ownerless",
        tool_name="ownerless_tool",
        fn_args={},
        context=ToolExecutionContext("session123", "model", 0, "RECON"),
    )

    assert result.error_type == "ToolMetadataError"
    assert calls == []


def test_tool_executor_execute_phase_switch_uses_schema_snapshot():
    executor = _make_tool_executor(
        schema_snapshot=lambda: [
            _schema("run_shell"),
            _schema("switch_phase"),
        ],
    )

    result = executor.execute_phase_switch(
        fn_args={"phase": "exploit", "reason": "next"},
        current_phase="RECON",
    )

    assert result.switched is True
    assert [schema["function"]["name"] for schema in result.active_tools] == [
        "run_shell",
        "switch_phase",
    ]


def test_tool_executor_precheck_and_record_failure_delegate_dependencies():
    rows = [{"error_type": "Timeout"}]
    writes = []
    executor = _make_tool_executor(
        check_failure_func=lambda *_args, **_kwargs: rows,
        write_failure_func=lambda **kwargs: writes.append(kwargs) or "fid-2",
    )

    precheck = executor.precheck_failures(
        tool_name="run_shell",
        args_preview="command='./target'",
        is_audited=True,
    )
    record = executor.record_failure(
        tool_name="run_shell",
        args_preview="command='./target'",
        content="ERROR: failed",
        audit_ok=False,
        is_audited=True,
        session_id="session123",
    )

    assert precheck.warning == "warning: 1"
    assert precheck.failure_count == 1
    assert record.recorded is True
    assert record.failure_id == "fid-2"
    assert writes[0]["error_type"] == "RuntimeError"


def _schema(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}


def test_execute_phase_switch_returns_next_phase_tools():
    phases = {"RECON": ["read_file"], "EXPLOIT": ["run_shell"]}
    schemas = [_schema("read_file"), _schema("run_shell"), _schema("switch_phase")]

    result = execute_phase_switch(
        fn_args={"phase": "exploit", "reason": "need shell"},
        current_phase="RECON",
        agent_phases=phases,
        schemas=schemas,
    )

    assert result.switched is True
    assert result.old_phase == "RECON"
    assert result.target_phase == "EXPLOIT"
    assert result.reason == "need shell"
    assert [schema["function"]["name"] for schema in result.active_tools] == [
        "run_shell",
        "switch_phase",
    ]
    assert result.available_tool_names == {"run_shell"}
    assert "[Phase Switch] RECON → EXPLOIT" in result.content
    assert "Reason: need shell" in result.content
    assert "Reload: 2 tools active." in result.content


def test_execute_phase_switch_reports_unknown_phase_without_active_tools():
    phases = {"RECON": ["read_file"]}

    result = execute_phase_switch(
        fn_args={"phase": "missing"},
        current_phase="RECON",
        agent_phases=phases,
        schemas=[_schema("read_file")],
    )

    assert result.switched is False
    assert result.old_phase == "RECON"
    assert result.target_phase == "MISSING"
    assert result.reason == "(no reason provided)"
    assert result.active_tools == []
    assert result.content == "ERROR: Unknown phase 'MISSING'. Available: RECON"


def test_execute_tool_handler_watchdog_abandons_hung_handler():
    """A handler stuck past the hard deadline must not block the agent loop."""
    import time

    context = ToolExecutionContext(
        session_id="1234567890abcdef",
        model_alias="test-model",
        iteration=0,
        current_phase="GENERAL",
    )
    started = time.monotonic()

    result = execute_tool_handler(
        tool_call_id="call_hang",
        tool_name="run_shell",
        fn_args={},
        handler=lambda _args: time.sleep(5),
        context=context,
        hard_timeout_seconds=0.2,
    )
    elapsed = time.monotonic() - started

    assert elapsed < 4, f"watchdog did not return promptly ({elapsed:.1f}s)"
    assert result.audit_ok is False
    assert "watchdog" in result.content.lower()
    assert "run_shell" in result.content
    # classify_tool_failure must label the abandoned call as a timeout.
    assert classify_tool_failure(result.content) == "Timeout"


def test_execute_tool_handler_watchdog_returns_fast_result_unchanged():
    context = ToolExecutionContext(
        session_id="1234567890abcdef",
        model_alias="test-model",
        iteration=0,
        current_phase="GENERAL",
    )

    result = execute_tool_handler(
        tool_call_id="call_fast",
        tool_name="read_file",
        fn_args={},
        handler=lambda _args: "file body",
        context=context,
        hard_timeout_seconds=5.0,
    )

    assert result.audit_ok is True
    assert result.content == "file body"


def test_execute_tool_handler_watchdog_relays_handler_exception():
    def _boom(_args):
        raise ValueError("handler exploded")

    context = ToolExecutionContext(
        session_id="1234567890abcdef",
        model_alias="test-model",
        iteration=0,
        current_phase="GENERAL",
    )

    result = execute_tool_handler(
        tool_call_id="call_err",
        tool_name="run_shell",
        fn_args={},
        handler=_boom,
        context=context,
        hard_timeout_seconds=5.0,
    )

    assert result.audit_ok is False
    assert "ValueError" in result.content


def test_tool_executor_passes_hard_timeout_to_handler_execution():
    def _hang(_args):
        import time

        time.sleep(30)

    spec = ToolSpec(
        name="run_shell",
        handler=_hang,
        schema=_schema("run_shell"),
        trust=TrustBoundaryKind.HOST_SHELL,
    )

    executor = _make_tool_executor(
        resolve_tool=lambda name: (spec, "core") if name == "run_shell" else None,
        hard_timeout_seconds=0.2,
    )
    context = ToolExecutionContext("session123", "model", 0, "RECON")

    result = executor.execute_handler(
        tool_call_id="call_x",
        tool_name="run_shell",
        fn_args={},
        context=context,
    )

    assert result.audit_ok is False
    assert "watchdog" in result.content.lower()


def test_execute_tool_handler_watchdog_defaults_to_runtime_config(monkeypatch):
    """Without an explicit limit the watchdog reads tool_watchdog_sec."""
    import time

    monkeypatch.setattr(
        "core.state.runtime_config",
        lambda: {"tool_watchdog_sec": 0.2},
    )
    context = ToolExecutionContext("session123", "model", 0, "RECON")

    result = execute_tool_handler(
        tool_call_id="call_cfg",
        tool_name="run_shell",
        fn_args={},
        handler=lambda _args: time.sleep(5),
        context=context,
    )

    assert result.audit_ok is False
    assert "watchdog" in result.content.lower()
