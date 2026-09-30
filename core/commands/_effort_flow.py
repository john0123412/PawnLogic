"""The reasoning-effort half of the model-selection flow.

``/model`` selects a model and then, in the same interaction, the level
that model should run at.  The two halves are kept apart on purpose:
``core/commands/provider.py`` owns the model, this module owns what
happens once a model is chosen.

Splitting them is not cosmetic.  ``provider.py`` sits exactly on its
architecture budget, so every line of the chained flow added to it had
to come from somewhere.  It also keeps the rule that is easy to get
wrong in one place: a level is only *sent* for a model that declares
support, and a level that is not sent must never be presented as if it
had been.  Both selectors and the ``/limits`` footer use the same
wording from ``config.tiers.effort_delivery`` for that reason.
"""

from __future__ import annotations

from typing import Any

from config.tiers import EFFORT_LEVELS, is_effort_level
from core.commands._common import sink_print as _print
from utils.ansi import GRAY, GREEN, RED, YELLOW, c


def current_level() -> str:
    """Return the active effort level, falling back to the default."""
    from config import DEFAULT_EFFORT_LEVEL
    from core.state import runtime_config

    return str(runtime_config().get("effort_level") or DEFAULT_EFFORT_LEVEL)


def delivery(model_alias: str, level: str) -> str:
    """Describe where ``level`` is actually applied for ``model_alias``."""
    from core.api_payloads import model_effort_map
    from config.tiers import effort_delivery as _describe

    return _describe(model_effort_map(model_alias), model_alias, level)


def report_current(model_alias: str, *, show_level: bool) -> None:
    """Print the active level without opening a selector.

    ``show_level`` adds the ``effort=<level>`` prefix used on the
    no-op path, where the user asked to change something and the answer
    is that the level did not need to.
    """
    level = current_level()
    prefix = f"effort={level}  " if show_level else ""
    _print(c(GRAY, f"    {prefix}({delivery(model_alias, level)})"))


async def offer_effort_after_model(ctx: Any, alias: str) -> None:
    """Offer the effort level for a model the user just selected.

    Skipped for a model that declares no ``reasoning_effort`` support:
    the level would still move the local limits, but there is nothing to
    negotiate with the provider, so a prompt would be noise.  ``/effort``
    still reaches those models.

    Any failure here is non-fatal by design.  The model switch has
    already happened and been reported; failing the whole command here
    would tell the user their model did not change when it did.
    """
    from core.api_payloads import model_effort_map
    from core.commands.system import (
        _effort_tui_available,
        _select_effort_level,
        apply_effort,
    )

    if not model_effort_map(alias):
        report_current(alias, show_level=True)
        return

    controller = getattr(ctx, "terminal_controller", None)
    # A controller that exists but cannot host a selector is worse than
    # none: resolving one would run a second Application and corrupt
    # cursor state (ADR 0010), so it is treated as absent.
    use_controller = (
        controller is not None and getattr(controller, "run_selector", None) is not None
    )
    if not use_controller and not _effort_tui_available():
        _print(
            c(
                GRAY,
                "  Pick a reasoning effort with /effort, or /model <alias> <effort>.",
            )
        )
        return

    current = current_level()
    try:
        if use_controller:
            from pawnlogic.selectors import EffortSelector

            selected = await controller.run_selector(
                lambda: EffortSelector(current, alias)
            )
        else:
            selected = await _select_effort_level(current, alias)
    except (EOFError, KeyboardInterrupt):
        selected = None
    except Exception:
        _print(c(YELLOW, "  Effort selector unavailable; use /effort <level>."))
        return

    if selected is None:
        _print(c(GRAY, f"  Effort unchanged ({current})."))
        return
    apply_effort(ctx, selected)


def apply_scripted_effort(ctx: Any, level: str) -> bool:
    """Apply an explicitly typed level, reporting an unknown one.

    Returns whether the level was accepted.  The caller must check this
    *before* switching models, so a typo does not leave the session on a
    model the user did not intend to move to.
    """
    from core.commands.system import apply_effort

    level = (level or "").strip().lower()
    if not is_effort_level(level):
        _print(c(RED, f"  ✗ Unknown effort level: {level}"))
        _print(c(GRAY, f"  Levels: {' / '.join(EFFORT_LEVELS)}"))
        return False
    apply_effort(ctx, level)
    return True


def set_provider_effort_support(arg: str) -> None:
    """Handle ``/provider effort <name> on|off``.

    Opt-in lives in ``custom_providers.json`` rather than in the
    provider TUI form on purpose: Add and Edit are one renderer, and
    adding a row to it is a known way to make a locked field
    reachable.  A one-token opt-in is not worth that risk.
    """
    import config.providers as provider_config

    parts = (arg or "").split()
    if not parts:
        _print(c(RED, "  Usage: /provider effort <name> on|off"))
        return
    name = parts[0]
    if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
        _print(c(RED, "  Usage: /provider effort <name> on|off"))
        return
    if name not in provider_config.PROVIDERS:
        _print(c(RED, f"  ✗ Unknown provider '{name}'"))
        return
    if name in provider_config.BUILTIN_PROVIDER_NAMES:
        # Refused rather than silently written: the opt-in lands in
        # custom_providers.json, where an entry without base_url/api_key_env
        # invalidates the entire file.  Built-in models already declare their
        # own effort support per model.
        _print(
            c(
                RED,
                f"  ✗ '{name}' is a built-in provider; each of its models declares"
                " its own effort support",
            )
        )
        _print(c(GRAY, "    This command opts in a custom provider only."))
        _print(c(GRAY, "    Use /effort <level> to choose the level for the current model."))
        return

    enabled = parts[1].lower() == "on"
    if not provider_config.set_provider_reasoning_effort(name, enabled):
        _print(c(RED, f"  ✗ Could not update reasoning-effort support for '{name}'"))
        return
    _print(
        c(
            GREEN,
            f"  ✓ reasoning_effort {'enabled' if enabled else 'disabled'} for provider '{name}'",
        )
    )
    if enabled:
        _print(
            c(
                GRAY,
                "    Its models will now receive reasoning_effort for /effort levels.",
            )
        )
    else:
        _print(c(GRAY, "    Effort levels still apply local runtime limits only."))


__all__ = [
    "apply_scripted_effort",
    "current_level",
    "delivery",
    "offer_effort_after_model",
    "report_current",
    "set_provider_effort_support",
]
