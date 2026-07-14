"""Unit tests for explicit tool outcomes and deterministic batch execution."""

from core.session_tool_loop import TurnToolLoop
from core.tool_executor import ToolExecutionOutcome, ToolExecutionResult


def test_execution_result_exposes_explicit_outcome_without_message_change():
    result = ToolExecutionResult(
        tool_call_id="call-1",
        tool_name="write_file",
        content="OK: wrote file",
        metadata={"side_effect": True},
    )
    assert result.tool_message() == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "OK: wrote file",
    }
    assert result.outcome == ToolExecutionOutcome(
        status="success",
        content="OK: wrote file",
        error_type=None,
        side_effect=True,
    )


def test_turn_tool_loop_orders_calls_and_injects_plan_signal_last():
    events: list[str] = []

    def execute(index, call, tools):
        events.append(str(call["name"]))
        return tools, ToolExecutionOutcome("success", f"done-{index}")

    batch = TurnToolLoop().execute_batch(
        {2: {"name": "second"}, 1: {"name": "first"}},
        current_tools=None,
        execute_call=execute,
        plan_signal_injected=True,
        inject_plan_signal=lambda: events.append("PLAN_MISSING"),
    )
    assert events == ["first", "second", "PLAN_MISSING"]
    assert [outcome.content for outcome in batch.outcomes] == ["done-1", "done-2"]


def test_turn_tool_loop_guard_and_concurrency_are_pure():
    guard = TurnToolLoop.plan_guard(
        missing_required_plan=True,
        plan_rejected=0,
        max_soft=2,
    )
    assert guard.action == "soft"
    limited = TurnToolLoop.concurrency_limit([3, 1, 2], 2)
    assert limited.truncated is True
    assert limited.kept_keys == [1, 2]
