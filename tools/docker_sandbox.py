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
# P4.1  安全工作区定义（One-Way Glass）
# ════════════════════════════════════════════════════════

SAFE_WORKSPACE = os.path.abspath(os.path.expanduser("~/.pawnlogic/workspace"))
os.makedirs(SAFE_WORKSPACE, exist_ok=True)


def _check_path_safety(host_path: str, mode: str) -> str:
    """
    校验挂载路径安全性。
    - 解析绝对路径（消除 .. 与软链接）
    - rw 模式：路径必须在 SAFE_WORKSPACE 内，否则抛出 PermissionError
    - ro 模式：仅做存在性检查，允许任意宿主机路径
    返回规范化的绝对路径字符串。
    """
    real = os.path.realpath(os.path.abspath(os.path.expanduser(host_path)))
    if mode == "rw":
        try:
            common = os.path.commonpath([real, SAFE_WORKSPACE])
        except ValueError:
            common = ""
        if common != SAFE_WORKSPACE:
            raise PermissionError(
                f"RW 权限仅限 /workspace 目录 ({SAFE_WORKSPACE})，"
                f"拒绝路径: {real}"
            )
    return real


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
        # 用户自定义挂载（P4.1）
        # mount_files 格式: {"./vuln": {"bind": "/target", "mode": "ro"}}
        for host_path, bind_spec in mount_files.items():
            if isinstance(bind_spec, str):
                # 兼容旧格式 {host: container_path}
                bind_spec = {"bind": bind_spec, "mode": "ro"}
            mount_mode = bind_spec.get("mode", "ro").lower()
            try:
                real_hp = _check_path_safety(host_path, mount_mode)
            except PermissionError as e:
                return f"ERROR: 挂载安全校验失败 — {e}"
            if os.path.exists(real_hp):
                volumes[real_hp] = {"bind": bind_spec["bind"], "mode": mount_mode}

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
            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="ignore")  # 编码清洗：丢弃非 UTF-8
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="ignore")  # 编码清洗：丢弃非 UTF-8
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
    network    = a.get("network", "none")
    mount_files = a.get("mount_files", {})  # P4.1: 挂载配置

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

        # 构建挂载卷（P4.1）
        volumes = {}
        for host_path, bind_spec in mount_files.items():
            if isinstance(bind_spec, str):
                bind_spec = {"bind": bind_spec, "mode": "ro"}
            mount_mode = bind_spec.get("mode", "ro").lower()
            try:
                real_hp = _check_path_safety(host_path, mount_mode)
            except PermissionError as e:
                return f"ERROR: 挂载安全校验失败 — {e}"
            if os.path.exists(real_hp):
                volumes[real_hp] = {"bind": bind_spec["bind"], "mode": mount_mode}

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
            volumes=volumes or None,   # P4.1：注入校验后的挂载
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
            result = output.decode("utf-8", errors="ignore")  # 编码清洗：丢弃非 UTF-8
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
# P4.2  气闸舱工具：tool_install_package（Airlock）
# ════════════════════════════════════════════════════════

_PKG_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


def tool_install_package(a: dict) -> str:
    """
    在持久化容器内安装软件包（气闸舱模式）。
    - 仅支持 apt / pip
    - 包名严格校验，防止命令注入
    - 临时接入 bridge 网络完成安装，finally 中强制断网
    """
    client = _get_docker_client()
    if not client:
        return f"ERROR: Docker 不可用 — {_docker_error}"

    container_name = a.get("container_name", "").strip()
    pkg_manager    = a.get("pkg_manager", "").lower().strip()
    packages       = a.get("packages", [])

    # ── 参数校验 ─────────────────────────────────────────
    if not container_name:
        return "ERROR: container_name 不能为空"
    if pkg_manager not in ("apt", "pip"):
        return "ERROR: pkg_manager 仅支持 apt 或 pip"
    if not packages:
        return "ERROR: packages 不能为空"

    invalid = [p for p in packages if not _PKG_NAME_RE.match(p)]
    if invalid:
        return f"ERROR: 包名包含非法字符，拒绝安装: {invalid}"

    # ── 获取容器 ─────────────────────────────────────────
    cid = _active_containers.get(container_name)
    if not cid:
        return f"ERROR: 未找到容器 '{container_name}'，请先 create"
    try:
        container = client.containers.get(cid)
    except Exception as e:
        return f"ERROR: 容器获取失败: {e}"

    # ── 构建安装命令 ──────────────────────────────────────
    pkg_str = " ".join(packages)
    if pkg_manager == "apt":
        install_cmd = f"apt-get update -qq && apt-get install -y --no-install-recommends {pkg_str}"
    else:
        install_cmd = f"pip install --quiet {pkg_str}"

    # ── 气闸舱：临时接网 → 安装 → 强制断网 ──────────────
    bridge_net = None
    _airlock_connected = False        # 标记：是否由本次气闸舱主动接入
    try:
        bridge_net = client.networks.get("bridge")

        # 检查容器是否已在 bridge 网络上（避免重复连接 + 误断用户手动网络）
        already_on_bridge = False
        try:
            net_attrs = bridge_net.attrs or {}
            containers_on_net = net_attrs.get("Containers", {})
            if container.id in containers_on_net:
                already_on_bridge = True
        except Exception:
            pass

        if already_on_bridge:
            print(c(GRAY, f"  ℹ [Airlock] 容器 '{container_name}' 已在 bridge 网络，跳过连接"))
        else:
            try:
                bridge_net.connect(container)
                _airlock_connected = True
                print(c(YELLOW, f"  🔌 [Airlock] 容器 '{container_name}' 临时接入 bridge 网络"))
            except Exception as conn_err:
                return f"ERROR: bridge 网络连接失败: {type(conn_err).__name__}: {conn_err}"

        exit_code, output = container.exec_run(
            cmd=["bash", "-c", install_cmd],
            stdout=True, stderr=True, demux=False,
        )
        result = output.decode("utf-8", errors="ignore") if output else ""  # 编码清洗
        status = "✓" if exit_code == 0 else f"✗ (exit {exit_code})"
        return (
            f"[Airlock {status}] {pkg_manager} install {pkg_str}\n"
            f"{result or '(无输出)'}"
        )

    except Exception as e:
        return f"ERROR: 安装过程异常: {type(e).__name__}: {e}"

    finally:
        # 仅断开由本次气闸舱主动接入的网络，不干扰用户手动开启的网络
        if bridge_net and _airlock_connected:
            try:
                bridge_net.disconnect(container, force=True)
                print(c(GREEN, f"  🔒 [Airlock] 容器 '{container_name}' 已强制断网"))
            except Exception as disc_err:
                print(c(RED, f"  ⚠ [Airlock] 断网失败（请手动检查）: {disc_err}"))


