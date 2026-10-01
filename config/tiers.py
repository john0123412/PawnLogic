"""config/tiers.py - runtime tier presets and the reasoning-effort ladder."""

TIER_LOW = {
    "max_tokens":      4_096,
    "ctx_max_tokens":  16_000,
    "ctx_trim_tokens": 12_000,
    "max_iter":        10,
    "tool_max_chars":   6_000,
    "fetch_max_chars":  8_000,
    "preferred_worker": "auto",
    "time_budget_sec":  300,
    "ctx_sliding_turns": 4,
    "ctx_summary_threshold": 6,
    "plan_guard_mode":  "advisory",
}
TIER_MID = {
    "max_tokens":      8_192,
    "ctx_max_tokens":  48_000,
    "ctx_trim_tokens": 36_000,
    "max_iter":        30,
    "tool_max_chars":   15_000,
    "fetch_max_chars":  20_000,
    "preferred_worker": "auto",
    "time_budget_sec":  600,
    "ctx_sliding_turns": 5,
    "ctx_summary_threshold": 8,
    "plan_guard_mode":  "advisory",
}
TIER_DEEP = {
    "max_tokens":      32_768,
    "ctx_max_tokens":  96_000,
    "ctx_trim_tokens": 72_000,
    "max_iter":        50,
    "tool_max_chars":   20_000,
    "fetch_max_chars":  30_000,
    "preferred_worker": "auto",
    "time_budget_sec":  1800,
    "ctx_sliding_turns": 8,
    "ctx_summary_threshold": 12,
    "plan_guard_mode":  "advisory",
}
TIER_MAX = {
    "max_tokens":      32_768,
    "ctx_max_tokens":  128_000,
    "ctx_trim_tokens":  96_000,
    "max_iter":        100,
    "tool_max_chars":   30_000,
    "fetch_max_chars":  40_000,
    "preferred_worker": "auto",
    "time_budget_sec":  3600,
    "ctx_sliding_turns": 10,
    "ctx_summary_threshold": 15,
    "plan_guard_mode":  "advisory",
}
TIER_ULTRA = {
    **TIER_MAX,
    "max_iter":        150,
}


# Reasoning-effort ladder.
#
# The effort level is the single user-facing knob: it selects both the
# ``reasoning_effort`` wire value and a full set of runtime limits.  The
# ladder reuses the tier presets rather than replacing them, so a level
# always describes a complete, internally consistent configuration.
#
# ``off`` and ``low`` share TIER_LOW on purpose.  Turning reasoning off and
# reasoning cheaply are the same budget decision; they differ only in what
# is sent to the provider.
#
# The top level maps to TIER_ULTRA rather than TIER_MAX so the 150-iteration
# ceiling survives the merge.  There is no separate ``ultra`` rung any more,
# and dropping the ceiling would take away capability the user already had.
EFFORT_LEVELS: tuple[str, ...] = ("off", "low", "medium", "high", "xhigh", "max")

DEFAULT_EFFORT_LEVEL = "medium"

_EFFORT_TIER_SOURCE: dict[str, dict] = {
    "off":    TIER_LOW,
    "low":    TIER_LOW,
    "medium": TIER_MID,
    "high":   TIER_DEEP,
    "xhigh":  TIER_MAX,
    "max":    TIER_ULTRA,
}

# The runtime limits each level applies, tagged with the level itself so the
# active level travels inside the same dict as the limits it selected.
EFFORT_PRESETS: dict[str, dict] = {
    level: {**tier, "effort_level": level}
    for level, tier in _EFFORT_TIER_SOURCE.items()
}

# Default wire value per level.  A model opts into sending by declaring its own
# ``effort`` map; a model that declares nothing is never sent this field, so
# an OpenAI-compatible relay that rejects the parameter cannot cause a 400.
EFFORT_WIRE_VALUES: dict[str, str] = {
    "off":    "none",
    "low":    "low",
    "medium": "medium",
    "high":   "high",
    "xhigh":  "xhigh",
    "max":    "max",
}


def is_effort_level(value: object) -> bool:
    """Return whether ``value`` names a reasoning-effort level."""
    return isinstance(value, str) and value in EFFORT_PRESETS


def effort_options(accepted: dict) -> tuple[tuple[str, str, str], ...]:
    """Build the ``(level, label, description)`` rows both selectors render.

    Each row states the runtime limits the level selects and whether the value
    reaches the provider, given the model's rung -> wire value map.  A level
    the model has not declared support for still changes the limits, so
    showing the two facts separately is what keeps a working selection from
    looking like a no-op.  ``accepted`` is passed in rather than resolved here
    so this module stays free of any dependency on the provider layer.
    """
    rows: list[tuple[str, str, str]] = []
    for level in EFFORT_LEVELS:
        preset = EFFORT_PRESETS[level]
        sent = (
            f"sent as {accepted[level]}" if level in accepted
            else "local limits only"
        )
        rows.append((
            level,
            level,
            f"iter={preset['max_iter']}  tokens={preset['max_tokens']:,}  "
            f"ctx={preset['ctx_max_tokens'] // 1000}k tokens  — {sent}",
        ))
    return tuple(rows)


def effort_delivery(accepted: dict, model_alias: str, level: str) -> str:
    """Describe where one level is actually applied for a model."""
    if level in accepted:
        return f"provider reasoning_effort={accepted[level]}"
    if model_alias:
        return "local limits only (model declares no reasoning_effort support)"
    return "local limits only"


def effort_preset(level: str) -> dict:
    """Return the runtime limits for one effort level."""
    return dict(EFFORT_PRESETS[level])


def infer_effort_level(limits) -> str:
    """Recover an effort level from raw runtime limits.

    Session snapshots written before the effort ladder existed carry limits
    but no ``effort_level``.  Reverse-inferring keeps such a session on the
    rung whose limits it already had, instead of silently snapping it to the
    default.  ``off`` is unreachable here because it shares TIER_LOW with
    ``low``; ``low`` is the honest answer for those limits.
    """
    try:
        max_tokens = int(limits.get("max_tokens", 0))
        max_iter = int(limits.get("max_iter", 0))
    except (AttributeError, TypeError, ValueError):
        return DEFAULT_EFFORT_LEVEL
    if max_iter <= 0 or max_tokens <= 0:
        # Nothing usable to reverse-infer from.  Without this guard an
        # empty or truncated snapshot matches the ``max_tokens <=
        # TIER_LOW`` branch below and restores as "low", silently
        # downgrading a session that was never set below the default.
        return DEFAULT_EFFORT_LEVEL
    if max_iter >= TIER_ULTRA["max_iter"]:
        return "max"
    if max_iter >= TIER_MAX["max_iter"]:
        return "xhigh"
    if max_tokens >= TIER_DEEP["max_tokens"]:
        return "high"
    if max_tokens <= TIER_LOW["max_tokens"]:
        return "low"
    return DEFAULT_EFFORT_LEVEL
