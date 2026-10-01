"""Contract tests for structured context construction."""

from __future__ import annotations

import pytest

from core.context_manager import (
    CONTEXT_STATE_VERSION,
    SUMMARY_VERSION,
    ContextManager,
    ContextState,
    context_state_from_messages,
    replace_context_state_message,
    without_context_state_messages,
)
from core.prompt_builder import (
    format_context_envelope_for_prompt,
    format_context_state_for_prompt,
)
from core.token_estimate import estimate_tokens


def test_context_state_round_trips_and_marks_old_summaries_stale():
    state = ContextState(
        goal="Ship structured context",
        constraints=("Keep message dictionaries stable",),
        facts=("The current helper ignores ctx_trim_tokens",),
        decisions=("Use one context construction interface",),
        artifacts=("reports/context.md",),
        failed_attempts=("Unbounded parent history",),
        open_questions=("How should retrieval attach later?",),
        current_phase="implementation",
        next_actions=("Add focused tests",),
    )

    assert ContextState.from_dict(state.to_dict()) == state
    assert state.version == CONTEXT_STATE_VERSION
    assert state.summary_version == SUMMARY_VERSION
    assert state.needs_summary_regeneration is False

    stale_data = state.to_dict()
    stale_data["summary_version"] = 0

    assert ContextState.from_dict(stale_data).needs_summary_regeneration is True


def test_structured_state_carrier_round_trips_through_existing_message_shape():
    state = ContextState(
        goal="Persist context",
        facts=("Verified fact",),
    )
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "goal"},
        {"role": "assistant", "content": "ack"},
    ]

    with_state = replace_context_state_message(messages, state)

    assert context_state_from_messages(with_state) == state
    assert with_state[3]["role"] == "assistant"
    assert with_state[3]["_pinned"] is True
    assert without_context_state_messages(with_state) == messages


def test_context_envelope_counts_message_content_reasoning_and_tool_data():
    messages = [
        {"role": "system", "content": "sys"},
        {
            "role": "assistant",
            "content": "answer",
            "reasoning_content": "reason",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path":"README.md"}',
                    },
                }
            ],
        },
        {"role": "tool", "content": "tool result", "tool_call_id": "call-1"},
    ]
    expected_tokens = sum(
        estimate_tokens(value)
        for value in (
            "sys",
            "answer",
            "reason",
            '{"path":"README.md"}',
            "tool result",
        )
    )

    envelope = ContextManager(
        max_tokens=expected_tokens,
        trim_tokens=expected_tokens - 1,
    ).build(messages)

    assert envelope.messages == tuple(messages)
    assert envelope.token_count == expected_tokens
    assert envelope.trimmed is False
    assert envelope.dropped_messages == 0


def test_overflow_trims_to_target_without_mutating_message_shapes():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "goal"},
        {"role": "assistant", "content": "ack"},
        {"role": "user", "content": "obsolete" * 10},
        {"role": "assistant", "content": "old"},
        {"role": "assistant", "content": "pin", "_pinned": True},
        {"role": "user", "content": "latest"},
        {"role": "assistant", "content": "done"},
    ]
    original = [dict(message) for message in messages]

    envelope = ContextManager(max_tokens=10, trim_tokens=7).build(messages)

    assert envelope.messages == (
        messages[0],
        messages[1],
        messages[2],
        messages[5],
        messages[6],
        messages[7],
    )
    assert envelope.token_count == 7
    assert envelope.token_count <= 7
    assert envelope.trimmed is True
    assert envelope.dropped_messages == 2
    assert messages == original
    assert all(
        set(selected) == set(original[messages.index(selected)])
        for selected in envelope.messages
    )


