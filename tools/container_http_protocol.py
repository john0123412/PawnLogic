"""Protocol and scope primitives for the container HTTP egress proxy.

The proxy intentionally accepts only HTTP/1.x requests over a private Unix
socket.  Scope resolution happens before the listener is exposed.  A request
may use a hostname only when that exact hostname was declared in the scope;
request-time DNS is never used.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Iterable, Mapping
from contextlib import suppress
import ipaddress
import re
import select
import socket
import time
from typing import Any
import urllib.parse


MAX_HEADER_BYTES = 64 * 1024
MAX_LINE_BYTES = 64 * 1024
MAX_TRAILER_BYTES = 64 * 1024
MAX_BODY_BYTES = 64 * 1024 * 1024
MAX_WIRE_BODY_BYTES = 128 * 1024 * 1024
IO_BUFFER_BYTES = 64 * 1024
MAX_TIMEOUT_SECONDS = 300.0

_TOKEN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "upgrade",
    }
)


class EgressScopeError(ValueError):
    """Raised when a scope or a request target cannot be authorized."""


class HTTPProtocolError(ValueError):
    """Raised when an HTTP request is ambiguous or unsafe to forward."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HTTPProtocolError(message)


def _normalise_host(host: str) -> str:
    value = host.strip().lower().rstrip(".")
    _require(bool(value), "empty authority host")
    return value


def _normalise_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise EgressScopeError(f"resolver returned non-numeric address '{value}'") from exc
    if "%" in value:
        raise EgressScopeError("scoped IPv6 addresses are not accepted")
    return str(address)


def _resolver_addresses(result: Iterable[Any]) -> tuple[str, ...]:
    addresses: list[str] = []
    for item in result:
        value: Any = item
        if isinstance(item, (tuple, list)):
            if len(item) < 5:
                raise EgressScopeError("resolver returned a malformed address record")
            value = item[4][0]
        if not isinstance(value, str):
            raise EgressScopeError("resolver returned a non-text address")
        address = _normalise_ip(value)
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise EgressScopeError("hostname resolved to no numeric addresses")
    return tuple(addresses)


@dataclass(frozen=True)
class EgressScope:
    """Validated, unresolved operator scope."""

    entries: tuple[str, ...]
    networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]
    hostnames: tuple[str, ...]

    def resolve(
        self,
        resolver: Callable[[str], Iterable[Any]] | None = None,
        resolved_hosts: Mapping[str, Iterable[Any] | str] | None = None,
    ) -> ResolvedEgressScope:
        """Resolve every declared hostname exactly once.

        ``resolver`` exists for deterministic tests and for callers that use
        a trusted host resolver.  Its results are validated as literal IP
        addresses before they can be used for dialing.
        """
        resolve = resolver or _default_resolver
        hostname_addresses: dict[str, tuple[str, ...]] = {}
        for hostname in self.hostnames:
            try:
                if resolved_hosts is not None:
                    if hostname not in resolved_hosts:
                        raise EgressScopeError(
                            f"pre-resolved scope is missing hostname '{hostname}'"
                        )
                    result = resolved_hosts[hostname]
                    if isinstance(result, str):
                        result = (result,)
                else:
                    result = resolve(hostname)
                hostname_addresses[hostname] = _resolver_addresses(result)
            except EgressScopeError:
                raise
            except Exception as exc:
                raise EgressScopeError(
                    f"hostname '{hostname}' could not be resolved at startup: {exc}"
                ) from exc
        return ResolvedEgressScope(
            entries=self.entries,
            networks=self.networks,
            hostname_addresses=hostname_addresses,
        )


@dataclass(frozen=True)
class ResolvedEgressScope:
    """Scope with all hostname addresses fixed for the proxy lifetime."""

    entries: tuple[str, ...]
    networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]
    hostname_addresses: Mapping[str, tuple[str, ...]]

    def resolve_target(self, host: str, port: int) -> tuple[str, int, tuple[str, ...]]:
        """Return ``(requested_host, port, numeric_dial_addresses)``.

        A literal IP is admitted only by an explicit IP/CIDR declaration.  A
        hostname is admitted only by the exact hostname declaration that was
        resolved at startup.  In particular, a resolved hostname address does
        not implicitly authorize the same address used as a literal target.
        """
        if not 1 <= port <= 65535:
            raise EgressScopeError("target port is outside 1..65535")
        normalised = _normalise_host(host)
        try:
            literal = _normalise_ip(normalised)
        except EgressScopeError:
            literal = None
        if literal is not None:
            address = ipaddress.ip_address(literal)
            if any(address in network for network in self.networks):
                return literal, port, (literal,)
            raise EgressScopeError(f"target '{host}' is not declared in the egress scope")
        addresses = self.hostname_addresses.get(normalised)
        if addresses is None:
            raise EgressScopeError(f"target '{host}' is not declared in the egress scope")
        return normalised, port, addresses


