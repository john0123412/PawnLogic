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


def test_turn_tool_loop_skips_remaining_calls_after_a_safe_point_claim():
    executed: list[str] = []
    skipped: list[str] = []
    safe_point_calls = 0

    def execute(index, call, tools):
        executed.append(str(call["id"]))
        return tools, ToolExecutionOutcome("success", f"done-{index}")

    def claim_safe_point() -> bool:
        nonlocal safe_point_calls
        safe_point_calls += 1
        return safe_point_calls == 1

    def skip_call(index, call):
        skipped.append(str(call["id"]))
        return ToolExecutionOutcome(
            "skipped",
            f"tool call {call['id']} skipped after steering",
        )

    batch = TurnToolLoop().execute_batch(
        {
            1: {"id": "call-1", "name": "first"},
            2: {"id": "call-2", "name": "second"},
        },
        current_tools=None,
        execute_call=execute,
        plan_signal_injected=False,
        inject_plan_signal=lambda: None,
        claim_safe_point=claim_safe_point,
        skip_call=skip_call,
    )

    assert executed == ["call-1"]
    assert skipped == ["call-2"]
    assert [outcome.status for outcome in batch.outcomes] == ["success", "skipped"]


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


def test_turn_tool_loop_closes_interrupted_and_unstarted_tool_pairs():
    executed: list[str] = []
    interrupted: list[str] = []
    skipped: list[str] = []
    cancelled = False

    def execute(index, call, tools):
        nonlocal cancelled
        executed.append(str(call["id"]))
        cancelled = True
        raise KeyboardInterrupt

    def interrupt_call(index, call):
        interrupted.append(str(call["id"]))
        return ToolExecutionOutcome(
            "interrupted",
            f"interrupted {call['id']}",
            side_effect=True,
        )

    def skip_call(index, call):
        skipped.append(str(call["id"]))
        return ToolExecutionOutcome("skipped", f"skipped {call['id']}")

    batch = TurnToolLoop().execute_batch(
        {
            1: {"id": "call-1", "name": "first"},
            2: {"id": "call-2", "name": "second"},
            3: {"id": "call-3", "name": "third"},
        },
        current_tools=None,
        execute_call=execute,
        plan_signal_injected=False,
        inject_plan_signal=lambda: None,
        cancellation_check=lambda: cancelled,
        interrupt_call=interrupt_call,
        skip_call=skip_call,
    )

    assert executed == ["call-1"]
    assert interrupted == ["call-1"]
    assert skipped == ["call-2", "call-3"]
    assert [outcome.status for outcome in batch.outcomes] == [
        "interrupted",
        "skipped",
        "skipped",
    ]
