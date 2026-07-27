"""Validate release-facing documentation agrees with config.paths.VERSION."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess


VERSION_RE = re.compile(r'^VERSION = "([0-9]+\.[0-9]+\.[0-9]+)"$', re.MULTILINE)
README_RELEASE_RE = re.compile(
    r"The current public release is \*\*([0-9]+\.[0-9]+\.[0-9]+)\*\*\."
)
README_ZH_CN_RELEASE_RE = re.compile(
    r"\u5f53\u524d\u516c\u5f00\u53d1\u5e03\u7248\u672c\u662f "
    r"\*\*([0-9]+\.[0-9]+\.[0-9]+)\*\*\u3002"
)
README_CANDIDATE_RE = re.compile(
    r"Version\s+\*\*([0-9]+\.[0-9]+\.[0-9]+)\*\*\s+is an unreleased release candidate"
)
README_ZH_CN_CANDIDATE_RE = re.compile(
    r"\u7248\u672c\s*\*\*([0-9]+\.[0-9]+\.[0-9]+)\*\*\s*"
    r"\u662f\u5c1a\u672a\u53d1\u5e03\u7684\u5019\u9009\u7248\u672c"
)
CHANGELOG_SECTION_RE = re.compile(
    r"^## \[([0-9]+\.[0-9]+\.[0-9]+)\] - \d{4}-\d{2}-\d{2}$",
    re.MULTILINE,
)
SECURITY_SUPPORTED_ROW_RE = re.compile(
    r"^\|\s*([0-9]+\.[0-9]+\.[0-9]+)\s*\|\s*\u2705\s*Yes\s*\|",
    re.MULTILINE,
)
TAG_RE = re.compile(r"^v([0-9]+\.[0-9]+\.[0-9]+)$")
RELEASE_READY_FILE = ".release-ready"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _version(root: Path) -> str:
    match = VERSION_RE.search(_read(root / "config" / "paths.py"))
    if match is None:
        raise ValueError('config/paths.py must contain VERSION = "x.y.z"')
    return match.group(1)


def _latest_release_tag(root: Path) -> str | None:
    """Return the highest ``vX.Y.Z`` tag, or None when tags are unavailable.

    Shallow CI checkouts and unpacked sdists have no tags. Returning None keeps
    those contexts usable instead of failing them for missing history, and the
    caller reports the skip rather than silently treating it as a pass.
    """
    try:
        completed = subprocess.run(
            ["git", "tag", "--list", "v*"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    versions: list[tuple[int, ...]] = []
    for line in completed.stdout.splitlines():
        match = TAG_RE.match(line.strip())
        if match is not None:
            versions.append(tuple(int(part) for part in match.group(1).split(".")))
    if not versions:
        return None
    return ".".join(str(part) for part in max(versions))


def _release_ready_version(root: Path) -> str | None:
    """Return the explicitly staged release version, if present."""
    path = root / RELEASE_READY_FILE
    if not path.is_file():
        return None
    value = path.read_text(encoding="utf-8").strip()
    if TAG_RE.fullmatch(f"v{value}") is None:
        raise ValueError(f"{RELEASE_READY_FILE} must contain exactly x.y.z")
    return value


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


def _check_release_candidate_is_declared(
    *,
    errors: list[str],
    root: Path,
    version: str,
) -> None:
    """Require both READMEs to name an unpublished working version as a candidate.

    Without this a release-candidate branch could omit the candidate entirely
    and read as though the repository were the published version.
    """
    for relative_path, pattern in (
        ("README.md", README_CANDIDATE_RE),
        ("README_zh-CN.md", README_ZH_CN_CANDIDATE_RE),
    ):
        match = pattern.search(_read(root / relative_path))
        if match is None:
            errors.append(
                f"{relative_path} must describe {version} as an unreleased "
                f"release candidate while it differs from the public release"
            )
        elif match.group(1) != version:
            errors.append(
                f"{relative_path} names {match.group(1)} as the unreleased "
                f"release candidate, expected {version}"
            )


def check_repository(root: Path) -> list[str]:
    version = _version(root)
    errors: list[str] = []

    # The published version is the newest release tag, never the working
    # version. Comparing the README claim against config/paths.py only proved
    # the docs agreed with themselves, so bumping VERSION on a candidate branch
    # used to make "the current public release is <VERSION>" pass while false.
    published = _latest_release_tag(root)
    if published is None:
        # Shallow checkouts and unpacked sdists have no tags. Fall back to the
        # working version so those contexts stay usable, and say so.
        print(
            "- note: no release tags found, comparing README claims against "
            "config/paths.py VERSION"
        )
        published = version

    release_ready = _release_ready_version(root)
    expected_public = published
    if release_ready is not None:
        if release_ready != version:
            errors.append(
                f"{RELEASE_READY_FILE} declares {release_ready}, expected {version}"
            )
        else:
            # A reviewed release-finalization commit has to land on main before
            # its tag can exist. This explicit, version-pinned marker permits
            # that short staging state without treating every VERSION bump as
            # a public release.
            expected_public = version

    _check_single_version(
        errors=errors,
        relative_path="README.md",
        text=_read(root / "README.md"),
        pattern=README_RELEASE_RE,
        expected_version=expected_public,
        description="public release version",
    )
    _check_single_version(
        errors=errors,
        relative_path="README_zh-CN.md",
        text=_read(root / "README_zh-CN.md"),
        pattern=README_ZH_CN_RELEASE_RE,
        expected_version=expected_public,
        description="public release version",
    )

    if version != expected_public:
        _check_release_candidate_is_declared(errors=errors, root=root, version=version)

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
