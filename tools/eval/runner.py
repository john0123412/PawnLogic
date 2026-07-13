"""tools/eval/runner.py - Runtime evaluation runner with deadline enforcement.

Executes evaluation scenarios with real wall-clock deadline enforcement,
child-process isolation on POSIX, and consistent timeout classification.
"""

from __future__ import annotations

import contextlib
import multiprocessing
import os
import queue as queue_module
import subprocess
import time
from collections.abc import Callable, Sequence

from tools.eval.contracts import EvalBudget, RuntimeEvalRecord
from tools.eval.redaction import redact_summary
from tools.eval.artifacts import unique_run_id

SCHEMA_VERSION = 1
_IS_POSIX = os.name == "posix"
_VALID_STATUSES = frozenset({"passed", "failed", "timed_out", "skipped"})


def _duration_ms(start: float, end: float) -> int:
    return max(0, int((end - start) * 1000))


def _run_in_child(
    scenario_fn: Callable[[], dict], result_queue: multiprocessing.Queue
) -> None:
    """Run scenario_fn in a child process and put the result in the queue."""
    try:
        result = scenario_fn()
        result_queue.put(("ok", result))
    except subprocess.TimeoutExpired as exc:
        result_queue.put(
            (
                "ok",
                {
                    "status": "timed_out",
                    "summary": str(exc),
                    "api_calls": 0,
                    "tool_calls": 0,
                    "failure_class": "TimeoutExpired",
                },
            )
        )
    except Exception as exc:
        result_queue.put(
            (
                "error",
                {
                    "status": "failed",
                    "summary": str(exc),
                    "api_calls": 0,
                    "tool_calls": 0,
                    "failure_class": type(exc).__name__,
                },
            )
        )


def run_scenario_with_deadline(
    scenario_fn: Callable[[], dict],
    *,
    deadline: float,
    now: Callable[[], float] = time.monotonic,
) -> dict:
    """Run a scenario with a real wall-clock deadline.

    On POSIX systems, executes the scenario in a child process so that
    timed-out scenarios can be terminated and killed, ensuring no worker
    remains alive.
    """
    remaining = deadline - now()
    if remaining <= 0:
        return {
            "status": "timed_out",
            "summary": "Budget exhausted before scenario started.",
            "api_calls": 0,
            "tool_calls": 0,
            "failure_class": "BudgetExhausted",
        }

    # A post-return elapsed-time check is not a hard deadline. Use an isolated
    # child for every real-clock POSIX run so a stuck scenario can be stopped.
    # Deterministic tests may inject a synthetic clock and remain in-process.
    if _IS_POSIX and now is time.monotonic:
        return _run_in_child_with_deadline(scenario_fn, remaining)

    # Same-process execution with elapsed-time check.
    start = now()
    try:
        result = scenario_fn()
        elapsed = now() - start
        if elapsed > remaining:
            return {
                "status": "timed_out",
                "summary": f"Scenario exceeded deadline ({elapsed:.1f}s > {remaining:.1f}s).",
                "api_calls": 0,
                "tool_calls": 0,
                "failure_class": "DeadlineExceeded",
            }
        return (
            result
            if isinstance(result, dict)
            else {
                "status": "passed",
                "summary": str(result),
                "api_calls": 0,
                "tool_calls": 0,
                "failure_class": "",
            }
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timed_out",
            "summary": str(exc),
            "api_calls": 0,
            "tool_calls": 0,
            "failure_class": "TimeoutExpired",
        }
    except Exception as exc:
        return {
            "status": "failed",
            "summary": str(exc),
            "api_calls": 0,
            "tool_calls": 0,
            "failure_class": type(exc).__name__,
        }


def _run_in_child_with_deadline(
    scenario_fn: Callable[[], dict],
    timeout: float,
) -> dict:
    """Run scenario in a child process with hard deadline enforcement."""
    result_queue: multiprocessing.Queue = multiprocessing.Queue()
    proc = multiprocessing.Process(
        target=_run_in_child, args=(scenario_fn, result_queue), daemon=True
    )
    proc.start()

    try:
        proc.join(timeout=timeout)
    except KeyboardInterrupt:
        _terminate_process(proc)
        return {
            "status": "failed",
            "summary": "Scenario interrupted by user.",
            "api_calls": 0,
            "tool_calls": 0,
            "failure_class": "KeyboardInterrupt",
        }

    if proc.is_alive():
        _terminate_process(proc)
        return {
            "status": "timed_out",
            "summary": f"Scenario exceeded {timeout:.1f}s deadline.",
            "api_calls": 0,
            "tool_calls": 0,
            "failure_class": "DeadlineExceeded",
        }

    try:
        status, result = result_queue.get(timeout=1.0)
        if status == "ok" and isinstance(result, dict):
            return result
        return result
    except queue_module.Empty:
        pass

    return {
        "status": "failed",
        "summary": "Scenario produced no output.",
        "api_calls": 0,
        "tool_calls": 0,
        "failure_class": "NoOutput",
    }


def _terminate_process(proc: multiprocessing.Process) -> None:
    """Terminate then kill a process, ensuring no worker remains alive."""
    with contextlib.suppress(ProcessLookupError, OSError):
        proc.terminate()
    proc.join(timeout=5)
    if proc.is_alive():
        with contextlib.suppress(ProcessLookupError, OSError):
            proc.kill()
        proc.join(timeout=2)


def run_suite(
    scenarios: Sequence[Callable[[], dict]],
    *,
    budget: EvalBudget,
    run_id: str | None = None,
    stop_on_first_failure: bool = False,
    now: Callable[[], float] = time.monotonic,
) -> list[RuntimeEvalRecord]:
    """Run evaluation scenarios with budget enforcement.

    Each scenario is a callable that returns a dict with:
    - status: "passed" | "failed" | "timed_out"
    - summary: human-readable summary
    - api_calls: number of API calls made
    - tool_calls: number of tool calls made
    - failure_class: exception class name on failure
    """
    if budget.max_duration_seconds <= 0:
        raise ValueError("max_duration_seconds must be positive")
    if budget.max_api_calls < 0:
        raise ValueError("max_api_calls must be non-negative")

    rid = run_id or unique_run_id()
    deadline = now() + budget.max_duration_seconds
    records: list[RuntimeEvalRecord] = []
    total_api_calls = 0

    for i, scenario_fn in enumerate(scenarios):
        scenario_id = getattr(scenario_fn, "__name__", f"scenario_{i}")

        start = now()
        result = run_scenario_with_deadline(scenario_fn, deadline=deadline, now=now)
        elapsed = now() - start

        api_calls = int(result.get("api_calls", 0))
        total_api_calls += api_calls
        status = str(result.get("status", "failed"))
        failure_class = str(result.get("failure_class", ""))
        summary = str(result.get("summary", ""))
        if status not in _VALID_STATUSES:
            status = "failed"
            failure_class = "UnknownStatus"
            summary = "Scenario returned an unsupported status."
        if total_api_calls > budget.max_api_calls:
            status = "failed"
            failure_class = "ApiCallBudgetExceeded"
            summary = f"Budget exceeded ({budget.max_api_calls} API calls allowed)."

        records.append(
            RuntimeEvalRecord(
                schema_version=SCHEMA_VERSION,
                run_id=rid,
                scenario_id=scenario_id,
                status=status,
                duration_ms=_duration_ms(start, start + elapsed),
                api_calls=api_calls,
                tool_calls=int(result.get("tool_calls", 0)),
                failure_class=failure_class,
                redacted_summary=redact_summary(summary),
            )
        )

        if status in ("failed", "timed_out") and stop_on_first_failure:
            break

    return records
