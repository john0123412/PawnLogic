"""Offline tests for the browser enforcement proxy (tools/policy_proxy.py)."""

from __future__ import annotations

import contextlib
import importlib.metadata
import socket
import threading

import pytest

from tools import policy_proxy
from tools.policy_proxy import PolicyProxy, scrapling_version_gate


def _addrinfo_for(address: str):
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            (address, 0),
        )
    ]


class FakeSock:
    def __init__(self, data: bytes = b"") -> None:
        self._data = data
        self.sent = b""
        self.closed = False
        self.timeouts: list[float | None] = []

    def recv(self, _size: int) -> bytes:
        chunk, self._data = self._data[:4096], self._data[4096:]
        return chunk

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def settimeout(self, value: float | None) -> None:
        self.timeouts.append(value)

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def no_splice(monkeypatch: pytest.MonkeyPatch):
    """Replace the byte relay so fake sockets never touch select()."""
    relays: list[tuple[object, object]] = []

    def fake_splice(sock_a: object, sock_b: object) -> None:
        relays.append((sock_a, sock_b))

    monkeypatch.setattr(policy_proxy, "_splice", fake_splice)
    return relays


def _patch_dns(monkeypatch: pytest.MonkeyPatch, addresses: list[str]):
    calls: list[str] = []

    def fake_getaddrinfo(host: str, *_args: object, **_kwargs: object):
        calls.append(host)
        return _addrinfo_for(addresses[min(len(calls), len(addresses)) - 1])

    monkeypatch.setattr(policy_proxy.socket, "getaddrinfo", fake_getaddrinfo)
    return calls


def test_connect_denies_private_target_before_dialing(monkeypatch):
    calls = _patch_dns(monkeypatch, ["93.184.216.34"])
    dialed: list[tuple[str, int]] = []

    def fake_create_connection(address: tuple[str, int], _timeout: float):
        dialed.append(address)
        raise AssertionError("denied CONNECT must not open an upstream socket")

    monkeypatch.setattr(policy_proxy.socket, "create_connection", fake_create_connection)
    client = FakeSock(b"CONNECT 192.168.1.5:443 HTTP/1.1\r\nHost: x\r\n\r\n")

    PolicyProxy().handle_connection(client)

    assert client.sent == policy_proxy._DENY_RESPONSE
    assert dialed == []
    assert calls == []  # literal IP: not even a DNS lookup


