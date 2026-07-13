"""tools/eval/contracts.py - Runtime evaluation data contracts.

Defines EvalBudget, RuntimeEvalRecord, and related types for the runtime
evaluation system.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalBudget:
    """Budget constraints for a runtime evaluation run."""

    max_duration_seconds: float
    max_api_calls: int


@dataclass(frozen=True)
class RuntimeEvalRecord:
    """Single evaluation scenario result for artifact persistence."""

    schema_version: int
    run_id: str
    scenario_id: str
    status: str
    duration_ms: int
    api_calls: int
    tool_calls: int
    failure_class: str
    redacted_summary: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "api_calls": self.api_calls,
            "tool_calls": self.tool_calls,
            "failure_class": self.failure_class,
            "redacted_summary": self.redacted_summary,
        }
