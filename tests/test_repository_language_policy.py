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


def _chinese_text_violations(root: Path, relative_paths: list[str]) -> list[str]:
    violations: list[str] = []

    for relative_path in relative_paths:
        path = root / relative_path
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

    return violations


def test_chinese_text_only_appears_in_zh_cn_files():
    violations = _chinese_text_violations(ROOT, _tracked_files())

    assert not violations, (
        "Chinese text is only allowed in tracked files whose filename stem "
        "ends with _zh-CN:\n" + "\n".join(violations)
    )


def test_language_policy_rejects_chinese_text_in_non_zh_cn_tracked_file(tmp_path):
    doc = tmp_path / "docs" / "example.md"
    doc.parent.mkdir()
    restricted_text = "\u4e2d\u6587"
    doc.write_text(f"English\n{restricted_text}\n", encoding="utf-8")

    violations = _chinese_text_violations(tmp_path, ["docs/example.md"])

    assert violations == [f"docs/example.md:2: {restricted_text}"]


def test_legacy_cn_documentation_filenames_are_not_tracked():
    legacy_names = {"README_CN.md", "GUIDE_CN.md"}

    assert legacy_names.isdisjoint(_tracked_files())