def test_parent_selection_is_deterministic_bounded_and_keeps_tool_groups():
    state = ContextState(goal="Review auth")
    messages = [
        {"role": "system", "content": "parent-only policy"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "ack"},
        {"role": "user", "content": "obsolete" * 20},
        {"role": "assistant", "content": "old"},
        {
            "role": "assistant",
            "content": "evidence",
            "_pinned": True,
            "_context_ref": "evidence:report",
        },
        {"role": "user", "content": "latest"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "content": "ok", "tool_call_id": "call-1"},
    ]
    manager = ContextManager(max_tokens=30, trim_tokens=27)

    first = manager.select_parent_context(
        messages,
        state=state,
        context_refs=("evidence:report",),
    )
    second = manager.select_parent_context(
        messages,
        state=state,
        context_refs=("evidence:report",),
    )

    assert first == second
    assert first.messages == (
        messages[1],
        messages[2],
        messages[5],
        messages[6],
        messages[7],
        messages[8],
    )
    assert first.token_count <= 27
    assert first.context_refs == ("evidence:report",)
    assert first.trimmed is True


def test_parent_context_modes_limit_inheritance():
    manager = ContextManager(max_tokens=30, trim_tokens=25)
    state = ContextState(goal="Parent goal", facts=("Verified fact",))
    messages = [
        {"role": "system", "content": "parent policy"},
        {"role": "user", "content": "parent task"},
    ]

    minimal = manager.select_parent_context(
        messages,
        state=state,
        context_mode="minimal",
    )
    none = manager.select_parent_context(
        messages,
        state=state,
        context_mode="none",
    )

    assert minimal.state.goal == state.goal
    assert minimal.state.facts == ()
    assert minimal.messages == ()
    assert minimal.token_count == estimate_tokens(minimal.state.prompt_block())
    assert none.state == ContextState()
    assert none.messages == ()
    assert none.token_count == 0
    with pytest.raises(ValueError, match="context_mode"):
        manager.select_parent_context(messages, context_mode="everything")


def test_protected_state_reports_over_budget_without_corruption():
    state = ContextState(goal="x" * 80)
    envelope = ContextManager(
        max_tokens=40,
        trim_tokens=4,
    ).select_parent_context((), state=state)

    assert envelope.state == state
    assert envelope.messages == ()
    assert envelope.token_count == estimate_tokens(state.prompt_block())
    assert envelope.over_budget is True


def test_context_build_repairs_dangling_tool_calls_without_rewriting_messages():
    messages = [
        {"role": "system", "content": "sys"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "missing",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        },
        {"role": "user", "content": "continue"},
    ]

    envelope = ContextManager(max_tokens=20, trim_tokens=16).build(messages)

    assert envelope.messages == (messages[0], messages[2])
    assert envelope.dropped_messages == 1
    assert messages[1]["tool_calls"][0]["id"] == "missing"


def test_pinned_tool_result_keeps_complete_atomic_call_group():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "anchor"},
        {"role": "assistant", "content": "ack"},
        {"role": "user", "content": "obsolete" * 20},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-a",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                },
                {
                    "id": "call-b",
                    "type": "function",
                    "function": {"name": "list_dir", "arguments": "{}"},
                },
            ],
        },
        {"role": "tool", "content": "a", "tool_call_id": "call-a"},
        {
            "role": "tool",
            "content": "b",
            "tool_call_id": "call-b",
            "_pinned": True,
        },
        {"role": "user", "content": "x" * 100},
    ]

    envelope = ContextManager(
        max_tokens=20,
        trim_tokens=12,
    ).build(messages)

    assert messages[4] in envelope.messages
    assert messages[5] in envelope.messages
    assert messages[6] in envelope.messages
    assert [
        message.get("tool_call_id")
        for message in envelope.messages
        if message.get("role") == "tool"
    ] == ["call-a", "call-b"]


def test_prompt_rendering_is_stable_bounded_and_redacts_credentials():
    state = ContextState(
        goal="Use OPENAI_API_KEY=sk-proj-" + ("x" * 32),
        facts=("Verified decision",),
    )
    envelope = ContextManager(
        max_tokens=200,
        trim_tokens=150,
    ).select_parent_context((), state=state)

    state_text = format_context_state_for_prompt(state)
    envelope_text = format_context_envelope_for_prompt(
        envelope,
        max_chars=80,
    )

    assert state_text.startswith("[Structured Context v1; summary v1]")
    assert "sk-proj-" not in state_text
    assert "[REDACTED_SECRET]" in state_text
    assert len(envelope_text) <= 80
