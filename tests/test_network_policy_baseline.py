"""Current network URL-policy characterization without real network access."""

from __future__ import annotations

import socket
import urllib.parse
from typing import Any

import pytest

from tools import browser_ops, network_adapter, web_ops


@pytest.fixture(autouse=True)
def _reset_browser_url(monkeypatch):
    monkeypatch.setattr(browser_ops, "_current_url", None)


def _addrinfo_for(address: str) -> list[tuple[Any, ...]]:
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sockaddr: tuple[Any, ...] = (
        (address, 0, 0, 0) if family == socket.AF_INET6 else (address, 0)
    )
    return [(family, socket.SOCK_STREAM, 6, "", sockaddr)]


class _FakeResponse:
    def __init__(self, body: bytes, final_url: str | None = None) -> None:
        self._body = body
        self._final_url = final_url

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int = -1) -> bytes:
        return self._body

    def geturl(self) -> str | None:
        return self._final_url


def test_search_backends_use_network_policy_opener(monkeypatch):
    targets: list[str] = []

    def record_policy_open(request, **_kwargs):
        targets.append(request.full_url)
        raise RuntimeError("synthetic stop")

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(web_ops, "_open_url_with_policy", record_policy_open)
    monkeypatch.setattr(
        web_ops.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("search must use the policy opener")
        ),
    )

    assert web_ops._search_tavily("query") is None
    assert web_ops._search_jina("query") is None
    assert web_ops._search_ddg("query").startswith("Search failed:")
    assert [urllib.parse.urlsplit(target).hostname for target in targets] == [
        "api.tavily.com",
        "s.jina.ai",
        "html.duckduckgo.com",
    ]


@pytest.mark.parametrize(
    "url",
    [
        "",
        "example.test/path",
        "ftp://example.test/resource",
        "http://",
        "https:///missing-host",
    ],
)
def test_malformed_or_unsupported_urls_are_blocked_before_dns(monkeypatch, url):
    def fail_getaddrinfo(*_args, **_kwargs):
        raise AssertionError("malformed URL must not reach DNS resolution")

    monkeypatch.setattr(web_ops.socket, "getaddrinfo", fail_getaddrinfo)

    error, warnings = web_ops.validate_fetch_url(url)

    assert error is not None
    assert error.startswith("SECURITY BLOCK")
    assert warnings == []


def test_unmatched_ipv6_bracket_is_a_structured_security_block():
    error, warnings = web_ops.validate_fetch_url("http://[::1")

    assert error is not None
    assert error.startswith("SECURITY BLOCK")
    assert "Traceback" not in error
    assert warnings == []


@pytest.mark.parametrize("host", ["localhost", "service.localhost", "127.0.0.1", "::1"])
def test_localhost_and_loopback_literals_are_blocked(host):
    url_host = f"[{host}]" if ":" in host else host

    error, warnings = web_ops.validate_fetch_url(f"http://{url_host}:8080")

    assert error is not None
    assert "loopback" in error
    assert warnings == []


@pytest.mark.parametrize("host", ["169.254.1.10", "fe80::1"])
def test_link_local_literals_are_blocked(host):
    url_host = f"[{host}]" if ":" in host else host

    error, warnings = web_ops.validate_fetch_url(f"http://{url_host}:8080")

    assert error is not None
    assert "link-local" in error
    assert warnings == []


@pytest.mark.parametrize("host", ["10.0.0.5", "172.16.0.5", "192.168.1.5", "fc00::5"])
def test_private_literals_are_allowed_with_warning(host):
    url_host = f"[{host}]" if ":" in host else host

    error, warnings = web_ops.validate_fetch_url(f"http://{url_host}:8080")

    assert error is None
    assert any("Private network target" in warning for warning in warnings)


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("10.1.2.3", "private network address"),
        ("127.0.0.1", "loopback address"),
        ("169.254.10.20", "link-local address"),
    ],
)
def test_dns_resolved_addresses_follow_current_policy(monkeypatch, address, expected):
    monkeypatch.setattr(
        web_ops.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _addrinfo_for(address),
    )

    error, warnings = web_ops.validate_fetch_url("http://resolved.example.test/path")

    if expected == "private network address":
        assert error is None
        assert any("private network address" in warning for warning in warnings)
    else:
        assert error is not None
        assert expected in error
        assert warnings == []


def test_dns_resolution_failure_is_confirmable_in_legacy_validation(monkeypatch):
    monkeypatch.setattr(
        web_ops.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(socket.gaierror("synthetic DNS failure")),
    )

    error, warnings = web_ops.validate_fetch_url("http://unresolved.example.test")

    assert error is None
    assert warnings == []


