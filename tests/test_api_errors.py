"""Tests for shared provider API error formatting."""

from core.api_errors import format_http_error, format_transport_error, retry_notice


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
