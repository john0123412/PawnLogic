"""Repository language policy tests."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def test_chinese_text_only_appears_in_zh_cn_files():
    violations: list[str] = []

    for relative_path in _tracked_files():
        path = ROOT / relative_path
        if path.stem.endswith("_zh-CN"):
            continue

        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        except FileNotFoundError:
            continue

        for line_no, line in enumerate(lines, start=1):
            if any("\u4e00" <= char <= "\u9fff" for char in line):
                violations.append(f"{relative_path}:{line_no}: {line}")

    assert not violations, (
        "Chinese text is only allowed in tracked files whose filename stem "
        "ends with _zh-CN:\n" + "\n".join(violations)
    )
