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
from collections.abc import Iterable, Mapping
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
                 `dispatch()` uses the session RuntimeContext sink first,
                 then the process-wide compatibility fallback.
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
_COMMAND_OWNERS: dict[str, str] = {}


def _normalize_verb(verb: str) -> str:
    """Validate the canonical slash-command spelling."""
    if not isinstance(verb, str) or not verb.startswith("/"):
        raise ValueError(f"command verb must start with '/': {verb!r}")
    return verb


def register_owned_commands(
    owner: str,
    handlers: Mapping[str, Handler] | Iterable[tuple[str, Handler]],
) -> None:
    """Atomically register commands owned by ``owner``.

    Registration validates the complete batch before changing ``COMMANDS``.
    Existing commands, including built-ins, are never overwritten.  The
    iterable form is intentional: it lets callers preserve declaration order
    and lets the validation reject duplicate verbs within one batch.
    """
    if not isinstance(owner, str) or not owner:
        raise ValueError("command owner must be a non-empty string")

    if isinstance(handlers, Mapping):
        entries = list(handlers.items())
    else:
        try:
            entries = list(handlers)
        except TypeError as exc:
            raise TypeError("handlers must be a mapping or iterable of pairs") from exc

    normalized: list[tuple[str, Handler]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise TypeError("each command handler entry must be a (verb, handler) pair")
        verb, handler = entry
        verb = _normalize_verb(verb)
        if verb in seen:
            raise ValueError(f"duplicate command verb in batch: {verb}")
        if verb in COMMANDS:
            existing_owner = _COMMAND_OWNERS.get(verb, "unknown")
            raise ValueError(
                f"command verb already registered: {verb} (owner={existing_owner})"
            )
        if not callable(handler):
            raise TypeError(f"command handler must be callable: {verb}")
        seen.add(verb)
        normalized.append((verb, handler))

    for verb, handler in normalized:
        COMMANDS[verb] = handler
        _COMMAND_OWNERS[verb] = owner


def unregister_owned_commands(owner: str) -> None:
    """Remove only commands currently owned by ``owner``."""
    if not isinstance(owner, str) or not owner:
        raise ValueError("command owner must be a non-empty string")

    for verb, command_owner_name in list(_COMMAND_OWNERS.items()):
        if command_owner_name == owner:
            COMMANDS.pop(verb, None)
            _COMMAND_OWNERS.pop(verb, None)


def command_owner(verb: str) -> str | None:
    """Return the owner of a registered verb, or ``None`` when unknown."""
    return _COMMAND_OWNERS.get(_normalize_verb(verb))


def register(*verbs: str) -> Callable[[Handler], Handler]:
    """Decorator: bind one or more verbs to a single async handler.

    Example:
        @register("/exit", "/quit", "/q")
        async def cmd_exit(ctx: CommandContext):
            return EXIT_SENTINEL
    """
    def deco(fn: Handler) -> Handler:
        register_owned_commands("builtin", ((verb, fn) for verb in verbs))
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

    The owning session RuntimeContext is active while the handler runs. If
    `ctx.sink` is None, its sink is preferred over the process-wide fallback.
    """
    from contextlib import nullcontext

    runtime_context = getattr(ctx.session, "runtime_context", None)
    activation = runtime_context.activate() if runtime_context is not None else nullcontext()

    with activation:
        if ctx.sink is None:
            from core.commands._common import get_active_sink
            ctx.sink = get_active_sink()

        handler = COMMANDS.get(ctx.verb)
        if handler is not None:
            from core.commands._common import set_active_sink, swap_active_sink
            old_sink = swap_active_sink(ctx.sink)
            try:
                return await handler(ctx)
            finally:
                set_active_sink(old_sink)

        # Unknown verb - match legacy behavior of printing a hint.
        from utils.ansi import c, GRAY
        ctx.sink.print(c(GRAY, f"  Unknown command '{ctx.verb}'. Type /help."))
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
from . import ctf  # noqa: E402, F401
from . import extensions  # noqa: E402, F401


__all__ = [
    "CommandContext",
    "register",
    "register_owned_commands",
    "unregister_owned_commands",
    "command_owner",
    "dispatch",
    "COMMANDS",
]
