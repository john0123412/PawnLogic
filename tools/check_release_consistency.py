"""Validate release-facing documentation agrees with config.paths.VERSION."""

from __future__ import annotations

from pathlib import Path
import re


VERSION_RE = re.compile(r'^VERSION = "([0-9]+\.[0-9]+\.[0-9]+)"$', re.MULTILINE)
README_RELEASE_RE = re.compile(
    r"The current public release is \*\*([0-9]+\.[0-9]+\.[0-9]+)\*\*\."
)
README_ZH_CN_RELEASE_RE = re.compile(
    r"\u5f53\u524d\u516c\u5f00\u53d1\u5e03\u7248\u672c\u662f "
    r"\*\*([0-9]+\.[0-9]+\.[0-9]+)\*\*\u3002"
)
CHANGELOG_SECTION_RE = re.compile(
    r"^## \[([0-9]+\.[0-9]+\.[0-9]+)\] - \d{4}-\d{2}-\d{2}$",
    re.MULTILINE,
)
SECURITY_SUPPORTED_ROW_RE = re.compile(
    r"^\|\s*([0-9]+\.[0-9]+\.[0-9]+)\s*\|\s*\u2705\s*Yes\s*\|",
    re.MULTILINE,
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _version(root: Path) -> str:
    match = VERSION_RE.search(_read(root / "config" / "paths.py"))
    if match is None:
        raise ValueError('config/paths.py must contain VERSION = "x.y.z"')
    return match.group(1)


def _check_single_version(
    *,
    errors: list[str],
    relative_path: str,
    text: str,
    pattern: re.Pattern[str],
    expected_version: str,
    description: str,
) -> None:
    match = pattern.search(text)
    if match is None:
        errors.append(f"{relative_path} is missing {description}")
        return
    found_version = match.group(1)
    if found_version != expected_version:
        errors.append(
            f"{relative_path} {description} is {found_version}, "
            f"expected {expected_version}"
        )


def check_repository(root: Path) -> list[str]:
    version = _version(root)
    errors: list[str] = []

    _check_single_version(
        errors=errors,
        relative_path="README.md",
        text=_read(root / "README.md"),
        pattern=README_RELEASE_RE,
        expected_version=version,
        description="public release version",
    )
    _check_single_version(
        errors=errors,
        relative_path="README_zh-CN.md",
        text=_read(root / "README_zh-CN.md"),
        pattern=README_ZH_CN_RELEASE_RE,
        expected_version=version,
        description="public release version",
    )

    changelog_versions = set(CHANGELOG_SECTION_RE.findall(_read(root / "CHANGELOG.md")))
    if version not in changelog_versions:
        errors.append(f"CHANGELOG.md is missing release section for {version}")

    supported_versions = set(
        SECURITY_SUPPORTED_ROW_RE.findall(_read(root / "SECURITY.md"))
    )
    if version not in supported_versions:
        errors.append(f"SECURITY.md does not mark {version} as supported")

    return errors


def main() -> int:
    errors = check_repository(Path(__file__).resolve().parents[1])
    if errors:
        for error in errors:
            print(f"- {error}")
        return 1
    print("Release consistency check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
