"""core/api_retry.py - Unified retry and circuit-breaker policy.

Centralizes retry configuration, timeout settings, and circuit-breaker
behavior for provider API requests. Loaded at request start from environment
variables with bounded validation.
"""

from __future__ import annotations

import os
import socket
import ssl
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


RETRYABLE_HTTP_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_RETRYABLE_EXCEPTION_NAMES = frozenset(
    {
        "ConnectError",
        "ConnectTimeout",
        "ReadError",
        "ReadTimeout",
        "RemoteProtocolError",
        "TimeoutException",
        "WriteError",
        "WriteTimeout",
    }
)


def is_retryable_http_status(status: int) -> bool:
    """Return whether an HTTP response is safe to retry before content."""
    return status in RETRYABLE_HTTP_STATUS_CODES


def is_retryable_transport_error(exc: BaseException) -> bool:
    """Classify transport failures consistently across provider call paths.

    Certificate validation, malformed URL/payload errors, and programming
    errors fail closed. DNS, refused/reset connections, and timeouts retry.
    """
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (ssl.SSLError, ssl.CertificateError)):
            return False
        if isinstance(current, (ValueError, TypeError)):
            return False
        if isinstance(
            current,
            (
                socket.gaierror,
                TimeoutError,
                ConnectionRefusedError,
                ConnectionResetError,
                BrokenPipeError,
                OSError,
            ),
        ):
            return True
        if type(current).__name__ in _RETRYABLE_EXCEPTION_NAMES:
            message = str(current).lower()
            if "certificate" in message or "ssl" in message:
                return False
            return True
        current = current.__cause__ or current.__context__
    return False


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


__all__ = [
    "RETRYABLE_HTTP_STATUS_CODES",
    "RetryPolicy",
    "is_retryable_http_status",
    "is_retryable_transport_error",
    "retry_policy_from_env",
]
