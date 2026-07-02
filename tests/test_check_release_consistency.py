from __future__ import annotations

from pathlib import Path

from tools import check_release_consistency


def _write_release_fixture(root: Path, *, version: str = "9.9.9") -> None:
    (root / "config").mkdir()
    (root / "config" / "paths.py").write_text(
        f'VERSION = "{version}"\n',
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        f"The current public release is **{version}**.\n",
        encoding="utf-8",
    )
    (root / "README_zh-CN.md").write_text(
        f"\u5f53\u524d\u516c\u5f00\u53d1\u5e03\u7248\u672c\u662f **{version}**\u3002\n",
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(
        f"## [{version}] - 2099-01-01\n",
        encoding="utf-8",
    )
    (root / "SECURITY.md").write_text(
        f"| {version} | \u2705 Yes |\n",
        encoding="utf-8",
    )


def test_release_consistency_accepts_current_repository():
    errors = check_release_consistency.check_repository(Path(__file__).resolve().parents[1])

    assert errors == []


def test_release_consistency_accepts_version_derived_fixture(tmp_path):
    _write_release_fixture(tmp_path, version="2.3.4")

    errors = check_release_consistency.check_repository(tmp_path)

    assert errors == []


def test_release_consistency_rejects_stale_english_readme_version(tmp_path):
    _write_release_fixture(tmp_path)
    (tmp_path / "README.md").write_text(
        "The current public release is **1.2.3**.\n",
        encoding="utf-8",
    )

    errors = check_release_consistency.check_repository(tmp_path)

    assert any("README.md public release version is 1.2.3" in error for error in errors)


def test_release_consistency_rejects_stale_zh_cn_readme_version(tmp_path):
    _write_release_fixture(tmp_path)
    (tmp_path / "README_zh-CN.md").write_text(
        "\u5f53\u524d\u516c\u5f00\u53d1\u5e03\u7248\u672c\u662f **1.2.3**\u3002\n",
        encoding="utf-8",
    )

    errors = check_release_consistency.check_repository(tmp_path)

    assert any(
        "README_zh-CN.md public release version is 1.2.3" in error
        for error in errors
    )


def test_release_consistency_rejects_missing_changelog_section(tmp_path):
    _write_release_fixture(tmp_path)
    (tmp_path / "CHANGELOG.md").write_text(
        "## [1.2.3] - 2099-01-01\n",
        encoding="utf-8",
    )

    errors = check_release_consistency.check_repository(tmp_path)

    assert any("CHANGELOG.md is missing release section for 9.9.9" in error for error in errors)


def test_release_consistency_rejects_unsupported_security_version(tmp_path):
    _write_release_fixture(tmp_path)
    (tmp_path / "SECURITY.md").write_text(
        "| 9.9.9 | Upgrade recommended |\n",
        encoding="utf-8",
    )

    errors = check_release_consistency.check_repository(tmp_path)

    assert any("SECURITY.md does not mark 9.9.9 as supported" in error for error in errors)


def test_release_consistency_reports_multiple_release_doc_mismatches(tmp_path):
    root = tmp_path
    _write_release_fixture(root)
    (root / "README.md").write_text(
        "The current public release is **1.2.3**.\n",
        encoding="utf-8",
    )
    (root / "README_zh-CN.md").write_text(
        "\u5f53\u524d\u516c\u5f00\u53d1\u5e03\u7248\u672c\u662f **1.2.3**\u3002\n",
        encoding="utf-8",
    )
    errors = check_release_consistency.check_repository(root)

    assert any("README.md" in error for error in errors)
    assert any("README_zh-CN.md" in error for error in errors)


def test_release_consistency_checker_does_not_hardcode_historical_versions():
    checker_source = Path(check_release_consistency.__file__).read_text(encoding="utf-8")

    assert "0.1.6" not in checker_source
