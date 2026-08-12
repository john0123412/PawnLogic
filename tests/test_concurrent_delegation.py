"""End-to-end isolation regressions for two delegated worker tasks."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from core.agent_orchestrator import CancellationToken, SerialAgentOrchestrator
from core.agent_events import AgentEventKind
from core.delegation import AgentBudget, AgentTask, publish_delegation_event
from core.delegation_runtime import (
    DelegationTaskExecutor,
    SubAgentSession,
    make_sub_executor,
    run_delegated_tasks,
)
from core.output import runtime_print
from core.runtime_context import RuntimeContext
from core.state import set_dynamic_config_value
from core.tool_executor import ToolExecutionContext
from core.tool_registry import ToolRegistry, ToolSpec
from tools.file_ops import tool_write_file


class _Sink:
    def __init__(self) -> None:
        self.events = []
        self._lock = threading.Lock()

    def print(self, _text: str) -> None:
        return None

    def write(self, _text: str) -> None:
        return None

    def print_json(self, _data: dict) -> None:
        return None

    def emit(self, event) -> None:
        with self._lock:
            self.events.append(event)


def _schema(name: str) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "parameters": {"type": "object"}},
    }


def _task(task_id: str) -> AgentTask:
    return AgentTask(
        task_id=task_id,
        objective=f"complete {task_id}",
        budget=AgentBudget(max_tokens=2, max_tool_calls=0),
    )


def test_concurrent_delegation_isolates_context_workspace_and_output(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    parent_sink = _Sink()
    parent = RuntimeContext.for_test(
        cwd=project,
        workspace_dir=tmp_path / "workspace",
        sink=parent_sink,
        dynamic_config={"preferred_worker": "parent", "tool_max_chars": 1_000},
    )
    parent.session_id = "parent-session"
    parent.agent_id = "parent-agent"
    ready = threading.Barrier(2)
    sessions: dict[str, _FakeSession] = {}

    class _FakeSession:
        status = "completed"
        failures = ()
        prompt_tokens = 1
        completion_tokens = 1
        tool_calls = 0

        def __init__(self, task, _model, *, runtime_context, **_options):
            self.session_id = f"child-{task.rsplit(' ', 1)[-1]}"
            self.runtime_context = runtime_context
            self.task_id = task.rsplit(" ", 1)[-1]
            self._tool_log = ()
            sessions[self.task_id] = self

        def run(self):
            set_dynamic_config_value("preferred_worker", self.task_id)
            ready.wait(timeout=1)
            print(f"stdout:{self.task_id}")
            runtime_print(f"sink:{self.task_id}")
            publish_delegation_event(
                AgentEventKind.USAGE,
                {"source": self.task_id},
                child_agent_id=self.session_id,
            )
            result = tool_write_file(
                {"path": "result.txt", "content": self.task_id}
            )
            assert result.startswith("OK:")
            return f"completed {self.task_id}"

    tasks = (_task("task-a"), _task("task-b"))

    with parent.activate():
        executor, outcome = run_delegated_tasks(
            tasks,
            model_alias="worker",
            budget=AgentBudget(max_tokens=4, max_tool_calls=0),
            cancellation=CancellationToken(),
            max_concurrency=2,
            parent_runtime_context=parent,
            session_factory=_FakeSession,
        )

    assert [result.status for result in outcome.results] == [
        "completed",
        "completed",
    ]
    assert parent.dynamic_config["preferred_worker"] == "parent"
    first = executor.record_for("task-a")
    second = executor.record_for("task-b")
    assert first is not None and second is not None
    assert "stdout:task-a" in first.output
    assert "sink:task-a" in first.output
    assert "task-b" not in first.output
    assert "stdout:task-b" in second.output
    assert "sink:task-b" in second.output
    assert "task-a" not in second.output
    first_workspace = Path(sessions["task-a"].runtime_context.workspace_dir)
    second_workspace = Path(sessions["task-b"].runtime_context.workspace_dir)
    assert first_workspace != second_workspace
    assert (first_workspace / "result.txt").read_text(encoding="utf-8") == "task-a"
    assert (second_workspace / "result.txt").read_text(encoding="utf-8") == "task-b"
    assert sessions["task-a"].runtime_context.dynamic_config["preferred_worker"] == "task-a"
    assert sessions["task-b"].runtime_context.dynamic_config["preferred_worker"] == "task-b"
    assert {
        event.payload["source"] for event in parent_sink.events
    } == {"task-a", "task-b"}


def test_concurrent_delegation_rejects_non_isolated_tools():
    registry = ToolRegistry()
    calls: list[str] = []
    registry.register_many_owned(
        "builtin",
        (
            ToolSpec(
                name="write_file",
                handler=lambda _args: calls.append("write") or "ok",
                schema=_schema("write_file"),
                capabilities=frozenset({"mutating"}),
            ),
            ToolSpec(
                name="web_search",
                handler=lambda _args: calls.append("network") or "unexpected",
                schema=_schema("web_search"),
                capabilities=frozenset({"network"}),
            ),
        ),
    )
    executor = make_sub_executor(
        registry.resolve_for_execution,
        concurrent_execution=True,
    )
    context = ToolExecutionContext(
        session_id="child",
        model_alias="worker",
        iteration=0,
        current_phase="GENERAL",
    )

    allowed = executor.execute_handler(
        tool_call_id="write",
        tool_name="write_file",
        fn_args={},
        context=context,
    )
    denied = executor.execute_handler(
        tool_call_id="network",
        tool_name="web_search",
        fn_args={},
        context=context,
    )

    assert allowed.content == "ok"
    assert denied.outcome.error_type == "ToolExecutionPolicyDenied"
    assert calls == ["write"]


def test_concurrent_subagent_does_not_advertise_non_isolated_tools(monkeypatch):
    monkeypatch.setattr(
        "core.delegation_runtime._tool_map",
        lambda: {"write_file": object(), "web_search": object()},
    )
    monkeypatch.setattr(
        "core.delegation_runtime._tool_capabilities",
        lambda: {"write_file": frozenset({"mutating"}), "web_search": frozenset({"network"})},
    )
    monkeypatch.setattr(
        "core.delegation_runtime._tools_schema",
        lambda: [_schema("write_file"), _schema("web_search")],
    )
    captured: dict[str, list[dict]] = {}

    def fake_stream(_messages, _model, *, tools_schema, **_kwargs):
        captured["schema"] = tools_schema
        return object()

    monkeypatch.setattr("core.delegation_runtime.stream_request", fake_stream)
    monkeypatch.setattr(
        "core.delegation_runtime.consume_model_stream",
        lambda *_args, **_kwargs: type(
            "Response",
            (),
            {"error": None, "usage": {}, "tool_calls": {}, "text": "done"},
        )(),
    )
    sub = SubAgentSession(
        "task",
        "worker",
        context_mode="none",
        concurrent_execution=True,
    )

    assert sub.run() == "done"
    assert captured["schema"] == [_schema("write_file")]


def test_concurrent_orchestrator_requires_a_forkable_parent_context():
    executor = DelegationTaskExecutor("worker", session_factory=object)

    with pytest.raises(ValueError, match="parent RuntimeContext"):
        SerialAgentOrchestrator(executor, max_concurrency=2)
