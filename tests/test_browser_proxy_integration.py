"""Offline Chromium checks for the loopback browser enforcement proxy.

These tests deliberately install only page/context-level counting routes.  The
routes are observation points, not enforcement layers: Chromium can follow a
redirect or let a service worker issue a request without surfacing the next
request to a route.  The proxy is therefore the boundary whose denial and
zero upstream request count are asserted here.
"""

from __future__ import annotations

import os
import shutil
import socket
import ssl
import subprocess
import threading
from contextlib import suppress
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from tools import policy_proxy
from tools.policy_proxy import PolicyProxy, browser_launch_arguments


pytestmark = pytest.mark.slow

_ALLOWED_HOST = "allowed.example.test"
_PUBLIC_PIN = "93.184.216.34"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_RUNTIME = _REPO_ROOT / ".agent-work" / "tmp" / "browser-runtime"

_patchright = pytest.importorskip("patchright.sync_api")


@dataclass
class _OriginState:
    scheme: str
    port: int = 0
    redirect_target: str = ""
    request_paths: list[str] = field(default_factory=list)
    selected_alpn: list[str | None] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def record_request(self, path: str) -> None:
        with self.lock:
            self.request_paths.append(path)

    def record_alpn(self, protocol: str | None) -> None:
        with self.lock:
            self.selected_alpn.append(protocol)


class _OriginHandler(BaseHTTPRequestHandler):
    server: _OriginServer
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        super().setup()
        selected = getattr(self.connection, "selected_alpn_protocol", None)
        if callable(selected):
            self.server.state.record_alpn(selected())

    def do_GET(self) -> None:
        state = self.server.state
        path = urlsplit(self.path).path or "/"
        state.record_request(path)

        if path == "/redirect":
            body = b""
            self.send_response(302)
            self.send_header("Location", state.redirect_target)
        elif path == "/sw-test":
            body = (
                b"<!doctype html><title>service worker test</title>"
                b"<p>service worker test</p>"
            )
            self.send_response(200)
        elif path == "/sw.js":
            loopback_target = f"https://127.0.0.1:{state.port}/denied"
            body = (
                b"self.addEventListener('install', event => "
                b"event.waitUntil(self.skipWaiting()));"
                b"self.addEventListener('activate', event => "
                b"event.waitUntil(self.clients.claim()));"
                + (
                    "self.addEventListener('message', event => {"
                    "if (event.data !== 'probe' || !event.ports.length) return;"
                    f"fetch({loopback_target!r}, {{cache: 'no-store', mode: 'no-cors'}}).then("
                    "response => event.ports[0].postMessage({"
                    "kind: 'fetch', status: response.status}),"
                    "error => event.ports[0].postMessage({"
                    "kind: 'fetch', status: 0, name: error.name}));"
                    "});"
                ).encode()
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
        else:
            body = b"ok"
            self.send_response(200)

        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _OriginServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, state: _OriginState, tls_context: ssl.SSLContext | None = None):
        super().__init__(("127.0.0.1", 0), _OriginHandler)
        self.state = state
        if tls_context is not None:
            self.socket = tls_context.wrap_socket(self.socket, server_side=True)
        state.port = self.server_address[1]
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
        self._thread.join(timeout=2)


def _start_origin(
    scheme: str,
    *,
    tls_context: ssl.SSLContext | None = None,
) -> _OriginServer:
    state = _OriginState(scheme=scheme)
    server = _OriginServer(state, tls_context=tls_context)
    state.redirect_target = f"{scheme}://127.0.0.1:{state.port}/denied"
    server.start()
    return server


def _make_self_signed_cert(tmp_path: Path) -> tuple[Path, Path]:
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl is required for the offline TLS integration test")
    key_path = tmp_path / "server.key"
    cert_path = tmp_path / "server.crt"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-subj",
            f"/CN={_ALLOWED_HOST}",
            "-addext",
            f"subjectAltName=DNS:{_ALLOWED_HOST}",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=20,
    )
    return cert_path, key_path


