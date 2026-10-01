"""Context window sizing and message cleanup helpers.

The single compaction path lives in ``core.context_manager.ContextManager``:
it bounds the per-request provider view without mutating canonical history.
There is deliberately no second, history-rewriting compaction path here —
the previous ``_trim_and_compact_context`` (tool-output placeholders plus
100-character truncation merged into canonical history) was dead code that
silently disagreed with the live path and destroyed exact values (addresses,
offsets) the summary path is required to preserve.

Budgets are denominated in estimated tokens (see ``core.token_estimate``);
``resolve_context_budget`` reads the token-denominated config keys and
derives them from the legacy character keys when a stale snapshot predates
the switch.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.message_history import repair_dangling_tool_calls
from core.token_estimate import estimate_tokens


def _ctx_tokens(msgs: list) -> int:
    # Reasoning content must count toward the real context budget.
    return sum(
        estimate_tokens(str(m.get("content") or ""))
        + estimate_tokens(str(m.get("reasoning_content") or ""))
        for m in msgs
    )


# Mixed-content characters-per-token factor used only to translate legacy
# character-denominated config into token estimates. English/code runs near
# 4 chars/token and CJK near 1, so 3 sits at the conservative middle.
_LEGACY_CHARS_PER_TOKEN = 3
_MIN_TOKEN_BUDGET = 1000
_MIN_TOKEN_TRIM = 500


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def resolve_context_budget(cfg: Mapping[str, Any]) -> tuple[int, int]:
    """Return ``(max_tokens, trim_tokens)`` from a dynamic config mapping.

    ``ctx_max_tokens``/``ctx_trim_tokens`` are authoritative and resolve
    per key, so a config that overrides only one of them keeps the other
    from its source. Session snapshots written before token budgeting carry
    only the legacy ``ctx_max_chars``/``ctx_trim_to`` keys; those are
    converted with the mixed-content factor above instead of failing with a
    ``KeyError``. A missing trim value inherits the max budget.
    """
    try:
        max_tokens = _int_or_none(cfg.get("ctx_max_tokens"))
        trim_tokens = _int_or_none(cfg.get("ctx_trim_tokens"))
        legacy_max = _int_or_none(cfg.get("ctx_max_chars"))
        legacy_trim = _int_or_none(cfg.get("ctx_trim_to"))
    except (TypeError, ValueError):
        return 48_000, 36_000

    if max_tokens is None:
        if legacy_max is not None:
            max_tokens = max(_MIN_TOKEN_BUDGET, legacy_max // _LEGACY_CHARS_PER_TOKEN)
        else:
            max_tokens = 48_000
    if trim_tokens is None:
        if legacy_trim is not None:
            trim_tokens = max(
                _MIN_TOKEN_TRIM, legacy_trim // _LEGACY_CHARS_PER_TOKEN
            )
        else:
            trim_tokens = max_tokens
    if trim_tokens > max_tokens:
        trim_tokens = max_tokens
    return max_tokens, trim_tokens


def migrate_legacy_context_budget(cfg: dict) -> bool:
    """Convert legacy character-denominated context keys in place to tokens.

    Session snapshots saved before token budgeting carry
    ``ctx_max_chars``/``ctx_trim_to``. Converting at LOAD time (before the
    snapshot merges into a runtime config already seeded with token
    defaults) is what keeps the saved budget authoritative: a plain merge
    would leave both key sets present, and the preset's token defaults
    would mask the user's saved character budget. Legacy keys are removed
    so a later ``/ctx`` token write can never be shadowed by them.
    Returns True when a conversion happened.
    """
    legacy_max = cfg.get("ctx_max_chars")
    if legacy_max is None:
        return False
    legacy_cfg = {"ctx_max_chars": legacy_max, "ctx_trim_to": cfg.get("ctx_trim_to")}
    try:
        max_tokens, trim_tokens = resolve_context_budget(legacy_cfg)
    except Exception:
        return False
    cfg["ctx_max_tokens"] = max_tokens
    cfg["ctx_trim_tokens"] = trim_tokens
    cfg.pop("ctx_max_chars", None)
    cfg.pop("ctx_trim_to", None)
    return True


def _drop_dangling_tool_call_messages(msgs: list) -> list:
    """Return a copy without assistant tool calls that lack matching tool output."""
    return repair_dangling_tool_calls(msgs)
