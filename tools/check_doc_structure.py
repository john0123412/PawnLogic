"""Validate that translated documentation keeps matching heading structure."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
PAIRS = (
    ("README.md", "README_CN.md"),
    ("GUIDE.md", "GUIDE_CN.md"),
)
CLAUDE_WRAPPER_MAX_LINES = 20


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    line: int


def collect_headings(path: Path) -> list[Heading]:
    headings: list[Heading] = []
    in_fence = False

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw_line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence or not raw_line.startswith("#"):
            continue

        marker, _, text = raw_line.partition(" ")
        if not text or set(marker) != {"#"} or len(marker) > 6:
            continue
        headings.append(Heading(level=len(marker), text=text.strip(), line=line_number))

    return headings


def describe_heading(path: str, heading: Heading | None) -> str:
    if heading is None:
        return f"{path}:<missing>"
    return f"{path}:{heading.line}: {'#' * heading.level} {heading.text}"


def compare_pair(left_path: str, right_path: str) -> list[str]:
    left = collect_headings(ROOT / left_path)
    right = collect_headings(ROOT / right_path)
    errors: list[str] = []

    if len(left) != len(right):
        errors.append(
            f"{left_path} has {len(left)} headings, but {right_path} has {len(right)} headings."
        )

    for index in range(max(len(left), len(right))):
        left_heading = left[index] if index < len(left) else None
        right_heading = right[index] if index < len(right) else None
        if left_heading is None or right_heading is None:
            errors.append(
                "Missing translated heading at position "
                f"{index + 1}: {describe_heading(left_path, left_heading)} | "
                f"{describe_heading(right_path, right_heading)}"
            )
            continue
        if left_heading.level != right_heading.level:
            errors.append(
                "Heading level mismatch at position "
                f"{index + 1}: {describe_heading(left_path, left_heading)} | "
                f"{describe_heading(right_path, right_heading)}"
            )

    return errors


def check_claude_wrapper() -> list[str]:
    path = ROOT / "CLAUDE.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    errors: list[str] = []

    if "@AGENT.md" not in lines:
        errors.append("CLAUDE.md must import AGENT.md with a standalone @AGENT.md line.")
    if len(lines) > CLAUDE_WRAPPER_MAX_LINES:
        errors.append(
            f"CLAUDE.md should stay a thin wrapper; found {len(lines)} lines, "
            f"limit is {CLAUDE_WRAPPER_MAX_LINES}."
        )
    if any(line.startswith("## ") for line in lines):
        errors.append("CLAUDE.md must not duplicate AGENT.md sections.")

    return errors


def main() -> int:
    errors: list[str] = []
    for left_path, right_path in PAIRS:
        errors.extend(compare_pair(left_path, right_path))
    errors.extend(check_claude_wrapper())

    if errors:
        print("Documentation heading structure check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Documentation heading structure check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
