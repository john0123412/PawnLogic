"""
tools/sandbox.py — multi-language code execution sandbox.

WSL performance optimizations:
  1. preexec_fn sets resource limits: 512 MB memory, CPU time = timeout + 5s.
  2. nice +10 lowers subprocess scheduling priority.
  3. Output is truncated at the subprocess layer to avoid large in-memory buffers.
  4. Existing venvs are reused to avoid repeated I/O.
  5. Compilation artifacts go to /tmp, which is tmpfs and faster than /home on WSL.
"""

import os, signal, sys, re, subprocess, tempfile
from pathlib import Path
from config import SANDBOX_LANGS
from core.state import runtime_config
from utils.ansi import c, YELLOW, RED

# Resource limits are available only on POSIX systems: Linux / WSL2 / macOS.
_IS_POSIX = (os.name == "posix")
if _IS_POSIX:
    import resource

# WSL resource-limit constants.
_MEM_LIMIT_MB      = 512          # Max subprocess memory in MB.
_NICE_LEVEL        = 10           # nice value to lower scheduling priority.
_OUTPUT_HARD_BYTES = 256_000      # Hard subprocess output truncation in bytes.
_PY_PKG_NAME_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9_,.-]+\])?([<>=!~]=?[A-Za-z0-9.*+!._-]+)?$"
)
_SYS_PKG_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+.-]*$")

# Minimized environment to prevent API keys and other secrets leaking to subprocesses.
_SENSITIVE_ENV_KEYS = {
    "PAWN_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "QWEN_API_KEY",
    "ZHIPU_API_KEY", "SILICON_API_KEY", "OPENROUTER_API_KEY", "MOONSHOT_API_KEY",
    "MINIMAX_API_KEY", "GROQ_API_KEY", "LOCAL_API_KEY", "XIAOMI_API_KEY",
    "TAVILY_API_KEY", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
}

