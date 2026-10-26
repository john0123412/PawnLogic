"""Tests for model stream consumption during a turn."""

from __future__ import annotations

import pytest

from core.turn_api import consume_model_stream
from tests.helpers import fake_stream_response


def _ensure_id(_tool_delta, iteration, idx):
    return f"call_{iteration}_{idx}"


def test_consume_model_stream_calls_retry_callback_before_continuing():
    events = []

    def deltas():
        events.append("yield retry")
        yield {"_retry": "HTTP 502 Bad Gateway: Retrying in 1s (1/3)."}
        events.append("after retry")
        yield {"choices": [{"delta": {"content": "ok"}}]}

    result = consume_model_stream(
        deltas(),
        ensure_tool_call_id=_ensure_id,
        iteration=2,
        on_retry=lambda detail: events.append(f"callback {detail}"),
    )

    assert events[:2] == [
        "yield retry",
        "callback HTTP 502 Bad Gateway: Retrying in 1s (1/3).",
    ]
    assert events[-1] == "after retry"
    assert result.retry_events == ["HTTP 502 Bad Gateway: Retrying in 1s (1/3)."]
    assert result.text == "ok"


def test_consume_model_stream_stops_on_http_error():
    seen = []

    result = consume_model_stream(
        fake_stream_response({"_error": "HTTP 403 Forbidden: API key rejected."}),
        ensure_tool_call_id=_ensure_id,
        iteration=0,
        on_error=seen.append,
    )

    assert result.error == "HTTP 403 Forbidden: API key rejected."
    assert seen == ["HTTP 403 Forbidden: API key rejected."]
    assert result.text == ""
    assert result.tool_calls == {}


def test_consume_model_stream_collects_usage_reasoning_text_and_tool_calls():
    result = consume_model_stream(
        fake_stream_response(
            {"_usage": {"prompt_tokens": 2, "completion_tokens": 3}},
            {"choices": [{"delta": {"reasoning_content": "hidden"}}]},
            {"choices": [{"delta": {"content": "visible"}}]},
            {
                "choices": [{
                    "delta": {
                        "tool_calls": [{
                            "index": 0,
                            "function": {"name": "read_", "arguments": '{"path"'},
                        }],
                    },
                }],
            },
            {
                "choices": [{
                    "delta": {
                        "tool_calls": [{
                            "index": 0,
                            "function": {"name": "file", "arguments": ': "x"}'},
                        }],
                    },
                }],
            },
        ),
        ensure_tool_call_id=_ensure_id,
        iteration=4,
    )

    assert result.usage == {"prompt_tokens": 2, "completion_tokens": 3}
    assert result.reasoning == "hidden"
    assert result.text == "visible"
    assert result.tool_calls[0] == {
        "id": "call_4_0",
        "name": "read_file",
        "args": '{"path": "x"}',
    }


@pytest.mark.parametrize(
    ("name_deltas", "expected_name"),
    [
        pytest.param(
            ["switch_phase", "switch_phase"],
            "switch_phase",
            id="repeated-complete-name",
        ),
        pytest.param(
            ["read_", "file"],
            "read_file",
            id="incremental-name-fragments",
        ),
        pytest.param(
            ["switch", "switch_phase"],
            "switch_phase",
            id="cumulative-name-snapshots",
        ),
    ],
)
def test_consume_model_stream_merges_tool_name_delta_protocols(
    name_deltas, expected_name
):
    result = consume_model_stream(
        fake_stream_response(
            *[
                {
                    "choices": [{
                        "delta": {
                            "tool_calls": [{
                                "index": 0,
                                "function": {
                                    "name": name,
                                    "arguments": arguments,
                                },
                            }],
                        },
                    }],
                }
                for name, arguments in zip(
                    name_deltas, ['{"phase"', ': "plan"}'], strict=True
                )
            ]
        ),
        ensure_tool_call_id=_ensure_id,
        iteration=5,
    )

    assert result.tool_calls[0] == {
        "id": "call_5_0",
        "name": expected_name,
        "args": '{"phase": "plan"}',
    }


def test_consume_model_stream_propagates_keyboard_interrupt():
    def deltas():
        raise KeyboardInterrupt
        yield {}  # pragma: no cover

    with pytest.raises(KeyboardInterrupt):
        consume_model_stream(deltas(), ensure_tool_call_id=_ensure_id, iteration=0)


def test_repetition_guard_stops_a_looping_content_stream():
    """A model that repeats one sentence to max_tokens is cut short."""
    from core.turn_api import REPETITION_NOTICE

    closed = {"n": 0}
    emitted = []

    def deltas():
        try:
            for _ in range(5000):
                yield {"choices": [{"delta": {"content": "I will now write the full analysis.\n"}}]}
        finally:
            closed["n"] += 1

    # Hold a reference so the generator is not garbage-collected when
    # consume_model_stream returns: then only the explicit close() inside it can
    # run the generator's finally, so this test fails if that close is removed.
    gen = deltas()
    result = consume_model_stream(
        gen,
        ensure_tool_call_id=_ensure_id,
        iteration=1,
        on_content=emitted.append,
    )

    assert result.repetition_stopped is True
    assert result.text.endswith(REPETITION_NOTICE)
    # Only a handful of repeats leaked, not thousands.
    assert result.text.count("I will now write the full analysis.") < 20
    assert emitted[-1] == REPETITION_NOTICE
    assert closed["n"] == 1  # the generator was closed to stop the request, before return
    assert gen is not None  # keep the reference alive past the assertion above


def test_repetition_guard_leaves_a_normal_answer_untouched():
    events = [
        {"choices": [{"delta": {"content": f"Distinct line number {i} with its own content.\n"}}]}
        for i in range(100)
    ]
    result = consume_model_stream(
        fake_stream_response(*events),
        ensure_tool_call_id=_ensure_id,
        iteration=1,
    )
    assert result.repetition_stopped is False
    assert "repeating itself" not in result.text
    assert result.text.count("Distinct line number") == 100


def test_repetition_guard_can_be_disabled_by_env(monkeypatch):
    monkeypatch.setenv("PAWNLOGIC_STREAM_LOOP_GUARD", "0")
    events = [
        {"choices": [{"delta": {"content": "The same repeated sentence over and over.\n"}}]}
        for _ in range(100)
    ]
    result = consume_model_stream(
        fake_stream_response(*events),
        ensure_tool_call_id=_ensure_id,
        iteration=1,
    )
    assert result.repetition_stopped is False
    assert result.text.count("The same repeated sentence over and over.") == 100
