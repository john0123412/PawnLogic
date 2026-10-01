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

#: Statuses a model-listing probe returns when the provider simply does not
#: publish one. Many relays expose only the inference endpoints.
_NO_MODEL_LISTING_STATUSES = (403, 404)


def auth_failure_hint(api_format: str, auth: str) -> str:
    """Return the 401 hint for a request whose auth scheme we know.

    The hint names the credential header actually sent, whatever the scheme.

    Naming it only for an *explicit* scheme was wrong, and the reported case is
    why: the user had ``auth: auto`` on an Anthropic-format relay, so the
    generic "your API key is invalid, run /setkey" is exactly what they saw,
    and it sent them to rotate a key that works. The relay's own body said
    "invalid API key or JWT token" -- which is what a gateway says when it
    cannot read the header at all, so the header was the thing to report.

    For a protocol whose default is ``Bearer`` there is nothing a user can
    change here, so the plain key wording is kept; only a scheme the user
    could have chosen differently is worth describing.
    """
    from core.provider_formats import (
        AUTH_LABELS,
        format_spec,
        normalize_auth,
        resolve_auth,
    )

    spec = format_spec(api_format)
    scheme = normalize_auth(auth)
    resolved = resolve_auth(spec.value, scheme)
    # The header is named whenever the user could change it. That covers an
    # explicit override (openai + x_api_key) and, for Anthropic, the default
    # itself -- relays commonly reject x-api-key, which is exactly the reported
    # 401. Only a protocol that already sends Bearer under its own default
    # leaves nothing to point at, so the plain key wording is kept there.
    if resolved == spec.default_auth == "bearer":
        return HTTP_STATUS_HINTS[401][1]

    protocol_label = spec.label.removesuffix(" Compatible")
    sent = {
        "bearer": "Authorization: Bearer",
        "x_api_key": "x-api-key",
    }.get(resolved, "both Authorization: Bearer and x-api-key")

    return (
        f"{protocol_label} request sent {sent} and the provider rejected it. "
        f"Relays often accept one credential header and not the other, so check "
        f"the provider's Auth setting in the provider TUI before rotating the key "
        f"(currently '{AUTH_LABELS[scheme]}'; 'Match protocol' uses the protocol "
        f"default). Only replace the key if it is also rejected on the header "
        f"the relay expects."
    )


def model_listing_unavailable_hint(status: int) -> str:
    """Return guidance for a probe that hit a provider with no model listing.

    Empty string when the status is not one of those, so callers can append it
    unconditionally.
    """
    if status not in _NO_MODEL_LISTING_STATUSES:
        return ""
    return (
        "This provider does not publish a /v1/models listing, so the free "
        "connection check cannot confirm the key. Add models by ID in the "
        "provider TUI; a model the key cannot use is reported on first use."
    )


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


def format_http_error(
    status: int,
    body: bytes | str = b"",
    *,
    api_format: str | None = None,
    auth: str | None = None,
) -> str:
    """Format provider HTTP errors with stable status-code-specific guidance.

    Passing ``api_format`` and ``auth`` swaps the 401 hint for one that names
    the credential header actually sent. Omit them when the caller has no
    provider context -- a hint about an Auth row the user never saw is worse
    than the generic wording.
    """
    if status == 401 and api_format is not None:
        label, hint = HTTP_STATUS_HINTS[401][0], auth_failure_hint(
            api_format, auth if auth is not None else "auto"
        )
    else:
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
    retry_after_max: float | None = None,
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
    "auth_failure_hint",
    "format_http_error",
    "format_transport_error",
    "is_retryable_http_status",
    "model_listing_unavailable_hint",
    "retry_after_max_from_env",
    "retry_notice",
]
