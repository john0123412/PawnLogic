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
  - One-shot containers run hardened by default: read-only root filesystem,
    tmpfs scratch space, all Linux capabilities dropped, host uid:gid when
    available. Dependency installs retain the image user and a writable rootfs.
  - Operator-scoped disposable HTTP runs use network=none and a Unix relay;
    each proxy destination is authorized against a frozen scope and DNS snapshot.

Dependencies:
  - pip install docker (optional).
  - Local Docker CE runtime (dockerd).
"""

import os, re, tempfile, threading

from config import DANGEROUS_PATTERNS
from core.network_policy import NetworkOperation, NetworkPolicy
from core.operation_policy import OperationAction
from core.state import state as _runtime_state, runtime_config
from core.trust import TrustBoundaryKind, trust_notice_for_boundary
from tools.docker_airlock import (
    AIRLOCK_TIMEOUT_DEFAULT,
    CONTAINMENT_JOIN_SECONDS,
    begin_airlock_operation,
    finish_airlock_run,
    offline_attach_rejection,
    start_deadline_watchdog,
    validate_airlock_timeout,
)
from tools.docker_egress import EGRESS_SCOPE_ENV
from tools.docker_http import (
    code_directory, finish_transport, persistent_scope_error, prepare_transport,
    scoped_addresses, scoped_mode_error, start_transport,
)
from tools.docker_mounts import check_path_safety
from tools.docker_plan import build_docker_execution_plan, validate_network_mode
from tools.docker_schemas import DOCKER_SCHEMAS as DOCKER_SCHEMAS
from tools.docker_spawn import check_privilege_flags, resolve_container_user, spawn_container
from utils.ansi import c, YELLOW, GREEN, RED, GRAY, CYAN, MAGENTA, BOLD

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
        # Explicit (finite) daemon request timeout; equals the SDK default but
        # keeps the bound project-owned for the containment contracts.
        _docker_client = docker.from_env(timeout=60)
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


def _policy_truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in _TRUTHY_POLICY_VALUES


def _docker_policy_enabled(arg_value: object, env_name: str) -> bool:
    return _policy_truthy(arg_value) or _policy_truthy(os.environ.get(env_name))


def _check_network_policy(a: dict, network: str) -> str | None:
    mode, error = validate_network_mode(network)
    if error or mode == "none":
        return error
    explicit_authorization = _docker_policy_enabled(
        a.get("allow_network"), "PAWNLOGIC_DOCKER_ALLOW_NETWORK"
    )
    decision = NetworkPolicy().evaluate(
        NetworkOperation(
            capability_only=True,
            action="container_network",
            explicit_authorization=explicit_authorization,
            interactive=False,
        )
    )
    if decision.action == OperationAction.ALLOW:
        return None
    return (
        f"SECURITY BLOCK: Docker network='{mode}' requires explicit approval. "
        "Set allow_network=true for this tool call or PAWNLOGIC_DOCKER_ALLOW_NETWORK=true. "
        f"Optionally declare a bridge egress scope via {EGRESS_SCOPE_ENV} (hosts, IPs, or CIDRs)."
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
    container_user : str
        Run the container as this user (name or uid[:gid]). Default: a user
        matching host ids when available; 'root' explicitly selects root.
    stdin : str
        Standard input passed to the program.
    install_deps : str
        Space-separated pip package names for Python only.

    Returns
    -------
    str: execution result (stdout + stderr) plus container cleanup status.

    Notes
    -----
    One-shot containers run hardened: read-only root filesystem (relaxed when
    install_deps must write site-packages), tmpfs /tmp and /run, all Linux
    capabilities dropped, and host uid:gid when available (which may be root).
    Dependency installation retains the image user unless explicitly set.
    Scoped bridge requests use network=none and a trusted HTTP/CONNECT relay;
    without an operator scope, bridge access remains capability-only.
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
    err = check_privilege_flags(a)
    if err:
        return err
    container_user, err = resolve_container_user(a, allow_default=not plan.installs_packages)
    if err:
        return err
    raw_scope = os.environ.get(EGRESS_SCOPE_ENV, '').strip()
    err = scoped_mode_error(a, network=plan.network, language=plan.language, image=plan.image,
                           user=container_user, installs_packages=plan.installs_packages,
                           timeout=plan.timeout_seconds, raw_scope=raw_scope)
    if err:
        return err
    egress_addresses, scope_fingerprint, err = scoped_addresses(plan.network, raw_scope)
    if err:
        return err
    language = plan.language
    timeout = plan.timeout_seconds
    network = plan.network
    ext = plan.extension
    run_cmd = plan.command
    image_name = plan.image
    scoped_http = network == 'bridge' and bool(raw_scope)
    actual_network = 'none' if scoped_http else network

    client = _get_docker_client()
    if not client:
        return (
            f"ERROR: Docker unavailable - {_docker_error}\n"
            f"Ensure Docker CE is running: sudo systemctl start docker\n"
            f"Install the Python SDK: pip install docker"
        )

    # Prepare temp directory and write code.
    with tempfile.TemporaryDirectory(prefix="pawn_docker_") as tmpdir:
        code_dir = code_directory(tmpdir, scoped_http)
        code_file = os.path.join(code_dir, f"main{ext}")
        with open(code_file, "w", encoding="utf-8") as f:
            f.write(code)

        # Build mount volumes.
        volumes = {
            code_dir: {"bind": "/code", "mode": "rw"},
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
                real_hp = check_path_safety(
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
            stdin_file = os.path.join(code_dir, "stdin.txt")
            with open(stdin_file, "w", encoding="utf-8") as f:
                f.write(stdin_data)

        # Full execution command.
        full_cmd = f"cd /code && {run_cmd}"
        if stdin_file:
            full_cmd = f"cd /code && {run_cmd} < /code/stdin.txt"

        print(c(MAGENTA, f"  [docker] {image_name} -> {language}"))
        print(c(GRAY,    f"  Network: {network} -> {actual_network}  Timeout: {timeout}s  Image: {image_name}"))
        if scope_fingerprint:
            print(c(GRAY,    f"  Egress scope: {len(egress_addresses)} pinned hostname(s), "
                             f"fingerprint {scope_fingerprint}"))

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
        http_proxy = None
        execution_error = None
        try:
            http_proxy, container_command = prepare_transport(
                tmpdir, scoped_http, raw_scope, egress_addresses, timeout, full_cmd, volumes, start_transport)
            spawn_labels = {"pawn": "true", "pawn_name": "run_code_docker"}
            if scope_fingerprint:
                spawn_labels["pawn_egress_scope"] = scope_fingerprint
            spawn_kwargs: dict = dict(
                image=image_name,
                command=container_command,
                volumes=volumes,
                network_mode=actual_network,
                mem_limit="512m",
                cpu_period=100000,
                cpu_quota=50000,
                pids_limit=256,
                labels=spawn_labels,
                detach=True,
                stderr=True,
                stdout=True,
                remove=False,
                read_only=not plan.installs_packages,
            )
            if container_user:
                spawn_kwargs["user"] = container_user
            container = spawn_container(client, harden=True, **spawn_kwargs)

            # Wait for completion with timeout.
            result = container.wait(timeout=timeout)
            exit_code = result.get("StatusCode", -1)

            # Read output.
            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="ignore")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="ignore")
            output = stdout + stderr

        except PermissionError as e:
            execution_error = str(e)
        except Exception as e:
            execution_error = f"ERROR: container execution failed: {type(e).__name__}: {e}"
            if "timed out" in str(e).lower() or "timeout" in str(e).lower():
                try:
                    container.kill()
                except Exception:
                    pass
                execution_error = f"[execution timed out after {timeout}s] container cleanup attempted"
        finally:
            cleanup_error = finish_transport(http_proxy, container, scoped_http)
        if cleanup_error or execution_error:
            return cleanup_error or execution_error

        # Format output.
        limit = runtime_config()["tool_max_chars"]
        if len(output) > limit:
            half = limit // 2
            output = output[:half] + f"\n...[truncated to {limit} chars]...\n" + output[-half // 4:]

        status = "OK" if exit_code == 0 else f"FAILED (exit {exit_code})"
        scope_tag = " | egress: enforced HTTP/CONNECT" if scoped_http else ""
        header = (
            f"[run_code_docker - {status} | image: {image_name} | network: {actual_network}{scope_tag}]\n"
        )
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
    err = persistent_scope_error(a, operation=action, network=network)
    if err:
        return err

    if action == "create":
        err = _check_network_policy(a, network)
        if err:
            return err
        err = check_privilege_flags(a)
        if err:
            return err
        container_user, err = resolve_container_user(a, allow_default=False)
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
                real_hp = check_path_safety(
                    host_path,
                    mount_mode,
                    allow_host_read_mount=allow_host_read_mount,
                )
            except PermissionError as e:
                return f"ERROR: mount safety check failed - {e}"
            if os.path.exists(real_hp):
                volumes[real_hp] = {"bind": bind_spec["bind"], "mode": mount_mode}

        spawn_labels = {"pawn": "true", "pawn_name": name}
        spawn_kwargs: dict = dict(
            image=image,
            command="sleep infinity",
            network_mode=network,
            mem_limit="512m",
            cpu_period=100000,
            cpu_quota=50000,
            pids_limit=256,
            detach=True,
            name=f"pawn_{name}",
            labels=spawn_labels,
            volumes=volumes or None,
        )
        if container_user:
            spawn_kwargs["user"] = container_user
        container = spawn_container(client, **spawn_kwargs)

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
            timeout = int(a.get("timeout", 30) or 30)
        except (TypeError, ValueError):
            timeout = 30
        timeout = max(1, timeout)

        # docker-py's exec_run has no per-call timeout, so bound it with a
        # join timeout; a hung exec reports instead of hanging the tool.
        exec_holder: dict = {}

        def _do_exec() -> None:
            try:
                exec_holder["result"] = container.exec_run(
                    cmd=["bash", "-c", command],
                    stdout=True,
                    stderr=True,
                    demux=False,
                )
            except Exception as e:
                exec_holder["error"] = e

        worker = threading.Thread(target=_do_exec, daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            return f"ERROR: exec timed out after {timeout}s"
        if "error" in exec_holder:
            e = exec_holder["error"]
            return f"ERROR: exec failed: {type(e).__name__}: {e}"
        try:
            exit_code, output = exec_holder["result"]
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


class _AirlockRejected(Exception):
    """Internal sentinel: a guard rejection after the operation has begun."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def tool_install_package(a: dict) -> str:
    """
    Install packages inside a persistent container in Airlock mode.
    - Supports apt and pip only.
    - Strict package-name validation prevents command injection.
    - The whole operation runs under a hard deadline (timeout_seconds,
      integer 1-300, default 120) enforced by an independent watchdog: on
      expiry the tool handle is revoked first, then the container is
      terminated (forced-removal fallback) and the owned bridge attachment
      is removed — a timed-out persistent container does not survive, and
      unresolved cleanup is reported as a containment failure. Operations
      for the same container are serialized; late timers cannot kill a
      successor operation.
    - Disconnects only bridge attachments made by this run; existing ones remain.
    - Failed temporary disconnect revokes access and kills/removes the container.
    - Offline containers (network none/unattached) and unknown network state
      are rejected before any connect or install; the container is preserved.
    """
    err = persistent_scope_error(a, operation='airlock')
    if err:
        return err
    timeout_seconds, terr = validate_airlock_timeout(
        a.get("timeout_seconds", AIRLOCK_TIMEOUT_DEFAULT)
    )
    if terr:
        return terr
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

    # Airlock: temporarily connect -> install -> force disconnect, all under
    # a hard operation deadline.
    bridge_net = None
    _airlock_connected = False
    op = None
    watchdog = None
    try:
        bridge_net = client.networks.get("bridge")

        # Issue #177.4: installing packages always causes outbound traffic,
        # so every call needs explicit network authorization — even when the
        # container is already on bridge via user-managed networking. The
        # already_on_bridge check below only decides whether the airlock
        # itself must connect/disconnect.
        err = _check_network_policy(a, "bridge")
        if err:
            return err

        # Serialize per container before reading bridge membership: the
        # ownership decision must come from serialized state, or a concurrent
        # operation's temporary attachment could be mistaken for a
        # pre-existing user-managed one.
        maybe_op = begin_airlock_operation(container_name, timeout_seconds)
        if isinstance(maybe_op, str):
            return maybe_op
        op = maybe_op

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
            # The daemon rejects bridge attachment for containers created in
            # private network modes; refuse before touching anything. Raised
            # as a sentinel so the operation still settles in the finally and
            # the rejection rides on `result`.
            guard = offline_attach_rejection(container, container_name)
            if guard:
                raise _AirlockRejected(guard)

        # The deadline starts before any attach and covers the exec and the
        # owned-network cleanup; watchdog callbacks are generation-bound, so
        # a late timer cannot kill its successor.
        watchdog = start_deadline_watchdog(
            op, container,
            revoke_handle=lambda: _active_containers.pop(container_name, None),
            owned_disconnect=(
                None if already_on_bridge
                else (lambda: bridge_net.disconnect(container, force=True))
            ),
        )

        if not already_on_bridge:
            # A lost daemon response can follow a successful attachment.
            # Attempt cleanup even when connect() raises.
            _airlock_connected = True
            try:
                bridge_net.connect(container)
            except Exception:
                try:
                    bridge_net.reload()
                    _airlock_connected = container.id in bridge_net.attrs["Containers"]
                except Exception:
                    pass  # Unknown daemon state must still trigger cleanup.
                raise
            print(c(YELLOW, f"  [Airlock] temporarily connected container '{container_name}' to bridge"))

        # Bounded installer call: the watchdog kills the container at the
        # deadline; if containment cannot land (kill/removal failing), the
        # caller must still stop waiting and report containment instead of
        # blocking on a stuck exec stream.
        exec_box: dict = {}
        exec_done = threading.Event()

        def _run_install():
            try:
                exec_box["out"] = container.exec_run(
                    cmd=["bash", "-c", install_cmd],
                    stdout=True, stderr=True, demux=False,
                )
            except Exception as exc:
                exec_box["error"] = exc
            finally:
                exec_done.set()

        threading.Thread(target=_run_install, daemon=True).start()
        if not exec_done.wait(timeout_seconds + CONTAINMENT_JOIN_SECONDS):
            result = (
                f"SECURITY BLOCK: Airlock install did not return within its "
                f"{timeout_seconds}s deadline for container '{container_name}'"
            )
        elif "error" in exec_box:
            raise exec_box["error"]
        else:
            exit_code, output = exec_box["out"]
            text = output.decode("utf-8", errors="ignore") if output else ""
            status = "✓" if exit_code == 0 else f"✗ (exit {exit_code})"
            result = (
                f"[Airlock {status}] {pkg_manager} install {pkg_str}\n"
                f"{text or '(no output)'}"
            )

    except _AirlockRejected as rejected:
        result = rejected.message
    except Exception as e:
        result = f"ERROR: install process failed: {type(e).__name__}: {e}"

    finally:
        if op is not None:
            # Containment first, owned-network cleanup second (bounded, with
            # the watchdog still armed), lease release last.
            result = finish_airlock_run(
                op, watchdog, result,
                container=container, container_name=container_name,
                owned_disconnect=(
                    (lambda: bridge_net.disconnect(container, force=True))
                    if (bridge_net is not None and _airlock_connected) else None
                ),
                revoke_handle=lambda: _active_containers.pop(container_name, None),
            )
    return result


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
