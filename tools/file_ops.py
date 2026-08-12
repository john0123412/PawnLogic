"""
tools/file_ops.py - file reading, writing, listing, and search tools.

Patch support:
  - patch_file uses Aider-style SEARCH/REPLACE blocks.
  - Multiple blocks can be applied in one call with precise failure diagnostics.
  - Minor indentation drift is tolerated.
  - Legacy old_content/new_content arguments remain supported.
"""

import fnmatch, os, difflib, subprocess, time
from pathlib import Path
from core.path_policy import resolve_within
from config import (
    READ_BLACKLIST,
    WRITE_BLACKLIST,
    WORKSPACE_DIR,
    scrub_sensitive_env,
)
from core.state import runtime_config
from core.trust import TrustBoundaryKind, trust_notice_for_boundary
from utils.ansi import c, YELLOW, BLUE, GRAY
from core.logger import logger
from core.operation_policy import (
    audit_operation_decision,
    classify_shell_command,
    is_confirmation_available,
    prompt_for_confirmation,
)
from tools.shell_ops import authorize_shell_operation
from tools.file_shell import run_interactive as _run_interactive_process
from tools.file_shell import run_shell as _run_shell_process
from tools.text_patch import apply_patch_blocks as _text_apply_patch_blocks

# Current session cwd/workspace references.
_session_cwd = [os.getcwd()]
_session_workspace_dir = [WORKSPACE_DIR]


def sync_runtime_context(ctx) -> None:
    """Sync the active RuntimeContext into legacy file-tool pointers."""
    if getattr(ctx, "isolated_workspace", False):
        return
    _session_cwd[0] = str(ctx.cwd)
    _session_workspace_dir[0] = str(ctx.workspace_dir)


def _active_runtime_context():
    """Return the scoped context without making file tools own runtime state."""
    try:
        from core.runtime_context import current_runtime_context

        return current_runtime_context()
    except Exception:
        return None


def _path_is_within(root: Path, candidate: Path) -> bool:
    """Return whether a resolved candidate is contained by a resolved root."""
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _context_cwd() -> Path:
    """Return the active context cwd or the legacy session cwd fallback."""
    context = _active_runtime_context()
    cwd = context.cwd if context is not None else _session_cwd[0]
    return Path(cwd).expanduser().resolve()


def _context_workspace_dir() -> Path:
    """Return the active context workspace or the legacy workspace fallback."""
    context = _active_runtime_context()
    workspace = (
        context.workspace_dir
        if context is not None
        else _session_workspace_dir[0] or WORKSPACE_DIR
    )
    return Path(workspace).expanduser().resolve()


def _is_other_isolated_child_path(path: Path) -> bool:
    """Return whether a path enters a sibling child workspace namespace."""
    context = _active_runtime_context()
    if context is None or not context.isolated_workspace:
        return False
    child_workspace = _context_workspace_dir()
    candidate = path.expanduser().resolve()
    return _path_is_within(child_workspace.parent, candidate) and not _path_is_within(
        child_workspace, candidate
    )


def _resolve_read_path(path: str | Path) -> tuple[Path | None, str]:
    """Resolve one read/list/search path against the active context cwd.

    Relative reads resolve inside the child workspace.  Absolute source paths
    remain readable, but sibling workspaces under the task namespace do not.
    """
    context = _active_runtime_context()
    candidate = Path(path).expanduser()
    resolved = (
        candidate.resolve()
        if candidate.is_absolute()
        else (_context_cwd() / candidate).resolve()
    )
    if context is not None and context.isolated_workspace:
        if _is_other_isolated_child_path(resolved):
            return None, (
                f"SECURITY BLOCK: '{path}' belongs to another isolated child workspace."
            )
    return resolved, ""


