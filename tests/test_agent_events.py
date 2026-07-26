from __future__ import annotations

from dataclasses import FrozenInstanceError
import json

import pytest

from core.agent_events import (
    AGENT_EVENT_SCHEMA_VERSION,
    ALLOWED_METADATA_KEYS,
    AgentEvent,
    AgentEventKind,
    AgentEventPublisher,
)


def _event(**overrides: object) -> AgentEvent:
    values: dict[str, object] = {
        "event_type": AgentEventKind.TURN_STARTED,
        "session_id": "session-1",
        "turn_id": "turn-1",
        "agent_id": "agent-1",
    }
    values.update(overrides)
    return AgentEvent(**values)


def test_v1_event_kinds_cover_the_agent_lifecycle_contract():
    kinds = {kind.value for kind in AgentEventKind}

    assert {
        "turn.started",
        "turn.completed",
        "text.delta",
        "reasoning.visibility",
        "tool.started",
        "tool.result",
        "retrieval.evidence",
        "delegation.started",
        "delegation.result",
        "policy.decision",
        "usage",
        "error",
    } <= kinds


def test_event_is_versioned_and_deeply_immutable():
    source_payload = {
        "items": [{"name": "first"}],
        "counts": [1, 2],
    }
    event = _event(payload=source_payload)
    source_payload["items"][0]["name"] = "changed"
    source_payload["counts"].append(3)

    assert event.schema_version == AGENT_EVENT_SCHEMA_VERSION
    assert event.payload["items"][0]["name"] == "first"
    assert event.payload["counts"] == (1, 2)
    with pytest.raises(FrozenInstanceError):
        event.turn_id = "other"
    with pytest.raises(TypeError):
        event.payload["new"] = "value"
    with pytest.raises(TypeError):
        event.payload["items"][0]["name"] = "changed"


def test_metadata_is_allowlisted_and_copied():
    metadata = {
        "sequence": 3,
        "source": "session",
        "provider": "test-provider",
        "arbitrary": "must not cross the event boundary",
    }

    event = _event(metadata=metadata)
    metadata["source"] = "changed"

    assert set(event.metadata) <= ALLOWED_METADATA_KEYS
    assert dict(event.metadata) == {
        "provider": "test-provider",
        "sequence": 3,
        "source": "session",
    }


def test_json_serialization_is_canonical_and_round_trips():
    event = _event(
        event_type="tool.result",
        parent_agent_id="parent-1",
        payload={"z": "snow", "a": [2, {"x": True}]},
        metadata={"sequence": 4, "source": "tool-loop"},
    )

    encoded = event.to_json()

    assert encoded == (
        '{"agent_id":"agent-1","event_type":"tool.result",'
        '"metadata":{"sequence":4,"source":"tool-loop"},'
        '"parent_agent_id":"parent-1",'
        '"payload":{"a":[2,{"x":true}],"z":"snow"},'
        '"schema_version":1,"session_id":"session-1","turn_id":"turn-1"}'
    )
    assert AgentEvent.from_json(encoded) == event
    assert json.loads(encoded) == event.to_dict()


def test_recursive_redaction_happens_before_construction_and_publication():
    provider_key = "sk-" + "proj-" + "abcdefghijklmnopqrstuvwxyz123456"
    source_payload = {
        "authorization": f"Bearer {provider_key}",
        "nested": [
            {"password": "hunter2"},
            f"request failed: OPENAI_API_KEY={provider_key}",
            {"prompt_tokens": 42},
        ],
    }
    event = _event(
        payload=source_payload,
        metadata={"source": f"Bearer {provider_key}"},
    )
    received: list[AgentEvent] = []
    publisher = AgentEventPublisher([received.append])

    publisher.publish(event)
    encoded = received[0].to_json()

    assert provider_key not in repr(event)
    assert provider_key not in encoded
    assert "hunter2" not in encoded
    assert encoded.count("[REDACTED_SECRET]") >= 3
    assert received[0].payload["nested"][2]["prompt_tokens"] == 42
    assert source_payload["nested"][0]["password"] == "hunter2"


def test_publisher_is_synchronous_ordered_and_unsubscribe_is_idempotent():
    calls: list[tuple[str, str]] = []
    publisher = AgentEventPublisher()

    def first(event: AgentEvent) -> None:
        calls.append(("first", event.event_type.value))

    def second(event: AgentEvent) -> None:
        calls.append(("second", event.event_type.value))

    unsubscribe_first = publisher.subscribe(first)
    publisher.subscribe(second)

    assert publisher.publish(_event()) is None
    assert calls == [
        ("first", "turn.started"),
        ("second", "turn.started"),
    ]

    unsubscribe_first()
    unsubscribe_first()
    publisher.emit(_event(event_type=AgentEventKind.TURN_COMPLETED))

    assert calls[-1] == ("second", "turn.completed")
    assert publisher.subscriber_count == 1


def test_failing_subscriber_does_not_block_later_subscribers():
    received = []
    publisher = AgentEventPublisher(
        [
            lambda event: (_ for _ in ()).throw(RuntimeError("failed")),
            received.append,
        ]
    )

    publisher.publish(_event())

    assert len(received) == 1


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("schema_version", 2, ValueError),
        ("event_type", "unknown.event", ValueError),
        ("session_id", "", ValueError),
        ("payload", {"not_finite": float("nan")}, ValueError),
        ("payload", {"bad": object()}, TypeError),
    ],
)
def test_invalid_contract_values_fail_closed(field: str, value: object, error: type[Exception]):
    with pytest.raises(error):
        _event(**{field: value})
