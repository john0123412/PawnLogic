from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from dataclasses import dataclass, field
import threading

from core.output import HumanSink, JsonSink, TaskOutputCollector, capture_stdout


@dataclass(frozen=True)
class StubAgentEvent:
    schema_version: int = 1
    event_type: str = "turn.completed"
    session_id: str = "session-1"
    turn_id: str = "turn-1"
    agent_id: str = "agent-1"
    parent_agent_id: str | None = None
    payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "event_type": self.event_type,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "agent_id": self.agent_id,
            "parent_agent_id": self.parent_agent_id,
            "payload": self.payload,
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


def test_json_sink_legacy_methods_keep_exact_ndjson_shapes(capsys):
    sink = JsonSink()

    sink.print("done")
    sink.write("part")
    sink.print_json({"ok": True})

    assert [json.loads(line) for line in capsys.readouterr().out.splitlines()] == [
        {"type": "text", "content": "done"},
        {"type": "chunk", "content": "part"},
        {"type": "json", "data": {"ok": True}},
    ]


def test_json_sink_emits_agent_event_in_additive_legacy_envelope(capsys):
    sink = JsonSink()
    event = StubAgentEvent(
        event_type="tool.result",
        parent_agent_id="parent-1",
        payload={"tool_name": "read_file", "status": "completed"},
    )

    sink.emit(event)

    assert json.loads(capsys.readouterr().out) == {
        "type": "event",
        "data": event.to_dict(),
    }


def test_human_sink_renders_text_delta_verbatim_without_newline(capsys):
    sink = HumanSink()
    event = StubAgentEvent(
        event_type="text.delta",
        payload={"text": "\x1b[31mred\x1b[0m"},
    )

    sink.emit(event)

    assert capsys.readouterr().out == "\x1b[31mred\x1b[0m"


def test_human_sink_renders_user_facing_error_as_line(capsys):
    sink = HumanSink()
    event = StubAgentEvent(
        event_type="error",
        payload={"message": "Request failed"},
    )

    sink.emit(event)

    assert capsys.readouterr().out == "Request failed\n"


def test_human_sink_consumes_lifecycle_event_without_terminal_noise(capsys):
    sink = HumanSink()
    event = StubAgentEvent(
        event_type="tool.started",
        payload={"tool_name": "read_file"},
    )

    sink.emit(event)

    assert capsys.readouterr().out == ""


def test_task_output_capture_is_thread_scoped(capsys):
    barrier = threading.Barrier(2, timeout=2)

    def emit(marker: str) -> str:
        collector = TaskOutputCollector()
        with capture_stdout(collector):
            print(f"{marker}-before")
            barrier.wait()
            print(f"{marker}-after")
        return collector.text

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = tuple(pool.map(emit, ("first", "second")))

    assert "first-before" in first
    assert "first-after" in first
    assert "second-" not in first
    assert "second-before" in second
    assert "second-after" in second
    assert "first-" not in second
    assert capsys.readouterr().out == ""
