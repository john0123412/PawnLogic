"""tools/policy_proxy.py - Loopback enforcement proxy for browser transports.

Route interception alone cannot enforce the network policy inside a browser
engine: Chromium's network manager continues redirected requests without
surfacing them to context routing (verified against the Playwright/Patchright
1.63.0 ``crNetworkManager`` source), and Service Worker routing coverage
depends on the SDK and context settings. Scrapling additionally swallows ``page_setup``
exceptions before navigating, so a failed interception callback cannot be
trusted to stop the engine.

Every browser engine PawnLogic launches is therefore pointed at this loopback
proxy. Each CONNECT tunnel and each plain-HTTP request is evaluated against
the shared NetworkPolicy before any byte is forwarded; denied targets receive
HTTP 403 before a connection is made. Plain HTTP uses one request per socket;
Chromium disables HTTP/2 and QUIC to prevent cross-authority TLS pooling.
The proxy dials only the addresses
the policy resolved, so connect-time DNS cannot rebind the socket elsewhere.
"""

from __future__ import annotations

import importlib.metadata
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
    evaluate_pinned_browser_authorization,
    install_browser_route_guard,
)
from tools.proxy_protocol import (
    close_socket, connect_url, dial_pinned, forward_http, read_request, splice as _splice,
)
from utils.ansi import c, YELLOW

_LISTEN_HOST = "127.0.0.1"
_IO_TIMEOUT = 10.0
_MAX_CONNECTIONS = 16
_DENY_RESPONSE = (
    b"HTTP/1.1 403 Forbidden\r\n"
    b"Content-Length: 0\r\n"
    b"Connection: close\r\n"
    b"\r\n"
)
_TUNNEL_ACCEPTED = b"HTTP/1.1 200 Connection established\r\n\r\n"

