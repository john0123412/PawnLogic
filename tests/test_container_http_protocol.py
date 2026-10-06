"""Contract tests for the container HTTP egress protocol."""

from __future__ import annotations

import socket
import threading

import pytest

from tools.container_http_protocol import (
    EgressScopeError,
    HTTPProtocolError,
    dial_pinned,
    forward_http,
    parse_egress_scope,
    read_request,
)


class ScriptedSocket:
    def __init__(self, *chunks: bytes) -> None:
        self._chunks = list(chunks)
        self.sent = bytearray()
        self.timeout: float | None = None

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

    def settimeout(self, value: float) -> None:
        self.timeout = value


def test_scope_resolves_hostnames_once_and_never_resolves_request_targets() -> None:
    calls: list[str] = []

    def resolver(host: str) -> tuple[str, ...]:
        calls.append(host)
        return ("203.0.113.10", "2001:db8::10")

    scope = parse_egress_scope("allowed.example,203.0.113.0/24")
    resolved = scope.resolve(resolver)

    assert calls == ["allowed.example"]
    assert resolved.resolve_target("allowed.example", 8080) == (
        "allowed.example",
        8080,
        ("203.0.113.10", "2001:db8::10"),
    )
    assert resolved.resolve_target("203.0.113.99", 1) == (
        "203.0.113.99",
        1,
        ("203.0.113.99",),
    )
    with pytest.raises(EgressScopeError, match="not declared"):
        resolved.resolve_target("198.51.100.10", 443)
    with pytest.raises(EgressScopeError, match="not declared"):
        resolved.resolve_target("unknown.example", 80)
    assert calls == ["allowed.example"]


def test_scope_rejects_invalid_entries() -> None:
    with pytest.raises(EgressScopeError, match="invalid"):
        parse_egress_scope("https://allowed.example")
    with pytest.raises(EgressScopeError, match="invalid"):
        parse_egress_scope("999.999.999.999")


def test_scope_resolver_must_return_numeric_addresses() -> None:
    scope = parse_egress_scope("allowed.example")
    with pytest.raises(EgressScopeError, match="numeric"):
        scope.resolve(lambda _host: ("still-a-hostname",))


def test_pre_resolved_scope_accepts_one_literal_address_per_hostname() -> None:
    scope = parse_egress_scope("allowed.example")
    resolved = scope.resolve(resolved_hosts={"allowed.example": "93.184.216.34"})
    assert resolved.resolve_target("allowed.example", 80)[2] == ("93.184.216.34",)


def test_scope_hostname_case_and_trailing_dot_are_equivalent() -> None:
    scope = parse_egress_scope("Allowed.Example., 93.184.216.34.")
    assert scope.entries == ("allowed.example", "93.184.216.34")
    resolved = scope.resolve(resolved_hosts={"allowed.example": ("93.184.216.34",)})

    assert resolved.resolve_target("ALLOWED.EXAMPLE.", 80) == (
        "allowed.example",
        80,
        ("93.184.216.34",),
    )
    assert resolved.resolve_target("93.184.216.34.", 80) == (
        "93.184.216.34",
        80,
        ("93.184.216.34",),
    )


