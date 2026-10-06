"""Integration tests for the private container HTTP egress proxy."""

from __future__ import annotations

from pathlib import Path
import socket
import tempfile
import threading
from collections.abc import Iterator

import pytest

from tools import container_http_proxy
from tools.container_http_proxy import ContainerHTTPProxy


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    """Keep AF_UNIX test paths below the platform's 108-byte limit."""
    repo_root = Path(__file__).resolve().parents[1]
    temp_parent = repo_root / ".agent-work" / "tmp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="u-", dir=temp_parent) as directory:
        yield Path(directory)


def _serve_response(upstream: socket.socket, response: bytes) -> threading.Thread:
    def serve() -> None:
        try:
            upstream.recv(64 * 1024)
            upstream.sendall(response)
        finally:
            upstream.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return thread


def test_start_uses_only_a_private_unix_socket_and_pre_resolved_hosts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialed: list[tuple[tuple[str, ...], int]] = []
    upstream, server = socket.socketpair()

    def fake_dial(
        addresses: tuple[str, ...],
        port: int,
        _timeout: float,
        **_kwargs: object,
    ) -> socket.socket:
        dialed.append((addresses, port))
        return upstream

    monkeypatch.setattr(container_http_proxy, "dial_pinned", fake_dial)
    monkeypatch.setattr(
        container_http_proxy.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: pytest.fail("pre-resolved hosts must not trigger DNS"),
    )
    proxy = ContainerHTTPProxy(
        str(tmp_path),
        "allowed.example",
        resolved_hosts={"allowed.example": ("93.184.216.34",)},
    )
    path = proxy.start()
    response_thread = _serve_response(
        server,
        b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK",
    )
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(path))
        client.sendall(
            b"GET http://allowed.example/ HTTP/1.1\r\n"
            b"Host: allowed.example\r\n\r\n"
        )
        assert b"200 OK" in client.recv(4096)
        assert path.is_socket()
        assert dialed == [(('93.184.216.34',), 80)]
        assert proxy._listener is not None
        assert proxy._listener.family == socket.AF_UNIX
    finally:
        client.close()
        proxy.stop()
        response_thread.join(timeout=2)
    assert not path.exists()


def test_unknown_target_is_denied_before_dial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dialed = False

    def fail_dial(*_args: object, **_kwargs: object) -> socket.socket:
        nonlocal dialed
        dialed = True
        raise AssertionError("denied target must not be dialed")

    monkeypatch.setattr(container_http_proxy, "dial_pinned", fail_dial)
    proxy = ContainerHTTPProxy(
        str(tmp_path),
        "allowed.example",
        resolved_hosts={"allowed.example": ("93.184.216.34",)},
    )
    path = proxy.start()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(path))
        client.sendall(
            b"GET http://unknown.example/ HTTP/1.1\r\n"
            b"Host: unknown.example\r\n\r\n"
        )
        assert b"403 Target denied" in client.recv(4096)
    finally:
        client.close()
        proxy.stop()
    assert dialed is False


def test_connect_is_a_scoped_tunnel_with_pending_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream, server = socket.socketpair()
    dialed: list[tuple[tuple[str, ...], int]] = []

    def fake_dial(
        addresses: tuple[str, ...],
        port: int,
        _timeout: float,
        **_kwargs: object,
    ) -> socket.socket:
        dialed.append((addresses, port))
        return upstream

    def echo() -> None:
        try:
            while True:
                data = server.recv(4096)
                if not data:
                    return
                server.sendall(data)
        finally:
            server.close()

    monkeypatch.setattr(container_http_proxy, "dial_pinned", fake_dial)
    thread = threading.Thread(target=echo, daemon=True)
    thread.start()
    proxy = ContainerHTTPProxy(
        str(tmp_path),
        "allowed.example",
        resolved_hosts={"allowed.example": ("93.184.216.34",)},
    )
    path = proxy.start()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(path))
        client.sendall(
            b"CONNECT allowed.example:443 HTTP/1.1\r\n"
            b"Host: allowed.example:443\r\n\r\n"
            b"pending"
        )
        client.settimeout(2)
        accepted = bytearray()
        while b"\r\n\r\npending" not in accepted:
            accepted.extend(client.recv(4096))
        assert b"200 Connection Established" in accepted
        client.sendall(b"payload")
        assert client.recv(4096) == b"payload"
        assert dialed == [(('93.184.216.34',), 443)]
    finally:
        client.close()
        proxy.stop()
        thread.join(timeout=2)


