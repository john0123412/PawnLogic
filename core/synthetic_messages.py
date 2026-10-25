"""Recognise user-role messages that the framework, not a person, injected.

The agent loop appends user-role messages nobody typed: plan corrections, the
plan-only recovery nudge, the empty-response notice, anti-loop hints, the
periodic logic-refresh request, the urgent-mode notice.  They are protocol, not
conversation.  Anything that counts turns by counting user messages -- the
history-summary trigger, the budget trimmer's turn groups -- must not count
them, or one real prompt that needed two recovery nudges is counted as three
turns and the history summary fires early.

Every injected message begins with a fixed marker.  This module owns that list
so each counter shares one definition instead of keeping a private prefix check.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Leading markers of framework-injected user messages.  The producers are
#: ``core.plan_guard`` (``[SYSTEM: PLAN_*]``), ``core.session`` (urgent mode,
#: empty-response notice, logic refresh) and ``core.tool_result`` (anti-loop).
SYNTHETIC_USER_PREFIXES: tuple[str, ...] = (
    "[SYSTEM:",
    "[System]",
    "[Logic Refresh",
)


def is_synthetic_user_message(message: Mapping[str, Any]) -> bool:
    """Return whether ``message`` is a user-role message the framework injected."""
    if message.get("role") != "user":
        return False
    content = message.get("content")
    return isinstance(content, str) and content.startswith(SYNTHETIC_USER_PREFIXES)


def starts_user_turn(message: Mapping[str, Any]) -> bool:
    """Return whether ``message`` is a user message a person typed.

    Only these start a turn.  A synthetic message belongs to the turn it was
    injected into.
    """
    return message.get("role") == "user" and not is_synthetic_user_message(message)


__all__ = ["SYNTHETIC_USER_PREFIXES", "is_synthetic_user_message", "starts_user_turn"]
