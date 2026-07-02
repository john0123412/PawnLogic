from __future__ import annotations

from core.turn_state import TurnState


def test_turn_state_default_initialization_fields():
    state = TurnState.for_turn(
        max_iter=12,
        max_tokens=2048,
        is_vision_model=False,
        current_tools=None,
    )

    assert state.max_iter == 12
    assert state.current_max_tokens == 2048
    assert state.current_tools is None
    assert state.is_vision_model is False
    assert state.iteration == 0
    assert state.plan_rejected == 0
    assert state.logic_refresh_interval == 20
    assert state.urgent_mode_active is False


def test_turn_state_vision_turn_caps_initial_tokens():
    state = TurnState.for_turn(
        max_iter=3,
        max_tokens=8192,
        is_vision_model=True,
        current_tools=None,
    )

    assert state.current_max_tokens == 4096
    assert state.is_vision_model is True


def test_turn_state_plan_rejected_can_increment_or_replace():
    state = TurnState.for_turn(
        max_iter=3,
        max_tokens=2048,
        is_vision_model=False,
        current_tools=None,
    )

    state.increment_plan_rejected()
    state.increment_plan_rejected()
    assert state.plan_rejected == 2

    state.replace_plan_rejected(0)
    assert state.plan_rejected == 0


def test_turn_state_current_tools_accepts_none_or_schema_list():
    schema = [{"type": "function", "function": {"name": "read_file"}}]
    state = TurnState.for_turn(
        max_iter=3,
        max_tokens=2048,
        is_vision_model=False,
        current_tools=None,
    )

    state.update_tools(schema)
    assert state.current_tools == schema

    state.update_tools(None)
    assert state.current_tools is None


def test_turn_state_current_max_tokens_can_update():
    state = TurnState.for_turn(
        max_iter=3,
        max_tokens=8192,
        is_vision_model=False,
        current_tools=None,
    )

    state.update_max_tokens(4096)

    assert state.current_max_tokens == 4096


def test_turn_state_new_turn_does_not_carry_previous_mutations():
    first = TurnState.for_turn(
        max_iter=3,
        max_tokens=8192,
        is_vision_model=False,
        current_tools=[{"function": {"name": "run_shell"}}],
    )
    first.set_iteration(2)
    first.replace_plan_rejected(2)
    first.update_tools(None)
    first.mark_urgent_mode()

    second = TurnState.for_turn(
        max_iter=5,
        max_tokens=2048,
        is_vision_model=False,
        current_tools=[{"function": {"name": "read_file"}}],
    )

    assert second.max_iter == 5
    assert second.current_max_tokens == 2048
    assert second.current_tools == [{"function": {"name": "read_file"}}]
    assert second.iteration == 0
    assert second.plan_rejected == 0
    assert second.urgent_mode_active is False
