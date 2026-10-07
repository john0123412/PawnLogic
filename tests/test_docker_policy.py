"""Tests for Docker sandbox risk policy gates."""

import os
import threading

import pytest

from tools import docker_egress, docker_mounts, docker_sandbox, docker_spawn
from tools import docker_plan


class _MissingImages:
    pulled = False

    def get(self, image):
        raise RuntimeError(f"missing image: {image}")

    def pull(self, image):
        self.pulled = True
        raise AssertionError("pull should be blocked by policy")


class _FakeDockerClient:
    def __init__(self):
        self.images = _MissingImages()


def test_docker_network_policy_blocks_risky_modes_by_default(monkeypatch):
    monkeypatch.delenv("PAWNLOGIC_DOCKER_ALLOW_NETWORK", raising=False)

    assert docker_sandbox._check_network_policy({}, "none") is None
    assert "SECURITY BLOCK" in docker_sandbox._check_network_policy({}, "bridge")
    assert "SECURITY BLOCK" in docker_sandbox._check_network_policy({}, "host")


def test_docker_network_policy_allows_explicit_arg():
    assert docker_sandbox._check_network_policy({"allow_network": True}, "bridge") is None


def test_run_code_docker_blocks_risky_network_before_docker(monkeypatch):
    monkeypatch.setattr(
        docker_sandbox,
        "_get_docker_client",
        lambda: (_ for _ in ()).throw(AssertionError("Docker should not be touched")),
    )

    result = docker_sandbox.tool_run_code_docker(
        {"language": "python", "code": "print(1)", "network": "host"}
    )

    assert result.startswith("SECURITY BLOCK: Docker network='host'")


def test_pwn_container_blocks_risky_network_before_docker(monkeypatch):
    monkeypatch.setattr(
        docker_sandbox,
        "_get_docker_client",
        lambda: (_ for _ in ()).throw(AssertionError("Docker should not be touched")),
    )

    result = docker_sandbox.tool_pwn_container(
        {"action": "create", "name": "lab", "network": "bridge"}
    )

    assert result.startswith("SECURITY BLOCK: Docker network='bridge'")


def test_run_code_docker_blocks_auto_pull_by_default(monkeypatch):
    fake_client = _FakeDockerClient()
    monkeypatch.delenv("PAWNLOGIC_DOCKER_ALLOW_AUTO_PULL", raising=False)
    monkeypatch.setattr(docker_sandbox, "_get_docker_client", lambda: fake_client)

    result = docker_sandbox.tool_run_code_docker(
        {"language": "python", "code": "print(1)", "image": "missing:latest"}
    )

    assert result.startswith("SECURITY BLOCK: Docker image 'missing:latest'")
    assert fake_client.images.pulled is False


def test_docker_auto_pull_policy_allows_explicit_arg():
    assert (
        docker_sandbox._check_auto_pull_policy(
            {"allow_auto_pull": True}, "missing:latest"
        )
        is None
    )


def test_run_code_docker_rejects_invalid_python_dependency_names():
    result = docker_sandbox.tool_run_code_docker(
        {
            "language": "python",
            "code": "print(1)",
            "install_deps": "requests;touch",
        }
    )

    assert "invalid Python package name" in result


