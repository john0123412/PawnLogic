"""config/paths.py — 路径与版本常量"""
import os
from pathlib import Path

VERSION = "1.0"

SESSIONS_DIR       = Path.home() / ".pawnlogic" / "sessions"
DB_PATH            = Path.home() / ".pawnlogic" / "pawn.db"
GLOBAL_SKILLS_PATH = Path.home() / ".pawnlogic" / "global_skills.md"
SKILLS_DIR         = Path(__file__).resolve().parent.parent / "skills"
LOG_DIR            = Path.home() / ".pawnlogic" / "logs"
WORKSPACE_DIR      = str(Path.home() / ".pawnlogic" / "workspace")
WORKSPACE_ROOT     = str(Path.home() / ".pawnlogic")
