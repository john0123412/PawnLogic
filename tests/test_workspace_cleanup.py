from __future__ import annotations

import io
import importlib
import sys
import tarfile
from pathlib import Path


def _drop_project_modules(*module_names: str) -> None:
    for name in module_names:
        sys.modules.pop(name, None)
        prefix = name + "."
        for loaded in list(sys.modules):
            if loaded.startswith(prefix):
                sys.modules.pop(loaded, None)
    core_module = sys.modules.get("core")
    if core_module is not None and hasattr(core_module, "workspace_cleanup"):
        delattr(core_module, "workspace_cleanup")


def _load_workspace_cleanup(monkeypatch, tmp_path: Path):
    runtime_home = tmp_path / "pawn-home"
    monkeypatch.setenv("PAWNLOGIC_HOME", str(runtime_home))
    _drop_project_modules("config", "core.workspace_cleanup")
    return importlib.import_module("core.workspace_cleanup")


def _add_file(tf: tarfile.TarFile, name: str, content: bytes = b"restored") -> None:
    info = tarfile.TarInfo(name)
    info.mode = 0o644
    info.size = len(content)
    tf.addfile(info, io.BytesIO(content))


def _write_tar(path: Path, members) -> Path:
    with tarfile.open(path, "w:gz") as tf:
        for member in members:
            kind = member[0]
            if kind == "file":
                _add_file(tf, member[1], member[2] if len(member) > 2 else b"restored")
            elif kind == "dir":
                info = tarfile.TarInfo(member[1])
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tf.addfile(info)
            elif kind == "symlink":
                info = tarfile.TarInfo(member[1])
                info.type = tarfile.SYMTYPE
                info.linkname = member[2]
                tf.addfile(info)
            elif kind == "hardlink":
                info = tarfile.TarInfo(member[1])
                info.type = tarfile.LNKTYPE
                info.linkname = member[2]
                tf.addfile(info)
            elif kind == "special":
                info = tarfile.TarInfo(member[1])
                info.type = member[2]
                tf.addfile(info)
            else:
                raise AssertionError(f"unknown member kind: {kind}")
    return path


def test_restore_backup_round_trips_workspace_and_renames_existing_workspace(monkeypatch, tmp_path):
    wc = _load_workspace_cleanup(monkeypatch, tmp_path)
    wc.WORKSPACE_PATH.mkdir(parents=True)
    (wc.WORKSPACE_PATH / "old.txt").write_text("old", encoding="utf-8")

    backup = _write_tar(
        tmp_path / "backup.tar.gz",
        [
            ("dir", "workspace"),
            ("file", "workspace/restored.txt", b"new"),
        ],
    )

    result = wc.restore_from_backup(backup)

    assert result["ok"] is True
    assert (wc.WORKSPACE_PATH / "restored.txt").read_text(encoding="utf-8") == "new"
    replaced = Path(result["old_workspace_renamed_to"])
    assert replaced.exists()
    assert (replaced / "old.txt").read_text(encoding="utf-8") == "old"


def test_restore_without_existing_workspace_does_not_reference_unset_replacement(
    monkeypatch, tmp_path
):
    wc = _load_workspace_cleanup(monkeypatch, tmp_path)
    backup = _write_tar(
        tmp_path / "backup.tar.gz",
        [
            ("dir", "workspace"),
            ("file", "workspace/restored.txt", b"new"),
        ],
    )

    result = wc.restore_from_backup(backup)

    assert result["ok"] is True
    assert result["old_workspace_renamed_to"] is None
    assert (wc.WORKSPACE_PATH / "restored.txt").read_text(encoding="utf-8") == "new"


def test_restore_rejects_absolute_member_path_without_moving_workspace(monkeypatch, tmp_path):
    wc = _load_workspace_cleanup(monkeypatch, tmp_path)
    wc.WORKSPACE_PATH.mkdir(parents=True)
    (wc.WORKSPACE_PATH / "keep.txt").write_text("keep", encoding="utf-8")
    escaped = tmp_path / "escaped.txt"
    backup = _write_tar(tmp_path / "bad.tar.gz", [("file", str(escaped), b"escape")])

    result = wc.restore_from_backup(backup)

    assert result["ok"] is False
    assert "unsafe" in result["error"].lower()
    assert not escaped.exists()
    assert (wc.WORKSPACE_PATH / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_restore_rejects_parent_traversal_without_moving_workspace(monkeypatch, tmp_path):
    wc = _load_workspace_cleanup(monkeypatch, tmp_path)
    wc.WORKSPACE_PATH.mkdir(parents=True)
    (wc.WORKSPACE_PATH / "keep.txt").write_text("keep", encoding="utf-8")
    backup = _write_tar(tmp_path / "bad.tar.gz", [("file", "../escaped.txt", b"escape")])

    result = wc.restore_from_backup(backup)

    assert result["ok"] is False
    assert "unsafe" in result["error"].lower()
    assert not (wc.PAWN_HOME.parent / "escaped.txt").exists()
    assert (wc.WORKSPACE_PATH / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_restore_rejects_symlink_to_outside_home(monkeypatch, tmp_path):
    wc = _load_workspace_cleanup(monkeypatch, tmp_path)
    wc.WORKSPACE_PATH.mkdir(parents=True)
    outside = tmp_path / "outside-target"
    backup = _write_tar(
        tmp_path / "bad.tar.gz",
        [
            ("dir", "workspace"),
            ("symlink", "workspace/link", str(outside)),
        ],
    )

    result = wc.restore_from_backup(backup)

    assert result["ok"] is False
    assert "unsafe" in result["error"].lower()
    assert not (wc.WORKSPACE_PATH / "link").exists()


def test_restore_rejects_hardlink_to_outside_home(monkeypatch, tmp_path):
    wc = _load_workspace_cleanup(monkeypatch, tmp_path)
    wc.WORKSPACE_PATH.mkdir(parents=True)
    outside = tmp_path / "outside-source"
    outside.write_text("outside", encoding="utf-8")
    backup = _write_tar(
        tmp_path / "bad.tar.gz",
        [
            ("dir", "workspace"),
            ("hardlink", "workspace/link", str(outside)),
        ],
    )

    result = wc.restore_from_backup(backup)

    assert result["ok"] is False
    assert "unsafe" in result["error"].lower()
    assert not (wc.WORKSPACE_PATH / "link").exists()


def test_restore_rejects_special_file_members(monkeypatch, tmp_path):
    wc = _load_workspace_cleanup(monkeypatch, tmp_path)
    wc.WORKSPACE_PATH.mkdir(parents=True)
    backup = _write_tar(
        tmp_path / "bad.tar.gz",
        [
            ("dir", "workspace"),
            ("special", "workspace/fifo", tarfile.FIFOTYPE),
        ],
    )

    result = wc.restore_from_backup(backup)

    assert result["ok"] is False
    assert "unsafe" in result["error"].lower()
    assert not (wc.WORKSPACE_PATH / "fifo").exists()


def test_scan_classifies_loose_files_and_safe_directories(monkeypatch, tmp_path):
    wc = _load_workspace_cleanup(monkeypatch, tmp_path)
    wc.WORKSPACE_PATH.mkdir(parents=True)
    (wc.WORKSPACE_PATH / "screenshots").mkdir()
    (wc.WORKSPACE_PATH / "exploit.py").write_text("print('x')", encoding="utf-8")

    rows, db = wc.scan()

    assert db == {}
    by_path = {row["path"]: row for row in rows}
    assert by_path["screenshots"]["action"] == "KEEP"
    assert by_path["exploit.py"]["category"] == "legacy_exploits"
