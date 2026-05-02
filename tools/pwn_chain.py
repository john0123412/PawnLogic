"""
tools/pwn_chain.py — CTF / Pwn 工具链
  inspect_binary · pwn_rop · pwn_cyclic · pwn_disasm · pwn_libc · pwn_env
  pwn_debug (1.1 NEW) — GDB 批处理动态调试
  pwn_one_gadget (1.1 NEW) — one_gadget 一键 execve 跳板搜索
"""

import re, shutil, subprocess, tempfile, os
from collections import OrderedDict
from pathlib import Path
from config import DYNAMIC_CONFIG
from utils.ansi import c, YELLOW, MAGENTA, GRAY, GREEN, RED
from tools.file_ops import _run, _check_read, _session_cwd

# ── ELF 分析结果缓存（进程内，最多 10 条，按 (path, mtime) 键控） ──
_ELF_CACHE: OrderedDict[tuple, dict] = OrderedDict()
_ELF_CACHE_MAX = 10


def _cache_get(path: str, slot: str) -> str | None:
    """命中返回缓存字符串，未命中返回 None。"""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    key = (os.path.abspath(path), mtime)
    entry = _ELF_CACHE.get(key)
    if entry and slot in entry:
        _ELF_CACHE.move_to_end(key)   # LRU 刷新
        return entry[slot]
    return None


def _cache_set(path: str, slot: str, value: str) -> None:
    """写入缓存，超限时淘汰最旧条目。"""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return
    key = (os.path.abspath(path), mtime)
    if key not in _ELF_CACHE:
        _ELF_CACHE[key] = {}
        if len(_ELF_CACHE) > _ELF_CACHE_MAX:
            _ELF_CACHE.popitem(last=False)   # 淘汰最旧
    _ELF_CACHE[key][slot] = value
    _ELF_CACHE.move_to_end(key)

# ════════════════════════════════════════════════════════
# pwn_env — 环境完整性检测
# ════════════════════════════════════════════════════════

PWN_TOOLS = {
    "file":         ("file",        "基础格式识别",      "sudo apt install file"),
    "checksec":     ("checksec",    "安全机制检查",      "sudo apt install checksec"),
    "strings":      ("strings",     "字符串提取",        "sudo apt install binutils"),
    "objdump":      ("objdump",     "反汇编",            "sudo apt install binutils"),
    "readelf":      ("readelf",     "ELF 结构解析",      "sudo apt install binutils"),
    "xxd":          ("xxd",         "十六进制查看",      "sudo apt install xxd"),
    "gdb":          ("gdb",         "动态调试",          "sudo apt install gdb"),
    "ROPgadget":    ("ROPgadget",   "ROP 链搜索",        "pip3 install ROPgadget"),
    "ropper":       ("ropper",      "ROP 链搜索 (备)",   "pip3 install ropper"),
    "one_gadget":   ("one_gadget",  "execve 跳板搜索",   "gem install one_gadget"),
    "gcc":          ("gcc",         "C 编译器",          "sudo apt install gcc"),
    "gcc-multilib": (None,          "32bit 编译支持",    "sudo apt install gcc-multilib"),
    "g++":          ("g++",         "C++ 编译器",        "sudo apt install g++"),
    "python3":      ("python3",     "Python 3",          "sudo apt install python3"),
    "pwntools":     (None,          "Pwn Python 库",     "无需全局安装，仅在 run_code(use_venv=true) 沙箱中可用"),
    "patchelf":     ("patchelf",    "ELF 动态修改",      "sudo apt install patchelf"),
    "strace":       ("strace",      "系统调用追踪",      "sudo apt install strace"),
    "ltrace":       ("ltrace",      "库调用追踪",        "sudo apt install ltrace"),
    "r2":           ("r2",          "Radare2 逆向框架",  "sudo apt install radare2"),
    "node":         ("node",        "JavaScript",        "sudo apt install nodejs"),
}

