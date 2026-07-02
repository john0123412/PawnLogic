"""
tools/file_ops.py - file reading, writing, listing, and search tools.

Patch support:
  - patch_file uses Aider-style SEARCH/REPLACE blocks.
  - Multiple blocks can be applied in one call with precise failure diagnostics.
  - Minor indentation drift is tolerated.
  - Legacy old_content/new_content arguments remain supported.
"""

import fnmatch, os, re, difflib, subprocess
from pathlib import Path
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
    OperationAction,
    audit_operation_decision,
    classify_shell_command,
    is_confirmation_available,
    prompt_for_confirmation,
)

# Current session cwd/workspace references.
_session_cwd = [os.getcwd()]
_session_workspace_dir = [WORKSPACE_DIR]


def sync_runtime_context(ctx) -> None:
    """Sync the active RuntimeContext into legacy file-tool pointers."""
    _session_cwd[0] = str(ctx.cwd)
    _session_workspace_dir[0] = str(ctx.workspace_dir)

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
    from core.state import state as _runtime_state
    if not _runtime_state.user_mode:
        return
    _run_shell_warning_emitted = True
    print(c(YELLOW, trust_notice_for_boundary(TrustBoundaryKind.HOST_SHELL)))

# ════════════════════════════════════════════════════════
# Security checks.
# ════════════════════════════════════════════════════════

def _read_block_reason(path, action: str) -> str:
    abs_p = str(Path(path).expanduser().resolve())
    for bl in READ_BLACKLIST:
        bl_p = str(Path(bl).expanduser().resolve())
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
        if _is_read_blacklisted(current_path):
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if not _is_read_blacklisted(current_path / d))
        for d in dirs:
            yield current_path / d
        for f in sorted(files):
            candidate = current_path / f
            if not _is_read_blacklisted(candidate):
                yield candidate

def _resolve_write_path(path: str) -> tuple:
    """Resolve writes into WORKSPACE_DIR.

    Returns (resolved_abs_path, error_msg). An empty error allows the write.
    """
    p = Path(path).expanduser()
    workspace_root = str(Path(WORKSPACE_DIR).expanduser().resolve())
    session_workspace = Path(_session_workspace_dir[0] or workspace_root).expanduser().resolve()
    session_workspace.mkdir(parents=True, exist_ok=True)

    # Absolute paths must stay inside the workspace.
    if p.is_absolute():
        abs_p = str(p.resolve())
        try:
            common = os.path.commonpath([abs_p, workspace_root])
        except ValueError:
            common = ""
        if common != workspace_root:
            return "", f"SECURITY BLOCK: '{path}' is outside the workspace. Write under {WORKSPACE_DIR}/."
        return abs_p, ""

    # Relative paths are redirected into the current session workspace.
    redirected = session_workspace / p
    redirected.parent.mkdir(parents=True, exist_ok=True)
    return str(redirected.resolve()), ""

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
    decision = classify_shell_command(
        cmd,
        cwd=work_dir,
        workspace_dir=_session_workspace_dir[0] or work_dir,
    )
    interactive = is_confirmation_available()

    if decision.action == OperationAction.ALLOW:
        audit_operation_decision(
            decision,
            operation_type=operation_type,
            cwd=work_dir,
            interactive=interactive,
        )
        return True, decision

    if decision.action == OperationAction.DENY:
        audit_operation_decision(
            decision,
            operation_type=operation_type,
            cwd=work_dir,
            interactive=interactive,
        )
        logger.warning(
            "[{}] operation policy denied command | risk={} rule={} cmd={!r}",
            operation_type,
            decision.risk.value,
            decision.matched_rule,
            decision.redacted_command,
        )
        return False, decision

    if not interactive:
        denied = decision.with_action(
            OperationAction.DENY,
            reason=(
                decision.reason
                + " Confirmation unavailable in non-interactive or --eval mode."
            ),
            matched_rule=f"confirmation_unavailable:{decision.matched_rule}",
        )
        audit_operation_decision(
            denied,
            operation_type=operation_type,
            cwd=work_dir,
            interactive=False,
        )
        logger.warning(
            "[{}] operation policy failed closed | risk={} rule={} cmd={!r}",
            operation_type,
            denied.risk.value,
            denied.matched_rule,
            denied.redacted_command,
        )
        return False, denied

    try:
        confirmed = prompt_for_confirmation(decision)
    except Exception:
        confirmed = False

    if not confirmed:
        denied = decision.with_action(
            OperationAction.DENY,
            reason=decision.reason + " User did not confirm the operation.",
            matched_rule=f"user_denied:{decision.matched_rule}",
        )
        audit_operation_decision(
            denied,
            operation_type=operation_type,
            cwd=work_dir,
            interactive=True,
        )
        return False, denied

    audit_operation_decision(
        decision,
        operation_type=operation_type,
        cwd=work_dir,
        interactive=True,
    )
    return True, decision


