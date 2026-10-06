"""Focused tests for extracted tool implementation modules."""

import pytest

from tools.docker_egress import parse_egress_scope, resolve_egress_scope
from tools.docker_mounts import check_path_safety
from tools.docker_plan import build_docker_execution_plan
from tools.docker_spawn import (
    HARDENING_TMPFS,
    check_privilege_flags,
    spawn_container,
)
from tools.pwn_binary import ElfAnalysisCache, cyclic_result
from tools.pwn_debugger import build_gdb_plan
from tools.text_patch import apply_patch_blocks, find_search_in_file


def test_docker_plan_builds_without_touching_docker():
    plan, error = build_docker_execution_plan(
        {"language": "python", "code": "print(1)", "install_deps": "httpx==1.0"},
        resolve_image=lambda image: f"resolved:{image}",
        network_error=lambda _args, _network: None,
        command_error=lambda _command: None,
    )
    assert error is None
    assert plan is not None
    assert plan.image == "resolved:python"
    assert plan.network == "none"
    assert plan.command.startswith("pip install httpx==1.0 -q")


def test_docker_plan_rejects_before_sdk_calls():
    plan, error = build_docker_execution_plan(
        {"language": "python", "code": "unsafe"},
        resolve_image=lambda image: image,
        network_error=lambda _args, _network: None,
        command_error=lambda _command: "SECURITY BLOCK: test",
    )
    assert plan is None
    assert error == "SECURITY BLOCK: test"


def test_elf_cache_invalidates_on_mtime_change(tmp_path):
    binary = tmp_path / "target"
    binary.write_text("one", encoding="utf-8")
    cache = ElfAnalysisCache(max_entries=2)
    cache.set(str(binary), "inspect", "cached")
    assert cache.get(str(binary), "inspect") == "cached"
    stat = binary.stat()
    binary.touch()
    if binary.stat().st_mtime == stat.st_mtime:
        binary.write_text("two", encoding="utf-8")
    assert cache.get(str(binary), "inspect") in {None, "cached"}


def test_cyclic_and_gdb_plans_preserve_public_shapes():
    generated = cyclic_result({"action": "gen", "length": 8})
    assert generated.startswith("Cyclic (8 bytes):\n")
    plan = build_gdb_plan(
        breakpoints=["main", "0x401000"],
        commands=["info registers"],
        input_file="/tmp/input",
    )
    assert "b main" in plan.script_lines
    assert "b *0x401000" in plan.script_lines
    assert "run < '/tmp/input'" in plan.script_lines
    assert plan.interactive_inputs[-1] == "quit\n"


def test_text_patch_engine_uses_injected_path_policy(tmp_path):
    target = tmp_path / "sample.py"
    target.write_text("def old():\n    return 1\n", encoding="utf-8")
    result = apply_patch_blocks(
        str(target),
        "<<<<<<< SEARCH\ndef old():\n    return 1\n=======\ndef new():\n    return 2\n>>>>>>> REPLACE",
        resolve_write_path=lambda path: (path, ""),
        check_write=lambda _path: (True, ""),
    )
    assert result.startswith("OK: applied 1/1")
    assert target.read_text(encoding="utf-8") == "def new():\n    return 2\n"
    assert find_search_in_file(["  x\n"], "x") == (0, 1)


def test_docker_spawn_funnel_denies_privileges_and_merges_hardening():
    class _Recording:
        def __init__(self):
            self.calls = []

        def run(self, **kwargs):
            self.calls.append(kwargs)
            return object()

    class _Client:
        def __init__(self):
            self.containers = _Recording()

    client = _Client()
    spawn_container(client, image="img", network_mode="none", harden=True)
    kwargs = client.containers.calls[0]
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["read_only"] is True
    assert kwargs["tmpfs"] == dict(HARDENING_TMPFS)
    with pytest.raises(PermissionError, match="privileged flags forbidden"):
        spawn_container(client, image="img", harden=True, cap_add=["SYS_ADMIN"])
    assert check_privilege_flags({"cap-drop": True}) is not None
    assert check_privilege_flags({"language": "python"}) is None


def test_docker_egress_scope_parses_and_pins_without_docker(monkeypatch):
    entries, error = parse_egress_scope("pwn.example.com, 10.0.0.0/8")
    assert error is None
    assert entries == ("pwn.example.com", "10.0.0.0/8")

    monkeypatch.setenv("PAWNLOGIC_DOCKER_EGRESS_ALLOW", "pwn.example.com")
    monkeypatch.setattr(
        "tools.docker_egress.egress_resolver", lambda host: ("203.0.113.7",)
    )
    pins, fingerprint, resolve_error = resolve_egress_scope()
    assert resolve_error is None
    assert pins == {"pwn.example.com": "203.0.113.7"}
    assert len(fingerprint) == 12


def test_docker_mount_policy_keeps_rw_inside_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    inside = workspace / "challenge.bin"
    inside.write_text("fixture", encoding="utf-8")
    outside = tmp_path / "outside.bin"
    outside.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr("tools.docker_mounts.SAFE_WORKSPACE", str(workspace.resolve()))

    assert check_path_safety(str(inside), "ro") == str(inside.resolve())
    with pytest.raises(PermissionError, match="RW mode is limited"):
        check_path_safety(str(outside), "rw")
