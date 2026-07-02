"""Deterministic browser tool failure-path tests."""

from __future__ import annotations

from tools import browser_ops


class _TimeoutPage:
    url = "about:blank"

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
    monkeypatch.setattr(browser_ops, "_validate_browser_url", lambda _url: (None, []))

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
    monkeypatch.setattr(browser_ops, "_validate_browser_url", lambda _url: (None, []))

    result = browser_ops.tool_web_fetch({"url": "https://example.test", "timeout": 1})

    assert result.startswith("ERROR: Scrapling fetch failed")
    assert "RuntimeError" in result
    assert "Traceback" not in result
