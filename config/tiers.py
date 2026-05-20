"""config/tiers.py — 三档算力预设"""

TIER_LOW = {
    "max_tokens":      4_096,
    "ctx_max_chars":   40_000,
    "ctx_trim_to":     30_000,
    "max_iter":        10,
    "tool_max_chars":   6_000,
    "fetch_max_chars":  8_000,
    "preferred_worker": "auto",
    "time_budget_sec":  300,
    "ctx_sliding_turns": 4,
    "ctx_summary_threshold": 6,
}
TIER_MID = {
    "max_tokens":      8_192,
    "ctx_max_chars":   150_000,
    "ctx_trim_to":     110_000,
    "max_iter":        30,
    "tool_max_chars":   15_000,
    "fetch_max_chars":  20_000,
    "preferred_worker": "auto",
    "time_budget_sec":  600,
    "ctx_sliding_turns": 5,
    "ctx_summary_threshold": 8,
}
TIER_DEEP = {
    "max_tokens":      32_768,
    "ctx_max_chars":   400_000,
    "ctx_trim_to":     300_000,
    "max_iter":        50,
    "tool_max_chars":   20_000,
    "fetch_max_chars":  30_000,
    "preferred_worker": "auto",
    "time_budget_sec":  1800,
    "ctx_sliding_turns": 8,
    "ctx_summary_threshold": 12,
}
TIER_MAX = {
    "max_tokens":      32_768,
    "ctx_max_chars":   600_000,
    "ctx_trim_to":     450_000,
    "max_iter":        100,
    "tool_max_chars":   30_000,
    "fetch_max_chars":  40_000,
    "preferred_worker": "auto",
    "time_budget_sec":  3600,
    "ctx_sliding_turns": 10,
    "ctx_summary_threshold": 15,
}
