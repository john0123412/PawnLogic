"""tools/policy_proxy.py - Loopback enforcement proxy for browser transports.

Route interception alone cannot enforce the network policy inside a browser
engine: Chromium's network manager continues redirected requests without
surfacing them to context routing (verified against the Playwright/Patchright
1.63.0 ``crNetworkManager`` source), and Service-Worker fetches bypass page and
context routes entirely. Scrapling additionally swallows ``page_setup``
exceptions before navigating, so a failed interception callback cannot be
trusted to stop the engine.

Every browser engine PawnLogic launches is therefore pointed at this loopback
proxy. Each CONNECT tunnel and each plain-HTTP request is evaluated against
the shared NetworkPolicy before any byte is forwarded; denied targets receive
HTTP 403 before a connection is made, so every redirect hop, subresource, and
service-worker fetch is authorized per connection, independent of what the
engine chooses to surface to interception. The proxy dials only the addresses
the policy resolved, so connect-time DNS cannot rebind the socket elsewhere.
"""

from __future__ import annotations

import importlib.metadata
import select
import socket
import threading
import time
import urllib.parse
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from typing import Any

from config import BROWSER_CONFIG
from tools.network_adapter import (
    BrowserRequestGuard,
    NetworkAction,
    NetworkDecision,
    evaluate_network_url_pinned,
    install_browser_route_guard,
)
from utils.ansi import c, YELLOW

_LISTEN_HOST = "127.0.0.1"
_HEADER_LIMIT = 32 * 1024
_IO_TIMEOUT = 10.0
_DENY_RESPONSE = (
    b"HTTP/1.1 403 Forbidden\r\n"
    b"Content-Length: 0\r\n"
    b"Connection: close\r\n"
    b"\r\n"
)
_TUNNEL_ACCEPTED = b"HTTP/1.1 200 Connection established\r\n\r\n"

# Scrapling 0.4.15 is the first release whose fetch exposes both the
# ``page_setup`` hook and ``additional_args`` context settings this module
# relies on; older versions silently drop the guard contract.
_MIN_SCRAPLING_VERSION = (0, 4, 15)
_MIN_SCRAPLING_VERSION_TEXT = "0.4.15"


def scrapling_version_gate() -> str | None:
    """Return a policy error when the installed Scrapling cannot be enforced.

    A missing package is not gated here: the real fetcher cannot start without
    it, and offline fakes must stay testable. A present but older version is
    denied before any fetch, because its ``page_setup`` contract cannot be
    verified.
    """
    try:
        version = importlib.metadata.version("scrapling")
    except importlib.metadata.PackageNotFoundError:
        return None
    parts: list[int] = []
    for chunk in version.split(".")[:3]:
        if not chunk.isdigit():
            return (
                "SECURITY BLOCK: unrecognized Scrapling version "
                f"'{version}'; the fetch transport cannot be verified. "
                f"Scrapling >= {_MIN_SCRAPLING_VERSION_TEXT} is required."
            )
        parts.append(int(chunk))
    while len(parts) < 3:
        parts.append(0)
    if tuple(parts) < _MIN_SCRAPLING_VERSION:
        return (
            f"SECURITY BLOCK: Scrapling {version} cannot enforce the network "
            "policy (page_setup/additional_args contract requires >= "
            f"{_MIN_SCRAPLING_VERSION_TEXT}); fetch denied."
        )
    return None


def _authority_key(url: str) -> tuple[str, int]:
    """Normalize a URL into the (host, port) key used for authorizations."""
    parts = urllib.parse.urlsplit(str(url))
    host = (parts.hostname or "").strip().lower().rstrip(".")
    port = parts.port
    if port is None:
        port = 443 if parts.scheme == "https" else 80
    return host, port


def _read_header_block(sock: Any) -> bytes:
    """Read one HTTP header block, failing closed on oversize or stall."""
    block = b""
    while b"\r\n\r\n" not in block:
        chunk = sock.recv(8192)
        if not chunk:
            raise ValueError("connection closed before request header completed")
        block += chunk
        if len(block) > _HEADER_LIMIT:
            raise ValueError("request header exceeds policy proxy limit")
    return block