def _resolve_shell_cwd(cwd: str | None = None) -> tuple[str, str]:
    """Resolve shell cwd from the active context with child containment."""
    context = _active_runtime_context()
    if context is not None and context.isolated_workspace:
        workspace = _context_workspace_dir()
        if not cwd:
            return str(workspace), ""
        try:
            return str(resolve_within(workspace, Path(cwd).expanduser())), ""
        except ValueError:
            return "", (
                f"SECURITY BLOCK: shell cwd '{cwd}' is outside the isolated child workspace."
            )

    base = _context_cwd()
    if not cwd:
        return str(base), ""
    candidate = Path(cwd).expanduser()
    resolved = (
        candidate.resolve()
        if candidate.is_absolute()
        else (base / candidate).resolve()
    )
    return str(resolved), ""

# Persistent environment cache for shell tools.
_env_cache: dict = {}
_env_cache_initialized = False
_run_shell_warning_emitted = False


def _init_env_cache():
    """Initialize cached shell environment on first use."""
    global _env_cache_initialized, _env_cache
    if _env_cache_initialized:
        return
    _env_cache_initialized = True
    _env_cache = scrub_sensitive_env(os.environ)

    # Detect HOST_IP for container and security-lab workflows.
    try:
        _ip_res = subprocess.run(
            ["hostname", "-I"], capture_output=True, text=True,
            timeout=3, errors="ignore",
        )
        _ip = _ip_res.stdout.strip().split()[0] if _ip_res.stdout.strip() else ""
        if _ip:
            _env_cache["HOST_IP"] = _ip
            logger.debug(f"[env_cache] HOST_IP detected: {_ip}")
    except Exception:
        pass

    # Preserve proxy settings.
    for _proxy_key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        _val = os.environ.get(_proxy_key, "")
        if _val:
            _env_cache[_proxy_key] = _val

    logger.debug(f"[env_cache] initialized with {len(_env_cache)} vars")


def _get_shell_env() -> dict:
    """Return the cached shell environment."""
    _init_env_cache()
    return _env_cache


def _emit_run_shell_warning() -> None:
    global _run_shell_warning_emitted
    if _run_shell_warning_emitted:
        return
    context = _active_runtime_context()
    if context is not None:
        user_mode = context.user_mode
    else:
        from core.state import state as _runtime_state

        user_mode = _runtime_state.user_mode
    if not user_mode:
        return
    _run_shell_warning_emitted = True
    print(c(YELLOW, trust_notice_for_boundary(TrustBoundaryKind.HOST_SHELL)))

# ════════════════════════════════════════════════════════
# Security checks.
# ════════════════════════════════════════════════════════

# Resolve blacklist paths once per READ_BLACKLIST identity. On WSL2, resolving
# a symlink to a Windows mount (e.g. ~/.aws -> /mnt/c/Users/...) costs ~18ms
# per call. Without caching, _read_block_reason re-resolves all entries for
# every file candidate, turning a 34k-file walk into a 60+ minute hang.
_resolved_blacklist_cache: tuple[tuple[str, ...], tuple[str, ...]] | None = None


def _resolved_blacklist() -> tuple[str, ...]:
    global _resolved_blacklist_cache
    bl_id = id(READ_BLACKLIST)
    if _resolved_blacklist_cache is not None and _resolved_blacklist_cache[0] == (bl_id,):
        return _resolved_blacklist_cache[1]
    resolved = tuple(str(Path(bl).expanduser().resolve()) for bl in READ_BLACKLIST)
    _resolved_blacklist_cache = ((bl_id,), resolved)
    return resolved


def _read_block_reason(path, action: str) -> str:
    abs_p = str(Path(path).expanduser().resolve())
    for bl_p in _resolved_blacklist():
        try:
            is_blocked = os.path.commonpath([abs_p, bl_p]) == bl_p
        except ValueError:
            is_blocked = False
        if is_blocked:
            return f"SECURITY BLOCK: '{path}' may contain sensitive credentials; {action}."
    return ""


def _check_read(path: str):
    reason = _read_block_reason(path, "read denied")
    if reason:
        return False, reason
    return True, ""


