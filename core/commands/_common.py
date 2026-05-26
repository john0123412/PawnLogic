"""
Shared helpers and constants for slash command modules.

Lives at the bottom of the import graph: depends only on `config` and
`utils.ansi`, so it can be safely imported from any command module
without risk of circular imports.
"""

from __future__ import annotations

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


__all__ = ["EXIT_SENTINEL", "fmt_config"]