def test_dns_failure_fails_closed_before_direct_http_in_noninteractive_mode(monkeypatch):
    monkeypatch.setattr(
        web_ops.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            socket.gaierror("synthetic DNS failure")
        ),
    )
    requests: list[object] = []

    def fail_open(request, **_kwargs):
        requests.append(request)
        raise AssertionError("DNS failure must block HTTP")

    monkeypatch.setattr(web_ops, "_open_url_with_policy", fail_open)

    result = web_ops.tool_fetch_url(
        {
            "url": "https://dns-failure.example.test",
            "strategy": "direct",
            "interactive": False,
        }
    )

    assert result.startswith("SECURITY BLOCK")
    assert "DNS resolution failed" in result
    assert requests == []


def test_direct_fetch_validates_before_http_for_loopback_resolution(monkeypatch):
    monkeypatch.setattr(
        web_ops.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _addrinfo_for("127.0.0.1"),
    )
    calls: list[object] = []

    def fail_urlopen(request, **_kwargs):
        calls.append(request)
        raise AssertionError("blocked URL must not reach HTTP")

    monkeypatch.setattr(web_ops.urllib.request, "urlopen", fail_urlopen)

    result = web_ops.tool_fetch_url(
        {"url": "http://blocked.example.test", "strategy": "direct"}
    )

    assert result.startswith("SECURITY BLOCK")
    assert calls == []


def test_direct_fetch_allows_private_literal_after_host_confirmation(monkeypatch):
    requests: list[str] = []

    def fake_urlopen(request, **_kwargs):
        requests.append(request.full_url)
        return _FakeResponse(b"<h1>synthetic private page</h1>")

    monkeypatch.setattr(web_ops, "_open_url_with_policy", fake_urlopen)
    monkeypatch.setattr(
        network_adapter,
        "is_confirmation_available",
        lambda: True,
    )
    monkeypatch.setattr(
        network_adapter,
        "prompt_for_confirmation",
        lambda _decision: True,
    )

    result = web_ops.tool_fetch_url(
        {"url": "http://192.168.1.5:8080/page", "strategy": "direct"}
    )

    assert result == "[Source: Regex cleanup]\n## synthetic private page"
    assert requests == ["http://192.168.1.5:8080/page"]


def test_confirmed_private_fetch_never_uses_remote_reader(monkeypatch):
    remote_reader_calls: list[str] = []
    monkeypatch.setattr(
        network_adapter,
        "is_confirmation_available",
        lambda: True,
    )
    monkeypatch.setattr(
        network_adapter,
        "prompt_for_confirmation",
        lambda _decision: True,
    )
    monkeypatch.setattr(
        web_ops,
        "_fetch_jina",
        lambda url, *_args: remote_reader_calls.append(url),
    )
    monkeypatch.setattr(
        web_ops,
        "_open_url_with_policy",
        lambda _request, **_kwargs: _FakeResponse(b"<p>private page</p>"),
    )

    result = web_ops.tool_fetch_url(
        {"url": "http://192.168.1.5/private", "strategy": "auto"}
    )

    assert result.endswith("\nprivate page")
    assert "[Source: Jina Reader]" not in result
    assert remote_reader_calls == []


def test_browser_navigate_validates_before_page_creation_for_dns_loopback(monkeypatch):
    monkeypatch.setattr(
        web_ops.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _addrinfo_for("127.0.0.1"),
    )
    page_calls: list[str] = []

    def fail_get_page():
        page_calls.append("created")
        raise AssertionError("blocked URL must not create a browser page")

    monkeypatch.setattr(browser_ops, "_get_page", fail_get_page)

    result = browser_ops.tool_web_navigate({"url": "http://browser.example.test"})

    assert result.startswith("SECURITY BLOCK")
    assert page_calls == []


def test_browser_navigate_allows_private_literal_after_host_confirmation(monkeypatch):
    class FakePage:
        url = "about:blank"

        def goto(self, url, **_kwargs):
            self.url = url

        def title(self):
            return "Synthetic page"

    page = FakePage()
    monkeypatch.setattr(browser_ops, "_get_page", lambda: page)
    monkeypatch.setattr(
        network_adapter,
        "is_confirmation_available",
        lambda: True,
    )
    monkeypatch.setattr(
        network_adapter,
        "prompt_for_confirmation",
        lambda _decision: True,
    )

    result = browser_ops.tool_web_navigate({"url": "http://192.168.1.5:8080"})

    assert result == (
        "OK: navigated to http://192.168.1.5:8080\n  Title: Synthetic page"
    )
    assert page.url == "http://192.168.1.5:8080"