def tool_pwn_env(a: dict) -> str:
    lines = []; missing = []; present = []
    for name, (cmd, desc, hint) in PWN_TOOLS.items():
        if cmd is None:
            if name == "gcc-multilib":
                r = subprocess.run(
                    "echo 'int main(){}' | gcc -m32 -x c - -o /dev/null 2>&1",
                    shell=True, capture_output=True, text=True, timeout=5
                )
                avail = r.returncode == 0
            elif name == "pwntools":
                r = subprocess.run(
                    ["python3", "-c", "import pwn; print(pwn.__version__)"],
                    capture_output=True, text=True, timeout=5
                )
                avail = r.returncode == 0
            else:
                avail = False
        else:
            avail = bool(shutil.which(cmd))
        status = c(GREEN, "✓") if avail else c(RED, "✗")
        lines.append(f"  {status} {name:18} {c(GRAY, desc)}")
        (present if avail else missing).append((name, hint))

    summary = [c(MAGENTA, "\n  === Pwn 环境检测 ==="), "\n".join(lines), ""]
    summary.append(c(GREEN, f"  已安装: {len(present)} / {len(PWN_TOOLS)}"))
    if missing:
        summary.append(c(RED, f"  缺失 ({len(missing)} 项):"))
        for name, hint in missing:
            summary.append(c(GRAY, f"    [{name}]  {hint}"))
    return "\n".join(summary)

# ════════════════════════════════════════════════════════
# inspect_binary
# ════════════════════════════════════════════════════════

_TEXT_EXTENSIONS = {".c", ".cpp", ".cc", ".cxx", ".py", ".md", ".txt",
                    ".js", ".ts", ".html", ".htm", ".sh", ".bash", ".rs",
                    ".go", ".java", ".rb", ".php", ".css", ".json", ".yaml",
                    ".yml", ".toml", ".ini", ".cfg"}

def tool_inspect_binary(a: dict) -> str:
    path = a["path"]; grep = a.get("strings_grep", "")
    ok, reason = _check_read(path)
    if not ok: return reason
    if not Path(path).expanduser().exists(): return f"ERROR: 不存在: {path}"

    # ── 🚨 物理拦截：严禁对文本源码文件使用二进制分析工具 ──────────
    _suffix = Path(path).suffix.lower()
    if _suffix in _TEXT_EXTENSIONS:
        return (
            f"🚨 [HARD BLOCK] inspect_binary 拒绝处理文本文件！\n"
            f"  文件: {path}  (检测到文本扩展名: '{_suffix}')\n\n"
            f"  ❌ 错误原因: inspect_binary 是二进制分析工具（file/checksec/hexdump/readelf），\n"
            f"     对源码文本文件执行这些命令毫无意义，属于严重的工具误用。\n\n"
            f"  ✅ 正确做法（根据你的实际需求选择）：\n"
            f"     · 阅读源码内容  → read_file(path='{path}')\n"
            f"     · 搜索函数/符号 → run_shell('grep -n <关键词> {path}')\n"
            f"     · 搜索全项目引用→ run_shell('grep -rn <关键词> .')\n"
            f"     · 查找相关文件  → find_files('<pattern>')\n\n"
            f"  📌 记住：inspect_binary 只能用于 ELF / PE / so / o 等真正的二进制文件！"
        )

    # ── 缓存命中 ──────────────────────────────────────────
    cache_slot = f"inspect:{grep}"
    cached = _cache_get(path, cache_slot)
    if cached is not None:
        return cached

    res = []
    res.append("=== file ===");            res.append(_run(f"file '{path}'").strip())
    cs = _run(f"checksec --file='{path}' 2>/dev/null || checksec '{path}' 2>/dev/null")
    if "not found" not in cs.lower() and cs.strip():
        res.append("\n=== checksec ===");  res.append(cs.strip())
    grep_pipe = f" | grep -i '{grep}'" if grep else " | head -60"
    res.append("\n=== strings ===");       res.append(_run(f"strings '{path}'{grep_pipe}").strip())
    res.append("\n=== hexdump (前128B) ==="); res.append(_run(f"xxd '{path}' | head -8").strip())
    res.append("\n=== readelf -S ===");    res.append(_run(f"readelf -S '{path}' 2>/dev/null | head -30").strip())
    res.append("\n=== ldd ===");           res.append(_run(f"ldd '{path}' 2>/dev/null").strip())
    result = "\n".join(res)
    _cache_set(path, cache_slot, result)
    return result

# ════════════════════════════════════════════════════════
# pwn_rop
# ════════════════════════════════════════════════════════

def tool_pwn_rop(a: dict) -> str:
    path = a["path"]; grep = a.get("grep",""); depth = int(a.get("depth",5))
    ok, reason = _check_read(path)
    if not ok: return reason

    # ── 缓存命中 ──────────────────────────────────────────
    cache_slot = f"rop:{grep}:{depth}"
    cached = _cache_get(path, cache_slot)
    if cached is not None:
        return cached

    if shutil.which("ROPgadget"):
        cmd = f"ROPgadget --binary '{path}' --depth {depth}"
        if grep: cmd += f" | grep -i '{grep}'"
    elif shutil.which("ropper"):
        cmd = f"ropper --file '{path}'"
        if grep: cmd += f" --search '{grep}'"
    else:
        return ("ROPgadget / ropper 均未安装。\n"
                "  pip3 install ROPgadget\n  pip3 install ropper")
    print(c(MAGENTA, f"  🔗 {cmd[:80]}"))
    result = _run(cmd, timeout=90)
    _cache_set(path, cache_slot, result)
    return result

