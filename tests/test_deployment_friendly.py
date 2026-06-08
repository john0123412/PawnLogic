"""Deployment-friendly startup regression tests."""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from importlib.metadata import PathDistribution
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent


def _clean_runtime_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "HOME": str(tmp_path / "home"),
        "PAWNLOGIC_HOME": str(tmp_path / "home" / ".pawnlogic"),
        "MCP_ENABLED": "false",
        "PROMPT_TOOLKIT_ENABLED": "0",
        "PAWNLOGIC_TEST_MODE": "false",
        "TERM": "dumb",
        "NO_COLOR": "1",
    })
    for key in [
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "PAWN_API_KEY",
    ]:
        env.pop(key, None)
    return env


def test_paths_fall_back_when_home_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.delenv("PAWNLOGIC_HOME", raising=False)
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    spec = importlib.util.spec_from_file_location(
        "paths_under_no_home_test",
        ROOT / "config" / "paths.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader

    with patch("pathlib.Path.home", side_effect=RuntimeError("no home")):
        spec.loader.exec_module(module)

    assert module.PAWNLOGIC_HOME == tmp_path / ".pawnlogic"


def test_pawn_sh_uses_detected_dot_venv_python(tmp_path):
    shutil.copy(ROOT / "pawn.sh", tmp_path / "pawn.sh")
    (tmp_path / "main.py").write_text("print('should not run real python')\n", encoding="utf-8")
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "activate").write_text("export VIRTUAL_ENV=dotvenv\n", encoding="utf-8")
    fake_python = venv_bin / "python3"
    fake_python.write_text("#!/bin/sh\necho DOTVENV \"$@\"\n", encoding="utf-8")
    fake_python.chmod(fake_python.stat().st_mode | stat.S_IXUSR)
    (tmp_path / "pawn.sh").chmod(0o755)

    result = subprocess.run(
        [str(tmp_path / "pawn.sh"), "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    assert result.stdout.startswith("DOTVENV ")
    assert str(tmp_path / "main.py") in result.stdout


def test_pawn_sh_is_executable_in_checkout():
    mode = ROOT.joinpath("pawn.sh").stat().st_mode
    assert mode & stat.S_IXUSR


def test_pawn_symlink_launcher_executes_checkout_script(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    shutil.copy(ROOT / "pawn.sh", project / "pawn.sh")
    shutil.copy(ROOT / "main.py", project / "main.py")
    (project / "pawn.sh").chmod(0o755)

    venv_bin = project / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "activate").write_text("export VIRTUAL_ENV=venv\n", encoding="utf-8")
    fake_python = venv_bin / "python3"
    fake_python.write_text("#!/bin/sh\necho SYMLINK_PAWN \"$@\"\n", encoding="utf-8")
    fake_python.chmod(fake_python.stat().st_mode | stat.S_IXUSR)

    local_bin = tmp_path / "user_bin"
    local_bin.mkdir(parents=True)
    (local_bin / "pawn").symlink_to(project / "pawn.sh")

    result = subprocess.run(
        [str(local_bin / "pawn"), "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    assert result.stdout.startswith("SYMLINK_PAWN ")
    assert str(project / "main.py") in result.stdout


def test_packaging_entry_point_uses_package_cli():
    dist = PathDistribution.at(ROOT / "pawnlogic.egg-info")
    scripts = [ep for ep in dist.entry_points if ep.group == "console_scripts"]

    assert any(
        ep.name == "pawn" and ep.value == "pawnlogic.cli:run"
        for ep in scripts
    )


def test_built_wheel_does_not_ship_top_level_main_module():
    wheels = sorted((ROOT / "dist").glob("pawnlogic-*.whl"))
    assert wheels, "run `python -m build` before this deployment check"

    with zipfile.ZipFile(wheels[-1]) as wheel:
        names = set(wheel.namelist())

    assert "main.py" not in names
    assert "pawnlogic/cli.py" in names
    assert "pawnlogic/__main__.py" in names


def test_json_first_run_exits_with_clean_json_error(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "--json", "--eval", "hello"],
        cwd=ROOT,
        env=_clean_runtime_env(tmp_path),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )

    assert result.returncode == 2
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["type"] == "json"
    assert payload["data"]["type"] == "error"
    assert payload["data"]["stage"] == "startup"


def test_first_run_gate_accepts_process_env_key_without_dot_env_file(tmp_path):
    """Regression: gate must not require ~/.pawnlogic/.env to exist when the
    API key is already in process env (Docker / CI / K8s scenario).

    Pre-fix, _first_run_required short-circuited on `not _ENV_PATH.exists()`,
    falsely blocking users who inject keys via env vars without writing a file.
    """
    env = _clean_runtime_env(tmp_path)
    # No .env file is created; key only lives in process env.
    env["DEEPSEEK_API_KEY"] = "sk-test-fake-key-for-gate-regression"

    result = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "--json", "--eval", "x"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=15,
    )

    # The gate's user-facing signature is the wizard prompt; any sign of it
    # in stdout means the regression has returned.
    assert "首次运行需要先完成 API 配置向导" not in result.stdout, (
        "first_run gate fired even though DEEPSEEK_API_KEY was in process env "
        "— regression of pre-0.0.6 bug. stdout: " + result.stdout[:500]
    )


def test_first_run_gate_treats_custom_provider_keys_uniformly(tmp_path):
    """Regression: gate must treat custom providers (loaded from
    custom_providers.json) the same as built-in providers — no name is
    hardcoded.

    Setup: only XIAOMI_API_KEY in env (a custom provider), no built-in
    provider key. Pre-fix, the gate ignored custom providers because
    _has_any_api_key() iterated PROVIDERS before custom_providers were merged.
    Post-fix the merge happens at config.providers import time, so the gate
    accepts the custom key.
    """
    pawn_home = Path(tmp_path) / "home" / ".pawnlogic"
    pawn_home.mkdir(parents=True, exist_ok=True)
    # Minimal custom_providers.json registering one provider with key env name.
    (pawn_home / "custom_providers.json").write_text(
        json.dumps({
            "providers": {
                "xiaomi": {
                    "base_url": "https://example.invalid/v1",
                    "api_key_env": "XIAOMI_API_KEY",
                    "label": "Custom (xiaomi)",
                    "api_format": "openai",
                }
            },
            "models": {}
        }),
        encoding="utf-8",
    )

    env = _clean_runtime_env(tmp_path)
    env.pop("XIAOMI_API_KEY", None)  # ensure clean baseline
    env["XIAOMI_API_KEY"] = "tp-test-fake-key-for-custom-provider-regression"

    result = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "--json", "--eval", "x"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=15,
    )

    assert "首次运行需要先完成 API 配置向导" not in result.stdout, (
        "first_run gate fired with only a custom-provider key set — "
        "custom providers should be treated like built-ins. stdout: "
        + result.stdout[:500]
    )


def test_first_run_wizard_sets_selected_model_and_secures_env(tmp_path):
    env = _clean_runtime_env(tmp_path)
    result = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "--quiet"],
        cwd=ROOT,
        env=env,
        input="2\nsk-test-openai\n/exit\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0
    assert "model=gpt-5.4-mini" in result.stdout

    env_path = Path(env["PAWNLOGIC_HOME"]) / ".env"
    assert env_path.read_text(encoding="utf-8").strip().endswith("OPENAI_API_KEY=sk-test-openai")
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600