def test_fixed_length_http_is_forwarded_without_proxy_or_hop_by_hop_headers() -> None:
    client = ScriptedSocket(
        b"POST http://allowed.example:8080/form HTTP/1.1\r\n"
        b"Host: allowed.example:8080\r\n"
        b"Connection: keep-alive\r\n"
        b"Proxy-Authorization: secret\r\n"
        b"Content-Length: 4\r\n\r\n",
        b"data",
    )
    upstream = ScriptedSocket(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
    request = read_request(client)

    forward_http(client, upstream, request)

    sent = bytes(upstream.sent)
    head, body = sent.split(b"\r\n\r\n", 1)
    assert head.startswith(b"POST /form HTTP/1.1\r\n")
    assert b"Host: allowed.example:8080\r\n" in head
    assert b"Connection: close" in head
    assert b"Proxy-Authorization:" not in head
    assert b"Content-Length: 4\r\n" in head
    assert body == b"data"
    assert bytes(client.sent) == b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK"


def test_chunked_http_stream_is_forwarded_without_an_eight_megabyte_cap() -> None:
    payload = b"x" * (9 * 1024 * 1024)
    chunk = f"{len(payload):x}".encode()
    client = ScriptedSocket(
        b"POST http://allowed.example/upload HTTP/1.1\r\n"
        b"Host: allowed.example\r\n"
        b"Transfer-Encoding: chunked\r\n\r\n"
        + chunk
        + b"\r\n"
        + payload
        + b"\r\n0\r\n\r\n"
    )
    upstream = ScriptedSocket(b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n")
    request = read_request(client)

    forward_http(client, upstream, request)

    forwarded = bytes(upstream.sent)
    assert b"Transfer-Encoding: chunked\r\n" in forwarded
    assert payload in forwarded
    assert forwarded.endswith(b"0\r\n\r\n")


def test_http_rejects_ambiguous_framing_and_pipelined_bytes() -> None:
    client = ScriptedSocket(
        b"POST http://allowed.example/ HTTP/1.1\r\n"
        b"Host: allowed.example\r\n"
        b"Content-Length: 1\r\n"
        b"Transfer-Encoding: chunked\r\n\r\n"
    )
    upstream = ScriptedSocket()
    request = read_request(client)
    with pytest.raises(HTTPProtocolError, match="ambiguous"):
        forward_http(client, upstream, request)
    assert bytes(upstream.sent) == b""

    pipelined = ScriptedSocket(
        b"POST http://allowed.example/ HTTP/1.1\r\n"
        b"Host: allowed.example\r\n"
        b"Content-Length: 1\r\n\r\n"
        b"aGET http://metadata/ HTTP/1.1\r\nHost: metadata\r\n\r\n"
    )
    upstream = ScriptedSocket()
    request = read_request(pipelined)
    with pytest.raises(HTTPProtocolError, match="pending"):
        forward_http(pipelined, upstream, request)
    assert bytes(upstream.sent) == b""


def test_http_requires_exact_host_authority() -> None:
    client = ScriptedSocket(
        b"GET http://allowed.example/ HTTP/1.1\r\nHost: other.example\r\n\r\n"
    )
    request = read_request(client)
    with pytest.raises(HTTPProtocolError, match="Host"):
        forward_http(client, ScriptedSocket(), request)


def test_dial_pinned_uses_numeric_socket_connect_without_getaddrinfo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    class NumericSocket:
        def __init__(self, family: int) -> None:
            self.family = family

        def settimeout(self, timeout: float) -> None:
            calls.append(("timeout", timeout))

        def connect(self, address: object) -> None:
            calls.append(("connect", self.family, address))

        def close(self) -> None:
            calls.append(("close", self.family))

    monkeypatch.setattr(
        "tools.container_http_protocol.socket.socket",
        lambda family, _kind: NumericSocket(family),
    )
    monkeypatch.setattr(
        "tools.container_http_protocol.socket.create_connection",
        lambda *_args, **_kwargs: pytest.fail("socket.create_connection must not be used"),
    )
    monkeypatch.setattr(
        "tools.container_http_protocol.socket.getaddrinfo",
        lambda *_args, **_kwargs: pytest.fail("dial must not resolve DNS"),
    )

    dial_pinned(("203.0.113.10",), 443)

    assert calls[0][0] == "timeout"
    assert calls[1] == ("connect", socket.AF_INET, ("203.0.113.10", 443))
    calls.clear()
    dial_pinned(("2001:db8::10",), 443)
    assert calls[1] == ("connect", socket.AF_INET6, ("2001:db8::10", 443, 0, 0))


def test_dial_pinned_registers_before_connect_for_stop_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    closed = threading.Event()
    stopping = threading.Event()
    registered: list[object] = []
    unregistered: list[object] = []
    errors: list[BaseException] = []

    class BlockingSocket:
        def settimeout(self, _timeout: float) -> None:
            return

        def connect(self, _address: object) -> None:
            started.set()
            if not closed.wait(2):
                raise AssertionError("stop did not close the in-flight socket")
            raise OSError("connect cancelled")

        def shutdown(self, _how: int) -> None:
            closed.set()

        def close(self) -> None:
            closed.set()

    sock_obj = BlockingSocket()
    monkeypatch.setattr(
        "tools.container_http_protocol.socket.socket",
        lambda _family, _kind: sock_obj,
    )

    def run() -> None:
        try:
            dial_pinned(
                ("203.0.113.10",),
                443,
                register=registered.append,
                unregister=unregistered.append,
                stop_predicate=stopping.is_set,
            )
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    assert started.wait(2)
    assert registered == [sock_obj]
    stopping.set()
    for active in registered:
        active.close()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert isinstance(errors[0], OSError)
    assert unregistered == [sock_obj]


def test_chunk_line_accepts_crlf_split_across_recv_chunks() -> None:
    client = ScriptedSocket(
        b"POST http://allowed.example/ HTTP/1.1\r\n"
        b"Host: allowed.example\r\n"
        b"Transfer-Encoding: chunked\r\n\r\n"
        b"1\r",
        b"\nX\r\n0\r\n\r\n",
    )
    upstream = ScriptedSocket(b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n")

    forward_http(client, upstream, read_request(client))

    assert b"X\r\n0\r\n\r\n" in bytes(upstream.sent)


def test_chunked_trailer_bytes_have_a_total_limit() -> None:
    trailer_lines = b"".join(b"X: y\r\n" for _ in range(12_000))
    client = ScriptedSocket(
        b"POST http://allowed.example/ HTTP/1.1\r\n"
        b"Host: allowed.example\r\n"
        b"Transfer-Encoding: chunked\r\n\r\n"
        b"0\r\n"
        + trailer_lines
        + b"\r\n"
    )
    upstream = ScriptedSocket()

    with pytest.raises(HTTPProtocolError, match="trailer"):
        forward_http(client, upstream, read_request(client))


def test_fixed_body_has_a_64_mib_decoded_limit() -> None:
    client = ScriptedSocket(
        b"POST http://allowed.example/ HTTP/1.1\r\n"
        b"Host: allowed.example\r\n"
        b"Content-Length: 67108865\r\n\r\n"
    )
    upstream = ScriptedSocket()

    with pytest.raises(HTTPProtocolError, match="64 MiB"):
        forward_http(client, upstream, read_request(client))


def test_chunked_body_has_a_64_mib_decoded_limit() -> None:
    client = ScriptedSocket(
        b"POST http://allowed.example/ HTTP/1.1\r\n"
        b"Host: allowed.example\r\n"
        b"Transfer-Encoding: chunked\r\n\r\n"
        b"4000001\r\n"
    )
    upstream = ScriptedSocket()

    with pytest.raises(HTTPProtocolError, match="64 MiB"):
        forward_http(client, upstream, read_request(client))


def test_chunked_body_wire_limit_is_independent_of_decoded_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A small decoded body can still exceed the separate wire budget."""
    monkeypatch.setattr("tools.container_http_protocol.MAX_WIRE_BODY_BYTES", 10)
    client = ScriptedSocket(
        b"POST http://allowed.example/ HTTP/1.1\r\n"
        b"Host: allowed.example\r\n"
        b"Transfer-Encoding: chunked\r\n\r\n"
        b"1\r\nx\r\n0\r\n\r\n"
    )
    upstream = ScriptedSocket()

    with pytest.raises(HTTPProtocolError, match="wire body"):
        forward_http(client, upstream, read_request(client))