# ════════════════════════════════════════════════════════
# P4.3  资源回收：docker_prune_resources
# ════════════════════════════════════════════════════════

def docker_prune_resources() -> str:
    """
    清理停止的容器和悬空镜像，返回释放空间（MB）。
    """
    client = _get_docker_client()
    if not client:
        return f"ERROR: Docker 不可用 — {_docker_error}"

    freed_bytes = 0
    deleted_containers = []
    deleted_images = []
    errors = []

    # ── 清理停止的容器 ─────────────────────────────────
    try:
        container_result = client.containers.prune()
        freed_bytes += container_result.get("SpaceReclaimed", 0)
        deleted_containers = container_result.get("ContainersDeleted") or []
    except Exception as e:
        errors.append(f"容器清理失败: {type(e).__name__}: {e}")

    # ── 清理悬空镜像 ───────────────────────────────────
    try:
        image_result = client.images.prune(filters={"dangling": True})
        freed_bytes += image_result.get("SpaceReclaimed", 0)
        deleted_images = image_result.get("ImagesDeleted") or []
    except Exception as e:
        errors.append(f"镜像清理失败: {type(e).__name__}: {e}")

    freed_mb = freed_bytes / (1024 * 1024)

    if errors:
        return (
            f"⚠ 资源回收部分失败\n"
            f"  已删除容器: {len(deleted_containers)} 个\n"
            f"  已删除镜像层: {len(deleted_images)} 个\n"
            f"  释放空间: {freed_mb:.2f} MB\n"
            f"  错误: {'; '.join(errors)}"
        )

    return (
        f"✓ 资源回收完成\n"
        f"  已删除容器: {len(deleted_containers)} 个\n"
        f"  已删除镜像层: {len(deleted_images)} 个\n"
        f"  释放空间: {freed_mb:.2f} MB"
    )


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
    # ── P4.2: tool_install_package Schema ────────────────
    {
        "type": "function",
        "function": {
            "name": "tool_install_package",
            "description": (
                "气闸舱软件安装工具（Airlock）。\n"
                "在持久化容器内临时联网安装 apt/pip 包，安装完毕后立即强制断网。\n"
                "包名经严格正则校验，防止命令注入。\n"
                "仅对已通过 pwn_container create 创建的容器有效。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "container_name": {
                        "type": "string",
                        "description": "目标持久化容器名称（pwn_container create 时指定的 name）",
                    },
                    "pkg_manager": {
                        "type": "string",
                        "enum": ["apt", "pip"],
                        "description": "包管理器：apt 或 pip",
                    },
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要安装的包名列表，每个包名只允许 [a-zA-Z0-9_\\-\\.]+",
                    },
                },
                "required": ["container_name", "pkg_manager", "packages"],
            },
        },
    },
    # ── P4.3: docker_prune_resources Schema ──────────────
    {
        "type": "function",
        "function": {
            "name": "docker_prune_resources",
            "description": (
                "Docker 资源回收工具。\n"
                "清理所有已停止的容器和悬空（dangling）镜像，返回释放的磁盘空间（MB）。\n"
                "建议在完成 CTF 任务后或磁盘空间告急时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]