def _default_resolver(hostname: str) -> tuple[str, ...]:
    records = socket.getaddrinfo(
        hostname,
        None,
        type=socket.SOCK_STREAM,
    )
    return _resolver_addresses(records)


def parse_egress_scope(raw: str) -> EgressScope:
    """Validate a comma/space-separated hostname, IP, or CIDR scope."""
    if not isinstance(raw, str):
        raise EgressScopeError("egress scope must be text")
    entries: list[str] = []
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    hostnames: list[str] = []
    for chunk in raw.replace(",", " ").split():
        entry = chunk.strip().lower().rstrip(".")
        if not entry or entry in entries:
            continue
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            numeric_shape = all(char.isdigit() or char in ".:" for char in entry)
            if numeric_shape:
                raise EgressScopeError(
                    f"invalid egress scope entry '{entry}' (use host, IP, or CIDR)"
                ) from None
            if len(entry) > 253 or not _HOST.fullmatch(entry):
                raise EgressScopeError(
                    f"invalid egress scope entry '{entry}' (use host, IP, or CIDR)"
                ) from None
            hostnames.append(entry)
        else:
            networks.append(network)
        entries.append(entry)
    return EgressScope(tuple(entries), tuple(networks), tuple(hostnames))


@dataclass(frozen=True)
class HTTPRequest:
    """One parsed request head and bytes read after its header block."""

    method: str
    target: str
    version: str
    headers: tuple[tuple[str, str], ...]
    pending: bytes


Request = HTTPRequest


def _read_header_block(sock_obj: Any) -> tuple[bytes, bytes]:
    data = bytearray()
    while True:
        marker = data.find(b"\r\n\r\n")
        if marker >= 0:
            end = marker + 4
            if end > MAX_HEADER_BYTES or len(data) > MAX_HEADER_BYTES:
                raise HTTPProtocolError("request headers exceed proxy limit")
            return bytes(data[:end]), bytes(data[end:])
        if len(data) >= MAX_HEADER_BYTES:
            raise HTTPProtocolError("request headers exceed proxy limit")
        chunk = sock_obj.recv(min(IO_BUFFER_BYTES, MAX_HEADER_BYTES - len(data)))
        if not chunk:
            raise HTTPProtocolError("request headers are incomplete")
        if not isinstance(chunk, bytes):
            raise HTTPProtocolError("socket returned a non-bytes request chunk")
        data.extend(chunk)
        if len(data) > MAX_HEADER_BYTES:
            raise HTTPProtocolError("request headers exceed proxy limit")


def _parse_request_line(raw: bytes) -> tuple[str, str, str]:
    fields = raw.split(b" ")
    _require(len(fields) == 3 and all(fields), "malformed request line")
    try:
        method, target, version = (field.decode("ascii") for field in fields)
    except UnicodeDecodeError as exc:
        raise HTTPProtocolError("request line is not ASCII") from exc
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
        raise HTTPProtocolError("header is not valid HTTP text") from exc
    _require(_TOKEN.fullmatch(name) is not None, "invalid header name")
    _require(
        re.search(r"[\x00-\x08\x0A-\x1F\x7F]", value) is None,
        "header contains control characters",
    )
    return name, value


def _parse_headers(raw: bytes) -> tuple[tuple[str, str], ...]:
    lines = raw[:-4].split(b"\r\n")
    headers = tuple(_parse_header(line) for line in lines[1:])
    _require(
        sum(name.lower() == "host" for name, _value in headers) <= 1,
        "multiple Host headers are ambiguous",
    )
    _require(
        sum(name.lower() == "content-length" for name, _value in headers) <= 1,
        "multiple Content-Length headers are ambiguous",
    )
    _require(
        sum(name.lower() == "transfer-encoding" for name, _value in headers) <= 1,
        "multiple Transfer-Encoding headers are ambiguous",
    )
    return headers


