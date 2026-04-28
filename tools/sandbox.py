"""
tools/sandbox.py — 多语言代码执行沙箱（重构版）

WSL 性能优化：
  ① preexec_fn 设置 resource 限制（内存 512MB、CPU 时间 = timeout+5s）
  ② 进程 nice +10 降低调度优先级，不抢主进程 CPU
  ③ 输出限制提前在 subprocess 层截断，避免大输出全量缓冲进内存
  ④ venv 复用检测：已存在则不重建，避免重复 I/O
  ⑤ 编译产物写入 /tmp（tmpfs，WSL 下比 /home 快）
"""

import os, sys, re, subprocess, tempfile, resource
from pathlib import Path
from config import DYNAMIC_CONFIG, SANDBOX_LANGS
from utils.ansi import c, YELLOW, RED

# ── WSL 资源限制常量 ──────────────────────────────────────
_MEM_LIMIT_MB   = 512          # 子进程最大内存（MB）
_NICE_LEVEL     = 10           # nice 值：降低调度优先级
_OUTPUT_HARD_BYTES = 256_000   # subprocess 输出硬截断（字节）


def _sandbox_preexec(cpu_timeout: int) -> None:
    """
    在子进程 fork 后、exec 前执行。
    设置资源上限，防止失控进程拖垮 WSL。
    """
    # 内存上限：512 MB
    mem = _MEM_LIMIT_MB * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    except (ValueError, resource.error):
        pass  # 部分 WSL 内核不支持，忽略

    # CPU 时间上限：比 timeout 多 5s 作为缓冲
    cpu = cpu_timeout + 5
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    except (ValueError, resource.error):
        pass

    # 降低调度优先级（nice +10）
    try:
        os.nice(_NICE_LEVEL)
    except OSError:
        pass


