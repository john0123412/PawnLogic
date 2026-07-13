"""core/api_retry.py - Unified retry and circuit-breaker policy.

Centralizes retry configuration, timeout settings, and circuit-breaker
behavior for provider API requests. Loaded at request start from environment
variables with bounded validation.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    """Retry and timeout configuration for provider API requests."""

    max_attempts: int = 3
    retry_after_cap_seconds: float = 10.0
    connect_timeout_seconds: float = 20.0
    read_timeout_seconds: float = 60.0
    nonstream_timeout_seconds: float = 60.0


def _env_float(
    env: Mapping[str, str], name: str, default: float, lo: float, hi: float
) -> float:
    """Read a bounded float from environment variables."""
    try:
        value = float(env.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def _env_int(env: Mapping[str, str], name: str, default: int, lo: int, hi: int) -> int:
    """Read a bounded int from environment variables."""
    try:
        value = int(env.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def retry_policy_from_env(env: Mapping[str, str] | None = None) -> RetryPolicy:
    """Load retry policy from environment variables with bounded validation.

    Environment variables:
    - PAWNLOGIC_API_RETRY_MAX: max retry attempts (1-8, default 3)
    - PAWNLOGIC_API_RETRY_AFTER_MAX: Retry-After cap in seconds (1-60, default 10)
    - PAWNLOGIC_API_CONNECT_TIMEOUT: connect timeout in seconds (5-120, default 20)
    - PAWNLOGIC_API_READ_TIMEOUT: streaming read timeout in seconds (10-300, default 60)
    - PAWNLOGIC_API_NONSTREAM_TIMEOUT: non-streaming timeout in seconds (10-300, default 60)
    """
    if env is None:
        env = os.environ
    return RetryPolicy(
        max_attempts=_env_int(env, "PAWNLOGIC_API_RETRY_MAX", 3, 1, 8),
        retry_after_cap_seconds=_env_float(
            env, "PAWNLOGIC_API_RETRY_AFTER_MAX", 10.0, 1.0, 60.0
        ),
        connect_timeout_seconds=_env_float(
            env, "PAWNLOGIC_API_CONNECT_TIMEOUT", 20.0, 5.0, 120.0
        ),
        read_timeout_seconds=_env_float(
            env, "PAWNLOGIC_API_READ_TIMEOUT", 60.0, 10.0, 300.0
        ),
        nonstream_timeout_seconds=_env_float(
            env, "PAWNLOGIC_API_NONSTREAM_TIMEOUT", 60.0, 10.0, 300.0
        ),
    )
