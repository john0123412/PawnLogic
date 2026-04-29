"""
tools/lsp_lite.py — LSP-lite: Semantic Code Indexing (1.0 新增)

无需完整语言服务器，提供：
  · find_symbol  — 跨工作区查找函数/类定义（Python 用 ast，其他语言用 grep）
  · find_refs    — 查找符号的所有引用/调用点
  · class_tree   — 提取 Python 类继承层级

设计原则：
  · Python 文件使用 ast.parse()，结果精确（带行号、类型标注）
  · 其他语言（C/C++/JS/Go/Rust）使用正则 grep，覆盖主流 def/class/fn 关键字
  · 结果数量限制（默认最多 25 条），防止大型工程刷爆 token
  · 零外部依赖：只用标准库 + subprocess(grep)
"""

import ast, os, re, subprocess
from pathlib import Path
from config import DYNAMIC_CONFIG
from utils.ansi import c, BLUE, GRAY, YELLOW

# ── 支持的文件扩展名 ──────────────────────────────────────
_PYTHON_EXTS = {".py"}
_GREP_EXTS   = {".c", ".cpp", ".cc", ".cxx", ".h", ".hpp",
                ".js", ".ts", ".jsx", ".tsx",
                ".go", ".rs", ".java", ".swift", ".kt",
                ".php", ".s", ".asm"}

# 各语言的定义关键字正则（用于 grep 搜索）
_LANG_DEF_PATTERNS = {
    ".c":    r"\b(void|int|char|double|float|struct|enum|typedef)\s+{sym}\s*[({]",
    ".cpp":  r"\b(class|struct|void|int|auto|template.*?)\s+{sym}\s*[(<{]",
    ".h":    r"\b(class|struct|void|int|typedef)\s+{sym}\b",
    ".js":   r"\b(function|class|const|let|var)\s+{sym}\b",
    ".ts":   r"\b(function|class|interface|const|let|var|async)\s+{sym}\b",
    ".go":   r"\bfunc\s+(\(\w+\s+\*?\w+\)\s+)?{sym}\s*\(",
    ".rs":   r"\b(fn|struct|enum|trait|impl)\s+{sym}\b",
    ".java": r"\b(class|interface|void|public|private|protected)\s+{sym}\s*[({]",
    ".php":  r"\b(function|class|interface|trait)\s+{sym}\b",
}
_DEFAULT_DEF_PATTERN = r"\b(def|function|fn|func|class|struct)\s+{sym}\b"

# ── 忽略目录 ──────────────────────────────────────────────
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".tox", "venv",
              ".venv", "dist", "build", ".cache", ".mypy_cache"}


# ════════════════════════════════════════════════════════
# AST helpers（Python only）
# ════════════════════════════════════════════════════════

def _ast_find_defs(symbol: str, filepath: str) -> list[dict]:
    """Parse one Python file and return all defs/classes matching symbol."""
    try:
        src  = Path(filepath).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=filepath)
    except Exception:
        return []
    results = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if symbol.lower() in node.name.lower():
                kind    = "class" if isinstance(node, ast.ClassDef) else "function"
                async_  = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
                results.append({
                    "file":  filepath,
                    "line":  node.lineno,
                    "kind":  kind,
                    "name":  node.name,
                    "extra": async_,
                })
    return results


def _ast_class_hierarchy(filepath: str) -> list[dict]:
    """Return class → bases list for all classes in a Python file."""
    try:
        src  = Path(filepath).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
    except Exception:
        return []
    results = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = []
            for b in node.bases:
                try:    bases.append(ast.unparse(b))
                except Exception: bases.append("<base>")
            results.append({
                "class": node.name,
                "bases": bases,
                "file":  filepath,
                "line":  node.lineno,
            })
    return results


# ════════════════════════════════════════════════════════
# Grep helpers（non-Python）
# ════════════════════════════════════════════════════════

def _grep_defs(symbol: str, filepath: str) -> list[dict]:
    """Grep a single non-Python file for definition patterns."""
    suffix  = Path(filepath).suffix.lower()
    pattern = _LANG_DEF_PATTERNS.get(suffix, _DEFAULT_DEF_PATTERN)
    regex   = pattern.format(sym=re.escape(symbol))
    try:
        res = subprocess.run(
            ["grep", "-nE", regex, filepath],
            capture_output=True, text=True, timeout=5,
        )
        results = []
        for line in res.stdout.splitlines():
            parts = line.split(":", 1)
            if len(parts) == 2:
                try:
                    lineno = int(parts[0])
                    results.append({"file": filepath, "line": lineno,
                                     "kind": "def", "name": symbol,
                                     "extra": parts[1].strip()[:60]})
                except ValueError:
                    pass
        return results
    except Exception:
        return []


def _grep_refs(symbol: str, root: str, max_results: int = 30) -> list[dict]:
    """grep -rn across the workspace for any occurrence of symbol."""
    include_args = []
    for ext in (_PYTHON_EXTS | _GREP_EXTS):
        include_args += [f"--include=*{ext}"]
    try:
        res = subprocess.run(
            ["grep", "-rn", "--color=never", "-w", symbol, root] + include_args,
            capture_output=True, text=True, timeout=12,
        )
        results = []
        for line in res.stdout.splitlines():
            parts = line.split(":", 2)
            if len(parts) >= 3:
                try:
                    results.append({
                        "file": parts[0],
                        "line": int(parts[1]),
                        "text": parts[2].strip()[:80],
                    })
                    if len(results) >= max_results:
                        break
                except ValueError:
                    pass
        return results
    except FileNotFoundError:
        return []   # grep not available
    except Exception:
        return []


