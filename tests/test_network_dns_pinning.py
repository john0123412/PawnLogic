"""DNS-pinning regression tests for the network adapter (issue #177.3).

The adapter must resolve a URL's host exactly once, at policy-check time,
and the connection layer must only dial those pinned addresses.  A DNS
record that changes between the check and the connection (DNS rebinding)
must not steer the socket elsewhere.

These tests use fakes and monkeypatches only; no real network, DNS, Docker,
MCP, or provider is touched.
"""

from __future__ import annotations

import io
import socket
import ssl
import urllib.request

import pytest

from core.network_policy import NetworkAction, NetworkDecision
from tools import network_adapter


class _FakeSocket:
    """Minimal socket double serving canned HTTP response bytes."""

    def __init__(self, response_bytes: bytes) -> None:
        self._response_bytes = response_bytes
        self.sent = bytearray()

    def settimeout(self, timeout) -> None:
        pass

    def setsockopt(self, *args) -> None:
        pass

    def setblocking(self, _flag: bool) -> None:
        pass

    def getpeername(self):
        return ("10.0.0.1", 80)

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)

    def makefile(self, mode: str, *args, **kwargs):
        assert "b" in mode
        return io.BytesIO(self._response_bytes)

    def close(self) -> None:
        pass


class _SequencedFakeSocket(_FakeSocket):
    """Socket double returning one canned response per ``makefile`` call."""

    def __init__(self, responses: tuple[bytes, ...]) -> None:
        super().__init__(responses[0])
        self._responses = iter(responses)

    def makefile(self, mode: str, *args, **kwargs):
        assert "b" in mode
        return io.BytesIO(next(self._responses))


def _ok_response(body: bytes = b"hello") -> bytes:
    return (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        b"Connection: close\r\n\r\n" + body
    )


def _redirect_response(location: str) -> bytes:
    return (
        b"HTTP/1.1 302 Found\r\n"
        b"Location: " + location.encode() + b"\r\n"
        b"Content-Length: 0\r\n"
        b"Connection: close\r\n\r\n"
    )


def _install_fake_dns(monkeypatch, mapping: dict[str, tuple[str, ...]]):
    """Replace the adapter resolver; fail loudly on unexpected hosts."""
    calls: list[str] = []

    def fake_resolve(host: str) -> tuple[str, ...]:
        calls.append(host)
        return mapping[host]

    monkeypatch.setattr(network_adapter, "_resolve_host_addresses", fake_resolve)
    return calls


def _install_fake_tcp(monkeypatch, responses: dict[str, bytes]):
    """Record every dial; serve canned bytes keyed by destination IP."""
    dialed: list[tuple[str, int]] = []
    sockets: list[_FakeSocket] = []

    def fake_create_connection(address, timeout=None, source_address=None):
        dialed.append((address[0], address[1]))
        sock = _FakeSocket(responses[address[0]])
        sockets.append(sock)
        return sock

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)
    return dialed, sockets


def _install_fake_tcp_sequences(monkeypatch, responses: dict[str, tuple[bytes, ...]]):
    """Record dials and return scripted responses for proxy CONNECT flows."""
    dialed: list[tuple[str, int]] = []
    sockets: list[_SequencedFakeSocket] = []

    def fake_create_connection(address, timeout=None, source_address=None):
        dialed.append((address[0], address[1]))
        sock = _SequencedFakeSocket(responses[address[0]])
        sockets.append(sock)
        return sock

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)
    return dialed, sockets


def _proxy_connect_response() -> bytes:
    return b"HTTP/1.1 200 Connection Established\r\nContent-Length: 0\r\n\r\n"


def _set_proxy(monkeypatch, scheme: str, proxy: str, no_proxy: str) -> None:
    """Set both env spellings so urllib's platform lookup is deterministic."""
    monkeypatch.setenv(f"{scheme}_proxy", proxy)
    monkeypatch.setenv(f"{scheme.upper()}_PROXY", proxy)
    monkeypatch.setenv("no_proxy", no_proxy)
    monkeypatch.setenv("NO_PROXY", no_proxy)


@pytest.fixture(autouse=True)
def _no_proxy_env(monkeypatch):
    """Pinned-direct tests must not inherit the operator's proxy env."""
    for var in (
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
    ):
        monkeypatch.delenv(var, raising=False)


