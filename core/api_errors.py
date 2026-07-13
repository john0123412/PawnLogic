"""Shared API error formatting for provider HTTP and transport failures."""

from __future__ import annotations

import http.client
import json
import os
import socket

from core.api_retry import RETRYABLE_HTTP_STATUS_CODES, is_retryable_http_status

DEFAULT_CONNECT_TIMEOUT = 20
DEFAULT_RETRY_AFTER_MAX = 10

HTTP_STATUS_HINTS: dict[int, tuple[str, str]] = {
    400: ("Bad Request", "provider rejected the request; check model ID, base URL, and request format."),
    401: ("Unauthorized", "API key is missing or invalid; reconfigure it with /setkey."),
    403: ("Forbidden", "API key was rejected or lacks access to this model/provider."),
    404: ("Not Found", "endpoint or model was not found; check the provider Base URL and model ID."),
    408: ("Request Timeout", "provider timed out before sending a response."),
    409: ("Conflict", "provider rejected the request state; retry later or switch model."),
    422: ("Unprocessable Entity", "provider rejected the payload; check model and parameter compatibility."),
    429: ("Rate Limited", "provider rate limit or quota was hit; wait before retrying."),
    500: ("Internal Server Error", "provider failed internally; retry later or switch provider."),
    502: ("Bad Gateway", "provider gateway or upstream model service failed."),
    503: ("Service Unavailable", "provider is overloaded or temporarily unavailable."),
    504: ("Gateway Timeout", "provider gateway timed out waiting for the model service."),
}


def response_excerpt(body: bytes | str, limit: int = 240) -> str:
    """Return a compact, credential-safe excerpt from a provider response body."""
    if isinstance(body, bytes):
        text = body.decode("utf-8", errors="replace")
    else:
        text = str(body or "")

    text = text.strip()
    if not text:
        return ""

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return " ".join(text.split())[:limit]

    if isinstance(parsed, dict):
        err = parsed.get("error")
        if isinstance(err, dict):
            parts = [
                str(err.get(k, "")).strip()
                for k in ("message", "type", "code")
                if err.get(k)
            ]
            if parts:
                return " | ".join(parts)[:limit]
        for key in ("message", "detail", "error"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:limit]
    return " ".join(text.split())[:limit]


def format_http_error(status: int, body: bytes | str = b"") -> str:
    """Format provider HTTP errors with stable status-code-specific guidance."""
    label, hint = HTTP_STATUS_HINTS.get(
        status,
        (http.client.responses.get(status, "HTTP Error"), "provider returned an error."),
    )
    msg = f"HTTP {status} {label}: {hint}"
    excerpt = response_excerpt(body)
    if excerpt:
        msg += f" Response: {excerpt}"
    return msg


def format_transport_error(
    exc: BaseException,
    *,
    proxy: str | None = None,
    connect_timeout: int = DEFAULT_CONNECT_TIMEOUT,
) -> str:
    """Format DNS, TCP, proxy, and other transport failures for user display."""
    hint = " Check network, proxy settings, and provider Base URL."
    if isinstance(exc, socket.gaierror):
        return f"DNS resolution failed: {exc}.{hint}"
    if isinstance(exc, TimeoutError):
        return f"Connection timeout ({connect_timeout}s): provider did not respond in time.{hint}"
    if isinstance(exc, ConnectionRefusedError):
        proxy_hint = f" Is proxy {proxy} running?" if proxy else ""
        return f"Connection refused.{proxy_hint}{hint}"
    if isinstance(exc, ConnectionResetError):
        return f"Connection reset by provider.{hint}"
    if isinstance(exc, BrokenPipeError):
        return f"Connection closed while sending request.{hint}"
    if isinstance(exc, OSError):
        return f"Network error ({type(exc).__name__}): {exc}.{hint}"
    return f"Connection failed ({type(exc).__name__}): {exc}.{hint}"


def _env_int(name: str, default: int, min_value: int, max_value: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(max_value, value))


def retry_after_max_from_env() -> int:
    """Return the bounded Retry-After cap for provider retry delays."""
    return _env_int(
        "PAWNLOGIC_API_RETRY_AFTER_MAX",
        DEFAULT_RETRY_AFTER_MAX,
        1,
        60,
    )


def _retry_delay(
    attempt: int,
    retry_after: str | None = None,
    *,
    retry_after_max: int | None = None,
) -> float:
    """Return retry delay for an attempt index, honoring bounded Retry-After."""
    cap = retry_after_max_from_env() if retry_after_max is None else retry_after_max
    if retry_after:
        try:
            return min(max(float(retry_after), 0.0), cap)
        except ValueError:
            pass
    return float(min(2 ** (attempt + 1), 8))


def retry_notice(message: str, attempt: int, max_attempts: int, delay: float) -> str:
    """Format a retry event that callers can surface before sleeping."""
    return f"{message} Retrying in {delay:g}s ({attempt + 1}/{max_attempts})."


__all__ = [
    "RETRYABLE_HTTP_STATUS_CODES",
    "format_http_error",
    "format_transport_error",
    "is_retryable_http_status",
    "retry_after_max_from_env",
    "retry_notice",
]
