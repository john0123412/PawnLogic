#!/usr/bin/env python3
"""Local runtime evaluation harness for deterministic PawnLogic smoke checks."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
import http.server
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

# Import shared evaluation infrastructure from tools/eval/.
from tools.eval.redaction import redact_summary
from tools.eval.artifacts import unique_run_id, write_artifact_atomic
from tools.eval.runner import run_scenario_with_deadline
from tools.eval.scenarios import run_offline_replay, run_registry_tools, run_soak


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
# Backward-compatible aliases for callers that import these from runtime_eval.
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


# Canonical RuntimeEvalRecord from tools.eval.contracts.
# Import as a compatibility alias so existing callers importing
# runtime_eval.RuntimeEvalRecord continue to work.
from tools.eval.contracts import RuntimeEvalRecord


def pass_scenario() -> ScenarioOutcome:
    return ScenarioOutcome(status="passed", summary="Harness-only fake scenario passed.")


def _offline_replay_scenario() -> ScenarioOutcome:
    """Replay provider fixtures through production stream parsers."""
    fixtures_dir = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "provider_streams"
    return ScenarioOutcome(**run_offline_replay(fixtures_dir))


def _registry_tools_scenario() -> ScenarioOutcome:
    return ScenarioOutcome(**run_registry_tools())


def _soak_scenario(max_duration_seconds: float) -> ScenarioOutcome:
    fixtures_dir = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "provider_streams"
    return ScenarioOutcome(
        **run_soak(
            fixtures_dir,
            max_duration_seconds=max_duration_seconds,
        )
    )


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
    max_api_calls: int,
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
        run_env["PAWNLOGIC_API_RETRY_MAX"] = str(max(1, max_api_calls))
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
    retry_events = summary.count("Retrying in")
    observed_calls = min(max_api_calls, 1 + retry_events)
    if result.returncode != 0:
        return ScenarioOutcome(
            status="failed",
            summary=summary or f"Real API smoke exited {result.returncode}.",
            provider="real-api",
            model="configured",
            api_calls=observed_calls,
            failure_class="RealApiSmokeFailed",
        )
    return ScenarioOutcome(
        status="passed",
        summary=summary or "Real API smoke passed.",
        provider="real-api",
        model="configured",
        api_calls=observed_calls,
    )


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _select_local_docker_python_image(client: object) -> str | None:
    candidates = (
        "python:3.12-slim",
        "python:3.11-slim",
        "python:3.10-slim",
        "python:3-slim",
    )
    images = getattr(client, "images", None)
    if images is None:
        return None
    for image in candidates:
        try:
            images.get(image)
        except Exception:
            continue
        return image
    return None


def _docker_local_smoke_scenario() -> ScenarioOutcome:
    from tools import docker_sandbox

    client = docker_sandbox._get_docker_client()
    if client is None:
        return ScenarioOutcome(
            status="skipped",
            summary="Docker runtime or Python SDK is unavailable; optional Docker suite skipped.",
            failure_class="DockerUnavailable",
        )

    image = _select_local_docker_python_image(client)
    if image is None:
        return ScenarioOutcome(
            status="skipped",
            summary=(
                "No local Python Docker image was available; optional Docker suite "
                "skipped without pulling images."
            ),
            failure_class="DockerImageUnavailable",
        )

    old_safe_workspace = docker_sandbox.SAFE_WORKSPACE
    try:
        with tempfile.TemporaryDirectory(prefix="pawnlogic-docker-smoke-") as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            fixture = workspace / "fixture.txt"
            fixture.write_text("pawnlogic-docker-ok\n", encoding="utf-8")
            docker_sandbox.SAFE_WORKSPACE = str(workspace.resolve())
            result = docker_sandbox.tool_run_code_docker(
                {
                    "language": "python",
                    "image": image,
                    "network": "none",
                    "timeout": 15,
                    "mount_files": {
                        str(fixture): {"bind": "/mnt/fixture.txt", "mode": "ro"}
                    },
                    "code": (
                        "from pathlib import Path\n"
                        "print(Path('/mnt/fixture.txt').read_text().strip())\n"
                    ),
                }
            )
    finally:
        docker_sandbox.SAFE_WORKSPACE = old_safe_workspace

    if "pawnlogic-docker-ok" not in result or "network: none" not in result:
        return ScenarioOutcome(
            status="failed",
            summary="Docker local smoke failed no-network workspace-mounted execution.",
            tool_calls=1,
            failure_class="DockerSmokeFailure",
        )
    return ScenarioOutcome(
        status="passed",
        summary="Validated no-network Docker execution with a workspace-bound read-only mount.",
        tool_calls=1,
    )


def _browser_dependencies_available() -> bool:
    return _module_available("patchright") or _module_available("scrapling")


def _browser_local_static_scenario() -> ScenarioOutcome:
    if not _browser_dependencies_available():
        return ScenarioOutcome(
            status="skipped",
            summary="Browser dependencies are unavailable; optional browser suite skipped.",
            failure_class="BrowserDependenciesUnavailable",
        )

    httpd: http.server.ThreadingHTTPServer | None = None
    thread: threading.Thread | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="pawnlogic-browser-smoke-") as tmp:
            root = Path(tmp)
            (root / "index.html").write_text(
                "<!doctype html><title>PawnLogic</title><p>pawnlogic-browser-ok</p>",
                encoding="utf-8",
            )
            handler = partial(
                http.server.SimpleHTTPRequestHandler,
                directory=str(root),
            )
            httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            port = httpd.server_address[1]
            from tools import browser_ops

            body = browser_ops.tool_web_navigate(
                {"url": f"http://127.0.0.1:{port}/index.html", "timeout": 5}
            )
    except Exception as exc:
        return ScenarioOutcome(
            status="failed",
            summary=f"Browser local static smoke failed: {type(exc).__name__}",
            tool_calls=1,
            failure_class=exc.__class__.__name__,
        )
    finally:
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if thread is not None:
            thread.join(timeout=5)

    if "OK: navigated" not in body or "PawnLogic" not in body:
        return ScenarioOutcome(
            status="failed",
            summary="Browser local static smoke did not retrieve the expected page.",
            tool_calls=1,
            failure_class="BrowserSmokeFailure",
        )
    return ScenarioOutcome(
        status="passed",
        summary="Validated the production browser navigation handler against local static HTML.",
        tool_calls=1,
    )


def _missing_commands(commands: Sequence[str]) -> list[str]:
    return [command for command in commands if shutil.which(command) is None]


def _ctf_local_smoke_scenario(
    *,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ScenarioOutcome:
    missing = _missing_commands(("file", "strings"))
    if missing:
        return ScenarioOutcome(
            status="skipped",
            summary=(
                "Local CTF binary tools are unavailable; optional CTF suite skipped: "
                + ", ".join(missing)
            ),
            failure_class="CtfToolsUnavailable",
        )

    from core import ctf_workspace

    with tempfile.TemporaryDirectory(prefix="pawnlogic-ctf-smoke-") as tmp:
        workspace = Path(tmp)
        fixture = workspace / "challenge.bin"
        fixture.write_bytes(b"\x7fELF\x02\x01\x01\x00pawnlogic-ctf-ok\x00")
        ctf_workspace.init_ctf_metadata(
            workspace,
            challenge_name="local smoke",
            category="pwn",
            source="local fixture",
        )
        ctf_workspace.add_artifact(workspace, fixture.name)
        file_result = command_runner(
            ["file", str(fixture)],
            capture_output=True,
            text=True,
            timeout=5,
            env={},
        )
        strings_result = command_runner(
            ["strings", str(fixture)],
            capture_output=True,
            text=True,
            timeout=5,
            env={},
        )
        loaded = ctf_workspace.load_ctf_metadata(workspace, strict=True)

    if (
        file_result.returncode != 0
        or strings_result.returncode != 0
        or "pawnlogic-ctf-ok" not in strings_result.stdout
        or loaded is None
        or "challenge.bin" not in loaded.artifacts
    ):
        return ScenarioOutcome(
            status="failed",
            summary="CTF local smoke failed local binary inspection or metadata checks.",
            tool_calls=3,
            failure_class="CtfSmokeFailure",
        )
    return ScenarioOutcome(
        status="passed",
        summary="Validated local CTF binary tooling and workspace metadata without remote targets.",
        tool_calls=3,
    )


def scenarios_for_suite(
    suite: str,
    *,
    env: dict[str, str] | None = None,
    max_duration_seconds: float = 60.0,
    max_api_calls: int = 1,
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
                    max_api_calls=max_api_calls,
                    source_env_path=source_env_path,
                    command_runner=command_runner,
                ),
                expected_api_calls=1,
            )
        ]
    if suite == "tools":
        return [Scenario("tools.registry_smoke", suite, _registry_tools_scenario)]
    if suite == "docker":
        return [Scenario("docker.local_smoke", suite, _docker_local_smoke_scenario)]
    if suite == "browser":
        return [Scenario("browser.local_static", suite, _browser_local_static_scenario)]
    if suite == "ctf":
        return [
            Scenario(
                "ctf.local_binary",
                suite,
                lambda: _ctf_local_smoke_scenario(command_runner=command_runner),
            )
        ]
    if suite == "offline":
        return [Scenario("offline.replay", suite, _offline_replay_scenario)]
    return [
        Scenario(
            "soak.deterministic",
            suite,
            lambda: _soak_scenario(max_duration_seconds),
        )
    ]


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
    """Run scenarios with deadline enforcement via tools/eval/runner."""
    rid = unique_run_id()
    deadline = now() + max_duration_seconds
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
                    run_id=rid,
                )
            )
            if stop_on_first_failure:
                break
            continue

        # Use run_scenario_with_deadline from tools/eval/runner for deadline enforcement.
        # Wrap scenario.run() to return a dict compatible with run_scenario_with_deadline.
        def _run_as_dict(outcome_fn: Callable[[], ScenarioOutcome] = scenario.run) -> dict:
            o = outcome_fn()
            return {
                "status": o.status,
                "summary": o.summary,
                "api_calls": o.api_calls,
                "tool_calls": o.tool_calls,
                "failure_class": o.failure_class,
            }

        start = now()
        result = run_scenario_with_deadline(
            _run_as_dict,
            deadline=deadline,
            now=now,
        )
        end = now()

        record = _record_from_outcome(
            scenario=scenario,
            outcome=ScenarioOutcome(
                status=result.get("status", "failed"),
                summary=result.get("summary", ""),
                provider=scenario.suite if scenario.suite == "real-api" else "offline",
                model="configured" if scenario.suite == "real-api" else "fake",
                api_calls=int(result.get("api_calls", 0)),
                tool_calls=int(result.get("tool_calls", 0)),
                failure_class=result.get("failure_class", ""),
            ),
            duration_ms=_duration_ms(start, end),
            max_duration_seconds=max_duration_seconds,
        )
        # Attach run_id to the record.
        record = RuntimeEvalRecord(
            scenario_id=record.scenario_id,
            suite=record.suite,
            status=record.status,
            duration_ms=record.duration_ms,
            provider=record.provider,
            model=record.model,
            api_calls=record.api_calls,
            tool_calls=record.tool_calls,
            failure_class=record.failure_class,
            redacted_summary=record.redacted_summary,
            schema_version=record.schema_version,
            run_id=rid,
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
            max_api_calls=max_api_calls,
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
    """Write evaluation records atomically.

    Compatibility wrapper over tools/eval/artifacts.write_artifact_atomic.
    Uses the same temp-file-then-rename logic for atomic writes.
    """
    return write_artifact_atomic(records, output_dir=output_dir, suite=suite)


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