def test_connect_allows_public_target_and_dials_policy_pins(monkeypatch, no_splice):
    calls = _patch_dns(monkeypatch, ["93.184.216.34", "6.6.6.6"])
    dialed: list[tuple[str, int]] = []
    upstream = FakeSock()

    def fake_create_connection(address: tuple[str, int], _timeout: float):
        dialed.append(address)
        return upstream

    monkeypatch.setattr(policy_proxy.socket, "create_connection", fake_create_connection)
    client = FakeSock(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com\r\n\r\n")

    proxy = PolicyProxy()
    proxy.handle_connection(client)

    assert client.sent == policy_proxy._TUNNEL_ACCEPTED
    # Policy-time resolution dialed exactly the resolved address, once — a
    # changed DNS record between check and connect cannot steer the socket.
    assert dialed == [("93.184.216.34", 443)]
    assert calls == ["example.com"]
    assert no_splice == [(client, upstream)]


def test_authorized_private_authority_is_admitted_inside_scope_only(monkeypatch):
    dialed: list[tuple[str, int]] = []

    def fake_create_connection(address: tuple[str, int], _timeout: float):
        dialed.append(address)
        return FakeSock()

    monkeypatch.setattr(policy_proxy.socket, "create_connection", fake_create_connection)
    monkeypatch.setattr(policy_proxy, "_splice", lambda *_args: None)
    proxy = PolicyProxy()
    client_inside = FakeSock(b"CONNECT 192.168.1.5:8443 HTTP/1.1\r\n\r\n")

    with proxy.scoped(None):
        proxy.authorize("https://192.168.1.5:8443/app")
        proxy.handle_connection(client_inside)
    assert client_inside.sent == policy_proxy._TUNNEL_ACCEPTED
    assert dialed == [("192.168.1.5", 8443)]

    # The authorization is scoped: after the operation the same authority
    # is refused again (non-interactive private target).
    client_after = FakeSock(b"CONNECT 192.168.1.5:8443 HTTP/1.1\r\n\r\n")
    proxy.handle_connection(client_after)
    assert client_after.sent == policy_proxy._DENY_RESPONSE
    assert dialed == [("192.168.1.5", 8443)]


def test_authorizing_one_target_does_not_admit_a_redirect_target():
    proxy = PolicyProxy()
    with proxy.scoped(None):
        proxy.authorize("https://public.example.test/landing")
        # A redirect hop connects to a different authority: every connection
        # is evaluated on its own, so the redirect target is still denied.
        client = FakeSock(b"CONNECT 10.0.0.7:443 HTTP/1.1\r\n\r\n")
        proxy.handle_connection(client)
        assert client.sent == policy_proxy._DENY_RESPONSE


def test_plain_http_request_is_rewritten_and_forwarded(monkeypatch, no_splice):
    _patch_dns(monkeypatch, ["93.184.216.34"])
    dialed: list[tuple[str, int]] = []
    upstream = FakeSock()

    def fake_create_connection(address: tuple[str, int], _timeout: float):
        dialed.append(address)
        return upstream

    monkeypatch.setattr(policy_proxy.socket, "create_connection", fake_create_connection)
    client = FakeSock(
        b"GET http://example.com/path?q=1 HTTP/1.1\r\nHost: example.com\r\n\r\n"
    )

    PolicyProxy().handle_connection(client)

    assert dialed == [("93.184.216.34", 80)]
    assert upstream.sent == (
        b"GET /path?q=1 HTTP/1.1\r\nHost: example.com\r\n\r\n"
    )
    assert no_splice == [(client, upstream)]


def test_plain_http_loopback_target_is_denied(monkeypatch):
    _patch_dns(monkeypatch, ["93.184.216.34"])

    def fake_create_connection(_address: tuple[str, int], _timeout: float):
        raise AssertionError("denied request must not open an upstream socket")

    monkeypatch.setattr(policy_proxy.socket, "create_connection", fake_create_connection)
    client = FakeSock(b"GET http://127.0.0.1:9000/metadata HTTP/1.1\r\n\r\n")

    PolicyProxy().handle_connection(client)

    assert client.sent == policy_proxy._DENY_RESPONSE


def test_oversized_header_block_fails_closed_without_dialing(monkeypatch):
    dialed: list[tuple[str, int]] = []

    def fake_create_connection(address: tuple[str, int], _timeout: float):
        dialed.append(address)
        raise AssertionError

    monkeypatch.setattr(policy_proxy.socket, "create_connection", fake_create_connection)
    oversized = b"CONNECT example.com:443 HTTP/1.1\r\nX-A: " + b"A" * (40 * 1024)
    client = FakeSock(oversized)

    PolicyProxy().handle_connection(client)

    assert client.sent == b""
    assert client.closed is True
    assert dialed == []


def test_malformed_request_line_fails_closed(monkeypatch):
    monkeypatch.setattr(
        policy_proxy.socket,
        "create_connection",
        lambda *_a: pytest.fail("malformed input must not dial"),
    )
    client = FakeSock(b"NOT-A-REQUEST\r\n\r\n")

    PolicyProxy().handle_connection(client)

    assert client.sent == b""
    assert client.closed is True


def test_splice_relays_bytes_and_stops_on_client_close():
    left, right = socket.socketpair()
    up_a, up_b = socket.socketpair()
    for sock in (left, right, up_a, up_b):
        sock.settimeout(2)
    relay_done = threading.Event()

    def run() -> None:
        policy_proxy._splice(left, up_a)
        relay_done.set()

    relay = threading.Thread(target=run, daemon=True)
    relay.start()
    try:
        right.sendall(b"ping")
        assert up_b.recv(65536) == b"ping"
        right.close()
        assert relay_done.wait(2)
    finally:
        for sock in (left, right, up_a, up_b):
            with contextlib.suppress(OSError):
                sock.close()


def test_start_binds_loopback_and_reports_proxy_url():
    proxy = PolicyProxy()
    url = proxy.start()
    try:
        assert url.startswith("http://127.0.0.1:")
        port = int(url.rsplit(":", 1)[1])
        assert 0 < port < 65536
    finally:
        proxy.stop()


def test_scrapling_version_gate(monkeypatch):
    real_version = importlib.metadata.version

    def fake_version(package: str) -> str:
        if package == "scrapling":
            return "0.4.14"
        return real_version(package)

    monkeypatch.setattr(importlib.metadata, "version", fake_version)
    blocked = scrapling_version_gate()
    assert blocked is not None
    assert blocked.startswith("SECURITY BLOCK")

    monkeypatch.setattr(
        importlib.metadata,
        "version",
        lambda package: "0.4.15" if package == "scrapling" else real_version(package),
    )
    assert scrapling_version_gate() is None

    monkeypatch.setattr(
        importlib.metadata,
        "version",
        lambda package: ("0.5.0" if package == "scrapling" else real_version(package)),
    )
    assert scrapling_version_gate() is None

    def missing(package: str) -> str:
        if package == "scrapling":
            raise importlib.metadata.PackageNotFoundError(package)
        return real_version(package)

    monkeypatch.setattr(importlib.metadata, "version", missing)
    assert scrapling_version_gate() is None
