#!/usr/bin/env python3
"""Check per-file line count and complexity budgets.

Fails only when a tracked file exceeds its recorded budget. New files that
are not yet in the budget list are reported but do not cause failure.

Usage:
    python tools/check_architecture_budget.py [--json]
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Per-file budgets: (max_lines, max_complexity).
# Complexity uses a simple McCabe-style count of branching nodes.
# These are regression ceilings, not aspirational targets.
BUDGETS: dict[str, tuple[int, int]] = {
    "core/session.py": (2100, 310),
    "pawnlogic/cli.py": (1200, 140),
    "core/provider_tui.py": (1100, 195),
    "core/memory.py": (1000, 170),
    "tools/file_ops.py": (650, 105),
    "tools/docker_sandbox.py": (800, 115),
    "tools/pwn_chain.py": (650, 90),
    "tools/browser_ops.py": (500, 80),
    "tools/web_ops.py": (500, 90),
    "tools/sandbox.py": (400, 65),
    "tools/delegate_tool.py": (400, 40),
    "core/commands/provider.py": (800, 125),
    "core/provider_runtime.py": (400, 70),
    "core/api_client.py": (600, 105),
    "core/runtime_context.py": (300, 15),
    "core/session_tool_loop.py": (300, 15),
    "core/session_snapshot.py": (200, 10),
    "core/message_history.py": (50, 15),
}


def _count_lines(path: Path) -> int:
    """Count non-blank, non-comment lines."""
    count = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            count += 1
    return count


def _count_complexity(path: Path) -> int:
    """Count branching nodes (if/elif/for/while/with/try/except/and/or)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return -1
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
            count += 1
        elif isinstance(node, ast.BoolOp):
            count += len(node.values) - 1
    return count


def check_budgets(*, as_json: bool = False) -> list[dict[str, object]]:
    violations: list[dict[str, object]] = []
    tracked_files = set()
    unknown_files: list[str] = []

    for rel_path, (max_lines, max_complexity) in BUDGETS.items():
        full_path = REPO_ROOT / rel_path
        tracked_files.add(rel_path)
        if not full_path.exists():
            violations.append(
                {
                    "file": rel_path,
                    "status": "missing",
                    "message": f"budgeted file not found: {rel_path}",
                }
            )
            continue
        lines = _count_lines(full_path)
        complexity = _count_complexity(full_path)
        over_lines = lines > max_lines
        over_complexity = complexity > max_complexity
        if over_lines or over_complexity:
            violations.append(
                {
                    "file": rel_path,
                    "status": "over_budget",
                    "lines": lines,
                    "max_lines": max_lines,
                    "complexity": complexity,
                    "max_complexity": max_complexity,
                }
            )

    # Report unbudgeted large files for awareness (not failure).
    for scan_dir in ("core", "tools", "pawnlogic"):
        scan_root = REPO_ROOT / scan_dir
        if not scan_root.is_dir():
            continue
        for py_file in sorted(scan_root.rglob("*.py")):
            rel = str(py_file.relative_to(REPO_ROOT))
            if rel in tracked_files:
                continue
            lines = _count_lines(py_file)
            if lines > 300:
                unknown_files.append(f"{rel} ({lines} lines)")

    if as_json:
        result = {"violations": violations, "unbudgeted_large": unknown_files}
        print(json.dumps(result, indent=2))
        return violations

    if violations:
        print("Architecture budget violations:")
        for v in violations:
            if v["status"] == "missing":
                print(f"  MISSING  {v['file']}")
            else:
                print(
                    f"  OVER     {v['file']}: "
                    f"lines {v['lines']}/{v['max_lines']}, "
                    f"complexity {v['complexity']}/{v['max_complexity']}"
                )

    if unknown_files:
        print("\nUnbudgeted files over 300 lines (informational):")
        for f in unknown_files:
            print(f"  INFO     {f}")

    if not violations and not unknown_files:
        print("All architecture budgets satisfied.")

    return violations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()
    violations = check_budgets(as_json=args.json)
    if violations:
        sys.exit(1)


if __name__ == "__main__":
    main()