def test_latest_documented_model_aliases_are_registered():
    from config.providers import MODELS

    for alias in [
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "claude-opus",
        "claude-sonnet",
        "claude-haiku",
        "ds-v4-flash",
        "ds-v4-pro",
    ]:
        assert alias in MODELS

    for doc in ["README.md", "README_CN.md", "GUIDE_EN.md", "GUIDE_CN.md"]:
        assert "claude-opus-4-8" not in (ROOT / doc).read_text(encoding="utf-8")


def test_pwn_debug_disables_user_gdbinit_by_default(tmp_path, monkeypatch):
    cached = sys.modules.get("tools.pwn_chain")
    cached_file = getattr(cached, "__file__", "") if cached is not None else ""
    if cached is not None and str(ROOT) not in cached_file:
        del sys.modules["tools.pwn_chain"]
        tools_pkg = sys.modules.get("tools")
        if tools_pkg is not None and hasattr(tools_pkg, "pwn_chain"):
            delattr(tools_pkg, "pwn_chain")

    from tools import pwn_chain

    binary = tmp_path / "target' name"
    binary.write_text("not really an elf", encoding="utf-8")
    binary.chmod(0o755)
    captured = {}

    monkeypatch.setattr(pwn_chain, "_check_read", lambda path: (True, ""))
    monkeypatch.setattr(pwn_chain.shutil, "which", lambda name: "/usr/bin/gdb")

    def fake_run(cmd, timeout=30, cwd=None):
        captured["cmd"] = cmd
        return "Breakpoint 1, main ()\nrip 0x401000\n"

    monkeypatch.setattr(pwn_chain, "_run", fake_run)

    out = pwn_chain.tool_pwn_debug({
        "path": str(binary),
        "breakpoints": ["main"],
        "commands": ["info registers rip"],
    })

    assert "gdb -nx -batch" in captured["cmd"]
    assert str(binary) in shlex.split(captured["cmd"])
    assert "Breakpoint" in out


def test_pwn_chain_quotes_binary_paths_and_filters(tmp_path, monkeypatch):
    cached = sys.modules.get("tools.pwn_chain")
    cached_file = getattr(cached, "__file__", "") if cached is not None else ""
    if cached is not None and str(ROOT) not in cached_file:
        del sys.modules["tools.pwn_chain"]
        tools_pkg = sys.modules.get("tools")
        if tools_pkg is not None and hasattr(tools_pkg, "pwn_chain"):
            delattr(tools_pkg, "pwn_chain")

    from tools import pwn_chain

    binary = tmp_path / "bin' ; touch owned ; 'x"
    binary.write_bytes(b"\x7fELF")
    commands: list[str] = []

    monkeypatch.setattr(pwn_chain, "_check_read", lambda path: (True, ""))
    monkeypatch.setattr(pwn_chain, "_run", lambda cmd, *a, **kw: commands.append(cmd) or "")
    pwn_chain._ELF_CACHE.clear()

    pwn_chain.tool_inspect_binary({
        "path": str(binary),
        "strings_grep": "needle' ; echo owned ; 'x",
    })

    split_file_cmd = shlex.split(commands[0])
    assert split_file_cmd == ["file", str(binary)]

    split_strings_cmd = shlex.split(next(cmd for cmd in commands if cmd.startswith("strings ")))
    assert str(binary) in split_strings_cmd
    assert "needle' ; echo owned ; 'x" in split_strings_cmd
