"""Immutable persistence contract for a PawnLogic session."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    session_id: str
    model_alias: str
    messages: tuple[dict[str, Any], ...]
    runtime: dict[str, Any]
    status: str = "idle"
    interrupted_at: str | None = field(default=None)
    queue_depth: int = 0
    queue_state: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def capture(
        cls,
        *,
        session_id: str,
        model_alias: str,
        messages: list[dict[str, Any]],
        cwd: str,
        workspace_dir: str,
        config: dict[str, Any],
        status: str = "idle",
        interrupted_at: str | None = None,
        queue_depth: int = 0,
        queue_state: dict[str, Any] | None = None,
    ) -> SessionSnapshot:
        return cls(
            session_id=session_id,
            model_alias=model_alias,
            messages=tuple(dict(message) for message in messages),
            runtime={
                "cwd": cwd,
                "workspace_dir": workspace_dir,
                "config": dict(config),
            },
            status=status,
            interrupted_at=interrupted_at,
            queue_depth=queue_depth,
            queue_state=deepcopy(queue_state) if queue_state else {},
        )


__all__ = ["SessionSnapshot"]
