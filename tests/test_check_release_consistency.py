from __future__ import annotations

from pathlib import Path

from tools import check_release_consistency


def test_release_consistency_accepts_current_repository():
    errors = check_release_consistency.check_repository(Path(__file__).resolve().parents[1])

    assert errors == []


def test_release_consistency_rejects_stale_readme_version(tmp_path):
    root = tmp_path
    (root / "config").mkdir()
    (root / "config" / "paths.py").write_text('VERSION = "9.9.9"\n', encoding="utf-8")
    (root / "README.md").write_text(
        "The current public release is **1.2.3**.\n",
        encoding="utf-8",
    )
    (root / "README_zh-CN.md").write_text(
        "\u5f53\u524d\u516c\u5f00\u53d1\u5e03\u7248\u672c\u662f **1.2.3**\u3002\n",
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text("## [9.9.9] - 2099-01-01\n", encoding="utf-8")
    (root / "SECURITY.md").write_text("| 9.9.9 | ✅ Yes |\n", encoding="utf-8")

    errors = check_release_consistency.check_repository(root)

    assert any("README.md" in error for error in errors)
    assert any("README_zh-CN.md" in error for error in errors)
