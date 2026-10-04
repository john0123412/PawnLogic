"""Deterministic browser tool failure-path tests."""

from __future__ import annotations

from contextlib import suppress
import importlib.metadata

from tools import browser_ops, policy_proxy


class _RoutingContext:
    def route(self, _pattern, _handler):
        return None

    def unroute(self, *_args):
        return None


class _TimeoutPage:
    url = "about:blank"
    context = _RoutingContext()

    def goto(self, *_args, **_kwargs):
        raise TimeoutError("navigation timed out\nTraceback (most recent call last): hidden")


class _SelectorMissingPage:
    def query_selector_all(self, _selector):
        return []


class _ReadinessFailurePage:
    url = "about:blank"

    def click(self, *_args, **_kwargs):
        return None

    def wait_for_load_state(self, *_args, **_kwargs):
        raise RuntimeError("readiness failed\nTraceback (most recent call last): hidden")


def test_web_navigate_timeout_returns_user_facing_error(monkeypatch):
    monkeypatch.setattr(browser_ops, "_get_page", lambda: _TimeoutPage())
    monkeypatch.setattr(
        browser_ops,
        "_validate_browser_url",
        lambda _url, _arguments=None: (None, []),
    )

    result = browser_ops.tool_web_navigate({"url": "https://example.test", "timeout": 1})

    assert result.startswith("ERROR: navigation failed")
    assert "TimeoutError" in result
    assert "Traceback" not in result


def test_web_select_missing_selector_is_deterministic(monkeypatch):
    monkeypatch.setattr(browser_ops, "_get_page", lambda: _SelectorMissingPage())

    result = browser_ops.tool_web_select({"selector": "#missing"})

    assert result == "No matching elements found: #missing"


def test_web_click_readiness_failure_has_no_traceback(monkeypatch):
    monkeypatch.setattr(browser_ops, "_get_page", lambda: _ReadinessFailurePage())

    result = browser_ops.tool_web_click({"selector": "#submit"})

    assert result.startswith("ERROR: click failed (#submit)")
    assert "RuntimeError" in result
    assert "Traceback" not in result


def test_browser_dependency_missing_returns_existing_guidance(monkeypatch):
    monkeypatch.setattr(browser_ops, "_get_page", lambda: None)
    monkeypatch.setattr(
        browser_ops,
        "_browser_error",
        "Browser dependencies are not installed. Fix: pip install 'pawnlogic[browser]'",
    )

    result = browser_ops.tool_web_click({"selector": "#submit"})

    assert result.startswith("ERROR: browser unavailable - Browser dependencies are not installed")
    assert "Traceback" not in result


def test_web_fetch_failure_has_no_traceback(monkeypatch):
    class FailingFetcher:
        def fetch(self, *_args, **_kwargs):
            raise RuntimeError("fetch failed\nTraceback (most recent call last): hidden")

    monkeypatch.setattr(browser_ops, "_get_stealthy_fetcher", lambda: FailingFetcher())
    monkeypatch.setattr(
        browser_ops,
        "_validate_browser_url",
        lambda _url, _arguments=None: (None, []),
    )

    result = browser_ops.tool_web_fetch({"url": "https://example.test", "timeout": 1})

    assert result.startswith("ERROR: Scrapling fetch failed")
    assert "RuntimeError" in result
    assert "Traceback" not in result