def _run(cmd: str, timeout: int = 15, cwd: str = None, env=None) -> str:
    """
    Low-level shell command runner.

    Blocking safeguards:
      - Operation policy classification before subprocess execution.
      - stdin=DEVNULL to avoid hanging interactive programs.
      - Timeout fail-fast behavior.
      - Cached HOST_IP/proxy environment injection.
      - Path hints when files are missing.
      - Timeout cleanup with partial output collection.
    """
    work_dir = cwd or _session_cwd[0]
    exec_env = env if env is not None else _get_shell_env()

    ok, policy_decision = _run_operation_policy(cmd, work_dir, operation_type="run_shell")
    if not ok:
        return _format_policy_block(policy_decision)

    logger.debug(
        "[run_shell] executing | risk={} rule={} cmd={!r} timeout={} cwd={}",
        policy_decision.risk.value,
        policy_decision.matched_rule,
        policy_decision.redacted_command,
        timeout,
        work_dir,
    )
    _emit_run_shell_warning()
    print(c(YELLOW, f"  ⚡ $ {cmd[:120]}"))

    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            cwd=work_dir,
            env=exec_env,
            start_new_session=True,
        )
        stdout, stderr = proc.communicate(timeout=timeout)
        out = stdout.decode("utf-8", errors="ignore") + stderr.decode("utf-8", errors="ignore")

        limit = runtime_config()["tool_max_chars"]
        if len(out) > limit:
            half = limit // 2
            out = out[:half] + f"\n...[{len(out)} chars total, truncated to {limit}]...\n" + out[-half // 4:]

        if proc.returncode != 0:
            logger.warning(
                f"[run_shell] command returned non-zero exit code {proc.returncode}: {cmd!r}\n"
                f"  stderr: {stderr[:300]!r}"
            )

        # Path hints for missing files.
        if out and "No such file or directory" in out:
            # Try to extract a likely filename from the command.
            _fname_match = re.search(r'(?:/|^)([a-zA-Z0-9_.\-]+)(?:\s|$)', cmd)
            _fname = _fname_match.group(1) if _fname_match else ""
            _suggestions = (
                "\n[Path Hint] File not found. Try:\n"
                f"  - find / -name '{_fname}' 2>/dev/null   # global search\n"
                "  - ls -la /proc/self/cwd                  # confirm current working directory\n"
                "  - readlink -f /proc/self/exe              # confirm binary location\n"
            ) if _fname else (
                "\n[Path Hint] File not found. Try:\n"
                "  - ls -la /proc/self/cwd                  # confirm current working directory\n"
                "  - find / -name '<filename>' 2>/dev/null   # global search\n"
            )
            out += _suggestions

        return out or "(no output)"

    except subprocess.TimeoutExpired:
        # Timeout cleanup: SIGTERM, wait, then SIGKILL while collecting partial output.
        _partial = ""
        if proc:
            try:
                # Try to collect anything already emitted.
                proc.terminate()
                try:
                    _stdout, _stderr = proc.communicate(timeout=3)
                    _partial = _stdout.decode("utf-8", errors="ignore")
                    if _stderr:
                        _partial += _stderr.decode("utf-8", errors="ignore")
                except subprocess.TimeoutExpired:
                    proc.kill()
                    _stdout, _stderr = proc.communicate()
                    _partial = _stdout.decode("utf-8", errors="ignore")
                    if _stderr:
                        _partial += _stderr.decode("utf-8", errors="ignore")
            except Exception:
                pass

        _partial_hint = ""
        if _partial.strip():
            _partial_hint = f"\n\n[Partial output received before timeout]:\n{_partial[:500]}"

        msg = (
            f"ERROR: command timed out (>{timeout}s); process terminated.{_partial_hint}\n\n"
            "Did you run an interactive program such as gdb, python, vim, or nc?\n"
            "  - For GDB, use -batch, e.g. gdb -batch -ex 'run' ./binary\n"
            "  - For interactive processes, use run_interactive with scripted inputs.\n"
            f"  - If the command legitimately takes longer, increase timeout (current: {timeout}s)."
        )
        logger.warning(f"[run_shell] timeout ({timeout}s): {cmd!r}")
        return msg

    except Exception as e:
        logger.error(f"[run_shell] execution error: {cmd!r} - {type(e).__name__}: {e}")
        return f"ERROR: {type(e).__name__}: {e}"

# ════════════════════════════════════════════════════════
# File reading tools.
# ════════════════════════════════════════════════════════

def tool_read_file(a: dict) -> str:
    ok, reason = _check_read(a["path"])
    if not ok: return reason
    try:
        p = Path(a["path"]).expanduser()
        if not p.exists(): return f"ERROR: file does not exist: {a['path']}"
        size = p.stat().st_size
        if size > 2_000_000:
            return (f"ERROR: file is too large ({size//1024}KB). "
                    "Use read_file_lines in chunks, or run_shell with head/grep/wc.")
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return f"ERROR: {e}"

def tool_read_file_lines(a: dict) -> str:
    ok, reason = _check_read(a["path"])
    if not ok: return reason
    try:
        p = Path(a["path"]).expanduser()
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

# Regex for SEARCH/REPLACE blocks.
_PATCH_BLOCK_RE = re.compile(
    r'<<<<<<+\s*SEARCH\s*\n'   # <<<<<<< SEARCH
    r'(.*?)'                    # SEARCH content
    r'=======+\s*\n'            # =======
    r'(.*?)'                    # REPLACE content
    r'>>>>>>>+\s*REPLACE',      # >>>>>>> REPLACE
    re.DOTALL
)


def _normalize_indent(text: str) -> str:
    """
    Remove shared leading indentation for indentation-tolerant comparison.
    Relative indentation levels are preserved.
    """
    lines = text.splitlines()
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return text
    min_indent = min(len(l) - len(l.lstrip()) for l in non_empty)
    return "\n".join(l[min_indent:] if len(l) >= min_indent else l for l in lines)


def _find_search_in_file(
    file_lines: list[str],
    search_text: str,
    indent_tolerance: int = 4,
) -> tuple[int, int] | None:
    """
    Find the line range matching search_text in file_lines.
    Returns (start_line_idx, end_line_idx_exclusive), or None.

    Matching strategy:
      1. Exact string match.
      2. Match ignoring trailing whitespace.
      3. Indentation-tolerant match.
    """
    file_text  = "".join(file_lines)
    search_stripped = search_text.rstrip("\n")

    # Strategy 1: exact match.
    if search_stripped in file_text:
        pos   = file_text.find(search_stripped)
        start = file_text[:pos].count("\n")
        end   = start + search_stripped.count("\n") + 1
        return start, end

    # Strategy 2: ignore trailing whitespace.
    search_lines = [l.rstrip() for l in search_stripped.splitlines()]
    file_rstripped = [l.rstrip() for l in file_lines]

    n = len(search_lines)
    for i in range(len(file_rstripped) - n + 1):
        if file_rstripped[i:i+n] == search_lines:
            return i, i + n

    # Strategy 3: indentation tolerance.
    search_norm = _normalize_indent(search_stripped).splitlines()
    for i in range(len(file_lines) - n + 1):
        window = "".join(file_lines[i:i+n])
        window_norm = _normalize_indent(window.rstrip("\n")).splitlines()
        if len(window_norm) == len(search_norm):
            if [l.rstrip() for l in window_norm] == [l.rstrip() for l in search_norm]:
                return i, i + n

    return None


def _line_similarity(a: str, b: str) -> float:
    """
    Return character-level line similarity (0.0-1.0) using difflib ratio.
    Empty-vs-nonempty lines return 0.0.
    """
    a, b = a.strip(), b.strip()
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _diagnose_mismatch(search_line: str, file_line: str, file_lineno: int) -> str:
    """
    Generate a short human-readable reason for a mismatched SEARCH/file line.
    Checks indentation, trailing whitespace, and CRLF/LF differences.
    """
    hints = []
    s_raw, f_raw = search_line, file_line

    # Indentation difference.
    s_indent = len(s_raw) - len(s_raw.lstrip())
    f_indent = len(f_raw) - len(f_raw.lstrip())
    if s_indent != f_indent:
        hints.append(
            f"indentation mismatch: your SEARCH has {s_indent} leading spaces, "
            f"file line {file_lineno} has {f_indent}"
        )

    # CRLF
    if s_raw.endswith("\r") or f_raw.endswith("\r"):
        hints.append("possible CRLF/LF line-ending mismatch")

    # Trailing whitespace.
    if s_raw.rstrip() != f_raw.rstrip() and s_raw.strip() == f_raw.strip():
        hints.append("trailing whitespace difference only")

    # General fallback.
    if not hints:
        hints.append("content differs — copy the exact file content into SEARCH")

    return "; ".join(hints)


def _best_match_context(
    file_lines: list[str],
    search_text: str,
    context_radius: int = 3,
) -> str:
    """
    Build a per-line similarity report when exact/fuzzy matching fails.

    Example output:
      Your SEARCH line 1 is 90% similar to file line 145.
        Hint: indentation mismatch (4 vs 0 spaces). Please fix.
      Your SEARCH line 2 is 100% similar to file line 146.
      ...
      --- File context around line 145 ---
         L143:     old_code()
      >>> L145:     def target_func(self):
         L146:         pass
    """
    search_lines = search_text.rstrip("\n").splitlines()
    if not search_lines:
        return "  (SEARCH block is empty; cannot locate content)"

    n_file = len(file_lines)
    if n_file == 0:
        return "  (file is empty)"

    n_search = len(search_lines)

    # Step 1: find the most similar file line for each SEARCH line.
    per_line_best: list[tuple[int, float]] = []  # (file_line_idx, score)
    for s_line in search_lines:
        best_idx   = 0
        best_score = -1.0
        for f_idx, f_line in enumerate(file_lines):
            score = _line_similarity(s_line, f_line)
            if score > best_score:
                best_score = score
                best_idx   = f_idx
        per_line_best.append((best_idx, best_score))

    # Step 2: emit per-line diagnostics.
    diag_lines = ["  [Per-line similarity report]"]
    for si, (s_line) in enumerate(search_lines):
        f_idx, score = per_line_best[si]
        pct = int(score * 100)
        file_lineno = f_idx + 1  # 1-indexed

        diag_lines.append(
            f"  Your SEARCH line {si+1} is {pct}% similar to file line {file_lineno}."
        )
        if score < 1.0:
            hint = _diagnose_mismatch(s_line, file_lines[f_idx], file_lineno)
            diag_lines.append(f"    Hint: {hint}.")

    # Step 3: show file context around the first line's best match.
    anchor_idx = per_line_best[0][0]
    s = max(0, anchor_idx - context_radius)
    e = min(n_file, anchor_idx + max(n_search, context_radius) + 1)

    diag_lines.append(f"\n  [File context around line {anchor_idx+1}]")
    for i in range(s, e):
        marker = ">>>" if i == anchor_idx else "   "
        diag_lines.append(f"  {marker} L{i+1:5d}: {file_lines[i].rstrip()}")

    return "\n".join(diag_lines)


def _apply_patch_blocks(path: str, patch_blocks_text: str) -> str:
    """
    Parse and apply SEARCH/REPLACE blocks in order.
    """
    blocks = _PATCH_BLOCK_RE.findall(patch_blocks_text)
    if not blocks:
        return (
            "ERROR: no valid SEARCH/REPLACE blocks found in patch_blocks.\n"
            "Use this exact format:\n"
            "<<<<<<< SEARCH\n<original code>\n=======\n<new code>\n>>>>>>> REPLACE"
        )

    resolved, err = _resolve_write_path(path)
    if err: return err
    ok, reason = _check_write(resolved)
    if not ok: return reason

    p = Path(resolved).expanduser()
    if not p.exists():
        return f"ERROR: file does not exist: {path}"

    try:
        original_text = p.read_text(encoding="utf-8")
    except Exception as e:
        return f"ERROR: failed to read file: {e}"

    file_lines = original_text.splitlines(keepends=True)
    applied    = 0
    errors     = []

    for block_idx, (search_raw, replace_raw) in enumerate(blocks):
        search_text  = search_raw
        replace_text = replace_raw

        if not search_text.strip():
            errors.append(f"Block {block_idx+1}: SEARCH block is empty; skipped.")
            continue

        result = _find_search_in_file(file_lines, search_text)
        if result is None:
            # Detailed failure: SEARCH preview plus per-line similarity diagnostics.
            search_preview = "\n".join(
                f"  {i+1}: {l.rstrip()}"
                for i, l in enumerate(search_text.splitlines()[:5])
            )
            file_context = _best_match_context(file_lines, search_text)
            errors.append(
                f"Block {block_idx+1}: SEARCH content was not found in the file.\n"
                f"  --- Your SEARCH (first 5 lines) ---\n{search_preview}\n"
                f"  --- Similarity diagnostics and file context ---\n{file_context}\n"
                f"  Fix: adjust SEARCH indentation, line endings, or content using the hints above, then retry."
            )
            continue

        start_idx, end_idx = result
        # Preserve line-oriented replacement behavior.
        if replace_text and not replace_text.endswith("\n"):
            replace_text += "\n"
        replace_lines = replace_text.splitlines(keepends=True)

        file_lines = file_lines[:start_idx] + replace_lines + file_lines[end_idx:]
        applied += 1

    if not applied and errors:
        return "ERROR: all SEARCH/REPLACE blocks failed:\n" + "\n".join(errors)

    try:
        p.write_text("".join(file_lines), encoding="utf-8")
    except Exception as e:
        return f"ERROR: failed to write file: {e}"

    result_lines = [f"OK: applied {applied}/{len(blocks)} SEARCH/REPLACE blocks to {path}"]
    if errors:
        result_lines.append(f"WARNING: {len(errors)} blocks failed:")
        result_lines.extend(errors)
    return "\n".join(result_lines)


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
        p = Path(a.get("path", ".")).expanduser()
        ok, reason = _check_directory_listing(p)
        if not ok:
            return reason
        if not p.exists(): return f"ERROR: path does not exist: {a.get('path','.')}"
        recursive = a.get("recursive", False)
        lines = []
        if recursive:
            for root, dirs, files in os.walk(p):
                root_path = Path(root)
                if _is_read_blacklisted(root_path):
                    dirs[:] = []
                    continue
                dirs[:] = sorted(d for d in dirs if not _is_read_blacklisted(root_path / d))
                files = sorted(f for f in files if not _is_read_blacklisted(root_path / f))
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
                if _is_read_blacklisted(e):
                    continue
                if e.is_dir(): lines.append(c(BLUE,  f"  📁 {e.name}/"))
                else:          lines.append(f"  📄 {e.name}  {c(GRAY, str(e.stat().st_size)+'B')}")
        return "\n".join(lines) or "(empty directory)"
    except Exception as e:
        return f"ERROR: {e}"

def tool_find_files(a: dict) -> str:
    pattern = a["pattern"]
    root    = Path(a.get("root", _session_cwd[0])).expanduser()
    max_r   = int(a.get("max_results", 50))
    results = []
    try:
        ok, reason = _check_directory_listing(root)
        if not ok:
            return reason
        pattern_path = pattern.replace("\\", "/").lstrip("/")
        if any(ch in pattern for ch in "*?["):
            matches = []
            for candidate in _iter_visible_paths(root):
                rel = str(candidate.relative_to(root)).replace(os.sep, "/")
                target = rel if "/" in pattern_path else candidate.name
                if fnmatch.fnmatch(target, pattern_path):
                    matches.append(candidate)
        else:
            matches = [p for p in _iter_visible_paths(root) if pattern.lower() in p.name.lower()]
        matches.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        for m in matches[:max_r]:
            rel = m.relative_to(root) if m.is_relative_to(root) else m
            tag = c(BLUE, "[DIR] ") if m.is_dir() else ""
            results.append(f"  {tag}{rel}  {c(GRAY, str(m.stat().st_size)+'B')}")
        if not results:
            return f"No files matched '{pattern}' under {root}"
        return c(GRAY, f"  Found {min(len(matches),max_r)} results under {root}:\n") + "\n".join(results)
    except Exception as e:
        return f"ERROR: {e}"

def tool_run_shell(a: dict) -> str:
    return _run(a["command"], int(a.get("timeout", 30)))


def tool_run_interactive(a: dict) -> str:
    """
    Run a stateful interactive process (nc, gdb, custom CLI) with a scripted
    input sequence. Solves the problem of nc/gdb hanging because stdin is never
    fed after launch.

    'inputs' is a list of strings. Special entry "SLEEP:N" pauses N seconds.
    Example:
        command = "nc target.ctf.site 1337"
        inputs  = ["1\n", "SLEEP:0.5", "2\n", "cat /flag\n"]

    Returns: all stdout/stderr collected during the interaction.
    """
    import threading, queue, time as _time

    command = a.get("command", "").strip()
    inputs  = a.get("inputs", [])          # list[str] — "SLEEP:N" for delays
    timeout = int(a.get("timeout", 30))
    cwd     = a.get("cwd") or _session_cwd[0]

    if not command:
        return "ERROR: 'command' parameter is required"
    ok, policy_decision = _run_operation_policy(
        command,
        cwd,
        operation_type="run_interactive",
    )
    if not ok:
        return _format_policy_block(policy_decision)

    print(c(YELLOW, f"  🔌 [interactive] $ {command[:100]}"))
    output_q: queue.Queue = queue.Queue()

    try:
        proc = subprocess.Popen(
            command, shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd, bufsize=0,
            env=_get_shell_env(),
        )
    except Exception as e:
        return f"ERROR: failed to start process: {e}"

    def _reader():
        """Background thread: pump stdout into queue."""
        try:
            while True:
                chunk = proc.stdout.read(512)
                if not chunk:
                    break
                output_q.put(chunk.decode("utf-8", errors="ignore"))
        except Exception:
            pass

    threading.Thread(target=_reader, daemon=True).start()

    def _drain(wait: float = 0.3) -> str:
        """Collect everything available after a short wait."""
        _time.sleep(wait)
        parts = []
        while not output_q.empty():
            try:    parts.append(output_q.get_nowait())
            except queue.Empty: break
        return "".join(parts)

    output_chunks: list[str] = []
    deadline = _time.time() + timeout
    try:
        # Collect initial banner / prompt
        output_chunks.append(_drain(0.6))

        for inp in inputs:
            if _time.time() > deadline:
                output_chunks.append("\n[TIMEOUT REACHED: Interactive script aborted]")
                break
            if isinstance(inp, str) and inp.upper().startswith("SLEEP:"):
                try:    _time.sleep(float(inp.split(":", 1)[1]))
                except Exception: pass
                output_chunks.append(_drain(0.1))
                continue

            data = inp.encode() if isinstance(inp, str) else inp
            print(c(GRAY, f"    → send: {repr(inp)[:60]}"))
            try:
                proc.stdin.write(data)
                proc.stdin.flush()
            except BrokenPipeError:
                output_chunks.append("[process closed stdin early]")
                break
            output_chunks.append(_drain(0.4))

        # Final drain + wait for graceful exit
        try:    proc.wait(timeout=2)
        except subprocess.TimeoutExpired: proc.terminate()
        output_chunks.append(_drain(0.3))

    except Exception as e:
        output_chunks.append(f"\n[ERROR during interaction: {e}]")
    finally:
        try: proc.terminate()
        except Exception: pass

    full  = "".join(output_chunks)
    limit = runtime_config()["tool_max_chars"]
    if len(full) > limit:
        full = full[:limit // 2] + "\n...[truncated]...\n" + full[-limit // 4:]
    return full or "(no output)"


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
