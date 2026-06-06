"""config/paths.py — 路径与版本常量

版本号唯一定义处。全局通过 `from config import VERSION` 读取。
升级时只需修改此处。
"""
from pathlib import Path
import os

# ── 唯一版本号定义 ──────────────────────────────────────
VERSION = "0.0.5"

PAWNLOGIC_HOME     = Path(os.environ.get("PAWNLOGIC_HOME", Path.home() / ".pawnlogic")).expanduser()
SESSIONS_DIR       = PAWNLOGIC_HOME / "sessions"
DB_PATH            = PAWNLOGIC_HOME / "pawn.db"
GLOBAL_SKILLS_PATH = PAWNLOGIC_HOME / "global_skills.md"
SKILLS_DIR         = Path(__file__).resolve().parent.parent / "skills"
LOG_DIR            = PAWNLOGIC_HOME / "logs"
WORKSPACE_DIR      = str(PAWNLOGIC_HOME / "workspace")
WORKSPACE_ROOT     = str(PAWNLOGIC_HOME)
