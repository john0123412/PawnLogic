"""Strict one-request HTTP proxy protocol handling for browser transports."""

from __future__ import annotations

import re
import select
import socket
import time
import urllib.parse
from dataclasses import dataclass
from contextlib import suppress
from typing import Any


_HEADER_LIMIT = 32 * 1024
_IO_TIMEOUT = 10.0
_BODY_LIMIT = 8 * 1024 * 1024
_TOKEN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_HOP_BY_HOP = frozenset(("connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "proxy-connection", "te", "trailer", "transfer-encoding", "upgrade"))


class ProxyProtocolError(ValueError):
    """Raised when a proxy request cannot be safely represented upstream."""


@dataclass(frozen=True)
class Request:
    """A parsed request head and bytes already read after its header block."""

    method: str
    target: str
    version: str
    headers: tuple[tuple[str, str], ...]
    pending: bytes


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProxyProtocolError(message)


def _read_header_block(sock: Any) -> tuple[bytes, bytes]:
    data = bytearray()
    while True:
        marker = data.find(b"\r\n\r\n")
        if marker >= 0:
            end = marker + 4
            if end > _HEADER_LIMIT:
                raise ProxyProtocolError("request header exceeds proxy limit")
            return bytes(data[:end]), bytes(data[end:])
        if len(data) >= _HEADER_LIMIT:
            raise ProxyProtocolError("request header exceeds proxy limit")
        chunk = sock.recv(min(8192, _HEADER_LIMIT - len(data)))
        _require(bool(chunk), "request header is incomplete")
        _require(isinstance(chunk, bytes), "socket returned a non-bytes request chunk")
        data.extend(chunk)


def _decode_request_line(raw: bytes) -> tuple[str, str, str]:
    fields = raw.split(b" ")
    _require(len(fields) == 3, "malformed request line")
    _require(all(fields), "malformed request line")
    try:
        method, target, version = (field.decode("ascii") for field in fields)
    except UnicodeDecodeError as exc:
        raise ProxyProtocolError("request line is not ASCII") from exc
    _require(_TOKEN.fullmatch(method) is not None, "invalid request method")
    _require(version in {"HTTP/1.0", "HTTP/1.1"}, "invalid HTTP version")
    _require(
        all(ord(char) >= 0x20 and ord(char) != 0x7F for char in target),
        "request target contains control characters",
    )
    return method.upper(), target, version


def _parse_header(line: bytes) -> tuple[str, str]:
    _require(bool(line), "invalid folded or empty header")
    _require(line[:1] not in {b" ", b"\t"}, "invalid folded header")
    name_raw, separator, value_raw = line.partition(b":")
    _require(bool(separator), "malformed header")
    try:
        name = name_raw.decode("ascii")
        value = value_raw.decode("latin-1").strip(" \t")
    except UnicodeDecodeError as exc:
        raise ProxyProtocolError("header is not valid HTTP text") from exc
    _require(_TOKEN.fullmatch(name) is not None, "invalid header name")
    _require(
        re.search(r"[\x00-\x08\x0A-\x1F\x7F]", value) is None,
        "header contains control characters",
    )
    return name, value


def _parse_headers(raw: bytes) -> tuple[tuple[str, str], ...]:
    lines = raw[:-4].split(b"\r\n")
    headers = tuple(_parse_header(line) for line in lines[1:])
    host_count = sum(name.lower() == "host" for name, _value in headers)
    _require(host_count <= 1, "multiple Host headers are ambiguous")
    lengths = [value for name, value in headers if name.lower() == "content-length"]
    _require(len(lengths) <= 1, "multiple Content-Length headers are ambiguous")
    _require(all(value.isdigit() for value in lengths), "invalid Content-Length")
    return headers


def read_request(sock: Any) -> Request:
    """Read exactly one HTTP request head, preserving bytes after the head."""
    header_block, pending = _read_header_block(sock)
    request_line = header_block.split(b"\r\n", 1)[0]
    method, target, version = _decode_request_line(request_line)
    return Request(method, target, version, _parse_headers(header_block), pending)


def _header_values(request: Request, name: str) -> list[str]:
    wanted = name.lower()
    return [value for key, value in request.headers if key.lower() == wanted]


def _parse_authority(authority: str, *, require_port: bool) -> tuple[str, int | None]:
    _require(bool(authority), "invalid authority")
    _require(re.fullmatch(r"[^\s/?#@]+", authority) is not None, "invalid authority")
    host: str
    port_text: str | None
    if authority.startswith("["):
        end = authority.find("]")
        _require(end > 1, "invalid bracketed authority")
        host = authority[1:end]
        rest = authority[end + 1 :]
        if rest:
            _require(rest.startswith(":"), "invalid authority suffix")
        port_text = rest[1:] if rest else None
        _require(":" in host, "brackets require an IPv6 authority")
    else:
        _require(authority.count(":") <= 1, "IPv6 authority must be bracketed")
        host, separator, port_text = authority.partition(":")
        port_text = port_text if separator else None
        _require(bool(host), "invalid authority host")
        _require(re.fullmatch(r"[A-Za-z0-9.-]+", host) is not None, "invalid authority host")
    _require(re.fullmatch(r"[^\x00-\x20\x7F]+", host) is not None, "invalid authority host")
    port = _parse_port(port_text) if port_text is not None else None
    _require((port is not None) if require_port else True, "CONNECT authority requires a port")
    return host.lower().rstrip("."), port


def _parse_port(value: str) -> int:
    _require(value.isdigit(), "invalid authority port")
    _require(len(value) <= 5, "invalid authority port")
    port = int(value)
    _require(1 <= port <= 65535, "invalid authority port")
    return port


def _url_authority(target: str) -> tuple[str, int]:
    try:
        parts = urllib.parse.urlsplit(target)
    except ValueError as exc:
        raise ProxyProtocolError("invalid request target authority") from exc
    _require(parts.scheme.lower() == "http", "HTTP request target must use http")
    _require(bool(parts.netloc), "HTTP request target must have authority")
    _require(parts.username is None, "userinfo is not allowed in request target")
    _require(parts.password is None, "userinfo is not allowed in request target")
    _require(not parts.fragment, "request target must not contain a fragment")
    host, port = _parse_authority(parts.netloc, require_port=False)
    return host, port or 80


def _format_authority(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def connect_url(request: Request) -> str:
    """Return the policy URL after validating request/Host authority."""
    hosts = _header_values(request, "Host")
    _require(len(hosts) <= 1, "multiple Host headers are ambiguous")
    if request.method == "CONNECT":
        host, port = _parse_authority(request.target, require_port=True)
        if port is None:
            raise ProxyProtocolError("CONNECT authority requires a port")
        authority = _format_authority(host, port)
        if hosts:
            host_header, host_port = _parse_authority(hosts[0], require_port=False)
            if (host_header, host_port or 443) != (host, port):
                raise ProxyProtocolError("Host does not match CONNECT authority")
        return f"https://{authority}/"
    host, port = _url_authority(request.target)
    _require(len(hosts) == 1, "absolute HTTP request requires one Host header")
    host_header, host_port = _parse_authority(hosts[0], require_port=False)
    _require((host_header, host_port or 80) == (host, port), "Host does not match request authority")
    return request.target


def _origin_form(target: str) -> str:
    parts = urllib.parse.urlsplit(target)
    path = parts.path or "/"
    return f"{path}?{parts.query}" if parts.query else path


def _body_length(request: Request) -> int:
    values = _header_values(request, "Content-Length")
    value = values[0] if values else None
    _require(value is None or value.isdigit(), "invalid Content-Length")
    return int(value) if value is not None else 0


def _forward_header(name: str, value: str, skipped: frozenset[str]) -> str | None:
    if name.lower() in skipped or name.lower().startswith("proxy-"):
        return None
    return f"{name}: {value}"


def _forward_headers(request: Request, authority: str, length: int) -> bytes:
    connection_tokens = {
        token.strip().lower()
        for value in _header_values(request, "Connection")
        for token in value.split(",")
        if token.strip()
    }
    skipped = _HOP_BY_HOP | connection_tokens | {"host", "content-length"}
    lines = [f"{request.method} {_origin_form(request.target)} {request.version}", f"Host: {authority}"]
    lines.extend(
        filter(None, (_forward_header(name, value, skipped) for name, value in request.headers))
    )
    if _header_values(request, "Content-Length"):
        lines.append(f"Content-Length: {length}")
    lines.append("Connection: close")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")


def _read_body(client: Any, request: Request, length: int) -> bytes:
    _require(len(request.pending) <= length, "more than one request is pending")
    body = bytearray(request.pending)
    while len(body) < length:
        chunk = client.recv(length - len(body))
        _require(bool(chunk), "request body is incomplete")
        _require(len(chunk) <= length - len(body), "request body contains a second request")
        body.extend(chunk)
    return bytes(body)


def forward_http(client: Any, upstream: Any, request: Request) -> None:
    """Forward one validated HTTP request and copy the upstream response."""
    _require(request.method != "CONNECT", "CONNECT must be handled as a tunnel")
    url = connect_url(request)
    framing = _header_values(request, "Transfer-Encoding") + _header_values(request, "TE")
    _require(not framing, "Transfer-Encoding and TE are unsupported")
    _require(not _header_values(request, "Upgrade"), "Upgrade requests are unsupported")
    _require(not _header_values(request, "Expect"), "Expect requests are unsupported")
    length = _body_length(request)
    _require(length <= _BODY_LIMIT, "request body exceeds proxy limit")
    parts = urllib.parse.urlsplit(url)
    authority = _format_authority(parts.hostname or "", parts.port or 80)
    body = _read_body(client, request, length)
    upstream.settimeout(_IO_TIMEOUT)
    upstream.sendall(_forward_headers(request, authority, length) + body)
    client.settimeout(_IO_TIMEOUT)
    while True:
        chunk = upstream.recv(65536)
        if not chunk:
            return
        client.sendall(chunk)


def close_socket(sock: Any) -> None:
    with suppress(Exception):
        sock.shutdown(socket.SHUT_RDWR)
    with suppress(Exception):
        sock.close()


def splice(sock_a: Any, sock_b: Any) -> None:
    """Relay a CONNECT tunnel with bounded idle and send timeouts."""
    pair = (sock_a, sock_b)
    deadline = time.monotonic() + _IO_TIMEOUT
    try:
        sock_a.settimeout(_IO_TIMEOUT)
        sock_b.settimeout(_IO_TIMEOUT)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            readable, _, _ = select.select(pair, [], [], min(0.2, remaining))
            if not readable:
                continue
            for source in readable:
                data = source.recv(65536)
                if not data:
                    return
                sink = sock_b if source is sock_a else sock_a
                sink.sendall(data)
                deadline = time.monotonic() + _IO_TIMEOUT
    except Exception:
        return
    finally:
        close_socket(sock_a)
        close_socket(sock_b)


def dial_pinned(pins: tuple[str, ...], port: int) -> socket.socket:
    """Dial only policy-approved numeric addresses, without hostname fallback."""
    if not pins:
        raise ValueError("policy produced no pinned address to dial")
    last_error: OSError = OSError("no pinned address was reachable")
    for pin in pins:
        try:
            return socket.create_connection((pin, port), _IO_TIMEOUT)
        except OSError as exc:
            last_error = exc
    raise last_error
