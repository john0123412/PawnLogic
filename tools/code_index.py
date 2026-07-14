#!/usr/bin/env python3
"""Developer-only code index for PawnLogic source navigation.

The index is intentionally local and dependency-free. It scans Python source
with ``ast`` and writes JSON files under ``.pawnlogic_index/`` so agents can
locate symbols and references without repeatedly grepping large files.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


INDEX_VERSION = 1
INDEX_DIR_NAME = ".pawnlogic_index"
INDEX_FILE_NAME = "code_index.json"
META_FILE_NAME = "code_index.meta.json"

SCAN_DIRS = ("pawnlogic", "core", "config", "tools", "utils")
SCAN_FILES = ("main.py",)
SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pawnlogic_index",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "node_modules",
    "venv",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run_git_root(cwd: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=5,
        )
    except Exception:
        return None
    path = result.stdout.strip()
    return Path(path).resolve() if path else None


def project_root() -> Path:
    return _run_git_root(Path.cwd()) or Path.cwd().resolve()


def index_dir(root: Path) -> Path:
    return root / INDEX_DIR_NAME


def index_path(root: Path) -> Path:
    return index_dir(root) / INDEX_FILE_NAME


def meta_path(root: Path) -> Path:
    return index_dir(root) / META_FILE_NAME


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_skipped(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def iter_source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for dirname in SCAN_DIRS:
        base = root / dirname
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            rel_parts = path.relative_to(root).parts
            if not _is_skipped(Path(*rel_parts)):
                files.append(path)
    for filename in SCAN_FILES:
        path = root / filename
        if path.exists() and path.suffix == ".py":
            files.append(path)
    return sorted(set(files), key=lambda p: _rel(root, p))


def _first_doc_line(node: ast.AST) -> str:
    doc = ast.get_docstring(node) or ""
    return doc.strip().splitlines()[0].strip() if doc.strip() else ""


def _attribute_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _attribute_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return _attribute_name(node.func)
    return None


class PythonIndexer(ast.NodeVisitor):
    def __init__(self, rel_path: str, source_lines: list[str]) -> None:
        self.rel_path = rel_path
        self.source_lines = source_lines
        self.class_stack: list[str] = []
        self.symbols: list[dict[str, Any]] = []
        self.refs: list[dict[str, Any]] = []
        self._ref_seen: set[tuple[str, int, str]] = set()

    def _context(self, line: int) -> str:
        if 1 <= line <= len(self.source_lines):
            return self.source_lines[line - 1].strip()[:200]
        return ""

    def _add_symbol(self, node: ast.AST, name: str, kind: str) -> None:
        qualified = ".".join([*self.class_stack, name])
        symbol = {
            "name": name,
            "qualified_name": qualified,
            "kind": kind,
            "file": self.rel_path,
            "line": getattr(node, "lineno", 0),
            "end_line": getattr(node, "end_lineno", getattr(node, "lineno", 0)),
            "class": self.class_stack[-1] if self.class_stack else "",
            "doc": _first_doc_line(node),
        }
        self.symbols.append(symbol)

    def _add_ref(self, name: str, line: int) -> None:
        if not name or not line:
            return
        context = self._context(line)
        key = (name, line, context)
        if key in self._ref_seen:
            return
        self._ref_seen.add(key)
        self.refs.append({
            "name": name,
            "file": self.rel_path,
            "line": line,
            "context": context,
        })

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self._add_symbol(node, node.name, "class")
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        kind = "method" if self.class_stack else "function"
        self._add_symbol(node, node.name, kind)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        kind = "async_method" if self.class_stack else "async_function"
        self._add_symbol(node, node.name, kind)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> Any:
        self._add_ref(node.id, node.lineno)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        dotted = _attribute_name(node)
        if dotted:
            self._add_ref(dotted, node.lineno)
            self._add_ref(node.attr, node.lineno)
        self.generic_visit(node)


def parse_python_file(root: Path, path: Path) -> dict[str, Any]:
    rel_path = _rel(root, path)
    source = path.read_text(encoding="utf-8", errors="replace")
    lines = source.splitlines()
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError as exc:
        return {
            "sha256": _sha256(path),
            "symbols": [],
            "refs": [],
            "imports": [],
            "error": f"SyntaxError: {exc}",
        }

    indexer = PythonIndexer(rel_path, lines)
    indexer.visit(tree)
    return {
        "sha256": _sha256(path),
        "symbols": sorted(indexer.symbols, key=lambda item: (item["line"], item["name"])),
        "refs": sorted(indexer.refs, key=lambda item: (item["line"], item["name"])),
        "imports": extract_imports(tree),
        "error": "",
    }


def extract_imports(tree: ast.AST) -> list[dict[str, Any]]:
    imports: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.append({
                "module": "",
                "names": [alias.name for alias in node.names],
                "line": node.lineno,
            })
        elif isinstance(node, ast.ImportFrom):
            imports.append({
                "module": "." * node.level + (node.module or ""),
                "names": [alias.name for alias in node.names],
                "line": node.lineno,
            })
    return sorted(imports, key=lambda item: (item["line"], item["module"]))


def rebuild_lookup(index: dict[str, Any]) -> None:
    symbols: dict[str, list[dict[str, Any]]] = {}
    refs: dict[str, list[dict[str, Any]]] = {}
    for rel_path, data in sorted(index.get("files", {}).items()):
        for symbol in data.get("symbols", []):
            item = {k: v for k, v in symbol.items() if k != "doc" or v}
            item["file"] = rel_path
            symbols.setdefault(symbol["name"], []).append(item)
            qname = symbol.get("qualified_name")
            if qname and qname != symbol["name"]:
                symbols.setdefault(qname, []).append(item)
        for ref in data.get("refs", []):
            item = dict(ref)
            item["file"] = rel_path
            refs.setdefault(ref["name"], []).append(item)
    index["symbols"] = {key: sorted(value, key=lambda i: (i["file"], i["line"])) for key, value in sorted(symbols.items())}
    index["refs"] = {key: sorted(value, key=lambda i: (i["file"], i["line"])) for key, value in sorted(refs.items())}


def new_index(root: Path) -> dict[str, Any]:
    return {
        "version": INDEX_VERSION,
        "root": str(root),
        "generated_at": _now_iso(),
        "files": {},
        "symbols": {},
        "refs": {},
    }


def load_index(root: Path) -> dict[str, Any]:
    path = index_path(root)
    if not path.exists():
        raise SystemExit(f"Index not found: {path}\nRun: python tools/code_index.py build")
    return json.loads(path.read_text(encoding="utf-8"))


def write_index(root: Path, index: dict[str, Any]) -> None:
    out_dir = index_dir(root)
    out_dir.mkdir(parents=True, exist_ok=True)
    index["generated_at"] = _now_iso()
    index_path(root).write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    meta = {
        "version": INDEX_VERSION,
        "root": str(root),
        "generated_at": index["generated_at"],
        "file_count": len(index.get("files", {})),
        "symbol_count": sum(len(data.get("symbols", [])) for data in index.get("files", {}).values()),
        "ref_count": sum(len(data.get("refs", [])) for data in index.get("files", {}).values()),
        "files": {
            rel_path: data.get("sha256", "")
            for rel_path, data in sorted(index.get("files", {}).items())
        },
    }
    meta_path(root).write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def command_build(root: Path) -> int:
    index = new_index(root)
    for path in iter_source_files(root):
        index["files"][_rel(root, path)] = parse_python_file(root, path)
    rebuild_lookup(index)
    write_index(root, index)
    file_count = len(index["files"])
    symbol_count = sum(len(data["symbols"]) for data in index["files"].values())
    ref_count = sum(len(data["refs"]) for data in index["files"].values())
    print(f"Indexed {file_count} files, {symbol_count} symbols, {ref_count} refs.")
    print(f"Index written to {index_path(root).relative_to(root)}")
    return 0


def command_update(root: Path, file_arg: str) -> int:
    index = load_index(root)
    target = (root / file_arg).resolve()
    try:
        rel_path = _rel(root, target)
    except ValueError:
        raise SystemExit(f"Path is outside project root: {file_arg}") from None

    if not target.exists():
        removed = index.get("files", {}).pop(rel_path, None) is not None
        rebuild_lookup(index)
        write_index(root, index)
        print(f"Removed {rel_path} from index." if removed else f"{rel_path} was not indexed.")
        return 0

    if target.suffix != ".py":
        raise SystemExit(f"Only Python files can be indexed: {rel_path}")

    data = parse_python_file(root, target)
    index.setdefault("files", {})[rel_path] = data
    rebuild_lookup(index)
    write_index(root, index)
    print(f"Updated {rel_path}: {len(data['symbols'])} symbols, {len(data['refs'])} refs.")
    return 0


def _matching_symbol_entries(index: dict[str, Any], query: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()
    symbols = index.get("symbols", {})
    for item in symbols.get(query, []):
        key = (item["file"], item["line"], item.get("qualified_name", item["name"]))
        seen.add(key)
        matches.append(item)
    for name, entries in symbols.items():
        if name == query or not name.endswith(f".{query}"):
            continue
        for item in entries:
            key = (item["file"], item["line"], item.get("qualified_name", item["name"]))
            if key not in seen:
                seen.add(key)
                matches.append(item)
    return sorted(matches, key=lambda item: (item["file"], item["line"], item.get("qualified_name", "")))


def command_symbol(root: Path, query: str) -> int:
    index = load_index(root)
    matches = _matching_symbol_entries(index, query)
    if not matches:
        print(f"No symbols found for {query}")
        return 1

    print(query)
    for item in matches:
        end_line = item.get("end_line") or item["line"]
        location = f"{item['file']}:{item['line']}"
        if end_line and end_line != item["line"]:
            location += f"-{end_line}"
        qname = item.get("qualified_name", item["name"])
        print(f"  {location}  {item.get('kind', 'symbol')}  {qname}")
    return 0


def _matching_ref_entries(index: dict[str, Any], query: str) -> list[dict[str, Any]]:
    refs = index.get("refs", {})
    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str, str]] = set()
    candidate_names = [name for name in refs if name == query or name.endswith(f".{query}")]
    for name in sorted(candidate_names):
        for item in refs[name]:
            context = item.get("context", "")
            key = (item["file"], item["line"], name, context)
            if key in seen:
                continue
            seen.add(key)
            ref = dict(item)
            ref["matched_name"] = name
            matches.append(ref)
    return sorted(matches, key=lambda item: (item["file"], item["line"], item["matched_name"]))


def command_refs(root: Path, query: str) -> int:
    index = load_index(root)
    matches = _matching_ref_entries(index, query)
    if not matches:
        print(f"No references found for {query}")
        return 1

    print(f"References to {query}")
    for item in matches:
        suffix = "" if item["matched_name"] == query else f" [{item['matched_name']}]"
        print(f"  {item['file']}:{item['line']}  {item.get('context', '')}{suffix}")
    return 0


def command_check(root: Path) -> int:
    """Check index freshness against current source files."""
    meta_file = meta_path(root)
    if not meta_file.exists():
        print("No index metadata found. Run: python tools/code_index.py build")
        return 1
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    stored_files: dict[str, str] = meta.get("files", {})
    current_files = iter_source_files(root)
    current_rels = {_rel(root, p): p for p in current_files}

    stale: list[str] = []
    missing: list[str] = []
    new_files: list[str] = []

    for rel_path, stored_hash in sorted(stored_files.items()):
        if rel_path not in current_rels:
            missing.append(rel_path)
            continue
        current_hash = _sha256(current_rels[rel_path])
        if current_hash != stored_hash:
            stale.append(rel_path)

    for rel_path in sorted(current_rels):
        if rel_path not in stored_files:
            new_files.append(rel_path)

    if not stale and not missing and not new_files:
        print(f"Index is fresh ({len(stored_files)} files).")
        return 0

    if stale:
        print(f"Stale ({len(stale)} files changed):")
        for f in stale:
            print(f"  {f}")
    if missing:
        print(f"Deleted ({len(missing)} files):")
        for f in missing:
            print(f"  {f}")
    if new_files:
        print(f"New ({len(new_files)} files not indexed):")
        for f in new_files:
            print(f"  {f}")
    print("\nRun: python tools/code_index.py build")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and query PawnLogic's local developer code index.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("build", help="Scan project source and rebuild the local code index.")

    update = subparsers.add_parser("update", help="Incrementally update one Python file in the index.")
    update.add_argument("file")

    symbol = subparsers.add_parser("symbol", help="Find function, class, or method definitions.")
    symbol.add_argument("name")

    refs = subparsers.add_parser("refs", help="Find references to a function, class, method, or attribute.")
    refs.add_argument("name")

    subparsers.add_parser("check", help="Validate index freshness against current source files.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = project_root()
    if args.command == "build":
        return command_build(root)
    if args.command == "update":
        return command_update(root, args.file)
    if args.command == "symbol":
        return command_symbol(root, args.name)
    if args.command == "refs":
        return command_refs(root, args.name)
    if args.command == "check":
        return command_check(root)
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
