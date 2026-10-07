"""Tests for Docker sandbox risk policy gates."""

import os

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

    def reload(self):
        if self.reload_error is not None:
            raise self.reload_error

    def exec_run(self, cmd, stdout=True, stderr=True, demux=False):
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
