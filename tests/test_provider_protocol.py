"""Tests for the per-format protocol seam used by ``core/api_client.py``.

``core/api_client.py`` used to branch on ``api_format`` inline, four times, with
an implicit ``else`` meaning OpenAI. That is the structural cause of the class of
bug this change exists to remove: a format registered in one place but absent
from one of those branches keeps "working" by speaking the wrong protocol.

These tests pin the seam's contract: every registered format must resolve a
complete protocol, and an unregistered format must be refused rather than
defaulted. They also pin that ``auth`` is honoured at request time, not only at
the free ``/v1/models`` probe -- the reported bug was a valid key rejected by a
real Turn because the auth scheme was not configurable there.
"""

from __future__ import annotations

import json

import pytest

from core import provider_protocol
from core.provider_formats import FORMAT_VALUES
from core.provider_protocol import (
    build_nonstream_payload,
    build_stream_payload,
    build_stream_headers,
    parse_nonstream_response,
    protocol_for,
)

_MESSAGES = [{"role": "user", "content": "hello"}]


# ── every registered format resolves a complete protocol ──────────


@pytest.mark.parametrize("api_format", FORMAT_VALUES)
def test_every_registered_format_resolves_a_protocol(api_format: str) -> None:
    protocol = protocol_for(api_format)
    assert callable(protocol.build_stream_payload)
    assert callable(protocol.build_nonstream_payload)
    assert callable(protocol.build_headers)
    assert callable(protocol.parse_nonstream)


def test_an_unregistered_format_is_refused_not_defaulted() -> None:
    with pytest.raises(ValueError, match="Unsupported API format"):
        protocol_for("gemini")


def test_registry_covers_exactly_the_registered_formats() -> None:
    assert set(provider_protocol.PROTOCOLS) == set(FORMAT_VALUES)


# ── auto auth reproduces today's headers byte for byte ───────────


def test_openai_stream_headers_unchanged_by_the_seam() -> None:
    assert build_stream_headers("openai", "secret-key", 42) == {
        "Authorization": "Bearer secret-key",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
        "Content-Length": "42",
    }


def test_anthropic_stream_headers_unchanged_by_the_seam() -> None:
    assert build_stream_headers("anthropic", "sk-ant-key", 42) == {
        "x-api-key": "sk-ant-key",
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
        "Content-Length": "42",
    }


def test_nonstream_headers_match_the_pre_seam_openai_shape() -> None:
    headers = build_stream_headers("openai", "secret-key", 7, stream=False)
    assert headers == {
        "Authorization": "Bearer secret-key",
        "Content-Type": "application/json",
        "Content-Length": "7",
    }


def test_nonstream_headers_keep_the_anthropic_stream_shape() -> None:
    # call_once always sent the streaming header set on this path, Accept
    # header included. Preserved deliberately: narrowing it is a behaviour
    # change unrelated to adding a third protocol.
    headers = build_stream_headers("anthropic", "sk-ant-key", 7, stream=False)
    assert headers["x-api-key"] == "sk-ant-key"
    assert headers["Accept"] == "text/event-stream"
    assert headers["Content-Length"] == "7"


# ── auth is honoured at request time (the reported bug) ──────────


def test_bearer_auth_replaces_x_api_key_on_anthropic_stream_headers() -> None:
    # eas-llm-gateway serves Anthropic-shaped payloads over Authorization:
    # Bearer and 401s on x-api-key. Under auth="auto" this request is
    # unanswerable no matter how many models the key can reach.
    headers = build_stream_headers("anthropic", "sk-relay", 42, auth="bearer")
    assert headers["Authorization"] == "Bearer sk-relay"
    assert "x-api-key" not in headers
    # The version header belongs to the *payload format*, not to the credential
    # scheme. Anthropic-compatible endpoints require it on every request, so
    # dropping it here trades the reported 401 for a 400 on the exact
    # combination this feature exists to support.
    assert headers["anthropic-version"] == "2023-06-01"


def test_anthropic_version_rides_along_under_every_auth_scheme() -> None:
    # It is a protocol constant, not a secret, so no credential override may
    # suppress it. Keying it off the scheme is what hid this bug.
    for auth in ("auto", "bearer", "x_api_key", "both"):
        headers = build_stream_headers("anthropic", "sk-key", 42, auth=auth)
        assert headers.get("anthropic-version") == "2023-06-01", auth


def test_anthropic_version_never_leaks_onto_an_openai_payload() -> None:
    # Some OpenAI-compatible gateways reject unknown headers outright, so the
    # constant must stay keyed to the format rather than following x-api-key.
    for auth in ("auto", "bearer", "x_api_key", "both"):
        headers = build_stream_headers("openai", "sk-key", 42, auth=auth)
        assert "anthropic-version" not in headers, auth