def test_network_policy_denies_loopback_even_when_scope_declares_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        container_http_proxy,
        "dial_pinned",
        lambda *_args, **_kwargs: pytest.fail("loopback must be denied before dialing"),
    )
    proxy = ContainerHTTPProxy(
        str(tmp_path),
        "loopback.example",
        resolved_hosts={"loopback.example": ("127.0.0.1",)},
    )
    path = proxy.start()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(path))
        client.sendall(
            b"GET http://loopback.example/ HTTP/1.1\r\n"
            b"Host: loopback.example\r\n\r\n"
        )
        assert b"403 Target denied" in client.recv(4096)
    finally:
        client.close()
        proxy.stop()


def test_network_policy_denies_literal_mapped_metadata_before_dial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        container_http_proxy,
        "dial_pinned",
        lambda *_args, **_kwargs: pytest.fail("mapped metadata must be denied before dialing"),
    )
    proxy = ContainerHTTPProxy(
        str(tmp_path),
        "::ffff:100.100.100.200",
    )
    path = proxy.start()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(path))
        client.sendall(
            b"GET http://[::ffff:100.100.100.200]/ HTTP/1.1\r\n"
            b"Host: [::ffff:100.100.100.200]\r\n\r\n"
        )
        assert b"403 Target denied" in client.recv(4096)
    finally:
        client.close()
        proxy.stop()


def test_network_policy_denies_mapped_metadata_hostname_snapshot_before_dial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        container_http_proxy,
        "dial_pinned",
        lambda *_args, **_kwargs: pytest.fail(
            "mapped metadata hostname snapshot must be denied before dialing"
        ),
    )
    proxy = ContainerHTTPProxy(
        str(tmp_path),
        "metadata-snapshot.example",
        resolved_hosts={"metadata-snapshot.example": ("::ffff:100.100.100.200",)},
    )
    path = proxy.start()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(path))
        client.sendall(
            b"GET http://metadata-snapshot.example/ HTTP/1.1\r\n"
            b"Host: metadata-snapshot.example\r\n\r\n"
        )
        assert b"403 Target denied" in client.recv(4096)
    finally:
        client.close()
        proxy.stop()


def test_stop_closes_an_active_connect_tunnel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream, server = socket.socketpair()

    def hold_upstream() -> None:
        try:
            while server.recv(4096):
                pass
        except OSError:
            pass
        finally:
            server.close()

    monkeypatch.setattr(
        container_http_proxy,
        "dial_pinned",
        lambda *_args, **_kwargs: upstream,
    )
    thread = threading.Thread(target=hold_upstream, daemon=True)
    thread.start()
    proxy = ContainerHTTPProxy(
        str(tmp_path),
        "allowed.example",
        resolved_hosts={"allowed.example": ("93.184.216.34",)},
    )
    path = proxy.start()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(path))
        client.sendall(
            b"CONNECT allowed.example:443 HTTP/1.1\r\n"
            b"Host: allowed.example:443\r\n\r\n"
        )
        assert b"200 Connection Established" in client.recv(4096)
        proxy.stop()
        client.settimeout(2)
        assert client.recv(1) == b""
    finally:
        client.close()
        proxy.stop()
        thread.join(timeout=2)


def test_operation_timer_revokes_an_idle_handler(tmp_path: Path) -> None:
    proxy = ContainerHTTPProxy(
        str(tmp_path),
        "93.184.216.34/32",
        timeout_seconds=1,
    )
    path = proxy.start()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(path))
        client.settimeout(3)
        assert client.recv(1) == b""
        assert proxy.running is False
    finally:
        client.close()
        proxy.stop()


def test_stop_removes_listener_and_is_idempotent(tmp_path: Path) -> None:
    proxy = ContainerHTTPProxy(str(tmp_path), "93.184.216.34/32")
    path = proxy.start()
    assert path.exists()
    proxy.stop()
    proxy.stop()
    assert not path.exists()
    assert proxy.running is False
    with pytest.raises(RuntimeError, match="cannot be restarted"):
        proxy.start()


def test_start_fails_closed_when_pre_resolved_host_is_missing(tmp_path: Path) -> None:
    proxy = ContainerHTTPProxy(
        str(tmp_path),
        "allowed.example",
        resolved_hosts={},
    )
    with pytest.raises(ValueError, match="missing hostname"):
        proxy.start()
    assert not (tmp_path / "egress.sock").exists()
