"""Aider-style SEARCH/REPLACE matching and atomic patch orchestration."""

from __future__ import annotations

from collections.abc import Callable
import difflib
from pathlib import Path
import re

PATCH_BLOCK_RE = re.compile(
    r"<<<<<<+\s*SEARCH\s*\n(.*?)=======+\s*\n(.*?)>>>>>>>+\s*REPLACE",
    re.DOTALL,
)


def normalize_indent(text: str) -> str:
    lines = text.splitlines()
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        return text
    minimum = min(len(line) - len(line.lstrip()) for line in non_empty)
    return "\n".join(line[minimum:] if len(line) >= minimum else line for line in lines)


def find_search_in_file(
    file_lines: list[str],
    search_text: str,
    indent_tolerance: int = 4,
) -> tuple[int, int] | None:
    del indent_tolerance
    file_text = "".join(file_lines)
    search = search_text.rstrip("\n")
    if search in file_text:
        position = file_text.find(search)
        start = file_text[:position].count("\n")
        return start, start + search.count("\n") + 1
    search_lines = [line.rstrip() for line in search.splitlines()]
    stripped_file = [line.rstrip() for line in file_lines]
    count = len(search_lines)
    for index in range(len(stripped_file) - count + 1):
        if stripped_file[index : index + count] == search_lines:
            return index, index + count
    normalized = normalize_indent(search).splitlines()
    for index in range(len(file_lines) - count + 1):
        window = "".join(file_lines[index : index + count])
        candidate = normalize_indent(window.rstrip("\n")).splitlines()
        if [line.rstrip() for line in candidate] == [line.rstrip() for line in normalized]:
            return index, index + count
    return None


def line_similarity(left: str, right: str) -> float:
    left, right = left.strip(), right.strip()
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(None, left, right, autojunk=False).ratio()


def diagnose_mismatch(search_line: str, file_line: str, file_lineno: int) -> str:
    hints: list[str] = []
    search_indent = len(search_line) - len(search_line.lstrip())
    file_indent = len(file_line) - len(file_line.lstrip())
    if search_indent != file_indent:
        hints.append(
            f"indentation mismatch: your SEARCH has {search_indent} leading spaces, "
            f"file line {file_lineno} has {file_indent}"
        )
    if search_line.endswith("\r") or file_line.endswith("\r"):
        hints.append("possible CRLF/LF line-ending mismatch")
    if search_line.rstrip() != file_line.rstrip() and search_line.strip() == file_line.strip():
        hints.append("trailing whitespace difference only")
    if not hints:
        hints.append("content differs — copy the exact file content into SEARCH")
    return "; ".join(hints)


def best_match_context(
    file_lines: list[str],
    search_text: str,
    context_radius: int = 3,
) -> str:
    search_lines = search_text.rstrip("\n").splitlines()
    if not search_lines:
        return "  (SEARCH block is empty; cannot locate content)"
    if not file_lines:
        return "  (file is empty)"
    matches: list[tuple[int, float]] = []
    for search_line in search_lines:
        scored = [
            (index, line_similarity(search_line, file_line))
            for index, file_line in enumerate(file_lines)
        ]
        matches.append(max(scored, key=lambda item: item[1]))
    output = ["  [Per-line similarity report]"]
    for index, search_line in enumerate(search_lines):
        file_index, score = matches[index]
        file_lineno = file_index + 1
        output.append(
            f"  Your SEARCH line {index + 1} is {int(score * 100)}% similar to file line {file_lineno}."
        )
        if score < 1.0:
            output.append(
                f"    Hint: {diagnose_mismatch(search_line, file_lines[file_index], file_lineno)}."
            )
    anchor = matches[0][0]
    start = max(0, anchor - context_radius)
    end = min(len(file_lines), anchor + max(len(search_lines), context_radius) + 1)
    output.append(f"\n  [File context around line {anchor + 1}]")
    for index in range(start, end):
        marker = ">>>" if index == anchor else "   "
        output.append(f"  {marker} L{index + 1:5d}: {file_lines[index].rstrip()}")
    return "\n".join(output)


def apply_patch_blocks(
    path: str,
    patch_blocks_text: str,
    *,
    resolve_write_path: Callable[[str], tuple[str, str]],
    check_write: Callable[[str], tuple[bool, str]],
) -> str:
    blocks = PATCH_BLOCK_RE.findall(patch_blocks_text)
    if not blocks:
        return (
            "ERROR: no valid SEARCH/REPLACE blocks found in patch_blocks.\n"
            "Use this exact format:\n<<<<<<< SEARCH\n<original code>\n"
            "=======\n<new code>\n>>>>>>> REPLACE"
        )
    resolved, error = resolve_write_path(path)
    if error:
        return error
    allowed, reason = check_write(resolved)
    if not allowed:
        return reason
    target = Path(resolved).expanduser()
    if not target.exists():
        return f"ERROR: file does not exist: {path}"
    try:
        file_lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
    except Exception as exc:
        return f"ERROR: failed to read file: {exc}"
    applied = 0
    errors: list[str] = []
    for block_index, (search_text, replacement) in enumerate(blocks):
        if not search_text.strip():
            errors.append(f"Block {block_index + 1}: SEARCH block is empty; skipped.")
            continue
        match = find_search_in_file(file_lines, search_text)
        if match is None:
            preview = "\n".join(
                f"  {index + 1}: {line.rstrip()}"
                for index, line in enumerate(search_text.splitlines()[:5])
            )
            errors.append(
                f"Block {block_index + 1}: SEARCH content was not found in the file.\n"
                f"  --- Your SEARCH (first 5 lines) ---\n{preview}\n"
                "  --- Similarity diagnostics and file context ---\n"
                f"{best_match_context(file_lines, search_text)}\n"
                "  Fix: adjust SEARCH indentation, line endings, or content using the hints above, then retry."
            )
            continue
        start, end = match
        if replacement and not replacement.endswith("\n"):
            replacement += "\n"
        file_lines = file_lines[:start] + replacement.splitlines(keepends=True) + file_lines[end:]
        applied += 1
    if not applied and errors:
        return "ERROR: all SEARCH/REPLACE blocks failed:\n" + "\n".join(errors)
    try:
        target.write_text("".join(file_lines), encoding="utf-8")
    except Exception as exc:
        return f"ERROR: failed to write file: {exc}"
    result = [f"OK: applied {applied}/{len(blocks)} SEARCH/REPLACE blocks to {path}"]
    if errors:
        result.append(f"WARNING: {len(errors)} blocks failed:")
        result.extend(errors)
    return "\n".join(result)


__all__ = [
    "apply_patch_blocks",
    "best_match_context",
    "diagnose_mismatch",
    "find_search_in_file",
    "line_similarity",
    "normalize_indent",
]
