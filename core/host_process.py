"""core/host_process.py - Centralized host process execution.

Provides HostProcessRequest, ProcessOutcome, and HostProcessRunner for
running host shell commands with unified operation policy enforcement,
environment scrubbing, and process-group cleanup.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from core.operation_policy import (
    OperationAction,
    OperationDecision,
    classify_shell_command,
)


@dataclass(frozen=True)
class HostProcessRequest:
    """A validated request to run a host process."""

    command: str
    cwd: Path
    timeout_seconds: float
    interactive: bool = False


@dataclass(frozen=True)
class ProcessOutcome:
    """Result of a host process execution."""

    returncode: int
    output: str
    timed_out: bool


# Non-secret config vars that must survive scrubbing.
_NON_SECRET_SUFFIXES = ("_URL", "_HOST", "_PORT", "_MODE", "_HOME", "_DIR")
_NON_SECRET_EXACT = {"PATH", "HOME", "USER", "SHELL", "TERM", "LANG", "LC_ALL"}


def scrub_environment(env: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of env with sensitive variables removed.

    Preserves non-secret runtime config like URLs, hosts, ports, and mode flags.
    """
    env = dict(os.environ) if env is None else dict(env)
    sensitive_prefixes = (
        "OPENAI_",
        "ANTHROPIC_",
        "DEEPSEEK_",
        "AZURE_",
        "GOOGLE_",
        "GEMINI_",
        "MISTRAL_",
        "OPENROUTER_",
        "TOGETHER_",
        "DASHSCOPE_",
        "MOONSHOT_",
        "ZHIPU_",
        "XAI_",
        "AWS_",
        "GITHUB_",
        "GITLAB_",
    )
    for key in list(env.keys()):
        if key in _NON_SECRET_EXACT:
            continue
        if any(key.startswith(prefix) for prefix in sensitive_prefixes):
            if key.endswith(_NON_SECRET_SUFFIXES):
                continue
            env.pop(key, None)
    return env


def classify_host_process(request: HostProcessRequest) -> OperationDecision:
    """Classify a host process request through the operation policy."""
    return classify_shell_command(request.command, cwd=str(request.cwd))


def _terminate_process_group(proc: subprocess.Popen, timeout: float = 5.0) -> None:
    """Terminate a process group, then kill if it doesn't exit."""
    with contextlib.suppress(ProcessLookupError, OSError):
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError, OSError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=2.0)


# Type for authorization callback: receives the decision, returns True to proceed.
AuthorizationCallback = Callable[[OperationDecision], bool]


def _default_authorizer(decision: OperationDecision) -> bool:
    """Default authorizer: always denies CONFIRM."""
    return False


class HostProcessRunner:
    """Run host processes with policy enforcement and cleanup."""

    def __init__(self, authorizer: AuthorizationCallback | None = None) -> None:
        self._authorizer = authorizer or _default_authorizer

    def run(self, request: HostProcessRequest) -> ProcessOutcome:
        """Execute a host process request.

        Enforces operation policy with distinct ALLOW/CONFIRM/DENY handling.
        CONFIRM requires explicit authorization; non-interactive mode fails closed.
        Uses process-group terminate + bounded kill on timeout.
        """
        decision = classify_host_process(request)

        if decision.action == OperationAction.DENY:
            return ProcessOutcome(
                returncode=-1,
                output=f"Denied: {decision.reason}",
                timed_out=False,
            )

        if decision.action == OperationAction.CONFIRM:
            if not request.interactive:
                return ProcessOutcome(
                    returncode=-1,
                    output=f"Requires confirmation (non-interactive): {decision.reason}",
                    timed_out=False,
                )
            # Interactive mode: require explicit authorization via callback.
            if not self._authorizer(decision):
                return ProcessOutcome(
                    returncode=-1,
                    output=f"Denied: confirmation not granted for: {decision.reason}",
                    timed_out=False,
                )

        env = scrub_environment()
        proc = None
        try:
            proc = subprocess.Popen(
                request.command,
                shell=True,
                cwd=str(request.cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                start_new_session=True,  # Process group for cleanup.
            )
            stdout, stderr = proc.communicate(timeout=request.timeout_seconds)
            return ProcessOutcome(
                returncode=proc.returncode,
                output=stdout + stderr,
                timed_out=False,
            )
        except subprocess.TimeoutExpired:
            if proc is not None:
                _terminate_process_group(proc)
                # Collect any partial output.
                try:
                    stdout, stderr = proc.communicate(timeout=1)
                    partial = stdout + stderr
                except Exception:
                    partial = ""
                return ProcessOutcome(
                    returncode=-1,
                    output=f"Process timed out after {request.timeout_seconds}s. {partial}".strip(),
                    timed_out=True,
                )
            return ProcessOutcome(
                returncode=-1,
                output=f"Process timed out after {request.timeout_seconds}s.",
                timed_out=True,
            )
        except KeyboardInterrupt:
            if proc is not None:
                _terminate_process_group(proc)
            return ProcessOutcome(
                returncode=-1,
                output="Process interrupted by user.",
                timed_out=False,
            )
        except Exception as exc:
            if proc is not None:
                _terminate_process_group(proc)
            return ProcessOutcome(
                returncode=-1,
                output=f"Process failed: {exc}",
                timed_out=False,
            )


def run_with_policy(
    command: str,
    cwd: Path,
    timeout_seconds: float,
    *,
    interactive: bool = False,
    authorizer: AuthorizationCallback | None = None,
) -> ProcessOutcome:
    """Convenience function to run a command with policy enforcement."""
    runner = HostProcessRunner(authorizer=authorizer)
    request = HostProcessRequest(
        command=command,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        interactive=interactive,
    )
    return runner.run(request)
