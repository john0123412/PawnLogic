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


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RuntimeEvalRecord:
    """Single evaluation scenario result for artifact persistence.

    Canonical record definition used by both tools.eval and tools.runtime_eval.
    The suite, provider, and model fields are compatibility extensions for the
    CLI facade.
    """

    schema_version: int = SCHEMA_VERSION
    run_id: str = ""
    scenario_id: str = ""
    status: str = "pending"
    duration_ms: int = 0
    api_calls: int = 0
    tool_calls: int = 0
    failure_class: str = ""
    redacted_summary: str = ""
    suite: str = ""
    provider: str = "offline"
    model: str = "fake"

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
            "suite": self.suite,
            "provider": self.provider,
            "model": self.model,
        }
