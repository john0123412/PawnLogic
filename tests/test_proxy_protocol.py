"""Offline contract tests for the strict one-request browser proxy protocol."""

from __future__ import annotations

from contextlib import suppress
import socket
import threading

import pytest

from tools.proxy_protocol import (
    ProxyProtocolError,
    Request,
    connect_url,
    forward_http,
    read_request,
    splice,
)


class ScriptedSocket:
    """Small socket double with independently scripted recv chunks."""

    def __init__(self, *chunks: bytes) -> None:
        self._chunks = list(chunks)
        self.sent = bytearray()
        self.timeouts: list[float | None] = []

    def recv(self, size: int) -> bytes:
        if not self._chunks:
            return b""
        chunk = self._chunks.pop(0)
        if len(chunk) <= size:
            return chunk
        self._chunks.insert(0, chunk[size:])
        return chunk[:size]

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)

    def settimeout(self, value: float | None) -> None:
        self.timeouts.append(value)


def test_read_request_preserves_connect_pending_tls_bytes() -> None:
    tls_client_hello = b"\x16\x03\x01\x00\x2aencrypted-client-hello"
    client = ScriptedSocket(
        b"CONNECT example.test:443 HTTP/1.1\r\n"
        b"Host: example.test:443\r\n"
        b"Proxy-Connection: keep-alive\r\n\r\n"
        + tls_client_hello
    )

    request = read_request(client)

    assert request == Request(
        method="CONNECT",
        target="example.test:443",
        version="HTTP/1.1",
        headers=(
            ("Host", "example.test:443"),
            ("Proxy-Connection", "keep-alive"),
        ),
        pending=tls_client_hello,
    )
    assert connect_url(request) == "https://example.test:443/"


