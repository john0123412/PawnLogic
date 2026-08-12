"""Scoped activation and child-workspace construction for RuntimeContext."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
from pathlib import Path
from tempfile import mkdtemp
from typing import TYPE_CHECKING, Any

from core.path_policy import resolve_within, safe_filename_fragment

if TYPE_CHECKING:
    from core.runtime_context import RuntimeContext


_ACTIVE_RUNTIME_CONTEXT: ContextVar[RuntimeContext | None] = ContextVar(
    "pawnlogic_runtime_context",
    default=None,
)
_ACTIVE_LEGACY_MIRROR: ContextVar[bool] = ContextVar(
    "pawnlogic_runtime_context_legacy_mirror",
    default=True,
)


def current_runtime_context() -> RuntimeContext | None:
    """Return the context active in the current thread or async task."""
    return _ACTIVE_RUNTIME_CONTEXT.get()


def active_runtime_context_mirrors_legacy() -> bool:
    """Return whether the active context may update legacy process globals."""
    context = current_runtime_context()
    return context is None or (
        bool(_ACTIVE_LEGACY_MIRROR.get()) and not context.isolated_workspace
    )


def context_allows_legacy_mirror(context: RuntimeContext) -> bool:
    """Return whether a context may update compatibility mirrors now."""
    active = current_runtime_context()
    if active is None:
        return not context.isolated_workspace
    return active is context and active_runtime_context_mirrors_legacy()


@contextmanager
def activate_runtime_context(
    context: RuntimeContext,
    *,
    mirror_legacy: bool | None = None,
) -> Iterator[RuntimeContext]:
    """Activate one context and restore the enclosing compatibility mirror."""
    mirror = bool(mirror_legacy) if mirror_legacy is not None else not context.isolated_workspace
    mirror = mirror and not context.isolated_workspace
    token = _ACTIVE_RUNTIME_CONTEXT.set(context)
    mirror_token = _ACTIVE_LEGACY_MIRROR.set(mirror)
    if mirror:
        context.sync_legacy_state()
    try:
        yield context
    finally:
        _ACTIVE_RUNTIME_CONTEXT.reset(token)
        _ACTIVE_LEGACY_MIRROR.reset(mirror_token)
        previous = current_runtime_context()
        if mirror and previous is not None and context_allows_legacy_mirror(previous):
            previous.sync_legacy_state()


def fork_task_context(
    parent: RuntimeContext,
    task: Any = None,
    *,
    sink: Any = None,
    task_id: str | None = None,
) -> RuntimeContext:
    """Build an isolated child context under the parent's task workspace."""
    if task is not None and task_id is not None:
        raise TypeError("pass task or task_id, not both")
    raw_task_id = task_id if task_id is not None else getattr(task, "task_id", task)
    if not isinstance(raw_task_id, str):
        raise TypeError("task or task.task_id must be a string")

    parent_workspace = Path(parent.workspace_dir).expanduser().resolve()
    parent_workspace.mkdir(parents=True, exist_ok=True)
    task_root = resolve_within(parent_workspace, parent_workspace / ".tasks")
    task_root.mkdir(parents=True, exist_ok=True)
    child_workspace = Path(
        mkdtemp(prefix=f"{_task_workspace_fragment(raw_task_id)}-", dir=task_root)
    )
    child_workspace = resolve_within(parent_workspace, child_workspace)

    return type(parent)(
        cwd=str(child_workspace),
        workspace_dir=str(child_workspace),
        sink=parent.sink if sink is None else sink,
        debug_mode=parent.debug_mode,
        user_mode=parent.user_mode,
        dynamic_config=dict(parent.dynamic_config),
        session_id=parent.session_id,
        agent_id=parent.agent_id,
        active_turn_id=parent.active_turn_id,
        isolated_workspace=True,
    )


def _task_workspace_fragment(task_id: str) -> str:
    """Return a bounded safe directory-name fragment for a task identifier."""
    safe = safe_filename_fragment(task_id, fallback="task")[:80]
    digest = sha256(task_id.encode("utf-8", errors="surrogatepass")).hexdigest()[:12]
    return f"{safe}-{digest}"


__all__ = [
    "activate_runtime_context",
    "active_runtime_context_mirrors_legacy",
    "context_allows_legacy_mirror",
    "current_runtime_context",
    "fork_task_context",
]