def test_connect_uses_check_time_pin_not_rebound_address(monkeypatch):
    """Core TOCTOU regression: DNS changing after the check is ignored."""
    calls: list[str] = []

    def rebinding_resolver(host: str) -> tuple[str, ...]:
        calls.append(host)
        # Benign at check time, malicious if re-resolved at connect time.
        return ("93.184.216.34",) if len(calls) == 1 else ("169.254.169.254",)

    monkeypatch.setattr(network_adapter, "_resolve_host_addresses", rebinding_resolver)
    dialed, _ = _install_fake_tcp(monkeypatch, {"93.184.216.34": _ok_response()})

    req = urllib.request.Request("http://rebind.test/")
    with network_adapter.open_url_with_policy(req, timeout=5) as resp:
        assert resp.read() == b"hello"

    assert dialed == [("93.184.216.34", 80)]
    assert calls == ["rebind.test"], "DNS must be resolved exactly once"


def test_https_pin_keeps_sni_and_host_header(monkeypatch):
    """Pinned TLS dials the IP but keeps SNI/cert validation on the host."""
    _install_fake_dns(monkeypatch, {"secure.test": ("93.184.216.34",)})
    dialed, sockets = _install_fake_tcp(monkeypatch, {"93.184.216.34": _ok_response(b"ok")})
    server_hostnames: list[str | None] = []

    def fake_wrap_socket(self, sock, server_hostname=None, **kwargs):
        server_hostnames.append(server_hostname)
        return sock  # skip real TLS; the pinning under test is the dial

    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", fake_wrap_socket)

    req = urllib.request.Request("https://secure.test/")
    with network_adapter.open_url_with_policy(req, timeout=5) as resp:
        assert resp.read() == b"ok"

    assert dialed == [("93.184.216.34", 443)]
    assert server_hostnames == ["secure.test"]
    assert b"Host: secure.test" in sockets[0].sent


def test_redirect_hop_is_repinned(monkeypatch):
    """Each redirect hop is resolved and pinned independently."""
    _install_fake_dns(
        monkeypatch,
        {"start.test": ("93.184.216.34",), "hop2.test": ("142.250.72.14",)},
    )
    dialed, _ = _install_fake_tcp(
        monkeypatch,
        {
            "93.184.216.34": _redirect_response("http://hop2.test/"),
            "142.250.72.14": _ok_response(b"hello-hop-2"),
        },
    )

    req = urllib.request.Request("http://start.test/")
    with network_adapter.open_url_with_policy(req, timeout=5) as resp:
        assert resp.read() == b"hello-hop-2"

    assert dialed == [("93.184.216.34", 80), ("142.250.72.14", 80)]


def test_denied_redirect_hop_aborts_before_dial(monkeypatch):
    """A redirect to a rebinding target is blocked and never dialed."""
    _install_fake_dns(
        monkeypatch,
        {"start.test": ("93.184.216.34",), "evil.test": ("169.254.169.254",)},
    )
    dialed: list[str] = []

    def fake_create_connection(address, timeout=None, source_address=None):
        dialed.append(address[0])
        assert address[0] != "169.254.169.254", "rebound IP must never be dialed"
        return _FakeSocket(_redirect_response("http://evil.test/"))

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)
    req = urllib.request.Request("http://start.test/")
    with pytest.raises(network_adapter.NetworkPolicyBlocked):
        network_adapter.open_url_with_policy(req, timeout=5)
    assert dialed == ["93.184.216.34"]


def test_missing_pin_fails_closed_without_dns(monkeypatch):
    """A connection with no pin record refuses instead of re-resolving."""

    def fail_dial(address, *args, **kwargs):
        raise AssertionError("must not attempt any DNS or dial")

    monkeypatch.setattr(socket, "create_connection", fail_dial)
    conn = network_adapter._PinnedHTTPConnection("evil.test", 80, host_pins={})
    with pytest.raises(OSError, match="no DNS pin record"):
        conn.connect()


def test_literal_ip_url_needs_no_dns(monkeypatch):
    """Literal-IP URLs pin the literal and never touch the resolver."""

    def fail_resolver(host: str):
        raise AssertionError("resolver must not be called for literal IPs")

    monkeypatch.setattr(network_adapter, "_resolve_host_addresses", fail_resolver)
    dialed, _ = _install_fake_tcp(monkeypatch, {"93.184.216.34": _ok_response()})

    req = urllib.request.Request("http://93.184.216.34/")
    with network_adapter.open_url_with_policy(req, timeout=5) as resp:
        assert resp.read() == b"hello"

    assert dialed == [("93.184.216.34", 80)]