def _check_directory_listing(path: Path) -> tuple[bool, str]:
    reason = _read_block_reason(path, "directory enumeration denied")
    if reason:
        return False, reason
    return True, ""


def _is_read_blacklisted(path: Path) -> bool:
    return bool(_read_block_reason(path, "read denied"))


def _iter_visible_paths(root: Path):
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        if _is_read_blacklisted(current_path) or _is_other_isolated_child_path(
            current_path
        ):
            dirs[:] = []
            continue
        dirs[:] = sorted(
            d
            for d in dirs
            if not _is_read_blacklisted(current_path / d)
            and not _is_other_isolated_child_path(current_path / d)
        )
        for d in dirs:
            yield current_path / d
        for f in sorted(files):
            candidate = current_path / f
            if not _is_read_blacklisted(candidate) and not _is_other_isolated_child_path(
                candidate
            ):
                yield candidate

def _resolve_write_path(path: str) -> tuple:
    """Resolve writes into WORKSPACE_DIR.

    Returns (resolved_abs_path, error_msg). An empty error allows the write.

    This function never creates directories; callers must create the parent
    directory only after validation succeeds.
    """
    p = Path(path).expanduser()
    context = _active_runtime_context()
    workspace_root = Path(WORKSPACE_DIR).expanduser().resolve()
    session_workspace = _context_workspace_dir()

    if context is not None and context.isolated_workspace:
        try:
            resolved = resolve_within(session_workspace, p)
        except ValueError:
            return "", (
                f"SECURITY BLOCK: '{path}' is outside the isolated child workspace."
            )
        return str(resolved), ""

    # Absolute paths must stay inside the workspace root.
    if p.is_absolute():
        try:
            resolved = resolve_within(workspace_root, p)
        except ValueError:
            return "", f"SECURITY BLOCK: '{path}' is outside the workspace. Write under {WORKSPACE_DIR}/."
        return str(resolved), ""

    # Relative paths are redirected into the current session workspace.
    try:
        resolved = resolve_within(session_workspace, p)
    except ValueError:
        return "", f"SECURITY BLOCK: '{path}' escapes the session workspace."
    return str(resolved), ""

def _check_write(path: str):
    abs_p = str(Path(path).expanduser().resolve())
    for bl in WRITE_BLACKLIST:
        bl_p = str(Path(bl).expanduser().resolve())
        try:
            is_blocked = os.path.commonpath([abs_p, bl_p]) == bl_p
        except ValueError:
            is_blocked = False
        if is_blocked:
            return False, f"SECURITY BLOCK: '{path}' is a protected system path; write denied."
    return True, ""

# ════════════════════════════════════════════════════════
# Shell execution used by file tools.
# ════════════════════════════════════════════════════════

def _format_policy_block(decision) -> str:
    return (
        "SECURITY BLOCK: host shell operation denied by operation policy.\n"
        f"Risk: {decision.risk.value}\n"
        f"Reason: {decision.reason}\n"
        f"Rule: {decision.matched_rule}\n"
        f"Command: {decision.redacted_command}"
    )


def _run_operation_policy(cmd: str, work_dir: str, *, operation_type: str):
    return authorize_shell_operation(
        cmd,
        work_dir,
        workspace_dir=str(_context_workspace_dir()),
        operation_type=operation_type,
        interactive=is_confirmation_available(),
        confirmer=prompt_for_confirmation,
        classifier=classify_shell_command,
        auditor=audit_operation_decision,
    )


