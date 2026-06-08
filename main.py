#!/usr/bin/env python3
"""Source-checkout compatibility entry point for PawnLogic.

The CLI runtime lives in ``pawnlogic.cli``. Keep this file as a thin wrapper so
``python main.py`` and legacy ``import main`` callers use the same implementation
as the installed ``pawn`` command.
"""

from __future__ import annotations

import sys

from pawnlogic import cli as _cli


if __name__ == "__main__":
    _cli.run()
else:
    sys.modules[__name__] = _cli
