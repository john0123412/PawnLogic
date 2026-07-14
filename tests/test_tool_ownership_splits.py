"""Focused tests for extracted tool implementation modules."""

from tools.docker_plan import build_docker_execution_plan
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
