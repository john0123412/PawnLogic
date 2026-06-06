"""Deployment-friendly startup regression tests."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent


def _clean_runtime_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "HOME": str(tmp_path / "home"),
        "PAWNLOGIC_HOME": str(tmp_path / "home" / ".pawnlogic"),
        "MCP_ENABLED": "false",
        "PROMPT_TOOLKIT_ENABLED": "0",
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

    binary = tmp_path / "target"
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
    assert "Breakpoint" in out
