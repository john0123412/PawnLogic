"""Regression tests for tools/precommit.sh leak-scan gating.

These spawn a throwaway git repository and run the real script, because
the failure being pinned is a shell-pipeline interaction (`grep -vF ""`
matching every line), not Python logic. The historical bug: when
tools/precommit.sh itself was staged with a deletion-only diff, the
self-exclusion filter collapsed the ENTIRE scan to zero lines and a real
API key staged in a sibling file passed with exit 0.

Trigger literals below are assembled at runtime so that this test file
does not itself trip the scanner it exercises.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "precommit.sh"

FAKE_KEY = "sk-proj-" + "abcdefghijklmnopqrstuvwx"
FAKE_AWS_ID = "AKIA" + "IOSFODNN7EXAMPLE"
FAKE_HOME = "/home/" + "someone/x"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture()
def script_repo(tmp_path: Path) -> Path:
    """A throwaway git repo holding a committed copy of precommit.sh."""
    if shutil.which("git") is None:
        pytest.skip("git not available")
    (tmp_path / "tools").mkdir()
    shutil.copy(SCRIPT, tmp_path / "tools" / "precommit.sh")
    _git(tmp_path, "init", "-q", ".")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "add", "tools/precommit.sh")
    _git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def _run_precommit(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "tools/precommit.sh"],
        cwd=repo,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )


def _stage(repo: Path, name: str, text: str) -> None:
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", name)


def test_leak_scan_blocks_api_key_in_sibling_file(script_repo):
    _stage(script_repo, "notes.txt", f'TOKEN = "{FAKE_KEY}"\n')

    result = _run_precommit(script_repo)

    assert result.returncode == 1
    assert "provider API key" in result.stdout


def test_leak_scan_survives_deletion_only_precommit_self_change(script_repo):
    """The pinned P1: a deletion-only precommit.sh edit must not disable
    the scan for other staged files."""
    script = script_repo / "tools" / "precommit.sh"
    lines = script.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [line for line in lines if "all checks passed" not in line]
    assert len(kept) < len(lines), "precommit.sh layout changed; update this test"
    script.write_text("".join(kept), encoding="utf-8")
    _git(script_repo, "add", "tools/precommit.sh")
    _stage(script_repo, "notes.txt", f'TOKEN = "{FAKE_KEY}"\n')

    result = _run_precommit(script_repo)

    assert result.returncode == 1, result.stdout
    assert "provider API key" in result.stdout


def test_self_pattern_literals_do_not_trip_the_scan(script_repo):
    """Appending the script's own pattern literals must still pass: the
    scanner excludes its own file by pathspec, not by content matching."""
    script = script_repo / "tools" / "precommit.sh"
    with script.open("a", encoding="utf-8") as fh:
        fh.write(f"# touch {FAKE_HOME} {FAKE_AWS_ID}\n")
    _stage(script_repo, "clean.txt", "hello\n")
    _git(script_repo, "add", "tools/precommit.sh")

    result = _run_precommit(script_repo)

    assert result.returncode == 0, result.stdout


def test_leak_scan_blocks_absolute_local_path(script_repo):
    _stage(script_repo, "notes.txt", f"log = {FAKE_HOME}private.log\n")

    result = _run_precommit(script_repo)

    assert result.returncode == 1
    assert "absolute local path" in result.stdout


def test_no_files_staged_passes(script_repo):
    result = _run_precommit(script_repo)

    assert result.returncode == 0
    assert "all checks passed" in result.stdout