def _run(cmd: str, timeout: int = 15, cwd: str | None = None, env=None) -> str:
    """Run a non-interactive command through the context-aware shell adapter."""
    work_dir, cwd_error = _resolve_shell_cwd(cwd)
    if cwd_error:
        return cwd_error
    return _run_shell_process(
        cmd,
        timeout=timeout,
        work_dir=work_dir,
        env=env if env is not None else _get_shell_env(),
        authorize=lambda command, directory: _run_operation_policy(
            command,
            directory,
            operation_type="run_shell",
        ),
        format_policy_block=_format_policy_block,
        logger=logger,
        emit_warning=_emit_run_shell_warning,
        announce=lambda command: print(c(YELLOW, f"  ⚡ $ {command[:120]}")),
        max_chars=lambda: runtime_config().get("tool_max_chars", 10_000),
        popen=subprocess.Popen,
        timeout_error=subprocess.TimeoutExpired,
    )

# ════════════════════════════════════════════════════════
# File reading tools.
# ════════════════════════════════════════════════════════

def tool_read_file(a: dict) -> str:
    p, path_error = _resolve_read_path(a["path"])
    if path_error:
        return path_error
    assert p is not None
    ok, reason = _check_read(str(p))
    if not ok: return reason
    try:
        if not p.exists(): return f"ERROR: file does not exist: {a['path']}"
        size = p.stat().st_size
        if size > 2_000_000:
            return (f"ERROR: file is too large ({size//1024}KB). "
                    "Use read_file_lines in chunks, or run_shell with head/grep/wc.")
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return f"ERROR: {e}"

def tool_read_file_lines(a: dict) -> str:
    p, path_error = _resolve_read_path(a["path"])
    if path_error:
        return path_error
    assert p is not None
    ok, reason = _check_read(str(p))
    if not ok: return reason
    try:
        if not p.exists(): return f"ERROR: file does not exist: {a['path']}"
        start = int(a["start_line"]) - 1
        end   = int(a["end_line"])
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        total = len(lines)
        chunk = lines[max(0, start):min(end, total)]
        header   = c(GRAY, f"  Lines {start+1}-{min(end,total)} / {total}  ({p.name})\n")
        numbered = "\n".join(f"{c(GRAY, str(start+1+i).rjust(5))}  {ln}" for i, ln in enumerate(chunk))
        return header + numbered
    except Exception as e:
        return f"ERROR: {e}"

def tool_write_file(a: dict) -> str:
    resolved, err = _resolve_write_path(a["path"])
    if err: return err
    ok, reason = _check_write(resolved)
    if not ok: return reason
    try:
        p = Path(resolved)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(a["content"], encoding="utf-8")
        return f"OK: wrote {len(a['content'])} chars -> {resolved}"
    except Exception as e:
        return f"ERROR: {e}"

# ════════════════════════════════════════════════════════
# Aider-style patch_file with SEARCH/REPLACE blocks.
#
# Two call modes are supported for backward compatibility:
#
# Mode A (recommended): patch_blocks
#   {
#     "path": "foo.py",
#     "patch_blocks": "<<<<<<< SEARCH\nold code\n=======\nnew code\n>>>>>>> REPLACE\n"
#   }
#
# Mode B (legacy): old_content + new_content
#   {
#     "path": "foo.py",
#     "old_content": "old",
#     "new_content": "new",
#     "fuzzy": true  (optional)
#   }
#
# SEARCH/REPLACE format:
#   <<<<<<< SEARCH
#   original lines to replace, usually 2-5 context lines are enough
#   =======
#   replacement lines
#   >>>>>>> REPLACE
#
#   - patch_blocks may contain multiple blocks applied in order.
#   - SEARCH allows minor indentation differences.
#   - Missing SEARCH content returns detailed diagnostics instead of failing silently.
# ════════════════════════════════════════════════════════

def _apply_patch_blocks(path: str, patch_blocks_text: str) -> str:
    """
    Parse and apply SEARCH/REPLACE blocks in order.
    """
    return _text_apply_patch_blocks(
        path,
        patch_blocks_text,
        resolve_write_path=_resolve_write_path,
        check_write=_check_write,
    )

