"""core/provider_transport.py - Provider transport layer.

Centralizes format-specific HTTP headers, provider definition validation,
and provider metadata validation before any disk or registry mutation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

VALID_API_FORMATS = frozenset({"openai", "anthropic"})


@dataclass(frozen=True)
class ProviderDefinition:
    """Validated provider configuration before persistence."""

    name: str
    base_url: str
    api_key_env: str
    api_format: str


def provider_headers(api_format: str, api_key: str) -> dict[str, str]:
    """Return format-specific HTTP headers for provider requests.

    OpenAI format uses Bearer token authentication.
    Anthropic format uses x-api-key and anthropic-version headers.
    """
    if api_format == "anthropic":
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
    # Default: OpenAI format.
    return {
        "Authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }


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

    api_format = str(config.get("api_format", "openai")).strip()
    if api_format not in VALID_API_FORMATS:
        raise ValueError(
            f"Provider '{name}' has unsupported api_format '{api_format}'. "
            f"Supported: {', '.join(sorted(VALID_API_FORMATS))}."
        )

    return ProviderDefinition(
        name=name,
        base_url=base_url,
        api_key_env=api_key_env,
        api_format=api_format,
    )
