"""core/provider_transport.py - Provider transport layer.

Centralizes format-specific HTTP headers, provider definition validation,
and provider metadata validation before any disk or registry mutation.

The format table and header construction live in `core.provider_formats`, which
is the single source of truth for both. Nothing here branches on a format by
hand: a new protocol registers once and every call site picks it up.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from core.provider_formats import (
    VALID_API_FORMATS,
    VALID_AUTH_SCHEMES,
    build_auth_headers,
    normalize_api_format,
    normalize_auth,
)

__all__ = [
    "VALID_API_FORMATS",
    "VALID_AUTH_SCHEMES",
    "ProviderDefinition",
    "provider_headers",
    "validate_provider_definition",
]


@dataclass(frozen=True)
class ProviderDefinition:
    """Validated provider configuration before persistence."""

    name: str
    base_url: str
    api_key_env: str
    api_format: str
    auth: str = "auto"


def provider_headers(
    api_format: str, api_key: str, auth: str = "auto"
) -> dict[str, str]:
    """Return authentication headers for a provider request.

    ``auth`` defaults to ``auto``, which reproduces the historical per-format
    mapping. Set it explicitly for a relay that authenticates differently from
    the protocol it speaks -- e.g. Anthropic-shaped payloads over Bearer.
    """
    return build_auth_headers(api_format, auth, api_key)


def validate_provider_definition(
    name: str,
    config: Mapping[str, object],
) -> ProviderDefinition:
    """Validate provider name and configuration before any persistence.

    Raises ValueError with a user-facing message on validation failure.
    Unknown api_format values are rejected instead of silently falling back.
    """
    if not name or not name.strip():
        raise ValueError("Provider name cannot be empty.")

    base_url = str(config.get("base_url", "")).strip()
    if not base_url:
        raise ValueError(f"Provider '{name}' requires a base_url.")

    api_key_env = str(config.get("api_key_env", "")).strip()
    if not api_key_env:
        raise ValueError(f"Provider '{name}' requires an api_key_env.")

    try:
        api_format = normalize_api_format(config.get("api_format", "openai"))
    except ValueError as exc:
        raise ValueError(f"Provider '{name}' has {exc}") from exc

    try:
        auth = normalize_auth(config.get("auth", "auto"))
    except ValueError as exc:
        raise ValueError(f"Provider '{name}' has {exc}") from exc

    return ProviderDefinition(
        name=name,
        base_url=base_url,
        api_key_env=api_key_env,
        api_format=api_format,
        auth=auth,
    )
