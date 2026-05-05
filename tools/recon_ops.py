"""
tools/recon_ops.py — P6 环境嗅探工具
=====================================
tool_check_service(port): 通过 /proc 或 lsof 快速提取指定端口的进程信息。
返回：PID、进程名、运行路径、环境变量、引用的动态库。

安全约束：
  · 只读操作，不修改任何系统状态
  · 所有输出经过编码清洗 errors='ignore'
"""

import os
import re
import subprocess
from pathlib import Path


def _clean(text: str) -> str:
    """编码清洗，防止终端崩溃。"""
    if text is None:
        return ""
    return text.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")


def _find_pid_by_port_lsof(port: int) -> list[dict]:
    """使用 lsof 查找监听指定端口的进程。"""
    try:
        result = subprocess.run(
            ["lsof", "-i", f":{port}", "-sTCP:LISTEN", "-nP"],
            capture_output=True, text=True, timeout=5, errors="ignore",
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
    """通过 /proc/net/tcp + /proc/<pid>/fd 查找监听指定端口的进程（无需 lsof）。"""
    port_hex = f"{port:04X}"
    target_inodes = set()

    for proto in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(proto, "r", errors="ignore") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 10:
                        continue
                    # state=0A 表示 LISTEN
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

    # 遍历 /proc/<pid>/fd 查找匹配的 socket inode
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
    """从 /proc/<pid>/ 提取进程详细信息。"""
    info = {"pid": pid}
    base = Path(f"/proc/{pid}")

    # 进程名
    try:
        info["name"] = (base / "comm").read_text(errors="ignore").strip()
    except OSError:
        info["name"] = "?"

    # 运行路径（可执行文件）
    try:
        info["exe"] = os.readlink(str(base / "exe"))
    except OSError:
        info["exe"] = "?"

    # 命令行
    try:
        cmdline = (base / "cmdline").read_text(errors="ignore")
        info["cmdline"] = cmdline.replace("\x00", " ").strip()
    except OSError:
        info["cmdline"] = "?"

    # 工作目录
    try:
        info["cwd"] = os.readlink(str(base / "cwd"))
    except OSError:
        info["cwd"] = "?"

    # 环境变量（提取关键安全相关变量）
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

    # 引用的动态库（从 /proc/<pid>/maps 提取去重 .so 路径）
    try:
        maps_text = (base / "maps").read_text(errors="ignore")
        libs = set()
        for line in maps_text.splitlines():
            # 匹配路径中包含 .so 的条目
            match = re.search(r"\s+(/\S+\.so\S*)", line)
            if match:
                libs.add(match.group(1))
        info["libs"] = sorted(libs)[:30]  # 限制输出量
    except OSError:
        info["libs"] = []

    return info


def tool_check_service(args: dict) -> str:
    """
    环境嗅探工具：检查指定端口上运行的服务进程详情。
    通过 /proc 文件系统或 lsof 快速提取 PID、进程名、运行路径、
    环境变量以及引用的动态库。
    """
    port = args.get("port")
    if port is None:
        return "ERROR: port 参数不能为空"
    try:
        port = int(port)
    except ValueError:
        return f"ERROR: 无效端口号 '{port}'"
    if not (1 <= port <= 65535):
        return f"ERROR: 端口号 {port} 超出范围 (1-65535)"

    # 优先 lsof，降级到 /proc
    pids = _find_pid_by_port_lsof(port)
    method = "lsof"
    if not pids:
        pids = _find_pid_by_port_proc(port)
        method = "/proc"
    if not pids:
        return f"端口 {port} 上未发现监听进程"

    # 去重
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
            f"=== 端口 {port} 进程信息 (via {method}) ===",
            f"  PID       : {info['pid']}",
            f"  进程名    : {info['name']}",
            f"  可执行文件: {info['exe']}",
            f"  命令行    : {info['cmdline']}",
            f"  工作目录  : {info['cwd']}",
        ]

        if info["env"]:
            lines.append("  环境变量:")
            for k, v in info["env"].items():
                # 截断过长的值
                v_disp = v[:80] + "..." if len(v) > 80 else v
                lines.append(f"    {k}={v_disp}")

        if info["libs"]:
            lines.append(f"  动态库 ({len(info['libs'])} 个):")
            for lib in info["libs"][:15]:
                lines.append(f"    {lib}")
            if len(info["libs"]) > 15:
                lines.append(f"    ... 还有 {len(info['libs']) - 15} 个")

        results.append("\n".join(lines))

    return "\n\n".join(results)


# ════════════════════════════════════════════════════════
# Schema 定义（注册到 session.py）
# ════════════════════════════════════════════════════════

RECON_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "check_service",
            "description": (
                "P6 环境嗅探：检查指定端口上运行的服务进程详情。\n"
                "返回：PID、进程名、可执行文件路径、命令行、工作目录、\n"
                "关键环境变量（PATH/LD_LIBRARY_PATH/HTTP_PROXY 等）、\n"
                "引用的动态库列表。\n"
                "用途：在侦察阶段确认目标服务的运行环境，替代盲目执行 ps aux。\n"
                "无副作用，只读操作。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "port": {
                        "type": "integer",
                        "description": "要检查的端口号（1-65535）",
                    },
                },
                "required": ["port"],
            },
        },
    },
]