# ════════════════════════════════════════════════════════
# Walk workspace
# ════════════════════════════════════════════════════════

def _walk_files(root: str):
    """Yield file paths, skipping ignored directories."""
    for dirpath, dirnames, filenames in os.walk(root):
        # prune skip dirs in-place
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            yield os.path.join(dirpath, fn)


# ════════════════════════════════════════════════════════
# Tool functions
# ════════════════════════════════════════════════════════

def tool_find_symbol(a: dict) -> str:
    """
    Semantic search: locate where a function or class is DEFINED.
    Python files use ast (accurate), others use grep with language-specific patterns.
    """
    symbol      = a.get("symbol", "").strip()
    root        = a.get("root", ".")
    max_results = int(a.get("max_results", 25))

    if not symbol:
        return "ERROR: 'symbol' parameter is required"

    print(c(BLUE, f"  🔍 [LSP-lite] find_symbol: '{symbol}'  root={root}"))

    results: list[dict] = []

    for filepath in _walk_files(root):
        if len(results) >= max_results:
            break
        suffix = Path(filepath).suffix.lower()
        if suffix in _PYTHON_EXTS:
            results.extend(_ast_find_defs(symbol, filepath))
        elif suffix in _GREP_EXTS:
            results.extend(_grep_defs(symbol, filepath))

    if not results:
        return (f"No definitions found for '{symbol}' in {root}\n"
                f"  Tip: try find_refs to locate usages even if the definition is in a library.")

    lines = [f"Found {len(results)} definition(s) for '{symbol}' (showing ≤ {max_results}):"]
    for r in results[:max_results]:
        extra = f"  [{r.get('extra', '')}]" if r.get("extra") else ""
        lines.append(
            f"  {r.get('kind', 'def'):10s}  {r['file']}:{r['line']}"
            f"  {r.get('name', symbol)}{extra}"
        )
    return "\n".join(lines)


def tool_find_refs(a: dict) -> str:
    """
    Find all USAGES/REFERENCES to a symbol across the workspace.
    Uses grep -w (whole word) for precision across all supported file types.
    """
    symbol      = a.get("symbol", "").strip()
    root        = a.get("root", ".")
    max_results = int(a.get("max_results", 30))

    if not symbol:
        return "ERROR: 'symbol' parameter is required"

    print(c(BLUE, f"  🔍 [LSP-lite] find_refs: '{symbol}'  root={root}"))

    results = _grep_refs(symbol, root, max_results)
    if not results:
        return (f"No references found for '{symbol}' in {root}\n"
                f"  Tip: check if 'grep' is installed (apt install grep).")

    lines = [f"Found {len(results)} reference(s) for '{symbol}':"]
    for r in results:
        rel = r["file"]
        try:
            rel = str(Path(r["file"]).relative_to(root))
        except ValueError:
            pass
        lines.append(f"  {rel}:{r['line']}  {r['text']}")
    return "\n".join(lines)


def tool_class_tree(a: dict) -> str:
    """
    Show the full Python class inheritance hierarchy for all .py files in root.
    Helps understand deep class chains in large codebases.
    """
    root = a.get("root", ".")
    print(c(BLUE, f"  🌳 [LSP-lite] class_tree  root={root}"))

    all_classes: list[dict] = []
    for filepath in _walk_files(root):
        if Path(filepath).suffix.lower() in _PYTHON_EXTS:
            all_classes.extend(_ast_class_hierarchy(filepath))

    if not all_classes:
        return f"No Python classes found in {root}"

    # Sort: classes with bases first, then alphabetically
    all_classes.sort(key=lambda x: (not x["bases"], x["class"]))

    lines = [f"Python class hierarchy ({len(all_classes)} classes found in {root}):"]
    for cls in all_classes[:60]:
        bases = " → ".join(cls["bases"]) if cls["bases"] else "object"
        try:
            rel = str(Path(cls["file"]).relative_to(root))
        except ValueError:
            rel = cls["file"]
        lines.append(
            f"  {cls['class']:35s}  extends [{bases}]"
            f"  ({rel}:{cls['line']})"
        )
    if len(all_classes) > 60:
        lines.append(f"  ... ({len(all_classes) - 60} more classes omitted)")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════
# Schema
# ════════════════════════════════════════════════════════

LSP_SCHEMAS = [
    {"type": "function", "function": {
        "name":        "find_symbol",
        "description": (
            "Semantic search: find where a function or class is DEFINED across the workspace.\n"
            "Smarter than grep — Python files use AST (accurate line numbers + type info).\n"
            "Use instead of repeated list_dir/find_files when looking for a specific function."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol":      {"type": "string",  "description": "Function or class name (or partial name)"},
                "root":        {"type": "string",  "description": "Root directory (default: cwd)"},
                "max_results": {"type": "integer", "description": "Max results to return (default 25)"},
            },
            "required": ["symbol"],
        },
    }},
    {"type": "function", "function": {
        "name":        "find_refs",
        "description": (
            "Find all USAGES/CALL SITES of a symbol across the workspace.\n"
            "Uses grep -w (whole-word match). Useful for impact analysis before refactoring."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol":      {"type": "string"},
                "root":        {"type": "string"},
                "max_results": {"type": "integer"},
            },
            "required": ["symbol"],
        },
    }},
    {"type": "function", "function": {
        "name":        "class_tree",
        "description": (
            "Show the Python class inheritance hierarchy for all .py files in a directory.\n"
            "Reveals class chains and base relationships at a glance."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "description": "Root directory (default: cwd)"},
            },
            "required": [],
        },
    }},
]
