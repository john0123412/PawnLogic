"""tests/test_api_retry.py - Tests for core/api_retry.py."""

from __future__ import annotations

import pytest

from core.api_retry import RetryPolicy, retry_policy_from_env


class TestRetryPolicy:
    """Unit tests for RetryPolicy defaults and construction."""

    def test_defaults(self) -> None:
        policy = RetryPolicy()
        assert policy.max_attempts == 3
        assert policy.retry_after_cap_seconds == 10.0
        assert policy.connect_timeout_seconds == 20.0
        assert policy.read_timeout_seconds == 60.0
        assert policy.nonstream_timeout_seconds == 60.0

    def test_frozen(self) -> None:
        policy = RetryPolicy()
        with pytest.raises(AttributeError):
            policy.max_attempts = 5  # type: ignore[misc]


class TestRetryPolicyFromEnv:
    """Unit tests for retry_policy_from_env."""

    def test_defaults_when_empty_env(self) -> None:
        policy = retry_policy_from_env({})
        assert policy.max_attempts == 3
        assert policy.retry_after_cap_seconds == 10.0

    def test_reads_env_vars(self) -> None:
        env = {
            "PAWNLOGIC_API_RETRY_MAX": "5",
            "PAWNLOGIC_API_RETRY_AFTER_MAX": "30",
            "PAWNLOGIC_API_CONNECT_TIMEOUT": "15",
            "PAWNLOGIC_API_READ_TIMEOUT": "120",
            "PAWNLOGIC_API_NONSTREAM_TIMEOUT": "90",
        }
        policy = retry_policy_from_env(env)
        assert policy.max_attempts == 5
        assert policy.retry_after_cap_seconds == 30.0
        assert policy.connect_timeout_seconds == 15.0
        assert policy.read_timeout_seconds == 120.0
        assert policy.nonstream_timeout_seconds == 90.0

    def test_clamps_to_bounds(self) -> None:
        policy = retry_policy_from_env(
            {
                "PAWNLOGIC_API_RETRY_MAX": "100",
                "PAWNLOGIC_API_RETRY_AFTER_MAX": "0.1",
            }
        )
        assert policy.max_attempts == 8  # max
        assert policy.retry_after_cap_seconds == 1.0  # min

    def test_ignores_invalid_values(self) -> None:
        policy = retry_policy_from_env(
            {
                "PAWNLOGIC_API_RETRY_MAX": "not-a-number",
            }
        )
        assert policy.max_attempts == 3  # default

    def test_none_env_uses_os_environ(self, monkeypatch) -> None:
        monkeypatch.setenv("PAWNLOGIC_API_RETRY_MAX", "7")
        policy = retry_policy_from_env(None)
        assert policy.max_attempts == 7
