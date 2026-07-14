"""
tools/docker_sandbox.py - P3 dynamic Docker sandbox.

Core tools:
  - run_code_docker: run code in a disposable Docker container.
  - pwn_container: manage persistent containers (create/exec/destroy).

Design notes:
  - Degrades clearly when Docker is unavailable.
  - Defaults to network_mode="none" to prevent CTF flag leakage.
  - Resource limits: 512 MB memory, 0.5 CPU, 256 PIDs.
  - Supports host/container file mounts.

Dependencies:
  - pip install docker (optional).
  - Local Docker CE runtime (dockerd).
"""

import os, re, tempfile

from config import DANGEROUS_PATTERNS, READ_BLACKLIST, WORKSPACE_DIR
from core.state import state as _runtime_state, runtime_config
from core.trust import TrustBoundaryKind, trust_notice_for_boundary
from tools.docker_plan import build_docker_execution_plan
from utils.ansi import c, YELLOW, GREEN, RED, GRAY, CYAN, MAGENTA, BOLD

# ════════════════════════════════════════════════════════
# P4.1 safe workspace definition (one-way glass).
# ════════════════════════════════════════════════════════

SAFE_WORKSPACE = os.path.abspath(os.path.expanduser(WORKSPACE_DIR))
os.makedirs(SAFE_WORKSPACE, exist_ok=True)


