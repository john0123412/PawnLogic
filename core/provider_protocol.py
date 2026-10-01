"""core/provider_protocol.py - Per-format request/response dispatch.

``core/api_client.py`` used to branch on ``api_format`` inline at four separate
sites with an implicit ``else`` meaning OpenAI. That shape is what let a format
added to a registry but missing from one branch keep running while speaking the
wrong protocol -- no error, wrong content.

This module is the single place a format is turned into behaviour. Every
registered format must appear in ``PROTOCOLS``; an unregistered one raises
rather than defaulting.

It exists as a separate module because ``core/api_client.py`` sits close to both
its line and complexity budgets, and consolidating four forks frees the room
the new format needs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.api_payloads import (
    _anthropic_build_headers,
    _anthropic_build_payload,
    _build_openai_headers,
    _build_openai_payload,
)
from core.provider_formats import build_auth_headers, format_spec

StreamPayloadBuilder = Callable[..., dict[str, Any]]
HeaderBuilder = Callable[..., dict[str, str]]
ResponseParser = Callable[[bytes], tuple[str, str | None]]

#: Header names that carry the credential. Everything else is protocol-neutral.
_AUTH_HEADER_NAMES = ("Authorization", "x-api-key", "anthropic-version")


@dataclass(frozen=True)
class Protocol:
    """Everything ``api_client`` needs in order to speak one wire format."""

    build_stream_payload: StreamPayloadBuilder
    build_nonstream_payload: StreamPayloadBuilder
    build_headers: HeaderBuilder
    parse_nonstream: ResponseParser
    #: Whether the single-shot path also advertises ``Accept: text/event-stream``.
    #: True only for Anthropic, which has always sent the SSE header set on
    #: that path. Kept as a declared flag rather than an ``or stream`` guess so
    #: the quirk stays visible: narrowing it is a behaviour change, and it is
    #: not this change's job to make one silently.
    sse_accept_on_nonstream: bool = False


def _openai_stream_payload(
    messages: list,
    model_alias: str,
    model_id: str,
    max_tokens: int,
    tools_schema: list | None,
    tool_choice: str,
    response_format: dict | None,
) -> dict[str, Any]:
    return _build_openai_payload(
        messages,
        model_alias,
        model_id,
        max_tokens,
        tools_schema,
        tool_choice,
        response_format,
    )


def _anthropic_stream_payload(
    messages: list,
    model_alias: str,
    model_id: str,
    max_tokens: int,
    tools_schema: list | None,
    tool_choice: str,
    response_format: dict | None,
) -> dict[str, Any]:
    # tool_choice and response_format have no Anthropic equivalent; the
    # protocol expresses those constraints on the model itself.
    return _anthropic_build_payload(messages, model_id, max_tokens, tools_schema)


def _responses_stream_payload(
    messages: list,
    model_alias: str,
    model_id: str,
    max_tokens: int,
    tools_schema: list | None,
    tool_choice: str,
    response_format: dict | None,
) -> dict[str, Any]:
    from core.provider_responses import build_responses_payload

    return build_responses_payload(
        messages,
        model_alias,
        model_id,
        max_tokens,
        tools_schema,
        tool_choice,
        response_format,
    )


def _openai_nonstream_payload(
    messages: list,
    model_alias: str,
    model_id: str,
    max_tokens: int,
) -> dict[str, Any]:
    # thinking-mode: use the same sanitizer as stream_request. Written out
    # rather than derived from the streaming builder, which additionally sets
    # stream_options -- meaningless, and ignored at best, on a single-shot
    # request.
    from core.api_payloads import _sanitize_messages_for_model

    return {
        "model": model_id,
        "messages": _sanitize_messages_for_model(messages, model_alias, model_id),
        "max_tokens": max_tokens,
        "stream": False,
    }


def _anthropic_nonstream_payload(
    messages: list,
    model_alias: str,
    model_id: str,
    max_tokens: int,
) -> dict[str, Any]:
    payload = _anthropic_build_payload(messages, model_id, max_tokens, None)
    payload["stream"] = False
    return payload


def _responses_nonstream_payload(
    messages: list,
    model_alias: str,
    model_id: str,
    max_tokens: int,
) -> dict[str, Any]:
    from core.provider_responses import build_responses_payload

    payload = build_responses_payload(
        messages, model_alias, model_id, max_tokens, None, "auto", None
    )
    payload["stream"] = False
    return payload


def build_stream_headers(
    api_format: str,
    api_key: str,
    body_len: int,
    *,
    auth: str = "auto",
    stream: bool = True,
) -> dict[str, str]:
    """Build the request headers for one format, honouring an auth override.

    ``auth`` is applied here, at request time, rather than only at the free
    ``/v1/models`` probe. A relay that authenticates differently from the
    protocol it speaks must work for the real Turn too -- that is the whole
    point of the setting.
    """
    spec = format_spec(api_format)
    auth_headers = build_auth_headers(spec.value, auth, api_key)

    # Start from the credential headers the resolved scheme actually needs, so
    # an override replaces the native pair rather than adding to it. Then
    # re-add the protocol-neutral headers under their historical spelling:
    # Content-Type is capitalised here but content-type in the registry, and
    # http.client sends the name through verbatim.
    headers = {key: auth_headers[key] for key in _AUTH_HEADER_NAMES if key in auth_headers}
    headers["Content-Type"] = "application/json"
    if stream or protocol_for(spec.value).sse_accept_on_nonstream:
        headers["Accept"] = "text/event-stream"
        headers["Cache-Control"] = "no-cache"
    headers["Content-Length"] = str(body_len)
    return headers


def build_stream_payload(
    api_format: str,
    messages: list,
    model_alias: str,
    model_id: str,
    max_tokens: int,
    tools_schema: list | None,
    tool_choice: str,
    response_format: dict | None,
) -> dict[str, Any]:
    return protocol_for(api_format).build_stream_payload(
        messages,
        model_alias,
        model_id,
        max_tokens,
        tools_schema,
        tool_choice,
        response_format,
    )


def build_nonstream_payload(
    api_format: str,
    messages: list,
    model_alias: str,
    model_id: str,
    max_tokens: int,
) -> dict[str, Any]:
    """Build a single-shot request body for one format."""
    return protocol_for(api_format).build_nonstream_payload(
        messages, model_alias, model_id, max_tokens
    )


def parse_nonstream_response(api_format: str, raw: bytes) -> tuple[str, str | None]:
    return protocol_for(api_format).parse_nonstream(raw)


def _openai_parse(raw: bytes) -> tuple[str, str | None]:
    from core.api_client import _parse_openai_nonstream_text

    return _parse_openai_nonstream_text(raw)


def _anthropic_parse(raw: bytes) -> tuple[str, str | None]:
    from core.api_client import _anthropic_parse_response

    return _anthropic_parse_response(raw)


def _responses_parse(raw: bytes) -> tuple[str, str | None]:
    from core.provider_responses import parse_responses_nonstream

    return parse_responses_nonstream(raw)


PROTOCOLS: dict[str, Protocol] = {
    "openai": Protocol(
        build_stream_payload=_openai_stream_payload,
        build_nonstream_payload=_openai_nonstream_payload,
        build_headers=build_stream_headers,
        parse_nonstream=_openai_parse,
    ),
    "anthropic": Protocol(
        build_stream_payload=_anthropic_stream_payload,
        build_nonstream_payload=_anthropic_nonstream_payload,
        build_headers=build_stream_headers,
        parse_nonstream=_anthropic_parse,
        sse_accept_on_nonstream=True,
    ),
    "responses": Protocol(
        build_stream_payload=_responses_stream_payload,
        build_nonstream_payload=_responses_nonstream_payload,
        build_headers=build_stream_headers,
        parse_nonstream=_responses_parse,
    ),
}

# Re-exported so existing callers of the old header builders keep working.
__all__ = [
    "PROTOCOLS",
    "Protocol",
    "_anthropic_build_headers",
    "_anthropic_build_payload",
    "_build_openai_headers",
    "_build_openai_payload",
    "build_nonstream_payload",
    "build_stream_headers",
    "build_stream_payload",
    "parse_nonstream_response",
    "protocol_for",
]


def protocol_for(api_format: str) -> Protocol:
    """Return the protocol for ``api_format``, refusing anything unregistered."""
    spec = format_spec(api_format)
    protocol = PROTOCOLS.get(spec.value)
    if protocol is None:
        raise ValueError(f"No protocol registered for format {spec.value!r}.")
    return protocol