def test_denied_target_never_dials(monkeypatch):
    """A policy-denied target raises before any socket is created."""

    def fail_dial(address, *args, **kwargs):
        raise AssertionError(f"must not dial {address}")

    monkeypatch.setattr(socket, "create_connection", fail_dial)
    req = urllib.request.Request("http://169.254.169.254/")
    with pytest.raises(network_adapter.NetworkPolicyBlocked):
        network_adapter.open_url_with_policy(req, timeout=5)


def test_evaluate_network_url_keeps_decision_only_contract(monkeypatch):
    """The public evaluate entry still returns just the decision."""
    _install_fake_dns(monkeypatch, {"example.test": ("93.184.216.34",)})
    decision = network_adapter.evaluate_network_url("http://example.test/")
    assert isinstance(decision, NetworkDecision)
    assert decision.action == NetworkAction.ALLOW


def test_pinned_handler_replaces_default_in_opener(monkeypatch):
    """The opener actually routes through the pinned handlers."""
    _install_fake_dns(monkeypatch, {"example.test": ("93.184.216.34",)})
    dialed, _ = _install_fake_tcp(monkeypatch, {"93.184.216.34": _ok_response()})
    req = urllib.request.Request("http://example.test/")
    with network_adapter.open_url_with_policy(req, timeout=5):
        pass
    # If the default HTTPHandler were used, create_connection would have
    # received the hostname instead of the pinned IP.
    assert dialed == [("93.184.216.34", 80)]


def test_proxy_for_url_detects_env_proxy(monkeypatch):
    """Proxy detection follows urllib semantics (env + no_proxy bypass)."""
    monkeypatch.setenv("http_proxy", "http://proxy.test:3128")
    assert network_adapter._proxy_for_url("http://example.test/") == "http://proxy.test:3128"
    # Different scheme without a configured proxy: direct.
    assert network_adapter._proxy_for_url("https://example.test/") is None
    # no_proxy bypass: direct.
    monkeypatch.setenv("no_proxy", "example.test")
    assert network_adapter._proxy_for_url("http://example.test/") is None


@pytest.mark.parametrize(
    ("url", "rule"),
    [
        ("http://bad host/", "malformed_url"),
        ("http://user:pass@example.test/", "url_credentials"),
        ("http://example.test:notaport/", "invalid_port"),
        ("http://localhost/", "loopback"),
        ("http://service.internal/", "cloud_metadata"),
    ],
)
def test_denied_urls_do_not_touch_dns(monkeypatch, url, rule):
    """Syntax and unconditional target denials happen before DNS."""
    calls: list[str] = []

    def fake_resolve(host: str) -> tuple[str, ...]:
        calls.append(host)
        return ("93.184.216.34",)

    monkeypatch.setattr(network_adapter, "_resolve_host_addresses", fake_resolve)
    decision = network_adapter.evaluate_network_url(url, confirmation_available=False)

    assert decision.action == NetworkAction.DENY
    assert decision.rule == rule
    assert calls == []


def test_dns_error_is_checked_once_and_fails_closed(monkeypatch):
    """A resolver failure keeps the policy's non-interactive deny semantics."""
    calls: list[str] = []

    def failing_resolve(host: str) -> tuple[str, ...]:
        calls.append(host)
        raise socket.gaierror("synthetic DNS failure")

    monkeypatch.setattr(network_adapter, "_resolve_host_addresses", failing_resolve)
    decision = network_adapter.evaluate_network_url(
        "http://dns-error.test/",
        confirmation_available=False,
    )

    assert decision.action == NetworkAction.DENY
    assert decision.rule == "dns_result_invalid"
    assert calls == ["dns-error.test"]


def test_proxy_redirect_to_no_proxy_http_hop_uses_direct_pin(monkeypatch):
    """A proxy-to-direct HTTP redirect must not reopen hostname resolution."""
    _set_proxy(monkeypatch, "http", "http://proxy.test:3128", "direct.test")
    dns_calls = _install_fake_dns(
        monkeypatch,
        {
            "start.test": ("93.184.216.34",),
            "direct.test": ("142.250.72.14",),
        },
    )
    dialed, _ = _install_fake_tcp(
        monkeypatch,
        {
            "proxy.test": _redirect_response("http://direct.test/"),
            "142.250.72.14": _ok_response(b"direct-http"),
        },
    )

    request = urllib.request.Request("http://start.test/")
    with network_adapter.open_url_with_policy(request, timeout=5) as response:
        assert response.read() == b"direct-http"

    assert dialed == [("proxy.test", 3128), ("142.250.72.14", 80)]
    assert dns_calls == ["start.test", "direct.test"]


