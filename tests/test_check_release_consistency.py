from __future__ import annotations

from pathlib import Path
import subprocess

from tools import check_release_consistency


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _tag_fixture_repository(root: Path, tag: str) -> None:
    """Give the fixture a real tagged history, since the check reads git tags."""
    _git(root, "init", "-q")
    _git(root, "commit", "-q", "--allow-empty", "-m", "seed")
    _git(root, "tag", tag)


def _declare_candidate(root: Path, *, public: str, candidate: str) -> None:
    (root / "README.md").write_text(
        f"The current public release is **{public}**. Version\n"
        f"**{candidate}** is an unreleased release candidate and is not on PyPI yet.\n",
        encoding="utf-8",
    )
    (root / "README_zh-CN.md").write_text(
        f"\u5f53\u524d\u516c\u5f00\u53d1\u5e03\u7248\u672c\u662f **{public}**\u3002"
        f"\u7248\u672c **{candidate}** "
        f"\u662f\u5c1a\u672a\u53d1\u5e03\u7684\u5019\u9009\u7248\u672c\u3002\n",
        encoding="utf-8",
    )


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


def test_release_consistency_rejects_english_zh_cn_readme_version_mismatch(tmp_path):
    _write_release_fixture(tmp_path, version="9.9.9")
    (tmp_path / "README_zh-CN.md").write_text(
        "\u5f53\u524d\u516c\u5f00\u53d1\u5e03\u7248\u672c\u662f **9.9.8**\u3002\n",
        encoding="utf-8",
    )

    errors = check_release_consistency.check_repository(tmp_path)

    assert any(
        "README_zh-CN.md public release version is 9.9.8, expected 9.9.9" in error
        for error in errors
    )
    assert not any("README.md public release version" in error for error in errors)


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


def test_release_consistency_rejects_unpublished_version_claimed_as_public(tmp_path):
    """The 0.3.0 regression: bumping VERSION made the README claim pass while false."""
    _write_release_fixture(tmp_path, version="9.9.9")
    _tag_fixture_repository(tmp_path, "v9.9.8")

    errors = check_release_consistency.check_repository(tmp_path)

    assert any(
        "README.md public release version is 9.9.9, expected 9.9.8" in error
        for error in errors
    )
    assert any(
        "README_zh-CN.md public release version is 9.9.9, expected 9.9.8" in error
        for error in errors
    )


def test_release_consistency_accepts_a_declared_release_candidate(tmp_path):
    _write_release_fixture(tmp_path, version="9.9.9")
    _tag_fixture_repository(tmp_path, "v9.9.8")
    _declare_candidate(tmp_path, public="9.9.8", candidate="9.9.9")

    errors = check_release_consistency.check_repository(tmp_path)

    assert errors == []


def test_release_consistency_accepts_explicit_release_ready_marker(tmp_path):
    _write_release_fixture(tmp_path, version="9.9.9")
    _tag_fixture_repository(tmp_path, "v9.9.8")
    (tmp_path / ".release-ready").write_text("9.9.9\n", encoding="utf-8")

    errors = check_release_consistency.check_repository(tmp_path)

    assert errors == []


def test_release_consistency_rejects_stale_release_ready_marker(tmp_path):
    _write_release_fixture(tmp_path, version="9.9.9")
    _tag_fixture_repository(tmp_path, "v9.9.8")
    (tmp_path / ".release-ready").write_text("9.9.7\n", encoding="utf-8")

    errors = check_release_consistency.check_repository(tmp_path)

    assert any(
        ".release-ready declares 9.9.7, expected 9.9.9" in error for error in errors
    )


def test_release_consistency_requires_the_candidate_to_be_declared(tmp_path):
    _write_release_fixture(tmp_path, version="9.9.9")
    _tag_fixture_repository(tmp_path, "v9.9.8")
    # Correct public release, but the working version is never mentioned.
    (tmp_path / "README.md").write_text(
        "The current public release is **9.9.8**.\n", encoding="utf-8"
    )
    (tmp_path / "README_zh-CN.md").write_text(
        "\u5f53\u524d\u516c\u5f00\u53d1\u5e03\u7248\u672c\u662f **9.9.8**\u3002\n",
        encoding="utf-8",
    )

    errors = check_release_consistency.check_repository(tmp_path)

    assert any(
        "README.md must describe 9.9.9 as an unreleased release candidate" in error
        for error in errors
    )
    assert any(
        "README_zh-CN.md must describe 9.9.9 as an unreleased release candidate" in error
        for error in errors
    )


def test_release_consistency_rejects_a_stale_candidate_version(tmp_path):
    _write_release_fixture(tmp_path, version="9.9.9")
    _tag_fixture_repository(tmp_path, "v9.9.8")
    _declare_candidate(tmp_path, public="9.9.8", candidate="9.9.7")

    errors = check_release_consistency.check_repository(tmp_path)

    assert any(
        "README.md names 9.9.7 as the unreleased release candidate, expected 9.9.9"
        in error
        for error in errors
    )


def test_release_consistency_falls_back_to_version_without_tags(tmp_path):
    """An untagged tree (sdist, shallow clone) stays checkable against VERSION."""
    _write_release_fixture(tmp_path, version="9.9.9")

    errors = check_release_consistency.check_repository(tmp_path)

    assert errors == []


def test_release_consistency_ignores_non_release_tags(tmp_path):
    _write_release_fixture(tmp_path, version="9.9.9")
    _tag_fixture_repository(tmp_path, "v9.9.9")
    _git(tmp_path, "tag", "v-not-a-release")
    _git(tmp_path, "tag", "nightly")

    errors = check_release_consistency.check_repository(tmp_path)

    assert errors == []
