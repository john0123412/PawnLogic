from __future__ import annotations

import asyncio
import importlib

from core.state import (
    dynamic_config_snapshot,
    get_dynamic_config_value,
    runtime_config,
    set_dynamic_config_value,
    state,
)
from core.runtime_context import RuntimeContext, current_runtime_context
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


def _current_config():
    return importlib.import_module("config")


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


def test_runtime_context_activation_isolates_mode_config_paths_and_sink(tmp_path):
    first_sink = CaptureSink()
    second_sink = CaptureSink()
    first = RuntimeContext.for_test(
        cwd=tmp_path / "first-cwd",
        workspace_dir=tmp_path / "first-workspace",
        sink=first_sink,
        debug_mode=True,
        user_mode=False,
        dynamic_config={"max_iter": 11},
    )
    second = RuntimeContext.for_test(
        cwd=tmp_path / "second-cwd",
        workspace_dir=tmp_path / "second-workspace",
        sink=second_sink,
        debug_mode=False,
        user_mode=True,
        dynamic_config={"max_iter": 22},
    )

    with first.activate():
        assert current_runtime_context() is first
        assert runtime_config()["max_iter"] == 11
        set_dynamic_config_value("max_iter", 12)
        assert first.dynamic_config["max_iter"] == 12
        assert second.dynamic_config["max_iter"] == 22

        with second.activate():
            assert current_runtime_context() is second
            assert runtime_config()["max_iter"] == 22
            set_dynamic_config_value("max_iter", 23)

        assert current_runtime_context() is first
        assert runtime_config()["max_iter"] == 12

    assert first.cwd != second.cwd
    assert first.workspace_dir != second.workspace_dir
    assert first.sink is first_sink
    assert second.sink is second_sink
    assert first.debug_mode is True
    assert second.debug_mode is False
    assert second.dynamic_config["max_iter"] == 23


def test_dispatch_uses_session_runtime_context_sink(tmp_path):
    from core.commands import CommandContext, dispatch, register

    sink = CaptureSink()

    class FakeSession:
        runtime_context = RuntimeContext.for_test(
            cwd=tmp_path,
            workspace_dir=tmp_path / "workspace",
            sink=sink,
        )

    @register("/__runtime_context_sink_test")
    async def _handler(ctx: CommandContext) -> None:
        from core.commands._common import sink_print

        assert current_runtime_context() is ctx.session.runtime_context
        sink_print("context-owned output")

    asyncio.run(
        dispatch(
            CommandContext(
                verb="/__runtime_context_sink_test",
                arg="",
                arg2="",
                session=FakeSession(),
            )
        )
    )

    assert sink.lines == ["context-owned output"]


def test_dynamic_config_is_bound_to_runtime_state():
    config = _current_config()

    assert runtime_config() is config.DYNAMIC_CONFIG
    assert state.dynamic_config is config.DYNAMIC_CONFIG


def test_runtime_context_from_current_uses_runtime_config():
    ctx = RuntimeContext.from_current()

    assert ctx.dynamic_config is runtime_config()


def test_dynamic_config_write_path_syncs_state_fields(monkeypatch):
    config = _current_config()
    original_worker = runtime_config().get("preferred_worker")
    original_budget = runtime_config().get("time_budget_sec")
    try:
        set_dynamic_config_value("preferred_worker", "pytest-worker")
        set_dynamic_config_value("time_budget_sec", 42)

        assert config.DYNAMIC_CONFIG["preferred_worker"] == "pytest-worker"
        assert state.current_worker == "pytest-worker"
        assert state.time_budget_sec == 42
    finally:
        if original_worker is None:
            runtime_config().pop("preferred_worker", None)
        else:
            set_dynamic_config_value("preferred_worker", original_worker)
        if original_budget is None:
            runtime_config().pop("time_budget_sec", None)
            state.time_budget_sec = 0
        else:
            set_dynamic_config_value("time_budget_sec", original_budget)


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


def test_worker_command_updates_runtime_state(monkeypatch):
    from core.commands import CommandContext
    from core.commands.tools import cmd_worker

    original_worker = runtime_config().get("preferred_worker")

    class FakeSession:
        reset_called = False

        def _reset_system_prompt(self) -> None:
            self.reset_called = True

    try:
        session = FakeSession()
        ctx = CommandContext(verb="/worker", arg="auto", arg2="", session=session)

        asyncio.run(cmd_worker(ctx))

        assert runtime_config()["preferred_worker"] == "auto"
        assert state.current_worker == "auto"
        assert session.reset_called is True
    finally:
        if original_worker is None:
            runtime_config().pop("preferred_worker", None)
            state.current_worker = "auto"
        else:
            set_dynamic_config_value("preferred_worker", original_worker)


def test_get_dynamic_config_value_reads_live_value():
    original = runtime_config().get("max_iter")
    try:
        set_dynamic_config_value("max_iter", 4321)
        assert get_dynamic_config_value("max_iter") == 4321
    finally:
        if original is None:
            runtime_config().pop("max_iter", None)
        else:
            set_dynamic_config_value("max_iter", original)


def test_get_dynamic_config_value_returns_default_for_missing_key():
    assert get_dynamic_config_value("definitely_absent_key", "fallback") == "fallback"


def test_dynamic_config_snapshot_is_a_detached_copy():
    snapshot = dynamic_config_snapshot()
    assert snapshot == dict(runtime_config())
    snapshot["max_iter"] = -999
    # Mutating the snapshot does not touch the live config.
    assert runtime_config().get("max_iter") != -999


def test_mode_command_updates_state_and_legacy_flags():
    from core.commands import CommandContext
    from core.commands.session import cmd_mode

    config = _current_config()
    original_debug = state.debug_mode
    original_user = state.user_mode
    original_config_user = config.USER_MODE

    try:
        state.debug_mode = False
        state.user_mode = True
        config.USER_MODE = True

        asyncio.run(cmd_mode(CommandContext(verb="/mode", arg="", arg2="", session=object())))

        assert state.debug_mode is True
        assert state.user_mode is False
        assert config.USER_MODE is False
    finally:
        state.debug_mode = original_debug
        state.user_mode = original_user
        config.USER_MODE = original_config_user