def _is_under(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def _is_sensitive_host_path(path: str) -> bool:
    if os.path.basename(path) == "docker.sock":
        return True
    for blocked in READ_BLACKLIST:
        blocked_real = os.path.realpath(os.path.abspath(os.path.expanduser(blocked)))
        if _is_under(path, blocked_real):
            return True
    return False


def _check_path_safety(host_path: str, mode: str, *, allow_host_read_mount: bool = False) -> str:
    """
    Validate mount path safety.
    - Resolve absolute paths, removing .. and symlinks.
    - rw mode: path must be inside SAFE_WORKSPACE or PermissionError is raised.
    - ro mode: path must also be inside SAFE_WORKSPACE by default. Explicit
      allow_host_read_mount permits outside read-only challenge files, but
      credential paths and docker.sock remain denied.
    Returns the canonical absolute path string.
    """
    mode = str(mode or "ro").lower()
    if mode not in {"ro", "rw"}:
        raise PermissionError("mount mode must be 'ro' or 'rw'")
    real = os.path.realpath(os.path.abspath(os.path.expanduser(host_path)))
    in_workspace = _is_under(real, SAFE_WORKSPACE)
    if _is_sensitive_host_path(real):
        raise PermissionError(f"mount path may contain credentials or host control sockets: {real}")
    if mode == "rw" and not in_workspace:
        raise PermissionError(
            f"RW mode is limited to the workspace directory ({SAFE_WORKSPACE}); "
            f"denied path: {real}"
        )
    if mode == "ro" and not in_workspace and not allow_host_read_mount:
        raise PermissionError(
            f"RO mounts are limited to the workspace directory ({SAFE_WORKSPACE}) by default; "
            "set allow_host_read_mount=true only for trusted read-only challenge files. "
            f"denied path: {real}"
        )
    return real


# ════════════════════════════════════════════════════════
# Docker availability check with lazy initialization.
# ════════════════════════════════════════════════════════

_docker_client = None
_docker_error  = None
_docker_checked = False


def _get_docker_client():
    """Lazily get the Docker client. Returns None when unavailable."""
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
        _docker_error = "docker-py is not installed. Fix: pip install docker"
        return None
    except Exception as e:
        _docker_error = f"Docker connection failed: {type(e).__name__}: {e}"
        return None


def docker_status() -> str:
    """Return formatted Docker connection status."""
    client = _get_docker_client()
    if client:
        try:
            info = client.info()
            containers = len(client.containers.list(all=True))
            images = len(client.images.list())
            return (
                f"  OK Docker connected\n"
                f"  Version: {info.get('ServerVersion', '?')}\n"
                f"  Containers: {containers}  |  Images: {images}\n"
                f"  Storage: {info.get('DockerRootDir', '?')}"
            )
        except Exception as e:
            return f"  ERROR Docker connection error: {e}"
    else:
        return f"  ERROR Docker unavailable: {_docker_error}"


# ════════════════════════════════════════════════════════
# Image registry. config.py may also define this; this is the local copy.
# ════════════════════════════════════════════════════════

DEFAULT_DOCKER_IMAGES = {
    "pwndocker":  "skysider/pwndocker",
    "ubuntu18":   "ubuntu:18.04",
    "ubuntu22":   "ubuntu:22.04",
    "kali":       "kalilinux/kali-rolling",
    "python":     "python:3.12-slim",
    "gcc":        "gcc:latest",
}

_TRUTHY_POLICY_VALUES = {"1", "true", "yes", "on"}
_RISKY_NETWORK_MODES = {"bridge", "host"}


def _policy_truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in _TRUTHY_POLICY_VALUES


def _docker_policy_enabled(arg_value: object, env_name: str) -> bool:
    return _policy_truthy(arg_value) or _policy_truthy(os.environ.get(env_name))


def _check_network_policy(a: dict, network: str) -> str | None:
    mode = (network or "none").strip().lower()
    if mode not in _RISKY_NETWORK_MODES:
        return None
    if _docker_policy_enabled(a.get("allow_network"), "PAWNLOGIC_DOCKER_ALLOW_NETWORK"):
        return None
    return (
        f"SECURITY BLOCK: Docker network='{mode}' requires explicit approval. "
        "Set allow_network=true for this tool call or PAWNLOGIC_DOCKER_ALLOW_NETWORK=true."
    )


def _check_auto_pull_policy(a: dict, image: str) -> str | None:
    if _docker_policy_enabled(a.get("allow_auto_pull"), "PAWNLOGIC_DOCKER_ALLOW_AUTO_PULL"):
        return None
    return (
        f"SECURITY BLOCK: Docker image '{image}' is not available locally and automatic "
        "pull is disabled. Pull it manually with /docker pull, set allow_auto_pull=true "
        "for this tool call, or set PAWNLOGIC_DOCKER_ALLOW_AUTO_PULL=true."
    )


def _resolve_image(name: str) -> str:
    """Resolve an alias to a full Docker image name."""
    if name in DEFAULT_DOCKER_IMAGES:
        return DEFAULT_DOCKER_IMAGES[name]
    if "/" in name or ":" in name:
        return name
    return name


# ════════════════════════════════════════════════════════
# Security checks.
# ════════════════════════════════════════════════════════

def _check_docker_cmd(cmd: str) -> str | None:
    """Check whether a command matches dangerous patterns. None means safe."""
    for pat in DANGEROUS_PATTERNS:
        if re.search(pat, cmd):
            return f"SECURITY BLOCK: command matches dangerous pattern '{pat}'"
    return None


def _user_mode() -> bool:
    return bool(_runtime_state.user_mode)


# ════════════════════════════════════════════════════════
# run_code_docker: disposable container execution.
# ════════════════════════════════════════════════════════

def tool_run_code_docker(a: dict) -> str:
    """
    Run code in a Docker container and destroy the container afterward.

    Parameters
    ----------
    language : str
        Programming language (python / c / cpp / bash / javascript / rust / go / java).
    code : str
        Source code to execute.
    image : str
        Docker image name or alias (default: pwndocker).
    timeout : int
        Execution timeout seconds (default 30).
    mount_files : dict
        File mount mapping {host path: container path}.
    network : str
        Network mode: none (default) / bridge / host.
    stdin : str
        Standard input passed to the program.
    install_deps : str
        Space-separated pip package names for Python only.

    Returns
    -------
    str: execution result (stdout + stderr) plus container cleanup status.
    """
    code         = a.get("code", "")
    mount_files  = a.get("mount_files", {})
    stdin_data   = a.get("stdin", "")
    plan, error = build_docker_execution_plan(
        a,
        resolve_image=_resolve_image,
        network_error=_check_network_policy,
        command_error=_check_docker_cmd,
    )
    if error or plan is None:
        return error or "ERROR: invalid Docker execution plan"
    language = plan.language
    timeout = plan.timeout_seconds
    network = plan.network
    ext = plan.extension
    run_cmd = plan.command
    image_name = plan.image

    client = _get_docker_client()
    if not client:
        return (
            f"ERROR: Docker unavailable - {_docker_error}\n"
            f"Ensure Docker CE is running: sudo systemctl start docker\n"
            f"Install the Python SDK: pip install docker"
        )

    # Prepare temp directory and write code.
    with tempfile.TemporaryDirectory(prefix="pawn_docker_") as tmpdir:
        code_file = os.path.join(tmpdir, f"main{ext}")
        with open(code_file, "w", encoding="utf-8") as f:
            f.write(code)

        # Build mount volumes.
        volumes = {
            tmpdir: {"bind": "/code", "mode": "rw"},
        }
        # User-defined mounts (P4.1).
        # mount_files format: {"./vuln": {"bind": "/target", "mode": "ro"}}
        allow_host_read_mount = _docker_policy_enabled(
            a.get("allow_host_read_mount"), "PAWNLOGIC_DOCKER_ALLOW_HOST_READ_MOUNT"
        )
        for host_path, bind_spec in mount_files.items():
            if isinstance(bind_spec, str):
                # Backward-compatible format: {host: container_path}.
                bind_spec = {"bind": bind_spec, "mode": "ro"}
            mount_mode = bind_spec.get("mode", "ro").lower()
            try:
                real_hp = _check_path_safety(
                    host_path,
                    mount_mode,
                    allow_host_read_mount=allow_host_read_mount,
                )
            except PermissionError as e:
                return f"ERROR: mount safety check failed - {e}"
            if os.path.exists(real_hp):
                volumes[real_hp] = {"bind": bind_spec["bind"], "mode": mount_mode}

        # stdin file.
        stdin_file = None
        if stdin_data:
            stdin_file = os.path.join(tmpdir, "stdin.txt")
            with open(stdin_file, "w", encoding="utf-8") as f:
                f.write(stdin_data)

        # Full execution command.
        full_cmd = f"cd /code && {run_cmd}"
        if stdin_file:
            full_cmd = f"cd /code && {run_cmd} < /code/stdin.txt"

        print(c(MAGENTA, f"  [docker] {image_name} -> {language}"))
        print(c(GRAY,    f"  Network: {network}  Timeout: {timeout}s  Image: {image_name}"))

        # Pull image if it is not available locally.
        try:
            client.images.get(image_name)
        except Exception:
            err = _check_auto_pull_policy(a, image_name)
            if err:
                return err
            print(c(YELLOW, f"  Pulling lightweight image {image_name}; please wait..."))
            try:
                client.images.pull(image_name)
                print(c(GREEN, f"  Image {image_name} pulled"))
            except Exception as e:
                return (
                    f"ERROR: failed to pull image '{image_name}': {e}\n"
                    f"Possible causes: network unavailable or invalid image name.\n"
                    f"Manual pull: docker pull {image_name}"
                )

        # Create and run container.
        container = None
        try:
            container = client.containers.run(
                image=image_name,
                command=["bash", "-c", full_cmd],
                volumes=volumes,
                network_mode=network,
                mem_limit="512m",
                cpu_period=100000,
                cpu_quota=50000,
                pids_limit=256,
                detach=True,
                stderr=True,
                stdout=True,
                remove=False,
            )

            # Wait for completion with timeout.
            result = container.wait(timeout=timeout)
            exit_code = result.get("StatusCode", -1)

            # Read output.
            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="ignore")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="ignore")
            output = stdout + stderr

        except Exception as e:
            if "timed out" in str(e).lower() or "timeout" in str(e).lower():
                try:
                    container.kill()
                except Exception:
                    pass
                return f"[execution timed out after {timeout}s] container destroyed"
            return f"ERROR: container execution failed: {type(e).__name__}: {e}"
        finally:
            # Ensure container cleanup.
            if container:
                try:
                    container.remove(force=True)
                except Exception:
                    pass

        # Format output.
        limit = runtime_config()["tool_max_chars"]
        if len(output) > limit:
            half = limit // 2
            output = output[:half] + f"\n...[truncated to {limit} chars]...\n" + output[-half // 4:]

        status = "OK" if exit_code == 0 else f"FAILED (exit {exit_code})"
        header = f"[run_code_docker - {status} | image: {image_name} | network: {network}]\n"
        return header + (output or "(no output)")


# ════════════════════════════════════════════════════════
# pwn_container: persistent container management.
# ════════════════════════════════════════════════════════

# In-process registry for running persistent containers.
_active_containers: dict[str, object] = {}


def tool_pwn_container(a: dict) -> str:
    """
    Persistent container management tool.

    Actions:
      - create: create and start a persistent container.
      - exec: run a command inside a running container.
      - destroy: stop and destroy a container.
      - list: list active persistent containers.

    Parameters
    ----------
    action : str
        create / exec / destroy / list
    name : str
        Container name identifier for create/exec/destroy.
    image : str
        Docker image for create, default pwndocker.
    command : str
        Command to execute for exec.
    timeout : int
        Command timeout seconds for exec, default 30.
    network : str
        Network mode for create, default none.

    Returns
    -------
    str: operation result.
    """
    action  = a.get("action", "").lower().strip()
    name    = a.get("name", "").strip()
    image   = _resolve_image(a.get("image", "pwndocker"))
    command = a.get("command", "").strip()
    network    = (a.get("network", "none") or "none").strip().lower()
    mount_files = a.get("mount_files", {})

    if action == "create":
        err = _check_network_policy(a, network)
        if err:
            return err

    client = _get_docker_client()
    if not client:
        return f"ERROR: Docker unavailable - {_docker_error}"

    if action == "list":
        if not _active_containers:
            return "  (no active persistent containers)"
        lines = [c(BOLD, "\n  Active persistent containers:")]
        for cname, cid in _active_containers.items():
            try:
                ctr = client.containers.get(cid)
                status = ctr.status
                lines.append(f"  {c(CYAN, cname):20} {c(GREEN, status):12} {c(GRAY, cid[:12])}")
            except Exception:
                lines.append(f"  {c(RED, cname):20} {'missing':12}")
        return "\n".join(lines)

    if action == "create":
        if not name:
            return "ERROR: create requires a name parameter"
        if name in _active_containers:
            return f"ERROR: container '{name}' already exists. Destroy it first or use another name."

        # Pull image.
        try:
            client.images.get(image)
        except Exception:
            err = _check_auto_pull_policy(a, image)
            if err:
                return err
            print(c(YELLOW, f"  Pulling lightweight image {image}; please wait..."))
            try:
                client.images.pull(image)
                print(c(GREEN, f"  Image {image} pulled"))
            except Exception as e:
                return (
                    f"ERROR: failed to pull image '{image}': {e}\n"
                    f"Manual pull: docker pull {image}"
                )

        print(c(MAGENTA, f"  [create] {name} <- {image}"))

        # Build mount volumes (P4.1).
        volumes = {}
        allow_host_read_mount = _docker_policy_enabled(
            a.get("allow_host_read_mount"), "PAWNLOGIC_DOCKER_ALLOW_HOST_READ_MOUNT"
        )
        for host_path, bind_spec in mount_files.items():
            if isinstance(bind_spec, str):
                bind_spec = {"bind": bind_spec, "mode": "ro"}
            mount_mode = bind_spec.get("mode", "ro").lower()
            try:
                real_hp = _check_path_safety(
                    host_path,
                    mount_mode,
                    allow_host_read_mount=allow_host_read_mount,
                )
            except PermissionError as e:
                return f"ERROR: mount safety check failed - {e}"
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
            volumes=volumes or None,
        )

        _active_containers[name] = container.id
        return (
            f"OK: container '{name}' created and started\n"
            f"  ID: {container.id[:12]}\n"
            f"  Image: {image}\n"
            f"  Network: {network}\n"
            f"  Run commands with /docker exec {name} <cmd>"
        )

    if action == "exec":
        if not name:
            return "ERROR: exec requires a name parameter"
        if not command:
            return "ERROR: exec requires a command parameter"

        # Security checks.
        err = _check_docker_cmd(command)
        if err:
            return err

        cid = _active_containers.get(name)
        if not cid:
            return f"ERROR: container '{name}' not found. Use /docker list to view active containers."

        try:
            container = client.containers.get(cid)
        except Exception:
            _active_containers.pop(name, None)
            return f"ERROR: container '{name}' no longer exists; it may have been removed externally."

        print(c(MAGENTA, f"  [exec] {name} $ {command[:80]}"))
        if _user_mode():
            print(c(YELLOW, trust_notice_for_boundary(TrustBoundaryKind.CONTAINER_EXEC)))

        try:
            exit_code, output = container.exec_run(
                cmd=["bash", "-c", command],
                stdout=True,
                stderr=True,
                demux=False,
            )
            result = output.decode("utf-8", errors="ignore")
        except Exception as e:
            return f"ERROR: exec failed: {type(e).__name__}: {e}"

        limit = runtime_config()["tool_max_chars"]
        if len(result) > limit:
            half = limit // 2
            result = result[:half] + f"\n...[truncated to {limit} chars]...\n" + result[-half // 4:]

        status = "✓" if exit_code == 0 else f"✗ (exit {exit_code})"
        return f"[{status}] {name} $ {command}\n{result or '(no output)'}"

    if action == "destroy":
        if not name:
            return "ERROR: destroy requires a name parameter"

        cid = _active_containers.pop(name, None)
        if not cid:
            return f"ERROR: container '{name}' not found"

        try:
            container = client.containers.get(cid)
            container.remove(force=True)
            return f"OK: container '{name}' destroyed"
        except Exception as e:
            return f"WARNING: error while destroying container '{name}' (it may no longer exist): {e}"

    return f"ERROR: unknown action '{action}'. Available: create / exec / destroy / list"


# ════════════════════════════════════════════════════════
# P4.2 Airlock package installation tool.
# ════════════════════════════════════════════════════════

_PKG_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


def tool_install_package(a: dict) -> str:
    """
    Install packages inside a persistent container in Airlock mode.
    - Supports apt and pip only.
    - Strict package-name validation prevents command injection.
    - Temporarily connects to bridge for installation, then disconnects in finally.
    """
    client = _get_docker_client()
    if not client:
        return f"ERROR: Docker unavailable - {_docker_error}"

    container_name = a.get("container_name", "").strip()
    pkg_manager    = a.get("pkg_manager", "").lower().strip()
    packages       = a.get("packages", [])

    # Parameter validation.
    if not container_name:
        return "ERROR: container_name is required"
    if pkg_manager not in ("apt", "pip"):
        return "ERROR: pkg_manager supports only apt or pip"
    if not packages:
        return "ERROR: packages is required"

    invalid = [p for p in packages if not _PKG_NAME_RE.match(p)]
    if invalid:
        return f"ERROR: package names contain invalid characters; install denied: {invalid}"

    # Get container.
    cid = _active_containers.get(container_name)
    if not cid:
        return f"ERROR: container '{container_name}' not found; create it first"
    try:
        container = client.containers.get(cid)
    except Exception as e:
        return f"ERROR: failed to get container: {e}"

    # Build install command.
    pkg_str = " ".join(packages)
    if pkg_manager == "apt":
        install_cmd = f"apt-get update -qq && apt-get install -y --no-install-recommends {pkg_str}"
    else:
        install_cmd = f"pip install --quiet {pkg_str}"

    # Airlock: temporarily connect -> install -> force disconnect.
    bridge_net = None
    _airlock_connected = False
    try:
        bridge_net = client.networks.get("bridge")

        # Check whether the container is already on bridge to avoid touching user-managed networking.
        already_on_bridge = False
        try:
            net_attrs = bridge_net.attrs or {}
            containers_on_net = net_attrs.get("Containers", {})
            if container.id in containers_on_net:
                already_on_bridge = True
        except Exception:
            pass

        if already_on_bridge:
            print(c(GRAY, f"  [Airlock] container '{container_name}' is already on bridge; skipping connect"))
        else:
            try:
                bridge_net.connect(container)
                _airlock_connected = True
                print(c(YELLOW, f"  [Airlock] temporarily connected container '{container_name}' to bridge"))
            except Exception as conn_err:
                return f"ERROR: bridge network connection failed: {type(conn_err).__name__}: {conn_err}"

        exit_code, output = container.exec_run(
            cmd=["bash", "-c", install_cmd],
            stdout=True, stderr=True, demux=False,
        )
        result = output.decode("utf-8", errors="ignore") if output else ""
        status = "✓" if exit_code == 0 else f"✗ (exit {exit_code})"
        return (
            f"[Airlock {status}] {pkg_manager} install {pkg_str}\n"
            f"{result or '(no output)'}"
        )

    except Exception as e:
        return f"ERROR: install process failed: {type(e).__name__}: {e}"

    finally:
        # Only disconnect network connections made by this Airlock run.
        if bridge_net and _airlock_connected:
            try:
                bridge_net.disconnect(container, force=True)
                print(c(GREEN, f"  [Airlock] container '{container_name}' forcibly disconnected from network"))
            except Exception as disc_err:
                print(c(RED, f"  [Airlock] network disconnect failed; please check manually: {disc_err}"))


# ════════════════════════════════════════════════════════
# P4.3 resource cleanup: docker_prune_resources.
# ════════════════════════════════════════════════════════

def docker_prune_resources() -> str:
    """
    Remove stopped PawnLogic-managed containers and dangling images.
    Only cleans resources with the 'pawn=true' label to avoid touching
    user-managed containers. Returns freed space in MB.
    """
    client = _get_docker_client()
    if not client:
        return f"ERROR: Docker unavailable - {_docker_error}"

    freed_bytes = 0
    deleted_containers = []
    deleted_images = []
    errors = []

    # Remove only PawnLogic-managed stopped containers.
    try:
        container_result = client.containers.prune(
            filters={"label": "pawn=true"}
        )
        freed_bytes += container_result.get("SpaceReclaimed", 0)
        deleted_containers = container_result.get("ContainersDeleted") or []
    except Exception as e:
        errors.append(f"container cleanup failed: {type(e).__name__}: {e}")

    # Remove dangling images.
    try:
        image_result = client.images.prune(filters={"dangling": True})
        freed_bytes += image_result.get("SpaceReclaimed", 0)
        deleted_images = image_result.get("ImagesDeleted") or []
    except Exception as e:
        errors.append(f"image cleanup failed: {type(e).__name__}: {e}")

    freed_mb = freed_bytes / (1024 * 1024)

    if errors:
        return (
            f"WARNING: resource cleanup partially failed\n"
            f"  Containers deleted: {len(deleted_containers)}\n"
            f"  Image layers deleted: {len(deleted_images)}\n"
            f"  Space reclaimed: {freed_mb:.2f} MB\n"
            f"  Errors: {'; '.join(errors)}"
        )

    return (
        f"OK: resource cleanup complete\n"
        f"  Containers deleted: {len(deleted_containers)}\n"
        f"  Image layers deleted: {len(deleted_images)}\n"
        f"  Space reclaimed: {freed_mb:.2f} MB"
    )


# ════════════════════════════════════════════════════════
# Schema definitions.
# ════════════════════════════════════════════════════════

DOCKER_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "run_code_docker",
            "description": (
                "Run code inside a disposable Docker container.\n"
                "Use for Pwn exploit testing, multi-libc environment checks, and isolated sandbox execution.\n"
                "Defaults to no network (network=none) to prevent CTF flag leakage.\n"
                "Resource limits: 512 MB memory, 0.5 CPU, 256 PIDs.\n"
                "Supported languages: python / c / cpp / bash / javascript / rust / go / java.\n"
                "Returns clear setup guidance when Docker is unavailable."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "description": "Programming language (default python).",
                    },
                    "code": {
                        "type": "string",
                        "description": "Source code to execute.",
                    },
                    "image": {
                        "type": "string",
                        "description": (
                            "Execution image. Use 'python' for pure Python logic and 'pwndocker' for Pwn analysis. "
                            "When omitted, an image is selected from the language. "
                            "Available aliases: pwndocker / ubuntu18 / ubuntu22 / kali / python / gcc."
                        ),
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Execution timeout seconds (default 30).",
                    },
                    "mount_files": {
                        "type": "object",
                        "description": "File mounts {host path: container path}.",
                    },
                    "network": {
                        "type": "string",
                        "description": (
                            "Network mode: none (default no network) / bridge / host. "
                            "bridge/host requires allow_network=true or an environment policy override."
                        ),
                    },
                    "allow_network": {
                        "type": "boolean",
                        "description": "Explicitly allow bridge/host Docker network mode (default false).",
                    },
                    "allow_auto_pull": {
                        "type": "boolean",
                        "description": "Explicitly allow automatic docker pull when an image is missing (default false).",
                    },
                    "allow_host_read_mount": {
                        "type": "boolean",
                        "description": "Explicitly allow read-only mounts outside the workspace for trusted challenge files.",
                    },
                    "stdin": {
                        "type": "string",
                        "description": "Standard input passed to the program.",
                    },
                    "install_deps": {
                        "type": "string",
                        "description": "Space-separated pip package names for Python only.",
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
                "Persistent container management tool for long-running CTF target environments.\n"
                "Actions:\n"
                "  create  - create and start a persistent container\n"
                "  exec    - run a command inside a running container\n"
                "  destroy - stop and destroy a container\n"
                "  list    - list active persistent containers\n"
                "Use for multi-step Pwn debugging and exploit verification."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "exec", "destroy", "list"],
                        "description": "Operation type.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Container name identifier.",
                    },
                    "image": {
                        "type": "string",
                        "description": "Docker image for create only (default pwndocker).",
                    },
                    "command": {
                        "type": "string",
                        "description": "Command to execute for exec.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Command timeout seconds for exec (default 30).",
                    },
                    "network": {
                        "type": "string",
                        "description": (
                            "Network mode for create (default none). "
                            "bridge/host requires allow_network=true or an environment policy override."
                        ),
                    },
                    "allow_network": {
                        "type": "boolean",
                        "description": "Explicitly allow create to use bridge/host Docker network mode (default false).",
                    },
                    "allow_auto_pull": {
                        "type": "boolean",
                        "description": "Explicitly allow automatic docker pull when an image is missing (default false).",
                    },
                    "allow_host_read_mount": {
                        "type": "boolean",
                        "description": "Explicitly allow read-only mounts outside the workspace for trusted challenge files.",
                    },
                },
                "required": ["action"],
            },
        },
    },
    # P4.2: tool_install_package schema.
    {
        "type": "function",
        "function": {
            "name": "tool_install_package",
            "description": (
                "Airlock package installation tool.\n"
                "Temporarily connects a persistent container to install apt/pip packages, then forces network disconnect.\n"
                "Package names are strictly regex-validated to prevent command injection.\n"
                "Works only for containers created through pwn_container create."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "container_name": {
                        "type": "string",
                        "description": "Target persistent container name (the name passed to pwn_container create).",
                    },
                    "pkg_manager": {
                        "type": "string",
                        "enum": ["apt", "pip"],
                        "description": "Package manager: apt or pip.",
                    },
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Package names to install; each package may contain only [a-zA-Z0-9_\\-\\.]+.",
                    },
                },
                "required": ["container_name", "pkg_manager", "packages"],
            },
        },
    },
    # P4.3: docker_prune_resources schema.
    {
        "type": "function",
        "function": {
            "name": "docker_prune_resources",
            "description": (
                "Docker resource cleanup tool.\n"
                "Removes all stopped containers and dangling images, returning reclaimed disk space in MB.\n"
                "Use after CTF tasks or when disk space is low."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]
