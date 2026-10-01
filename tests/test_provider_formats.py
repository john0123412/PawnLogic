"""Tests for the provider format/auth registry.

The registry exists because ``api_format`` used to be a hard binary fork with an
implicit ``else`` meaning "openai" in ~47 places. Adding a third format and
adding one branch meant the missing branches silently degraded to OpenAI
behaviour rather than failing. These tests pin the two properties that make
that failure impossible: every format is looked up (never defaulted), and the
auth scheme is a separate axis from the payload format.
"""

from __future__ import annotations

import pytest

from core.provider_formats import (
    ANTHROPIC_VERSION,
    AUTH_SCHEMES,
    FORMAT_LABELS,
    FORMAT_VALUES,
    VALID_API_FORMATS,
    auth_headers,
    build_auth_headers,
    endpoint_suffix,
    format_spec,
    normalize_api_format,
    normalize_auth,
    protocol_headers,
    resolve_auth,
)

# ── registry shape ───────────────────────────────────────────────


def test_registry_exposes_exactly_the_three_supported_formats() -> None:
    assert FORMAT_VALUES == ("openai", "anthropic", "responses")
    assert frozenset(FORMAT_VALUES) == VALID_API_FORMATS


def test_every_format_has_a_distinct_label_and_tag() -> None:
    labels = [format_spec(v).label for v in FORMAT_VALUES]
    tags = [format_spec(v).short_tag for v in FORMAT_VALUES]
    assert len(set(labels)) == len(FORMAT_VALUES)
    assert len(set(tags)) == len(FORMAT_VALUES)
    assert tuple(labels) == FORMAT_LABELS


def test_format_dropdown_labels_are_unique_so_a_row_can_render_its_value() -> None:
    # provider_tui_form collapsed a format value back to a label with a
    # two-way ternary, so a third format displayed as "OpenAI Compatible".
    assert len(set(FORMAT_LABELS)) == 3
    assert "OpenAI Responses" in FORMAT_LABELS


def test_auth_schemes_are_auto_bearer_x_api_key_and_both() -> None:
    assert AUTH_SCHEMES == ("auto", "bearer", "x_api_key", "both")


# ── unknown values must fail loudly, never fall back to openai ────


def test_format_spec_rejects_an_unknown_format_instead_of_defaulting() -> None:
    with pytest.raises(ValueError, match="Unsupported API format"):
        format_spec("gemini")


def test_normalize_api_format_rejects_unknown_rather_than_defaulting() -> None:
    with pytest.raises(ValueError, match="Unsupported API format"):
        normalize_api_format("gemini")


def test_normalize_auth_rejects_unknown_rather_than_defaulting() -> None:
    with pytest.raises(ValueError, match="Unsupported auth scheme"):
        normalize_auth("oauth")


def test_resolve_auth_rejects_an_unknown_format() -> None:
    with pytest.raises(ValueError, match="Unsupported API format"):
        resolve_auth("gemini", "auto")


# ── `auto` must reproduce today's behaviour exactly ──────────────


@pytest.mark.parametrize(
    "api_format, expected_auth",
    [("openai", "bearer"), ("anthropic", "x_api_key"), ("responses", "bearer")],
)
def test_auto_infers_the_historical_auth_scheme_per_format(
    api_format: str, expected_auth: str
) -> None:
    assert resolve_auth(api_format, "auto") == expected_auth


def test_auto_openai_headers_are_bearer_only() -> None:
    headers = build_auth_headers("openai", "auto", "sk-test")
    assert headers["Authorization"] == "Bearer sk-test"
    assert "x-api-key" not in headers


