"""
tools/docker_sandbox.py — P3: Docker 动态容器化沙箱
====================================================
提供两个核心工具：
  · run_code_docker — 在 Docker 容器中执行代码（一次性，执行后销毁）
  · pwn_container   — 持久化容器管理（create/exec/destroy）

设计原则：
  · Docker 不可用时静默降级，返回明确安装指引
  · 默认断网（network_mode="none"），防止 CTF flag 泄露
  · 资源限制：内存 512MB、CPU 0.5 核、PID 256
  · 文件双向挂载：宿主机 ↔ 容器

依赖：
  · pip install docker（可选，不强制）
  · 本地 Docker CE 运行时（dockerd）
"""

import os, re, time, shutil, tempfile
from pathlib import Path

from config import DYNAMIC_CONFIG, DANGEROUS_PATTERNS
from utils.ansi import c, YELLOW, GREEN, RED, GRAY, MAGENTA, BOLD

# ════════════════════════════════════════════════════════
# Docker 可用性检测（惰性初始化）
# ════════════════════════════════════════════════════════

_docker_client = None
_docker_error  = None
_docker_checked = False


def _get_docker_client():
    """惰性获取 Docker 客户端。不可用时返回 None。"""
    global _docker_client, _docker_error, _docker_checked
    if _docker_checked:
        return _docker_client
    _docker_checked = True
    try:
        import docker
        _docker_client = docker.from_env()
        _docker_client.ping()
        return _docker_client
    except ImportError:
        _docker_error = "未安装 docker-py。修复: pip install docker"
        return None
    except Exception as e:
        _docker_error = f"Docker 连接失败: {type(e).__name__}: {e}"
        return None


def docker_status() -> str:
    """返回 Docker 连接状态的格式化字符串。"""
    client = _get_docker_client()
    if client:
        try:
            info = client.info()
            containers = len(client.containers.list(all=True))
            images = len(client.images.list())
            return (
                f"  ✓ Docker 连接正常\n"
                f"  版本: {info.get('ServerVersion', '?')}\n"
                f"  容器: {containers} 个  |  镜像: {images} 个\n"
                f"  存储: {info.get('DockerRootDir', '?')}"
            )
        except Exception as e:
            return f"  ✗ Docker 连接异常: {e}"
    else:
        return f"  ✗ Docker 不可用: {_docker_error}"


# ════════════════════════════════════════════════════════
# 镜像注册表（config.py 中也可定义，此处为本地副本）
# ════════════════════════════════════════════════════════

DEFAULT_DOCKER_IMAGES = {
    "pwndocker":  "skysider/pwndocker",
    "ubuntu18":   "ubuntu:18.04",
    "ubuntu22":   "ubuntu:22.04",
    "kali":       "kalilinux/kali-rolling",
    "python":     "python:3.12-slim",
    "gcc":        "gcc:latest",
}


def _resolve_image(name: str) -> str:
    """将别名解析为完整镜像名。"""
    if name in DEFAULT_DOCKER_IMAGES:
        return DEFAULT_DOCKER_IMAGES[name]
    if "/" in name or ":" in name:
        return name  # 已经是完整镜像名
    return name


# ════════════════════════════════════════════════════════
# 安全检查
# ════════════════════════════════════════════════════════

def _check_docker_cmd(cmd: str) -> str | None:
    """检查命令是否匹配危险模式。返回 None 表示安全。"""
    for pat in DANGEROUS_PATTERNS:
        if re.search(pat, cmd):
            return f"SECURITY BLOCK: 命令匹配危险模式 '{pat}'"
    return None


# ════════════════════════════════════════════════════════
# run_code_docker — 一次性容器执行
# ════════════════════════════════════════════════════════

