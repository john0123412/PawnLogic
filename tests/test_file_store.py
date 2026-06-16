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
