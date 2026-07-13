"""tests/test_codex_goal_run.py - Tests for tools/codex_goal_run.sh."""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "codex_goal_run.sh"


def _run(
    args: list[str], cwd: Path, timeout: int = 60, **kwargs
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        **kwargs,
    )


class TestCodexGoalRun:
    """Tests for the codex goal runner script."""

    def test_help(self, tmp_path: Path) -> None:
        result = _run(["--help"], tmp_path)
        assert result.returncode == 0
        assert "goal" in result.stdout.lower()

    def test_missing_goal_fails(self, tmp_path: Path) -> None:
        result = _run([], tmp_path)
        assert result.returncode != 0
        combined = (result.stdout + result.stderr).lower()
        assert "required" in combined or "error" in combined

    def test_main_branch_refused(self, tmp_path: Path) -> None:
        # Create a git repo on main branch.
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        (tmp_path / "dummy.txt").write_text("test")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True
        )

        result = _run(["--goal", "test"], tmp_path)
        assert result.returncode != 0
        combined = (result.stdout + result.stderr).lower()
        assert "main" in combined or "refuse" in combined

    def test_real_api_requires_max_api_calls(self, tmp_path: Path) -> None:
        # Create a git repo on feature branch.
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        (tmp_path / "dummy.txt").write_text("test")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True
        )
        subprocess.run(
            ["git", "checkout", "-b", "feature"], cwd=str(tmp_path), capture_output=True
        )

        result = _run(["--goal", "test", "--real-api"], tmp_path)
        assert result.returncode != 0
        combined = (result.stdout + result.stderr).lower()
        assert "max-api-calls" in combined

    def test_creates_output_directory(self, tmp_path: Path) -> None:
        # Create a git repo on feature branch.
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        (tmp_path / "dummy.txt").write_text("test")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True
        )
        subprocess.run(
            ["git", "checkout", "-b", "feature"], cwd=str(tmp_path), capture_output=True
        )

        output_dir = tmp_path / "test_output"
        _run(
            [
                "--goal",
                "test goal",
                "--output-dir",
                str(output_dir),
                "--max-wall-seconds",
                "5",
            ],
            tmp_path,
        )
        assert output_dir.exists()
        assert (output_dir / "manifest.json").exists()
        assert (output_dir / "heartbeat.log").exists()

    def test_lock_prevents_concurrent_runs(self, tmp_path: Path) -> None:
        # Create a git repo on feature branch.
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        (tmp_path / "dummy.txt").write_text("test")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True
        )
        subprocess.run(
            ["git", "checkout", "-b", "feature"], cwd=str(tmp_path), capture_output=True
        )

        output_dir = tmp_path / "test_output"
        output_dir.mkdir()
        # Use current PID to simulate an active lock.
        import os

        (output_dir / ".lock").write_text(str(os.getpid()))

        result = _run(["--goal", "test", "--output-dir", str(output_dir)], tmp_path)
        assert result.returncode != 0
        combined = (result.stdout + result.stderr).lower()
        assert "active" in combined or "lock" in combined
