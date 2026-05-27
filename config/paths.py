"""config/paths.py — 路径与版本常量

版本号唯一定义处。全局通过 `from config import VERSION` 读取。
升级时只需修改此处。
"""
from pathlib import Path

# ── 唯一版本号定义 ──────────────────────────────────────
VERSION = "0.0.5"

SESSIONS_DIR       = Path.home() / ".pawnlogic" / "sessions"
DB_PATH            = Path.home() / ".pawnlogic" / "pawn.db"
GLOBAL_SKILLS_PATH = Path.home() / ".pawnlogic" / "global_skills.md"
SKILLS_DIR         = Path(__file__).resolve().parent.parent / "skills"
LOG_DIR            = Path.home() / ".pawnlogic" / "logs"
WORKSPACE_DIR      = str(Path.home() / ".pawnlogic" / "workspace")
WORKSPACE_ROOT     = str(Path.home() / ".pawnlogic")