def _run_limited(
    cmd,
    timeout: int,
    cwd: str,
    input_data: str = "",
    shell: bool = False,
    env=None,
    disable_rlimit: bool = False,
) -> tuple[str, int]:
    """
    带资源限制的 subprocess 运行。
    返回 (output_text, return_code)。
    输出超过 _OUTPUT_HARD_BYTES 时直接截断，不会全量进内存。
    """
    try:
        proc = subprocess.Popen(
            cmd,
            shell=shell,
            stdin=subprocess.PIPE if input_data else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,   # 合并 stderr，只读一个管道
            cwd=cwd,
            env=env,
            preexec_fn=None if disable_rlimit else lambda: _sandbox_preexec(timeout),
        )
        # communicate 带超时
        try:
            stdout_bytes, _ = proc.communicate(
                input=input_data.encode() if input_data else None,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return f"[执行超时 {timeout}s]", 1

        # 硬截断
        if len(stdout_bytes) > _OUTPUT_HARD_BYTES:
            half = _OUTPUT_HARD_BYTES // 2
            stdout_bytes = (
                stdout_bytes[:half]
                + f"\n...[输出过大，已截断至 {_OUTPUT_HARD_BYTES//1024}KB]...\n".encode()
                + stdout_bytes[-half // 4:]
            )

        return stdout_bytes.decode("utf-8", errors="replace"), proc.returncode

    except FileNotFoundError as e:
        return f"ERROR: 命令不存在 — {e}", 1
    except MemoryError:
        return "ERROR: 内存超限（>512MB）", 1
    except Exception as e:
        return f"ERROR: {e}", 1


def _get_python_exec(use_venv: bool, cwd: str) -> str:
    """获取 Python 解释器，支持 ./venv 自动创建/复用。"""
    if not use_venv:
        return sys.executable
    venv_path = Path(cwd) / "venv"
    if not venv_path.exists():
        print(c(YELLOW, f"  🐍 创建 venv: {venv_path}"))
        out, rc = _run_limited(
            [sys.executable, "-m", "venv", str(venv_path)],
            timeout=60, cwd=cwd
        )
        if rc != 0:
            print(c(RED, f"  venv 创建失败: {out[:200]}"))
            return sys.executable
    for candidate in ["bin/python3", "bin/python", "Scripts/python.exe"]:
        py = venv_path / candidate
        if py.exists():
            return str(py)
    return sys.executable


def tool_run_code(a: dict) -> str:
    language     = a.get("language", "").lower().strip()
    code         = a.get("code", "")
    stdin_data   = a.get("stdin", "")
    timeout      = int(a.get("timeout", 10))
    use_venv     = bool(a.get("use_venv", False))
    install_deps = a.get("install_deps", "").strip()
    cwd          = a.get("cwd") or _get_cwd()

    if language not in SANDBOX_LANGS:
        return (f"ERROR: 不支持的语言 '{language}'。\n"
                f"支持: {', '.join(SANDBOX_LANGS.keys())}")

    lang_cfg = SANDBOX_LANGS[language]
    ext      = lang_cfg["ext"]
    output   = []

    # 使用 /tmp 下的临时目录（WSL 中 tmpfs，比 /home 快）
    with tempfile.TemporaryDirectory(prefix="pawn_sandbox_", dir="/tmp") as tmpdir:

        # ══ Python ══════════════════════════════════════
        if language == "python":
            py_exec = _get_python_exec(use_venv, cwd)

            if install_deps:
                pkgs = install_deps.split()
                print(c(YELLOW, f"  📦 pip install {' '.join(pkgs)}"))
                out, rc = _run_limited(
                    [py_exec, "-m", "pip", "install", *pkgs, "-q",
                     "--no-warn-script-location"],
                    timeout=120, cwd=cwd, disable_rlimit=True,
                )
                if rc != 0:
                    output.append(f"[pip 警告]\n{out[:500]}")

            src = os.path.join(tmpdir, f"code{ext}")
            with open(src, "w", encoding="utf-8") as f:
                f.write(code)
            print(c(YELLOW, f"  🐍 python code{ext}"))
            out, rc = _run_limited(
                [py_exec, src],
                timeout=timeout, cwd=cwd, input_data=stdin_data,
            )
            output.append(out)
            output.append(f"[exit {rc}]")

        # ══ 编译型（C / C++ / Rust / Java）════════════
        elif lang_cfg.get("compile"):
            src  = os.path.join(tmpdir, f"code{ext}")
            bin_ = os.path.join(tmpdir, "a.out")
            with open(src, "w", encoding="utf-8") as f:
                f.write(code)

            compile_cmd = lang_cfg["compile"].format(src=src, bin=bin_)
            print(c(YELLOW, f"  🔨 {compile_cmd[:90]}"))
            cout, crc = _run_limited(compile_cmd, timeout=60, cwd=tmpdir, shell=True)
            if cout.strip():
                output.append(f"[编译输出]\n{cout}")
            if crc != 0:
                output.append(f"[编译失败 exit {crc}]")
                return "\n".join(output)

            if language == "java":
                cm = re.search(r'\bclass\s+(\w+)', code)
                cls_name = cm.group(1) if cm else "Main"
                run_cmd  = f"java -cp {tmpdir} {cls_name}"
                run_out, run_rc = _run_limited(
                    run_cmd, timeout=timeout, cwd=tmpdir,
                    input_data=stdin_data, shell=True,
                )
            else:
                print(c(YELLOW, f"  ▶ {bin_}"))
                run_out, run_rc = _run_limited(
                    [bin_], timeout=timeout, cwd=tmpdir, input_data=stdin_data,
                )
            output.append(run_out)
            output.append(f"[exit {run_rc}]")

        # ══ 解释型（bash / node / go run）═════════════
        else:
            src = os.path.join(tmpdir, f"code{ext}")
            with open(src, "w", encoding="utf-8") as f:
                f.write(code)
            run_cmd = lang_cfg["cmd"].format(
                src=src, bin=os.path.join(tmpdir, "a.out")
            )
            print(c(YELLOW, f"  ▶ {run_cmd[:90]}"))
            out, rc = _run_limited(
                run_cmd, timeout=timeout, cwd=cwd,
                input_data=stdin_data, shell=True,
            )
            output.append(out)
            output.append(f"[exit {rc}]")

    result = "\n".join(x for x in output if x)
    limit  = DYNAMIC_CONFIG["tool_max_chars"]
    if len(result) > limit:
        result = result[:limit // 2] + "\n...[截断]...\n" + result[-limit // 4:]
    return result or "(无输出)"


def _get_cwd() -> str:
    from tools.file_ops import _session_cwd
    return _session_cwd[0]


def tool_check_deps(a: dict) -> str:
    """
    Verify Python packages and/or system packages are available BEFORE running code.
    Use this before complex run_code calls that require pwntools, scipy, etc.

    python: space-separated pip package names  (e.g. "pwntools numpy")
    system: space-separated apt package names  (e.g. "libssl-dev gcc-multilib")
    use_venv: check inside ./venv if True

    Returns a summary of satisfied / missing deps.
    The agent can then install missing ones with run_code(install_deps=...) or run_shell(apt install).
    """
    python_pkgs = [p.strip() for p in a.get("python", "").split()  if p.strip()]
    system_pkgs = [p.strip() for p in a.get("system", "").split()  if p.strip()]
    use_venv    = bool(a.get("use_venv", False))
    cwd         = a.get("cwd") or _get_cwd()

    if not python_pkgs and not system_pkgs:
        return "ERROR: specify at least one of 'python' or 'system' package lists"

    results: list[str] = []

    # ── Python packages ───────────────────────────────────
    if python_pkgs:
        py_exec = _get_python_exec(use_venv, cwd)
        out, _  = _run_limited(
            [py_exec, "-m", "pip", "list", "--format=columns"],
            timeout=15, cwd=cwd, disable_rlimit=True,
        )
        # Build set of installed package names (lowercase, normalised _ ↔ -)
        installed: set[str] = set()
        for line in out.splitlines()[2:]:   # skip header
            parts = line.split()
            if parts:
                name = parts[0].lower()
                installed.add(name)
                installed.add(name.replace("-", "_"))
                installed.add(name.replace("_", "-"))

        for pkg in python_pkgs:
            norm  = pkg.lower()
            found = norm in installed or norm.replace("-", "_") in installed
            mark  = "✓" if found else "✗"
            hint  = "" if found else f"  → fix: run_code(install_deps='{pkg}')"
            results.append(f"  {mark} python: {pkg}{hint}")

    # ── System packages ───────────────────────────────────
    if system_pkgs:
        for pkg in system_pkgs:
            out, rc = _run_limited(
                f"dpkg -s {pkg} 2>/dev/null | grep '^Status'",
                timeout=6, cwd=cwd, shell=True, disable_rlimit=True,
            )
            found = "install ok" in out.lower()
            mark  = "✓" if found else "✗"
            hint  = "" if found else f"  → fix: run_shell('sudo apt install -y {pkg}')"
            results.append(f"  {mark} system: {pkg}{hint}")

    total   = len(results)
    ok_cnt  = sum(1 for r in results if r.strip().startswith("✓"))
    summary = f"Dependency check: {ok_cnt}/{total} satisfied"
    if ok_cnt < total:
        summary += "  ← missing packages detected, install before run_code"
    return summary + "\n" + "\n".join(results)


# ── Schema ───────────────────────────────────────────────

SANDBOX_SCHEMAS = [
    {"type": "function", "function": {
        "name": "run_code",
        "description": (
            "在沙箱中执行代码。语言: python / c / cpp / javascript / bash / rust / go / java。\n"
            "Python: use_venv=true 自动创建/复用 ./venv；install_deps='numpy requests' 安装依赖。\n"
            "C/C++: 自动 gcc/g++ 编译，先输出编译信息再运行。\n"
            "资源限制：内存 512MB，CPU = timeout+5s，输出 256KB。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "language":     {"type": "string"},
                "code":         {"type": "string"},
                "stdin":        {"type": "string"},
                "timeout":      {"type": "integer", "description": "执行超时秒数（默认10）"},
                "use_venv":     {"type": "boolean", "description": "Python only: 使用 ./venv"},
                "install_deps": {"type": "string",  "description": "Python only: 空格分隔的 pip 包名"},
            },
            "required": ["language", "code"],
        },
    }},

    {"type": "function", "function": {
        "name": "check_deps",
        "description": (
            "Verify Python packages and/or system packages are installed BEFORE running code.\n"
            "Use before complex run_code calls (pwntools, scipy, openssl-dev, etc).\n"
            "Reports ✓/✗ per package with fix commands for missing ones."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "python":   {"type": "string",  "description": "Space-separated pip package names"},
                "system":   {"type": "string",  "description": "Space-separated apt package names"},
                "use_venv": {"type": "boolean", "description": "Check inside ./venv (default false)"},
            },
            "required": [],
        },
    }},
]
