"""
Slash command dispatch framework.

This package will eventually contain all slash command handlers organized by
theme (system/session/provider/workspace/tools). During the migration
(stage 1 of the main.py refactor), the monolithic dispatcher in main.py
registers itself via `set_legacy_dispatcher` and `dispatch` falls back to it
for verbs that have not yet been migrated. As individual commands move into
their own modules in `core/commands/<theme>.py`, they declare themselves with
the `@register("/verb")` decorator and the legacy fallback shrinks.

Public API:
    - CommandContext: dataclass passed to every command handler
    - register(*verbs): decorator that binds verbs to a handler
    - dispatch(ctx): main entry point called by main.py's `handle_slash`
    - set_legacy_dispatcher(fn): migration hook (temporary)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional


@dataclass
class CommandContext:
    """Context passed to every slash command handler.

    Attributes:
        verb:    The lowercased slash command, e.g. "/help".
        arg:     First positional argument after the verb (may be empty).
        arg2:    Remainder of the line after `arg` (may be empty).
        session: The active AgentSession instance.
    """
    verb: str
    arg: str
    arg2: str
    session: Any  # AgentSession; kept loose to avoid circular import


# ────────────────────────────────────────────────────────
# Command registry
# ────────────────────────────────────────────────────────
Handler = Callable[[CommandContext], Awaitable[Any]]
COMMANDS: dict[str, Handler] = {}


def register(*verbs: str) -> Callable[[Handler], Handler]:
    """Decorator: bind one or more verbs to a single async handler.

    Example:
        @register("/exit", "/quit", "/q")
        async def cmd_exit(ctx: CommandContext):
            return EXIT_SENTINEL
    """
    def deco(fn: Handler) -> Handler:
        for v in verbs:
            COMMANDS[v] = fn
        return fn
    return deco


# ────────────────────────────────────────────────────────
# Migration hook (temporary)
# ────────────────────────────────────────────────────────
_LEGACY_DISPATCHER: Optional[Handler] = None


def set_legacy_dispatcher(fn: Handler) -> None:
    """Register the monolithic legacy dispatcher.

    Called once from main.py during stage-1 migration. Once all commands
    have been extracted, this function and its global will be removed.
    """
    global _LEGACY_DISPATCHER
    _LEGACY_DISPATCHER = fn


# ────────────────────────────────────────────────────────
# Dispatch
# ────────────────────────────────────────────────────────
async def dispatch(ctx: CommandContext) -> Any:
    """Route a slash command to its handler.

    Order:
      1. Look up `ctx.verb` in COMMANDS (populated by @register decorators).
      2. If no match, fall back to the legacy dispatcher in main.py.

    Raises RuntimeError only if neither a registered handler nor the
    legacy fallback is available, which should be impossible in normal use.
    """
    handler = COMMANDS.get(ctx.verb)
    if handler is not None:
        return await handler(ctx)

    if _LEGACY_DISPATCHER is None:
        raise RuntimeError(
            f"No handler for {ctx.verb!r} and no legacy dispatcher registered."
        )
    return await _LEGACY_DISPATCHER(ctx)


# ────────────────────────────────────────────────────────
# Eagerly load command modules so their @register decorators fire.
# Order matters only insofar as later modules can override earlier ones
# (which they should not, in practice).
# ────────────────────────────────────────────────────────
from . import system  # noqa: E402, F401


__all__ = [
    "CommandContext",
    "register",
    "dispatch",
    "set_legacy_dispatcher",
    "COMMANDS",
]
