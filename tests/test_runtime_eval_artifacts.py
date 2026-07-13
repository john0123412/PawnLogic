"""tests/test_runtime_eval_artifacts.py - Tests for tools/eval/ module."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.eval.contracts import EvalBudget, RuntimeEvalRecord
from tools.eval.redaction import redact_summary
from tools.eval.artifacts import unique_run_id, write_artifact_atomic
from tools.eval.runner import run_suite, run_scenario_with_deadline, SCHEMA_VERSION

# ---------------------------------------------------------------------------
# contracts
# ---------------------------------------------------------------------------


class TestEvalBudget:
    def test_frozen(self) -> None:
        budget = EvalBudget(max_duration_seconds=10.0, max_api_calls=5)
        with pytest.raises(AttributeError):
            budget.max_duration_seconds = 20.0  # type: ignore[misc]

    def test_zero_budget(self) -> None:
        budget = EvalBudget(max_duration_seconds=0.0, max_api_calls=0)
        assert budget.max_duration_seconds == 0.0
        assert budget.max_api_calls == 0


class TestRuntimeEvalRecord:
    def test_to_json(self) -> None:
        record = RuntimeEvalRecord(
            schema_version=1,
            run_id="test-run",
            scenario_id="test-scenario",
            status="passed",
            duration_ms=100,
            api_calls=1,
            tool_calls=2,
            failure_class="",
            redacted_summary="ok",
        )
        j = record.to_json()
        assert j["schema_version"] == 1
        assert j["run_id"] == "test-run"
        assert j["status"] == "passed"


# ---------------------------------------------------------------------------
# redaction
# ---------------------------------------------------------------------------


class TestRedaction:
    def test_redacts_api_keys(self) -> None:
        summary = "Used key sk-ant-abcdefghijklmnopqrstuvwxyz123456"
        result = redact_summary(summary)
        assert "sk-ant-" not in result
        assert "[REDACTED_SECRET]" in result

    def test_redacts_local_paths(self) -> None:
        summary = "File at /home/johnny/.pawnlogic/config.json"
        result = redact_summary(summary)
        assert "/home/johnny" not in result
        assert "[REDACTED_PATH]" in result

    def test_preserves_safe_text(self) -> None:
        summary = "All tests passed successfully."
        result = redact_summary(summary)
        assert result == summary


# ---------------------------------------------------------------------------
# artifacts
# ---------------------------------------------------------------------------


class TestArtifacts:
    def test_unique_run_id_format(self) -> None:
        rid = unique_run_id()
        assert len(rid) > 10
        assert "-" in rid

    def test_write_artifact_atomic(self, tmp_path: Path) -> None:
        records = [
            RuntimeEvalRecord(
                schema_version=1,
                run_id="test",
                scenario_id="s1",
                status="passed",
                duration_ms=10,
                api_calls=0,
                tool_calls=0,
                failure_class="",
                redacted_summary="ok",
            )
        ]
        path = write_artifact_atomic(records, output_dir=tmp_path, suite="test")
        assert path.exists()
        assert path.suffix == ".jsonl"
        content = path.read_text()
        assert "s1" in content


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------


class TestRunner:
    def test_run_suite_pass(self) -> None:
        def ok_scenario() -> dict:
            return {
                "status": "passed",
                "summary": "ok",
                "api_calls": 0,
                "tool_calls": 0,
                "failure_class": "",
            }

        budget = EvalBudget(max_duration_seconds=10.0, max_api_calls=5)
        records = run_suite([ok_scenario], budget=budget, run_id="test")
        assert len(records) == 1
        assert records[0].status == "passed"
        assert records[0].run_id == "test"
        assert records[0].schema_version == SCHEMA_VERSION

    def test_run_suite_failure(self) -> None:
        def fail_scenario() -> dict:
            return {
                "status": "failed",
                "summary": "oops",
                "api_calls": 0,
                "tool_calls": 0,
                "failure_class": "TestError",
            }

        budget = EvalBudget(max_duration_seconds=10.0, max_api_calls=5)
        records = run_suite([fail_scenario], budget=budget, run_id="test")
        assert len(records) == 1
        assert records[0].status == "failed"
        assert records[0].failure_class == "TestError"

    def test_run_suite_stop_on_first_failure(self) -> None:
        def fail_scenario() -> dict:
            return {
                "status": "failed",
                "summary": "oops",
                "api_calls": 0,
                "tool_calls": 0,
                "failure_class": "",
            }

        def ok_scenario() -> dict:
            return {
                "status": "passed",
                "summary": "ok",
                "api_calls": 0,
                "tool_calls": 0,
                "failure_class": "",
            }

        budget = EvalBudget(max_duration_seconds=10.0, max_api_calls=5)
        records = run_suite(
            [fail_scenario, ok_scenario],
            budget=budget,
            run_id="test",
            stop_on_first_failure=True,
        )
        assert len(records) == 1

    def test_run_suite_budget_exceeded(self) -> None:
        def api_scenario() -> dict:
            return {
                "status": "passed",
                "summary": "ok",
                "api_calls": 1,
                "tool_calls": 0,
                "failure_class": "",
            }

        budget = EvalBudget(max_duration_seconds=10.0, max_api_calls=0)
        records = run_suite([api_scenario], budget=budget, run_id="test")
        assert len(records) == 1
        assert records[0].status == "failed"
        assert records[0].failure_class == "ApiCallBudgetExceeded"

    def test_run_suite_negative_budget_raises(self) -> None:
        budget = EvalBudget(max_duration_seconds=-1.0, max_api_calls=0)
        with pytest.raises(ValueError, match="positive"):
            run_suite([], budget=budget, run_id="test")

    def test_run_scenario_with_deadline_pass(self) -> None:
        def ok() -> dict:
            return {
                "status": "passed",
                "summary": "ok",
                "api_calls": 0,
                "tool_calls": 0,
                "failure_class": "",
            }

        import time

        deadline = time.monotonic() + 10.0
        result = run_scenario_with_deadline(ok, deadline=deadline)
        assert result["status"] == "passed"

    def test_run_scenario_with_deadline_budget_exhausted(self) -> None:
        import time

        def ok() -> dict:
            return {
                "status": "passed",
                "summary": "ok",
                "api_calls": 0,
                "tool_calls": 0,
                "failure_class": "",
            }

        deadline = time.monotonic() - 1.0  # Already past
        result = run_scenario_with_deadline(ok, deadline=deadline)
        assert result["status"] == "timed_out"
        assert result["failure_class"] == "BudgetExhausted"

    def test_run_scenario_with_deadline_exception(self) -> None:
        import time

        def bad() -> dict:
            raise RuntimeError("boom")

        deadline = time.monotonic() + 10.0
        result = run_scenario_with_deadline(bad, deadline=deadline)
        assert result["status"] == "failed"
        assert result["failure_class"] == "RuntimeError"