def test_docker_ro_mount_outside_workspace_blocked_by_default(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "challenge.bin"
    outside.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(docker_mounts, "SAFE_WORKSPACE", str(workspace.resolve()))

    with pytest.raises(PermissionError, match="RO mounts are limited"):
        docker_mounts.check_path_safety(str(outside), "ro")


def test_docker_ro_mount_outside_workspace_requires_explicit_allow(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "challenge.bin"
    outside.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(docker_mounts, "SAFE_WORKSPACE", str(workspace.resolve()))

    assert docker_mounts.check_path_safety(
        str(outside),
        "ro",
        allow_host_read_mount=True,
    ) == str(outside.resolve())


def test_docker_mount_blocks_sensitive_paths_even_when_read_only_allowed(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    secret_dir = tmp_path / ".ssh"
    secret_file = secret_dir / "id_rsa"
    workspace.mkdir()
    secret_dir.mkdir()
    secret_file.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(docker_mounts, "SAFE_WORKSPACE", str(workspace.resolve()))
    monkeypatch.setattr(docker_mounts, "READ_BLACKLIST", [str(secret_dir)])

    with pytest.raises(PermissionError, match="credentials"):
        docker_mounts.check_path_safety(
            str(secret_file),
            "ro",
            allow_host_read_mount=True,
        )


def test_docker_mount_blocks_docker_socket(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    socket_path = tmp_path / "docker.sock"
    workspace.mkdir()
    socket_path.write_text("socket placeholder", encoding="utf-8")
    monkeypatch.setattr(docker_mounts, "SAFE_WORKSPACE", str(workspace.resolve()))

    with pytest.raises(PermissionError, match=r"docker.sock|host control"):
        docker_mounts.check_path_safety(
            str(socket_path),
            "ro",
            allow_host_read_mount=True,
        )


def test_privilege_flags_rejected_in_tool_args():
    assert docker_spawn.check_privilege_flags({}) is None
    assert docker_spawn.check_privilege_flags({"language": "python"}) is None
    for flag in (
        "privileged",
        "--privileged",
        "cap_add",
        "cap-add",
        "--cap-add",
        "cap_drop",
        "--cap-drop",
        "security_opt",
        "security-opt",
        "--security-opt",
        "Privileged",
    ):
        err = docker_spawn.check_privilege_flags({flag: True})
        assert err is not None
        assert err.startswith("SECURITY BLOCK")
        assert "never permitted" in err


def test_run_code_docker_blocks_privilege_flags_before_docker(monkeypatch):
    monkeypatch.setattr(
        docker_sandbox,
        "_get_docker_client",
        lambda: (_ for _ in ()).throw(AssertionError("Docker should not be touched")),
    )

    result = docker_sandbox.tool_run_code_docker(
        {"language": "python", "code": "print(1)", "privileged": True}
    )

    assert result.startswith("SECURITY BLOCK")
    assert "never permitted" in result


def test_pwn_container_create_blocks_privilege_flags_before_docker(monkeypatch):
    monkeypatch.setattr(
        docker_sandbox,
        "_get_docker_client",
        lambda: (_ for _ in ()).throw(AssertionError("Docker should not be touched")),
    )

    result = docker_sandbox.tool_pwn_container(
        {"action": "create", "name": "lab", "cap_add": ["NET_ADMIN"]}
    )

    assert result.startswith("SECURITY BLOCK")
    assert "never permitted" in result


class _RecordingContainers:
    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return object()


class _RecordingClient:
    def __init__(self):
        self.containers = _RecordingContainers()


def test_spawn_container_never_passes_privilege_kwargs():
    client = _RecordingClient()
    docker_spawn.spawn_container(client, image="img", network_mode="none")
    assert client.containers.calls, "expected one containers.run call"
    assert not (
        set(client.containers.calls[0]) & docker_spawn.FORBIDDEN_CONTAINER_KWARGS
    )

    with pytest.raises(PermissionError, match="privileged flags forbidden"):
        docker_spawn.spawn_container(client, image="img", privileged=True)
    with pytest.raises(PermissionError, match="privileged flags forbidden"):
        docker_spawn.spawn_container(client, image="img", cap_add=["SYS_PTRACE"])
    # CLI-style aliases must not dodge the choke point either.
    with pytest.raises(PermissionError, match="privileged flags forbidden"):
        docker_spawn.spawn_container(client, **{"cap-add": ["SYS_PTRACE"]})
    assert len(client.containers.calls) == 1, "blocked spawns must not reach the SDK"
class _FakeBridgeNet:
    def __init__(self):
        self.connected = []
        self.disconnected = []
        self.attrs = {"Containers": {}}

    def connect(self, container):
        self.connected.append(container)

    def disconnect(self, container, force=False):
        self.disconnected.append(container)


class _FakeAirlockContainer:
    def __init__(self):
        self.id = "cid123"
        # Empty membership models an offline (none/unattached) container;
        # tests that exercise the attach path set a real network here.
        self.attrs = {"NetworkSettings": {"Networks": {}}}
        self.reload_error: Exception | None = None
        self.kill_calls = 0
        self.remove_calls: list[bool] = []
        self.kill_error: Exception | None = None
        self.remove_error: Exception | None = None
        self.exec_mode = "ok"  # "ok" stalls until killed when set to "stall"
        self.dead = threading.Event()

    def reload(self):
        if self.reload_error is not None:
            raise self.reload_error

    def kill(self):
        self.kill_calls += 1
        if self.kill_error is not None:
            raise self.kill_error
        self.dead.set()

    def remove(self, force=False):
        self.remove_calls.append(force)
        if self.remove_error is not None:
            raise self.remove_error

    def exec_run(self, cmd, stdout=True, stderr=True, demux=False):
        if self.exec_mode in ("stall", "stall_success"):
            # Models a hung apt update / pip resolve; returns only when the
            # watchdog kills the container (or after a test-bounded wait).
            self.dead.wait(timeout=15)
            if self.exec_mode == "stall_success":
                return 0, b"ok"
            if self.dead.is_set():
                return 137, b"terminated mid-install"
            return 124, b"exec still running"
        return 0, b"ok"


class _FakeGetter:
    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, name):
        return self._mapping[name]


class _FakeAirlockClient:
    def __init__(self):
        self.bridge = _FakeBridgeNet()
        self.container = _FakeAirlockContainer()
        self.networks = _FakeGetter({"bridge": self.bridge})
        self.containers = _FakeGetter({"cid123": self.container})


def _install_airlock_client(monkeypatch):
    monkeypatch.delenv("PAWNLOGIC_DOCKER_ALLOW_NETWORK", raising=False)
    monkeypatch.delenv("PAWNLOGIC_DOCKER_EGRESS_ALLOW", raising=False)
    client = _FakeAirlockClient()
    monkeypatch.setattr(docker_sandbox, "_get_docker_client", lambda: client)
    monkeypatch.setitem(docker_sandbox._active_containers, "c1", "cid123")
    return client


def test_airlock_install_blocks_bridge_egress_without_authorization(monkeypatch):
    client = _install_airlock_client(monkeypatch)

    result = docker_sandbox.tool_install_package(
        {"container_name": "c1", "pkg_manager": "pip", "packages": ["requests"]}
    )

    assert result.startswith("SECURITY BLOCK")
    assert client.bridge.connected == []


def test_airlock_install_allows_bridge_egress_with_explicit_arg(monkeypatch):
    client = _install_airlock_client(monkeypatch)
    # Attach is only supported for containers that already sit on a real
    # network (e.g. a user-defined bridge); offline containers are rejected
    # by the compatibility guard before any mutation.
    client.container.attrs["NetworkSettings"]["Networks"] = {
        "lab_net": {"NetworkID": "netabc"}
    }

    result = docker_sandbox.tool_install_package(
        {
            "container_name": "c1",
            "pkg_manager": "pip",
            "packages": ["requests"],
            "allow_network": True,
        }
    )

    assert result.startswith("[Airlock")
    assert client.bridge.connected == [client.container]
    assert client.bridge.disconnected == [client.container]


@pytest.mark.parametrize("install_fails", [False, True])
@pytest.mark.parametrize("kill_fails,remove_fails", [(False, False), (True, False), (True, True)])
def test_airlock_disconnect_failure_revokes_container_access(monkeypatch, kill_fails, remove_fails, install_fails):
    client = _install_airlock_client(monkeypatch)
    client.container.attrs["NetworkSettings"]["Networks"] = {
        "lab_net": {"NetworkID": "netabc"}
    }
    actions = []
    if install_fails:
        def fail_install(**kwargs):
            raise RuntimeError("install unavailable")
        monkeypatch.setattr(client.container, "exec_run", fail_install)

    def fail_disconnect(*args, **kwargs):
        raise RuntimeError("disconnect unavailable")

    def kill():
        actions.append("kill")
        if kill_fails:
            raise RuntimeError("kill unavailable")

    def remove(force=False):
        assert force
        actions.append("remove")
        if remove_fails:
            raise RuntimeError("remove unavailable")

    monkeypatch.setattr(client.bridge, "disconnect", fail_disconnect)
    monkeypatch.setattr(client.container, "kill", kill, raising=False)
    monkeypatch.setattr(client.container, "remove", remove, raising=False)
    result = docker_sandbox.tool_install_package(
        {"container_name": "c1", "pkg_manager": "pip", "packages": ["requests"],
         "allow_network": True}
    )

    assert result.startswith("SECURITY BLOCK: Airlock network disconnect failed")
    assert "[Airlock ✓]" not in result
    assert actions == (["kill", "remove"] if kill_fails else ["kill"])
    assert "c1" not in docker_sandbox._active_containers
    if remove_fails:
        assert "may still be running" in result
    denied = docker_sandbox.tool_pwn_container({"action": "exec", "name": "c1", "command": "true"})
    assert "not found" in denied


@pytest.mark.parametrize("disconnect_fails", [False, True])
def test_airlock_connect_error_still_revokes_partial_attachment(monkeypatch, disconnect_fails):
    client = _install_airlock_client(monkeypatch)
    client.container.attrs["NetworkSettings"]["Networks"] = {
        "lab_net": {"NetworkID": "netabc"}
    }
    killed = []

    def partially_connect(container):
        client.bridge.connected.append(container)
        raise RuntimeError("connect response lost")

    monkeypatch.setattr(client.bridge, "connect", partially_connect)
    monkeypatch.setattr(client.container, "exec_run", lambda **kwargs: pytest.fail("install must not run"))
    monkeypatch.setattr(client.container, "kill", lambda: killed.append(True), raising=False)
    if disconnect_fails:
        def fail_disconnect(*args, **kwargs):
            raise RuntimeError("disconnect unavailable")
        monkeypatch.setattr(client.bridge, "disconnect", fail_disconnect)
    result = docker_sandbox.tool_install_package(
        {"container_name": "c1", "pkg_manager": "pip", "packages": ["requests"],
         "allow_network": True}
    )
    if disconnect_fails:
        assert result.startswith("SECURITY BLOCK: Airlock network disconnect failed")
        assert killed == [True]
        assert "c1" not in docker_sandbox._active_containers
    else:
        assert result.startswith("ERROR:")
        assert client.bridge.disconnected == [client.container]
        assert killed == []


@pytest.mark.parametrize(
    "networks",
    [
        {"none": {"NetworkID": "net_none"}},
        {},
    ],
    ids=["none_mode", "unattached"],
)
def test_airlock_rejects_offline_container_before_any_mutation(monkeypatch, networks):
    # Engine contract: the daemon rejects attaching containers created in
    # private network modes to bridge, so the guard must refuse before any
    # connect attempt, before running the installer, and leave the container.
    client = _install_airlock_client(monkeypatch)
    client.container.attrs["NetworkSettings"]["Networks"] = networks
    monkeypatch.setattr(
        client.bridge, "connect", lambda c: pytest.fail("offline container must not be connected")
    )
    monkeypatch.setattr(
        client.container, "exec_run", lambda **kwargs: pytest.fail("install must not run")
    )
    monkeypatch.setattr(
        client.container, "kill", lambda: pytest.fail("offline container must survive"), raising=False
    )
    monkeypatch.setattr(
        client.bridge, "disconnect", lambda *a, **k: pytest.fail("nothing to disconnect"), raising=False
    )

    result = docker_sandbox.tool_install_package(
        {"container_name": "c1", "pkg_manager": "pip", "packages": ["requests"],
         "allow_network": True}
    )

    assert result.startswith("SECURITY BLOCK")
    assert "offline" in result
    # The rejection must not suggest host networking or scope relaxation.
    assert "host network" not in result
    assert client.bridge.connected == []
    assert client.bridge.disconnected == []
    assert docker_sandbox._active_containers.get("c1") == "cid123"


@pytest.mark.parametrize("broken", ["reload", "attrs", "settings"])
def test_airlock_fails_closed_on_unknown_network_state(monkeypatch, broken):
    client = _install_airlock_client(monkeypatch)
    if broken == "reload":
        client.container.reload_error = RuntimeError("daemon unreachable")
    elif broken == "settings":
        client.container.attrs = {"NetworkSettings": "garbage"}
    else:
        client.container.attrs = {}
    monkeypatch.setattr(
        client.bridge, "connect", lambda c: pytest.fail("unknown state must not be connected")
    )
    monkeypatch.setattr(
        client.container, "exec_run", lambda **kwargs: pytest.fail("install must not run")
    )
    monkeypatch.setattr(
        client.container, "kill", lambda: pytest.fail("unknown state must not mutate"), raising=False
    )

    result = docker_sandbox.tool_install_package(
        {"container_name": "c1", "pkg_manager": "pip", "packages": ["requests"],
         "allow_network": True}
    )

    assert result.startswith("SECURITY BLOCK")
    assert "cannot" in result
    assert client.bridge.connected == []
    assert client.bridge.disconnected == []
    assert docker_sandbox._active_containers.get("c1") == "cid123"


@pytest.mark.parametrize("pkg_manager", ["apt", "pip"])
@pytest.mark.parametrize("already_on_bridge", [False, True])
def test_airlock_deadline_terminates_stalled_install(monkeypatch, pkg_manager, already_on_bridge):
    # The deadline covers the whole operation (attach + apt update + install);
    # expiry must revoke the handle, terminate the container, remove the owned
    # attachment, and never report install success.
    client = _install_airlock_client(monkeypatch)
    if already_on_bridge:
        client.bridge.attrs = {"Containers": {"cid123": {}}}
    else:
        client.container.attrs["NetworkSettings"]["Networks"] = {
            "lab_net": {"NetworkID": "netabc"}
        }
    client.container.exec_mode = "stall"

    result = docker_sandbox.tool_install_package(
        {"container_name": "c1", "pkg_manager": pkg_manager, "packages": ["curl"],
         "allow_network": True, "timeout_seconds": 1}
    )

    assert result.startswith("SECURITY BLOCK")
    assert "deadline" in result
    assert client.container.kill_calls == 1
    assert "c1" not in docker_sandbox._active_containers
    if already_on_bridge:
        assert client.bridge.connected == []
        assert client.bridge.disconnected == []
    else:
        assert client.bridge.connected == [client.container]
        assert client.bridge.disconnected == [client.container]


def test_airlock_deadline_kill_and_remove_failure_reports_manual_cleanup(monkeypatch):
    client = _install_airlock_client(monkeypatch)
    client.container.attrs["NetworkSettings"]["Networks"] = {
        "lab_net": {"NetworkID": "netabc"}
    }
    client.container.exec_mode = "stall"
    client.container.kill_error = RuntimeError("kill unavailable")
    client.container.remove_error = RuntimeError("remove unavailable")

    result = docker_sandbox.tool_install_package(
        {"container_name": "c1", "pkg_manager": "pip", "packages": ["curl"],
         "allow_network": True, "timeout_seconds": 1}
    )

    assert result.startswith("SECURITY BLOCK")
    assert "may still be running" in result
    assert "manual Docker cleanup" in result
    assert client.container.remove_calls == [True]
    assert "c1" not in docker_sandbox._active_containers


def test_airlock_install_completing_after_expiry_reports_containment_not_success(monkeypatch):
    # Deadline/completion race: if the watchdog won the atomic decision, the
    # operation is a containment failure even when exec returned success.
    client = _install_airlock_client(monkeypatch)
    client.container.attrs["NetworkSettings"]["Networks"] = {
        "lab_net": {"NetworkID": "netabc"}
    }
    client.container.exec_mode = "stall_success"

    result = docker_sandbox.tool_install_package(
        {"container_name": "c1", "pkg_manager": "pip", "packages": ["curl"],
         "allow_network": True, "timeout_seconds": 1}
    )

    assert result.startswith("SECURITY BLOCK")
    assert "deadline" in result
    assert "[Airlock ✓]" not in result
    assert client.container.kill_calls == 1


@pytest.mark.parametrize(
    "raw", [True, "60", 0, 301, None, 1.5], ids=["bool", "str", "zero", "too-big", "none", "float"]
)
def test_airlock_rejects_invalid_timeout_without_touching_docker(monkeypatch, raw):
    monkeypatch.setattr(
        docker_sandbox,
        "_get_docker_client",
        lambda: pytest.fail("invalid timeout must be rejected before any daemon use"),
    )
    result = docker_sandbox.tool_install_package(
        {"container_name": "c1", "pkg_manager": "pip", "packages": ["curl"],
         "allow_network": True, "timeout_seconds": raw}
    )
    assert result.startswith("ERROR: timeout_seconds")


def test_airlock_serializes_operations_for_same_container(monkeypatch):
    from tools import docker_airlock

    monkeypatch.setattr(docker_airlock, "SERIAL_WAIT_SECONDS", 0.3)
    client = _install_airlock_client(monkeypatch)
    client.container.attrs["NetworkSettings"]["Networks"] = {
        "lab_net": {"NetworkID": "netabc"}
    }
    client.container.exec_mode = "stall"

    first = {}

    def run_first():
        first["result"] = docker_sandbox.tool_install_package(
            {"container_name": "c1", "pkg_manager": "pip", "packages": ["curl"],
             "allow_network": True, "timeout_seconds": 300}
        )

    worker = threading.Thread(target=run_first, daemon=True)
    worker.start()
    for _ in range(100):
        if client.bridge.connected:
            break
        threading.Event().wait(0.02)
    assert client.bridge.connected, "first operation never reached connect"

    second = docker_sandbox.tool_install_package(
        {"container_name": "c1", "pkg_manager": "pip", "packages": ["curl"],
         "allow_network": True, "timeout_seconds": 5}
    )
    assert second.startswith("SECURITY BLOCK")
    assert "another Airlock operation" in second
    assert client.container.kill_calls == 0
    # The rejected call must not have touched network ownership either.
    assert client.bridge.connected == [client.container]

    client.container.dead.set()  # unblock the stalled exec; no watchdog at 300s
    worker.join(timeout=10)
    assert first["result"].startswith("[Airlock ✗")
    assert client.container.kill_calls == 0

    # The serial slot is released: a fresh operation can run to completion.
    client.container.exec_mode = "ok"
    client.container.dead.clear()
    third = docker_sandbox.tool_install_package(
        {"container_name": "c1", "pkg_manager": "pip", "packages": ["curl"],
         "allow_network": True, "timeout_seconds": 120}
    )
    assert third.startswith("[Airlock ✓")


def test_airlock_stale_watchdog_cannot_kill_successor_operation():
    from tools import docker_airlock

    handles: dict[str, str] = {"c1": "cid123"}
    container_one = _FakeAirlockContainer()
    container_two = _FakeAirlockContainer()

    op1 = docker_airlock.begin_airlock_operation("c1", 1)
    revoke = lambda: handles.pop("c1", None)
    watchdog1 = docker_airlock.start_deadline_watchdog(
        op1, container_one, revoke, owned_disconnect=None
    )
    # Production exec blocks until the kill lands; mirror that here by
    # waiting for the watchdog to fire before settling the operation.
    for _ in range(300):
        if container_one.kill_calls:
            break
        threading.Event().wait(0.01)
    expired, _ = docker_airlock.settle_airlock_operation(op1, watchdog1)
    assert expired and container_one.kill_calls == 1
    assert "c1" not in handles

    op2 = docker_airlock.begin_airlock_operation("c1", 1)
    assert op2.generation == op1.generation + 1

    # The old timer fires late: generation mismatch must make it a no-op.
    docker_airlock._deadline_fired(op1, container_two, revoke, owned_disconnect=None)
    assert container_two.kill_calls == 0
    assert not container_two.dead.is_set()

    watchdog2 = docker_airlock.start_deadline_watchdog(
        op2, container_two, revoke, owned_disconnect=None
    )
    for _ in range(300):
        if container_two.kill_calls:
            break
        threading.Event().wait(0.01)
    expired2, _ = docker_airlock.settle_airlock_operation(op2, watchdog2)
    assert expired2 and container_two.kill_calls == 1


def test_airlock_watchdog_start_failure_releases_serial_slot(monkeypatch):
    from tools import docker_airlock

    client = _install_airlock_client(monkeypatch)
    client.container.attrs["NetworkSettings"]["Networks"] = {
        "lab_net": {"NetworkID": "netabc"}
    }

    def no_threads(*args, **kwargs):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(docker_sandbox, "start_deadline_watchdog", no_threads)
    result = docker_sandbox.tool_install_package(
        {"container_name": "c1", "pkg_manager": "pip", "packages": ["curl"],
         "allow_network": True, "timeout_seconds": 120}
    )
    assert result.startswith("ERROR: install process failed")
    assert client.container.kill_calls == 0  # nothing attached or executed

    # The serial slot must not leak: a fresh operation can begin immediately.
    op = docker_airlock.begin_airlock_operation("c1", 120)
    assert not isinstance(op, str)
    expired, _ = docker_airlock.settle_airlock_operation(op, None)
    assert expired is False


def test_airlock_uncontainable_install_returns_bounded(monkeypatch):
    # Kill and forced removal both fail: the caller must stop waiting at the
    # deadline window and report containment instead of blocking on exec.
    from tools import docker_airlock

    monkeypatch.setattr(docker_sandbox, "CONTAINMENT_JOIN_SECONDS", 0.5)
    monkeypatch.setattr(docker_airlock, "CONTAINMENT_JOIN_SECONDS", 0.5)
    client = _install_airlock_client(monkeypatch)
    client.container.attrs["NetworkSettings"]["Networks"] = {
        "lab_net": {"NetworkID": "netabc"}
    }
    client.container.exec_mode = "stall"
    client.container.kill_error = RuntimeError("kill unavailable")
    client.container.remove_error = RuntimeError("remove unavailable")

    result = docker_sandbox.tool_install_package(
        {"container_name": "c1", "pkg_manager": "pip", "packages": ["curl"],
         "allow_network": True, "timeout_seconds": 1}
    )

    assert result.startswith("SECURITY BLOCK")
    assert "deadline" in result
    assert "may still be running" in result
    assert "c1" not in docker_sandbox._active_containers


def test_airlock_disconnect_stall_is_contained_within_bound(monkeypatch):
    from tools import docker_airlock

    monkeypatch.setattr(docker_airlock, "CONTAINMENT_JOIN_SECONDS", 0.5)
    client = _install_airlock_client(monkeypatch)
    client.container.attrs["NetworkSettings"]["Networks"] = {
        "lab_net": {"NetworkID": "netabc"}
    }
    release = threading.Event()

    def stalled_disconnect(*args, **kwargs):
        client.bridge.disconnected.append(client.container)
        release.wait(timeout=15)  # models a stuck daemon call

    monkeypatch.setattr(client.bridge, "disconnect", stalled_disconnect)
    result = docker_sandbox.tool_install_package(
        {"container_name": "c1", "pkg_manager": "pip", "packages": ["curl"],
         "allow_network": True, "timeout_seconds": 120}
    )

    assert result.startswith("SECURITY BLOCK")
    assert "did not complete" in result
    assert client.container.kill_calls == 1  # containment covers the stall
    assert "c1" not in docker_sandbox._active_containers
    release.set()  # unblock the leaked worker before the test process moves on


class _LegacyContainer:
    def __init__(self, name, attrs):
        self.name = name
        self.status = "running"
        self.attrs = attrs
        self.reload_calls = 0

    def reload(self):
        self.reload_calls += 1


class _PreflightClient:
    def __init__(self, items=None, list_error=None):
        self._items = items or []
        self._list_error = list_error
        self.list_filters = None
        self.containers = self

    def list(self, filters=None, ignore_removed=False):
        if self._list_error is not None:
            raise self._list_error
        self.list_filters = filters
        return self._items


def test_pwn_container_preflight_is_read_only_and_labelled(monkeypatch):
    legacy = _LegacyContainer(
        "pawn_legacy", {"NetworkSettings": {"Networks": {"bridge": {"NetworkID": "b"}}}}
    )
    offline = _LegacyContainer(
        "pawn_offline", {"NetworkSettings": {"Networks": {"none": {"NetworkID": "n"}}}}
    )
    broken = _LegacyContainer("pawn_broken", None)
    client = _PreflightClient([legacy, offline, broken])
    monkeypatch.setattr(docker_sandbox, "_get_docker_client", lambda: client)
    monkeypatch.delenv("PAWNLOGIC_DOCKER_EGRESS_ALLOW", raising=False)

    result = docker_sandbox.tool_pwn_container({"action": "preflight"})

    assert client.list_filters == {"label": "pawn=true"}
    assert "pawn_legacy" in result and "network=bridge" in result
    assert "NEEDS ATTENTION" in result
    assert "pawn_offline" in result and "network=none" in result
    assert "pawn_broken" in result and "network=unknown" in result
    assert "does not quarantine" in result
    assert legacy.reload_calls == 1 and offline.reload_calls == 1


def test_pwn_container_preflight_allowed_under_scope(monkeypatch):
    client = _PreflightClient([])
    monkeypatch.setattr(docker_sandbox, "_get_docker_client", lambda: client)
    monkeypatch.setenv("PAWNLOGIC_DOCKER_EGRESS_ALLOW", "pwn.example.com")

    result = docker_sandbox.tool_pwn_container({"action": "preflight"})

    assert result.startswith("  Read-only preflight")
    assert "No running" in result


def test_pwn_container_preflight_reports_daemon_failure(monkeypatch):
    client = _PreflightClient(list_error=RuntimeError("daemon down"))
    monkeypatch.setattr(docker_sandbox, "_get_docker_client", lambda: client)

    result = docker_sandbox.tool_pwn_container({"action": "preflight"})

    assert result.startswith("ERROR: preflight inspection failed")


def test_airlock_expired_connect_recovery_does_not_install(monkeypatch):
    # A hung attach that outlives the deadline and then completes must not
    # hand an expired, condemned operation to the installer.
    client = _install_airlock_client(monkeypatch)
    client.container.attrs["NetworkSettings"]["Networks"] = {
        "lab_net": {"NetworkID": "netabc"}
    }
    exec_calls = []

    def connect_after_kill(container):
        client.bridge.connected.append(container)
        client.container.dead.wait(timeout=10)  # deadline fires; kill lands
        return None  # the hung connect eventually "recovers"

    monkeypatch.setattr(client.bridge, "connect", connect_after_kill)
    monkeypatch.setattr(
        client.container,
        "exec_run",
        lambda **kwargs: exec_calls.append(True) or (0, b"ok"),
    )

    result = docker_sandbox.tool_install_package(
        {"container_name": "c1", "pkg_manager": "pip", "packages": ["curl"],
         "allow_network": True, "timeout_seconds": 1}
    )

    assert result.startswith("SECURITY BLOCK")
    assert "deadline" in result
    assert exec_calls == [], "an expired operation must not start the installer"
    assert client.container.kill_calls == 1
    assert "c1" not in docker_sandbox._active_containers


def test_airlock_expiry_before_installer_worker_admission_does_not_install(monkeypatch):
    client = _install_airlock_client(monkeypatch)
    client.bridge.attrs = {"Containers": {"cid123": {}}}
    exec_calls = []
    original_thread = threading.Thread

    class DelayedInstallerThread(original_thread):
        def run(self):
            if self._target and self._target.__name__ == "_run_install":
                assert client.container.dead.wait(timeout=5)
            return super().run()

    monkeypatch.setattr(threading, "Thread", DelayedInstallerThread)
    monkeypatch.setattr(client.container, "exec_run", lambda **kwargs: exec_calls.append(True) or (0, b"ok"))
    result = docker_sandbox.tool_install_package(
        {"container_name": "c1", "pkg_manager": "pip", "packages": ["fixture"],
         "allow_network": True, "timeout_seconds": 1}
    )
    assert result.startswith("SECURITY BLOCK")
    assert exec_calls == [], "an expired queued worker must not enter the installer"


@pytest.mark.parametrize("flag", ["expired", "finished", "settled"])
def test_airlock_execution_claim_rejects_terminal_state(monkeypatch, flag):
    from tools import docker_airlock

    op = docker_airlock.AirlockOperation("claim-test", 1, 120)
    monkeypatch.setitem(docker_airlock._generations, op.container_name, op.generation)
    setattr(op, flag, True)
    assert docker_airlock.claim_airlock_execution(op) is False


def test_airlock_execution_claim_is_once_per_current_generation(monkeypatch):
    from tools import docker_airlock

    op = docker_airlock.AirlockOperation("claim-test", 1, 120)
    monkeypatch.setitem(docker_airlock._generations, op.container_name, op.generation)
    assert docker_airlock.claim_airlock_execution(op) is True
    assert docker_airlock.claim_airlock_execution(op) is False
    stale = docker_airlock.AirlockOperation(op.container_name, 0, 120)
    assert docker_airlock.claim_airlock_execution(stale) is False


def test_airlock_disconnect_failure_containment_is_bounded(monkeypatch):
    # When the owned disconnect fails, the kill/remove containment must be a
    # bounded wait too: a hung daemon call cannot outwait the deadline window
    # or hold the per-container lease forever.
    import time

    from tools import docker_airlock

    monkeypatch.setattr(docker_sandbox, "CONTAINMENT_JOIN_SECONDS", 0.5)
    monkeypatch.setattr(docker_airlock, "CONTAINMENT_JOIN_SECONDS", 0.5)
    client = _install_airlock_client(monkeypatch)
    client.container.attrs["NetworkSettings"]["Networks"] = {
        "lab_net": {"NetworkID": "netabc"}
    }

    def failing_disconnect(*args, **kwargs):
        raise RuntimeError("disconnect unavailable")

    kill_started = threading.Event()

    def hanging_kill():
        kill_started.set()
        client.container.dead.wait(timeout=15)  # models a stuck daemon kill

    monkeypatch.setattr(client.bridge, "disconnect", failing_disconnect)
    monkeypatch.setattr(client.container, "kill", hanging_kill, raising=False)

    started = time.monotonic()
    result = docker_sandbox.tool_install_package(
        {"container_name": "c1", "pkg_manager": "pip", "packages": ["curl"],
         "allow_network": True, "timeout_seconds": 120}
    )
    elapsed = time.monotonic() - started

    assert result.startswith("SECURITY BLOCK")
    assert "disconnect failed" in result
    assert "could not be confirmed" in result
    assert elapsed < 10, f"containment must stay bounded, took {elapsed:.1f}s"
    assert "c1" not in docker_sandbox._active_containers
    client.container.dead.set()  # unblock the leaked worker before exiting


@pytest.mark.parametrize("already_on_bridge", [False, True])
def test_airlock_invalid_operator_scope_blocks_install(monkeypatch, already_on_bridge):
    client = _install_airlock_client(monkeypatch)
    monkeypatch.setenv("PAWNLOGIC_DOCKER_EGRESS_ALLOW", "bad host!!")
    if already_on_bridge:
        client.bridge.attrs = {"Containers": {"cid123": {}}}
    monkeypatch.setattr(client.container, "exec_run", lambda **kwargs: pytest.fail("install must not run"))
    result = docker_sandbox.tool_install_package(
        {"container_name": "c1", "pkg_manager": "pip", "packages": ["requests"],
         "allow_network": True}
    )
    assert result.startswith("SECURITY BLOCK: PAWNLOGIC_DOCKER_EGRESS_ALLOW is set but invalid")
    assert client.bridge.connected == []
    assert client.bridge.disconnected == []


def test_airlock_install_requires_authorization_even_when_already_on_bridge(
    monkeypatch,
):
    # apt/pip itself causes outbound traffic, so the policy gate applies
    # even when user-managed networking already attached the container.
    client = _install_airlock_client(monkeypatch)
    client.bridge.attrs = {"Containers": {"cid123": {}}}

    result = docker_sandbox.tool_install_package(
        {"container_name": "c1", "pkg_manager": "pip", "packages": ["requests"]}
    )
    assert result.startswith("SECURITY BLOCK")

    result = docker_sandbox.tool_install_package(
        {
            "container_name": "c1",
            "pkg_manager": "pip",
            "packages": ["requests"],
            "allow_network": True,
        }
    )
    assert result.startswith("[Airlock")
    # Already on bridge: the airlock authorizes but does not touch networking.
    assert client.bridge.connected == []
    assert client.bridge.disconnected == []


def test_docker_network_policy_rejects_container_and_unknown_modes():
    for mode in ("container:victim", "container", "weird", "host:evil"):
        result = docker_sandbox._check_network_policy({"allow_network": True}, mode)
        assert result is not None
        assert result.startswith("SECURITY BLOCK: Docker network=")
        assert "not a supported mode" in result


def test_run_code_docker_blocks_container_network_before_docker(monkeypatch):
    monkeypatch.setattr(
        docker_sandbox,
        "_get_docker_client",
        lambda: (_ for _ in ()).throw(AssertionError("Docker should not be touched")),
    )

    result = docker_sandbox.tool_run_code_docker(
        {"language": "python", "code": "print(1)", "network": "container:victim",
         "allow_network": True}
    )

    assert result.startswith("SECURITY BLOCK: Docker network='container:victim'")


def test_pwn_container_blocks_container_network_before_docker(monkeypatch):
    monkeypatch.setattr(
        docker_sandbox,
        "_get_docker_client",
        lambda: (_ for _ in ()).throw(AssertionError("Docker should not be touched")),
    )

    result = docker_sandbox.tool_pwn_container(
        {"action": "create", "name": "lab", "network": "container:victim",
         "allow_network": True}
    )

    assert result.startswith("SECURITY BLOCK: Docker network='container:victim'")


def test_docker_plan_rejects_unsupported_network_mode_even_when_authorized():
    from tools.docker_plan import build_docker_execution_plan

    plan, error = build_docker_execution_plan(
        {"language": "python", "code": "print(1)", "network": "container:victim",
         "allow_network": True},
        resolve_image=lambda name: name,
        network_error=docker_sandbox._check_network_policy,
        command_error=lambda _code: None,
    )

    assert plan is None
    assert error is not None
    assert error.startswith("SECURITY BLOCK: Docker network='container:victim'")


def test_docker_schemas_enum_matches_supported_network_modes():
    for schema in docker_sandbox.DOCKER_SCHEMAS:
        properties = schema["function"].get("parameters", {}).get("properties", {})
        if "network" not in properties:
            continue
        assert properties["network"]["enum"] == list(docker_plan.SUPPORTED_NETWORK_MODES)


# ── One-shot hardening defaults ──────────────────────────────────────────


def test_spawn_container_harden_defaults_applied_after_deny_check():
    client = _RecordingClient()

    docker_spawn.spawn_container(
        client, image="img", network_mode="none", harden=True
    )

    kwargs = client.containers.calls[0]
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["read_only"] is True
    assert kwargs["tmpfs"] == dict(docker_spawn.HARDENING_TMPFS)

    # An explicit caller value wins over the default via setdefault.
    docker_spawn.spawn_container(
        client, image="img", network_mode="none", harden=True, read_only=False
    )
    assert client.containers.calls[1]["read_only"] is False


def test_spawn_container_harden_never_rescues_forbidden_kwargs():
    client = _RecordingClient()
    with pytest.raises(PermissionError, match="privileged flags forbidden"):
        docker_spawn.spawn_container(
            client, image="img", network_mode="none", harden=True, cap_add=["SYS_ADMIN"]
        )
    assert client.containers.calls == []


class _FakeContainer:
    def __init__(self):
        self.id = "abc123def456"
        self.removed = False

    def wait(self, timeout=None):
        return {"StatusCode": 0}

    def logs(self, stdout=True, stderr=False):
        return b"hello\n" if stdout else b""

    def remove(self, force=False):
        self.removed = True


class _PresentImages:
    def get(self, image):
        return object()


class _FullRecordingContainers(_RecordingContainers):
    def run(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeContainer()


class _FullRecordingClient:
    def __init__(self):
        self.images = _PresentImages()
        self.containers = _FullRecordingContainers()


def test_run_code_docker_applies_hardening_and_nonroot_default(monkeypatch):
    monkeypatch.delenv("PAWNLOGIC_DOCKER_ALLOW_NETWORK", raising=False)
    monkeypatch.delenv("PAWNLOGIC_DOCKER_EGRESS_ALLOW", raising=False)
    client = _FullRecordingClient()
    monkeypatch.setattr(docker_sandbox, "_get_docker_client", lambda: client)

    result = docker_sandbox.tool_run_code_docker(
        {"language": "python", "code": "print(1)"}
    )

    assert result.startswith("[run_code_docker - OK")
    kwargs = client.containers.calls[0]
    assert kwargs["read_only"] is True
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["tmpfs"] == dict(docker_spawn.HARDENING_TMPFS)
    assert kwargs["user"] == f"{os.getuid()}:{os.getgid()}"
    assert "extra_hosts" not in kwargs
    assert "pawn_egress_scope" not in kwargs["labels"]


def test_run_code_docker_install_deps_keep_writable_rootfs_and_root(monkeypatch):
    monkeypatch.delenv("PAWNLOGIC_DOCKER_EGRESS_ALLOW", raising=False)
    client = _FullRecordingClient()
    monkeypatch.setattr(docker_sandbox, "_get_docker_client", lambda: client)

    result = docker_sandbox.tool_run_code_docker(
        {"language": "python", "code": "print(1)", "install_deps": "requests"}
    )

    assert result.startswith("[run_code_docker - OK")
    kwargs = client.containers.calls[0]
    assert kwargs["read_only"] is False
    assert kwargs["cap_drop"] == ["ALL"]
    assert "user" not in kwargs, "pip needs the image default (root) user"


def test_run_code_docker_container_user_arg_and_validation(monkeypatch):
    monkeypatch.delenv("PAWNLOGIC_DOCKER_EGRESS_ALLOW", raising=False)
    client = _FullRecordingClient()
    monkeypatch.setattr(docker_sandbox, "_get_docker_client", lambda: client)

    docker_sandbox.tool_run_code_docker(
        {"language": "python", "code": "print(1)", "container_user": "root"}
    )
    assert client.containers.calls[0]["user"] == "root"

    monkeypatch.setattr(
        docker_sandbox,
        "_get_docker_client",
        lambda: (_ for _ in ()).throw(AssertionError("Docker should not be touched")),
    )
    result = docker_sandbox.tool_run_code_docker(
        {"language": "python", "code": "print(1)", "container_user": "bad user"}
    )
    assert result.startswith("ERROR: invalid container_user")


# ── Operator-declared bridge egress scope ────────────────────────────────


def test_parse_egress_scope_accepts_hosts_ips_cidrs_and_rejects_junk():
    entries, error = docker_egress.parse_egress_scope(
        "pwn.example.com, 203.0.113.5, 10.0.0.0/8 ,dup.example.com dup.example.com"
    )
    assert error is None
    assert entries == (
        "pwn.example.com",
        "203.0.113.5",
        "10.0.0.0/8",
        "dup.example.com",
    )

    entries, error = docker_egress.parse_egress_scope("not a host!")
    assert entries == ()
    assert error is not None and "invalid egress scope entry" in error


def test_resolve_egress_addresses_snapshot_multi_answer(monkeypatch):
    monkeypatch.setenv(
        "PAWNLOGIC_DOCKER_EGRESS_ALLOW", "pwn.example.com,203.0.113.5,10.0.0.0/8"
    )
    monkeypatch.setattr(
        docker_egress,
        "egress_resolver",
        lambda host: ("203.0.113.7", "203.0.113.8"),
    )

    host_addresses, fingerprint, error = docker_egress.resolve_egress_addresses()

    assert error is None
    assert host_addresses == {"pwn.example.com": ("203.0.113.7", "203.0.113.8")}
    assert fingerprint is not None and len(fingerprint) == 12


def test_resolve_egress_addresses_unset_env_is_a_no_op(monkeypatch):
    monkeypatch.delenv("PAWNLOGIC_DOCKER_EGRESS_ALLOW", raising=False)
    host_addresses, fingerprint, error = docker_egress.resolve_egress_addresses()
    assert host_addresses == {} and fingerprint is None and error is None


def test_resolve_egress_addresses_fails_closed_on_bad_entries(monkeypatch):
    monkeypatch.setenv("PAWNLOGIC_DOCKER_EGRESS_ALLOW", "bad host!!")
    host_addresses, fingerprint, error = docker_egress.resolve_egress_addresses()
    assert host_addresses == {} and fingerprint is None
    assert error is not None
    assert error.startswith("SECURITY BLOCK: PAWNLOGIC_DOCKER_EGRESS_ALLOW is set but invalid")

    monkeypatch.setenv("PAWNLOGIC_DOCKER_EGRESS_ALLOW", "missing.example.com")
    def _boom(host):
        raise OSError("resolver down")
    monkeypatch.setattr(docker_egress, "egress_resolver", _boom)
    host_addresses, fingerprint, error = docker_egress.resolve_egress_addresses()
    assert host_addresses == {} and fingerprint is None
    assert error is not None and "could not be resolved at policy time" in error


def test_run_code_docker_scope_forces_offline_proxy_and_labels(monkeypatch):
    monkeypatch.delenv("PAWNLOGIC_DOCKER_ALLOW_NETWORK", raising=False)
    monkeypatch.setenv(
        "PAWNLOGIC_DOCKER_EGRESS_ALLOW", "pwn.example.com,203.0.113.5,10.0.0.0/8"
    )
    monkeypatch.setattr(
        docker_egress, "egress_resolver", lambda host: ("203.0.113.7",)
    )
    client = _FullRecordingClient()
    monkeypatch.setattr(docker_sandbox, "_get_docker_client", lambda: client)

    class Proxy:
        def stop(self):
            pass
    monkeypatch.setattr(docker_sandbox, "start_transport", lambda *args: Proxy())
    monkeypatch.setattr(docker_spawn, "host_uid_gid", lambda: "1000:1000")

    result = docker_sandbox.tool_run_code_docker(
        {
            "language": "python",
            "code": "print(1)",
            "network": "bridge",
            "allow_network": True,
        }
    )

    assert result.startswith("[run_code_docker - OK")
    assert "| egress: enforced HTTP/CONNECT]" in result
    kwargs = client.containers.calls[0]
    assert kwargs["network_mode"] == "none"
    assert "extra_hosts" not in kwargs
    assert len(kwargs["labels"]["pawn_egress_scope"]) == 12


def test_run_code_docker_bridge_scope_failure_blocks_before_docker(monkeypatch):
    monkeypatch.delenv("PAWNLOGIC_DOCKER_ALLOW_NETWORK", raising=False)
    monkeypatch.setenv("PAWNLOGIC_DOCKER_EGRESS_ALLOW", "missing.example.com")
    def _boom(host):
        raise OSError("resolver down")
    monkeypatch.setattr(docker_egress, "egress_resolver", _boom)
    monkeypatch.setattr(
        docker_sandbox,
        "_get_docker_client",
        lambda: (_ for _ in ()).throw(AssertionError("Docker should not be touched")),
    )

    result = docker_sandbox.tool_run_code_docker(
        {"language": "python", "code": "print(1)", "network": "bridge",
         "allow_network": True}
    )
    assert result.startswith("SECURITY BLOCK: egress scope host")


def test_pwn_container_create_scope_user_and_label(monkeypatch):
    monkeypatch.delenv("PAWNLOGIC_DOCKER_ALLOW_NETWORK", raising=False)
    monkeypatch.setenv("PAWNLOGIC_DOCKER_EGRESS_ALLOW", "pwn.example.com")
    monkeypatch.setattr(
        docker_egress, "egress_resolver", lambda host: ("203.0.113.7",)
    )

    client = _FullRecordingClient()
    monkeypatch.setattr(docker_sandbox, "_get_docker_client", lambda: client)
    result = docker_sandbox.tool_pwn_container(
        {
            "action": "create",
            "name": "lab",
            "network": "bridge",
            "allow_network": True,
            "container_user": "1000:1000",
        }
    )

    assert result.startswith("SECURITY BLOCK:")
    assert client.containers.calls == []
    # Without the scope env, create stays unchanged (no host mappings, no label).
    monkeypatch.delenv("PAWNLOGIC_DOCKER_EGRESS_ALLOW", raising=False)
    docker_sandbox.tool_pwn_container(
        {"action": "create", "name": "lab2", "network": "bridge",
         "allow_network": True}
    )
    kwargs = client.containers.calls[0]
    assert "extra_hosts" not in kwargs
    assert "pawn_egress_scope" not in kwargs["labels"]
