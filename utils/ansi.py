"""utils/ansi.py - ANSI color helpers.

Fix WSL2 / Ubuntu readline cursor drift:
  readline counts ANSI escape sequences such as \033[...m as visible
  characters when measuring input() prompts. That shifts the cursor and can
  make user input overwrite the previous output line.

  The fix is to wrap escape sequences with readline markers:
    \001  = RL_PROMPT_START_IGNORE
    \002  = RL_PROMPT_END_IGNORE

  Regular output should use c(). Only input() prompts need cp() / rl_wrap().
"""

import sys
import threading
import re as _re

# Color constants.
R       = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
GRAY    = "\033[90m"
CYAN    = "\033[96m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
RED     = "\033[91m"
BLUE    = "\033[94m"
MAGENTA = "\033[95m"

# Regular output helpers for print / sys.stdout.write.

def c(col: str, txt: str) -> str:
    """Color regular output. Do not use this for input() prompts."""
    return f"{col}{txt}{R}"

def box(txt: str, col: str = CYAN) -> str:
    return f"{col}│{R} {txt}"

# readline prompt helpers.
#
# \001 and \002 are readline's RL_PROMPT_START_IGNORE /
# RL_PROMPT_END_IGNORE markers. They tell readline to ignore the wrapped
# bytes when computing display width.
#
# Principle:
#   visible_width = len(prompt) - len(bytes between every \001...\002 pair)
# Wrapping every \033[...m removes the width error.

_ANSI_RE = _re.compile(r'(\033\[[0-9;]*m)')

def rl_wrap(text: str) -> str:
    """
    Wrap every ANSI escape sequence with readline ignore markers.
    Use this for any colored string passed to input().
    """
    return _ANSI_RE.sub(r'\001\1\002', text)

def cp(col: str, txt: str) -> str:
    """
    readline-safe c().
    Use this for input() prompts; use c() everywhere else.

    Example:
        # Regular output
        print(c(GREEN, "Done"))

        # input prompt
        raw = input(cp(BOLD+GREEN, "▶ ") + cp(BOLD, "You > "))
    """
    return rl_wrap(f"{col}{txt}{R}")


# Loading animation.

class Spinner:
    """USER_MODE loading animation that renders a spinner in a background thread.

    Usage:
        with Spinner("Syncing skill packs"):
            do_long_running_work()
    """
    _FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, text: str = "Loading", col: str = CYAN):
        self._text = text
        self._col = col
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        # Clear the animation line.
        sys.stdout.write(f"\r\033[K")
        sys.stdout.flush()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()

    def _run(self):
        i = 0
        while not self._stop.is_set():
            frame = self._FRAMES[i % len(self._FRAMES)]
            line = f"\r  {self._col}{frame}{R} {self._text}..."
            sys.stdout.write(line)
            sys.stdout.flush()
            i += 1
            self._stop.wait(0.1)