def tool_run_code_docker(a: dict) -> str:
    """
    在 Docker 容器中执行代码，执行完毕后自动销毁容器。

    Parameters
    ----------
    language : str
        编程语言（python / c / cpp / bash / javascript / rust / go / java）
    code : str
        要执行的源代码
    image : str
        Docker 镜像名或别名（默认 pwndocker）
    timeout : int
        执行超时秒数（默认 30）
    mount_files : dict
        文件挂载映射 {宿主机路径: 容器内路径}
    network : str
        网络模式：none（默认断网）/ bridge / host
    stdin : str
        传给程序的标准输入
    install_deps : str
        空格分隔的 pip 包名（仅 Python）

    Returns
    -------
    str — 执行结果（stdout + stderr）+ 容器销毁状态
    """
    client = _get_docker_client()
    if not client:
        return (
            f"ERROR: Docker 不可用 — {_docker_error}\n"
            f"请确保 Docker CE 已启动: sudo systemctl start docker\n"
            f"并安装 Python SDK: pip install docker"
        )

    language     = a.get("language", "python").lower().strip()
    code         = a.get("code", "")
    raw_image    = a.get("image", "")
    timeout      = int(a.get("timeout", 30))
    mount_files  = a.get("mount_files", {})
    network      = a.get("network", "none")
    stdin_data   = a.get("stdin", "")
    install_deps = a.get("install_deps", "").strip()

    if not code:
        return "ERROR: code 参数不能为空"

    # 安全检查
    err = _check_docker_cmd(code)
    if err:
        return err

    # ── 语言 → 文件扩展名 + 执行命令 ────────────────────
    _LANG_MAP = {
        "python":     (".py",  "python3 /code/main.py"),
        "c":          (".c",   "gcc -O0 -g /code/main.c -o /code/main -lm && /code/main"),
        "cpp":        (".cpp", "g++ -O0 -g -std=c++17 /code/main.cpp -o /code/main && /code/main"),
        "bash":       (".sh",  "bash /code/main.sh"),
        "javascript": (".js",  "node /code/main.js"),
        "rust":       (".rs",  "rustc /code/main.rs -o /code/main && /code/main"),
        "go":         (".go",  "cd /code && go run main.go"),
        "java":       (".java", "cd /code && javac Main.java && java -cp . Main"),
    }

    if language not in _LANG_MAP:
        return f"ERROR: 不支持的语言 '{language}'。支持: {', '.join(_LANG_MAP.keys())}"

    ext, run_cmd = _LANG_MAP[language]

    # ── 智能镜像选择 ─────────────────────────────────────
    # 未指定 image 时，根据语言自动选择最合适的镜像
    _LANG_IMAGE_MAP = {
        "python":     "python",
        "c":          "gcc",
        "cpp":        "gcc",
        "bash":       "ubuntu22",
        "javascript": "ubuntu22",
        "rust":       "ubuntu22",
        "go":         "ubuntu22",
        "java":       "ubuntu22",
    }
    if raw_image:
        image_name = _resolve_image(raw_image)
    else:
        image_name = _resolve_image(_LANG_IMAGE_MAP.get(language, "pwndocker"))

    # ── Python 依赖安装 ──────────────────────────────────
    if language == "python" and install_deps:
        pkgs = install_deps.split()
        run_cmd = f"pip install {' '.join(pkgs)} -q && {run_cmd}"

    # ── 准备临时目录 + 写入代码 ──────────────────────────
    with tempfile.TemporaryDirectory(prefix="pawn_docker_") as tmpdir:
        code_file = os.path.join(tmpdir, f"main{ext}")
        with open(code_file, "w", encoding="utf-8") as f:
            f.write(code)

        # ── 构建挂载卷 ───────────────────────────────────
        volumes = {
            tmpdir: {"bind": "/code", "mode": "rw"},
        }
        # 用户自定义挂载
        for host_path, container_path in mount_files.items():
            hp = os.path.expanduser(host_path)
            if os.path.exists(hp):
                volumes[hp] = {"bind": container_path, "mode": "rw"}

        # ── stdin 文件 ───────────────────────────────────
        stdin_file = None
        if stdin_data:
            stdin_file = os.path.join(tmpdir, "stdin.txt")
            with open(stdin_file, "w", encoding="utf-8") as f:
                f.write(stdin_data)

        # ── 完整执行命令 ─────────────────────────────────
        full_cmd = f"cd /code && {run_cmd}"
        if stdin_file:
            full_cmd = f"cd /code && {run_cmd} < /code/stdin.txt"

        print(c(MAGENTA, f"  🐳 [docker] {image_name} → {language}"))
        print(c(GRAY,    f"  网络: {network}  超时: {timeout}s  镜像: {image_name}"))

        # ── 拉取镜像（如果本地不存在）──────────────────
        try:
            client.images.get(image_name)
        except Exception:
            print(c(YELLOW, f"  📥 正在拉取轻量级镜像 {image_name}，请稍候..."))
            try:
                client.images.pull(image_name)
                print(c(GREEN, f"  ✓ 镜像 {image_name} 拉取完成"))
            except Exception as e:
                return (
                    f"ERROR: 镜像 '{image_name}' 拉取失败: {e}\n"
                    f"可能原因: 网络不通或镜像名错误。\n"
                    f"手动拉取: docker pull {image_name}"
                )

        # ── 创建并运行容器 ───────────────────────────────
        container = None
        try:
            container = client.containers.run(
                image=image_name,
                command=["bash", "-c", full_cmd],
                volumes=volumes,
                network_mode=network,
                mem_limit="512m",
                cpu_period=100000,
                cpu_quota=50000,       # 0.5 核
                pids_limit=256,
                detach=True,
                stderr=True,
                stdout=True,
                remove=False,          # 先不自动删除，等读完输出
            )

            # 等待完成（带超时）
            result = container.wait(timeout=timeout)
            exit_code = result.get("StatusCode", -1)

            # 读取输出
            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")
            output = stdout + stderr

        except Exception as e:
            if "timed out" in str(e).lower() or "timeout" in str(e).lower():
                try:
                    container.kill()
                except Exception:
                    pass
                return f"[执行超时 {timeout}s] 容器已被销毁"
            return f"ERROR: 容器执行异常: {type(e).__name__}: {e}"
        finally:
            # 确保容器被清理
            if container:
                try:
                    container.remove(force=True)
                except Exception:
                    pass

        # ── 格式化输出 ───────────────────────────────────
        limit = DYNAMIC_CONFIG["tool_max_chars"]
        if len(output) > limit:
            half = limit // 2
            output = output[:half] + f"\n...[截断至 {limit} 字符]...\n" + output[-half // 4:]

        status = "✓ 成功" if exit_code == 0 else f"✗ 失败 (exit {exit_code})"
        header = f"[run_code_docker — {status} | 镜像: {image_name} | 网络: {network}]\n"
        return header + (output or "(无输出)")


# ════════════════════════════════════════════════════════
# pwn_container — 持久化容器管理
# ════════════════════════════════════════════════════════

# 运行中的持久化容器注册表（进程内）
_active_containers: dict[str, object] = {}


def tool_pwn_container(a: dict) -> str:
    """
    持久化容器管理工具。

    Actions:
      · create  — 创建并启动一个持久化容器（可 attach 多次 exec）
      · exec    — 在运行中的容器内执行命令
      · destroy — 停止并销毁指定容器
      · list    — 列出所有活跃的持久化容器

    Parameters
    ----------
    action : str
        create / exec / destroy / list
    name : str
        容器名称标识（用于 create/exec/destroy）
    image : str
        Docker 镜像（仅 create 时需要，默认 pwndocker）
    command : str
        要执行的命令（exec 时需要）
    timeout : int
        命令执行超时秒数（exec 时，默认 30）
    network : str
        网络模式（create 时，默认 none）

    Returns
    -------
    str — 操作结果
    """
    client = _get_docker_client()
    if not client:
        return f"ERROR: Docker 不可用 — {_docker_error}"

    action  = a.get("action", "").lower().strip()
    name    = a.get("name", "").strip()
    image   = _resolve_image(a.get("image", "pwndocker"))
    command = a.get("command", "").strip()
    timeout = int(a.get("timeout", 30))
    network = a.get("network", "none")

    if action == "list":
        if not _active_containers:
            return "  (无活跃的持久化容器)"
        lines = [c(BOLD, "\n  活跃的持久化容器：")]
        for cname, cid in _active_containers.items():
            try:
                ctr = client.containers.get(cid)
                status = ctr.status
                lines.append(f"  {c(CYAN, cname):20} {c(GREEN, status):12} {c(GRAY, cid[:12])}")
            except Exception:
                lines.append(f"  {c(RED, cname):20} {'已丢失':12}")
        return "\n".join(lines)

    if action == "create":
        if not name:
            return "ERROR: create 需要 name 参数"
        if name in _active_containers:
            return f"ERROR: 容器 '{name}' 已存在。先 destroy 或使用其他名称。"

        # 拉取镜像
        try:
            client.images.get(image)
        except Exception:
            print(c(YELLOW, f"  📥 正在拉取轻量级镜像 {image}，请稍候..."))
            try:
                client.images.pull(image)
                print(c(GREEN, f"  ✓ 镜像 {image} 拉取完成"))
            except Exception as e:
                return (
                    f"ERROR: 镜像 '{image}' 拉取失败: {e}\n"
                    f"手动拉取: docker pull {image}"
                )

        print(c(MAGENTA, f"  🐳 [create] {name} ← {image}"))

        container = client.containers.run(
            image=image,
            command="sleep infinity",
            network_mode=network,
            mem_limit="512m",
            cpu_period=100000,
            cpu_quota=50000,
            pids_limit=256,
            detach=True,
            name=f"pawn_{name}",
            labels={"pawn": "true", "pawn_name": name},
        )

        _active_containers[name] = container.id
        return (
            f"✓ 容器 '{name}' 已创建并启动\n"
            f"  ID: {container.id[:12]}\n"
            f"  镜像: {image}\n"
            f"  网络: {network}\n"
            f"  用 /docker exec {name} <cmd> 执行命令"
        )

    if action == "exec":
        if not name:
            return "ERROR: exec 需要 name 参数"
        if not command:
            return "ERROR: exec 需要 command 参数"

        # 安全检查
        err = _check_docker_cmd(command)
        if err:
            return err

        cid = _active_containers.get(name)
        if not cid:
            return f"ERROR: 未找到容器 '{name}'。用 /docker list 查看活跃容器。"

        try:
            container = client.containers.get(cid)
        except Exception:
            _active_containers.pop(name, None)
            return f"ERROR: 容器 '{name}' 已不存在（可能已被外部销毁）"

        print(c(MAGENTA, f"  🐳 [exec] {name} $ {command[:80]}"))

        try:
            exit_code, output = container.exec_run(
                cmd=["bash", "-c", command],
                stdout=True,
                stderr=True,
                demux=False,
            )
            result = output.decode("utf-8", errors="replace")
        except Exception as e:
            return f"ERROR: exec 失败: {type(e).__name__}: {e}"

        limit = DYNAMIC_CONFIG["tool_max_chars"]
        if len(result) > limit:
            half = limit // 2
            result = result[:half] + f"\n...[截断至 {limit} 字符]...\n" + result[-half // 4:]

        status = "✓" if exit_code == 0 else f"✗ (exit {exit_code})"
        return f"[{status}] {name} $ {command}\n{result or '(无输出)'}"

    if action == "destroy":
        if not name:
            return "ERROR: destroy 需要 name 参数"

        cid = _active_containers.pop(name, None)
        if not cid:
            return f"ERROR: 未找到容器 '{name}'"

        try:
            container = client.containers.get(cid)
            container.remove(force=True)
            return f"✓ 容器 '{name}' 已销毁"
        except Exception as e:
            return f"⚠ 容器 '{name}' 销毁时异常（可能已不存在）: {e}"

    return f"ERROR: 未知 action '{action}'。可用: create / exec / destroy / list"


# ════════════════════════════════════════════════════════
# Schema 定义
# ════════════════════════════════════════════════════════

DOCKER_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "run_code_docker",
            "description": (
                "在 Docker 容器中执行代码（一次性，执行后自动销毁）。\n"
                "适用场景：Pwn 靶机 exploit 测试、多版本 libc 环境验证、隔离沙箱执行。\n"
                "默认断网（network=none），防止 CTF flag 泄露。\n"
                "资源限制：内存 512MB、CPU 0.5 核、PID 256。\n"
                "支持语言：python / c / cpp / bash / javascript / rust / go / java。\n"
                "如果 Docker 不可用，会返回明确的安装指引。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "description": "编程语言（默认 python）",
                    },
                    "code": {
                        "type": "string",
                        "description": "要执行的源代码",
                    },
                    "image": {
                        "type": "string",
                        "description": (
                            "执行镜像。纯 Python 逻辑指定 'python'，"
                            "Pwn 题目分析使用 'pwndocker'。"
                            "未指定时根据语言自动选择。"
                            "可用别名: pwndocker / ubuntu18 / ubuntu22 / kali / python / gcc"
                        ),
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "执行超时秒数（默认 30）",
                    },
                    "mount_files": {
                        "type": "object",
                        "description": "文件挂载 {宿主机路径: 容器内路径}",
                    },
                    "network": {
                        "type": "string",
                        "description": "网络模式：none（默认断网）/ bridge / host",
                    },
                    "stdin": {
                        "type": "string",
                        "description": "传给程序的标准输入",
                    },
                    "install_deps": {
                        "type": "string",
                        "description": "空格分隔的 pip 包名（仅 Python）",
                    },
                },
                "required": ["language", "code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pwn_container",
            "description": (
                "持久化容器管理工具。用于 CTF 靶机环境的长期运行。\n"
                "Actions:\n"
                "  create  — 创建并启动一个持久化容器\n"
                "  exec    — 在运行中的容器内执行命令\n"
                "  destroy — 停止并销毁指定容器\n"
                "  list    — 列出所有活跃的持久化容器\n"
                "适用场景：需要多次交互的 Pwn 调试、多步 exploit 验证。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "exec", "destroy", "list"],
                        "description": "操作类型",
                    },
                    "name": {
                        "type": "string",
                        "description": "容器名称标识",
                    },
                    "image": {
                        "type": "string",
                        "description": "Docker 镜像（仅 create，默认 pwndocker）",
                    },
                    "command": {
                        "type": "string",
                        "description": "要执行的命令（exec 时需要）",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "命令超时秒数（exec 时，默认 30）",
                    },
                    "network": {
                        "type": "string",
                        "description": "网络模式（create 时，默认 none）",
                    },
                },
                "required": ["action"],
            },
        },
    },
]