def _patch_allowed_dns_and_dial(
    monkeypatch: pytest.MonkeyPatch,
    origin_port: int,
) -> tuple[list[str], list[tuple[str, int]]]:
    """Keep policy resolution and upstream dialing entirely offline.

    The fake resolver presents the allowed host as a public address.  Only the
    test's dial adapter maps that already-pinned address to the local origin;
    policy hard-denials for literal loopback targets remain production code.
    """

    resolutions: list[str] = []
    dialed: list[tuple[str, int]] = []

    def fake_getaddrinfo(host: str, *_args: object, **_kwargs: object):
        normalized = host.rstrip(".").lower()
        resolutions.append(normalized)
        if normalized != _ALLOWED_HOST:
            raise socket.gaierror(f"offline test refused DNS for {host!r}")
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (_PUBLIC_PIN, 0),
            )
        ]

    def fake_create_connection(address: tuple[str, int], *args: object, **kwargs: object):
        host, port = address
        if host != _PUBLIC_PIN or port != origin_port:
            raise AssertionError(
                f"offline integration attempted an unpinned dial: {host}:{port}"
            )
        dialed.append((host, port))
        # Do not call socket.create_connection here: the test replaces
        # getaddrinfo above, so even a numeric loopback address would be
        # routed back through the fake resolver.  Numeric socket.connect is
        # the test-only adapter from the policy pin to the local origin.
        upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        timeout = kwargs.get("timeout", args[0] if args else None)
        if isinstance(timeout, (int, float)):
            upstream.settimeout(timeout)
        try:
            upstream.connect(("127.0.0.1", origin_port))
        except Exception:
            upstream.close()
            raise
        return upstream

    monkeypatch.setattr(policy_proxy.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        policy_proxy.socket, "create_connection", fake_create_connection
    )
    return resolutions, dialed


def _evaluate_main_world(page: Any, expression: str) -> Any:
    """Evaluate an awaitable in Chromium's default (main-world) context.

    Patchright's ``Page.evaluate`` helper uses an isolated world for this
    integration.  CDP ``Runtime.evaluate`` on a page session uses the page's
    main world, which is required for an honest ServiceWorker API check.
    """

    cdp = page.context.new_cdp_session(page)
    try:
        result = cdp.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
                "userGesture": True,
            },
        )
    finally:
        cdp.detach()
    if result.get("exceptionDetails"):
        raise AssertionError(
            f"main-world Runtime.evaluate failed: {result['exceptionDetails']}"
        )
    value = result.get("result", {})
    if value.get("type") == "undefined":
        return None
    if "value" not in value:
        raise AssertionError(f"main-world value was not serializable: {value}")
    return value["value"]


def _record_policy_denials(
    proxy: PolicyProxy,
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, Any]]:
    """Record the policy decision immediately before the proxy sends 403."""

    denials: list[tuple[str, Any]] = []
    original_evaluate = proxy._evaluate

    def record_evaluate(url: str, scope: object | None):
        decision, pins = original_evaluate(url, scope)
        if decision.action == policy_proxy.NetworkAction.DENY:
            # Both proxy handlers send _DENY_RESPONSE immediately after this
            # decision.  Recording here avoids a second DNS evaluation while
            # proving that the browser-visible refusal was policy-generated.
            denials.append((url, decision))
        return decision, pins

    monkeypatch.setattr(proxy, "_evaluate", record_evaluate)
    return denials


@dataclass
class _BrowserHarness:
    proxy: PolicyProxy
    browser: Any
    context: Any
    page: Any


@pytest.fixture(scope="module")
def browser_harness() -> Any:
    """Launch one explicitly installed Chromium and one page for this module."""

    runtime = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", str(_DEFAULT_RUNTIME)))
    if not runtime.is_dir():
        pytest.skip(f"Chromium runtime is not installed at {runtime}")

    previous_runtime = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(runtime)
    proxy = PolicyProxy()
    proxy.start()
    real_evaluate = proxy._evaluate

    def offline_evaluate(url, scope):
        if scope is None or urlsplit(url).hostname not in {_ALLOWED_HOST, "127.0.0.1"}:
            return policy_proxy.NetworkDecision(
                policy_proxy.NetworkAction.DENY, "offline fixture denied background egress",
                "dns_result_invalid", url,
            ), ()
        return real_evaluate(url, scope)

    proxy._evaluate = offline_evaluate
    browser = context = page = None
    harness: _BrowserHarness | None = None
    try:
        with _patchright.sync_playwright() as playwright:
            try:
                executable = Path(playwright.chromium.executable_path)
            except Exception as exc:
                pytest.skip(f"Patchright Chromium executable is unavailable: {exc}")
            if not executable.is_file():
                pytest.skip(f"Patchright Chromium executable is missing: {executable}")
            try:
                browser = playwright.chromium.launch(
                    executable_path=str(executable),
                    headless=True,
                    args=[
                        *browser_launch_arguments(),
                        "--disable-background-networking",
                        "--disable-component-update",
                        "--disable-default-apps",
                        "--disable-sync",
                        # Test-only: expose Browser.getBrowserCommandLine so
                        # the WebRTC launch flag is checked at runtime. This
                        # does not alter production browser launch flags.
                        "--enable-automation",
                        # Test-only: the origin deliberately uses a
                        # self-signed certificate. Production keeps normal
                        # certificate validation and only opts into this in
                        # the offline integration process.
                        "--ignore-certificate-errors",
                        "--no-first-run",
                    ],
                    proxy={"server": proxy.url, "bypass": "<-loopback>"},
                )
            except Exception as exc:
                pytest.skip(f"Chromium could not launch: {type(exc).__name__}: {exc}")
            context = browser.new_context(
                service_workers="block",
                ignore_https_errors=True,
            )
            page = context.new_page()
            harness = _BrowserHarness(proxy, browser, context, page)
            yield harness
    finally:
        resources = (
            (harness.page, harness.context, browser)
            if harness is not None
            else (page, context, browser)
        )
        for resource in resources:
            close = getattr(resource, "close", None)
            if callable(close):
                with suppress(Exception):
                    close()
        proxy.stop()
        if previous_runtime is None:
            os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
        else:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = previous_runtime


