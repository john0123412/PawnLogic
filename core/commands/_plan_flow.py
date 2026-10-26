"""The plan-protocol half of ``/provider``: ``/provider plan <name> [on|off]``.

Kept out of ``core/commands/provider.py`` for the reason ``_effort_flow.py`` is:
that file sits on its architecture budget, and a one-token switch for one
capability does not belong in a dispatcher.  Like the effort opt-in it is a
command and not a row of the provider TUI form: Add and Edit are one renderer,
and a new row is a known way to make a locked field reachable.

The switch lives in ``custom_providers.json`` (``config/providers.py``
``set_provider_plan_protocol``), which refuses built-in names and never creates
an entry.  What it changes is described in ``core/plan_protocol.py``.
"""

from __future__ import annotations

from core.commands._common import sink_print as _print
from utils.ansi import GRAY, GREEN, RED, c

USAGE = "  Usage: /provider plan <name> [on|off]"


def _describe(enabled: bool) -> str:
    return "on" if enabled else "off"


def set_provider_plan_protocol(arg: str) -> None:
    """Handle ``/provider plan <name> [on|off]``.

    ``/provider plan <name>`` only reports the current state, for built-in
    providers too (it is always on there).  ``handle_slash`` splits the line as
    ``verb arg arg2``, so ``arg`` here is the ``<name> [on|off]`` remainder that
    ``/provider`` forwards.
    """
    import config.providers as provider_config

    parts = (arg or "").split()
    state = parts[1].lower() if len(parts) == 2 else ""
    if not parts or len(parts) > 2 or (state and state not in ("on", "off")):
        _print(c(RED, USAGE))
        return
    name = parts[0]
    if name not in provider_config.PROVIDERS:
        _print(c(RED, f"  ✗ Unknown provider '{name}'"))
        return

    if not state:
        current = provider_config.provider_plan_protocol(name)
        _print(f"  plan protocol for '{name}': {c(GREEN if current else GRAY, _describe(current))}")
        if name in provider_config.BUILTIN_PROVIDER_NAMES:
            _print(c(GRAY, "    Built-in providers always use the plan protocol."))
        elif current:
            _print(c(GRAY, "    Its models are asked for a <plan> before tool calls, and the plan guard enforces it."))
        else:
            _print(c(GRAY, "    Its models are not asked for a <plan>; the plan guard does not flag missing plans."))
        return

    if name in provider_config.BUILTIN_PROVIDER_NAMES:
        # Refused rather than silently written: the setting persists into
        # custom_providers.json, where an entry without base_url/api_key_env
        # invalidates the entire file, and the loader skips built-in names.
        _print(c(RED, f"  ✗ '{name}' is a built-in provider; it always uses the plan protocol"))
        _print(c(GRAY, "    This command switches the plan protocol for a custom provider only."))
        return

    enabled = state == "on"
    if not provider_config.set_provider_plan_protocol(name, enabled):
        _print(c(RED, f"  ✗ Could not update the plan protocol for '{name}'"))
        _print(c(GRAY, "    It must be a custom provider already saved with a base URL and an API key name."))
        return
    _print(c(GREEN, f"  ✓ plan protocol {_describe(enabled)} for provider '{name}'"))
    if enabled:
        _print(c(GRAY, "    Its models are asked for a <plan> before tool calls again; the plan guard enforces it."))
    else:
        _print(c(GRAY, "    Its models are no longer asked for a <plan>, and the plan guard stops flagging missing"))
        _print(c(GRAY, "    plans (/planguard has nothing to enforce for them). Takes effect on the next turn."))


__all__ = ["USAGE", "set_provider_plan_protocol"]
