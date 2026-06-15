"""config/paths.py - path and version constants.

VERSION is defined only here and consumed globally through `from config import
VERSION`. Version bumps should edit this file only.
"""
from pathlib import Path
import os

# Single source of truth for the package version.
VERSION = "0.1.0"

def _safe_home() -> Path:
    try:
        return Path.home()
    except Exception:
        return Path(os.environ.get("TMPDIR") or "/tmp")


def _pawnlogic_home() -> Path:
    raw = os.environ.get("PAWNLOGIC_HOME")
    return Path(raw).expanduser() if raw else (_safe_home() / ".pawnlogic").expanduser()


PAWNLOGIC_HOME     = _pawnlogic_home()
SESSIONS_DIR       = PAWNLOGIC_HOME / "sessions"
DB_PATH            = PAWNLOGIC_HOME / "pawn.db"
GLOBAL_SKILLS_PATH = PAWNLOGIC_HOME / "global_skills.md"
_SOURCE_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
SKILLS_DIR         = _SOURCE_SKILLS_DIR if _SOURCE_SKILLS_DIR.exists() else PAWNLOGIC_HOME / "skills"
LOG_DIR            = PAWNLOGIC_HOME / "logs"
WORKSPACE_DIR      = str(PAWNLOGIC_HOME / "workspace")
WORKSPACE_ROOT     = str(PAWNLOGIC_HOME)
