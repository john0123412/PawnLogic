"""
tools/pwn_chain.py - CTF / Pwn toolchain.
  inspect_binary · pwn_rop · pwn_cyclic · pwn_disasm · pwn_libc · pwn_env
  pwn_debug - GDB batch dynamic debugging
  pwn_one_gadget - one_gadget execve trampoline search
"""

import re, shlex, shutil, subprocess, tempfile, os
from collections import OrderedDict
from pathlib import Path
from config import scrub_sensitive_env
from utils.ansi import c, YELLOW, MAGENTA, GRAY, GREEN, RED
from tools.file_ops import _run, _check_read, _session_cwd, _get_shell_env

# ELF analysis cache, keyed by (path, mtime), capped at 10 entries.
_ELF_CACHE: OrderedDict[tuple, dict] = OrderedDict()
_ELF_CACHE_MAX = 10
_ADDR_RANGE_RE = re.compile(r"^(?:0x[0-9a-fA-F]+|[0-9]+)(?::(?:0x[0-9a-fA-F]+|[0-9]+))?$")


def _q(value: str) -> str:
    return shlex.quote(str(value))


def _cache_get(path: str, slot: str) -> str | None:
    """Return cached string on hit, otherwise None."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    key = (os.path.abspath(path), mtime)
    entry = _ELF_CACHE.get(key)
    if entry and slot in entry:
        _ELF_CACHE.move_to_end(key)
        return entry[slot]
    return None


def _cache_set(path: str, slot: str, value: str) -> None:
    """Write cache entry and evict the oldest item when over capacity."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return
    key = (os.path.abspath(path), mtime)
    if key not in _ELF_CACHE:
        _ELF_CACHE[key] = {}
        if len(_ELF_CACHE) > _ELF_CACHE_MAX:
            _ELF_CACHE.popitem(last=False)
    _ELF_CACHE[key][slot] = value
    _ELF_CACHE.move_to_end(key)

# ════════════════════════════════════════════════════════
# pwn_env: environment completeness check.
# ════════════════════════════════════════════════════════

PWN_TOOLS = {
    "file":         ("file",        "basic file format identification", "sudo apt install file"),
    "checksec":     ("checksec",    "binary security mitigation check", "sudo apt install checksec"),
    "strings":      ("strings",     "string extraction",                "sudo apt install binutils"),
    "objdump":      ("objdump",     "disassembly",                      "sudo apt install binutils"),
    "readelf":      ("readelf",     "ELF structure parsing",            "sudo apt install binutils"),
    "xxd":          ("xxd",         "hex view",                         "sudo apt install xxd"),
    "gdb":          ("gdb",         "dynamic debugging",                "sudo apt install gdb"),
    "ROPgadget":    ("ROPgadget",   "ROP gadget search",                "pip3 install ROPgadget"),
    "ropper":       ("ropper",      "ROP gadget search fallback",       "pip3 install ropper"),
    "one_gadget":   ("one_gadget",  "execve trampoline search",         "gem install one_gadget"),
    "gcc":          ("gcc",         "C compiler",                       "sudo apt install gcc"),
    "gcc-multilib": (None,          "32-bit compilation support",        "sudo apt install gcc-multilib"),
    "g++":          ("g++",         "C++ compiler",                     "sudo apt install g++"),
    "python3":      ("python3",     "Python 3",          "sudo apt install python3"),
    "pwntools":     (None,          "Pwn Python library", "No global install required; available in run_code(use_venv=true) sandbox"),
    "patchelf":     ("patchelf",    "ELF patching",       "sudo apt install patchelf"),
    "strace":       ("strace",      "syscall tracing",    "sudo apt install strace"),
    "ltrace":       ("ltrace",      "library call tracing", "sudo apt install ltrace"),
    "r2":           ("r2",          "Radare2 reverse engineering framework", "sudo apt install radare2"),
    "node":         ("node",        "JavaScript",        "sudo apt install nodejs"),
}

