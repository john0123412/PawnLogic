"""Slash commands for inspecting and managing optional Extensions."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from core.commands import CommandContext, register


_USAGE = "Usage: /extension [list|status [name]|enable <name>|disable <name>]"
_SECRET_VALUE_RE = re.compile(
    r"(?i)((?:api[_-]?key|access[_-]?key|token|password|passwd|secret|private[_-]?key)"
    r"\s*[:=]\s*)[^\s,;]+"
)


def _safe_error(error: object) -> str:
    """Render one short, redacted line suitable for a user-facing sink."""
    if error is None:
        return ""
    if isinstance(error, BaseException):
        text = f"{error.__class__.__name__}: {error}"
    else:
        text = str(error)
    if "traceback" in text.lower():
        return "operation failed"
    text = _SECRET_VALUE_RE.sub(r"\1<redacted>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:240] or "operation failed"


def _state(status: object) -> str:
    value = getattr(status, "state", getattr(status, "status", "unknown"))
    value = getattr(value, "value", value)
    return str(value).strip().lower() or "unknown"


def _status_name(status: object, fallback: str = "<unknown>") -> str:
    value = getattr(status, "name", fallback)
    return str(value).strip() or fallback


def _write(ctx: CommandContext, message: str) -> None:
    """Write through the command sink, including direct handler tests."""
    sink = ctx.sink
    if sink is None:
        from core.commands._common import sink_print

        sink_print(message)
    else:
        sink.print(message)


def _manager(ctx: CommandContext) -> Any:
    session = getattr(ctx, "session", None)
    runtime_context = getattr(session, "runtime_context", None)
    return getattr(runtime_context, "extension_manager", None)


def _parts(ctx: CommandContext) -> list[str]:
    values: list[str] = []
    if ctx.arg.strip():
        values.append(ctx.arg.strip())
    if ctx.arg2.strip():
        values.extend(ctx.arg2.strip().split())
    return values


def _render_list(ctx: CommandContext, statuses: Iterable[object]) -> None:
    rows = list(statuses)
    if not rows:
        _write(ctx, "No Extensions discovered.")
        return
    _write(ctx, "Extensions:")
    for status in rows:
        line = f"  {_status_name(status):24} {_state(status)}"
        error = _safe_error(getattr(status, "error", None))
        if error:
            line += f" — {error}"
        _write(ctx, line)


def _render_operation(ctx: CommandContext, action: str, requested_name: str, status: object) -> None:
    if status is None:
        _write(ctx, f"✗ Unable to {action} '{requested_name}' — state: unavailable")
        return
    name = _status_name(status, requested_name)
    state = _state(status)
    error = _safe_error(getattr(status, "error", None))
    failed = bool(error) or state in {"failed", "unavailable"}
    if failed:
        detail = f"; error: {error}" if error else ""
        _write(ctx, f"✗ Unable to {action} '{name}' — state: {state}{detail}")
        return
    _write(ctx, f"✓ Extension '{name}' — state: {state}")


def _render_unavailable(ctx: CommandContext) -> None:
    _write(ctx, "Extension manager is unavailable. Extensions cannot be managed.")


@register("/extension")
async def cmd_extension(ctx: CommandContext) -> None:
    """List, inspect, enable, or disable optional Extensions."""
    manager = _manager(ctx)
    if manager is None:
        _render_unavailable(ctx)
        return

    parts = _parts(ctx)
    action = parts[0].lower() if parts else "list"

    if action in {"list", "status"}:
        if len(parts) > 2 or (action == "list" and len(parts) > 1):
            _write(ctx, _USAGE)
            return
        requested_name = parts[1] if len(parts) == 2 else None
        try:
            statuses = manager.status(requested_name)
        except Exception as error:
            _write(ctx, f"Unable to read Extension status: {_safe_error(error)}")
            return
        if requested_name is None:
            _render_list(ctx, statuses)
        else:
            _render_operation(ctx, "inspect", requested_name, statuses[0] if statuses else None)
        return

    if action in {"enable", "disable"}:
        if len(parts) != 2:
            _write(ctx, _USAGE)
            return
        requested_name = parts[1]
        try:
            status = getattr(manager, action)(requested_name)
        except Exception as error:
            _write(ctx, f"✗ Unable to {action} '{requested_name}' — error: {_safe_error(error)}")
            return
        _render_operation(ctx, action, requested_name, status)
        return

    _write(ctx, _USAGE)


__all__ = ["cmd_extension"]
