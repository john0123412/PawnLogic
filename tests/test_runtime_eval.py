from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from tools import runtime_eval


EXPECTED_RECORD_KEYS = {
    "scenario_id",
    "suite",
    "status",
    "duration_ms",
    "provider",
    "model",
    "api_calls",
    "tool_calls",
    "failure_class",
    "redacted_summary",
}


def _lines(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _clock(*values: float):
    ticks: Iterator[float] = iter(values)
    return lambda: next(ticks)


def test_cli_rejects_unknown_suite(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        runtime_eval.main(["--suite", "unknown", "--output-dir", str(tmp_path)])

    assert excinfo.value.code == 2


def test_offline_cli_writes_jsonl_artifact_with_contract(tmp_path):
    output_dir = tmp_path / ".pawnlogic_eval"

    assert runtime_eval.main(["--suite", "offline", "--output-dir", str(output_dir)]) == 0

    artifacts = sorted(output_dir.glob("*.jsonl"))
    assert len(artifacts) == 1
    records = _lines(artifacts[0])
    assert records
    assert {record["suite"] for record in records} == {"offline"}
    for record in records:
        assert set(record) == EXPECTED_RECORD_KEYS
        assert record["status"] == "passed"
        assert isinstance(record["duration_ms"], int)
        assert record["provider"] == "offline"
        assert record["model"] == "fake"
        assert record["api_calls"] == 0
        assert record["tool_calls"] == 0
        assert record["failure_class"] == ""
        assert isinstance(record["redacted_summary"], str)


def test_redacted_summary_removes_secret_like_values_and_local_paths():
    posix_path = "/" + "home/alice/pawnlogic"
    windows_path = "C:" + "\\Users\\Alice\\pawnlogic"
    secret = "sk-" + "proj-" + "abcdefghijklmnopqrstuvwxyz123456"
    text = (
        f"request failed for {secret} "
        f"inside {posix_path} and {windows_path}"
    )

    redacted = runtime_eval.redact_summary(text)

    assert secret not in redacted
    assert posix_path not in redacted
    assert windows_path not in redacted
    assert "[REDACTED_SECRET]" in redacted
    assert "[REDACTED_PATH]" in redacted


def test_exception_status_is_classified_without_raw_exception_summary():
    secret = "sk-" + "live-" + "abcdefghijklmnopqrstuvwxyz123456"

    def fail() -> runtime_eval.ScenarioOutcome:
        raise ValueError(f"bad key {secret}")

    records = runtime_eval.run_scenarios(
        [runtime_eval.Scenario("fake-failure", "offline", fail)],
        max_duration_seconds=10,
        now=_clock(0.0, 0.01),
    )

    assert len(records) == 1
    record = records[0]
    assert record.status == "failed"
    assert record.failure_class == "ValueError"
    assert secret not in record.redacted_summary
    assert "[REDACTED_SECRET]" in record.redacted_summary


def test_max_duration_classifies_scenario_timeout():
    records = runtime_eval.run_scenarios(
        [runtime_eval.Scenario("fake-slow", "offline", runtime_eval.pass_scenario)],
        max_duration_seconds=0.5,
        now=_clock(10.0, 11.0),
    )

    assert len(records) == 1
    record = records[0]
    assert record.status == "timed_out"
    assert record.duration_ms == 1000
    assert record.failure_class == "MaxDurationExceeded"
    assert "exceeded 0.5 seconds" in record.redacted_summary


def test_offline_execution_is_deterministic_with_fixed_clock():
    first = runtime_eval.run_suite(
        "offline",
        max_duration_seconds=10,
        now=_clock(100.0, 100.123),
    )
    second = runtime_eval.run_suite(
        "offline",
        max_duration_seconds=10,
        now=_clock(100.0, 100.123),
    )

    assert [record.to_json() for record in first] == [record.to_json() for record in second]


def test_all_supported_suites_have_harness_only_fake_scenarios():
    for suite in runtime_eval.SUPPORTED_SUITES:
        scenarios = runtime_eval.scenarios_for_suite(suite)
        assert scenarios
        assert {scenario.suite for scenario in scenarios} == {suite}
