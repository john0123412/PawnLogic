"""Runtime context shared by sessions, commands, and tool adapters."""

from __future__ import annotations

from collections.abc import MutableMapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.runtime_context_scope import (
    activate_runtime_context,
    active_runtime_context_mirrors_legacy,
    context_allows_legacy_mirror,
    current_runtime_context,
    fork_task_context,
)


@dataclass
class RuntimeContext:
    """Mutable runtime state that used to be spread across module globals."""

    cwd: str
    workspace_dir: str
    sink: Any
    debug_mode: bool
    user_mode: bool
    dynamic_config: MutableMapping[str, Any]
    extension_manager: Any = None
    context_provider: Any = None
    event_publisher: Any = None
    session_id: str = ""
    agent_id: str = ""
    active_turn_id: str = "turn-inactive"
    isolated_workspace: bool = False

    def __post_init__(self) -> None:
        if self.event_publisher is None:
            from core.agent_events import AgentEventPublisher

            self.event_publisher = AgentEventPublisher()
        emit = getattr(self.sink, "emit", None)
        if callable(emit):
            self.event_publisher.subscribe(emit)

    def publish_event(self, event: Any) -> None:
        """Publish one validated event to process-local subscribers."""
        self.event_publisher.publish(event)

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
        from config import WORKSPACE_DIR
        from core.state import runtime_config, state

        if sink is None:
            sink = _default_sink()
        if dynamic_config is None:
            dynamic_config = runtime_config()

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
            from core.state import runtime_config

            dynamic_config = dict(runtime_config())
        return cls(
            cwd=str(Path(cwd).expanduser()),
            workspace_dir=str(Path(workspace_dir).expanduser()),
            sink=sink,
            debug_mode=debug_mode,
            user_mode=user_mode,
            dynamic_config=dynamic_config,
        )

    def activate(
        self,
        *,
        mirror_legacy: bool | None = None,
    ) -> AbstractContextManager[RuntimeContext]:
        """Make this context authoritative for the current execution scope.

        ``mirror_legacy=False`` keeps compatibility globals untouched.  Isolated
        child workspaces always use that mode, even if a caller requests a
        mirror, because process-wide pointers cannot identify a concurrent child.
        """
        return activate_runtime_context(self, mirror_legacy=mirror_legacy)

    def set_output_mode(self, *, debug_mode: bool, user_mode: bool | None = None) -> None:
        """Update this context's output mode and its compatibility mirrors."""
        self.debug_mode = bool(debug_mode)
        self.user_mode = (not self.debug_mode) if user_mode is None else bool(user_mode)
        if self._allows_legacy_mirror():
            self.sync_legacy_state()

    def fork_for_task(
        self,
        task: Any = None,
        *,
        sink: Any = None,
        task_id: str | None = None,
    ) -> RuntimeContext:
        """Create an isolated child context for one delegated task.

        Child workspaces are unique descendants of the parent workspace.  The
        task identifier is only used as a sanitized filename fragment, never as
        a path, so an untrusted task id cannot traverse into a sibling workspace.
        """
        return fork_task_context(
            self,
            task,
            sink=sink,
            task_id=task_id,
        )

    def sync_legacy_state(self) -> None:
        """Mirror authoritative context values into transitional process globals."""
        if not self._allows_legacy_mirror():
            return
        from core.state import mirror_runtime_context

        mirror_runtime_context(self)

    def _allows_legacy_mirror(self) -> bool:
        """Return whether this context may update process-global mirrors."""
        return context_allows_legacy_mirror(self)

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

__all__ = [
    "RuntimeContext",
    "active_runtime_context_mirrors_legacy",
    "current_runtime_context",
]