def read_request(sock_obj: Any) -> HTTPRequest:
    """Read exactly one HTTP request head and preserve already-read bytes."""
    header_block, pending = _read_header_block(sock_obj)
    request_line = header_block.split(b"\r\n", 1)[0]
    method, target, version = _parse_request_line(request_line)
    return HTTPRequest(method, target, version, _parse_headers(header_block), pending)


def _header_values(request: HTTPRequest, name: str) -> list[str]:
    wanted = name.lower()
    return [value for key, value in request.headers if key.lower() == wanted]


def _parse_port(value: str) -> int:
    _require(bool(value) and value.isdigit() and len(value) <= 5, "invalid authority port")
    port = int(value)
    _require(1 <= port <= 65535, "invalid authority port")
    return port


def parse_authority(authority: str, *, require_port: bool) -> tuple[str, int | None]:
    """Parse an HTTP authority, accepting bracketed IPv6 literals."""
    _require(bool(authority), "invalid authority")
    _require(re.fullmatch(r"[^\s/?#@]+", authority) is not None, "invalid authority")
    if authority.startswith("["):
        end = authority.find("]")
        _require(end > 1, "invalid bracketed authority")
        host = authority[1:end]
        rest = authority[end + 1 :]
        _require(not rest or rest.startswith(":"), "invalid authority suffix")
        _require(":" in host, "brackets require an IPv6 authority")
        port_text = rest[1:] if rest else None
    else:
        _require(authority.count(":") <= 1, "IPv6 authority must be bracketed")
        host, separator, port_text = authority.partition(":")
        port_text = port_text if separator else None
        _require(bool(host), "invalid authority host")
    _require(re.fullmatch(r"[^\x00-\x20\x7F]+", host) is not None, "invalid authority host")
    if ":" not in host:
        _require(_HOST.fullmatch(host.lower().rstrip(".")) is not None, "invalid authority host")
    port = _parse_port(port_text) if port_text is not None else None
    _require(not require_port or port is not None, "authority requires a port")
    return _normalise_host(host), port