def tool_patch_file(a: dict) -> str:
    """
    Aider-style patch_file.

    Mode A (recommended): patch_blocks in SEARCH/REPLACE format.
    Mode B (legacy): old_content + new_content.
    """
    path = a.get("path", "")
    if not path:
        return "ERROR: missing 'path' parameter"

    # Mode A: SEARCH/REPLACE blocks.
    patch_blocks = a.get("patch_blocks", "")
    if patch_blocks:
        return _apply_patch_blocks(path, patch_blocks)

    # Mode B: backward-compatible old_content/new_content.
    old = a.get("old_content", "")
    new = a.get("new_content", "")
    if not old:
        return (
            "ERROR: missing patch_blocks or old_content parameter.\n"
            "Recommended: use patch_blocks in SEARCH/REPLACE format,\n"
            "or provide old_content + new_content for legacy compatibility."
        )

    resolved, err = _resolve_write_path(path)
    if err: return err
    ok, reason = _check_write(resolved)
    if not ok: return reason
    try:
        p    = Path(resolved).expanduser()
        text = p.read_text(encoding="utf-8")

        if old in text:
            p.write_text(text.replace(old, new, 1), encoding="utf-8")
            return f"OK: exact patch applied to {resolved}"

        if a.get("fuzzy"):
            tl = text.splitlines(keepends=True)
            ol = old.splitlines(keepends=True)
            m  = difflib.SequenceMatcher(None, tl, ol, autojunk=False)
            b  = m.find_longest_match(0, len(tl), 0, len(ol))
            if b.size > 0 and b.size >= len(ol) * 0.7:
                patched = tl[:b.a] + [new] + tl[b.a + b.size:]
                p.write_text("".join(patched), encoding="utf-8")
                return f"OK: fuzzy patch ({b.size}/{len(ol)} lines) applied to {resolved}"
            return f"ERROR: fuzzy match too weak ({b.size}/{len(ol)} lines); provide more exact old_content."

        return (
            f"ERROR: old_content was not found in {resolved}.\n"
            "Use patch_blocks in SEARCH/REPLACE format for better diagnostics,\n"
            "or set fuzzy=true to enable fuzzy matching."
        )
    except Exception as e:
        return f"ERROR: {e}"

# ════════════════════════════════════════════════════════
# Remaining file tools.
# ════════════════════════════════════════════════════════

def tool_list_dir(a: dict) -> str:
    try:
        p, path_error = _resolve_read_path(a.get("path", "."))
        if path_error:
            return path_error
        assert p is not None
        ok, reason = _check_directory_listing(p)
        if not ok:
            return reason
        if not p.exists(): return f"ERROR: path does not exist: {a.get('path','.')}"
        recursive = a.get("recursive", False)
        lines = []
        if recursive:
            for root, dirs, files in os.walk(p):
                root_path = Path(root)
                if _is_read_blacklisted(root_path) or _is_other_isolated_child_path(
                    root_path
                ):
                    dirs[:] = []
                    continue
                dirs[:] = sorted(
                    d
                    for d in dirs
                    if not _is_read_blacklisted(root_path / d)
                    and not _is_other_isolated_child_path(root_path / d)
                )
                files = sorted(
                    f
                    for f in files
                    if not _is_read_blacklisted(root_path / f)
                    and not _is_other_isolated_child_path(root_path / f)
                )
                level  = len(Path(root).relative_to(p).parts)
                indent = "  " * level
                rel    = Path(root).relative_to(p)
                if str(rel) != ".":
                    lines.append(c(BLUE, f"{indent}📁 {Path(root).name}/"))
                for f in files:
                    fp = Path(root) / f
                    lines.append(f"{'  '*(level+1)}📄 {f}  {c(GRAY, str(fp.stat().st_size)+'B')}")
                if len(lines) > 500:
                    lines.append(c(GRAY, "  ...[more than 500 entries, truncated]")); break
        else:
            entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
            for e in entries[:200]:
                if _is_read_blacklisted(e) or _is_other_isolated_child_path(e):
                    continue
                if e.is_dir(): lines.append(c(BLUE,  f"  📁 {e.name}/"))
                else:          lines.append(f"  📄 {e.name}  {c(GRAY, str(e.stat().st_size)+'B')}")
        return "\n".join(lines) or "(empty directory)"
    except Exception as e:
        return f"ERROR: {e}"

