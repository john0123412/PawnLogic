"""
core/workspace_cleanup.py — Workspace 维护工具

提供 ``/workspace`` 系列命令的实现：
    plan     — 生成清理候选清单（只读）
    execute  — 按清单归档 + DB 同步
    restore  — 从最近一次 tar 备份回滚
    status   — 展示 workspace 总览
"""

from __future__ import annotations

import os
import re
import json
import shutil
import sqlite3
import tarfile
from pathlib import Path
from datetime import datetime
from typing import Optional

from config import WORKSPACE_DIR, DB_PATH
from core.logger import logger


# ════════════════════════════════════════════════════════
# 常量
# ════════════════════════════════════════════════════════

WORKSPACE_PATH = Path(WORKSPACE_DIR).expanduser()
PAWN_HOME      = Path.home() / ".pawnlogic"
ARCHIVE_ROOT   = PAWN_HOME / "archive"
LAST_BACKUP    = PAWN_HOME / ".last_backup"
DEFAULT_PLAN   = PAWN_HOME / "cleanup_plan.md"

HIGH_DAYS = 7    # >7 天未改 → HIGH（自动归档）
MID_DAYS  = 14   # >14 天未改 session → HIGH

SAFE_DIRS = {"skills", "screenshots", "writeups", "sub", "by-name"}
SENSITIVE_RE = re.compile(r"(flag|key|token|secret|password|credential)", re.IGNORECASE)
SKILLS_LOCKED_SUFFIX = (".json", ".yaml", ".yml")


# ════════════════════════════════════════════════════════
# 通用工具
# ════════════════════════════════════════════════════════

