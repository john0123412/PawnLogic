"""Tests for Docker sandbox risk policy gates."""

import pytest

from tools import docker_sandbox


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
    monkeypatch.setattr(docker_sandbox, "SAFE_WORKSPACE", str(workspace.resolve()))

    with pytest.raises(PermissionError, match="RO mounts are limited"):
        docker_sandbox._check_path_safety(str(outside), "ro")


def test_docker_ro_mount_outside_workspace_requires_explicit_allow(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "challenge.bin"
    outside.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(docker_sandbox, "SAFE_WORKSPACE", str(workspace.resolve()))

    assert docker_sandbox._check_path_safety(
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
    monkeypatch.setattr(docker_sandbox, "SAFE_WORKSPACE", str(workspace.resolve()))
    monkeypatch.setattr(docker_sandbox, "READ_BLACKLIST", [str(secret_dir)])

    with pytest.raises(PermissionError, match="credentials"):
        docker_sandbox._check_path_safety(
            str(secret_file),
            "ro",
            allow_host_read_mount=True,
        )


def test_docker_mount_blocks_docker_socket(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    socket_path = tmp_path / "docker.sock"
    workspace.mkdir()
    socket_path.write_text("socket placeholder", encoding="utf-8")
    monkeypatch.setattr(docker_sandbox, "SAFE_WORKSPACE", str(workspace.resolve()))

    with pytest.raises(PermissionError, match=r"docker.sock|host control"):
        docker_sandbox._check_path_safety(
            str(socket_path),
            "ro",
            allow_host_read_mount=True,
        )


def test_privilege_flags_rejected_in_tool_args():
    assert docker_sandbox._check_privilege_flags({}) is None
    assert docker_sandbox._check_privilege_flags({"language": "python"}) is None
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
        err = docker_sandbox._check_privilege_flags({flag: True})
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
    docker_sandbox._spawn_container(client, image="img", network_mode="none")
    assert client.containers.calls, "expected one containers.run call"
    assert not (
        set(client.containers.calls[0]) & docker_sandbox._FORBIDDEN_CONTAINER_KWARGS
    )

    with pytest.raises(PermissionError, match="privileged flags forbidden"):
        docker_sandbox._spawn_container(client, image="img", privileged=True)
    with pytest.raises(PermissionError, match="privileged flags forbidden"):
        docker_sandbox._spawn_container(client, image="img", cap_add=["SYS_PTRACE"])
    # CLI-style aliases must not dodge the choke point either.
    with pytest.raises(PermissionError, match="privileged flags forbidden"):
        docker_sandbox._spawn_container(client, **{"cap-add": ["SYS_PTRACE"]})
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
