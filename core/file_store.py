"""Small atomic write helpers for runtime state files."""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path


def atomic_write_text(path: Path, text: str, *, mode: int | None = None) -> None:
    """Atomically replace a text file with flushed same-directory temp content."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    final_mode = mode
    if final_mode is None and target.exists():
        final_mode = target.stat().st_mode & 0o777

    tmp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_name = tmp.name
            tmp.write(text)
            tmp.flush()
            os.fsync(tmp.fileno())

        if final_mode is not None:
            os.chmod(tmp_name, final_mode)
        os.replace(tmp_name, target)
        tmp_name = ""
        _fsync_dir(target.parent)
    finally:
        if tmp_name:
            with suppress(FileNotFoundError):
                os.unlink(tmp_name)


def ensure_private_dir(path: Path, *, mode: int = 0o700) -> None:
    """Create a runtime directory and keep it private when the OS allows it."""
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    with suppress(OSError):
        os.chmod(target, mode)


def ensure_private_file(path: Path, *, mode: int = 0o600) -> None:
    """Apply private file permissions to an existing runtime file."""
    target = Path(path)
    if target.exists():
        with suppress(OSError):
            os.chmod(target, mode)


def _fsync_dir(path: Path) -> None:
    """Best-effort directory fsync after a replace."""
    if not hasattr(os, "O_DIRECTORY"):
        return
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