def tool_pwn_env(a: dict) -> str:
    lines = []; missing = []; present = []
    for name, (cmd, desc, hint) in PWN_TOOLS.items():
        if cmd is None:
            if name == "gcc-multilib":
                r = subprocess.run(
                    "echo 'int main(){}' | gcc -m32 -x c - -o /dev/null 2>&1",
                    shell=True, capture_output=True, text=True, timeout=5,
                    env=scrub_sensitive_env(),
                )
                avail = r.returncode == 0
            elif name == "pwntools":
                r = subprocess.run(
                    ["python3", "-c", "import pwn; print(pwn.__version__)"],
                    capture_output=True, text=True, timeout=5,
                    env=scrub_sensitive_env(),
                )
                avail = r.returncode == 0
            else:
                avail = False
        else:
            avail = bool(shutil.which(cmd))
        status = c(GREEN, "✓") if avail else c(RED, "✗")
        lines.append(f"  {status} {name:18} {c(GRAY, desc)}")
        (present if avail else missing).append((name, hint))

    summary = [c(MAGENTA, "\n  === Pwn environment check ==="), "\n".join(lines), ""]
    summary.append(c(GREEN, f"  Installed: {len(present)} / {len(PWN_TOOLS)}"))
    if missing:
        summary.append(c(RED, f"  Missing ({len(missing)} items):"))
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
    if not Path(path).expanduser().exists(): return f"ERROR: path does not exist: {path}"

    # Hard block: do not run binary analysis tools on source/text files.
    _suffix = Path(path).suffix.lower()
    if _suffix in _TEXT_EXTENSIONS:
        return (
            f"[HARD BLOCK] inspect_binary refuses to process text/source files.\n"
            f"  File: {path}  (detected text extension: '{_suffix}')\n\n"
            f"  Reason: inspect_binary is a binary-analysis tool (file/checksec/hexdump/readelf).\n"
            f"  Running these tools on source files is meaningless and is considered tool misuse.\n\n"
            f"  Correct alternatives:\n"
            f"  - Read source content: read_file(path='{path}')\n"
            f"  - Search functions/symbols: run_shell('grep -n <keyword> {path}')\n"
            f"  - Search project references: run_shell('grep -rn <keyword> .')\n"
            f"  - Find related files: find_files('<pattern>')\n\n"
            f"  inspect_binary is only for real binaries such as ELF / PE / so / o files."
        )

    # Cache hit.
    cache_slot = f"inspect:{grep}"
    cached = _cache_get(path, cache_slot)
    if cached is not None:
        return cached

    q_path = _q(path)
    res = []
    res.append("=== file ===");            res.append(_run(f"file {q_path}").strip())
    cs = _run(f"checksec --file={q_path} 2>/dev/null || checksec {q_path} 2>/dev/null")
    if "not found" not in cs.lower() and cs.strip():
        res.append("\n=== checksec ===");  res.append(cs.strip())
    grep_pipe = f" | grep -i {_q(grep)}" if grep else " | head -60"
    res.append("\n=== strings ===");       res.append(_run(f"strings {q_path}{grep_pipe}").strip())
    res.append("\n=== hexdump (first 128B) ==="); res.append(_run(f"xxd {q_path} | head -8").strip())
    res.append("\n=== readelf -S ===");    res.append(_run(f"readelf -S {q_path} 2>/dev/null | head -30").strip())
    res.append("\n=== ldd ===");           res.append(_run(f"ldd {q_path} 2>/dev/null").strip())
    result = "\n".join(res)
    _cache_set(path, cache_slot, result)

    # Auto-append a short summary to .pawn_state.md when it exists in cwd.
    try:
        from tools.file_ops import _session_cwd
        _state_path = Path(_session_cwd[0]) / ".pawn_state.md"
        if _state_path.exists():
            _header = f"\n\n## Binary: {Path(path).name}\n"
            _body = f"```\n{result[:2000]}\n```\n"
            with open(_state_path, "a", encoding="utf-8") as _sf:
                _sf.write(_header + _body)
    except Exception:
        pass

    return result