# ════════════════════════════════════════════════════════
# pwn_cyclic — 内置 de Bruijn
# ════════════════════════════════════════════════════════

def tool_pwn_cyclic(a: dict) -> str:
    action   = a["action"]
    alphabet = b"abcdefghijklmnopqrstuvwxyz"; k = 4

    def _debruijn():
        arr = [0] * k * len(alphabet); seq = []
        def db(t, p):
            if t > k:
                if k % p == 0: seq.extend(arr[1:p+1])
            else:
                arr[t] = arr[t-p]; db(t+1, p)
                for j in range(arr[t-p]+1, len(alphabet)):
                    arr[t] = j; db(t+1, t)
        db(1,1)
        return bytes(alphabet[i] for i in seq)

    pat = _debruijn()

    def gen(n=200):
        out = b""
        while len(out) < n: out += pat
        return out[:n].decode("latin-1")

    def find(val_str):
        val_str = val_str.strip()
        try:
            raw = bytes.fromhex(val_str[2:]) if val_str.startswith("0x") else val_str.encode("latin-1")[:k]
        except Exception as e: return f"ERROR: {e}"
        big = b""
        while len(big) < 8192: big += pat
        for i in range(len(big)-k+1):
            if big[i:i+k] == raw:      return f"偏移 (小端): {i}  (hex: {raw.hex()})"
            if big[i:i+k] == raw[::-1]: return f"偏移 (大端): {i}"
        return f"'{val_str}' 未找到，请检查格式（0x61616161 或 aaab）。"

    if action == "gen":   return f"Cyclic ({a.get('length',200)} bytes):\n{gen(int(a.get('length',200)))}"
    if action == "find":
        val = a.get("value","")
        if not val: return "ERROR: find 需要 'value'"
        return find(val)
    return "ERROR: action = gen | find"

# ════════════════════════════════════════════════════════
# pwn_disasm
# ════════════════════════════════════════════════════════

def tool_pwn_disasm(a: dict) -> str:
    path = a["path"]; func = a.get("function",""); addr = a.get("address","")
    ok, reason = _check_read(path)
    if not ok: return reason
    if func:
        nm  = _run(f"nm '{path}' 2>/dev/null | grep -w '{func}'", timeout=10)
        asm = _run(f"objdump -d -M intel '{path}' | awk '/^[0-9a-f]+ <{func}>:/,/^$/'", timeout=30)
        return f"=== nm ===\n{nm.strip()}\n\n=== disasm ===\n{asm}"
    if addr:
        pts = addr.split(":")
        cmd = (f"objdump -d -M intel --start-address={pts[0]} --stop-address={pts[1]} '{path}'"
               if len(pts)==2 else
               f"objdump -d -M intel --start-address={addr} '{path}' | head -50")
        return _run(cmd, timeout=30)
    return _run(f"objdump -d -M intel '{path}' | grep -E '^[0-9a-f]+ <' | head -60", timeout=30)

# ════════════════════════════════════════════════════════
# pwn_libc
# ════════════════════════════════════════════════════════

def tool_pwn_libc(a: dict) -> str:
    path = a["path"]; action = a["action"]
    ok, reason = _check_read(path)
    if not ok: return reason
    if action == "detect":
        ver = _run(f"strings '{path}' | grep -iE 'glibc|ubuntu|libc[-_]' | head -10", timeout=15)
        bid = _run(f"readelf -n '{path}' 2>/dev/null | grep 'Build ID' | head -3", timeout=10)
        ldd = _run(f"ldd '{path}' 2>/dev/null", timeout=10)
        return f"=== version strings ===\n{ver.strip()}\n\n=== Build ID ===\n{bid.strip()}\n\n=== ldd ===\n{ldd.strip()}"
    if action == "symbols":
        key = ["system","execve","printf","puts","gets","read","write",
               "__libc_start_main","__stack_chk_fail","exit","mprotect","mmap"]
        re_out = _run(f"readelf -s '{path}' 2>/dev/null | grep -E '({'|'.join(key)})'", timeout=15)
        nm_out = _run(f"nm -D '{path}' 2>/dev/null | head -30", timeout=10)
        return f"=== readelf symbols ===\n{re_out}\n\n=== nm -D ===\n{nm_out.strip()}"
    return "ERROR: action = detect | symbols"

