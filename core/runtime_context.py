"""Runtime context shared by sessions, commands, and tool adapters."""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from contextvars import ContextVar
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

    @contextmanager
    def activate(self) -> Iterator[RuntimeContext]:
        """Make this context authoritative for the current execution scope."""
        token = _ACTIVE_RUNTIME_CONTEXT.set(self)
        self.sync_legacy_state()
        try:
            yield self
        finally:
            _ACTIVE_RUNTIME_CONTEXT.reset(token)
            previous = current_runtime_context()
            if previous is not None:
                previous.sync_legacy_state()

    def set_output_mode(self, *, debug_mode: bool, user_mode: bool | None = None) -> None:
        """Update this context's output mode and its compatibility mirrors."""
        self.debug_mode = bool(debug_mode)
        self.user_mode = (not self.debug_mode) if user_mode is None else bool(user_mode)
        self.sync_legacy_state()

    def sync_legacy_state(self) -> None:
        """Mirror authoritative context values into transitional process globals."""
        from core.state import mirror_runtime_context

        mirror_runtime_context(self)

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


_ACTIVE_RUNTIME_CONTEXT: ContextVar[RuntimeContext | None] = ContextVar(
    "pawnlogic_runtime_context",
    default=None,
)


def _default_sink() -> Any:
    try:
        from core.commands._common import get_active_sink
        return get_active_sink()
    except Exception:
        from core.output import HumanSink
        return HumanSink()


def current_runtime_context() -> RuntimeContext | None:
    """Return the context active in the current thread or async task."""
    return _ACTIVE_RUNTIME_CONTEXT.get()


__all__ = ["RuntimeContext", "current_runtime_context"]