def test_web_fetch_registers_policy_guard_via_page_setup(monkeypatch):
    captured_kwargs: dict = {}
    registered_handlers: list = []

    class GuardedRoute:
        def __init__(self) -> None:
            self.aborted = False
            self.continued = False

        def abort(self):
            self.aborted = True

        def continue_(self):
            self.continued = True

    class GuardedRequest:
        def __init__(self, url: str) -> None:
            self.url = url

    class FakeContext:
        def route(self, _pattern, handler):
            registered_handlers.append(handler)

        def unroute(self, *_args):
            return None

    class FakePage:
        context = FakeContext()

    class FakeResponse:
        status = 200
        text = "synthetic page body"
        body = None
        url = "https://example.test/"

        def get_all_text(self):
            return "synthetic page body"

    def fake_fetch(url, **kwargs):
        captured_kwargs.update(kwargs)
        kwargs["page_setup"](FakePage())
        assert len(registered_handlers) == 1
        denied = GuardedRoute()
        registered_handlers[0](denied, GuardedRequest("http://127.0.0.1:9000/x"))
        assert denied.aborted is True
        allowed = GuardedRoute()
        registered_handlers[0](allowed, GuardedRequest("https://example.test/app.js"))
        assert allowed.continued is True
        return FakeResponse()

    import socket as _socket

    def fake_getaddrinfo(host, *_args, **_kwargs):
        return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(_socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(browser_ops, "_get_stealthy_fetcher", lambda: type("F", (), {"fetch": staticmethod(fake_fetch)})())
    monkeypatch.setattr(
        browser_ops,
        "_validate_browser_url",
        lambda _url, _arguments=None: (None, []),
    )

    result = browser_ops.tool_web_fetch({"url": "https://example.test/"})

    assert captured_kwargs.get("page_setup") is not None
    assert "synthetic page body" in result


def test_web_fetch_uses_context_route_and_blocks_service_workers(monkeypatch):
    captured_kwargs: dict = {}
    context_routes: list = []
    page_route_calls: list = []

    class FakeContext:
        def route(self, pattern, handler):
            context_routes.append((pattern, handler))

        def unroute(self, *_args):
            return None

    class FakePage:
        context = FakeContext()

        def route(self, *_args):
            page_route_calls.append(True)
            raise AssertionError("fetch policy must be installed on the context")

    class FakeResponse:
        status = 200
        text = "synthetic page body"
        body = None
        url = "https://example.test/"

        def get_all_text(self):
            return "synthetic page body"

    def fake_fetch(url, **kwargs):
        captured_kwargs.update(kwargs)
        kwargs["page_setup"](FakePage())
        return FakeResponse()

    monkeypatch.setattr(
        browser_ops,
        "_get_stealthy_fetcher",
        lambda: type("F", (), {"fetch": staticmethod(fake_fetch)})(),
    )
    monkeypatch.setattr(
        browser_ops,
        "_validate_browser_url",
        lambda _url, _arguments=None: (None, []),
    )
    monkeypatch.setattr(
        browser_ops,
        "response_url_with_policy",
        lambda *_args, **_kwargs: (None, "https://example.test/"),
    )

    result = browser_ops.tool_web_fetch({"url": "https://example.test/"})

    assert "synthetic page body" in result
    assert captured_kwargs["additional_args"] == {"service_workers": "block"}
    assert [pattern for pattern, _handler in context_routes] == ["**/*"]
    assert page_route_calls == []


def test_web_fetch_closes_context_when_context_route_install_is_swallowed(monkeypatch):
    class FakeContext:
        def __init__(self) -> None:
            self.closed = False

        def route(self, *_args):
            raise RuntimeError("context route unavailable")

        def unroute(self, *_args):
            return None

        def close(self):
            self.closed = True

    context = FakeContext()
    page_route_calls: list = []

    class FakePage:
        def __init__(self) -> None:
            self.context = context

        def route(self, *_args):
            page_route_calls.append(True)

    class FakeResponse:
        status = 200
        text = "must not escape"
        body = None
        url = "https://example.test/"

        def get_all_text(self):
            return "must not escape"

    def fake_fetch(url, **kwargs):
        # Scrapling 0.4.15 logs and swallows page_setup exceptions, then
        # continues toward goto. A closed context must make that continuation
        # fail before a response can be returned.
        with suppress(Exception):
            kwargs["page_setup"](FakePage())
        if context.closed:
            raise RuntimeError("page context is closed")
        return FakeResponse()

    monkeypatch.setattr(
        browser_ops,
        "_get_stealthy_fetcher",
        lambda: type("F", (), {"fetch": staticmethod(fake_fetch)})(),
    )
    monkeypatch.setattr(
        browser_ops,
        "_validate_browser_url",
        lambda _url, _arguments=None: (None, []),
    )
    monkeypatch.setattr(
        browser_ops,
        "response_url_with_policy",
        lambda *_args, **_kwargs: (None, "https://example.test/"),
    )

    result = browser_ops.tool_web_fetch({"url": "https://example.test/"})

    assert "must not escape" not in result
    assert context.closed is True
    assert page_route_calls == []


def test_web_fetch_rejects_silent_page_setup_ignoring_fetcher(monkeypatch):
    calls = 0

    class FakeResponse:
        status = 200
        text = "must not escape"
        body = None
        url = "https://example.test/"

        def get_all_text(self):
            return "must not escape"

    def fake_fetch(url, **_kwargs):
        nonlocal calls
        calls += 1
        return FakeResponse()

    monkeypatch.setattr(
        browser_ops,
        "_get_stealthy_fetcher",
        lambda: type("F", (), {"fetch": staticmethod(fake_fetch)})(),
    )
    monkeypatch.setattr(
        browser_ops,
        "_validate_browser_url",
        lambda _url, _arguments=None: (None, []),
    )
    monkeypatch.setattr(
        browser_ops,
        "response_url_with_policy",
        lambda *_args, **_kwargs: (None, "https://example.test/"),
    )

    result = browser_ops.tool_web_fetch({"url": "https://example.test/"})

    assert result.startswith("SECURITY BLOCK")
    assert "must not escape" not in result
    assert calls <= 1


def test_web_fetch_rechecks_page_setup_after_each_retry(monkeypatch):
    calls = 0
    setup_calls = 0

    class FakeContext:
        def route(self, *_args):
            return None

        def unroute(self, *_args):
            return None

    class FakePage:
        context = FakeContext()

        def route(self, *_args):
            raise AssertionError("fetch policy must be installed on the context")

    class FakeResponse:
        status = 200
        text = "must not escape"
        body = None
        url = "https://example.test/"

        def get_all_text(self):
            return "must not escape"

    def fake_fetch(url, **kwargs):
        nonlocal calls, setup_calls
        calls += 1
        if calls == 1:
            setup_calls += 1
            kwargs["page_setup"](FakePage())
            raise TimeoutError("synthetic first attempt timeout")
        # Simulate a retry transport that silently ignores page_setup.
        return FakeResponse()

    monkeypatch.setattr(policy_proxy.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(
        browser_ops,
        "_get_stealthy_fetcher",
        lambda: type("F", (), {"fetch": staticmethod(fake_fetch)})(),
    )
    monkeypatch.setattr(
        browser_ops,
        "_validate_browser_url",
        lambda _url, _arguments=None: (None, []),
    )
    monkeypatch.setattr(
        browser_ops,
        "response_url_with_policy",
        lambda *_args, **_kwargs: (None, "https://example.test/"),
    )

    result = browser_ops.tool_web_fetch({"url": "https://example.test/"})

    assert result.startswith("SECURITY BLOCK")
    assert "must not escape" not in result
    assert calls == 2
    assert setup_calls == 1


def test_web_fetch_rejects_scrapling_before_fetch_when_version_is_unsupported(monkeypatch):
    calls = 0

    class FakeResponse:
        status = 200
        text = "must not escape"
        body = None
        url = "https://example.test/"

        def get_all_text(self):
            return "must not escape"

    def fake_fetch(url, **_kwargs):
        nonlocal calls
        calls += 1
        return FakeResponse()

    real_version = importlib.metadata.version

    def fake_version(package):
        if package == "scrapling":
            return "0.4.14"
        return real_version(package)

    monkeypatch.setattr(importlib.metadata, "version", fake_version)
    monkeypatch.setattr(
        browser_ops,
        "_get_stealthy_fetcher",
        lambda: type("F", (), {"fetch": staticmethod(fake_fetch)})(),
    )
    monkeypatch.setattr(
        browser_ops,
        "_validate_browser_url",
        lambda _url, _arguments=None: (None, []),
    )

    result = browser_ops.tool_web_fetch({"url": "https://example.test/"})

    assert result.startswith("SECURITY BLOCK")
    assert "must not escape" not in result
    assert calls == 0


def test_web_fetch_fails_closed_when_page_setup_unsupported(monkeypatch):
    class OldFetcher:
        def fetch(self, _url, **_kwargs):
            raise TypeError("fetch() got an unexpected keyword argument 'page_setup'")

    monkeypatch.setattr(browser_ops, "_get_stealthy_fetcher", lambda: OldFetcher())
    monkeypatch.setattr(
        browser_ops,
        "_validate_browser_url",
        lambda _url, _arguments=None: (None, []),
    )

    result = browser_ops.tool_web_fetch({"url": "https://example.test/"})

    assert result.startswith("SECURITY BLOCK")
    assert "cannot enforce" in result
    assert "Traceback" not in result


def test_browser_bootstrap_installs_context_lifetime_guard(monkeypatch):
    import sys
    import types
    from types import SimpleNamespace

    registered: list = []

    class FakeContext:
        def route(self, _pattern, handler):
            registered.append(handler)

        def unroute(self, *_args):
            return None

        def new_page(self):
            return SimpleNamespace(is_closed=lambda: False)

    fake_context = FakeContext()

    context_kwargs: dict = {}
    launch_kwargs: dict = {}

    class FakeBrowser:
        def new_context(self, **kwargs):
            context_kwargs.update(kwargs)
            return fake_context

    class FakeBrowserType:
        def launch(self, **kwargs):
            launch_kwargs.update(kwargs)
            return FakeBrowser()

    class FakePlaywright:
        def start(self):
            return self

        chromium = property(lambda self: FakeBrowserType())

    fake_pkg = types.ModuleType("patchright")
    fake_pkg.__path__ = []
    fake_mod = types.ModuleType("patchright.sync_api")
    fake_mod.sync_playwright = lambda: FakePlaywright()
    fake_pkg.sync_api = fake_mod
    monkeypatch.setitem(sys.modules, "patchright", fake_pkg)
    monkeypatch.setitem(sys.modules, "patchright.sync_api", fake_mod)
    monkeypatch.setattr(browser_ops, "_page", None, raising=False)
    monkeypatch.setattr(browser_ops, "_browser", None, raising=False)
    monkeypatch.setattr(browser_ops, "_context", None, raising=False)
    monkeypatch.setattr(browser_ops, "_network_guard", None, raising=False)
    monkeypatch.setattr(browser_ops, "_browser_error", None, raising=False)

    page = browser_ops._get_page()

    assert page is not None
    assert len(registered) == 1
    assert browser_ops._network_guard is registered[0]
    assert context_kwargs["service_workers"] == "block"
    # The browser transport boundary: every engine connection is forced
    # through the loopback enforcement proxy, and WebRTC cannot bypass it
    # with non-proxied UDP.
    assert launch_kwargs["proxy"]["server"].startswith("http://127.0.0.1:")
    assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in (
        launch_kwargs["args"]
    )


def test_browser_bootstrap_fails_closed_without_request_interception(monkeypatch):
    import sys
    import types

    class FakeContextNoRoute:
        def __init__(self) -> None:
            self.closed = False

        def close(self):
            self.closed = True

        def new_page(self):
            raise AssertionError("page must not be created without enforcement")

    fake_context = FakeContextNoRoute()

    class FakeBrowser:
        def __init__(self) -> None:
            self.closed = False

        def new_context(self, **_kwargs):
            return fake_context

        def close(self):
            self.closed = True

    class FakeBrowserType:
        def __init__(self) -> None:
            self.browser = FakeBrowser()

        def launch(self, **_kwargs):
            return self.browser

    browser_type = FakeBrowserType()

    class FakePlaywright:
        def start(self):
            return self

        chromium = property(lambda self: browser_type)

    fake_pkg = types.ModuleType("patchright")
    fake_pkg.__path__ = []
    fake_mod = types.ModuleType("patchright.sync_api")
    fake_mod.sync_playwright = lambda: FakePlaywright()
    fake_pkg.sync_api = fake_mod
    monkeypatch.setitem(sys.modules, "patchright", fake_pkg)
    monkeypatch.setitem(sys.modules, "patchright.sync_api", fake_mod)
    monkeypatch.setattr(browser_ops, "_page", None, raising=False)
    monkeypatch.setattr(browser_ops, "_browser", None, raising=False)
    monkeypatch.setattr(browser_ops, "_context", None, raising=False)
    monkeypatch.setattr(browser_ops, "_network_guard", None, raising=False)
    monkeypatch.setattr(browser_ops, "_browser_error", None, raising=False)

    page = browser_ops._get_page()

    assert page is None
    assert browser_ops._browser_error is not None
    assert "cannot enforce" in browser_ops._browser_error
    assert fake_context.closed is True
    assert browser_type.browser.closed is True