def test_x_api_key_auth_replaces_bearer_on_openai_stream_headers() -> None:
    headers = build_stream_headers("openai", "sk-key", 42, auth="x_api_key")
    assert headers["x-api-key"] == "sk-key"
    assert "Authorization" not in headers


def test_both_auth_sends_both_schemes() -> None:
    headers = build_stream_headers("anthropic", "sk-key", 42, auth="both")
    assert headers["Authorization"] == "Bearer sk-key"
    assert headers["x-api-key"] == "sk-key"


def test_an_unknown_auth_scheme_is_refused_at_request_time() -> None:
    with pytest.raises(ValueError, match="Unsupported auth scheme"):
        build_stream_headers("openai", "sk-key", 42, auth="oauth")


def test_headers_keep_the_stream_extras_under_every_auth_scheme() -> None:
    for scheme in ("auto", "bearer", "x_api_key", "both"):
        headers = build_stream_headers("openai", "sk-key", 42, auth=scheme)
        assert headers["Accept"] == "text/event-stream"
        assert headers["Cache-Control"] == "no-cache"
        assert headers["Content-Type"] == "application/json"
        assert headers["Content-Length"] == "42"


# ── payloads ─────────────────────────────────────────────────────


@pytest.mark.parametrize("api_format", FORMAT_VALUES)
def test_stream_payload_for_every_format_names_its_model(api_format: str) -> None:
    payload = build_stream_payload(
        api_format,
        _MESSAGES,
        "plain-model",
        "plain-model-id",
        128,
        None,
        "auto",
        None,
    )
    assert payload["model"] == "plain-model-id"
    assert payload["stream"] is True


def test_openai_stream_payload_keeps_chat_completions_field_names() -> None:
    payload = build_stream_payload(
        "openai",
        _MESSAGES,
        "plain-model",
        "plain-model-id",
        128,
        None,
        "auto",
        None,
    )
    assert "messages" in payload
    assert payload["max_tokens"] == 128


def test_anthropic_stream_payload_keeps_messages_field_names() -> None:
    payload = build_stream_payload(
        "anthropic",
        _MESSAGES,
        "plain-model",
        "plain-model-id",
        128,
        None,
        "auto",
        None,
    )
    assert "messages" in payload
    assert payload["max_tokens"] == 128


def test_responses_stream_payload_uses_input_and_max_output_tokens() -> None:
    payload = build_stream_payload(
        "responses",
        _MESSAGES,
        "plain-model",
        "plain-model-id",
        128,
        None,
        "auto",
        None,
    )
    assert "input" in payload
    assert payload["max_output_tokens"] == 128
    assert "max_tokens" not in payload


def test_nonstream_payload_clears_stream_for_every_format() -> None:
    for api_format in FORMAT_VALUES:
        payload = build_nonstream_payload(
            api_format, _MESSAGES, "plain-model", "plain-model-id", 128
        )
        assert payload["stream"] is False


def test_openai_nonstream_payload_omits_stream_options() -> None:
    # call_once never sent stream_options on the single-shot path. Deriving it
    # from the streaming builder would silently add the field.
    payload = build_nonstream_payload(
        "openai", _MESSAGES, "plain-model", "plain-model-id", 128
    )
    assert "stream_options" not in payload


def test_openai_nonstream_payload_still_sanitizes_messages() -> None:
    payload = build_nonstream_payload(
        "openai",
        [{"role": "user", "content": "hello", "_private": "drop"}],
        "plain-model",
        "plain-model-id",
        128,
    )
    assert "_private" not in payload["messages"][0]


def test_responses_nonstream_payload_keeps_input_and_output_budget() -> None:
    payload = build_nonstream_payload(
        "responses", _MESSAGES, "plain-model", "plain-model-id", 128
    )
    assert payload["max_output_tokens"] == 128
    assert payload["input"][0]["type"] == "message"


# ── non-streaming response parsing ───────────────────────────────


def test_nonstream_response_parsing_per_format() -> None:
    assert parse_nonstream_response(
        "openai",
        json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode(),
    ) == ("hi", None)
    assert parse_nonstream_response(
        "anthropic",
        json.dumps({"content": [{"type": "text", "text": "hi"}]}).encode(),
    ) == ("hi", None)
    assert parse_nonstream_response(
        "responses",
        json.dumps(
            {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "hi"}],
                    }
                ]
            }
        ).encode(),
    ) == ("hi", None)


def test_nonstream_response_parsing_refuses_an_unregistered_format() -> None:
    with pytest.raises(ValueError, match="Unsupported API format"):
        parse_nonstream_response("gemini", b"{}")