def test_forward_http_rewrites_one_request_and_strips_proxy_headers() -> None:
    client = ScriptedSocket(
        b"POST http://example.test:8080/form?q=1 HTTP/1.1\r\n"
        b"Host: example.test:8080\r\n"
        b"Connection: keep-alive\r\n"
        b"Keep-Alive: timeout=5\r\n"
        b"Proxy-Authorization: Basic secret\r\n"
        b"Content-Length: 4\r\n\r\n",
        b"data",
    )
    request = read_request(client)
    upstream = ScriptedSocket(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")

    forward_http(client, upstream, request)

    sent = bytes(upstream.sent)
    head, body = sent.split(b"\r\n\r\n", 1)
    assert head.startswith(b"POST /form?q=1 HTTP/1.1\r\n")
    assert b"Host: example.test:8080\r\n" in head
    assert b"Connection: close" in head
    assert b"Proxy-Authorization:" not in head
    assert b"Keep-Alive:" not in head
    assert body == b"data"
    assert bytes(client.sent) == b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK"
    assert upstream.timeouts == [10.0]


def test_forward_http_rejects_second_request_in_pending_bytes() -> None:
    second_request = b"GET http://169.254.169.254/latest HTTP/1.1\r\nHost: metadata\r\n\r\n"
    client = ScriptedSocket(
        b"GET http://example.test/ HTTP/1.1\r\nHost: example.test\r\n\r\n"
        + second_request
    )
    request = read_request(client)
    upstream = ScriptedSocket()

    with pytest.raises(ProxyProtocolError, match="one request"):
        forward_http(client, upstream, request)

    assert bytes(upstream.sent) == b""


@pytest.mark.parametrize(
    "extra_headers",
    [
        b"Transfer-Encoding: chunked\r\n",
        b"TE: trailers\r\n",
        b"Upgrade: websocket\r\n",
    ],
)
def test_forward_http_rejects_streaming_or_upgrade_framing(extra_headers: bytes) -> None:
    client = ScriptedSocket(
        b"GET http://example.test/ HTTP/1.1\r\n"
        b"Host: example.test\r\n"
        + extra_headers
        + b"\r\n"
    )
    request = read_request(client)
    upstream = ScriptedSocket()

    with pytest.raises(ProxyProtocolError):
        forward_http(client, upstream, request)

    assert bytes(upstream.sent) == b""


def test_read_request_rejects_ambiguous_content_length_and_header_injection() -> None:
    duplicate_length = ScriptedSocket(
        b"POST http://example.test/ HTTP/1.1\r\n"
        b"Host: example.test\r\n"
        b"Content-Length: 1\r\n"
        b"Content-Length: 2\r\n\r\n"
    )
    with pytest.raises(ProxyProtocolError, match="Content-Length"):
        read_request(duplicate_length)

    duplicate_host = ScriptedSocket(
        b"GET http://example.test/ HTTP/1.1\r\n"
        b"Host: example.test\r\n"
        b"Host: example.test\r\n\r\n"
    )
    with pytest.raises(ProxyProtocolError, match="Host"):
        read_request(duplicate_host)

    folded_header = ScriptedSocket(
        b"GET http://example.test/ HTTP/1.1\r\n"
        b"Host: example.test\r\n"
        b"X-Test: safe\r\n injected\r\n\r\n"
    )
    with pytest.raises(ProxyProtocolError, match="header"):
        read_request(folded_header)


@pytest.mark.parametrize(
    ("raw_request", "message"),
    [
        (
            b"GET http://example.test/ HTTP/1.1\r\n"
            b"Host: other.example\r\n\r\n",
            "Host",
        ),
        (
            b"CONNECT https://example.test:443/ HTTP/1.1\r\n"
            b"Host: example.test:443\r\n\r\n",
            "authority",
        ),
        (
            b"CONNECT example.test HTTP/1.1\r\n"
            b"Host: example.test\r\n\r\n",
            "port",
        ),
    ],
)
def test_connect_url_rejects_non_authority_or_host_mismatch(
    raw_request: bytes, message: str
) -> None:
    client = ScriptedSocket(raw_request)
    request = read_request(client)

    with pytest.raises(ProxyProtocolError, match=message):
        connect_url(request)


def test_forward_http_reads_exact_content_length_without_forwarding_trailing_bytes() -> None:
    client = ScriptedSocket(
        b"POST http://example.test/upload HTTP/1.1\r\n"
        b"Host: example.test\r\n"
        b"Content-Length: 4\r\n\r\n",
        b"body",
        b"GET http://169.254.169.254/ HTTP/1.1\r\nHost: metadata\r\n\r\n",
    )
    request = read_request(client)
    upstream = ScriptedSocket(b"HTTP/1.1 204 No Content\r\n\r\n")

    forward_http(client, upstream, request)

    sent = bytes(upstream.sent)
    assert sent.endswith(b"\r\n\r\nbody")
    assert b"169.254.169.254" not in sent


def test_splice_relays_both_directions_and_closes_both_sockets() -> None:
    left, left_peer = socket.socketpair()
    right, right_peer = socket.socketpair()
    for sock in (left, left_peer, right, right_peer):
        sock.settimeout(2)

    relay = threading.Thread(target=splice, args=(left, right), daemon=True)
    relay.start()
    try:
        left_peer.sendall(b"client-bytes")
        assert right_peer.recv(64) == b"client-bytes"
        right_peer.sendall(b"server-bytes")
        assert left_peer.recv(64) == b"server-bytes"
        left_peer.shutdown(socket.SHUT_WR)
        relay.join(2)
        assert not relay.is_alive()
    finally:
        for sock in (left, left_peer, right, right_peer):
            with suppress(OSError):
                sock.close()


@pytest.mark.parametrize("headers", [b"Expect: 100-continue\r\n", b"Content-Length: 8388609\r\n"])
def test_http_unsupported_body_never_forwards_headers(headers: bytes) -> None:
    client = ScriptedSocket(b"POST http://example.test/upload HTTP/1.1\r\nHost: example.test\r\n" + headers + b"\r\n")
    upstream = ScriptedSocket()
    with pytest.raises(ProxyProtocolError):
        forward_http(client, upstream, read_request(client))
    assert upstream.sent == b""