# ════════════════════════════════════════════════════════
# pwn_rop
# ════════════════════════════════════════════════════════

def tool_pwn_rop(a: dict) -> str:
    path = a["path"]; grep = a.get("grep",""); depth = int(a.get("depth",5))
    ok, reason = _check_read(path)
    if not ok: return reason

    # Cache hit.
    cache_slot = f"rop:{grep}:{depth}"
    cached = _cache_get(path, cache_slot)
    if cached is not None:
        return cached

    q_path = _q(path)
    if shutil.which("ROPgadget"):
        cmd = f"ROPgadget --binary {q_path} --depth {depth}"
        if grep: cmd += f" | grep -i {_q(grep)}"
    elif shutil.which("ropper"):
        cmd = f"ropper --file {q_path}"
        if grep: cmd += f" --search {_q(grep)}"
    else:
        return ("Neither ROPgadget nor ropper is installed.\n"
                "  pip3 install ROPgadget\n  pip3 install ropper")
    print(c(MAGENTA, f"  🔗 {cmd[:80]}"))
    result = _run(cmd, timeout=90)
    _cache_set(path, cache_slot, result)
    return result

# ════════════════════════════════════════════════════════
# pwn_cyclic: built-in de Bruijn pattern.
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
            if big[i:i+k] == raw:      return f"Offset (little-endian): {i}  (hex: {raw.hex()})"
            if big[i:i+k] == raw[::-1]: return f"Offset (big-endian): {i}"
        return f"'{val_str}' not found. Check format, e.g. 0x61616161 or aaab."

    if action == "gen":   return f"Cyclic ({a.get('length',200)} bytes):\n{gen(int(a.get('length',200)))}"
    if action == "find":
        val = a.get("value","")
        if not val: return "ERROR: find requires 'value'"
        return find(val)
    return "ERROR: action = gen | find"

# ════════════════════════════════════════════════════════
# pwn_disasm
# ════════════════════════════════════════════════════════

def tool_pwn_disasm(a: dict) -> str:
    path = a["path"]; func = a.get("function",""); addr = a.get("address","")
    ok, reason = _check_read(path)
    if not ok: return reason
    q_path = _q(path)
    if func:
        q_func = _q(func)
        awk_script = _q(f"/^[0-9a-f]+ <{re.escape(func)}>:/,/^$/")
        nm  = _run(f"nm {q_path} 2>/dev/null | grep -w {q_func}", timeout=10)
        asm = _run(f"objdump -d -M intel {q_path} | awk {awk_script}", timeout=30)
        return f"=== nm ===\n{nm.strip()}\n\n=== disasm ===\n{asm}"
    if addr:
        if not _ADDR_RANGE_RE.match(addr):
            return "ERROR: address must be 0xADDR or 0xSTART:0xEND"
        pts = addr.split(":")
        cmd = (
            f"objdump -d -M intel --start-address={pts[0]} --stop-address={pts[1]} {q_path}"
            if len(pts) == 2 else
            f"objdump -d -M intel --start-address={addr} {q_path} | head -50"
        )
        return _run(cmd, timeout=30)
    return _run(f"objdump -d -M intel {q_path} | grep -E '^[0-9a-f]+ <' | head -60", timeout=30)

# ════════════════════════════════════════════════════════
# pwn_libc
# ════════════════════════════════════════════════════════

