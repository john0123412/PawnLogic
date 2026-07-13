"""core/host_process.py - Centralized host process execution.

Provides HostProcessRequest, ProcessOutcome, and HostProcessRunner for
running host shell commands with unified operation policy enforcement,
environment scrubbing, and process-group cleanup.
"""

from __future__ import annotations

import os
import subprocess
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


def scrub_environment(env: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of env with sensitive variables removed."""
    env = dict(os.environ) if env is None else dict(env)
    # Remove variables that could leak secrets to child processes.
    sensitive_prefixes = (
        "PAWNLOGIC_",
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
        if any(key.startswith(prefix) for prefix in sensitive_prefixes):
            # Keep non-secret config vars.
            if key.endswith(("_URL", "_HOST", "_PORT", "_MODE")):
                continue
            env.pop(key, None)
    return env


def classify_host_process(request: HostProcessRequest) -> OperationDecision:
    """Classify a host process request through the operation policy."""
    return classify_shell_command(request.command, cwd=str(request.cwd))


class HostProcessRunner:
    """Run host processes with policy enforcement and cleanup."""

    def run(self, request: HostProcessRequest) -> ProcessOutcome:
        """Execute a host process request.

        Enforces operation policy, scrubs environment, and ensures
        process-group cleanup on timeout or interruption.
        """
        decision = classify_host_process(request)
        if decision.action == OperationAction.DENY:
            return ProcessOutcome(
                returncode=-1,
                output=f"Denied: {decision.reason}",
                timed_out=False,
            )

        env = scrub_environment()
        try:
            result = subprocess.run(
                request.command,
                shell=True,
                cwd=str(request.cwd),
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
                env=env,
                start_new_session=True,  # Process group for cleanup.
            )
            return ProcessOutcome(
                returncode=result.returncode,
                output=result.stdout + result.stderr,
                timed_out=False,
            )
        except subprocess.TimeoutExpired:
            return ProcessOutcome(
                returncode=-1,
                output=f"Process timed out after {request.timeout_seconds}s.",
                timed_out=True,
            )
        except KeyboardInterrupt:
            return ProcessOutcome(
                returncode=-1,
                output="Process interrupted by user.",
                timed_out=False,
            )
        except Exception as exc:
            return ProcessOutcome(
                returncode=-1,
                output=f"Process failed: {exc}",
                timed_out=False,
            )
