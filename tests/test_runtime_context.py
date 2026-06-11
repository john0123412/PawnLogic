from __future__ import annotations

import asyncio

from core.runtime_context import RuntimeContext
from tools import file_ops


class CaptureSink:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.chunks: list[str] = []
        self.json: list[dict] = []

    def print(self, text: str) -> None:
        self.lines.append(text)

    def write(self, text: str) -> None:
        self.chunks.append(text)

    def print_json(self, data: dict) -> None:
        self.json.append(data)


def test_runtime_context_for_test_is_isolated(tmp_path):
    sink = CaptureSink()
    cfg = {"max_tokens": 123}

    ctx = RuntimeContext.for_test(
        cwd=tmp_path / "cwd",
        workspace_dir=tmp_path / "workspace",
        sink=sink,
        debug_mode=True,
        user_mode=False,
        dynamic_config=cfg,
    )

    assert ctx.cwd == str(tmp_path / "cwd")
    assert ctx.workspace_dir == str(tmp_path / "workspace")
    assert ctx.sink is sink
    assert ctx.debug_mode is True
    assert ctx.user_mode is False
    assert ctx.dynamic_config is cfg


def test_sync_runtime_context_updates_file_ops_pointers(tmp_path):
    ctx = RuntimeContext.for_test(
        cwd=tmp_path / "cwd",
        workspace_dir=tmp_path / "workspace",
    )

    file_ops.sync_runtime_context(ctx)

    assert file_ops._session_cwd[0] == str(tmp_path / "cwd")
    assert file_ops._session_workspace_dir[0] == str(tmp_path / "workspace")


def test_agent_session_creates_runtime_context(monkeypatch, tmp_path):
    from core.session import AgentSession

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("core.session._gen_id", lambda: "session-runtime")
    monkeypatch.setattr(
        "core.session.stable_workspace_dir",
        lambda _session_id: str(tmp_path / "workspace"),
    )
    monkeypatch.setattr("core.session.init_db", lambda: None)
    monkeypatch.setattr(
        "core.session.AgentSession._reset_system_prompt",
        lambda self: None,
    )

    session = AgentSession()

    assert session.runtime_context.cwd == str(tmp_path)
    assert session.runtime_context.workspace_dir == str(tmp_path / "workspace")
    assert file_ops._session_cwd[0] == str(tmp_path)
    assert file_ops._session_workspace_dir[0] == str(tmp_path / "workspace")


def test_cd_updates_runtime_context_for_test_session(monkeypatch, tmp_path):
    from core.commands import CommandContext, dispatch

    target = tmp_path / "target"
    target.mkdir()

    class FakeSession:
        cwd = str(tmp_path)
        workspace_dir = str(tmp_path / "workspace")
        runtime_context = RuntimeContext.for_test(
            cwd=cwd,
            workspace_dir=workspace_dir,
        )
        reset_called = False

        def _reset_system_prompt(self) -> None:
            self.reset_called = True

    session = FakeSession()
    sink = CaptureSink()
    ctx = CommandContext(
        verb="/cd",
        arg=str(target),
        arg2="",
        session=session,
        sink=sink,
    )

    asyncio.run(dispatch(ctx))

    assert session.cwd == str(target)
    assert session.runtime_context.cwd == str(target)
    assert file_ops._session_cwd[0] == str(target)
    assert session.reset_called is True
    assert sink.lines
