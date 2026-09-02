"""Immutable persistence contract for a PawnLogic session."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


SESSION_SNAPSHOT_SCHEMA = 1


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
    schema_version: int = SESSION_SNAPSHOT_SCHEMA

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
        schema_version: int = SESSION_SNAPSHOT_SCHEMA,
    ) -> SessionSnapshot:
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version != SESSION_SNAPSHOT_SCHEMA
        ):
            raise ValueError(
                f"unsupported session snapshot schema: {schema_version!r}"
            )
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
            schema_version=schema_version,
        )


__all__ = ["SESSION_SNAPSHOT_SCHEMA", "SessionSnapshot"]
