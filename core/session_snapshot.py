"""Immutable persistence contract for a PawnLogic session."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    session_id: str
    model_alias: str
    messages: tuple[dict[str, Any], ...]
    runtime: dict[str, Any]

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
        )


__all__ = ["SessionSnapshot"]
