"""Deterministic bounded soak workload and local resource-growth checks."""

from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import time

from tools.eval.scenarios.offline import run_offline_replay


def _fd_count() -> int:
    fd_root = Path("/proc/self/fd")
    return len(tuple(fd_root.iterdir())) if fd_root.exists() else 0


def run_soak(
    fixtures_dir: Path,
    *,
    max_duration_seconds: float,
    iterations: int = 25,
) -> dict[str, object]:
    """Repeat replay while enforcing a total deadline and resource budgets."""
    start = time.monotonic()
    deadline = start + max_duration_seconds
    threads_before = threading.active_count()
    fds_before = _fd_count()
    with tempfile.TemporaryDirectory(prefix="pawnlogic-soak-") as tmp:
        temp_root = Path(tmp)
        for iteration in range(iterations):
            if time.monotonic() >= deadline:
                return {
                    "status": "timed_out",
                    "summary": "Soak exhausted its total wall-clock budget.",
                    "api_calls": 0,
                    "tool_calls": iteration,
                    "failure_class": "SoakBudgetExceeded",
                }
            outcome = run_offline_replay(fixtures_dir)
            if outcome["status"] != "passed":
                return outcome
            marker = temp_root / f"iteration-{iteration}.tmp"
            marker.write_text("ok", encoding="utf-8")
            marker.unlink()
        temp_growth = len(tuple(temp_root.iterdir()))
    thread_growth = threading.active_count() - threads_before
    fd_growth = _fd_count() - fds_before
    passed = thread_growth <= 1 and fd_growth <= 2 and temp_growth == 0
    return {
        "status": "passed" if passed else "failed",
        "summary": (
            f"Completed {iterations} deterministic iterations; thread growth "
            f"{thread_growth}, fd growth {fd_growth}, temp growth {temp_growth}."
        ),
        "api_calls": 0,
        "tool_calls": iterations,
        "failure_class": "" if passed else "SoakResourceGrowth",
    }


__all__ = ["run_soak"]
