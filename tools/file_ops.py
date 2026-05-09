"""
tools/file_ops.py — 文件读写、目录列出、文件搜索
1.1 新增（模块 3）：
  · patch_file 重构为 Aider 风格 SEARCH/REPLACE 块机制
  · 支持多块连续替换，提供精确的失败定位信息
  · 允许轻微缩进宽容度（indentation tolerance）
  · 向后兼容：仍接受旧式 old_content/new_content 参数
1.1 优化：
  · _best_match_context 现在输出逐行相似度百分比和原因提示
    例："Your SEARCH line 1 is 90% similar to file line 145. Please check indentation."
"""

import os, re, difflib, subprocess, signal, threading
from pathlib import Path
from config import DYNAMIC_CONFIG, READ_BLACKLIST, WRITE_BLACKLIST, DANGEROUS_PATTERNS
from utils.ansi import c, YELLOW, BLUE, GRAY, RED
from core.logger import logger

# ── 全局 cwd 引用 ─────────────────────────────────────────
_session_cwd = [os.getcwd()]

# ── 环境变量持久化缓存 ─────────────────────────────────────
_env_cache: dict = {}
_env_cache_initialized = False


def _init_env_cache():
    """首次 shell 调用时探测 HOST_IP 和代理状态，缓存到 _env_cache。"""
    global _env_cache_initialized, _env_cache
    if _env_cache_initialized:
        return
    _env_cache_initialized = True
    _env_cache = dict(os.environ)  # 继承当前进程环境

    # 探测 HOST_IP（容器/渗透场景常用）
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

    # 缓存代理设置
    for _proxy_key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        _val = os.environ.get(_proxy_key, "")
        if _val:
            _env_cache[_proxy_key] = _val

    logger.debug(f"[env_cache] initialized with {len(_env_cache)} vars")


def _get_shell_env() -> dict:
    """返回带缓存的环境变量字典。"""
    _init_env_cache()
    return _env_cache

# ════════════════════════════════════════════════════════
# 安全检查
# ════════════════════════════════════════════════════════

def _check_read(path: str):
    abs_p = str(Path(path).expanduser().resolve())
    for bl in READ_BLACKLIST:
        if abs_p.startswith(str(Path(bl).resolve())):
            return False, f"SECURITY BLOCK: '{path}' 含有敏感凭证，拒绝读取。"
    return True, ""

def _check_write(path: str):
    abs_p = str(Path(path).expanduser().resolve())
    for bl in WRITE_BLACKLIST:
        if abs_p.startswith(bl):
            return False, f"SECURITY BLOCK: '{path}' 是受保护系统路径，拒绝写入。"
    return True, ""

# ════════════════════════════════════════════════════════
# Shell 执行（文件工具内部用）
# ════════════════════════════════════════════════════════