# ════════════════════════════════════════════════════════
# pwn_debug — GDB 批处理动态调试（1.9.0 NEW）
# ════════════════════════════════════════════════════════

def tool_pwn_debug(a: dict) -> str:
    """
    用 GDB -batch 模式动态调试二进制。
    参数：
      path        — 目标程序路径（必须）
      breakpoints — 断点地址列表，如 ["0x40068e", "main"]（可选）
      input_data  — 直接传给 stdin 的字节串，如 "AAAA...\\x00"（可选）
      input_file  — stdin 重定向文件路径（与 input_data 二选一）
      commands    — 断点触发后执行的 GDB 命令列表（可选）
                    默认: ["info registers", "x/20wx $rsp", "backtrace"]
      timeout     — 超时秒数（默认30）
      use_pwndbg  — True 时尝试用 pwndbg 扩展（若已安装）
    """
    path        = a["path"]
    breakpoints = a.get("breakpoints", [])
    input_data  = a.get("input_data", "")
    input_file  = a.get("input_file", "")
    commands    = a.get("commands", ["info registers", "x/20wx $rsp", "backtrace 5"])
    timeout     = int(a.get("timeout", 30))
    use_pwndbg  = bool(a.get("use_pwndbg", False))
    interactive_mode = bool(a.get("interactive_mode", False))

    ok, reason = _check_read(path)
    if not ok: return reason
    if not Path(path).expanduser().exists():
        return f"ERROR: 文件不存在: {path}"
    if not shutil.which("gdb"):
        return "ERROR: gdb 未安装。\n  sudo apt install gdb"

    # ── 交互式模式：委托给 tool_run_interactive ────────────
    if interactive_mode:
        from tools.file_ops import tool_run_interactive
        bp_cmds = []
        for bp in breakpoints:
            bp_cmds.append(f"b *{bp}\n" if (bp.startswith("0x") or bp.isdigit()) else f"b {bp}\n")
        gdb_inputs = bp_cmds + [f"{cmd}\n" for cmd in commands] + ["quit\n"]
        if a.get("inputs"):
            gdb_inputs = list(a["inputs"]) + gdb_inputs
        gdb_cmd = f"gdb -q '{path}'"
        print(c(MAGENTA, f"  🐛 [interactive] {gdb_cmd}"))
        return tool_run_interactive({
            "command": gdb_cmd,
            "inputs":  gdb_inputs,
            "timeout": timeout,
        })

    # ── 构建 GDB 脚本 ──────────────────────────────────
    script_lines = ["set pagination off", "set confirm off"]

    # pwndbg 支持
    if use_pwndbg:
        pwndbg_init = os.path.expanduser("~/.gdbinit.pwndbg")
        gdbinit     = os.path.expanduser("~/.gdbinit")
        if os.path.exists(pwndbg_init):
            script_lines.insert(0, f"source {pwndbg_init}")
        elif os.path.exists(gdbinit):
            pass  # 系统 gdbinit 可能已加载 pwndbg

    # 设置断点
    for bp in breakpoints:
        if bp.startswith("0x") or bp.isdigit():
            script_lines.append(f"b *{bp}")
        else:
            script_lines.append(f"b {bp}")

    # 写入 input_data 到临时文件
    tmp_input = None
    if input_data and not input_file:
        tmp = tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".input",
                                          prefix="pawn_gdb_")
        # 支持 \x?? 转义
        try:
            raw_bytes = bytes(input_data, "utf-8").decode("unicode_escape").encode("latin-1")
        except Exception:
            raw_bytes = input_data.encode("latin-1", errors="replace")
        tmp.write(raw_bytes); tmp.close()
        tmp_input  = tmp.name
        input_file = tmp_input

    # run 命令
    if input_file:
        script_lines.append(f"run < '{input_file}'")
    else:
        script_lines.append("run")

    # 调试命令（断点后）
    script_lines.extend(commands)
    script_lines.append("quit")

    # ── 写 GDB 脚本文件 ────────────────────────────────
    with tempfile.NamedTemporaryFile(mode="w", delete=False,
                                     suffix=".gdb", prefix="pawn_gdb_") as f:
        f.write("\n".join(script_lines) + "\n")
        script_path = f.name

    print(c(MAGENTA, f"  🐛 gdb -batch -x {script_path} {path}"))
    print(c(GRAY, f"  断点: {breakpoints}  命令: {commands}"))

    try:
        cmd = f"gdb -batch -x '{script_path}' '{path}' 2>&1"
        result = _run(cmd, timeout=timeout, cwd=_session_cwd[0])
    finally:
        try: os.unlink(script_path)
        except: pass
        if tmp_input:
            try: os.unlink(tmp_input)
            except: pass

    # ── 关键信息高亮提取 ──────────────────────────────
    highlights = []
    for line in result.splitlines():
        low = line.lower()
        if any(kw in low for kw in
               ["rip", "rsp", "rbp", "eip", "esp", "ebp", "segfault",
                "sigsegv", "overflow", "stopped", "breakpoint hit",
                "program received"]):
            highlights.append(c(YELLOW, f"  ★ {line}"))
    summary = "\n".join(highlights)

    out = f"=== GDB Batch Output ===\n{result}"
    if summary:
        out += f"\n\n=== 关键信息摘要 ===\n{summary}"
    return out

