"""
Shared helpers and constants for slash command modules.

Lives at the bottom of the import graph: depends only on `config` and
`utils.ansi`, so it can be safely imported from any command module
without risk of circular imports.
"""

from __future__ import annotations

from typing import Optional

from config import DYNAMIC_CONFIG
from utils.ansi import c, CYAN

# ────────────────────────────────────────────────────────
# Exit sentinel
# ────────────────────────────────────────────────────────
# Returned by an exit command (/exit, /quit, /q) to signal the main
# REPL loop in main.py to break. Identity-checked, so this object must
# be unique across the codebase — main.py imports it from here.
EXIT_SENTINEL: str = "__PAWN_EXIT__"


# ────────────────────────────────────────────────────────
# Pretty-print of dynamic runtime configuration
# ────────────────────────────────────────────────────────
def fmt_config() -> str:
    """Render the current DYNAMIC_CONFIG block as a multi-line string.

    Used by /low, /mid, /deep, /max, /normal, /limits to display the
    effective runtime tunables after a tier change.
    """
    cfg = DYNAMIC_CONFIG
    return (
        f"  max_tokens      : {c(CYAN, str(cfg['max_tokens']))}  (每次 API 输出上限)\n"
        f"  ctx_max_chars   : {c(CYAN, str(cfg['ctx_max_chars']))}  (~{cfg['ctx_max_chars']//4:,} tokens)\n"
        f"  max_iter        : {c(CYAN, str(cfg['max_iter']))}  (工具调用轮次上限)\n"
        f"  tool_max_chars  : {c(CYAN, str(cfg['tool_max_chars']))}\n"
        f"  fetch_max_chars : {c(CYAN, str(cfg['fetch_max_chars']))}\n"
    )


# ────────────────────────────────────────────────────────
# Deferred history rendering
# ────────────────────────────────────────────────────────
# /load and /resume commands can replace the full conversation history.
# The REPL loop in main.py wants to render that new history *before* the
# next prompt_async call (so it appears above the prompt). Since the
# command handlers run inside the REPL's iteration, they can't render
# directly without conflicting with the prompt.
#
# Pattern:
#   set_deferred_history(session.messages)   # called by /load, /resume,
#                                            # and /chat (auto-resume)
#   ...
#   msgs = take_deferred_history()           # called by REPL loop;
#                                            # returns msgs once and clears
#
# Set from main.py too (startup auto-resume), so this lives in shared
# state rather than being owned by a single module.
_deferred_history: Optional[list] = None


def set_deferred_history(msgs: list) -> None:
    """Tell the REPL loop to render this message list before the next prompt."""
    global _deferred_history
    _deferred_history = list(msgs)


def take_deferred_history() -> Optional[list]:
    """Pop and return the deferred history list. Returns None if not set."""
    global _deferred_history
    snap, _deferred_history = _deferred_history, None
    return snap


__all__ = [
    "EXIT_SENTINEL",
    "fmt_config",
    "set_deferred_history",
    "take_deferred_history",
]