@pytest.fixture()
def http_origin() -> Any:
    server = _start_origin("http")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def https_origin(tmp_path: Path) -> Any:
    cert_path, key_path = _make_self_signed_cert(tmp_path)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert_path, keyfile=key_path)
    context.set_alpn_protocols(["h2", "http/1.1"])
    server = _start_origin("https", tls_context=context)
    try:
        yield server
    finally:
        server.stop()


def _target(origin: _OriginServer, path: str) -> str:
    return f"{origin.state.scheme}://{_ALLOWED_HOST}:{origin.state.port}{path}"


def test_http_redirect_bypasses_page_route_but_proxy_denies_loopback(
    browser_harness: _BrowserHarness,
    http_origin: _OriginServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolutions, dialed = _patch_allowed_dns_and_dial(
        monkeypatch, http_origin.state.port
    )
    denials = _record_policy_denials(browser_harness.proxy, monkeypatch)
    routed: list[str] = []

    def count_route(route: Any) -> None:
        routed.append(route.request.url)
        route.continue_()

    page = browser_harness.page
    page.route("**/*", count_route)
    try:
        with browser_harness.proxy.scoped(None):
            try:
                response = page.goto(
                    _target(http_origin, "/redirect"),
                    wait_until="domcontentloaded",
                    timeout=5000,
                )
            except Exception as exc:
                response = None
                assert "ERR_HTTP_RESPONSE_CODE_FAILURE" in str(exc)
    finally:
        page.unroute("**/*", count_route)

    if response is not None:
        assert response.status == 403
    assert routed == [_target(http_origin, "/redirect")]
    assert http_origin.state.request_paths == ["/redirect"]
    assert _ALLOWED_HOST in resolutions
    assert (_PUBLIC_PIN, http_origin.state.port) in dialed
    assert all(host == _PUBLIC_PIN for host, _port in dialed)
    target_denials = [(url, decision) for url, decision in denials if url == http_origin.state.redirect_target]
    assert target_denials
    denied_url, decision = target_denials[0]
    assert denied_url.startswith("http://127.0.0.1:")
    assert decision.rule == "loopback"
    assert decision.action == policy_proxy.NetworkAction.DENY


def test_https_uses_http11_when_server_advertises_h2(
    browser_harness: _BrowserHarness,
    https_origin: _OriginServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_allowed_dns_and_dial(monkeypatch, https_origin.state.port)

    with browser_harness.proxy.scoped(None):
        response = browser_harness.page.goto(
            _target(https_origin, "/ok"),
            wait_until="domcontentloaded",
            timeout=5000,
        )

    assert response is not None
    assert response.status == 200
    assert https_origin.state.request_paths == ["/ok"]
    assert https_origin.state.selected_alpn
    assert set(https_origin.state.selected_alpn) == {"http/1.1"}


def test_https_redirect_to_loopback_is_denied_before_target_connection(
    browser_harness: _BrowserHarness,
    https_origin: _OriginServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_allowed_dns_and_dial(monkeypatch, https_origin.state.port)
    denials = _record_policy_denials(browser_harness.proxy, monkeypatch)

    with browser_harness.proxy.scoped(None):
        try:
            response = browser_harness.page.goto(
                _target(https_origin, "/redirect"),
                wait_until="domcontentloaded",
                timeout=5000,
            )
        except Exception as exc:
            # Chromium may surface a 403 CONNECT response as a tunnel error
            # instead of exposing it as a page Response.  Assert that the
            # navigation failed at the proxy boundary; do not swallow it.
            message = str(exc)
            assert "ERR_" in message or "proxy" in message.lower()
        else:
            assert response is not None
            assert response.status == 403
    assert https_origin.state.request_paths == ["/redirect"]
    assert "/denied" not in https_origin.state.request_paths
    target_denials = [(url, decision) for url, decision in denials if url.startswith(f"https://127.0.0.1:{https_origin.state.port}/")]
    assert target_denials
    denied_url, decision = target_denials[0]
    assert denied_url.startswith("https://127.0.0.1:")
    assert decision.rule == "loopback"
    assert decision.action == policy_proxy.NetworkAction.DENY


def test_service_worker_egress_stays_inside_proxy_when_registration_is_allowed(
    browser_harness: _BrowserHarness,
    https_origin: _OriginServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_allowed_dns_and_dial(monkeypatch, https_origin.state.port)
    denials = _record_policy_denials(browser_harness.proxy, monkeypatch)

    # The fixture's initial context is created with service_workers="block" to
    # retain the launch contract.  Patchright implements that option as an
    # init-script shim, so the security assertion here deliberately uses an
    # explicit allow context and proves the proxy remains the hard boundary.
    browser_harness.page.close()
    browser_harness.context.close()

    allow_context = browser_harness.browser.new_context(
        service_workers="allow",
        ignore_https_errors=True,
    )
    allow_page = allow_context.new_page()
    routed: list[str] = []

    def count_context_route(route: Any) -> None:
        routed.append(route.request.url)
        route.continue_()

    allow_context.route("**/*", count_context_route)
    allow_script_hits_before = https_origin.state.request_paths.count("/sw.js")
    try:
        with browser_harness.proxy.scoped(None):
            allow_page.goto(
                _target(https_origin, "/sw-test"),
                wait_until="domcontentloaded",
                timeout=5000,
            )
            capabilities = _evaluate_main_world(
                allow_page,
                "({secure: window.isSecureContext, "
                "serviceWorker: !!navigator.serviceWorker})",
            )
            assert capabilities == {"secure": True, "serviceWorker": True}
            allow_result = _evaluate_main_world(
                allow_page,
                """(async () => {
                    const registration = await navigator.serviceWorker.register("/sw.js");
                    const active = await new Promise((resolve, reject) => {
                        const timer = setTimeout(
                            () => reject(new Error("service worker did not activate")),
                            5000,
                        );
                        const check = () => {
                            if (registration.active) {
                                clearTimeout(timer);
                                resolve(registration.active);
                            } else if (registration.installing) {
                                registration.installing.addEventListener("statechange", check);
                            }
                        };
                        registration.addEventListener("updatefound", check);
                        check();
                    });
                    const probe = await new Promise(resolve => {
                        const channel = new MessageChannel();
                        const timer = setTimeout(
                            () => resolve({kind: "timeout"}),
                            5000,
                        );
                        channel.port1.onmessage = event => {
                            clearTimeout(timer);
                            resolve(event.data);
                        };
                        active.postMessage("probe", [channel.port2]);
                    });
                    return {
                        registered: !!registration,
                        active: !!active,
                        state: active.state,
                        probe,
                    };
                })()"""
            )
            assert allow_result["registered"] is True
            assert allow_result["active"] is True
            assert allow_result["probe"]["kind"] == "fetch"
        allow_script_hits_after = https_origin.state.request_paths.count("/sw.js")
        assert allow_script_hits_after > allow_script_hits_before
    finally:
        with suppress(Exception):
            allow_context.unroute("**/*", count_context_route)
        allow_page.close()
        allow_context.close()

    blocked_context = browser_harness.browser.new_context(
        service_workers="block",
        ignore_https_errors=True,
    )
    blocked_page = blocked_context.new_page()
    browser_harness.context = blocked_context
    browser_harness.page = blocked_page
    with browser_harness.proxy.scoped(None):
        blocked_page.goto(
            _target(https_origin, "/sw-test"),
            wait_until="domcontentloaded",
            timeout=5000,
        )
        block_result = _evaluate_main_world(
            blocked_page,
            """(async () => {
                try {
                    const registration = await navigator.serviceWorker.register("/sw.js");
                    const native = await ServiceWorkerContainer.prototype.register.call(
                        navigator.serviceWorker, "/sw.js"
                    );
                    return {registered: !!registration, nativeRegistered: !!native};
                } catch (error) {
                    return {registered: false, error: error.name};
                }
            })()""",
        )
    print(
        f"[browser-proxy] service_workers=block main-world registration: {block_result}",
        flush=True,
    )

    assert "/denied" not in https_origin.state.request_paths
    loopback_denials = [
        (url, decision)
        for url, decision in denials
        if url.startswith("https://127.0.0.1:")
    ]
    assert loopback_denials
    assert all(decision.rule == "loopback" for _url, decision in loopback_denials)
    assert all(
        decision.action == policy_proxy.NetworkAction.DENY
        for _url, decision in loopback_denials
    )


def test_browser_launch_arguments_force_non_proxied_webrtc_policy(
    browser_harness: _BrowserHarness,
) -> None:
    arguments = browser_launch_arguments()
    assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in arguments
    cdp = browser_harness.browser.new_browser_cdp_session()
    try:
        command_line = cdp.send("Browser.getBrowserCommandLine")["arguments"]
    finally:
        cdp.detach()
    assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in command_line