def test_model_arguments_cannot_self_authorize_private_network(monkeypatch):
    touched: list[str] = []
    monkeypatch.setattr(
        web_ops,
        "_open_url_with_policy",
        lambda *_args, **_kwargs: touched.append("opened"),
    )

    result = web_ops.tool_fetch_url(
        {
            "url": "http://192.168.1.5:8080/private",
            "strategy": "direct",
            "allow_private_network": True,
            "explicit_authorization": True,
            "authorized_targets": ["192.168.1.5"],
        }
    )

    assert result.startswith("SECURITY BLOCK")
    assert touched == []


def test_direct_fetch_rejects_fake_redirect_target_before_consuming_body(monkeypatch):
    final_url = "http://127.0.0.1:9000/metadata"
    monkeypatch.setattr(
        web_ops,
        "_open_url_with_policy",
        lambda _request, **_kwargs: _FakeResponse(
            b"<p>response after redirect</p>", final_url=final_url
        ),
    )
    monkeypatch.setattr(
        web_ops.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _addrinfo_for("93.184.216.34"),
    )

    result = web_ops.tool_fetch_url(
        {"url": "https://public.example.test/start", "strategy": "direct"}
    )

    assert result.startswith("SECURITY BLOCK")
    assert "loopback" in result


def test_urllib_redirect_handler_blocks_before_following(monkeypatch):
    handler = web_ops._NetworkRedirectHandler({"interactive": False})
    request = web_ops.urllib.request.Request("https://public.example.test/start")

    with pytest.raises(web_ops._NetworkPolicyBlocked) as blocked:
        handler.redirect_request(
            request,
            object(),
            302,
            "Found",
            {},
            "http://127.0.0.1:9000/metadata",
        )

    assert "loopback" in str(blocked.value)


def test_browser_navigate_rechecks_final_url_when_fake_page_has_no_route_api(monkeypatch):
    requested_url = "https://public.example.test/start"
    redirected_url = "http://127.0.0.1:9000/metadata"

    class RedirectingPage:
        url = "about:blank"

        def goto(self, _url, **_kwargs):
            self.url = redirected_url

        def title(self):
            return "Redirected synthetic page"

    page = RedirectingPage()
    monkeypatch.setattr(browser_ops, "_get_page", lambda: page)
    monkeypatch.setattr(
        web_ops.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _addrinfo_for("93.184.216.34"),
    )

    result = browser_ops.tool_web_navigate({"url": requested_url})

    assert result.startswith("SECURITY BLOCK")
    assert "loopback" in result
    assert page.url == redirected_url
    assert browser_ops._current_url is None


def test_browser_route_guard_aborts_redirect_request_when_api_is_available(monkeypatch):
    requested_url = "https://public.example.test/start"
    redirected_url = "http://127.0.0.1:9000/metadata"

    class FakeRoute:
        def __init__(self) -> None:
            self.aborted = False

        def abort(self):
            self.aborted = True

        def continue_(self):
            raise AssertionError("blocked request must not continue")

    class FakeRequest:
        url = redirected_url

    class RoutedPage:
        url = "about:blank"

        def __init__(self) -> None:
            self.handler = None
            self.route_obj = FakeRoute()

        def route(self, _pattern, handler):
            self.handler = handler

        def unroute(self, *_args):
            return None

        def goto(self, _url, **_kwargs):
            assert self.handler is not None
            self.handler(self.route_obj, FakeRequest())
            if self.route_obj.aborted:
                raise RuntimeError("synthetic route abort")

        def title(self):
            return "unreachable"

    page = RoutedPage()
    monkeypatch.setattr(browser_ops, "_get_page", lambda: page)
    monkeypatch.setattr(
        web_ops.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _addrinfo_for("93.184.216.34"),
    )

    result = browser_ops.tool_web_navigate(
        {"url": requested_url, "interactive": False}
    )

    assert result.startswith("SECURITY BLOCK")
    assert "loopback" in result
    assert page.route_obj.aborted is True


def test_policy_lookup_and_http_request_are_separate_dns_rebinding_seams(monkeypatch):
    dns_calls: list[str] = []

    def fake_getaddrinfo(host, *_args, **_kwargs):
        dns_calls.append(host)
        return _addrinfo_for("93.184.216.34")

    requests: list[str] = []

    def fake_urlopen(request, **_kwargs):
        requests.append(request.full_url)
        return _FakeResponse(b"<p>stable synthetic response</p>")

    monkeypatch.setattr(web_ops.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(web_ops, "_open_url_with_policy", fake_urlopen)

    result = web_ops.tool_fetch_url(
        {"url": "https://rebind.example.test/start", "strategy": "direct"}
    )

    assert result == "[Source: Regex cleanup]\nstable synthetic response"
    assert dns_calls == ["rebind.example.test"]
    assert requests == ["https://rebind.example.test/start"]
