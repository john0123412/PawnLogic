"""
Slash command dispatch framework.

Command handlers are organized by theme into modules under this package
(system / session / provider / workspace / tools). Each module declares
its handlers with the `@register("/verb")` decorator at import time, and
`dispatch(ctx)` looks them up in the global `COMMANDS` dict.

Public API:
    - CommandContext: dataclass passed to every command handler
    - register(*verbs): decorator that binds verbs to a handler
    - dispatch(ctx): main entry point called by main.py's `handle_slash`
    - COMMANDS: the registry, exposed for introspection
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass
class CommandContext:
    """Context passed to every slash command handler.

    Attributes:
        verb:    The lowercased slash command, e.g. "/help".
        arg:     First positional argument after the verb (may be empty).
        arg2:    Remainder of the line after `arg` (may be empty).
        session: The active AgentSession instance.
        sink:    Output sink (HumanSink or JsonSink). If left as None,
                 `dispatch()` will inject the process-wide active sink
                 from `core.commands._common.get_active_sink()` before
                 invoking the handler.
    """
    verb: str
    arg: str
    arg2: str
    session: Any  # AgentSession; kept loose to avoid circular import
    sink: Any = None  # HumanSink | JsonSink; populated by dispatch()


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
# Dispatch
# ────────────────────────────────────────────────────────
async def dispatch(ctx: CommandContext) -> Any:
    """Route a slash command to its handler.

    Looks up `ctx.verb` in COMMANDS (populated by @register decorators).
    If unknown, prints a friendly error consistent with the legacy
    behavior and returns None.

    If `ctx.sink` is None, the process-wide active sink (set once by
    main() at startup) is injected so handlers can rely on it.
    """
    if ctx.sink is None:
        from core.commands._common import get_active_sink
        ctx.sink = get_active_sink()

    handler = COMMANDS.get(ctx.verb)
    if handler is not None:
        return await handler(ctx)

    # Unknown verb — match legacy behavior of printing a hint.
    from utils.ansi import c, GRAY
    print(c(GRAY, f"  未知命令 '{ctx.verb}'，输入 /help"))
    return None


# ────────────────────────────────────────────────────────
# Eagerly load command modules so their @register decorators fire.
# Order matters only insofar as later modules can override earlier ones
# (which they should not, in practice).
# ────────────────────────────────────────────────────────
from . import system  # noqa: E402, F401
from . import session  # noqa: E402, F401
from . import provider  # noqa: E402, F401
from . import workspace  # noqa: E402, F401
from . import tools  # noqa: E402, F401


__all__ = [
    "CommandContext",
    "register",
    "dispatch",
    "COMMANDS",
]
