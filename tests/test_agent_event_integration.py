from __future__ import annotations

from dataclasses import dataclass

from core.agent_events import AgentEventKind
from core.delegation import publish_delegation_event
from core.runtime_context import RuntimeContext
from core.session_events import SessionEventEmitter
from core.tool_executor import ToolExecutionOutcome


class CaptureEventSink:
    def __init__(self) -> None:
        self.events = []

    def emit(self, event) -> None:
        self.events.append(event)

    def print(self, text: str) -> None:
        return None

    def print_json(self, data: dict) -> None:
        return None

    def write(self, text: str) -> None:
        return None


@dataclass
class FakeHit:
    record_id: str = "record:one"
    namespace: str = "project"
    source_type: str = "document"
    source_id: str = "guide.md"
    source_revision: str = "rev-2"
    score: float = 0.8
    score_kind: str = "keyword"
    provenance: dict | None = None
    content: str = "OPENAI_API_KEY=event-only-test"

    def __post_init__(self) -> None:
        if self.provenance is None:
            self.provenance = {"retrieval_algorithm": "sqlite_fts5"}


@dataclass
class FakeMetrics:
    turn_prompt_tokens: int = 20
    turn_completion_tokens: int = 8
    turn_tool_calls: int = 1


def test_session_event_order_and_safe_retrieval_projection(tmp_path):
    sink = CaptureEventSink()
    context = RuntimeContext.for_test(
        cwd=tmp_path,
        workspace_dir=tmp_path / "workspace",
        sink=sink,
    )
    emitter = SessionEventEmitter(context, "session-1")

    emitter.start_turn("model-a", "RECON")
    emitter.retrieval([FakeHit()])
    emitter.usage({"prompt_tokens": 20, "completion_tokens": 8})
    tool_call = {"id": "call-1", "name": "read_file"}
    emitter.tool_started(tool_call, 0)
    emitter.tool_result(
        tool_call,
        ToolExecutionOutcome(status="success", content="secret output"),
        0,
    )
    emitter.policy(policy="plan_guard", decision="ok")
    emitter.finish("completed", FakeMetrics())
    emitter.finish("completed", FakeMetrics())

    assert [event.event_type for event in sink.events] == [
        AgentEventKind.TURN_STARTED,
        AgentEventKind.RETRIEVAL_EVIDENCE,
        AgentEventKind.USAGE,
        AgentEventKind.TOOL_STARTED,
        AgentEventKind.TOOL_RESULT,
        AgentEventKind.POLICY_DECISION,
        AgentEventKind.TURN_COMPLETED,
    ]
    encoded = "\n".join(event.to_json() for event in sink.events)
    assert "event-only-test" not in encoded
    assert "secret output" not in encoded
    assert sink.events[-1].payload["tool_calls"] == 1


def test_delegation_events_keep_parent_child_identity(tmp_path):
    sink = CaptureEventSink()
    context = RuntimeContext.for_test(
        cwd=tmp_path,
        workspace_dir=tmp_path / "workspace",
        sink=sink,
    )
    context.session_id = "session-1"
    context.agent_id = "agent-parent"
    context.active_turn_id = "turn-1"

    with context.activate():
        publish_delegation_event(
            AgentEventKind.DELEGATION_STARTED,
            {
                "status": "started",
                "model_alias": "worker-a",
                "instructions": "PASSWORD=do-not-emit",
            },
            child_agent_id="agent-child",
        )

    event = sink.events[0]
    assert event.session_id == "session-1"
    assert event.turn_id == "turn-1"
    assert event.agent_id == "agent-child"
    assert event.parent_agent_id == "agent-parent"
    assert "do-not-emit" not in event.to_json()


def test_event_subscriber_failure_does_not_break_session_runtime(tmp_path):
    context = RuntimeContext.for_test(
        cwd=tmp_path,
        workspace_dir=tmp_path / "workspace",
    )
    context.event_publisher.subscribe(
        lambda event: (_ for _ in ()).throw(RuntimeError("consumer failed"))
    )
    emitter = SessionEventEmitter(context, "session-1")

    emitter.start_turn("model-a", "RECON")
    emitter.finish("failed", FakeMetrics())