def _format_authority(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def parse_http_target(request: HTTPRequest) -> tuple[str, int, str]:
    """Validate an absolute-form HTTP request and return host, port, path."""
    try:
        parts = urllib.parse.urlsplit(request.target)
    except ValueError as exc:
        raise HTTPProtocolError("invalid HTTP request target") from exc
    _require(parts.scheme.lower() == "http", "HTTP target must use http")
    _require(bool(parts.netloc), "HTTP target must have authority")
    _require(parts.username is None and parts.password is None, "userinfo is not allowed")
    _require(not parts.fragment, "HTTP target must not contain a fragment")
    try:
        host, explicit_port = parse_authority(parts.netloc, require_port=False)
    except HTTPProtocolError:
        raise
    port = explicit_port or 80
    hosts = _header_values(request, "Host")
    _require(len(hosts) == 1, "absolute HTTP target requires one Host header")
    host_header, host_port = parse_authority(hosts[0], require_port=False)
    _require((host_header, host_port or 80) == (host, port), "Host does not match request target")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return host, port, path


def parse_connect_target(request: HTTPRequest) -> tuple[str, int]:
    """Validate a CONNECT authority and return host and port."""
    _require(request.method == "CONNECT", "CONNECT method required")
    host, port = parse_authority(request.target, require_port=True)
    if port is None:
        raise HTTPProtocolError("CONNECT authority requires a port")
    hosts = _header_values(request, "Host")
    _require(len(hosts) <= 1, "multiple Host headers are ambiguous")
    if hosts:
        host_header, host_port = parse_authority(hosts[0], require_port=False)
        _require((host_header, host_port or 443) == (host, port), "Host does not match CONNECT authority")
    return host, port


def connect_url(request: HTTPRequest) -> str:
    """Return the HTTPS policy URL for a CONNECT request."""
    host, port = parse_connect_target(request)
    return f"https://{_format_authority(host, port)}/"


class _BodyReader:
    def __init__(self, client: Any, pending: bytes) -> None:
        self.client = client
        self.pending = bytearray(pending)

    def read_exact(self, length: int) -> bytes:
        result = bytearray()
        if self.pending:
            take = min(length, len(self.pending))
            result.extend(self.pending[:take])
            del self.pending[:take]
        while len(result) < length:
            chunk = self.client.recv(min(IO_BUFFER_BYTES, length - len(result)))
            _require(bool(chunk), "request body is incomplete")
            _require(isinstance(chunk, bytes), "socket returned a non-bytes body chunk")
            _require(
                len(chunk) <= length - len(result),
                "request body contains a second request",
            )
            result.extend(chunk)
        return bytes(result)

    def read_line(self) -> bytes:
        line = bytearray()
        while True:
            marker = self.pending.find(b"\r\n")
            if marker >= 0:
                line.extend(self.pending[:marker])
                del self.pending[: marker + 2]
                _require(len(line) <= MAX_LINE_BYTES, "chunk line exceeds proxy limit")
                return bytes(line)
            if len(line) + len(self.pending) > MAX_LINE_BYTES:
                raise HTTPProtocolError("chunk line exceeds proxy limit")
            if self.pending:
                if self.pending[-1:] == b"\r":
                    line.extend(self.pending[:-1])
                    self.pending = bytearray(b"\r")
                else:
                    line.extend(self.pending)
                    self.pending.clear()
            if len(line) >= MAX_LINE_BYTES and self.pending != b"\r":
                raise HTTPProtocolError("chunk line exceeds proxy limit")
            read_size = min(
                IO_BUFFER_BYTES,
                MAX_LINE_BYTES - len(line) + (1 if self.pending == b"\r" else 0),
            )
            chunk = self.client.recv(read_size)
            _require(bool(chunk), "chunk line is incomplete")
            _require(isinstance(chunk, bytes), "socket returned a non-bytes chunk line")
            _require(len(chunk) <= read_size, "socket returned an oversized chunk line")
            self.pending.extend(chunk)


def _content_length(request: HTTPRequest) -> int | None:
    values = _header_values(request, "Content-Length")
    if not values:
        return None
    value = values[0]
    _require(value.isdigit(), "invalid Content-Length")
    try:
        return int(value)
    except ValueError as exc:
        raise HTTPProtocolError("invalid Content-Length") from exc


def _transfer_encoding(request: HTTPRequest) -> bool:
    values = _header_values(request, "Transfer-Encoding")
    if not values:
        return False
    _require(len(values) == 1, "multiple Transfer-Encoding headers are ambiguous")
    tokens = [token.strip().lower() for token in values[0].split(",") if token.strip()]
    _require(tokens == ["chunked"], "only Transfer-Encoding: chunked is supported")
    return True


def _validate_request_framing(request: HTTPRequest) -> tuple[int | None, bool]:
    length = _content_length(request)
    chunked = _transfer_encoding(request)
    _require(not (length is not None and chunked), "Content-Length and Transfer-Encoding are ambiguous")
    _require(not _header_values(request, "TE"), "TE is unsupported on the container proxy")
    _require(not _header_values(request, "Expect"), "Expect is unsupported on the container proxy")
    _require(not _header_values(request, "Upgrade"), "Upgrade is unsupported on the container proxy")
    if chunked:
        _require(request.version == "HTTP/1.1", "chunked requests require HTTP/1.1")
    return length, chunked


def _forward_header(name: str, value: str, skipped: frozenset[str]) -> str | None:
    lower = name.lower()
    if lower in skipped or lower.startswith("proxy-"):
        return None
    return f"{name}: {value}"


def build_forward_headers(
    request: HTTPRequest,
    host: str,
    port: int,
    path: str,
    *,
    length: int | None,
    chunked: bool,
) -> bytes:
    """Build an origin-form request with proxy and hop-by-hop fields removed."""
    connection_tokens = {
        token.strip().lower()
        for value in _header_values(request, "Connection")
        for token in value.split(",")
        if token.strip()
    }
    skipped = _HOP_BY_HOP | connection_tokens | {"host", "content-length", "transfer-encoding"}
    lines = [
        f"{request.method} {path} {request.version}",
        f"Host: {_format_authority(host, port)}",
    ]
    lines.extend(
        field
        for field in (_forward_header(name, value, skipped) for name, value in request.headers)
        if field is not None
    )
    if chunked:
        lines.append("Transfer-Encoding: chunked")
    elif length is not None:
        lines.append(f"Content-Length: {length}")
    lines.append("Connection: close")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")


def _forward_fixed_body(reader: _BodyReader, upstream: Any, length: int) -> None:
    remaining = length
    while remaining:
        chunk = reader.read_exact(min(IO_BUFFER_BYTES, remaining))
        upstream.sendall(chunk)
        remaining -= len(chunk)
    _require(not reader.pending, "more than one request is pending")


def _parse_chunk_size(line: bytes) -> int:
    _require(
        re.search(rb"[\x00-\x08\x0A-\x1F\x7F]", line) is None,
        "chunk line contains control characters",
    )
    token = line.split(b";", 1)[0].strip()
    _require(bool(token) and re.fullmatch(rb"[0-9A-Fa-f]+", token) is not None, "invalid chunk size")
    try:
        return int(token, 16)
    except ValueError as exc:
        raise HTTPProtocolError("invalid chunk size") from exc


def _validate_trailer(line: bytes) -> None:
    name, separator, value = line.partition(b":")
    _require(bool(separator), "malformed chunk trailer")
    try:
        name_text = name.decode("ascii")
    except UnicodeDecodeError as exc:
        raise HTTPProtocolError("invalid chunk trailer") from exc
    _require(_TOKEN.fullmatch(name_text) is not None, "invalid chunk trailer")
    _require(
        name_text.lower() not in _HOP_BY_HOP
        and name_text.lower() not in {"content-length", "host"},
        "forbidden chunk trailer",
    )
    _require(
        re.search(rb"[\x00-\x08\x0A-\x1F\x7F]", value) is None,
        "chunk trailer contains control characters",
    )


def _forward_chunked_body(reader: _BodyReader, upstream: Any) -> None:
    decoded_bytes = 0
    wire_bytes = 0
    while True:
        line = reader.read_line()
        size = _parse_chunk_size(line)
        wire_bytes += len(line) + 2
        _require(
            wire_bytes <= MAX_WIRE_BODY_BYTES,
            "chunked request wire body exceeds 128 MiB limit",
        )
        if size:
            decoded_bytes += size
            _require(
                decoded_bytes <= MAX_BODY_BYTES,
                "chunked request body exceeds 64 MiB limit",
            )
            wire_bytes += size + 2
            _require(
                wire_bytes <= MAX_WIRE_BODY_BYTES,
                "chunked request wire body exceeds 128 MiB limit",
            )
        upstream.sendall(line + b"\r\n")
        if size:
            remaining = size
            while remaining:
                piece = reader.read_exact(min(IO_BUFFER_BYTES, remaining))
                upstream.sendall(piece)
                remaining -= len(piece)
            delimiter = reader.read_exact(2)
            _require(delimiter == b"\r\n", "chunk data is missing its terminator")
            upstream.sendall(delimiter)
            continue
        trailer_bytes = 0
        while True:
            trailer = reader.read_line()
            trailer_bytes += len(trailer) + 2
            wire_bytes += len(trailer) + 2
            _require(
                trailer_bytes <= MAX_TRAILER_BYTES,
                "chunk trailer section exceeds proxy limit",
            )
            _require(
                wire_bytes <= MAX_WIRE_BODY_BYTES,
                "chunked request wire body exceeds 128 MiB limit",
            )
            if not trailer:
                upstream.sendall(b"\r\n")
                _require(not reader.pending, "more than one request is pending")
                return
            _validate_trailer(trailer)
            upstream.sendall(trailer + b"\r\n")


def forward_http(
    client: Any,
    upstream: Any,
    request: HTTPRequest,
    *,
    timeout_seconds: float = 30.0,
) -> None:
    """Forward one fixed-length or chunked HTTP request and its response."""
    _require(request.method != "CONNECT", "CONNECT must be handled as a tunnel")
    host, port, path = parse_http_target(request)
    length, chunked = _validate_request_framing(request)
    if length is not None and length < 0:
        raise HTTPProtocolError("negative Content-Length")
    if length is not None and length > MAX_BODY_BYTES:
        raise HTTPProtocolError("request body exceeds 64 MiB limit")
    reader = _BodyReader(client, request.pending)
    if length is not None:
        _require(len(reader.pending) <= length, "more than one request is pending")
    elif not chunked:
        _require(not reader.pending, "more than one request is pending")
    upstream.settimeout(timeout_seconds)
    upstream.sendall(
        build_forward_headers(
            request,
            host,
            port,
            path,
            length=length,
            chunked=chunked,
        )
    )
    if length is not None:
        _forward_fixed_body(reader, upstream, length)
    elif chunked:
        _forward_chunked_body(reader, upstream)
    else:
        _require(not reader.pending, "more than one request is pending")
    client.settimeout(timeout_seconds)
    while True:
        chunk = upstream.recv(IO_BUFFER_BYTES)
        if not chunk:
            return
        _require(isinstance(chunk, bytes), "upstream returned a non-bytes response chunk")
        client.sendall(chunk)


def dial_pinned(
    addresses: tuple[str, ...],
    port: int,
    timeout_seconds: float = 30.0,
    *,
    register: Callable[[socket.socket], None] | None = None,
    unregister: Callable[[socket.socket], None] | None = None,
    stop_predicate: Callable[[], bool] | None = None,
    deadline: float | None = None,
) -> socket.socket:
    """Dial fixed numeric addresses without invoking a hostname resolver.

    A socket is registered before ``connect`` so an operation stop can close
    an in-flight dial.  ``deadline`` is shared by every candidate address.
    """
    _require(1 <= port <= 65535, "target port is outside 1..65535")
    if not addresses:
        raise OSError("scope produced no dial addresses")
    operation_deadline = (
        deadline if deadline is not None else time.monotonic() + timeout_seconds
    )
    last_error: OSError = OSError("no scoped address was reachable")
    for address in addresses:
        numeric = _normalise_ip(address)
        if stop_predicate is not None and stop_predicate():
            raise OSError("dial cancelled by proxy stop")
        remaining = operation_deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("dial deadline expired")
        family = socket.AF_INET6 if ipaddress.ip_address(numeric).version == 6 else socket.AF_INET
        sock_obj = socket.socket(family, socket.SOCK_STREAM)
        registered = False
        keep_socket = False
        try:
            if register is not None:
                register(sock_obj)
                registered = True
            if stop_predicate is not None and stop_predicate():
                raise OSError("dial cancelled by proxy stop")
            remaining = operation_deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("dial deadline expired")
            sock_obj.settimeout(remaining)
            endpoint: tuple[object, ...] = (
                (numeric, port, 0, 0)
                if family == socket.AF_INET6
                else (numeric, port)
            )
            sock_obj.connect(endpoint)
            if stop_predicate is not None and stop_predicate():
                raise OSError("dial cancelled by proxy stop")
            keep_socket = True
            return sock_obj
        except OSError as exc:
            last_error = exc
        finally:
            if not keep_socket:
                if registered and unregister is not None:
                    unregister(sock_obj)
                close_socket(sock_obj)
    raise last_error


def close_socket(sock_obj: Any) -> None:
    """Best-effort shutdown used by normal completion and stop races."""
    with suppress(Exception):
        sock_obj.shutdown(socket.SHUT_RDWR)
    with suppress(Exception):
        sock_obj.close()


def relay_streams(
    client: Any,
    upstream: Any,
    pending: bytes = b"",
    *,
    timeout_seconds: float = 30.0,
    close_sockets: bool = True,
) -> None:
    """Relay a CONNECT tunnel with bounded idle deadlines and clean shutdown."""
    if pending:
        upstream.sendall(pending)
    client.settimeout(timeout_seconds)
    upstream.settimeout(timeout_seconds)
    pair = (client, upstream)
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            readable, _, _ = select.select(pair, [], [], min(0.2, remaining))
            for source in readable:
                data = source.recv(IO_BUFFER_BYTES)
                if not data:
                    return
                sink = upstream if source is client else client
                sink.sendall(data)
                deadline = time.monotonic() + timeout_seconds
    except (OSError, ValueError):
        return
    finally:
        if close_sockets:
            close_socket(client)
            close_socket(upstream)


__all__ = [
    "MAX_BODY_BYTES",
    "MAX_HEADER_BYTES",
    "MAX_LINE_BYTES",
    "MAX_TRAILER_BYTES",
    "MAX_WIRE_BODY_BYTES",
    "EgressScope",
    "EgressScopeError",
    "HTTPProtocolError",
    "HTTPRequest",
    "Request",
    "ResolvedEgressScope",
    "build_forward_headers",
    "close_socket",
    "connect_url",
    "dial_pinned",
    "forward_http",
    "parse_authority",
    "parse_connect_target",
    "parse_egress_scope",
    "parse_http_target",
    "read_request",
    "relay_streams",
]
