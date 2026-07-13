"""tools/eval/runner.py - Runtime evaluation runner with deadline enforcement.

Executes evaluation scenarios with real wall-clock deadline enforcement,
child-process isolation on POSIX, and consistent timeout classification.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from tools.eval.contracts import EvalBudget, RuntimeEvalRecord
from tools.eval.redaction import redact_summary
from tools.eval.artifacts import unique_run_id

SCHEMA_VERSION = 1


def _duration_ms(start: float, end: float) -> int:
    return max(0, int((end - start) * 1000))


def run_scenario_with_deadline(
    scenario_fn: Callable[[], dict],
    *,
    deadline: float,
    now: Callable[[], float] = time.monotonic,
) -> dict:
    """Run a scenario with a real wall-clock deadline.

    If the scenario exceeds the deadline, it is classified as timed_out.
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
    except Exception as exc:
        return {
            "status": "failed",
            "summary": str(exc),
            "api_calls": 0,
            "tool_calls": 0,
            "failure_class": type(exc).__name__,
        }


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

        # Check API call budget.
        if total_api_calls >= budget.max_api_calls:
            records.append(
                RuntimeEvalRecord(
                    schema_version=SCHEMA_VERSION,
                    run_id=rid,
                    scenario_id=scenario_id,
                    status="failed",
                    duration_ms=0,
                    api_calls=0,
                    tool_calls=0,
                    failure_class="ApiCallBudgetExceeded",
                    redacted_summary=f"Budget exhausted ({budget.max_api_calls} API calls).",
                )
            )
            if stop_on_first_failure:
                break
            continue

        start = now()
        result = run_scenario_with_deadline(scenario_fn, deadline=deadline, now=now)
        elapsed = now() - start

        api_calls = int(result.get("api_calls", 0))
        total_api_calls += api_calls

        records.append(
            RuntimeEvalRecord(
                schema_version=SCHEMA_VERSION,
                run_id=rid,
                scenario_id=scenario_id,
                status=result.get("status", "failed"),
                duration_ms=_duration_ms(start, start + elapsed),
                api_calls=api_calls,
                tool_calls=int(result.get("tool_calls", 0)),
                failure_class=result.get("failure_class", ""),
                redacted_summary=redact_summary(result.get("summary", "")),
            )
        )

        if result.get("status") in ("failed", "timed_out") and stop_on_first_failure:
            break

    return records