def tool_pwn_libc(a: dict) -> str:
    path = a["path"]; action = a["action"]
    ok, reason = _check_read(path)
    if not ok: return reason
    q_path = _q(path)
    if action == "detect":
        ver = _run(f"strings {q_path} | grep -iE 'glibc|ubuntu|libc[-_]' | head -10", timeout=15)
        bid = _run(f"readelf -n {q_path} 2>/dev/null | grep 'Build ID' | head -3", timeout=10)
        ldd = _run(f"ldd {q_path} 2>/dev/null", timeout=10)
        return f"=== version strings ===\n{ver.strip()}\n\n=== Build ID ===\n{bid.strip()}\n\n=== ldd ===\n{ldd.strip()}"
    if action == "symbols":
        key = ["system","execve","printf","puts","gets","read","write",
               "__libc_start_main","__stack_chk_fail","exit","mprotect","mmap"]
        re_out = _run(f"readelf -s {q_path} 2>/dev/null | grep -E '({'|'.join(key)})'", timeout=15)
        nm_out = _run(f"nm -D {q_path} 2>/dev/null | head -30", timeout=10)
        return f"=== readelf symbols ===\n{re_out}\n\n=== nm -D ===\n{nm_out.strip()}"
    return "ERROR: action = detect | symbols"

# ════════════════════════════════════════════════════════
# pwn_debug: GDB batch dynamic debugging.
# ════════════════════════════════════════════════════════

