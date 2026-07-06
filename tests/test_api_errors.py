"""Tests for shared provider API error formatting."""

from core.api_errors import (
    _retry_delay,
    format_http_error,
    format_transport_error,
    is_retryable_http_status,
    retry_after_max_from_env,
    retry_notice,
)


def test_format_http_error_covers_common_provider_statuses():
    for status in (401, 403, 429, 500, 502, 503, 504):
        msg = format_http_error(status, b'{"error":{"message":"provider detail"}}')
        assert f"HTTP {status}" in msg
        assert "provider detail" in msg


def test_format_http_error_extracts_json_error_parts():
    msg = format_http_error(
        403,
        b'{"error":{"message":"invalid key","type":"auth","code":"forbidden"}}',
    )

    assert "HTTP 403" in msg
    assert "invalid key | auth | forbidden" in msg


def test_format_transport_error_reports_connection_refused_proxy_hint():
    msg = format_transport_error(ConnectionRefusedError("refused"), proxy="http://127.0.0.1:7890")

    assert "Connection refused" in msg
    assert "127.0.0.1:7890" in msg


def test_retry_notice_includes_attempt_budget_and_delay():
    assert retry_notice("HTTP 502 Bad Gateway", attempt=1, max_attempts=3, delay=4) == (
        "HTTP 502 Bad Gateway Retrying in 4s (2/3)."
    )


def test_retryable_http_status_policy_is_explicit():
    retryable = {429, 500, 502, 503, 504}
    non_retryable = {400, 401, 403, 404, 408, 409, 422}

    assert all(is_retryable_http_status(status) for status in retryable)
    assert not any(is_retryable_http_status(status) for status in non_retryable)


def test_retry_delay_honors_bounded_retry_after():
    assert _retry_delay(0, "3") == 3
    assert _retry_delay(0, "999") == 10
    assert _retry_delay(0, "-2") == 0


def test_retry_delay_falls_back_for_invalid_retry_after():
    assert _retry_delay(0, "not-a-number") == 2
    assert _retry_delay(3, None) == 8


def test_retry_after_max_can_be_configured(monkeypatch):
    monkeypatch.setenv("PAWNLOGIC_API_RETRY_AFTER_MAX", "30")

    assert retry_after_max_from_env() == 30
    assert _retry_delay(0, "999") == 30


def test_retry_after_max_invalid_env_falls_back(monkeypatch):
    monkeypatch.setenv("PAWNLOGIC_API_RETRY_AFTER_MAX", "not-an-int")

    assert retry_after_max_from_env() == 10
    assert _retry_delay(0, "999") == 10


def test_retry_after_max_env_is_clamped(monkeypatch):
    monkeypatch.setenv("PAWNLOGIC_API_RETRY_AFTER_MAX", "999")
    assert retry_after_max_from_env() == 60

    monkeypatch.setenv("PAWNLOGIC_API_RETRY_AFTER_MAX", "0")
    assert retry_after_max_from_env() == 1


def test_format_transport_error_is_user_friendly_without_traceback_detail():
    msg = format_transport_error(OSError("connection reset by peer"))

    assert "Network error (OSError): connection reset by peer" in msg
    assert "Check network, proxy settings, and provider Base URL." in msg
    assert "Traceback" not in msg
