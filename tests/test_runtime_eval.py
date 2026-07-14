from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
import subprocess

import pytest

from tools import runtime_eval


EXPECTED_RECORD_KEYS = {
    "schema_version",
    "run_id",
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
        assert record["status"] in ("passed", "skipped")
        assert isinstance(record["duration_ms"], int)
        assert record["provider"] == "offline"
        assert record["model"] == "fake"
        assert record["api_calls"] == 0
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
        now=_clock(0.0, 0.0, 0.0, 0.005, 0.01, 0.01),
    )

    assert len(records) == 1
    record = records[0]
    assert record.status == "failed"
    assert record.failure_class == "ValueError"
    assert secret not in record.redacted_summary
    assert "[REDACTED_SECRET]" in record.redacted_summary


def test_max_duration_classifies_scenario_timeout():
    # Use a slow scenario that sleeps to exceed the deadline.
    import time

    def slow_scenario() -> runtime_eval.ScenarioOutcome:
        time.sleep(2)
        return runtime_eval.pass_scenario()

    records = runtime_eval.run_scenarios(
        [runtime_eval.Scenario("fake-slow", "offline", slow_scenario)],
        max_duration_seconds=0.1,
    )

    assert len(records) == 1
    record = records[0]
    assert record.status == "timed_out"
    assert record.failure_class in ("MaxDurationExceeded", "DeadlineExceeded")
    assert "exceeded" in record.redacted_summary


def test_offline_execution_is_deterministic_with_fixed_clock():
    # run_scenario_with_deadline needs multiple now() calls per scenario.
    # Offline suite has 2 scenarios (replay + harness_smoke).
    clock_values = [100.0] * 12  # Enough for 2 scenarios
    first = runtime_eval.run_suite(
        "offline",
        max_duration_seconds=10,
        now=_clock(*clock_values),
    )
    second = runtime_eval.run_suite(
        "offline",
        max_duration_seconds=10,
        now=_clock(*clock_values),
    )

    # Compare everything except run_id (which is unique per run).
    def _comparable(records):
        return [{k: v for k, v in r.to_json().items() if k != "run_id"} for r in records]

    assert _comparable(first) == _comparable(second)


def test_all_supported_suites_have_harness_only_fake_scenarios():
    for suite in runtime_eval.SUPPORTED_SUITES:
        scenarios = runtime_eval.scenarios_for_suite(suite)
        assert scenarios
        assert {scenario.suite for scenario in scenarios} == {suite}


def test_tools_suite_runs_safe_local_tool_smoke():
    records = runtime_eval.run_suite("tools", max_duration_seconds=30)

    assert len(records) == 1
    record = records[0]
    assert record.scenario_id == "tools.local_smoke"
    assert record.status == "passed"
    assert record.provider == "offline"
    assert record.api_calls == 0
    assert record.tool_calls >= 5
    assert record.failure_class == ""
    assert "safe file ops" in record.redacted_summary
    assert "plain HTTP warning" in record.redacted_summary


def test_optional_dynamic_suites_do_not_use_harness_fake_fallback():
    expected = {
        "docker": "docker.local_smoke",
        "browser": "browser.local_static",
        "ctf": "ctf.local_binary",
    }

    for suite, scenario_id in expected.items():
        scenarios = runtime_eval.scenarios_for_suite(suite)
        assert [scenario.scenario_id for scenario in scenarios] == [scenario_id]


def test_docker_suite_skips_cleanly_when_docker_is_unavailable(monkeypatch):
    from tools import docker_sandbox

    monkeypatch.setattr(docker_sandbox, "_get_docker_client", lambda: None)
    monkeypatch.setattr(docker_sandbox, "_docker_error", "not running")

    records = runtime_eval.run_suite("docker", max_duration_seconds=30)

    assert len(records) == 1
    assert records[0].status == "skipped"
    assert records[0].failure_class == "DockerUnavailable"
    assert records[0].api_calls == 0


def test_docker_suite_uses_no_network_and_workspace_bound_mount(monkeypatch):
    from tools import docker_sandbox

    # With child-process execution, side effects from fake functions are not visible.
    # Verify behavior through returned records instead.
    class FakeClient:
        pass

    def fake_tool_run_code_docker(args: dict[str, object]) -> str:
        mount_files = args["mount_files"]
        assert isinstance(mount_files, dict)
        [host_path] = mount_files.keys()
        assert Path(host_path).is_relative_to(Path(docker_sandbox.SAFE_WORKSPACE))
        return "[run_code_docker - OK | image: python:3.12-slim | network: none]\npawnlogic-docker-ok"

    monkeypatch.setattr(docker_sandbox, "_get_docker_client", lambda: FakeClient())
    monkeypatch.setattr(
        runtime_eval,
        "_select_local_docker_python_image",
        lambda _client: "python:3.12-slim",
    )
    monkeypatch.setattr(docker_sandbox, "tool_run_code_docker", fake_tool_run_code_docker)

    records = runtime_eval.run_suite("docker", max_duration_seconds=30)

    assert len(records) == 1
    assert records[0].status == "passed"
    assert records[0].tool_calls == 1


def test_browser_suite_skips_cleanly_when_dependencies_are_unavailable(monkeypatch):
    monkeypatch.setattr(runtime_eval, "_browser_dependencies_available", lambda: False)

    records = runtime_eval.run_suite("browser", max_duration_seconds=30)

    assert len(records) == 1
    assert records[0].status == "skipped"
    assert records[0].failure_class == "BrowserDependenciesUnavailable"
    assert records[0].api_calls == 0


