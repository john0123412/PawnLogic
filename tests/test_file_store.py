"""Atomic runtime file write tests."""

from __future__ import annotations

import os
import stat

from core import file_store


def test_atomic_write_text_uses_replace_and_cleans_temp(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    calls: list[tuple[str, str]] = []
    real_replace = os.replace

    def wrapped_replace(src, dst):
        calls.append((str(src), str(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(file_store.os, "replace", wrapped_replace)

    file_store.atomic_write_text(target, '{"ok": true}')

    assert target.read_text(encoding="utf-8") == '{"ok": true}'
    assert calls
    src, dst = calls[0]
    assert dst == str(target)
    assert src.startswith(str(tmp_path / ".state.json."))
    assert not list(tmp_path.glob(".state.json.*.tmp"))


def test_atomic_write_text_preserves_existing_mode(tmp_path):
    target = tmp_path / "custom_providers.json"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o640)

    file_store.atomic_write_text(target, "new")

    assert target.read_text(encoding="utf-8") == "new"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_atomic_write_text_applies_requested_mode(tmp_path):
    target = tmp_path / ".env"

    file_store.atomic_write_text(target, "TOKEN=value\n", mode=0o600)

    assert target.read_text(encoding="utf-8") == "TOKEN=value\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_private_runtime_permissions_helpers(tmp_path):
    directory = tmp_path / "runtime"
    target = directory / "pawn.db"

    file_store.ensure_private_dir(directory)
    target.write_text("db", encoding="utf-8")
    file_store.ensure_private_file(target)

    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_private_log_opener_creates_private_file(tmp_path):
    from core import logger as logger_mod

    log_file = tmp_path / "pawnlogic.log"
    fd = logger_mod._private_log_opener(str(log_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    os.close(fd)

    assert stat.S_IMODE(log_file.stat().st_mode) == 0o600
