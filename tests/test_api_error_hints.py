"""Tests for context-aware provider authentication hints.

The reported failure was a valid API key against a relay that speaks the
Anthropic protocol but authenticates with ``Authorization: Bearer``. PawnLogic
sent ``x-api-key``, the relay answered 401, and the product printed "API key is
missing or invalid; reconfigure it with /setkey" -- sending the user to rotate
a key that worked.

The fix is to name the *likely* cause without asserting the key is bad: an
auth-scheme mismatch is far more common on a relay than an actually invalid
credential, and telling the user to rotate first is the wrong instruction.

A second, separate defect: many relays publish no ``/v1/models`` endpoint. The
403/404 that results is about the endpoint, not the credential, and again the
old text pointed at the key.
"""

from __future__ import annotations

import pytest

from core.api_errors import (
    auth_failure_hint,
    format_http_error,
    model_listing_unavailable_hint,
)

# ── the generic path is unchanged ────────────────────────────────


def test_http_error_without_context_still_mentions_the_key() -> None:
    msg = format_http_error(401, b"Unauthorized")
    assert "HTTP 401 Unauthorized" in msg
    assert "API key is missing or invalid" in msg


# ── a configured non-default auth scheme changes the guidance ────


def test_bearer_over_anthropic_names_the_header_it_sent() -> None:
    # The one case where Bearer is a real change from the protocol default, so
    # it is the one case worth describing. It must not send the user to rotate
    # a key that may be perfectly valid.
    hint = auth_failure_hint("anthropic", "bearer")
    assert "Authorization: Bearer" in hint
    assert "/setkey" not in hint


def test_bearer_over_a_bearer_protocol_is_just_a_key_problem() -> None:
    # openai and responses already send Bearer under auto, so selecting Bearer
    # changes nothing and "check the Auth setting" would be advice to change a
    # setting that is already correct.
    for api_format in ("openai", "responses"):
        assert "/setkey" in auth_failure_hint(api_format, "bearer")


@pytest.mark.parametrize("api_format", ["openai", "anthropic", "responses"])
def test_auth_hint_points_at_the_auth_row(api_format: str) -> None:
    hint = auth_failure_hint(api_format, "x_api_key")
    assert "Auth" in hint
    assert "Match protocol" in hint


def test_bearer_over_anthropic_names_both_sides_of_the_mismatch() -> None:
    # The exact reported configuration: Anthropic payload shape, Bearer auth.
    hint = auth_failure_hint("anthropic", "bearer")
    assert "Anthropic" in hint
    assert "Bearer" in hint or "bearer" in hint


def test_x_api_key_over_openai_names_both_sides_of_the_mismatch() -> None:
    hint = auth_failure_hint("openai", "x_api_key")
    assert "OpenAI" in hint
    assert "x-api-key" in hint


def test_both_scheme_is_described_as_such() -> None:
    hint = auth_failure_hint("anthropic", "both")
    assert "Both" in hint or "both" in hint


def test_auto_over_anthropic_still_names_the_header_it_sent() -> None:
    # The reported case, verbatim: auth left on auto with an Anthropic-format
    # relay. The generic "your key is invalid, run /setkey" is what the user
    # saw, and it sent them to rotate a key that works -- the relay answered
    # "invalid API key or JWT token", which is what a gateway says when it
    # cannot read the header at all.
    hint = auth_failure_hint("anthropic", "auto")
    assert "x-api-key" in hint
    assert "/setkey" not in hint
    assert "Auth" in hint


def test_auto_over_a_bearer_protocol_keeps_the_generic_key_guidance() -> None:
    # openai and responses already send Bearer, so there is no header choice to
    # point at and the key really is the thing to check.
    for api_format in ("openai", "responses"):
        assert auth_failure_hint(api_format, "auto") == (
            "API key is missing or invalid; reconfigure it with /setkey."
        )


def test_no_hint_ever_suggests_setkey_while_naming_a_credential_header() -> None:
    # One invariant across every combination, so a future format or scheme
    # cannot reintroduce the "rotate a working key" advice.
    from core.provider_formats import AUTH_SCHEMES, FORMAT_VALUES

    for api_format in FORMAT_VALUES:
        for auth in AUTH_SCHEMES:
            hint = auth_failure_hint(api_format, auth)
            if "request sent" in hint:
                assert "/setkey" not in hint, (api_format, auth)


def test_auth_hint_refuses_an_unregistered_format() -> None:
    with pytest.raises(ValueError, match="Unsupported API format"):
        auth_failure_hint("gemini", "bearer")


# ── relays with no model listing endpoint ────────────────────────


def test_model_listing_hint_blames_the_endpoint_not_the_key() -> None:
    hint = model_listing_unavailable_hint(404)
    assert "/v1/models" in hint
    assert "/setkey" not in hint


def test_model_listing_hint_covers_forbidden() -> None:
    hint = model_listing_unavailable_hint(403)
    assert "/v1/models" in hint
    assert "/setkey" not in hint


def test_model_listing_hint_ignores_other_statuses() -> None:
    assert model_listing_unavailable_hint(500) == ""


def test_http_401_without_auth_context_is_unchanged() -> None:
    # A caller that has no provider context must not be told about an Auth row
    # it never rendered.
    msg = format_http_error(401, b"bad key")
    assert "Auth" not in msg


def test_http_error_with_auth_context_omits_the_rotate_the_key_advice() -> None:
    msg = format_http_error(
        401,
        b"Unauthorized: authentication failed: invalid API key or JWT token",
        api_format="anthropic",
        auth="bearer",
    )
    assert "HTTP 401 Unauthorized" in msg
    assert "authentication failed" in msg
    assert "/setkey" not in msg