def tool_find_files(a: dict) -> str:
    pattern = a["pattern"]
    root, path_error = _resolve_read_path(a.get("root", "."))
    if path_error:
        return path_error
    assert root is not None
    max_r   = int(a.get("max_results", 50))
    timeout = int(a.get("timeout", 10))  # seconds
    results = []
    try:
        ok, reason = _check_directory_listing(root)
        if not ok:
            return reason
        pattern_path = pattern.replace("\\", "/").lstrip("/")
        deadline = time.monotonic() + timeout
        matches = []
        timed_out = False
        paths = iter(_iter_visible_paths(root))
        while True:
            # This prevents starting another Python-level iteration after the
            # deadline. A single blocked iterator step cannot be interrupted.
            if time.monotonic() >= deadline:
                timed_out = True
                break
            try:
                candidate = next(paths)
            except StopIteration:
                timed_out = time.monotonic() >= deadline
                break
            if time.monotonic() >= deadline:
                timed_out = True
                break
            rel = str(candidate.relative_to(root)).replace(os.sep, "/")
            if any(ch in pattern for ch in "*?["):
                target = rel if "/" in pattern_path else candidate.name
                if fnmatch.fnmatch(target, pattern_path):
                    matches.append(candidate)
            else:
                if pattern.lower() in candidate.name.lower():
                    matches.append(candidate)
        matches.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        for m in matches[:max_r]:
            rel = m.relative_to(root) if m.is_relative_to(root) else m
            tag = c(BLUE, "[DIR] ") if m.is_dir() else ""
            results.append(f"  {tag}{rel}  {c(GRAY, str(m.stat().st_size)+'B')}")
        if not results:
            if timed_out:
                return (
                    f"Search timed out after {timeout}s before finding a match "
                    f"for '{pattern}' under {root}"
                )
            return f"No files matched '{pattern}' under {root}"
        header = f"  Found {min(len(matches),max_r)} results under {root}"
        if timed_out:
            header += f" (search timed out after {timeout}s; showing partial results)"
        return c(GRAY, header + ":\n") + "\n".join(results)
    except Exception as e:
        return f"ERROR: {e}"

def tool_run_shell(a: dict) -> str:
    return _run(a["command"], int(a.get("timeout", 30)), cwd=a.get("cwd"))


def tool_run_interactive(a: dict) -> str:
    """Run a scripted interactive command through the shell-process adapter."""
    command = a.get("command", "").strip()
    inputs = a.get("inputs", [])
    timeout = int(a.get("timeout", 30))
    cwd, cwd_error = _resolve_shell_cwd(a.get("cwd"))

    if not command:
        return "ERROR: 'command' parameter is required"
    if cwd_error:
        return cwd_error
    return _run_interactive_process(
        command,
        inputs,
        timeout=timeout,
        work_dir=cwd,
        authorize=lambda command, directory: _run_operation_policy(
            command,
            directory,
            operation_type="run_interactive",
        ),
        format_policy_block=_format_policy_block,
        get_shell_env=_get_shell_env,
        announce=lambda command: print(c(YELLOW, f"  🔌 [interactive] $ {command[:100]}")),
        announce_input=lambda item: print(c(GRAY, f"    → send: {repr(item)[:60]}")),
        max_chars=lambda: runtime_config().get("tool_max_chars", 10_000),
        popen=subprocess.Popen,
        timeout_error=subprocess.TimeoutExpired,
        sleep=time.sleep,
        clock=time.time,
    )


# ════════════════════════════════════════════════════════
# Schema
# ════════════════════════════════════════════════════════

