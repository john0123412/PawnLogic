"""Focused tests for extracted tool implementation modules."""

import pytest

from tools.docker_airlock import offline_attach_rejection
from tools.docker_egress import parse_egress_scope, resolve_egress_addresses
from tools.docker_mounts import check_path_safety
from tools.docker_plan import build_docker_execution_plan
from tools.docker_spawn import (
    HARDENING_TMPFS,
    check_privilege_flags,
    spawn_container,
)
from tools.docker_preflight import build_preflight_report, classify_container_network
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


class _InspectOnlyContainer:
    def __init__(self, attrs, reload_error=None):
        self.attrs = attrs
        self._reload_error = reload_error

    def reload(self):
        if self._reload_error is not None:
            raise self._reload_error


def test_offline_attach_guard_rejects_offline_and_allows_attached():
    offline = offline_attach_rejection(_InspectOnlyContainer({}), "c1")
    assert offline is not None
    assert offline.startswith("SECURITY BLOCK")

    malformed = offline_attach_rejection(_InspectOnlyContainer(None), "c1")
    assert malformed is not None
    assert malformed.startswith("SECURITY BLOCK")

    attached = offline_attach_rejection(
        _InspectOnlyContainer(
            {"NetworkSettings": {"Networks": {"lab": {"NetworkID": "n1"}}}}
        ),
        "c1",
    )
    assert attached is None


def _net_attrs(networks, mode=None):
    attrs = {"NetworkSettings": {"Networks": networks}}
    if mode:
        attrs["HostConfig"] = {"NetworkMode": mode}
    return attrs


def test_preflight_classification_covers_membership_kinds():
    assert classify_container_network(_net_attrs({"bridge": {"NetworkID": "b"}})) == "bridge"
    assert classify_container_network(_net_attrs({"lab": {"NetworkID": "u"}}, mode="lab")) == "other"
    # Real daemon shapes for host mode: explicit NetworkMode and a live
    # "host" endpoint with a populated NetworkID.
    assert classify_container_network(_net_attrs({}, mode="host")) == "host"
    assert classify_container_network(_net_attrs({"host": {"NetworkID": "h"}})) == "host"
    assert classify_container_network(_net_attrs({"none": {"NetworkID": "n"}})) == "none"
    assert classify_container_network(_net_attrs({})) == "unknown"
    assert classify_container_network(None) == "unknown"
    assert classify_container_network({"NetworkSettings": "junk"}) == "unknown"
    assert classify_container_network(
        {"NetworkSettings": {"Networks": ["bridge"]}}
    ) == "unknown"


def test_preflight_classification_prefers_real_attachment_over_none():
    # A container attached to both none and a real network is network-capable.
    attrs = _net_attrs({"none": {"NetworkID": "n"}, "bridge": {"NetworkID": "b"}})
    assert classify_container_network(attrs) == "bridge"
    # Malformed entries never mask a live attachment.
    attrs = _net_attrs({"bridge": "junk", "lab": {"NetworkID": "u"}})
    assert classify_container_network(attrs) == "other"


def test_preflight_report_flags_risky_and_explains_no_quarantine():
    report = build_preflight_report(
        [("legacy", "running", "bridge"), ("offline", "running", "none")]
    )
    assert "legacy" in report and "NEEDS ATTENTION" in report
    assert "does not quarantine" in report

    clean = build_preflight_report([("offline", "running", "none")])
    assert "No running PawnLogic-labelled container" in clean


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


def test_docker_egress_scope_parses_and_maps_without_docker(monkeypatch):
    entries, error = parse_egress_scope("pwn.example.com, 10.0.0.0/8")
    assert error is None
    assert entries == ("pwn.example.com", "10.0.0.0/8")

    monkeypatch.setenv("PAWNLOGIC_DOCKER_EGRESS_ALLOW", "pwn.example.com")
    monkeypatch.setattr(
        "tools.docker_egress.egress_resolver", lambda host: ("203.0.113.7",)
    )
    host_addresses, fingerprint, resolve_error = resolve_egress_addresses()
    assert resolve_error is None
    assert host_addresses == {"pwn.example.com": ("203.0.113.7",)}
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