def tool_pwn_debug(a: dict) -> str:
    """
    Dynamically debug a binary with GDB -batch.
    Args:
      path: target program path (required)
      breakpoints: breakpoint list, e.g. ["0x40068e", "main"]
      input_data: bytes-like stdin string, e.g. "AAAA...\\x00"
      input_file: stdin redirect file path; mutually exclusive with input_data
      commands: GDB commands to run after breakpoint
      timeout: timeout seconds (default 30)
      use_pwndbg: try loading pwndbg when true
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
        return f"ERROR: file does not exist: {path}"
    if not shutil.which("gdb"):
        return "ERROR: gdb is not installed.\n  sudo apt install gdb"

    # Interactive mode delegates to tool_run_interactive.
    if interactive_mode:
        from tools.file_ops import tool_run_interactive
        bp_cmds = []
        for bp in breakpoints:
            bp_cmds.append(f"b *{bp}\n" if (bp.startswith("0x") or bp.isdigit()) else f"b {bp}\n")
        gdb_inputs = bp_cmds + [f"{cmd}\n" for cmd in commands] + ["quit\n"]
        if a.get("inputs"):
            gdb_inputs = list(a["inputs"]) + gdb_inputs
        gdb_opts = "" if use_pwndbg else "-nx "
        gdb_cmd = f"gdb {gdb_opts}-q {_q(path)}"
        print(c(MAGENTA, f"  🐛 [interactive] {gdb_cmd}"))
        return tool_run_interactive({
            "command": gdb_cmd,
            "inputs":  gdb_inputs,
            "timeout": timeout,
        })

    # Build GDB script.
    script_lines = ["set pagination off", "set confirm off", "set debuginfod enabled off"]

    # pwndbg support.
    if use_pwndbg:
        pwndbg_init = os.path.expanduser("~/.gdbinit.pwndbg")
        gdbinit     = os.path.expanduser("~/.gdbinit")
        if os.path.exists(pwndbg_init):
            script_lines.insert(0, f"source {pwndbg_init}")
        elif os.path.exists(gdbinit):
            pass

    # Set breakpoints.
    for bp in breakpoints:
        if bp.startswith("0x") or bp.isdigit():
            script_lines.append(f"b *{bp}")
        else:
            script_lines.append(f"b {bp}")

    # Write input_data to a temporary file.
    tmp_input = None
    if input_data and not input_file:
        tmp = tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".input",
                                          prefix="pawn_gdb_")
        # Support \x?? escapes.
        try:
            raw_bytes = bytes(input_data, "utf-8").decode("unicode_escape").encode("latin-1")
        except Exception:
            raw_bytes = input_data.encode("latin-1", errors="replace")
        tmp.write(raw_bytes); tmp.close()
        tmp_input  = tmp.name
        input_file = tmp_input

    # run command.
    if input_file:
        script_lines.append(f"run < '{input_file}'")
    else:
        script_lines.append("run")

    # Debug commands after breakpoint.
    script_lines.extend(commands)
    script_lines.append("quit")

    # Write GDB script file.
    with tempfile.NamedTemporaryFile(mode="w", delete=False,
                                     suffix=".gdb", prefix="pawn_gdb_") as f:
        f.write("\n".join(script_lines) + "\n")
        script_path = f.name

    gdb_opts = "" if use_pwndbg else "-nx "
    q_path = _q(path)
    q_script_path = _q(script_path)
    print(c(MAGENTA, f"  gdb {gdb_opts}-batch -x {q_script_path} {q_path}"))
    print(c(GRAY, f"  Breakpoints: {breakpoints}  Commands: {commands}"))

    try:
        cmd = f"gdb {gdb_opts}-batch -x {q_script_path} {q_path} 2>&1"
        result = _run(cmd, timeout=timeout, cwd=_session_cwd[0])
    finally:
        try: os.unlink(script_path)
        except Exception: pass
        if tmp_input:
            try: os.unlink(tmp_input)
            except Exception: pass

    # If a fatal signal appears, auto-run bt full for a complete backtrace.
    if re.search(r"SIGSEGV|SIGABRT|SIGBUS", result):
        _bt_script = script_path + ".bt"
        try:
            _bt_cmds = list(script_lines[:-2])
            _bt_cmds.extend(["bt full", "quit"])
            with open(_bt_script, "w") as _bf:
                _bf.write("\n".join(_bt_cmds) + "\n")
            _bt_cmd = f"gdb {gdb_opts}-batch -x {_q(_bt_script)} {q_path} 2>&1"
            if input_file:
                pass
            _bt_out = _run(_bt_cmd, timeout=timeout, cwd=_session_cwd[0])
            # Append bt full output.
            if "bt full" in _bt_out.lower() or "#0" in _bt_out:
                result += "\n\n=== bt full (auto-triggered by signal) ===\n" + _bt_out
        except Exception:
            pass
        finally:
            try: os.unlink(_bt_script)
            except Exception: pass

    # Extract highlighted key information.
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
        out += f"\n\n=== Key information summary ===\n{summary}"
    return out

# ════════════════════════════════════════════════════════
# pwn_one_gadget: one-shot execve trampoline search.
# ════════════════════════════════════════════════════════

def tool_pwn_one_gadget(a: dict) -> str:
    """
    Call system one_gadget to search libc for execve gadgets.

    Args:
      libc_path: libc.so path, e.g. '/lib/x86_64-linux-gnu/libc.so.6'
      buildid: optional Build ID lookup when supported
      level: search depth 0-3; higher gives more candidates with looser constraints
      only_near: output only candidates near null constraints via --near mode

    Use pwn_libc(action='detect') first to confirm libc path/version.
    """
    libc_path = a.get("libc_path", "").strip()
    level     = int(a.get("level", 0))
    only_near = bool(a.get("only_near", False))

    if not libc_path:
        return (
            "ERROR: missing 'libc_path' parameter.\n"
            "Example: pwn_one_gadget({'libc_path': '/lib/x86_64-linux-gnu/libc.so.6'})\n"
            "You can first use pwn_libc({'path': '<binary>', 'action': 'detect'}) to confirm libc path."
        )

    if not shutil.which("one_gadget"):
        return (
            "ERROR: one_gadget is not installed.\n"
            "Install:\n"
            "  gem install one_gadget\n"
            "  # without ruby: sudo apt install ruby && gem install one_gadget\n\n"
            "one_gadget finds libc gadget offsets that can directly execve('/bin/sh') when constraints are met. "
            "It is commonly used in ret2libc / FSOP instead of building a manual ROP chain."
        )

    ok, reason = _check_read(libc_path)
    if not ok: return reason
    if not Path(libc_path).expanduser().exists():
        return f"ERROR: libc file does not exist: {libc_path}"

    # Build command.
    cmd = f"one_gadget {_q(libc_path)}"
    if level > 0:
        cmd += f" --level {level}"
    if only_near:
        cmd += " --near 0"

    print(c(MAGENTA, f"  💊 {cmd}"))

    raw = _run(cmd, timeout=30, cwd=_session_cwd[0])

    # Highlight address lines.
    gadget_lines = []
    for line in raw.splitlines():
        if re.match(r'\s*0x[0-9a-fA-F]+', line):
            gadget_lines.append(c(GREEN, line))
        else:
            gadget_lines.append(line)

    header = (
        f"[one_gadget - {Path(libc_path).name}  level={level}]\n"
        f"Note: addresses are libc offsets and require adding libc base; usable only when constraints are satisfied.\n"
        f"{'─'*60}\n"
    )
    return header + "\n".join(gadget_lines)

# ════════════════════════════════════════════════════════
# Schema
# ════════════════════════════════════════════════════════

PWN_SCHEMAS = [
    {"type":"function","function":{
        "name":"pwn_env",
        "description":"Check CTF/Pwn toolchain completeness, including one_gadget, and provide install hints. Call this first.",
        "parameters":{"type":"object","properties":{},"required":[]}}},

    {"type":"function","function":{
        "name":"inspect_binary",
        "description":(
            "Run file/checksec/strings/hexdump/readelf/ldd on a binary.\n"
            "Never use this tool on source/text files (.c .cpp .py .js .sh .md .txt, etc.). "
            "Use grep or read_file for source. This tool is meaningful only for real ELF/PE/so/o binaries, "
            "and text-file calls are hard-blocked."
        ),
        "parameters":{"type":"object","properties":{
            "path":{"type":"string"},
            "strings_grep":{"type":"string"}},
        "required":["path"]}}},

    {"type":"function","function":{
        "name":"pwn_rop",
        "description":"Search ROP gadgets with ROPgadget or ropper.",
        "parameters":{"type":"object","properties":{
            "path":{"type":"string"},
            "grep":{"type":"string","description":"Filter string, e.g. 'pop rdi'."},
            "depth":{"type":"integer"}},
        "required":["path"]}}},

    {"type":"function","function":{
        "name":"pwn_cyclic",
        "description":"Generate or find cyclic pattern offsets using built-in de Bruijn logic; pwntools not required.",
        "parameters":{"type":"object","properties":{
            "action":{"type":"string","enum":["gen","find"]},
            "length":{"type":"integer"},
            "value": {"type":"string","description":"Example: '0x61616161' or 'aaab'."}},
        "required":["action"]}}},

    {"type":"function","function":{
        "name":"pwn_disasm",
        "description":"Disassemble with objdump by function name or address range.",
        "parameters":{"type":"object","properties":{
            "path":{"type":"string"},
            "function":{"type":"string"},
            "address": {"type":"string","description":"Example: '0x401234:0x401280'."}},
        "required":["path"]}}},

    {"type":"function","function":{
        "name":"pwn_libc",
        "description":"Detect libc version or list key symbol offsets.",
        "parameters":{"type":"object","properties":{
            "path":{"type":"string"},
            "action":{"type":"string","enum":["detect","symbols"]}},
        "required":["path","action"]}}},

    {"type":"function","function":{
        "name":"pwn_debug",
        "description":(
            "GDB batch dynamic debugging. Set breakpoints, feed input, and output registers/stack/backtrace.\n"
            "input_data supports \\x?? escapes, e.g. 'AAAA\\x00\\x00'.\n"
            "Default commands: ['info registers', 'x/20wx $rsp', 'backtrace 5']."
        ),
        "parameters":{"type":"object","properties":{
            "path":        {"type":"string","description":"Target program path."},
            "breakpoints": {"type":"array","items":{"type":"string"},
                            "description":"Breakpoint list, e.g. ['0x40068e','main']."},
            "input_data":  {"type":"string","description":"stdin input; supports \\x?? escapes."},
            "input_file":  {"type":"string","description":"stdin redirect file path."},
            "commands":    {"type":"array","items":{"type":"string"},
                            "description":"GDB commands to run after breakpoints."},
            "timeout":     {"type":"integer"},
            "use_pwndbg":  {"type":"boolean","description":"Try loading the pwndbg extension."}},
        "required":["path"]}}},

    {"type":"function","function":{
        "name":"pwn_one_gadget",
        "description":(
            "Search libc for one-shot execve('/bin/sh') gadget offsets through one_gadget.\n"
            "Use when libc base is known (ret2libc / FSOP) and a constraint-satisfying get-shell trampoline is needed.\n"
            "Prerequisites: inspect_binary confirms NX enabled; pwn_libc detect confirms libc path.\n"
            "RULE: when checksec shows NX enabled, do not inject shellcode on the stack; use this tool instead."
        ),
        "parameters":{"type":"object","properties":{
            "libc_path": {"type":"string","description":"libc.so file path."},
            "level":     {"type":"integer",
                          "description":"Search depth 0-3 (default 0); higher yields more candidates with looser constraints."},
            "only_near": {"type":"boolean","description":"Output only candidates whose constraints are near null."},
        },"required":["libc_path"]}}},

    # P1: pwn_timed_debug - countdown-aware interactive debugging.
    {"type":"function","function":{
        "name":"pwn_timed_debug",
        "description":(
            "Countdown-aware interactive dynamic debugging for time-limited CTF targets.\n"
            "Wraps run_interactive-style behavior, controls timeout, and returns collected output.\n"
            "Use for connecting to remote targets, sending exploits, and reading flags.\n"
            "When time_limit_sec expires, it terminates automatically and returns all collected output."
        ),
        "parameters":{"type":"object","properties":{
            "command":       {"type":"string","description":"Shell command, e.g. 'nc target.ctf.site 1337'."},
            "inputs":        {"type":"array","items":{"type":"string"},
                              "description":"Ordered input list. 'SLEEP:N' waits N seconds."},
            "time_limit_sec":{"type":"integer","description":"Total time limit seconds (default 60)."},
            "poll_interval": {"type":"number","description":"Seconds to wait for response after each send (default 0.5)."},
        },"required":["command"]}}},
]


# ════════════════════════════════════════════════════════
# P1: pwn_timed_debug - countdown-aware interactive debugging.
#
# Available in all phases (RECON / VULN_DEV / EXPLOIT / GENERAL).
# Registered manually through TOOL_MAP + AGENT_PHASES allowlist.
# ════════════════════════════════════════════════════════

def tool_pwn_timed_debug(a: dict) -> str:
    """
    Countdown-aware interactive dynamic debugging tool.

    Use cases:
      - CTF dynamic targets with countdown-limited nc interactions.
      - Sending an exploit and collecting a flag within a fixed time window.
      - Automated Pwn verification pipelines.

    Difference from pwn_debug:
      - pwn_debug: GDB batch mode for local binary analysis.
      - pwn_timed_debug: network/process interaction with deadline control.

    Difference from run_interactive:
      - run_interactive: generic interactive process, no countdown awareness.
      - pwn_timed_debug: CTF-oriented, terminates at deadline and returns partial results.

    Parameters
    ----------
    command : str
        Shell command, e.g. 'nc target.ctf.site 1337' or './exploit.py'.
    inputs : list[str]
        Ordered input list. Each item is sent after collecting a response.
        Special instruction 'SLEEP:N' waits N seconds, e.g. 'SLEEP:0.5'.
        Example: ["1\\n", "SLEEP:0.5", "payload\\n", "cat /flag\\n"]
    time_limit_sec : int
        Total time limit in seconds, default 60. Terminates at deadline and returns collected output.
    poll_interval : float
        Seconds to wait for response after each send, default 0.5.

    Returns
    -------
    str
        Formatted output containing a status header and collected stdout/stderr.

    Examples
    --------
    >>> tool_pwn_timed_debug({
    ...     "command": "nc challenge.ctf.com 1337",
    ...     "inputs": ["1\\n", "SLEEP:1", "AAAA...\\n"],
    ...     "time_limit_sec": 30,
    ... })
    """
    import time as _time
    import re as _re
    import threading, queue, subprocess

    command: str          = a.get("command", "").strip()
    inputs: list          = a.get("inputs", [])
    time_limit_sec: int   = int(a.get("time_limit_sec", 60))
    poll_interval: float  = float(a.get("poll_interval", 0.5))

    if not command:
        return "ERROR: 'command' parameter is required. Example: 'nc target.ctf.site 1337'"

    # Security checks.
    from tools.file_ops import DANGEROUS_PATTERNS, _session_cwd
    for pat in DANGEROUS_PATTERNS:
        if _re.search(pat, command):
            return f"SECURITY BLOCK: dangerous command pattern '{pat}'"

    print(c(MAGENTA, f"  [timed-debug] $ {command[:100]}"))
    print(c(GRAY,    f"  Time limit: {time_limit_sec}s  Inputs: {len(inputs)}  Poll interval: {poll_interval}s"))

    output_chunks: list[str] = []
    deadline   = _time.time() + time_limit_sec
    timed_out  = False
    start_time = _time.time()

    # Start subprocess.
    try:
        proc = subprocess.Popen(
            command, shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=_session_cwd[0],
            bufsize=0,
            env=_get_shell_env(),
        )
    except FileNotFoundError:
        return f"ERROR: command not found: {command.split()[0]}"
    except Exception as e:
        return f"ERROR: failed to start process: {type(e).__name__}: {e}"

    # Background stdout reader thread.
    output_q: queue.Queue[str] = queue.Queue()

    def _reader() -> None:
        try:
            while True:
                chunk = proc.stdout.read(512)
                if not chunk:
                    break
                output_q.put(chunk.decode("utf-8", errors="replace"))
        except Exception:
            pass

    threading.Thread(target=_reader, daemon=True).start()

    def _drain(wait: float = 0.3) -> str:
        """Wait for wait seconds, then collect all available output."""
        _time.sleep(wait)
        parts: list[str] = []
        while not output_q.empty():
            try:
                parts.append(output_q.get_nowait())
            except queue.Empty:
                break
        return "".join(parts)

    # Main interaction loop.
    try:
        # Collect initial banner / prompt.
        output_chunks.append(_drain(0.6))

        for inp in inputs:
            # Check deadline before each operation.
            remaining = deadline - _time.time()
            if remaining <= 0:
                output_chunks.append(
                    f"\n[TIME LIMIT {time_limit_sec}s REACHED — collecting partial results]"
                )
                timed_out = True
                break

            # Handle SLEEP instruction.
            if isinstance(inp, str) and inp.upper().startswith("SLEEP:"):
                try:
                    sleep_sec = float(inp.split(":", 1)[1])
                    # Do not sleep beyond the remaining deadline.
                    _time.sleep(min(sleep_sec, max(0, remaining)))
                except (ValueError, IndexError):
                    pass
                output_chunks.append(_drain(0.1))
                continue

            # Send input.
            data = inp.encode() if isinstance(inp, str) else inp
            try:
                proc.stdin.write(data)
                proc.stdin.flush()
            except BrokenPipeError:
                output_chunks.append("[process closed stdin early]")
                break

            output_chunks.append(_drain(poll_interval))

        # Final drain and graceful exit.
        if not timed_out:
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.terminate()
        output_chunks.append(_drain(0.3))

    except Exception as e:
        output_chunks.append(f"\n[ERROR during timed-debug: {type(e).__name__}: {e}]")
    finally:
        try:
            proc.terminate()
        except Exception:
            pass

    # Format output.
    full = "".join(output_chunks)

    from core.state import runtime_config
    limit = runtime_config()["tool_max_chars"]
    if len(full) > limit:
        half = limit // 2
        full = full[:half] + f"\n...[truncated to {limit} chars]...\n" + full[-half // 4:]

    elapsed = min(time_limit_sec, int(_time.time() - start_time))
    status  = "time limit reached (partial results)" if timed_out else "completed normally"
    header  = (
        f"[pwn_timed_debug - {status} | elapsed: {elapsed}s / {time_limit_sec}s]\n"
        f"{'─' * 50}\n"
    )
    return header + (full or "(no output)")
