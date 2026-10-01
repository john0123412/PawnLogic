"""Provider format and auth-scheme registry.

This module is the single source of truth for "which wire protocols does
PawnLogic speak" and "how do we authenticate to them".

It exists because ``api_format`` was previously a hard binary fork with an
implicit ``else`` meaning "openai" spread across the codebase. Two providers
selected ``anthropic`` behaved differently from the two formats the product
documented, and a third format could be added to a validation allowlist while
silently degrading to OpenAI behaviour everywhere the branch was missed.

Two rules hold here:

* Every format is **looked up**, never defaulted. An unknown format raises.
  The cost is one exception at the boundary; the benefit is that a missing
  branch fails loudly instead of talking to the wrong endpoint.
* The auth scheme is an **independent axis** from the payload format. Real
  relays serve Anthropic-shaped payloads over ``Authorization: Bearer`` and
  OpenAI-shaped payloads over ``x-api-key``. Coupling the two sent the wrong
  header, and the resulting 401 was reported as "your API key is invalid" —
  sending the user to rotate a perfectly good key.

``auth`` defaults to ``auto``, which reproduces the historical mapping exactly,
so every existing provider keeps working without a config change.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Version header required by Anthropic-shaped endpoints.
ANTHROPIC_VERSION = "2023-06-01"


@dataclass(frozen=True)
class FormatSpec:
    """Everything the product needs to know about one wire protocol."""

    value: str
    label: str
    path_suffix: str
    default_auth: str
    short_tag: str


FORMATS: dict[str, FormatSpec] = {
    "openai": FormatSpec(
        value="openai",
        label="OpenAI Compatible",
        path_suffix="/chat/completions",
        default_auth="bearer",
        short_tag="[OpenAI]",
    ),
    "anthropic": FormatSpec(
        value="anthropic",
        label="Anthropic Compatible",
        path_suffix="/messages",
        default_auth="x_api_key",
        short_tag="[Anthropic]",
    ),
    "responses": FormatSpec(
        value="responses",
        label="OpenAI Responses",
        path_suffix="/responses",
        default_auth="bearer",
        short_tag="[Responses]",
    ),
}

#: Dropdown/display order. Keep in sync with ``FORMAT_LABELS`` by construction.
FORMAT_VALUES: tuple[str, ...] = tuple(FORMATS)
FORMAT_LABELS: tuple[str, ...] = tuple(spec.label for spec in FORMATS.values())
FORMAT_TAGS: tuple[str, ...] = tuple(spec.short_tag for spec in FORMATS.values())

VALID_API_FORMATS: frozenset[str] = frozenset(FORMATS)

#: ``auto`` defers to the format's historical scheme.
AUTH_SCHEMES: tuple[str, ...] = ("auto", "bearer", "x_api_key", "both")
VALID_AUTH_SCHEMES: frozenset[str] = frozenset(AUTH_SCHEMES)

AUTH_LABELS: dict[str, str] = {
    "auto": "Match protocol (recommended)",
    "bearer": "Authorization: Bearer",
    "x_api_key": "x-api-key header",
    "both": "Both headers",
}


def _unsupported(value: str, kind: str, supported: tuple[str, ...]) -> ValueError:
    return ValueError(
        f"Unsupported {kind} '{value}'; supported: {', '.join(supported)}."
    )


def normalize_api_format(value: object) -> str:
    """Return a validated canonical format value.

    An empty or missing value keeps the historical ``openai`` default, but a
    *wrong* value is refused rather than silently treated as ``openai``.
    """
    text = str(value or "").strip().lower()
    if not text:
        return "openai"
    if text not in FORMATS:
        raise _unsupported(text, "API format", FORMAT_VALUES)
    return text


def normalize_auth(value: object) -> str:
    """Return a validated auth scheme, defaulting to ``auto``."""
    text = str(value or "").strip().lower().replace("-", "_")
    if not text:
        return "auto"
    if text not in AUTH_SCHEMES:
        raise _unsupported(text, "auth scheme", AUTH_SCHEMES)
    return text


def format_spec(api_format: object) -> FormatSpec:
    """Return the registry entry for ``api_format``; raise if unknown."""
    return FORMATS[normalize_api_format(api_format)]


def endpoint_suffix(api_format: object) -> str:
    """Return the chat endpoint path appended to a provider base URL."""
    return format_spec(api_format).path_suffix


def resolve_auth(api_format: object, auth: object = "auto") -> str:
    """Collapse the ``auth`` field to a concrete scheme.

    ``auto`` resolves to the format's historical scheme, which is what every
    provider configured before this field existed was already doing.
    """
    scheme = normalize_auth(auth)
    if scheme != "auto":
        return scheme
    return format_spec(api_format).default_auth


def auth_headers(auth: object, api_key: str) -> dict[str, str]:
    """Build the credential headers for a concrete scheme.

    Credentials only. ``anthropic-version`` is *not* here: it is a protocol
    constant, not a secret, and it belongs to the format rather than to the
    scheme that carries the key. See :func:`protocol_headers`.
    """
    scheme = normalize_auth(auth)
    if scheme == "auto":
        raise ValueError(
            "auth_headers() needs a concrete scheme; call resolve_auth() first."
        )
    headers = {"content-type": "application/json"}
    if scheme in ("bearer", "both"):
        headers["Authorization"] = f"Bearer {api_key}"
    if scheme in ("x_api_key", "both"):
        headers["x-api-key"] = api_key
    return headers


def protocol_headers(api_format: object) -> dict[str, str]:
    """Non-credential headers a format mandates, whatever the auth scheme.

    ``anthropic-version`` is required on every Anthropic-shaped request by
    Anthropic-compatible endpoints. Keying it off the auth scheme instead --
    as the first cut of this registry did -- dropped it under ``auth: bearer``,
    which is precisely the combination this feature exists to support: the
    user trades a 401 for a 400 and has no way to guess why. Verified against
    a live relay that accepts it either way, so keeping it is free.

    Conversely it must not ride along on an ``openai`` payload: some
    OpenAI-compatible gateways reject unknown headers outright.
    """
    if normalize_api_format(api_format) == "anthropic":
        return {"anthropic-version": ANTHROPIC_VERSION}
    return {}


def build_auth_headers(
    api_format: object, auth: object, api_key: str
) -> dict[str, str]:
    """Build the full header set for a format plus an ``auth`` override."""
    headers = auth_headers(resolve_auth(api_format, auth), api_key)
    headers.update(protocol_headers(api_format))
    return headers


def format_label(api_format: object) -> str:
    """Human-readable label, falling back to the raw value for unknown input."""
    try:
        return format_spec(api_format).label
    except ValueError:
        return str(api_format)


def format_tag(api_format: object) -> str:
    """Short bracketed tag used by ``/provider list`` and the ``/model`` menu."""
    try:
        return format_spec(api_format).short_tag
    except ValueError:
        return ""


__all__ = [
    "ANTHROPIC_VERSION",
    "AUTH_LABELS",
    "AUTH_SCHEMES",
    "FORMATS",
    "FORMAT_LABELS",
    "FORMAT_TAGS",
    "FORMAT_VALUES",
    "VALID_API_FORMATS",
    "VALID_AUTH_SCHEMES",
    "FormatSpec",
    "auth_headers",
    "build_auth_headers",
    "endpoint_suffix",
    "format_label",
    "format_spec",
    "format_tag",
    "normalize_api_format",
    "normalize_auth",
    "protocol_headers",
    "resolve_auth",
]