def _size_human(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if f < 1024:
            return f"{f:.1f}{unit}"
        f /= 1024
    return f"{f:.1f}TB"


def _age_days(path: Path) -> float:
    try:
        return (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds() / 86400
    except OSError:
        return 0.0


def _dir_size(path: Path) -> int:
    if not path.is_dir():
        return 0
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
    except OSError:
        pass
    return total


def _categorize(name: str, is_dir: bool) -> str:
    """文件 → 归档类别（与 cleanup_plan.md 表格保持一致）"""
    if is_dir and name.startswith("session_"):
        return "orphan_sessions"
    n_low = name.lower()
    if re.match(r"^(flask_)?exploit", n_low):
        return "pre_v1.1_exploits"
    if name.endswith((".php", ".html")):
        return "web_pentest_relics"
    if name.startswith(("mechanism", "mech_", "rune_")):
        return "web_pentest_relics"
    if n_low.endswith(".sh"):
        return "scripts"
    if name == "libc.so.6" or name == "notepad":
        return "binaries"
    if name.startswith(("pwn", "final_")):
        return "pre_v1.1_exploits"
    return "misc"


def _load_db_sessions() -> dict:
    """{session_id: {age_days, name, workspace_dir}}"""
    if not Path(DB_PATH).exists():
        return {}
    out = {}
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        now = datetime.now()
        for r in conn.execute(
            "SELECT id, name, auto_name, workspace_dir, updated_at FROM sessions"
        ):
            try:
                age = (now - datetime.fromisoformat(r["updated_at"])).total_seconds() / 86400
            except Exception:
                age = 9999
            out[r["id"]] = {
                "age_days":      age,
                "name":          r["name"] or r["auto_name"] or "",
                "workspace_dir": r["workspace_dir"] or "",
            }
    return out


# ════════════════════════════════════════════════════════
# 1) 备份
# ════════════════════════════════════════════════════════

def make_backup() -> Path:
    """tar.gz 整个 workspace，返回备份文件路径，并写入 .last_backup"""
    if not WORKSPACE_PATH.exists():
        raise FileNotFoundError(f"workspace 不存在: {WORKSPACE_PATH}")
    PAWN_HOME.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = PAWN_HOME / f"backup_before_cleanup_{ts}.tar.gz"
    with tarfile.open(out, "w:gz") as tf:
        tf.add(str(WORKSPACE_PATH), arcname="workspace")
    LAST_BACKUP.write_text(str(out))
    return out


# ════════════════════════════════════════════════════════
# 2) 扫描 + 分类
# ════════════════════════════════════════════════════════

def _classify(path: Path, db: dict) -> dict:
    rel = path.relative_to(WORKSPACE_PATH)
    kind = "file" if path.is_file() else ("symlink" if path.is_symlink() else "dir")
    size = path.stat().st_size if path.is_file() else _dir_size(path)
    age = _age_days(path)
    sensitive = bool(SENSITIVE_RE.search(path.name))

    # skills/ 内 JSON / YAML：LOCKED
    try:
        path.relative_to(WORKSPACE_PATH / "skills")
        if path.name.endswith(SKILLS_LOCKED_SUFFIX) or path.name == "manifest.json":
            return {"path": str(rel), "kind": kind, "size": size, "age_days": age,
                    "confidence": "LOCKED", "reason": "skills/ 工具链描述文件",
                    "sensitive": False, "locked": True,
                    "action": "KEEP", "category": ""}
    except ValueError:
        pass

    top = rel.parts[0] if rel.parts else ""
    if top in SAFE_DIRS:
        return {"path": str(rel), "kind": kind, "size": size, "age_days": age,
                "confidence": "SAFE", "reason": f"功能目录 {top}/",
                "sensitive": False, "locked": False,
                "action": "KEEP", "category": ""}

    # session_* 目录
    if kind == "dir" and top.startswith("session_"):
        sid = top.replace("session_", "", 1)
        info = db.get(sid)
        if info and info["age_days"] <= HIGH_DAYS:
            return {"path": str(rel), "kind": kind, "size": size, "age_days": age,
                    "confidence": "SAFE",
                    "reason": f"DB 会话 {info['age_days']:.1f} 天前活跃",
                    "sensitive": sensitive, "locked": False,
                    "action": "KEEP", "category": ""}
        elif info and info["age_days"] <= MID_DAYS:
            return {"path": str(rel), "kind": kind, "size": size, "age_days": age,
                    "confidence": "MID",
                    "reason": f"DB 会话 {info['age_days']:.1f} 天未改",
                    "sensitive": sensitive, "locked": False,
                    "action": "CONFIRM", "category": "stale_sessions"}
        else:
            reason = (f"DB 会话 {info['age_days']:.1f} 天未改"
                      if info else "DB 已无对应会话（孤儿目录）")
            return {"path": str(rel), "kind": kind, "size": size, "age_days": age,
                    "confidence": "SENSITIVE" if sensitive else "HIGH",
                    "reason": reason + ("（含敏感字样）" if sensitive else ""),
                    "sensitive": sensitive, "locked": False,
                    "action": "CONFIRM" if sensitive else "ARCHIVE",
                    "category": "orphan_sessions"}

    # 根目录散落文件
    if len(rel.parts) == 1 and kind == "file":
        cat = _categorize(path.name, False)
        if age >= HIGH_DAYS:
            conf, action = "HIGH", "ARCHIVE"
            reason = f"散落文件 ({age:.1f}d, {_size_human(size)})"
        else:
            conf, action = "MID", "CONFIRM"
            reason = f"散落文件 ({age:.1f}d) 较新"
        if sensitive:
            conf, action = "SENSITIVE", "CONFIRM"
            reason += "（含敏感字样）"
        return {"path": str(rel), "kind": kind, "size": size, "age_days": age,
                "confidence": conf, "reason": reason,
                "sensitive": sensitive, "locked": False,
                "action": action, "category": cat}

    # 其他
    return {"path": str(rel), "kind": kind, "size": size, "age_days": age,
            "confidence": "MID", "reason": "未分类",
            "sensitive": sensitive, "locked": False,
            "action": "CONFIRM", "category": "misc"}


def scan() -> tuple[list, dict]:
    """返回 (条目列表, db_sessions)"""
    if not WORKSPACE_PATH.exists():
        return [], {}
    db = _load_db_sessions()
    rows = []
    for item in sorted(WORKSPACE_PATH.iterdir()):
        if item.name.startswith("."):
            continue
        rows.append(_classify(item, db))
    return rows, db


# ════════════════════════════════════════════════════════
# 3) 清单生成
# ════════════════════════════════════════════════════════

_CONF_ICON = {
    "LOCKED": "🔒", "SAFE": "🟢", "MID": "🟡", "HIGH": "🔴", "SENSITIVE": "⚠️",
}
_ACTION_LABEL = {"KEEP": "保留", "ARCHIVE": "→归档", "CONFIRM": "需确认"}


def render_plan(rows: list, db: dict, plan_path: Path = DEFAULT_PLAN) -> str:
    lines = [
        "# Workspace Cleanup Plan",
        "",
        f"**Generated**: {datetime.now().isoformat(timespec='seconds')}",
        f"**Workspace**: `{WORKSPACE_PATH}`",
        f"**Backup**: `{LAST_BACKUP.read_text().strip() if LAST_BACKUP.exists() else '(none)'}`",
        "",
        "## 总览",
        "",
    ]

    by_conf = {}
    total_size = archive_size = 0
    for r in rows:
        by_conf[r["confidence"]] = by_conf.get(r["confidence"], 0) + 1
        total_size += r["size"]
        if r["action"] == "ARCHIVE":
            archive_size += r["size"]

    lines.append(f"- 扫描条目: **{len(rows)}**")
    lines.append(f"- 总大小: **{_size_human(total_size)}**")
    lines.append(f"- 拟归档大小: **{_size_human(archive_size)}**")
    lines.append("")
    lines.append("| 置信度 | 数量 |")
    lines.append("|---|---|")
    for k in ("LOCKED", "SAFE", "MID", "HIGH", "SENSITIVE"):
        lines.append(f"| {_CONF_ICON[k]} {k} | {by_conf.get(k, 0)} |")
    lines.append("")

    lines.append("## 详细清单")
    lines.append("")
    lines.append("| 置信度 | 路径 | 类型 | 大小 | 年龄(天) | 建议 | 类别 | 理由 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    order = {"SENSITIVE": 0, "HIGH": 1, "MID": 2, "SAFE": 3, "LOCKED": 4}
    for r in sorted(rows, key=lambda x: (order.get(x["confidence"], 9), x["path"])):
        lines.append(
            f"| {_CONF_ICON[r['confidence']]} {r['confidence']} "
            f"| `{r['path']}` | {r['kind']} | {_size_human(r['size'])} "
            f"| {r['age_days']:.1f} | {_ACTION_LABEL[r['action']]} "
            f"| `{r['category']}` | {r['reason']} |"
        )
    lines.append("")

    # DB 一致性
    empty = [(s, info) for s, info in db.items() if not info["workspace_dir"]]
    lines.append("## DB 一致性")
    lines.append("")
    lines.append(f"- DB 总会话: **{len(db)}**")
    lines.append(f"- workspace_dir 为空: **{len(empty)}** "
                 "(execute 阶段会批量补写指向归档共享占位)")
    lines.append("")

    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text("\n".join(lines), encoding="utf-8")
    return str(plan_path)


# ════════════════════════════════════════════════════════
# 4) 归档执行
# ════════════════════════════════════════════════════════

def _safe_mv(src: Path, dst_dir: Path) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    target = dst_dir / src.name
    if target.exists():
        stem, suf = src.stem, src.suffix
        for i in range(2, 1000):
            cand = dst_dir / f"{stem}-{i}{suf}"
            if not cand.exists():
                target = cand
                break
    shutil.move(str(src), str(target))
    return target


def execute_cleanup(rows: list, db: dict) -> dict:
    """按 rows 中 action='ARCHIVE' 的条目执行归档 + DB 补写。

    返回 {"moved": [...], "skipped": [...], "archive_root": Path,
          "db_updated": int}
    """
    date_tag = datetime.now().strftime("%Y%m%d")
    archive_root = ARCHIVE_ROOT / f"cleanup_{date_tag}"
    archive_root.mkdir(parents=True, exist_ok=True)

    moved = []
    skipped = []
    sid_to_archive = {}

    for r in rows:
        if r["action"] != "ARCHIVE":
            continue
        if r["locked"] or r["sensitive"]:
            skipped.append((r["path"], "locked/sensitive — 跳过"))
            continue

        src = WORKSPACE_PATH / r["path"]
        if not src.exists():
            skipped.append((r["path"], "源路径不存在"))
            continue
        if src.is_symlink():
            skipped.append((r["path"], "symlink，跳过"))
            continue

        cat_dir = archive_root / (r["category"] or "misc")
        try:
            target = _safe_mv(src, cat_dir)
            moved.append((r["path"], str(target.relative_to(Path.home())),
                          r["category"]))
            if r["category"] == "orphan_sessions" and r["path"].startswith("session_"):
                sid = r["path"].replace("session_", "", 1)
                sid_to_archive[sid] = str(target)
        except Exception as exc:
            skipped.append((r["path"], f"mv 失败: {exc}"))
            logger.warning("Cleanup mv failed | path={} exc={!r}", r["path"], exc)

    # 写 MANIFEST
    manifest = archive_root / "MANIFEST.md"
    lines = [
        "# Cleanup Manifest",
        "",
        f"**Executed**: {datetime.now().isoformat(timespec='seconds')}",
        f"**Backup**: `{LAST_BACKUP.read_text().strip() if LAST_BACKUP.exists() else '(none)'}`",
        f"**Archive root**: `{archive_root}`",
        f"**Moved**: {len(moved)} | **Skipped**: {len(skipped)}",
        "",
        "## 归档明细",
        "",
        "| 原路径 | 归档至 | 类别 |",
        "|---|---|---|",
    ]
    for src, dst, cat in moved:
        lines.append(f"| `workspace/{src}` | `{dst}` | {cat} |")
    if skipped:
        lines.append("")
        lines.append("## 跳过明细")
        lines.append("")
        for n, reason in skipped:
            lines.append(f"- `{n}`: {reason}")
    manifest.write_text("\n".join(lines), encoding="utf-8")

    # _orphan_sessions_map.json
    (archive_root / "_orphan_sessions_map.json").write_text(
        json.dumps(sid_to_archive, indent=2)
    )

    # DB 同步：workspace_dir='' 的会话补写
    db_updated = 0
    placeholder = archive_root / "orphan_sessions" / "_shared_ancient"
    placeholder.mkdir(parents=True, exist_ok=True)
    if not (placeholder / "README.md").exists():
        (placeholder / "README.md").write_text(
            "# Shared placeholder for ancient sessions\n\n"
            "Sessions whose workspace_dir was empty got rewritten to this dir.\n"
        )

    if Path(DB_PATH).exists():
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            empty_rows = conn.execute(
                "SELECT id FROM sessions WHERE workspace_dir = '' OR workspace_dir IS NULL"
            ).fetchall()
            now_iso = datetime.now().isoformat(timespec="seconds")
            for r in empty_rows:
                sid = r["id"]
                target = sid_to_archive.get(sid, str(placeholder))
                conn.execute(
                    "UPDATE sessions SET workspace_dir=?, updated_at=? WHERE id=?",
                    (target, now_iso, sid),
                )
                db_updated += 1
            conn.commit()

    return {
        "moved":         moved,
        "skipped":       skipped,
        "archive_root":  archive_root,
        "manifest":      manifest,
        "db_updated":    db_updated,
    }


# ════════════════════════════════════════════════════════
# 5) 回滚（从最近备份）
# ════════════════════════════════════════════════════════

def restore_from_backup(backup_path: Optional[Path] = None) -> dict:
    """从备份 tar 解压回 ~/.pawnlogic/。注意会覆盖当前 workspace 内容！"""
    if backup_path is None:
        if not LAST_BACKUP.exists():
            return {"ok": False, "error": "未找到 .last_backup 记录"}
        backup_path = Path(LAST_BACKUP.read_text().strip())
    if not backup_path.exists():
        return {"ok": False, "error": f"备份文件不存在: {backup_path}"}

    # 把当前 workspace 重命名为 _replaced_<ts>，以防回滚出错丢数据
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if WORKSPACE_PATH.exists():
        replaced = WORKSPACE_PATH.parent / f"workspace_replaced_{ts}"
        os.rename(str(WORKSPACE_PATH), str(replaced))

    with tarfile.open(backup_path, "r:gz") as tf:
        tf.extractall(str(PAWN_HOME))

    return {"ok": True, "restored_from": str(backup_path),
            "old_workspace_renamed_to": str(replaced) if WORKSPACE_PATH.exists() else None}


# ════════════════════════════════════════════════════════
# 6) status
# ════════════════════════════════════════════════════════

def workspace_status() -> dict:
    if not WORKSPACE_PATH.exists():
        return {"exists": False}
    items = list(WORKSPACE_PATH.iterdir())
    files = [p for p in items if p.is_file()]
    dirs  = [p for p in items if p.is_dir() and not p.is_symlink()]
    links = [p for p in items if p.is_symlink()]
    total_size = sum(p.stat().st_size for p in files)
    for d in dirs:
        total_size += _dir_size(d)

    db = _load_db_sessions()
    empty_db = sum(1 for s in db.values() if not s["workspace_dir"])

    return {
        "exists":       True,
        "path":         str(WORKSPACE_PATH),
        "total_size":   total_size,
        "size_human":   _size_human(total_size),
        "n_files":      len(files),
        "n_dirs":       len(dirs),
        "n_symlinks":   len(links),
        "session_dirs": sum(1 for d in dirs if d.name.startswith("session_")),
        "db_sessions":  len(db),
        "db_empty":     empty_db,
        "last_backup":  LAST_BACKUP.read_text().strip() if LAST_BACKUP.exists() else "",
    }
