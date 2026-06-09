"""
tools/recon_ops.py - P6 service environment reconnaissance.
===========================================================
tool_check_service(port): quickly extract process information for a listening port
using /proc or lsof.

Returns PID, process name, executable path, environment variables, and linked
dynamic libraries.

Safety constraints:
  - Read-only operations; no system state changes.
  - Output is cleaned with errors='ignore'.
"""

import os
import re
import subprocess
from pathlib import Path
from config import scrub_sensitive_env


def _clean(text: str) -> str:
    """Clean encoding to avoid terminal crashes."""
    if text is None:
        return ""
    return text.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")


def _find_pid_by_port_lsof(port: int) -> list[dict]:
    """Find processes listening on a port using lsof."""
    try:
        result = subprocess.run(
            ["lsof", "-i", f":{port}", "-sTCP:LISTEN", "-nP"],
            capture_output=True, text=True, timeout=5, errors="ignore",
            env=scrub_sensitive_env(),
        )
        if result.returncode != 0:
            return []
        pids = []
        for line in result.stdout.strip().splitlines()[1:]:  # skip header
            parts = line.split()
            if len(parts) >= 2:
                try:
                    pids.append({"pid": int(parts[1]), "raw": line.strip()})
                except ValueError:
                    pass
        return pids
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def _find_pid_by_port_proc(port: int) -> list[dict]:
    """Find processes listening on a port through /proc without lsof."""
    port_hex = f"{port:04X}"
    target_inodes = set()

    for proto in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(proto, "r", errors="ignore") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 10:
                        continue
                    # state=0A means LISTEN.
                    local = parts[1]
                    state = parts[3]
                    inode = parts[9]
                    if state != "0A":
                        continue
                    # local_addr format: HEX_IP:PORT
                    if local.endswith(f":{port_hex}"):
                        target_inodes.add(inode)
        except OSError:
            continue

    if not target_inodes:
        return []

    # Walk /proc/<pid>/fd to find matching socket inodes.
    pids = []
    try:
        for entry in os.scandir("/proc"):
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            fd_dir = f"/proc/{pid}/fd"
            try:
                for fd in os.scandir(fd_dir):
                    try:
                        link = os.readlink(fd.path)
                        # socket:[inode]
                        for inode in target_inodes:
                            if link == f"socket:[{inode}]":
                                pids.append({"pid": pid, "raw": ""})
                                break
                    except OSError:
                        continue
            except OSError:
                continue
    except OSError:
        pass
    return pids


def _get_proc_info(pid: int) -> dict:
    """Extract detailed process information from /proc/<pid>/."""
    info = {"pid": pid}
    base = Path(f"/proc/{pid}")

    # Process name.
    try:
        info["name"] = (base / "comm").read_text(errors="ignore").strip()
    except OSError:
        info["name"] = "?"

    # Executable path.
    try:
        info["exe"] = os.readlink(str(base / "exe"))
    except OSError:
        info["exe"] = "?"

    # Command line.
    try:
        cmdline = (base / "cmdline").read_text(errors="ignore")
        info["cmdline"] = cmdline.replace("\x00", " ").strip()
    except OSError:
        info["cmdline"] = "?"

    # Working directory.
    try:
        info["cwd"] = os.readlink(str(base / "cwd"))
    except OSError:
        info["cwd"] = "?"

    # Environment variables, limited to security-relevant keys.
    try:
        env_raw = (base / "environ").read_text(errors="ignore")
        env_vars = {}
        _SECURE_KEYS = (
            "PATH", "HOME", "USER", "SHELL", "LD_LIBRARY_PATH",
            "LD_PRELOAD", "PYTHONPATH", "NODE_PATH", "GOPATH",
            "JAVA_HOME", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
        )
        for entry in env_raw.split("\x00"):
            if "=" in entry:
                k, v = entry.split("=", 1)
                k = k.strip()
                if k in _SECURE_KEYS or k.startswith("PAWN_") or k.startswith("API_"):
                    env_vars[k] = v.strip()
        info["env"] = env_vars
    except OSError:
        info["env"] = {}

    # Linked dynamic libraries from /proc/<pid>/maps, deduplicated.
    try:
        maps_text = (base / "maps").read_text(errors="ignore")
        libs = set()
        for line in maps_text.splitlines():
            # Match paths containing .so.
            match = re.search(r"\s+(/\S+\.so\S*)", line)
            if match:
                libs.add(match.group(1))
        info["libs"] = sorted(libs)[:30]
    except OSError:
        info["libs"] = []

    return info


def tool_check_service(args: dict) -> str:
    """
    Inspect details for service processes listening on a given port.
    Uses /proc or lsof to extract PID, process name, executable path,
    environment variables, and linked dynamic libraries.
    """
    port = args.get("port")
    if port is None:
        return "ERROR: port parameter is required"
    try:
        port = int(port)
    except ValueError:
        return f"ERROR: invalid port '{port}'"
    if not (1 <= port <= 65535):
        return f"ERROR: port {port} is out of range (1-65535)"

    # Prefer lsof, fall back to /proc.
    pids = _find_pid_by_port_lsof(port)
    method = "lsof"
    if not pids:
        pids = _find_pid_by_port_proc(port)
        method = "/proc"
    if not pids:
        return f"No listening process found on port {port}"

    # Deduplicate.
    seen = set()
    unique_pids = []
    for p in pids:
        if p["pid"] not in seen:
            seen.add(p["pid"])
            unique_pids.append(p)

    results = []
    for p in unique_pids:
        info = _get_proc_info(p["pid"])
        lines = [
            f"=== Port {port} process information (via {method}) ===",
            f"  PID       : {info['pid']}",
            f"  Name      : {info['name']}",
            f"  Executable: {info['exe']}",
            f"  Command   : {info['cmdline']}",
            f"  CWD       : {info['cwd']}",
        ]

        if info["env"]:
            lines.append("  Environment:")
            for k, v in info["env"].items():
                # Truncate long values.
                v_disp = v[:80] + "..." if len(v) > 80 else v
                lines.append(f"    {k}={v_disp}")

        if info["libs"]:
            lines.append(f"  Dynamic libraries ({len(info['libs'])}):")
            for lib in info["libs"][:15]:
                lines.append(f"    {lib}")
            if len(info["libs"]) > 15:
                lines.append(f"    ... {len(info['libs']) - 15} more")

        results.append("\n".join(lines))

    return "\n\n".join(results)


# ════════════════════════════════════════════════════════
# Schema definitions registered by session.py.
# ════════════════════════════════════════════════════════

RECON_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "check_service",
            "description": (
                "P6 environment reconnaissance: inspect service process details for a given port.\n"
                "Returns PID, process name, executable path, command line, working directory,\n"
                "important environment variables (PATH/LD_LIBRARY_PATH/HTTP_PROXY, etc.),\n"
                "and linked dynamic libraries.\n"
                "Use during reconnaissance to confirm a target service environment instead of blind ps aux.\n"
                "Read-only with no side effects."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "port": {
                        "type": "integer",
                        "description": "Port number to inspect (1-65535).",
                    },
                },
                "required": ["port"],
            },
        },
    },
]