def test_turn_interruption_closes_an_open_tool_event(tmp_path):
    sink = CaptureEventSink()
    context = RuntimeContext.for_test(
        cwd=tmp_path,
        workspace_dir=tmp_path / "workspace",
        sink=sink,
    )
    emitter = SessionEventEmitter(context, "session-1")
    emitter.start_turn("model-a", "RECON")
    emitter.tool_started({"id": "call-1", "name": "run_shell"}, 0)

    emitter.finish("interrupted", FakeMetrics())

    assert [event.event_type for event in sink.events[-2:]] == [
        AgentEventKind.TOOL_RESULT,
        AgentEventKind.TURN_CANCELLED,
    ]
    assert sink.events[-2].payload["status"] == "interrupted"


def test_content_delta_publishes_text_delta_in_sequence(tmp_path):
    """content_delta feeds the typed stream: TEXT_DELTA lands in subscriber
    order with the renderer-approved text, so sinks can render or forward
    it without touching stdout."""
    sink = CaptureEventSink()
    context = RuntimeContext.for_test(
        cwd=tmp_path,
        workspace_dir=tmp_path / "workspace",
        sink=sink,
    )
    emitter = SessionEventEmitter(context, "session-1")

    emitter.start_turn("model-a", "RECON")
    emitter.content_delta("Hel")
    emitter.content_delta("lo!")
    emitter.finish("completed", FakeMetrics())

    assert [event.event_type for event in sink.events] == [
        AgentEventKind.TURN_STARTED,
        AgentEventKind.TEXT_DELTA,
        AgentEventKind.TEXT_DELTA,
        AgentEventKind.TURN_COMPLETED,
    ]
    assert [event.payload["text"] for event in sink.events[1:3]] == ["Hel", "lo!"]


def test_stream_delta_renders_exactly_once(monkeypatch, capsys):
    """Regression (owner-reported live-terminal doubling): the session must
    render a content delta exactly once. The runtime context auto-subscribes
    the active sink, so a direct stdout write on top of the published
    text.delta event rendered every chunk twice in the live terminal.

    Contract: the ONLY render path is the subscribed sink's emit/write;
    no direct stdout write may run beside the published event.
    """
    import re as _re

    import core.session as session_mod
    from core.commands._common import set_active_sink
    from core.output import HumanSink
    from core.session import AgentSession, _PlanRenderer
    from core.state import set_output_mode
    from core.turn_api import TurnApiResult

    renders: list[str] = []

    class CountingSink(HumanSink):
        def write(self, text: str) -> None:
            renders.append(text)  # record without touching real stdout

    saved_sink = None
    from core.commands import _common as _common_mod
    saved_sink = _common_mod._active_sink
    try:
        set_output_mode(debug_mode=False)
        set_active_sink(CountingSink())
        session = AgentSession()

        def fake_consume(stream_request, **kwargs):
            kwargs["on_content"]("Hello")
            kwargs["on_content"](" world\n")
            return TurnApiResult()

        monkeypatch.setattr(session_mod, "consume_model_stream", fake_consume)

        result = session._consume_api_stream_attempt(
            api_msgs=[],
            current_tools=None,
            current_max_tokens=64,
            renderer=_PlanRenderer(),
            iteration=0,
        )
        assert result.error is None

        joined = "".join(renders)
        plain = _re.sub(r"\x1b\[[0-9;]*m", "", joined)
        # Exactly one render of each fragment, via the subscribed sink only.
        assert plain.count("Hello") == 1, renders
        assert plain.count("world") == 1, renders
        # No direct stdout write may run beside the published event.
        assert "Hello" not in capsys.readouterr().out
    finally:
        set_active_sink(saved_sink)
