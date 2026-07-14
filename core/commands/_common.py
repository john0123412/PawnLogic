"""
Shared helpers and constants for slash command modules.

Lives at the bottom of the import graph: depends only on `config` and
`utils.ansi`, so it can be safely imported from any command module
without risk of circular imports.
"""

from __future__ import annotations

from typing import Any, Optional

from core.state import runtime_config
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
    """Render the current dynamic runtime config block as a multi-line string.

    Used by /low, /mid, /deep, /max, /normal, /limits to display the
    effective runtime tunables after a tier change.
    """
    cfg = runtime_config()
    return (
        f"  max_tokens      : {c(CYAN, str(cfg['max_tokens']))}  (per-API output limit)\n"
        f"  ctx_max_chars   : {c(CYAN, str(cfg['ctx_max_chars']))}  (~{cfg['ctx_max_chars']//4:,} tokens)\n"
        f"  max_iter        : {c(CYAN, str(cfg['max_iter']))}  (tool-call iteration limit)\n"
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


# ────────────────────────────────────────────────────────
# Active output sink (stage 2)
# ────────────────────────────────────────────────────────
# Set once by main() at startup based on --json. dispatch() reads it to
# populate `ctx.sink` if the caller didn't supply one. Kept here (not in
# main.py) so command handlers and tests have a single import target.
_active_sink: Any = None


def set_active_sink(sink: Any) -> None:
    """Register the process-wide output sink (HumanSink or JsonSink)."""
    global _active_sink
    _active_sink = sink


def swap_active_sink(sink: Any) -> Any:
    """Replace the active sink and return the previous sink for restoration."""
    global _active_sink
    old = _active_sink
    _active_sink = sink
    return old


def get_active_sink() -> Any:
    """Return the context sink, compatibility sink, or a new HumanSink.

    Falling back to HumanSink keeps unit tests and ad-hoc scripts that
    construct CommandContext directly working without explicit setup.
    """
    from core.runtime_context import current_runtime_context

    if _active_sink is not None:
        return _active_sink
    context = current_runtime_context()
    if context is not None and context.sink is not None:
        return context.sink
    from core.output import HumanSink
    return HumanSink()


def sink_print(*args: Any, sep: str = " ", end: str = "\n", flush: bool = False) -> None:
    """Print through the active sink while preserving basic print() ergonomics."""
    text = sep.join(str(arg) for arg in args)
    sink = get_active_sink()
    if end == "\n":
        sink.print(text)
    else:
        sink.write(text + end)


__all__ = [
    "EXIT_SENTINEL",
    "fmt_config",
    "set_deferred_history",
    "take_deferred_history",
    "set_active_sink",
    "swap_active_sink",
    "get_active_sink",
    "sink_print",
]