def _build_sandbox_env() -> dict:
    """Build a minimal environment with only basic vars and no API keys."""
    env = {}
    safe_keys = {"PATH", "HOME", "USER", "LANG", "LC_ALL", "LC_CTYPE",
                 "TERM", "SHELL", "TMPDIR", "TEMP", "TMP",
                 "VIRTUAL_ENV", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"}
    for k, v in os.environ.items():
        if k in safe_keys:
            env[k] = v
        elif k in _SENSITIVE_ENV_KEYS:
            continue  # Drop API keys.
        elif k.startswith("PAWN_") or k.startswith("OPENAI_") or k.startswith("DEEPSEEK_"):
            continue  # Drop likely API-related variables.
    return env


def _invalid_packages(pkgs: list[str], pattern: re.Pattern[str]) -> list[str]:
    return [pkg for pkg in pkgs if not pattern.fullmatch(pkg)]


def _sandbox_preexec(cpu_timeout: int) -> None:
    """
    Run after fork and before exec in the subprocess, POSIX only.
    Sets resource limits to prevent runaway processes from harming the host.
    """
    if not _IS_POSIX:
        return  # Windows has no resource module.

    # Memory limit: 512 MB.
    mem = _MEM_LIMIT_MB * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    except (ValueError, resource.error):
        pass

    # CPU time limit: timeout plus 5 seconds of buffer.
    cpu = cpu_timeout + 5
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    except (ValueError, resource.error):
        pass

    # File write limit: 64 MB, to avoid filling the disk.
    fsize = 64 * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
    except (ValueError, resource.error, AttributeError):
        pass

    # Process count limit to reduce fork-bomb risk, Linux only.
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))
    except (ValueError, resource.error, AttributeError):
        pass

    # Lower scheduling priority with nice +10.
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
    Run a subprocess with resource limits.
    Returns (output_text, return_code). Output above _OUTPUT_HARD_BYTES is
    truncated before large buffers accumulate in memory.
    """
    # Use minimized sandbox environment by default to prevent API key leaks.
    if env is None:
        env = _build_sandbox_env()

    # Windows does not support preexec_fn.
    preexec = None
    start_new_session = False
    if not disable_rlimit and _IS_POSIX:
        preexec = lambda: _sandbox_preexec(timeout)
        start_new_session = True

    try:
        proc = subprocess.Popen(
            cmd,
            shell=shell,
            stdin=subprocess.PIPE if input_data else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,   # Merge stderr so only one pipe is read.
            cwd=cwd,
            env=env,
            preexec_fn=preexec,
            start_new_session=start_new_session,
        )
        # communicate with timeout.
        try:
            stdout_bytes, _ = proc.communicate(
                input=input_data.encode() if input_data else None,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            if start_new_session and _IS_POSIX:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    proc.kill()
            else:
                proc.kill()
            proc.communicate()
            return f"[execution timed out after {timeout}s]", 1

        # Hard truncation.
        if len(stdout_bytes) > _OUTPUT_HARD_BYTES:
            half = _OUTPUT_HARD_BYTES // 2
            stdout_bytes = (
                stdout_bytes[:half]
                + f"\n...[output too large, truncated to {_OUTPUT_HARD_BYTES//1024}KB]...\n".encode()
                + stdout_bytes[-half // 4:]
            )

        return stdout_bytes.decode("utf-8", errors="replace"), proc.returncode

    except FileNotFoundError as e:
        return f"ERROR: command not found — {e}", 1
    except MemoryError:
        return "ERROR: memory limit exceeded (>512MB)", 1
    except Exception as e:
        return f"ERROR: {e}", 1


def _get_python_exec(use_venv: bool, cwd: str) -> str:
    """Return Python executable; supports automatic ./venv creation/reuse."""
    if not use_venv:
        return sys.executable
    venv_path = Path(cwd) / "venv"
    if not venv_path.exists():
        print(c(YELLOW, f"  🐍 Creating venv: {venv_path}"))
        out, rc = _run_limited(
            [sys.executable, "-m", "venv", str(venv_path)],
            timeout=60, cwd=cwd
        )
        if rc != 0:
            print(c(RED, f"  venv creation failed: {out[:200]}"))
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
        return (f"ERROR: unsupported language '{language}'.\n"
                f"Supported: {', '.join(SANDBOX_LANGS.keys())}")

    lang_cfg = SANDBOX_LANGS[language]
    ext      = lang_cfg["ext"]
    output   = []

    # Use system temp dir. Linux/WSL uses /tmp tmpfs; Windows uses %TEMP%.
    _tmp_root = "/tmp" if _IS_POSIX else None  # None = system default tempdir.
    with tempfile.TemporaryDirectory(prefix="pawn_sandbox_", dir=_tmp_root) as tmpdir:

        # ══ Python ══════════════════════════════════════
        if language == "python":
            py_exec = _get_python_exec(use_venv, cwd)

            if install_deps:
                pkgs = install_deps.split()
                invalid = _invalid_packages(pkgs, _PY_PKG_NAME_RE)
                if invalid:
                    return "ERROR: invalid Python package name(s): " + ", ".join(invalid)
                print(c(YELLOW, f"  📦 pip install {' '.join(pkgs)}"))
                out, rc = _run_limited(
                    [py_exec, "-m", "pip", "install", *pkgs, "-q",
                     "--no-warn-script-location"],
                    timeout=120, cwd=cwd, disable_rlimit=True,
                )
                if rc != 0:
                    output.append(f"[pip warning]\n{out[:500]}")

            src = os.path.join(tmpdir, f"code{ext}")
            with open(src, "w", encoding="utf-8") as f:
                f.write(code)
            print(c(YELLOW, f"  🐍 python code{ext}"))
            out, rc = _run_limited(
                [py_exec, src],
                timeout=timeout, cwd=tmpdir, input_data=stdin_data,
            )
            output.append(out)
            output.append(f"[exit {rc}]")

        # Compiled languages: C / C++ / Rust / Java.
        elif lang_cfg.get("compile"):
            src  = os.path.join(tmpdir, f"code{ext}")
            bin_ = os.path.join(tmpdir, "a.out")
            with open(src, "w", encoding="utf-8") as f:
                f.write(code)

            compile_cmd = lang_cfg["compile"].format(src=src, bin=bin_)
            print(c(YELLOW, f"  🔨 {compile_cmd[:90]}"))
            cout, crc = _run_limited(compile_cmd, timeout=60, cwd=tmpdir, shell=True)
            if cout.strip():
                output.append(f"[compile output]\n{cout}")
            if crc != 0:
                output.append(f"[compile failed exit {crc}]")
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

        # Interpreted commands: bash / node / go run.
        else:
            src = os.path.join(tmpdir, f"code{ext}")
            with open(src, "w", encoding="utf-8") as f:
                f.write(code)
            run_cmd = lang_cfg["cmd"].format(
                src=src, bin=os.path.join(tmpdir, "a.out")
            )
            print(c(YELLOW, f"  ▶ {run_cmd[:90]}"))
            out, rc = _run_limited(
                run_cmd, timeout=timeout, cwd=tmpdir,
                input_data=stdin_data, shell=True,
            )
            output.append(out)
            output.append(f"[exit {rc}]")

    result = "\n".join(x for x in output if x)
    limit  = runtime_config()["tool_max_chars"]
    if len(result) > limit:
        result = result[:limit // 2] + "\n...[truncated]...\n" + result[-limit // 4:]
    return result or "(no output)"


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

    invalid_python = _invalid_packages(python_pkgs, _PY_PKG_NAME_RE)
    invalid_system = _invalid_packages(system_pkgs, _SYS_PKG_NAME_RE)
    if invalid_python or invalid_system:
        parts = []
        if invalid_python:
            parts.append("python=" + ", ".join(invalid_python))
        if invalid_system:
            parts.append("system=" + ", ".join(invalid_system))
        return "ERROR: invalid package name(s): " + "; ".join(parts)

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
                ["dpkg", "-s", pkg],
                timeout=6, cwd=cwd, shell=False, disable_rlimit=True,
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
            "Execute code in a sandbox. Languages: python / c / cpp / javascript / bash / rust / go / java.\n"
            "Python: use_venv=true creates/reuses ./venv; install_deps='numpy requests' installs deps.\n"
            "C/C++: automatically compiles with gcc/g++, then runs after compile output.\n"
            "Resource limits: memory 512MB, CPU = timeout+5s, output 256KB.\n"
            "Anti-hallucination warning: if your script needs local files, it must read them "
            "with open('path').read(). Never fabricate, invent, or hardcode fake target file content."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "language":     {"type": "string"},
                "code":         {"type": "string"},
                "stdin":        {"type": "string"},
                "timeout":      {"type": "integer", "description": "Execution timeout in seconds; default 10"},
                "use_venv":     {"type": "boolean", "description": "Python only: use ./venv"},
                "install_deps": {"type": "string",  "description": "Python only: space-separated pip package names"},
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
