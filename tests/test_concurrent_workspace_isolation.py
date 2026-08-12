"""Concurrency regressions for isolated delegated RuntimeContexts."""

from __future__ import annotations

import threading
from pathlib import Path

from core.runtime_context import RuntimeContext, current_runtime_context
from core.state import set_dynamic_config_value, state
from tools import file_ops


class CaptureSink:
    def print(self, _text: str) -> None:
        return None

    def write(self, _text: str) -> None:
        return None

    def print_json(self, _data: dict) -> None:
        return None


def test_concurrent_children_keep_runtime_and_workspace_state_isolated(tmp_path):
    import config

    project = tmp_path / "project"
    project.mkdir()
    parent_workspace = tmp_path / "workspace"
    parent_workspace.mkdir()
    parent = RuntimeContext.for_test(
        cwd=project,
        workspace_dir=parent_workspace,
        sink=CaptureSink(),
        debug_mode=False,
        user_mode=True,
        dynamic_config={
            "preferred_worker": "parent",
            "time_budget_sec": 10,
            "tool_max_chars": 1_000,
        },
    )
    first = parent.fork_for_task("first", sink=CaptureSink())
    second = parent.fork_for_task("second", sink=CaptureSink())
    ready = threading.Barrier(3)
    release = threading.Barrier(3)
    results: dict[str, dict[str, object]] = {}
    errors: list[BaseException] = []
    saved_state = (
        state.debug_mode,
        state.user_mode,
        state.dynamic_config,
        state.current_worker,
        state.time_budget_sec,
    )
    saved_config = (config.USER_MODE, config.QUIET_MODE)
    saved_paths = (file_ops._session_cwd[0], file_ops._session_workspace_dir[0])

    def run_child(
        name: str,
        child: RuntimeContext,
        *,
        debug_mode: bool,
        sibling: RuntimeContext,
    ) -> None:
        try:
            with child.activate(mirror_legacy=False):
                assert current_runtime_context() is child
                child.set_output_mode(
                    debug_mode=debug_mode,
                    user_mode=not debug_mode,
                )
                set_dynamic_config_value("preferred_worker", name)
                set_dynamic_config_value("time_budget_sec", 20 if name == "first" else 30)
                ready.wait(timeout=5)
                release.wait(timeout=5)

                write_result = file_ops.tool_write_file(
                    {"path": "same-relative-name.txt", "content": name}
                )
                sibling_result = file_ops.tool_write_file(
                    {
                        "path": str(Path(sibling.workspace_dir) / "forbidden.txt"),
                        "content": "blocked",
                    }
                )
                results[name] = {
                    "cwd": child.cwd,
                    "workspace": child.workspace_dir,
                    "user_mode": child.user_mode,
                    "worker": child.dynamic_config["preferred_worker"],
                    "budget": child.dynamic_config["time_budget_sec"],
                    "write_result": write_result,
                    "sibling_result": sibling_result,
                }
        except BaseException as error:  # pragma: no cover - asserted by parent thread
            errors.append(error)

    first_thread = threading.Thread(
        target=run_child,
        args=("first", first),
        kwargs={"debug_mode": False, "sibling": second},
    )
    second_thread = threading.Thread(
        target=run_child,
        args=("second", second),
        kwargs={"debug_mode": True, "sibling": first},
    )

    try:
        parent.sync_legacy_state()
        file_ops.sync_runtime_context(parent)
        expected_legacy = (
            state.debug_mode,
            state.user_mode,
            state.dynamic_config,
            state.current_worker,
            state.time_budget_sec,
            config.USER_MODE,
            config.QUIET_MODE,
            file_ops._session_cwd[0],
            file_ops._session_workspace_dir[0],
        )

        first_thread.start()
        second_thread.start()
        ready.wait(timeout=5)

        assert (
            state.debug_mode,
            state.user_mode,
            state.dynamic_config,
            state.current_worker,
            state.time_budget_sec,
            config.USER_MODE,
            config.QUIET_MODE,
            file_ops._session_cwd[0],
            file_ops._session_workspace_dir[0],
        ) == expected_legacy

        release.wait(timeout=5)
        first_thread.join(timeout=5)
        second_thread.join(timeout=5)

        assert not first_thread.is_alive()
        assert not second_thread.is_alive()
        assert errors == []
        assert results["first"]["cwd"] == results["first"]["workspace"]
        assert results["second"]["cwd"] == results["second"]["workspace"]
        assert results["first"]["workspace"] != results["second"]["workspace"]
        assert results["first"]["user_mode"] is True
        assert results["second"]["user_mode"] is False
        assert results["first"]["worker"] == "first"
        assert results["second"]["worker"] == "second"
        assert results["first"]["budget"] == 20
        assert results["second"]["budget"] == 30
        assert parent.dynamic_config["preferred_worker"] == "parent"
        assert parent.dynamic_config["time_budget_sec"] == 10
        assert (Path(first.workspace_dir) / "same-relative-name.txt").read_text(
            encoding="utf-8"
        ) == "first"
        assert (Path(second.workspace_dir) / "same-relative-name.txt").read_text(
            encoding="utf-8"
        ) == "second"
        assert results["first"]["write_result"].startswith("OK:")
        assert results["second"]["write_result"].startswith("OK:")
        assert results["first"]["sibling_result"].startswith("SECURITY BLOCK")
        assert results["second"]["sibling_result"].startswith("SECURITY BLOCK")
    finally:
        (
            state.debug_mode,
            state.user_mode,
            state.dynamic_config,
            state.current_worker,
            state.time_budget_sec,
        ) = saved_state
        config.USER_MODE, config.QUIET_MODE = saved_config
        file_ops._session_cwd[0], file_ops._session_workspace_dir[0] = saved_paths
