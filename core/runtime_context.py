"""Runtime context shared by sessions, commands, and tool adapters."""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class RuntimeContext:
    """Mutable runtime state that used to be spread across module globals."""

    cwd: str
    workspace_dir: str
    sink: Any
    debug_mode: bool
    user_mode: bool
    dynamic_config: MutableMapping[str, Any]

    @classmethod
    def from_current(
        cls,
        *,
        cwd: str | Path | None = None,
        workspace_dir: str | Path | None = None,
        sink: Any = None,
        dynamic_config: MutableMapping[str, Any] | None = None,
    ) -> RuntimeContext:
        """Build a context from the process' current runtime modules."""
        from config import DYNAMIC_CONFIG, WORKSPACE_DIR
        from core.state import state

        if sink is None:
            sink = _default_sink()
        if dynamic_config is None:
            dynamic_config = DYNAMIC_CONFIG

        return cls(
            cwd=str(Path(cwd).expanduser()) if cwd is not None else str(Path.cwd()),
            workspace_dir=(
                str(Path(workspace_dir).expanduser())
                if workspace_dir is not None
                else str(WORKSPACE_DIR)
            ),
            sink=sink,
            debug_mode=bool(state.debug_mode),
            user_mode=bool(state.user_mode),
            dynamic_config=dynamic_config,
        )

    @classmethod
    def for_test(
        cls,
        *,
        cwd: str | Path = "/tmp",
        workspace_dir: str | Path = "/tmp/pawnlogic-test-workspace",
        sink: Any = None,
        debug_mode: bool = False,
        user_mode: bool = True,
        dynamic_config: MutableMapping[str, Any] | None = None,
    ) -> RuntimeContext:
        """Build an isolated context for unit tests."""
        if sink is None:
            from core.output import HumanSink
            sink = HumanSink()
        if dynamic_config is None:
            dynamic_config = {}
        return cls(
            cwd=str(Path(cwd).expanduser()),
            workspace_dir=str(Path(workspace_dir).expanduser()),
            sink=sink,
            debug_mode=debug_mode,
            user_mode=user_mode,
            dynamic_config=dynamic_config,
        )

    def sync_state_flags(self) -> None:
        """Refresh mode flags from the shared process state."""
        from core.state import state

        self.debug_mode = bool(state.debug_mode)
        self.user_mode = bool(state.user_mode)

    def update_paths(
        self,
        *,
        cwd: str | Path | None = None,
        workspace_dir: str | Path | None = None,
    ) -> None:
        """Update path fields while preserving callers' string interface."""
        if cwd is not None:
            self.cwd = str(Path(cwd).expanduser())
        if workspace_dir is not None:
            self.workspace_dir = str(Path(workspace_dir).expanduser())


def _default_sink() -> Any:
    try:
        from core.commands._common import get_active_sink
        return get_active_sink()
    except Exception:
        from core.output import HumanSink
        return HumanSink()
