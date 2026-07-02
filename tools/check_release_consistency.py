"""Validate release-facing documentation agrees with config.paths.VERSION."""

from __future__ import annotations

from pathlib import Path
import re


VERSION_RE = re.compile(r'^VERSION = "([0-9]+\.[0-9]+\.[0-9]+)"$', re.MULTILINE)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _version(root: Path) -> str:
    match = VERSION_RE.search(_read(root / "config" / "paths.py"))
    if match is None:
        raise ValueError('config/paths.py must contain VERSION = "x.y.z"')
    return match.group(1)


def check_repository(root: Path) -> list[str]:
    version = _version(root)
    errors: list[str] = []

    expectations = {
        "README.md": f"The current public release is **{version}**.",
        "README_zh-CN.md": f"当前公开发布版本是 **{version}**。",
        "CHANGELOG.md": f"## [{version}] - ",
        "SECURITY.md": f"| {version}   | ✅ Yes",
    }
    forbidden = {
        "README.md": "The current public release is **0.1.6**.",
        "README_zh-CN.md": "当前公开发布版本是 **0.1.6**。",
    }

    for relative_path, expected in expectations.items():
        text = _read(root / relative_path)
        if expected not in text:
            errors.append(f"{relative_path} is missing expected release text: {expected}")

    for relative_path, stale in forbidden.items():
        text = _read(root / relative_path)
        if version != "0.1.6" and stale in text:
            errors.append(f"{relative_path} still contains stale 0.1.6 public release text")

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
