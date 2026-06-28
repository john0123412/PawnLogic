"""
core/workspace_cleanup.py — workspace maintenance utilities.

Implements the ``/workspace`` command family:
    plan     — generate cleanup candidates, read-only
    execute  — archive by plan and sync DB metadata
    restore  — roll back from the latest tar backup
    status   — show workspace overview
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

from config import PAWNLOGIC_HOME, WORKSPACE_DIR, DB_PATH
from core.logger import logger


# ════════════════════════════════════════════════════════
# Constants.
# ════════════════════════════════════════════════════════

WORKSPACE_PATH = Path(WORKSPACE_DIR).expanduser()
PAWN_HOME      = PAWNLOGIC_HOME
ARCHIVE_ROOT   = PAWN_HOME / "archive"
LAST_BACKUP    = PAWN_HOME / ".last_backup"
DEFAULT_PLAN   = PAWN_HOME / "cleanup_plan.md"

HIGH_DAYS = 7    # Unmodified for >7 days -> HIGH, auto-archive.
MID_DAYS  = 14   # Session unmodified for >14 days -> HIGH.

SAFE_DIRS = {"skills", "screenshots", "writeups", "sub", "by-name"}
SENSITIVE_RE = re.compile(r"(flag|key|token|secret|password|credential)", re.IGNORECASE)
SKILLS_LOCKED_SUFFIX = (".json", ".yaml", ".yml")


# ════════════════════════════════════════════════════════
# Shared helpers.
# ════════════════════════════════════════════════════════

def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False

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


def _validate_restore_member(member: tarfile.TarInfo, root: Path) -> None:
    """Reject tar entries that could write outside the restore root."""
    member_name = member.name
    member_path = Path(member_name)
    if not member_name or member_name in {".", ".."}:
        raise ValueError(f"unsafe archive member path: {member_name!r}")
    if member_path.is_absolute() or ".." in member_path.parts:
        raise ValueError(f"unsafe archive member path: {member_name!r}")

    target = (root / member_path).resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    if not _is_relative_to(target, root_resolved):
        raise ValueError(f"unsafe archive member path: {member_name!r}")

    if member.issym() or member.islnk():
        raise ValueError(f"unsafe archive link member: {member_name!r}")
    if not (member.isdir() or member.isfile()):
        raise ValueError(f"unsafe archive special member: {member_name!r}")


def _validated_restore_members(tf: tarfile.TarFile, root: Path) -> list[tarfile.TarInfo]:
    members = tf.getmembers()
    for member in members:
        _validate_restore_member(member, root)
    return members


def _categorize(name: str, is_dir: bool) -> str:
    """Map a file to an archive category consistent with cleanup_plan.md."""
    if is_dir and name.startswith("session_"):
        return "orphan_sessions"
    n_low = name.lower()
    if re.match(r"^(flask_)?exploit", n_low):
        return "legacy_exploits"
    if name.endswith((".php", ".html")):
        return "web_pentest_relics"
    if name.startswith(("mechanism", "mech_", "rune_")):
        return "web_pentest_relics"
    if n_low.endswith(".sh"):
        return "scripts"
    if name == "libc.so.6" or name == "notepad":
        return "binaries"
    if name.startswith(("pwn", "final_")):
        return "legacy_exploits"
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
# 1. Backup.
# ════════════════════════════════════════════════════════

def make_backup() -> Path:
    """Create a tar.gz of the workspace, return the backup path, and write .last_backup."""
    if not WORKSPACE_PATH.exists():
        raise FileNotFoundError(f"workspace does not exist: {WORKSPACE_PATH}")
    PAWN_HOME.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = PAWN_HOME / f"backup_before_cleanup_{ts}.tar.gz"
    with tarfile.open(out, "w:gz") as tf:
        tf.add(str(WORKSPACE_PATH), arcname="workspace")
    LAST_BACKUP.write_text(str(out))
    return out


# ════════════════════════════════════════════════════════
# 2. Scan and classify.
# ════════════════════════════════════════════════════════

def _classify(path: Path, db: dict) -> dict:
    rel = path.relative_to(WORKSPACE_PATH)
    kind = "file" if path.is_file() else ("symlink" if path.is_symlink() else "dir")
    size = path.stat().st_size if path.is_file() else _dir_size(path)
    age = _age_days(path)
    sensitive = bool(SENSITIVE_RE.search(path.name))

    # JSON/YAML files under skills/ are LOCKED.
    try:
        path.relative_to(WORKSPACE_PATH / "skills")
        if path.name.endswith(SKILLS_LOCKED_SUFFIX) or path.name == "manifest.json":
            return {"path": str(rel), "kind": kind, "size": size, "age_days": age,
                    "confidence": "LOCKED", "reason": "skills/ toolchain descriptor",
                    "sensitive": False, "locked": True,
                    "action": "KEEP", "category": ""}
    except ValueError:
        pass

    top = rel.parts[0] if rel.parts else ""
    if top in SAFE_DIRS:
        return {"path": str(rel), "kind": kind, "size": size, "age_days": age,
                "confidence": "SAFE", "reason": f"functional directory {top}/",
                "sensitive": False, "locked": False,
                "action": "KEEP", "category": ""}

    # session_* directories.
    if kind == "dir" and top.startswith("session_"):
        sid = top.replace("session_", "", 1)
        info = db.get(sid)
        if info and info["age_days"] <= HIGH_DAYS:
            return {"path": str(rel), "kind": kind, "size": size, "age_days": age,
                    "confidence": "SAFE",
                    "reason": f"DB session active {info['age_days']:.1f} days ago",
                    "sensitive": sensitive, "locked": False,
                    "action": "KEEP", "category": ""}
        elif info and info["age_days"] <= MID_DAYS:
            return {"path": str(rel), "kind": kind, "size": size, "age_days": age,
                    "confidence": "MID",
                    "reason": f"DB session unchanged for {info['age_days']:.1f} days",
                    "sensitive": sensitive, "locked": False,
                    "action": "CONFIRM", "category": "stale_sessions"}
        else:
            reason = (f"DB session unchanged for {info['age_days']:.1f} days"
                      if info else "No matching DB session; orphan directory")
            return {"path": str(rel), "kind": kind, "size": size, "age_days": age,
                    "confidence": "SENSITIVE" if sensitive else "HIGH",
                    "reason": reason + ("; sensitive-looking name" if sensitive else ""),
                    "sensitive": sensitive, "locked": False,
                    "action": "CONFIRM" if sensitive else "ARCHIVE",
                    "category": "orphan_sessions"}

    # Loose files in workspace root.
    if len(rel.parts) == 1 and kind == "file":
        cat = _categorize(path.name, False)
        if age >= HIGH_DAYS:
            conf, action = "HIGH", "ARCHIVE"
            reason = f"loose file ({age:.1f}d, {_size_human(size)})"
        else:
            conf, action = "MID", "CONFIRM"
            reason = f"loose file ({age:.1f}d), relatively new"
        if sensitive:
            conf, action = "SENSITIVE", "CONFIRM"
            reason += "; sensitive-looking name"
        return {"path": str(rel), "kind": kind, "size": size, "age_days": age,
                "confidence": conf, "reason": reason,
                "sensitive": sensitive, "locked": False,
                "action": action, "category": cat}

    # Other entries.
    return {"path": str(rel), "kind": kind, "size": size, "age_days": age,
            "confidence": "MID", "reason": "unclassified",
            "sensitive": sensitive, "locked": False,
            "action": "CONFIRM", "category": "misc"}


def scan() -> tuple[list, dict]:
    """Return (entry_list, db_sessions)."""
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
# 3. Plan rendering.
# ════════════════════════════════════════════════════════

_CONF_ICON = {
    "LOCKED": "🔒", "SAFE": "🟢", "MID": "🟡", "HIGH": "🔴", "SENSITIVE": "⚠️",
}
_ACTION_LABEL = {"KEEP": "keep", "ARCHIVE": "-> archive", "CONFIRM": "needs confirmation"}


def render_plan(rows: list, db: dict, plan_path: Path = DEFAULT_PLAN) -> str:
    lines = [
        "# Workspace Cleanup Plan",
        "",
        f"**Generated**: {datetime.now().isoformat(timespec='seconds')}",
        f"**Workspace**: `{WORKSPACE_PATH}`",
        f"**Backup**: `{LAST_BACKUP.read_text().strip() if LAST_BACKUP.exists() else '(none)'}`",
        "",
        "## Overview",
        "",
    ]

    by_conf = {}
    total_size = archive_size = 0
    for r in rows:
        by_conf[r["confidence"]] = by_conf.get(r["confidence"], 0) + 1
        total_size += r["size"]
        if r["action"] == "ARCHIVE":
            archive_size += r["size"]

    lines.append(f"- Scanned entries: **{len(rows)}**")
    lines.append(f"- Total size: **{_size_human(total_size)}**")
    lines.append(f"- Planned archive size: **{_size_human(archive_size)}**")
    lines.append("")
    lines.append("| Confidence | Count |")
    lines.append("|---|---|")
    for k in ("LOCKED", "SAFE", "MID", "HIGH", "SENSITIVE"):
        lines.append(f"| {_CONF_ICON[k]} {k} | {by_conf.get(k, 0)} |")
    lines.append("")

    lines.append("## Detailed Inventory")
    lines.append("")
    lines.append("| Confidence | Path | Type | Size | Age (days) | Suggestion | Category | Reason |")
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

    # DB consistency.
    empty = [(s, info) for s, info in db.items() if not info["workspace_dir"]]
    lines.append("## DB Consistency")
    lines.append("")
    lines.append(f"- Total DB sessions: **{len(db)}**")
    lines.append(f"- Empty workspace_dir: **{len(empty)}** "
                 "(execute will batch-fill these with an archived shared placeholder)")
    lines.append("")

    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text("\n".join(lines), encoding="utf-8")
    return str(plan_path)


# ════════════════════════════════════════════════════════
# 4. Archive execution.
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
    """Archive rows with action='ARCHIVE' and backfill DB workspace metadata.

    Returns {"moved": [...], "skipped": [...], "archive_root": Path,
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
            skipped.append((r["path"], "locked/sensitive — skipped"))
            continue

        src = WORKSPACE_PATH / r["path"]
        if not src.exists():
            skipped.append((r["path"], "source path does not exist"))
            continue
        if src.is_symlink():
            skipped.append((r["path"], "symlink; skipped"))
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
            skipped.append((r["path"], f"mv failed: {exc}"))
            logger.warning("Cleanup mv failed | path={} exc={!r}", r["path"], exc)

    # Write MANIFEST.
    manifest = archive_root / "MANIFEST.md"
    lines = [
        "# Cleanup Manifest",
        "",
        f"**Executed**: {datetime.now().isoformat(timespec='seconds')}",
        f"**Backup**: `{LAST_BACKUP.read_text().strip() if LAST_BACKUP.exists() else '(none)'}`",
        f"**Archive root**: `{archive_root}`",
        f"**Moved**: {len(moved)} | **Skipped**: {len(skipped)}",
        "",
        "## Archived Items",
        "",
        "| Source Path | Archived To | Category |",
        "|---|---|---|",
    ]
    for src, dst, cat in moved:
        lines.append(f"| `workspace/{src}` | `{dst}` | {cat} |")
    if skipped:
        lines.append("")
        lines.append("## Skipped Items")
        lines.append("")
        for n, reason in skipped:
            lines.append(f"- `{n}`: {reason}")
    manifest.write_text("\n".join(lines), encoding="utf-8")

    # _orphan_sessions_map.json
    (archive_root / "_orphan_sessions_map.json").write_text(
        json.dumps(sid_to_archive, indent=2)
    )

    # DB sync: backfill sessions with empty workspace_dir.
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
# 5. Restore from latest backup.
# ════════════════════════════════════════════════════════

def restore_from_backup(backup_path: Optional[Path] = None) -> dict:
    """Extract a backup tar into ~/.pawnlogic/. This overwrites current workspace content."""
    if backup_path is None:
        if not LAST_BACKUP.exists():
            return {"ok": False, "error": ".last_backup record not found"}
        backup_path = Path(LAST_BACKUP.read_text().strip())
    if not backup_path.exists():
        return {"ok": False, "error": f"backup file does not exist: {backup_path}"}

    try:
        with tarfile.open(backup_path, "r:gz") as tf:
            members = _validated_restore_members(tf, PAWN_HOME)
    except (tarfile.TarError, OSError, ValueError) as exc:
        return {"ok": False, "error": f"unsafe backup archive: {exc}"}

    # Rename current workspace to _replaced_<ts> only after the archive is
    # validated, so rejected backups leave current data untouched.
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    replaced: Path | None = None
    if WORKSPACE_PATH.exists():
        replaced = WORKSPACE_PATH.parent / f"workspace_replaced_{ts}"
        os.rename(str(WORKSPACE_PATH), str(replaced))

    with tarfile.open(backup_path, "r:gz") as tf:
        tf.extractall(str(PAWN_HOME), members=members)

    return {"ok": True, "restored_from": str(backup_path),
            "old_workspace_renamed_to": str(replaced) if replaced else None}


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