# Scrapling 0.4.15 is the minimum version validated for the page_setup,
# proxy, extra_flags, and additional_args enforcement contract.
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
    parts.extend([0] * (3 - len(parts)))
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
        self._authorized: dict[tuple[str, int], tuple[str, ...]] = {}
        self._scope: object | None = None
        self._connections: dict[Any, object | None] = {}
        self._capacity = threading.BoundedSemaphore(_MAX_CONNECTIONS)
        self._stopped = False

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> str:
        """Bind the loopback listener on an ephemeral port; return its URL."""
        with self._lock:
            if self._listener is not None:
                return self.url
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                listener.bind((_LISTEN_HOST, 0))
                listener.listen(_MAX_CONNECTIONS)
                listener.settimeout(0.2)
            except OSError:
                listener.close()
                raise
            self._listener = listener
            self._stopped = False
            self._thread = threading.Thread(
                target=self._serve, name="pawnlogic-policy-proxy", daemon=True
            )
            self._thread.start()
            return self.url

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            listener, self._listener = self._listener, None
            self._scope, self._arguments = None, None
            sockets = tuple(self._connections)
            self._authorized.clear()
        for sock in (listener, *sockets):
            if sock is not None:
                close_socket(sock)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1)

    @property
    def url(self) -> str:
        listener = self._listener
        if listener is None:
            raise RuntimeError("policy proxy is not started")
        return f"http://{_LISTEN_HOST}:{listener.getsockname()[1]}"

    def _serve(self) -> None:
        while (listener := self._listener) is not None:
            try:
                conn, _addr = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            if not self._capacity.acquire(blocking=False):
                close_socket(conn)
                continue
            scope = self.authorization_scope
            worker = threading.Thread(
                target=self.handle_connection, args=(conn,),
                kwargs={"reserved": True, "scope": scope}, daemon=True,
            )
            try:
                self._track_connection(conn, scope)
                worker.start()
            except Exception:
                self._capacity.release()
                with self._lock:
                    self._connections.pop(conn, None)
                close_socket(conn)

    # ── per-operation authorization scope ─────────────────────────────────

    @contextmanager
    def scoped(self, arguments: dict | None) -> Iterator[None]:
        """One exclusive operation; revoke its grants and sockets on exit."""
        token = object()
        with self._lock:
            if self._scope is not None or self._stopped:
                raise RuntimeError("SECURITY BLOCK: proxy scope is busy or stopped")
            self._scope, self._arguments = token, dict(arguments or {})
            self._authorized.clear()
        try:
            yield
        finally:
            with self._lock:
                sockets = tuple(s for s, scope in self._connections.items() if scope is token)
                if self._scope is token:
                    self._scope, self._arguments = None, None
                    self._authorized.clear()
            for sock in sockets:
                close_socket(sock)

    @property
    def authorization_scope(self) -> object | None:
        with self._lock:
            return None if self._stopped else self._scope

    def authorize(
        self, url: str, decision: NetworkDecision, pins: tuple[str, ...],
        *, scope: object | None = None,
    ) -> None:
        """Register exact pins only after the host confirmed this decision."""
        if (decision.action, decision.rule) != (NetworkAction.CONFIRM, "private_network") or not pins:
            raise ValueError("only a confirmed, resolved private target may be authorized")
        checked = evaluate_pinned_browser_authorization(url, pins)
        if (checked.action, checked.rule) != (NetworkAction.ALLOW, "private_network_authorized") or _authority_key(url) != _authority_key(decision.normalized_target):
            raise ValueError("authorization cannot override an unconditional denial")
        with self._lock:
            if scope is None or scope is not self._scope or self._stopped:
                raise RuntimeError("SECURITY BLOCK: authorization requires the active scope")
            self._authorized[_authority_key(url)] = pins

    # ── connection handling (public so offline tests can drive fakes) ────

    def handle_connection(
        self, sock: Any, *, reserved: bool = False, scope: object | None = None,
    ) -> None:
        if not reserved and not self._capacity.acquire(blocking=False):
            close_socket(sock)
            return
        scope = scope if reserved else self.authorization_scope
        try:
            self._track_connection(sock, scope)
            self._handle(sock, scope)
        except Exception:
            pass  # Fail closed before forwarding on any invalid input.
        finally:
            with self._lock:
                self._connections.pop(sock, None)
            close_socket(sock)
            self._capacity.release()

    def _handle(self, sock: Any, scope: object | None) -> None:
        sock.settimeout(_IO_TIMEOUT)
        request = read_request(sock)
        url = connect_url(request)
        decision, pins = self._evaluate(url, scope)
        if decision.action != NetworkAction.ALLOW:
            sock.sendall(_DENY_RESPONSE)
            return
        upstream = dial_pinned(pins, _authority_key(url)[1])
        try:
            self._track_connection(upstream, scope)
            if request.method == "CONNECT":
                sock.sendall(_TUNNEL_ACCEPTED)
                if request.pending:
                    upstream.sendall(request.pending)
                _splice(sock, upstream)
            else:
                forward_http(sock, upstream, request)
        finally:
            with self._lock:
                self._connections.pop(upstream, None)
            close_socket(upstream)

    def _evaluate(
        self, url: str, scope: object | None,
    ) -> tuple[NetworkDecision, tuple[str, ...]]:
        with self._lock:
            if self._stopped or scope is not self._scope:
                raise RuntimeError("proxy operation was revoked")
            pins = self._authorized.get(_authority_key(url), ()) if scope is not None else ()
            arguments = self._arguments
        if pins:
            decision = evaluate_pinned_browser_authorization(url, pins)
            return decision, pins
        return evaluate_network_url_pinned(
            url, arguments=arguments, confirmation_available=False,
        )

    def _track_connection(self, upstream: Any, scope: object | None) -> None:
        with self._lock:
            if self._stopped or scope is not self._scope:
                close_socket(upstream)
                raise RuntimeError("proxy operation was revoked during connection")
            self._connections[upstream] = scope


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
        "--disable-http2",
        "--disable-quic",
        "--proxy-bypass-list=<-loopback>",
        # WebRTC can open non-proxied UDP sockets that bypass the enforcement
        # proxy; this restricts WebRTC's non-proxied UDP paths.
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
    (``proxy``), non-proxied WebRTC UDP is restricted, and Service Worker
    blocking is requested. The proxy independently enforces Worker egress.
    Each attempt registers the
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
        "extra_flags": browser_launch_arguments(),
        "additional_args": {"service_workers": "block"},
    }
    delays = [2, 5, 10]
    last_exc: Exception | None = None
    with proxy.scoped(arguments):
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
