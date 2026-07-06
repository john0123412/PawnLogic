#!/usr/bin/env python3
"""Local runtime evaluation harness for deterministic PawnLogic smoke checks."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time


ARTIFACT_DIR_NAME = ".pawnlogic_eval"
SUPPORTED_SUITES = (
    "offline",
    "tools",
    "real-api",
    "docker",
    "browser",
    "ctf",
    "soak",
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


def scenarios_for_suite(suite: str) -> list[Scenario]:
    if suite not in SUPPORTED_SUITES:
        raise ValueError(f"unsupported suite: {suite}")
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
    now: Callable[[], float] = time.monotonic,
) -> list[RuntimeEvalRecord]:
    records: list[RuntimeEvalRecord] = []
    for scenario in scenarios:
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
            continue

        end = now()
        records.append(
            _record_from_outcome(
                scenario=scenario,
                outcome=outcome,
                duration_ms=_duration_ms(start, end),
                max_duration_seconds=max_duration_seconds,
            )
        )
    return records


def run_suite(
    suite: str,
    *,
    max_duration_seconds: float,
    now: Callable[[], float] = time.monotonic,
) -> list[RuntimeEvalRecord]:
    return run_scenarios(
        scenarios_for_suite(suite),
        max_duration_seconds=max_duration_seconds,
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    records = run_suite(args.suite, max_duration_seconds=args.max_duration_seconds)
    artifact = write_artifact(records, output_dir=args.output_dir, suite=args.suite)
    failed = [record for record in records if record.status != "passed"]

    print(f"Wrote {artifact}")
    print(f"Scenarios: {len(records)} passed={len(records) - len(failed)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