def test_proxy_redirect_to_no_proxy_https_hop_uses_direct_pin(monkeypatch):
    """A proxy-to-direct HTTPS redirect must pin the direct TLS socket."""
    _set_proxy(monkeypatch, "https", "http://proxy.test:3128", "direct.test")
    dns_calls = _install_fake_dns(
        monkeypatch,
        {
            "start.test": ("93.184.216.34",),
            "direct.test": ("142.250.72.14",),
        },
    )
    dialed, _ = _install_fake_tcp_sequences(
        monkeypatch,
        {
            "proxy.test": (
                _proxy_connect_response(),
                _redirect_response("https://direct.test/"),
            ),
            "142.250.72.14": (_ok_response(b"direct-https"),),
        },
    )
    monkeypatch.setattr(
        ssl.SSLContext,
        "wrap_socket",
        lambda _self, sock, server_hostname=None, **kwargs: sock,
    )

    request = urllib.request.Request("https://start.test/")
    with network_adapter.open_url_with_policy(request, timeout=5) as response:
        assert response.read() == b"direct-https"

    assert dialed == [("proxy.test", 3128), ("142.250.72.14", 443)]
    assert dns_calls == ["start.test", "direct.test"]


def test_direct_redirect_to_proxy_http_uses_proxy_resolution(monkeypatch):
    """A direct-to-proxy HTTP redirect keeps the proxy outside target pinning."""
    _set_proxy(monkeypatch, "http", "http://proxy.test:3128", "start.test")
    dns_calls = _install_fake_dns(
        monkeypatch,
        {
            "start.test": ("93.184.216.34",),
            "proxied.test": ("142.250.72.14",),
        },
    )
    dialed, _ = _install_fake_tcp(
        monkeypatch,
        {
            "93.184.216.34": _redirect_response("http://proxied.test/"),
            "proxy.test": _ok_response(b"proxied-http"),
        },
    )

    request = urllib.request.Request("http://start.test/")
    with network_adapter.open_url_with_policy(request, timeout=5) as response:
        assert response.read() == b"proxied-http"

    assert dialed == [("93.184.216.34", 80), ("proxy.test", 3128)]
    assert dns_calls == ["start.test", "proxied.test"]


def test_direct_redirect_to_proxy_https_uses_proxy_resolution(monkeypatch):
    """A direct-to-proxy HTTPS redirect keeps CONNECT on the proxy path."""
    _set_proxy(monkeypatch, "https", "http://proxy.test:3128", "start.test")
    dns_calls = _install_fake_dns(
        monkeypatch,
        {
            "start.test": ("93.184.216.34",),
            "proxied.test": ("142.250.72.14",),
        },
    )
    dialed, _ = _install_fake_tcp_sequences(
        monkeypatch,
        {
            "93.184.216.34": (_redirect_response("https://proxied.test/"),),
            "proxy.test": (
                _proxy_connect_response(),
                _ok_response(b"proxied-https"),
            ),
        },
    )
    monkeypatch.setattr(
        ssl.SSLContext,
        "wrap_socket",
        lambda _self, sock, server_hostname=None, **kwargs: sock,
    )

    request = urllib.request.Request("https://start.test/")
    with network_adapter.open_url_with_policy(request, timeout=5) as response:
        assert response.read() == b"proxied-https"

    assert dialed == [("93.184.216.34", 443), ("proxy.test", 3128)]
    assert dns_calls == ["start.test", "proxied.test"]


def test_proxied_url_skips_pinning_but_keeps_policy_gate(monkeypatch):
    """With a proxy, the policy still gates the URL before any dial."""
    monkeypatch.setenv("http_proxy", "http://proxy.test:3128")
    _install_fake_dns(monkeypatch, {"example.test": ("93.184.216.34",)})

    def fail_dial(address, *args, **kwargs):
        raise AssertionError(f"must not dial directly: {address}")

    monkeypatch.setattr(socket, "create_connection", fail_dial)
    # 169.254.169.254 is denied by policy; the proxy must never see it.
    req = urllib.request.Request("http://169.254.169.254/")
    with pytest.raises(network_adapter.NetworkPolicyBlocked):
        network_adapter.open_url_with_policy(req, timeout=5)
