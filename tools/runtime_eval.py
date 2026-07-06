#!/usr/bin/env python3
"""Local runtime evaluation harness for deterministic PawnLogic smoke checks."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time


ARTIFACT_DIR_NAME = ".pawnlogic_eval"
REAL_API_GATE_ENV = "PAWNLOGIC_REAL_API_SMOKE"
SUPPORTED_SUITES = (
    "offline",
    "tools",
    "real-api",
    "docker",
    "browser",
    "ctf",
    "soak",
)
FAILING_STATUSES = {"failed", "timed_out"}
PROVIDER_KEY_NAMES = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "MISTRAL_API_KEY",
    "OPENROUTER_API_KEY",
    "TOGETHER_API_KEY",
    "DASHSCOPE_API_KEY",
    "MOONSHOT_API_KEY",
    "ZHIPU_API_KEY",
    "XAI_API_KEY",
)
SECRET_RE = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{20,}|"
    r"sk-(proj-|svcacct-|live-)?[A-Za-z0-9_-]{20,}|"
    r"ghp_[A-Za-z0-9]{36}|"
    r"github_pat_[A-Za-z0-9_]{50,}|"
    r"tp-[a-z0-9]{30,}|"
    r"AIza[A-Za-z0-9_-]{35}|"
    r"AKIA[0-9A-Z]{16}|"
    r"ASIA[0-9A-Z]{16}|"
    r"(OPENAI|ANTHROPIC|DEEPSEEK|AZURE|GOOGLE|GEMINI|MISTRAL|OPENROUTER|"
    r"TOGETHER|DASHSCOPE|MOONSHOT|ZHIPU|XAI)[A-Z0-9_]*(API_)?KEY"
    r"[ \t]*[:=][ \t]*['\"]?[A-Za-z0-9_./+=-]{20,}"
)
LINUX_HOME_PREFIX = "/" + "home/"
MAC_USERS_PREFIX = "/" + "Users/"
WINDOWS_USERS_PREFIX = "C:" + "\\Users\\"
LOCAL_PATH_RE = re.compile(
    re.escape(LINUX_HOME_PREFIX)
    + r"[^/ ]+(?:/[^ \n\t]*)?|"
    + re.escape(MAC_USERS_PREFIX)
    + r"[^/ ]+(?:/[^ \n\t]*)?|"
    + re.escape(WINDOWS_USERS_PREFIX)
    + r"[^\\ \n\t]+(?:\\[^ \n\t]*)?"
)


@dataclass(frozen=True)
class ScenarioOutcome:
    status: str
    summary: str
    provider: str = "offline"
    model: str = "fake"
    api_calls: int = 0
    tool_calls: int = 0
    failure_class: str = ""


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    suite: str
    run: Callable[[], ScenarioOutcome]
    expected_api_calls: int = 0


@dataclass(frozen=True)
class RuntimeEvalRecord:
    scenario_id: str
    suite: str
    status: str
    duration_ms: int
    provider: str
    model: str
    api_calls: int
    tool_calls: int
    failure_class: str
    redacted_summary: str

    def to_json(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "suite": self.suite,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "provider": self.provider,
            "model": self.model,
            "api_calls": self.api_calls,
            "tool_calls": self.tool_calls,
            "failure_class": self.failure_class,
            "redacted_summary": self.redacted_summary,
        }


def redact_summary(summary: str) -> str:
    """Redact local paths and secret-shaped values before artifact persistence."""
    summary = SECRET_RE.sub("[REDACTED_SECRET]", summary)
    return LOCAL_PATH_RE.sub("[REDACTED_PATH]", summary)


def pass_scenario() -> ScenarioOutcome:
    return ScenarioOutcome(status="passed", summary="Harness-only fake scenario passed.")


def _tools_local_smoke_scenario() -> ScenarioOutcome:
    from core import provider_runtime
    from tools import file_ops

    class QuietLogger:
        def debug(self, *_args: object, **_kwargs: object) -> None:
            return None

        def warning(self, *_args: object, **_kwargs: object) -> None:
            return None

        def error(self, *_args: object, **_kwargs: object) -> None:
            return None

    old_cwd = list(file_ops._session_cwd)
    old_workspace = list(file_ops._session_workspace_dir)
    old_get_shell_env = file_ops._get_shell_env
    old_logger = file_ops.logger
    try:
        with tempfile.TemporaryDirectory(prefix="pawnlogic-tools-smoke-") as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            outside = Path(tmp) / "outside.txt"
            file_ops._session_cwd[0] = str(workspace)
            file_ops._session_workspace_dir[0] = str(workspace)
            file_ops._get_shell_env = lambda: {}
            file_ops.logger = QuietLogger()

            write_result = file_ops.tool_write_file(
                {"path": "notes.txt", "content": "pawnlogic tools smoke\n"}
            )
            read_result = file_ops.tool_read_file({"path": str(workspace / "notes.txt")})
            traversal_result = file_ops.tool_write_file(
                {"path": str(outside), "content": "blocked\n"}
            )
            shell_result = file_ops.tool_run_shell(
                {"command": "printf pawnlogic-tools-ok", "timeout": 5}
            )
            high_risk_result = file_ops.tool_run_shell(
                {"command": f"echo blocked > {outside}", "timeout": 5}
            )

            warnings: list[str] = []
            provider_runtime.maybe_warn_insecure_provider(
                "http://provider.example/v1",
                emit=warnings.append,
            )

        checks = {
            "safe file write": write_result.startswith("OK: wrote"),
            "safe file read": "pawnlogic tools smoke" in read_result,
            "traversal rejection": "SECURITY BLOCK" in traversal_result,
            "safe shell": "pawnlogic-tools-ok" in shell_result,
            "high-risk fail-closed": "SECURITY BLOCK" in high_risk_result,
            "plain HTTP warning": any("plain HTTP" in warning for warning in warnings),
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            return ScenarioOutcome(
                status="failed",
                summary="Tool smoke failed checks: " + ", ".join(failed),
                tool_calls=6,
                failure_class="ToolSmokeFailure",
            )
        return ScenarioOutcome(
            status="passed",
            summary=(
                "Validated safe file ops, traversal rejection, safe shell, "
                "high-risk fail-closed, and plain HTTP warning."
            ),
            tool_calls=6,
        )
    finally:
        file_ops._session_cwd[:] = old_cwd
        file_ops._session_workspace_dir[:] = old_workspace
        file_ops._get_shell_env = old_get_shell_env
        file_ops.logger = old_logger


def _env_enabled(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def _has_provider_key(env: dict[str, str]) -> bool:
    return any(bool(env.get(name)) for name in PROVIDER_KEY_NAMES)


def prepare_real_api_home(
    *,
    target_home: Path | None = None,
    source_env_path: Path | None = None,
) -> Path:
    target = target_home or Path(tempfile.mkdtemp(prefix="pawnlogic-real-api-"))
    target.mkdir(parents=True, exist_ok=True)
    source = source_env_path or (Path.home() / ".pawnlogic" / ".env")
    if source.exists():
        target_env = target / ".env"
        shutil.copyfile(source, target_env)
        target_env.chmod(0o600)
    return target


def _real_api_disabled_scenario() -> ScenarioOutcome:
    return ScenarioOutcome(
        status="skipped",
        summary=f"Set {REAL_API_GATE_ENV}=true to run real API smoke.",
        failure_class="RealApiSmokeDisabled",
    )


def _real_api_missing_key_scenario() -> ScenarioOutcome:
    return ScenarioOutcome(
        status="skipped",
        summary="No provider API key was available for real API smoke.",
        failure_class="ProviderKeyUnavailable",
    )


def _real_api_smoke_scenario(
    *,
    env: dict[str, str],
    max_duration_seconds: float,
    source_env_path: Path | None,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ScenarioOutcome:
    source = source_env_path or (Path.home() / ".pawnlogic" / ".env")
    if not _has_provider_key(env) and not source.exists():
        return _real_api_missing_key_scenario()

    with tempfile.TemporaryDirectory(prefix="pawnlogic-real-api-") as home:
        real_api_home = prepare_real_api_home(
            target_home=Path(home),
            source_env_path=source,
        )
        run_env = dict(os.environ)
        run_env.update(env)
        run_env["PAWNLOGIC_HOME"] = str(real_api_home)
        run_env["MCP_ENABLED"] = "false"
        run_env.pop("PAWNLOGIC_TEST_MODE", None)
        result = command_runner(
            [
                sys.executable,
                "-m",
                "pawnlogic",
                "--json",
                "--eval",
                "Reply with exactly: pawnlogic-runtime-eval-ok",
            ],
            cwd=str(Path(__file__).resolve().parents[1]),
            env=run_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max_duration_seconds,
        )

    summary = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    if result.returncode != 0:
        return ScenarioOutcome(
            status="failed",
            summary=summary or f"Real API smoke exited {result.returncode}.",
            provider="real-api",
            model="configured",
            api_calls=1,
            failure_class="RealApiSmokeFailed",
        )
    return ScenarioOutcome(
        status="passed",
        summary=summary or "Real API smoke passed.",
        provider="real-api",
        model="configured",
        api_calls=1,
    )


def scenarios_for_suite(
    suite: str,
    *,
    env: dict[str, str] | None = None,
    max_duration_seconds: float = 60.0,
    source_env_path: Path | None = None,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[Scenario]:
    if suite not in SUPPORTED_SUITES:
        raise ValueError(f"unsupported suite: {suite}")
    if suite == "real-api":
        scenario_env = dict(os.environ if env is None else env)
        if not _env_enabled(scenario_env.get(REAL_API_GATE_ENV)):
            return [
                Scenario(
                    "real-api.disabled_gate",
                    suite,
                    _real_api_disabled_scenario,
                )
            ]
        return [
            Scenario(
                "real-api.smoke",
                suite,
                lambda: _real_api_smoke_scenario(
                    env=scenario_env,
                    max_duration_seconds=max_duration_seconds,
                    source_env_path=source_env_path,
                    command_runner=command_runner,
                ),
                expected_api_calls=1,
            )
        ]
    if suite == "tools":
        return [Scenario("tools.local_smoke", suite, _tools_local_smoke_scenario)]
    return [Scenario(f"{suite}.harness_smoke", suite, pass_scenario)]


def _duration_ms(start: float, end: float) -> int:
    return max(0, round((end - start) * 1000))


def _record_from_outcome(
    *,
    scenario: Scenario,
    outcome: ScenarioOutcome,
    duration_ms: int,
    max_duration_seconds: float,
) -> RuntimeEvalRecord:
    status = outcome.status
    failure_class = outcome.failure_class
    summary = outcome.summary
    if duration_ms > int(max_duration_seconds * 1000):
        status = "timed_out"
        failure_class = "MaxDurationExceeded"
        summary = f"Scenario exceeded {max_duration_seconds:g} seconds."

    return RuntimeEvalRecord(
        scenario_id=scenario.scenario_id,
        suite=scenario.suite,
        status=status,
        duration_ms=duration_ms,
        provider=outcome.provider,
        model=outcome.model,
        api_calls=outcome.api_calls,
        tool_calls=outcome.tool_calls,
        failure_class=failure_class,
        redacted_summary=redact_summary(summary),
    )


def run_scenarios(
    scenarios: Sequence[Scenario],
    *,
    max_duration_seconds: float,
    max_api_calls: int = 1,
    stop_on_first_failure: bool = False,
    now: Callable[[], float] = time.monotonic,
) -> list[RuntimeEvalRecord]:
    records: list[RuntimeEvalRecord] = []
    api_calls_used = 0
    for scenario in scenarios:
        if api_calls_used + scenario.expected_api_calls > max_api_calls:
            records.append(
                RuntimeEvalRecord(
                    scenario_id=scenario.scenario_id,
                    suite=scenario.suite,
                    status="failed",
                    duration_ms=0,
                    provider="real-api" if scenario.suite == "real-api" else "offline",
                    model="configured" if scenario.suite == "real-api" else "fake",
                    api_calls=0,
                    tool_calls=0,
                    failure_class="ApiCallBudgetExceeded",
                    redacted_summary=(
                        "Scenario was not run because it would exceed "
                        f"--max-api-calls={max_api_calls}."
                    ),
                )
            )
            if stop_on_first_failure:
                break
            continue

        start = now()
        try:
            outcome = scenario.run()
        except Exception as exc:
            end = now()
            records.append(
                RuntimeEvalRecord(
                    scenario_id=scenario.scenario_id,
                    suite=scenario.suite,
                    status="failed",
                    duration_ms=_duration_ms(start, end),
                    provider="offline",
                    model="fake",
                    api_calls=0,
                    tool_calls=0,
                    failure_class=exc.__class__.__name__,
                    redacted_summary=redact_summary(str(exc)),
                )
            )
            if stop_on_first_failure:
                break
            continue

        end = now()
        record = _record_from_outcome(
            scenario=scenario,
            outcome=outcome,
            duration_ms=_duration_ms(start, end),
            max_duration_seconds=max_duration_seconds,
        )
        records.append(record)
        api_calls_used += record.api_calls
        if stop_on_first_failure and record.status in FAILING_STATUSES:
            break
    return records


def run_suite(
    suite: str,
    *,
    max_duration_seconds: float,
    max_api_calls: int = 1,
    stop_on_first_failure: bool = False,
    source_env_path: Path | None = None,
    env: dict[str, str] | None = None,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    now: Callable[[], float] = time.monotonic,
) -> list[RuntimeEvalRecord]:
    return run_scenarios(
        scenarios_for_suite(
            suite,
            env=env,
            max_duration_seconds=max_duration_seconds,
            source_env_path=source_env_path,
            command_runner=command_runner,
        ),
        max_duration_seconds=max_duration_seconds,
        max_api_calls=max_api_calls,
        stop_on_first_failure=stop_on_first_failure,
        now=now,
    )


def write_artifact(
    records: Sequence[RuntimeEvalRecord],
    *,
    output_dir: Path,
    suite: str,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = output_dir / f"{stamp}-{suite}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.to_json(), sort_keys=True) + "\n")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run local PawnLogic runtime evaluation scenarios."
    )
    parser.add_argument(
        "--suite",
        choices=SUPPORTED_SUITES,
        default="offline",
        help="Evaluation suite to run.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(ARTIFACT_DIR_NAME),
        help="Directory for local JSONL evaluation artifacts.",
    )
    parser.add_argument(
        "--max-duration-seconds",
        type=float,
        default=60.0,
        help="Maximum allowed duration per scenario before timeout classification.",
    )
    parser.add_argument(
        "--max-api-calls",
        type=int,
        default=1,
        help="Maximum real provider calls allowed for this run.",
    )
    parser.add_argument(
        "--stop-on-first-failure",
        action="store_true",
        help="Stop running scenarios after the first failed or timed-out record.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    records = run_suite(
        args.suite,
        max_duration_seconds=args.max_duration_seconds,
        max_api_calls=args.max_api_calls,
        stop_on_first_failure=args.stop_on_first_failure,
    )
    artifact = write_artifact(records, output_dir=args.output_dir, suite=args.suite)
    failed = [record for record in records if record.status in FAILING_STATUSES]

    print(f"Wrote {artifact}")
    print(f"Scenarios: {len(records)} passed={len(records) - len(failed)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