# ════════════════════════════════════════════════════════
# pwn_one_gadget — execve 跳板一键搜索（2.1.0 NEW）
# ════════════════════════════════════════════════════════

def tool_pwn_one_gadget(a: dict) -> str:
    """
    调用系统 one_gadget 工具在 libc 中搜索可直接 get-shell 的 execve 跳板地址。

    参数：
      libc_path    — libc.so 路径（必须），如 '/lib/x86_64-linux-gnu/libc.so.6'
      buildid      — （可选）通过 Build ID 查询（需联网或本地数据库）
      level        — 搜索深度 0-3（默认 0），数字越大候选越多但约束越宽松
      only_near    — （可选）仅输出约束接近 null 的候选（传 true 启用 --near 模式）

    返回：
      one_gadget 输出，包含每个候选地址及其寄存器/内存约束。
      配合 pwn_libc(action='detect') 获取 libc 版本以便核验。

    使用建议：
      1. 先 inspect_binary → 确认 NX enabled + PIE disabled（或已知 base）
      2. 先 pwn_libc(detect) → 确认 libc 路径
      3. pwn_one_gadget(libc_path) → 获取候选地址
      4. 在 exploit 中逐一尝试（one_gadget 约束必须满足才能成功）
    """
    libc_path = a.get("libc_path", "").strip()
    level     = int(a.get("level", 0))
    only_near = bool(a.get("only_near", False))

    if not libc_path:
        return (
            "ERROR: 缺少 'libc_path' 参数。\n"
            "示例: pwn_one_gadget({'libc_path': '/lib/x86_64-linux-gnu/libc.so.6'})\n"
            "可先用 pwn_libc({'path': '<binary>', 'action': 'detect'}) 确认 libc 路径。"
        )

    if not shutil.which("one_gadget"):
        return (
            "ERROR: one_gadget 未安装。\n"
            "安装方法:\n"
            "  gem install one_gadget\n"
            "  # 若无 ruby: sudo apt install ruby && gem install one_gadget\n\n"
            "one_gadget 用于在 libc 中找到满足条件即可直接 execve('/bin/sh') 的 gadget 地址，\n"
            "通常在 ret2libc / FSOP 场景中用于替代手动构造 ROP 链。"
        )

    ok, reason = _check_read(libc_path)
    if not ok: return reason
    if not Path(libc_path).expanduser().exists():
        return f"ERROR: libc 文件不存在: {libc_path}"

    # 构建命令
    cmd = f"one_gadget '{libc_path}'"
    if level > 0:
        cmd += f" --level {level}"
    if only_near:
        cmd += " --near 0"   # 约束接近 null：更容易满足

    print(c(MAGENTA, f"  💊 {cmd}"))

    raw = _run(cmd, timeout=30, cwd=_session_cwd[0])

    # ── 简单高亮解析：提取地址 ────────────────────────
    gadget_lines = []
    for line in raw.splitlines():
        if re.match(r'\s*0x[0-9a-fA-F]+', line):
            gadget_lines.append(c(GREEN, line))
        else:
            gadget_lines.append(line)

    header = (
        f"[one_gadget — {Path(libc_path).name}  level={level}]\n"
        f"注意：地址为 libc 内偏移（需加 libc base），只有约束满足时才可用。\n"
        f"{'─'*60}\n"
    )
    return header + "\n".join(gadget_lines)