def _run(cmd: str, timeout: int = 15, cwd: str = None, env=None) -> str:
    """
    执行 Shell 命令的底层实现。

    防阻塞加固（v1.2）：
      · stdin=DEVNULL  —— 切断键盘输入，防止交互式程序挂起（SIGTTIN）
      · timeout=15s    —— 默认超时熔断，防止大模型逻辑死锁
      · env 缓存       —— 自动注入 HOST_IP / proxy 等持久化环境变量
      · 路径自动建议   —— 文件未找到时提示 find / -name 和 /proc/self/cwd
      · 超时信号捕获   —— SIGTERM → 等待 → SIGKILL，收集已输出的部分内容
    """
    work_dir = cwd or _session_cwd[0]
    exec_env = env or _get_shell_env()   # ★ 使用持久化环境缓存

    # ── 安全检查 ────────────────────────────────────────────
    for pat in DANGEROUS_PATTERNS:
        if re.search(pat, cmd):
            logger.warning(f"[run_shell] SECURITY BLOCK: cmd={cmd!r}, pattern={pat!r}")
            return f"SECURITY BLOCK: 命令匹配危险模式 '{pat}'"

    logger.debug(f"[run_shell] 开始执行: {cmd!r}  (timeout={timeout}s, cwd={work_dir})")
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
            preexec_fn=os.setsid,   # 新进程组，便于超时时杀整棵树
        )
        stdout, stderr = proc.communicate(timeout=timeout)
        out = stdout.decode("utf-8", errors="ignore") + stderr.decode("utf-8", errors="ignore")

        limit = DYNAMIC_CONFIG["tool_max_chars"]
        if len(out) > limit:
            half = limit // 2
            out  = out[:half] + f"\n...[共{len(out)}字符，截断至{limit}]...\n" + out[-half // 4:]

        if proc.returncode != 0:
            logger.warning(
                f"[run_shell] 命令返回非零退出码 {proc.returncode}: {cmd!r}\n"
                f"  stderr: {stderr[:300]!r}"
            )

        # ── 路径自动建议（realpath 失败 / 文件未找到）──────
        if out and "No such file or directory" in out:
            # 从命令中提取可能的文件名
            _fname_match = re.search(r'(?:/|^)([a-zA-Z0-9_.\-]+)(?:\s|$)', cmd)
            _fname = _fname_match.group(1) if _fname_match else ""
            _suggestions = (
                "\n💡 [Path Hint] 文件未找到，建议尝试：\n"
                f"  · find / -name '{_fname}' 2>/dev/null   # 全局搜索\n"
                "  · ls -la /proc/self/cwd                  # 确认当前工作目录\n"
                "  · readlink -f /proc/self/exe              # 确认二进制位置\n"
            ) if _fname else (
                "\n💡 [Path Hint] 文件未找到，建议尝试：\n"
                "  · ls -la /proc/self/cwd                  # 确认当前工作目录\n"
                "  · find / -name '<filename>' 2>/dev/null   # 全局搜索\n"
            )
            out += _suggestions

        return out or "(no output)"

    except subprocess.TimeoutExpired:
        # ★ 超时熔断：SIGTERM → 等待 → SIGKILL，收集部分输出
        _partial = ""
        if proc:
            try:
                # 尝试收集已输出的部分内容
                proc.terminate()   # SIGTERM
                try:
                    _stdout, _stderr = proc.communicate(timeout=3)
                    _partial = _stdout.decode("utf-8", errors="ignore")
                    if _stderr:
                        _partial += _stderr.decode("utf-8", errors="ignore")
                except subprocess.TimeoutExpired:
                    proc.kill()    # SIGKILL
                    _stdout, _stderr = proc.communicate()
                    _partial = _stdout.decode("utf-8", errors="ignore")
                    if _stderr:
                        _partial += _stderr.decode("utf-8", errors="ignore")
            except Exception:
                pass

        _partial_hint = ""
        if _partial.strip():
            _partial_hint = f"\n\n[部分输出（超时前已接收）]:\n{_partial[:500]}"

        msg = (
            f"ERROR: 命令执行超时（>{timeout}s），进程已被终止。{_partial_hint}\n\n"
            "你是否运行了交互式程序（如 gdb、python、vim、nc）？\n"
            "  · 如果是 GDB，请务必加 -batch 参数，例如：gdb -batch -ex 'run' ./binary\n"
            "  · 如果需要与进程交互，请改用 run_interactive 工具并通过 inputs 传入脚本化输入。\n"
            f"  · 如果命令确实耗时，可增大 timeout（当前: {timeout}s）。"
        )
        logger.warning(f"[run_shell] 超时 ({timeout}s): {cmd!r}")
        return msg

    except Exception as e:
        logger.error(f"[run_shell] 执行异常: {cmd!r} — {type(e).__name__}: {e}")
        return f"ERROR: {type(e).__name__}: {e}"

    except Exception as e:
        logger.error(f"[run_shell] 执行异常: {cmd!r} — {type(e).__name__}: {e}")
        return f"ERROR: {e}"

# ════════════════════════════════════════════════════════
# 文件读取工具
# ════════════════════════════════════════════════════════

def tool_read_file(a: dict) -> str:
    ok, reason = _check_read(a["path"])
    if not ok: return reason
    try:
        p = Path(a["path"]).expanduser()
        if not p.exists(): return f"ERROR: 文件不存在: {a['path']}"
        size = p.stat().st_size
        if size > 2_000_000:
            return (f"ERROR: 文件过大 ({size//1024}KB)。"
                    "请用 read_file_lines 分段读取，或用 run_shell 配合 head/grep/wc。")
        return p.read_text(encoding="utf-8", errors="ignore")  # 编码清洗：丢弃非 UTF-8
    except Exception as e:
        return f"ERROR: {e}"

def tool_read_file_lines(a: dict) -> str:
    ok, reason = _check_read(a["path"])
    if not ok: return reason
    try:
        p = Path(a["path"]).expanduser()
        if not p.exists(): return f"ERROR: 文件不存在: {a['path']}"
        start = int(a["start_line"]) - 1
        end   = int(a["end_line"])
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()  # 编码清洗
        total = len(lines)
        chunk = lines[max(0, start):min(end, total)]
        header   = c(GRAY, f"  行 {start+1}–{min(end,total)} / {total}  ({p.name})\n")
        numbered = "\n".join(f"{c(GRAY, str(start+1+i).rjust(5))}  {ln}" for i, ln in enumerate(chunk))
        return header + numbered
    except Exception as e:
        return f"ERROR: {e}"

def tool_write_file(a: dict) -> str:
    ok, reason = _check_write(a["path"])
    if not ok: return reason
    try:
        p = Path(a["path"]).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(a["content"], encoding="utf-8")
        return f"OK: 已写入 {len(a['content'])} 字符 → {a['path']}"
    except Exception as e:
        return f"ERROR: {e}"

# ════════════════════════════════════════════════════════
# 模块 3：Aider 风格 patch_file（SEARCH/REPLACE 块机制）
#
# 两种调用模式（向后兼容）：
#
# 模式 A（新，推荐）：patch_blocks 参数
#   {
#     "path": "foo.py",
#     "patch_blocks": "<<<<<<< SEARCH\nold code\n=======\nnew code\n>>>>>>> REPLACE\n"
#   }
#
# 模式 B（旧，兼容）：old_content + new_content 参数
#   {
#     "path": "foo.py",
#     "old_content": "old",
#     "new_content": "new",
#     "fuzzy": true  (可选)
#   }
#
# SEARCH/REPLACE 格式规则：
#   <<<<<<< SEARCH
#   （需要替换的原始代码，可以是 2-5 行上下文，无需整个函数）
#   =======
#   （修改后的新代码）
#   >>>>>>> REPLACE
#
#   · 一个 patch_blocks 字符串可以包含多个 SEARCH/REPLACE 块（连续替换）
#   · SEARCH 内容允许轻微缩进差异（indentation tolerance = 4 空格以内）
#   · 若 SEARCH 找不到，返回详细错误（指出哪行没找到），不静默失败
# ════════════════════════════════════════════════════════

# 解析 SEARCH/REPLACE 块的正则
_PATCH_BLOCK_RE = re.compile(
    r'<<<<<<+\s*SEARCH\s*\n'   # <<<<<<< SEARCH
    r'(.*?)'                    # SEARCH 内容（捕获组 1）
    r'=======+\s*\n'            # =======
    r'(.*?)'                    # REPLACE 内容（捕获组 2）
    r'>>>>>>>+\s*REPLACE',      # >>>>>>> REPLACE
    re.DOTALL
)


def _normalize_indent(text: str) -> str:
    """
    去除每行行首公共缩进，用于缩进宽容度比较。
    保留相对缩进层级。
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
    在文件行列表中查找 search_text 对应的行范围。
    返回 (start_line_idx, end_line_idx_exclusive)，或 None。

    匹配策略（按优先级）：
      1. 精确字符串匹配（最快）
      2. 忽略行尾空白匹配
      3. 缩进宽容度匹配（允许 ±indent_tolerance 空格偏移）
    """
    file_text  = "".join(file_lines)
    search_stripped = search_text.rstrip("\n")

    # ── 策略 1：精确匹配 ─────────────────────────────────
    if search_stripped in file_text:
        pos   = file_text.find(search_stripped)
        start = file_text[:pos].count("\n")
        end   = start + search_stripped.count("\n") + 1
        return start, end

    # ── 策略 2：忽略行尾空白 ─────────────────────────────
    search_lines = [l.rstrip() for l in search_stripped.splitlines()]
    file_rstripped = [l.rstrip() for l in file_lines]

    n = len(search_lines)
    for i in range(len(file_rstripped) - n + 1):
        if file_rstripped[i:i+n] == search_lines:
            return i, i + n

    # ── 策略 3：缩进宽容度匹配 ───────────────────────────
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
    计算两行文本的字符级相似度（0.0-1.0），使用 difflib ratio。
    对空行返回 0.0。
    """
    a, b = a.strip(), b.strip()
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _diagnose_mismatch(search_line: str, file_line: str, file_lineno: int) -> str:
    """
    对一对不匹配的行（search vs file）生成人类可读的原因诊断：
    检查缩进差异 / 行尾差异 / CRLF vs LF 等常见问题。
    返回简短英文提示字符串。
    """
    hints = []
    s_raw, f_raw = search_line, file_line

    # 缩进差异
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

    # 行尾空白
    if s_raw.rstrip() != f_raw.rstrip() and s_raw.strip() == f_raw.strip():
        hints.append("trailing whitespace difference only")

    # 通用
    if not hints:
        hints.append("content differs — copy the exact file content into SEARCH")

    return "; ".join(hints)


def _best_match_context(
    file_lines: list[str],
    search_text: str,
    context_radius: int = 3,
) -> str:
    """
    当精确/模糊匹配均失败时，逐行对比 SEARCH 块与文件内容，
    找到每行最相近的文件行，并输出带相似度百分比的诊断报告。

    示例输出:
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
        return "  (SEARCH 块为空，无法定位)"

    n_file = len(file_lines)
    if n_file == 0:
        return "  (文件为空)"

    n_search = len(search_lines)

    # ── 步骤 1：为 SEARCH 每行找到文件中最相似的行 ───────
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

    # ── 步骤 2：输出逐行诊断 ──────────────────────────────
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

    # ── 步骤 3：以第一行最佳匹配为中心，输出文件上下文 ──
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
    解析并应用 SEARCH/REPLACE 块。
    支持一次传入多个块，按顺序依次应用。
    """
    blocks = _PATCH_BLOCK_RE.findall(patch_blocks_text)
    if not blocks:
        return (
            "ERROR: patch_blocks 中未找到有效的 SEARCH/REPLACE 块。\n"
            "请确保格式正确：\n"
            "<<<<<<< SEARCH\n<原始代码>\n=======\n<新代码>\n>>>>>>> REPLACE"
        )

    ok, reason = _check_write(path)
    if not ok: return reason

    p = Path(path).expanduser()
    if not p.exists():
        return f"ERROR: 文件不存在: {path}"

    try:
        original_text = p.read_text(encoding="utf-8")
    except Exception as e:
        return f"ERROR: 读取文件失败: {e}"

    file_lines = original_text.splitlines(keepends=True)
    applied    = 0
    errors     = []

    for block_idx, (search_raw, replace_raw) in enumerate(blocks):
        search_text  = search_raw
        replace_text = replace_raw

        if not search_text.strip():
            errors.append(f"Block {block_idx+1}: SEARCH 块为空，已跳过。")
            continue

        result = _find_search_in_file(file_lines, search_text)
        if result is None:
            # 生成详细错误：展示 SEARCH 前5行 + 逐行相似度诊断
            search_preview = "\n".join(
                f"  {i+1}: {l.rstrip()}"
                for i, l in enumerate(search_text.splitlines()[:5])
            )
            file_context = _best_match_context(file_lines, search_text)
            errors.append(
                f"Block {block_idx+1}: SEARCH 内容未在文件中找到。\n"
                f"  --- 你的 SEARCH（前5行）---\n{search_preview}\n"
                f"  --- 相似度诊断 & 文件上下文 ---\n{file_context}\n"
                f"  修复建议：根据上方 Hint 修正 SEARCH 块的缩进/换行/内容后重试。"
            )
            continue

        start_idx, end_idx = result
        # 处理 replace_text 末尾换行
        if replace_text and not replace_text.endswith("\n"):
            replace_text += "\n"
        replace_lines = replace_text.splitlines(keepends=True)

        file_lines = file_lines[:start_idx] + replace_lines + file_lines[end_idx:]
        applied += 1

    if not applied and errors:
        return "ERROR: 所有 SEARCH/REPLACE 块均失败：\n" + "\n".join(errors)

    try:
        p.write_text("".join(file_lines), encoding="utf-8")
    except Exception as e:
        return f"ERROR: 写入文件失败: {e}"

    result_lines = [f"OK: {applied}/{len(blocks)} 个 SEARCH/REPLACE 块已应用到 {path}"]
    if errors:
        result_lines.append(f"⚠ {len(errors)} 个块失败：")
        result_lines.extend(errors)
    return "\n".join(result_lines)


def tool_patch_file(a: dict) -> str:
    """
    Aider 风格 patch_file。

    模式 A（推荐）：使用 patch_blocks 参数（SEARCH/REPLACE 格式）
    模式 B（兼容）：使用 old_content + new_content 参数
    """
    path = a.get("path", "")
    if not path:
        return "ERROR: 缺少 'path' 参数"

    # ── 模式 A：SEARCH/REPLACE 块 ─────────────────────────
    patch_blocks = a.get("patch_blocks", "")
    if patch_blocks:
        return _apply_patch_blocks(path, patch_blocks)

    # ── 模式 B：向后兼容旧式 old_content/new_content ────────
    old = a.get("old_content", "")
    new = a.get("new_content", "")
    if not old:
        return (
            "ERROR: 缺少 patch_blocks 或 old_content 参数。\n"
            "推荐使用 patch_blocks（SEARCH/REPLACE 格式），\n"
            "或提供 old_content + new_content（旧式兼容模式）。"
        )

    ok, reason = _check_write(path)
    if not ok: return reason
    try:
        p    = Path(path).expanduser()
        text = p.read_text(encoding="utf-8")

        if old in text:
            p.write_text(text.replace(old, new, 1), encoding="utf-8")
            return f"OK: 精确 patch 已应用于 {path}"

        if a.get("fuzzy"):
            tl = text.splitlines(keepends=True)
            ol = old.splitlines(keepends=True)
            m  = difflib.SequenceMatcher(None, tl, ol, autojunk=False)
            b  = m.find_longest_match(0, len(tl), 0, len(ol))
            if b.size > 0 and b.size >= len(ol) * 0.7:
                patched = tl[:b.a] + [new] + tl[b.a + b.size:]
                p.write_text("".join(patched), encoding="utf-8")
                return f"OK: 模糊 patch ({b.size}/{len(ol)} 行) 已应用于 {path}"
            return f"ERROR: 模糊匹配太弱 ({b.size}/{len(ol)} 行)，请提供更精确的 old_content。"

        return (
            f"ERROR: old_content 未在 {path} 中找到。\n"
            "建议改用 patch_blocks（SEARCH/REPLACE 格式）以获得更好的容错性，\n"
            "或设置 fuzzy=true 启用模糊匹配。"
        )
    except Exception as e:
        return f"ERROR: {e}"

# ════════════════════════════════════════════════════════
# 其余文件工具（不变）
# ════════════════════════════════════════════════════════

def tool_list_dir(a: dict) -> str:
    try:
        p = Path(a.get("path", ".")).expanduser()
        if not p.exists(): return f"ERROR: 路径不存在: {a.get('path','.')}"
        recursive = a.get("recursive", False)
        lines = []
        if recursive:
            for root, dirs, files in os.walk(p):
                dirs.sort(); files.sort()
                level  = len(Path(root).relative_to(p).parts)
                indent = "  " * level
                rel    = Path(root).relative_to(p)
                if str(rel) != ".":
                    lines.append(c(BLUE, f"{indent}📁 {Path(root).name}/"))
                for f in files:
                    fp = Path(root) / f
                    lines.append(f"{'  '*(level+1)}📄 {f}  {c(GRAY, str(fp.stat().st_size)+'B')}")
                if len(lines) > 500:
                    lines.append(c(GRAY, "  ...[超过500条，已截断]")); break
        else:
            entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
            for e in entries[:200]:
                if e.is_dir(): lines.append(c(BLUE,  f"  📁 {e.name}/"))
                else:          lines.append(f"  📄 {e.name}  {c(GRAY, str(e.stat().st_size)+'B')}")
        return "\n".join(lines) or "(空目录)"
    except Exception as e:
        return f"ERROR: {e}"

def tool_find_files(a: dict) -> str:
    pattern = a["pattern"]
    root    = Path(a.get("root", _session_cwd[0])).expanduser()
    max_r   = int(a.get("max_results", 50))
    results = []
    try:
        if any(ch in pattern for ch in "*?["):
            matches = list(root.glob(("**/" + pattern.lstrip("/")) if "/" not in pattern else pattern))
        else:
            matches = [p for p in root.rglob("*") if pattern.lower() in p.name.lower()]
        matches.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        for m in matches[:max_r]:
            rel = m.relative_to(root) if m.is_relative_to(root) else m
            tag = c(BLUE, "[DIR] ") if m.is_dir() else ""
            results.append(f"  {tag}{rel}  {c(GRAY, str(m.stat().st_size)+'B')}")
        if not results:
            return f"未找到匹配 '{pattern}' 的文件（搜索范围: {root}）"
        return c(GRAY, f"  在 {root} 找到 {min(len(matches),max_r)} 个结果:\n") + "\n".join(results)
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
    for pat in DANGEROUS_PATTERNS:
        if re.search(pat, command):
            return f"SECURITY BLOCK: 危险命令模式 '{pat}'"

    print(c(YELLOW, f"  🔌 [interactive] $ {command[:100]}"))
    output_q: queue.Queue = queue.Queue()

    try:
        proc = subprocess.Popen(
            command, shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd, bufsize=0,
        )
    except Exception as e:
        return f"ERROR: 启动进程失败: {e}"

    def _reader():
        """Background thread: pump stdout into queue."""
        try:
            while True:
                chunk = proc.stdout.read(512)
                if not chunk:
                    break
                output_q.put(chunk.decode("utf-8", errors="ignore"))  # 编码清洗
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
    limit = DYNAMIC_CONFIG["tool_max_chars"]
    if len(full) > limit:
        full = full[:limit // 2] + "\n...[截断]...\n" + full[-limit // 4:]
    return full or "(no output)"


# ════════════════════════════════════════════════════════
# Schema
# ════════════════════════════════════════════════════════

FILE_SCHEMAS = [
    {"type":"function","function":{
        "name":"read_file",
        "description":"读取本地文件全文（< 2MB）。敏感目录已被阻止。",
        "parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},

    {"type":"function","function":{
        "name":"read_file_lines",
        "description":"按行范围读取大文件（1-indexed）。",
        "parameters":{"type":"object","properties":{
            "path":{"type":"string"},
            "start_line":{"type":"integer"},
            "end_line":{"type":"integer"}},
        "required":["path","start_line","end_line"]}}},

    {"type":"function","function":{
        "name":"write_file",
        "description":"创建新文件（不存在时使用）。对已有代码文件，请用 patch_file。",
        "parameters":{"type":"object","properties":{
            "path":{"type":"string"},"content":{"type":"string"}},
        "required":["path","content"]}}},

    {"type":"function","function":{
        "name":"patch_file",
        "description":(
            "修改已有文件（Aider SEARCH/REPLACE 格式，推荐）。\n\n"
            "使用 patch_blocks 参数，格式：\n"
            "<<<<<<< SEARCH\n"
            "[需要替换的原始代码行，2-5行足够定位即可]\n"
            "=======\n"
            "[修改后的新代码]\n"
            ">>>>>>> REPLACE\n\n"
            "特性：\n"
            "  · 允许轻微缩进差异（自动容错）\n"
            "  · 支持一次传入多个块连续修改\n"
            "  · 找不到时返回逐行相似度诊断（含行号、缩进/换行 Hint）\n"
            "  · 向后兼容 old_content/new_content 旧格式"
        ),
        "parameters":{"type":"object","properties":{
            "path":{"type":"string"},
            "patch_blocks":{"type":"string",
                "description":"SEARCH/REPLACE 格式的补丁块（推荐）"},
            "old_content":{"type":"string",
                "description":"旧格式兼容：精确要替换的字符串"},
            "new_content":{"type":"string",
                "description":"旧格式兼容：替换后的字符串"},
            "fuzzy":{"type":"boolean",
                "description":"旧格式兼容：启用模糊匹配"},
        },"required":["path"]}}},

    {"type":"function","function":{
        "name":"list_dir",
        "description":"列出目录内容。recursive=true 显示完整目录树。",
        "parameters":{"type":"object","properties":{
            "path":{"type":"string"},
            "recursive":{"type":"boolean"}},
        "required":[]}}},

    {"type":"function","function":{
        "name":"find_files",
        "description":"按 glob 模式或名称子串递归搜索文件。每次任务最多使用 1-2 次。",
        "parameters":{"type":"object","properties":{
            "pattern":{"type":"string","description":"如 '*.py', '**/*.c', 或名称子串"},
            "root":{"type":"string","description":"搜索起始目录（默认 cwd）"},
            "max_results":{"type":"integer"}},
        "required":["pattern"]}}},

    {"type":"function","function":{
        "name":"run_shell",
        "description":"在当前工作目录执行 shell 命令。git 操作请用 git_op。",
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