def test_auto_anthropic_headers_are_x_api_key_with_version() -> None:
    headers = build_auth_headers("anthropic", "auto", "sk-test")
    assert headers["x-api-key"] == "sk-test"
    assert headers["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in headers


def test_auto_responses_headers_are_bearer() -> None:
    headers = build_auth_headers("responses", "auto", "sk-test")
    assert headers["Authorization"] == "Bearer sk-test"
    assert "x-api-key" not in headers


# ── the decoupling: auth is an axis independent of payload format ──


def test_bearer_auth_over_an_anthropic_payload_is_the_bug_fix() -> None:
    # eas-llm-gateway serves Anthropic-shaped payloads but only accepts
    # Authorization: Bearer. It answered x-api-key with
    # "authentication failed: invalid API key or JWT token", which the
    # product then reported as an invalid API key.
    headers = build_auth_headers("anthropic", "bearer", "sk-test")
    assert headers["Authorization"] == "Bearer sk-test"
    assert "x-api-key" not in headers


def test_x_api_key_auth_over_an_openai_payload() -> None:
    headers = build_auth_headers("openai", "x_api_key", "sk-test")
    assert headers["x-api-key"] == "sk-test"
    assert "Authorization" not in headers


def test_both_sends_both_schemes_for_relays_that_try_either() -> None:
    headers = auth_headers("both", "sk-test")
    assert headers["Authorization"] == "Bearer sk-test"
    assert headers["x-api-key"] == "sk-test"


# ── protocol headers are keyed to the format, not the credential ──


def test_anthropic_version_is_a_protocol_constant_not_a_credential() -> None:
    # ``anthropic-version`` is required by Anthropic-compatible endpoints on
    # every request. Tying it to the x-api-key scheme suppressed it under
    # ``auth: bearer`` — the one combination this feature was built for — and
    # the user got a 400 where they had been getting a 401.
    for auth in ("auto", "bearer", "x_api_key", "both"):
        headers = build_auth_headers("anthropic", auth, "sk-test")
        assert headers.get("anthropic-version") == ANTHROPIC_VERSION, auth


def test_anthropic_version_never_rides_on_a_non_anthropic_payload() -> None:
    # Some OpenAI-compatible gateways reject unknown headers outright.
    for api_format in ("openai", "responses"):
        for auth in ("auto", "bearer", "x_api_key", "both"):
            headers = build_auth_headers(api_format, auth, "sk-test")
            assert "anthropic-version" not in headers, (api_format, auth)


def test_protocol_headers_are_exposed_on_their_own() -> None:
    assert protocol_headers("anthropic") == {"anthropic-version": ANTHROPIC_VERSION}
    assert protocol_headers("openai") == {}
    assert protocol_headers("responses") == {}


def test_auth_headers_carry_no_protocol_constants() -> None:
    # The credential layer must stay credential-only, so composing the two
    # cannot produce a header from the wrong axis.
    for scheme in ("bearer", "x_api_key", "both"):
        assert "anthropic-version" not in auth_headers(scheme, "sk-test")


def test_build_auth_headers_rejects_an_unknown_auth_scheme() -> None:
    with pytest.raises(ValueError, match="Unsupported auth scheme"):
        build_auth_headers("openai", "oauth", "sk-test")


def test_auth_headers_always_carry_the_content_type() -> None:
    for scheme in ("bearer", "x_api_key", "both"):
        assert auth_headers(scheme, "sk-test")["content-type"] == "application/json"


# ── URL suffixes ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "api_format, suffix",
    [
        ("openai", "/chat/completions"),
        ("anthropic", "/messages"),
        ("responses", "/responses"),
    ],
)
def test_endpoint_suffix_per_format(api_format: str, suffix: str) -> None:
    assert endpoint_suffix(api_format) == suffix


def test_endpoint_suffix_rejects_an_unknown_format() -> None:
    with pytest.raises(ValueError, match="Unsupported API format"):
        endpoint_suffix("gemini")


# ── normalisation ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("openai", "openai"),
        ("  Anthropic ", "anthropic"),
        ("RESPONSES", "responses"),
        ("", "openai"),
    ],
)
def test_normalize_api_format_accepts_case_and_whitespace(
    raw: str, expected: str
) -> None:
    assert normalize_api_format(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("auto", "auto"),
        (" Bearer ", "bearer"),
        ("X-API-KEY", "x_api_key"),
        ("", "auto"),
    ],
)
def test_normalize_auth_accepts_case_and_whitespace(raw: str, expected: str) -> None:
    assert normalize_auth(raw) == expected