FILE_SCHEMAS = [
    {"type":"function","function":{
        "name":"read_file",
        "description":"Read a local file in full (< 2 MB). Sensitive directories are blocked.",
        "parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},

    {"type":"function","function":{
        "name":"read_file_lines",
        "description":"Read a line range from a large file (1-indexed).",
        "parameters":{"type":"object","properties":{
            "path":{"type":"string"},
            "start_line":{"type":"integer"},
            "end_line":{"type":"integer"}},
        "required":["path","start_line","end_line"]}}},

    {"type":"function","function":{
        "name":"write_file",
        "description":"Create a new file. For existing code files, use patch_file.",
        "parameters":{"type":"object","properties":{
            "path":{"type":"string"},"content":{"type":"string"}},
        "required":["path","content"]}}},

    {"type":"function","function":{
        "name":"patch_file",
        "description":(
            "Modify an existing file with Aider-style SEARCH/REPLACE blocks (recommended).\n\n"
            "Use the patch_blocks parameter in this format:\n"
            "<<<<<<< SEARCH\n"
            "[original lines to replace; usually 2-5 context lines are enough]\n"
            "=======\n"
            "[new replacement lines]\n"
            ">>>>>>> REPLACE\n\n"
            "Features:\n"
            "  - Tolerates minor indentation drift.\n"
            "  - Supports multiple blocks in one call.\n"
            "  - Returns per-line similarity diagnostics when SEARCH is not found.\n"
            "  - Backward-compatible with old_content/new_content."
        ),
        "parameters":{"type":"object","properties":{
            "path":{"type":"string"},
            "patch_blocks":{"type":"string",
                "description":"Patch blocks in SEARCH/REPLACE format (recommended)."},
            "old_content":{"type":"string",
                "description":"Legacy compatibility: exact string to replace."},
            "new_content":{"type":"string",
                "description":"Legacy compatibility: replacement string."},
            "fuzzy":{"type":"boolean",
                "description":"Legacy compatibility: enable fuzzy matching."},
        },"required":["path"]}}},

    {"type":"function","function":{
        "name":"list_dir",
        "description":"List directory contents. Set recursive=true to show the full tree.",
        "parameters":{"type":"object","properties":{
            "path":{"type":"string"},
            "recursive":{"type":"boolean"}},
        "required":[]}}},

    {"type":"function","function":{
        "name":"find_files",
        "description":"Recursively search files by glob pattern or filename substring. Use at most 1-2 times per task.",
        "parameters":{"type":"object","properties":{
            "pattern":{"type":"string","description":"Examples: '*.py', '**/*.c', or a filename substring."},
            "root":{"type":"string","description":"Search root directory (default: cwd)."},
            "max_results":{"type":"integer"}},
        "required":["pattern"]}}},

    {"type":"function","function":{
        "name":"run_shell",
        "description":"Run a shell command in the current working directory. Use git_op for git operations.",
        "parameters":{"type":"object","properties":{
            "command":{"type":"string"},
            "cwd":{"type":"string"},
            "timeout":{"type":"integer"}},
        "required":["command"]}}},

    {"type":"function","function":{
        "name":"run_interactive",
        "description":(
            "Run a stateful interactive process (nc, gdb, custom CTF CLI) with scripted input.\n"
            "Use for: CTF netcat challenges, interactive exploits, any process needing piped input.\n"
            "Use 'SLEEP:N' in inputs list to wait N seconds between sends.\n"
            "Example inputs: [\"1\\n\", \"SLEEP:0.5\", \"cat /flag\\n\"]"
        ),
        "parameters":{"type":"object","properties":{
            "command": {"type":"string", "description":"Shell command, e.g. 'nc host 1337'"},
            "inputs":  {"type":"array", "items":{"type":"string"},
                        "description":"Ordered list of inputs to send. 'SLEEP:N' = wait N sec."},
            "timeout": {"type":"integer", "description":"Total timeout seconds (default 30)"},
            "cwd":     {"type":"string"}},
        "required":["command"]}}},
]