# ════════════════════════════════════════════════════════
# Schema
# ════════════════════════════════════════════════════════

PWN_SCHEMAS = [
    {"type":"function","function":{
        "name":"pwn_env",
        "description":"检测 CTF/Pwn 工具链完整性（含 one_gadget），给出安装建议。首次使用时调用。",
        "parameters":{"type":"object","properties":{},"required":[]}}},

    {"type":"function","function":{
        "name":"inspect_binary",
        "description":(
            "对二进制运行 file/checksec/strings/hexdump/readelf/ldd。\n"
            "🚨 严禁：绝对不要对源码文件（.c .cpp .py .js .sh .md .txt 等文本文件）使用此工具！"
            "源码请用 grep 或 read_file。此工具仅对 ELF/PE/so/o 等真正的二进制文件有意义，"
            "对文本文件调用将被系统硬性拦截并返回错误。"
        ),
        "parameters":{"type":"object","properties":{
            "path":{"type":"string"},
            "strings_grep":{"type":"string"}},
        "required":["path"]}}},

    {"type":"function","function":{
        "name":"pwn_rop",
        "description":"用 ROPgadget/ropper 搜索 ROP gadget。",
        "parameters":{"type":"object","properties":{
            "path":{"type":"string"},
            "grep":{"type":"string","description":"过滤词，如 'pop rdi'"},
            "depth":{"type":"integer"}},
        "required":["path"]}}},

    {"type":"function","function":{
        "name":"pwn_cyclic",
        "description":"生成/查找 cyclic 偏移模式（内置 de Bruijn，无需 pwntools）。",
        "parameters":{"type":"object","properties":{
            "action":{"type":"string","enum":["gen","find"]},
            "length":{"type":"integer"},
            "value": {"type":"string","description":"如 '0x61616161' 或 'aaab'"}},
        "required":["action"]}}},

    {"type":"function","function":{
        "name":"pwn_disasm",
        "description":"objdump 反汇编：按函数名或地址范围。",
        "parameters":{"type":"object","properties":{
            "path":{"type":"string"},
            "function":{"type":"string"},
            "address": {"type":"string","description":"如 '0x401234:0x401280'"}},
        "required":["path"]}}},

    {"type":"function","function":{
        "name":"pwn_libc",
        "description":"检测 libc 版本或列出关键符号偏移。",
        "parameters":{"type":"object","properties":{
            "path":{"type":"string"},
            "action":{"type":"string","enum":["detect","symbols"]}},
        "required":["path","action"]}}},

    {"type":"function","function":{
        "name":"pwn_debug",
        "description":(
            "GDB 批处理动态调试。设置断点，喂入输入，输出寄存器/栈/回溯。\n"
            "input_data 支持 \\x?? 转义（如 'AAAA\\x00\\x00'）。\n"
            "commands 默认: ['info registers', 'x/20wx $rsp', 'backtrace 5']。"
        ),
        "parameters":{"type":"object","properties":{
            "path":        {"type":"string","description":"目标程序路径"},
            "breakpoints": {"type":"array","items":{"type":"string"},
                            "description":"断点列表，如 ['0x40068e','main']"},
            "input_data":  {"type":"string","description":"stdin 输入（支持 \\x??）"},
            "input_file":  {"type":"string","description":"stdin 重定向文件路径"},
            "commands":    {"type":"array","items":{"type":"string"},
                            "description":"断点后执行的 GDB 命令"},
            "timeout":     {"type":"integer"},
            "use_pwndbg":  {"type":"boolean","description":"是否尝试加载 pwndbg 扩展"}},
        "required":["path"]}}},

    {"type":"function","function":{
        "name":"pwn_one_gadget",
        "description":(
            "在 libc 中搜索 execve('/bin/sh') 单跳 gadget 地址（one_gadget 工具封装）。\n"
            "适用场景：已知 libc base（ret2libc / FSOP），需要一个满足约束即可 get-shell 的跳板。\n"
            "使用前提：inspect_binary 确认 NX enabled；pwn_libc detect 确认 libc 路径。\n"
            "RULE: 若 checksec 显示 'NX enabled'，禁止向栈注入 shellcode，改用本工具。"
        ),
        "parameters":{"type":"object","properties":{
            "libc_path": {"type":"string","description":"libc.so 文件路径"},
            "level":     {"type":"integer",
                          "description":"搜索深度 0-3（默认 0），越大候选越多但约束越松"},
            "only_near": {"type":"boolean","description":"仅输出约束接近 null 的候选"},
        },"required":["libc_path"]}}},
]