def _parse_request_line(line: str) -> tuple[str, str, str]:
    pieces = line.split(" ")
    if len(pieces) != 3:
        raise ValueError(f"malformed request line: {line!r}")
    method, target, version = pieces
    return method.upper(), target, version


def _origin_form(target: str) -> str:
    parts = urllib.parse.urlsplit(target)
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    return path


def _splice(sock_a: Any, sock_b: Any) -> None:
    """Relay raw bytes between two open sockets until either side closes."""
    pair = [sock_a, sock_b]
    try:
        while True:
            readable, _, _ = select.select(pair, [], [], 1.0)
            for source in readable:
                data = source.recv(65536)
                if not data:
                    return
                sink = sock_b if source is sock_a else sock_a
                sink.sendall(data)
    except OSError:
        return
    finally:
        for sock in (sock_a, sock_b):
            with suppress(Exception):
                sock.close()


class PolicyProxy:
    """Loopback CONNECT/absolute-URI proxy enforcing NetworkPolicy per connection.

    One instance serves one browser session. Operations wrap their engine
    work in :meth:`scoped` so per-call authorizations cannot outlive the call,
    and interactive confirmations performed by the calling tool register their
    already-confirmed authority via :meth:`authorize` (the proxy thread itself
    never prompts).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._listener: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._arguments: dict | None = None
        self._authorized: set[tuple[str, int]] = set()

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> str:
        """Bind the loopback listener on an ephemeral port; return its URL."""
        with self._lock:
            if self._listener is not None:
                return self.url
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                listener.bind((_LISTEN_HOST, 0))
                listener.listen(64)
            except OSError:
                listener.close()
                raise
            self._listener = listener
            self._thread = threading.Thread(
                target=self._serve, name="pawnlogic-policy-proxy", daemon=True
            )
            self._thread.start()
            return self.url

    def stop(self) -> None:
        with self._lock:
            listener = self._listener
            self._listener = None
        if listener is not None:
            with suppress(OSError):
                listener.close()

    @property
    def url(self) -> str:
        listener = self._listener
        if listener is None:
            raise RuntimeError("policy proxy is not started")
        return f"http://{_LISTEN_HOST}:{listener.getsockname()[1]}"

    def _serve(self) -> None:
        while True:
            listener = self._listener
            if listener is None:
                return
            try:
                conn, _addr = listener.accept()
            except OSError:
                return
            worker = threading.Thread(
                target=self.handle_connection, args=(conn,), daemon=True
            )
            worker.start()

    # ── per-operation authorization scope ─────────────────────────────────

    @contextmanager
    def scoped(self, arguments: dict | None) -> Iterator[None]:
        """Evaluate connections made inside the block with *arguments*.

        Authorizations registered inside the scope are dropped when it exits,
        so a confirmed private target cannot outlive the operation that
        confirmed it.
        """
        with self._lock:
            previous_arguments = self._arguments
            self._arguments = arguments
            self._authorized.clear()
        try:
            yield
        finally:
            with self._lock:
                self._arguments = previous_arguments
                self._authorized.clear()

    def authorize(self, url: str) -> None:
        """Admit one already-confirmed authority for the current scope.

        Call this only after ``confirm_network_decision`` accepted the target:
        the proxy thread evaluates non-interactively, so a private target the
        user confirmed at tool level would otherwise be refused here.
        """
        with self._lock:
            self._authorized.add(_authority_key(url))

    # ── connection handling (public so offline tests can drive fakes) ────

    def handle_connection(self, sock: Any) -> None:
        try:
            self._handle(sock)
        except Exception:
            # Fail closed: anything unreadable, oversized, or unresolved is
            # dropped without forwarding a single byte.
            pass
        finally:
            with suppress(Exception):
                sock.close()

    def _handle(self, sock: Any) -> None:
        sock.settimeout(_IO_TIMEOUT)
        block = _read_header_block(sock)
        method, target, version = _parse_request_line(
            block.split(b"\r\n", 1)[0].decode("latin-1")
        )
        if method == "CONNECT":
            self._handle_connect(sock, target)
        else:
            self._handle_http(sock, block, target, version)

    def _evaluate(self, url: str) -> tuple[NetworkDecision, tuple[str, ...]]:
        # Non-interactive by design: the proxy thread must never prompt. A
        # private target is admitted only through a scoped authorization
        # recorded by the tool that interactively confirmed it.
        return evaluate_network_url_pinned(
            url, arguments=self._arguments, confirmation_available=False
        )

    def _denied(self, decision: NetworkDecision, url: str) -> bool:
        if decision.action == NetworkAction.ALLOW:
            return False
        return _authority_key(url) not in self._authorized

    def _dial(self, pins: tuple[str, ...], port: int) -> socket.socket:
        if not pins:
            raise ValueError("policy produced no pinned address to dial")
        last_error: OSError | None = None
        for pin in pins:
            try:
                return socket.create_connection((pin, port), _IO_TIMEOUT)
            except OSError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def _handle_connect(self, sock: Any, authority: str) -> None:
        url = f"https://{authority}/"
        decision, pins = self._evaluate(url)
        if self._denied(decision, url):
            sock.sendall(_DENY_RESPONSE)
            return
        upstream = self._dial(pins, _authority_key(url)[1])
        sock.sendall(_TUNNEL_ACCEPTED)
        sock.settimeout(None)
        _splice(sock, upstream)

    def _handle_http(self, sock: Any, block: bytes, target: str, version: str) -> None:
        parts = urllib.parse.urlsplit(target)
        if parts.scheme != "http" or not parts.hostname:
            sock.sendall(_DENY_RESPONSE)
            return
        decision, pins = self._evaluate(target)
        if self._denied(decision, target):
            sock.sendall(_DENY_RESPONSE)
            return
        upstream = self._dial(pins, parts.port or 80)
        # Rewrite the first request line to origin-form; the remainder of the
        # header block forwards verbatim.
        head, _, rest = block.partition(b"\r\n")
        method = head.split(b" ", 1)[0].decode("latin-1")
        rewritten = f"{method} {_origin_form(target)} {version}".encode("latin-1")
        upstream.sendall(rewritten + (b"\r\n" + rest if rest else b"\r\n\r\n"))
        sock.settimeout(None)
        _splice(sock, upstream)


_SHARED_POLICY_PROXY: PolicyProxy | None = None
_SHARED_POLICY_PROXY_LOCK = threading.Lock()


def start_shared_policy_proxy() -> PolicyProxy:
    """Start (or return) the process-wide enforcement proxy for browsers."""
    global _SHARED_POLICY_PROXY
    with _SHARED_POLICY_PROXY_LOCK:
        if _SHARED_POLICY_PROXY is None:
            _SHARED_POLICY_PROXY = PolicyProxy()
        _SHARED_POLICY_PROXY.start()
        return _SHARED_POLICY_PROXY


def shared_policy_proxy() -> PolicyProxy | None:
    """Return the shared proxy when it is running, else None."""
    return _SHARED_POLICY_PROXY


def reset_shared_policy_proxy() -> None:
    """Drop the shared proxy (test isolation and browser teardown)."""
    global _SHARED_POLICY_PROXY
    with _SHARED_POLICY_PROXY_LOCK:
        proxy = _SHARED_POLICY_PROXY
        _SHARED_POLICY_PROXY = None
    if proxy is not None:
        proxy.stop()


class FetchGuardState:
    """Whether the current fetch attempt actually verified its route guard.

    Scrapling may silently ignore ``page_setup`` on any attempt, so the flag
    is reset before every retry and checked after the response arrives.
    """

    def __init__(self) -> None:
        self.verified = False

    def reset(self) -> None:
        self.verified = False


def install_fetch_page_guard(
    page: Any,
    *,
    arguments: dict | None,
    proxy: PolicyProxy | None,
    state: FetchGuardState,
) -> None:
    """Install the context-level request guard for a Scrapling fetch page.

    Scrapling 0.4.15 logs and swallows ``page_setup`` exceptions and then
    navigates anyway, so on any installation failure this closes the context
    before raising: the closed context is what stops the engine, not the
    exception. Page-level routes are never used — they do not cover the
    requests issued before the page route was installed.
    """
    context = getattr(page, "context", None)
    guard: BrowserRequestGuard | None = None
    error = ""
    try:
        guard, error = install_browser_route_guard(context, arguments, proxy=proxy)
    except Exception as exc:  # pragma: no cover - defensive, fail closed
        error = f"request interception could not be installed: {type(exc).__name__}"
    if guard is None:
        close = getattr(context, "close", None)
        if callable(close):
            with suppress(Exception):
                close()
        raise RuntimeError(error)
    state.verified = True


def browser_launch_arguments() -> list[str]:
    """Chromium launch arguments for the enforced browser transport."""
    args = [
        "--disable-blink-features=AutomationControlled",
        # WebRTC can open non-proxied UDP sockets that bypass the enforcement
        # proxy; this forces every WebRTC path through the proxy or denies it.
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    ]
    if bool(BROWSER_CONFIG.get("allow_no_sandbox", False)):
        args.insert(0, "--no-sandbox")
    return args


def retry_fetch_with_enforcement(
    fetcher: Any,
    url: str,
    timeout_ms: int,
    *,
    arguments: dict | None,
    proxy: PolicyProxy,
    max_retries: int = 3,
) -> tuple[Any | None, str | None]:
    """Fetch with the full enforcement contract; return ``(response, error)``.

    The fetch session's browser context is bound to the enforcement proxy
    (``proxy``), WebRTC is forced through it (``block_webrtc``), and Service
    Workers are blocked at context creation. Each attempt registers the
    context-level request guard through Scrapling's ``page_setup``; because
    Scrapling may silently ignore the hook on any attempt, the verified flag
    resets before every retry and is re-checked after the response arrives.
    A fetcher that rejects the enforcement parameters fails closed instead
    of fetching unenforced.
    """
    state = FetchGuardState()

    def page_setup(page: Any) -> None:
        install_fetch_page_guard(page, arguments=arguments, proxy=proxy, state=state)

    engine_kwargs: dict[str, Any] = {
        "proxy": proxy.url,
        "block_webrtc": True,
        "additional_args": {"service_workers": "block"},
    }
    delays = [2, 5, 10]
    last_exc: Exception | None = None
    with proxy.scoped(arguments):
        proxy.authorize(url)
        for attempt in range(max_retries):
            state.reset()
            try:
                response = fetcher.fetch(
                    url,
                    headless=True,
                    timeout=timeout_ms,
                    page_setup=page_setup,
                    **engine_kwargs,
                )
            except TypeError as exc:
                raise RuntimeError(
                    "SECURITY BLOCK: fetch transport cannot enforce the "
                    "network policy (page_setup/proxy parameters unsupported); "
                    "fetch denied."
                ) from exc
            except Exception as exc:
                last_exc = exc
                err_name = type(exc).__name__
                is_timeout = "timeout" in str(exc).lower() or "Timeout" in err_name
                if not is_timeout or attempt == max_retries - 1:
                    raise
                delay = delays[min(attempt, len(delays) - 1)]
                print(c(
                    YELLOW,
                    f"  [Retry {attempt+1}/{max_retries}] {err_name}, "
                    f"retrying after {delay}s...",
                ))
                time.sleep(delay)
                continue
            if not state.verified:
                return None, (
                    "SECURITY BLOCK: fetch transport did not install the "
                    "network policy guard; fetch denied."
                )
            return response, None
    raise RuntimeError("fetch retry loop exhausted") from last_exc