def test_browser_suite_uses_local_static_html_server(monkeypatch):
    monkeypatch.setattr(runtime_eval, "_browser_dependencies_available", lambda: True)

    records = runtime_eval.run_suite("browser", max_duration_seconds=30)

    assert len(records) == 1
    assert records[0].status == "passed"
    assert records[0].tool_calls == 1
    assert "local static HTML server" in records[0].redacted_summary
    assert "127.0.0.1" not in records[0].redacted_summary


def test_ctf_suite_skips_cleanly_when_local_tools_are_unavailable(monkeypatch):
    monkeypatch.setattr(runtime_eval, "_missing_commands", lambda _commands: ["strings"])

    records = runtime_eval.run_suite("ctf", max_duration_seconds=30)

    assert len(records) == 1
    assert records[0].status == "skipped"
    assert records[0].failure_class == "CtfToolsUnavailable"
    assert records[0].api_calls == 0


def test_ctf_suite_uses_local_binary_tools_and_metadata(monkeypatch):
    # With child-process execution, side effects from fake_runner are not visible.
    # Verify behavior through returned records instead.
    def fake_runner(cmd, **_kwargs):
        if cmd[0] == "file":
            return subprocess.CompletedProcess(cmd, 0, stdout="ELF executable\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="pawnlogic-ctf-ok\n", stderr="")

    monkeypatch.setattr(runtime_eval, "_missing_commands", lambda _commands: [])

    records = runtime_eval.run_suite(
        "ctf",
        max_duration_seconds=30,
        command_runner=fake_runner,
    )

    assert len(records) == 1
    assert records[0].status == "passed"
    assert records[0].tool_calls == 3
    assert "remote targets" in records[0].redacted_summary


def test_real_api_suite_is_skipped_without_explicit_gate(monkeypatch, tmp_path):
    monkeypatch.delenv(runtime_eval.REAL_API_GATE_ENV, raising=False)

    records = runtime_eval.run_suite(
        "real-api",
        max_duration_seconds=10,
        source_env_path=tmp_path / "missing.env",
        env={},
    )

    assert len(records) == 1
    record = records[0]
    assert record.status == "skipped"
    assert record.api_calls == 0
    assert record.failure_class == "RealApiSmokeDisabled"


def test_real_api_cli_without_gate_writes_skipped_artifact(monkeypatch, tmp_path):
    monkeypatch.delenv(runtime_eval.REAL_API_GATE_ENV, raising=False)
    output_dir = tmp_path / ".pawnlogic_eval"

    assert runtime_eval.main(
        [
            "--suite",
            "real-api",
            "--output-dir",
            str(output_dir),
            "--max-api-calls",
            "0",
            "--stop-on-first-failure",
        ]
    ) == 0

    artifacts = sorted(output_dir.glob("*.jsonl"))
    assert len(artifacts) == 1
    records = _lines(artifacts[0])
    assert len(records) == 1
    assert records[0]["status"] == "skipped"
    assert records[0]["failure_class"] == "RealApiSmokeDisabled"


def test_real_api_gate_without_key_skips_before_network_runner(tmp_path):
    def unexpected_runner(*_args, **_kwargs):
        raise AssertionError("real API runner should not run without a key")

    records = runtime_eval.run_suite(
        "real-api",
        max_duration_seconds=10,
        env={runtime_eval.REAL_API_GATE_ENV: "true"},
        source_env_path=tmp_path / "missing.env",
        command_runner=unexpected_runner,
    )

    assert len(records) == 1
    assert records[0].status == "skipped"
    assert records[0].api_calls == 0
    assert records[0].failure_class == "ProviderKeyUnavailable"


def test_api_call_budget_prevents_expensive_scenario_from_running():
    calls: list[str] = []

    def call_api() -> runtime_eval.ScenarioOutcome:
        calls.append("called")
        return runtime_eval.ScenarioOutcome(
            status="passed",
            summary="called",
            provider="real-api",
            model="configured",
            api_calls=1,
        )

    records = runtime_eval.run_scenarios(
        [
            runtime_eval.Scenario(
                "real-api.expensive",
                "real-api",
                call_api,
                expected_api_calls=1,
            )
        ],
        max_duration_seconds=10,
        max_api_calls=0,
    )

    assert calls == []
    assert len(records) == 1
    assert records[0].status == "failed"
    assert records[0].failure_class == "ApiCallBudgetExceeded"


def test_stop_on_first_failure_does_not_run_later_scenarios():
    # With child-process execution, side effects are not visible in parent.
    # Verify behavior through returned records instead.
    def fail() -> runtime_eval.ScenarioOutcome:
        return runtime_eval.ScenarioOutcome(status="failed", summary="failed")

    def succeed() -> runtime_eval.ScenarioOutcome:
        return runtime_eval.ScenarioOutcome(status="passed", summary="passed")

    records = runtime_eval.run_scenarios(
        [
            runtime_eval.Scenario("fake.fail", "offline", fail),
            runtime_eval.Scenario("fake.succeed", "offline", succeed),
        ],
        max_duration_seconds=10,
        stop_on_first_failure=True,
    )

    assert len(records) == 1
    assert records[0].status == "failed"
    assert records[0].scenario_id == "fake.fail"


def test_prepare_real_api_home_copies_env_with_owner_only_permissions(tmp_path):
    source_env = tmp_path / "source.env"
    secret = "DEEPSEEK_API_KEY=" + "x" * 32
    source_env.write_text(secret + "\n", encoding="utf-8")
    target_home = tmp_path / "runtime-home"

    copied = runtime_eval.prepare_real_api_home(
        target_home=target_home,
        source_env_path=source_env,
    )

    assert copied == target_home
    target_env = target_home / ".env"
    assert target_env.read_text(encoding="utf-8") == secret + "\n"
    assert target_env.stat().st_mode & 0o777 == 0o600
