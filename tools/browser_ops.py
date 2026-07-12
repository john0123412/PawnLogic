"""
tools/browser_ops.py - P5 Scrapling/Patchright browser tools.

Uses local Scrapling + Patchright Python APIs directly without an MCP bridge.

Core capabilities:
  - web_fetch: StealthyFetcher anti-bot page fetching.
  - web_click: element clicks.
  - web_screenshot: page screenshots stored under SAFE_WORKSPACE.
  - web_select: CSS selector extraction.
  - web_type: form input.
  - web_navigate: page navigation.

Architecture:
  - web_fetch uses StealthyFetcher/Camoufox without a browser window.
  - screenshot/click/select/type/navigate use Patchright.
  - _current_url bridges both engines so fetch can sync later screenshots.

Safety constraints:
  - Downloaded/generated files are forced into SAFE_WORKSPACE.
  - Output is cleaned with errors='ignore'.

Dependencies:
  - pip install 'pawnlogic[browser]' for scrapling and patchright.
  - patchright install chromium for first-time browser setup.
"""

import os
import time
import threading
from datetime import datetime
from pathlib import Path

from config import BROWSER_CONFIG, WORKSPACE_DIR
from core.path_policy import resolve_within
from core.state import state as _runtime_state
from core.trust import (
    BROWSER_SANDBOX_DISABLED,
    TrustBoundaryKind,
    trust_notice,
    trust_notice_for_boundary,
)
from tools.web_ops import validate_fetch_url
from utils.ansi import c, YELLOW, GREEN, RED, GRAY, CYAN

# Constants.
SAFE_WORKSPACE = WORKSPACE_DIR
SCREENSHOT_DIR = os.path.join(SAFE_WORKSPACE, "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# Cross-engine URL bridge:
# web_fetch sets _current_url; web_screenshot reads it and syncs navigation.
_current_url = None

# Global Patchright browser context, created lazily.
_browser_lock = threading.Lock()
_browser = None       # patchright Browser
_context = None        # patchright BrowserContext
_page = None           # active patchright Page
_browser_error = None  # error message

# StealthyFetcher instance, created lazily.
_stealthy_fetcher = None
_fetcher_error = None
_fetcher_lock = threading.Lock()
_browser_warning_emitted = False


def _user_mode() -> bool:
    return bool(_runtime_state.user_mode)


def _browser_launch_args() -> list[str]:
    args = ["--disable-blink-features=AutomationControlled"]
    allow_no_sandbox = bool(BROWSER_CONFIG.get("allow_no_sandbox", False))
    if allow_no_sandbox:
        args.insert(0, "--no-sandbox")
    return args


def _emit_browser_trust_warning() -> None:
    global _browser_warning_emitted
    if _browser_warning_emitted or not _user_mode():
        return
    _browser_warning_emitted = True
    print(c(YELLOW, trust_notice_for_boundary(TrustBoundaryKind.BROWSER_NETWORK)))
    if BROWSER_CONFIG.get("allow_no_sandbox", False):
        print(c(YELLOW, trust_notice(BROWSER_SANDBOX_DISABLED)))


def _validate_browser_url(url: str) -> tuple[str | None, list[str]]:
    return validate_fetch_url(url)


def _get_page():
    """Get or create a Patchright browser page lazily."""
    global _browser, _context, _page, _browser_error

    with _browser_lock:
        if _page and not _page.is_closed():
            return _page

        try:
            from patchright.sync_api import sync_playwright
        except ImportError:
            _browser_error = (
                "Browser dependencies are not installed. Fix: pip install 'pawnlogic[browser]' && patchright install chromium"
            )
            return None

        try:
            pw = sync_playwright().start()
            _emit_browser_trust_warning()
            _browser = pw.chromium.launch(
                headless=True,
                args=_browser_launch_args(),
            )
            _context = _browser.new_context(
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
            )
            _page = _context.new_page()
            _browser_error = None
            return _page

        except Exception as e:
            _browser_error = f"browser startup failed: {type(e).__name__}: {e}"
            return None


def _ensure_page_url(url: str):
    """Ensure the Patchright page has navigated to the target URL."""
    global _current_url
    err, warnings = _validate_browser_url(url)
    if err:
        _current_url = None
        return
    page = _get_page()
    if not page:
        return
    try:
        if warnings and _user_mode():
            for warning in warnings:
                print(c(YELLOW, trust_notice(warning)))
        current = page.url
        # Navigate when about:blank or URL mismatch is detected.
        if not current or current == "about:blank" or current != url:
            timeout_ms = BROWSER_CONFIG["timeout"] * 1000
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            _current_url = url
    except Exception:
        pass  # Navigation failure should not block screenshots that may still have content.


def _get_stealthy_fetcher():
    """Get or create a StealthyFetcher instance.
    StealthyFetcher.configure() warms global Camoufox state to avoid first-fetch cold-start timeouts.
    """
    global _stealthy_fetcher, _fetcher_error
    with _fetcher_lock:
        if _stealthy_fetcher is None:
            try:
                from scrapling import StealthyFetcher
                # Global warm-up; later fetch() calls reuse the preloaded engine configuration.
                StealthyFetcher.configure()
                _stealthy_fetcher = StealthyFetcher()
                _fetcher_error = None
            except Exception as e:
                if isinstance(e, ImportError):
                    _fetcher_error = "ERROR: browser dependencies are not installed. Fix: pip install 'pawnlogic[browser]'"
                    return None
                _fetcher_error = f"ERROR: {e}"
                return None
        return _stealthy_fetcher


def _retry_fetch(fetcher, url: str, timeout_ms: int, max_retries: int = 3):
    """Retry fetches with increasing delays for timeout failures.
    Delay sequence: 2s, 5s, 10s.
    """
    delays = [2, 5, 10]
    last_exc = None
    for attempt in range(max_retries):
        try:
            return fetcher.fetch(url, headless=True, timeout=timeout_ms)
        except Exception as e:
            last_exc = e
            err_name = type(e).__name__
            is_timeout = "timeout" in str(e).lower() or "Timeout" in err_name
            if not is_timeout or attempt == max_retries - 1:
                raise
            delay = delays[min(attempt, len(delays) - 1)]
            print(c(YELLOW,
                f"  [Retry {attempt+1}/{max_retries}] {err_name}, "
                f"retrying after {delay}s..."
            ))
            time.sleep(delay)
    raise RuntimeError("fetch retry loop exhausted") from last_exc


def _safe_path(filename: str) -> str:
    """Ensure a file path stays inside SCREENSHOT_DIR using canonical containment."""
    try:
        resolved = resolve_within(Path(SCREENSHOT_DIR), filename)
    except ValueError:
        raise ValueError(f"path escapes screenshot directory: {filename}") from None
    return str(resolved)


def _clean(text: str) -> str:
    """Clean encoding to avoid terminal crashes."""
    if text is None:
        return ""
    return text.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")


def _format_browser_error(action: str, exc: Exception) -> str:
    """Return a compact browser-tool error without traceback internals."""
    detail = " ".join(str(exc).split())
    detail = detail.replace("Traceback (most recent call last):", "").strip()
    return f"ERROR: {action}: {type(exc).__name__}: {_clean(detail)}"


# ════════════════════════════════════════════════════════
# Tool implementations.
# ════════════════════════════════════════════════════════

def tool_web_fetch(a: dict) -> str:
    """
    Fetch a page with StealthyFetcher without MCP overhead.
    Handles anti-bot pages and JS rendering where Scrapling can.
    Syncs the URL to Patchright for later web_screenshot consistency.
    """
    global _current_url
    url = a["url"]
    timeout = int(a.get("timeout", BROWSER_CONFIG["timeout"]))
    print(c(CYAN, f"  🌐 [Scrapling/Fetch] {url[:80]}"))
    err, warnings = _validate_browser_url(url)
    if err:
        return err
    if warnings and _user_mode():
        for warning in warnings:
            print(c(YELLOW, trust_notice(warning)))

    try:
        fetcher = _get_stealthy_fetcher()
        if fetcher is None:
            return _fetcher_error or "ERROR: browser initialization failed"

        # StealthyFetcher is Camoufox-backed; timeout is in milliseconds.
        # Timeout retry delays are 2s -> 5s -> 10s.
        resp = _retry_fetch(fetcher, url, timeout * 1000, max_retries=3)

        _current_url = url

        status = resp.status
        # Scrapling TextHandler may be None, so use multiple fallbacks.
        raw_text = str(resp.text) if resp.text else ""
        if not raw_text and resp.body:
            raw_text = resp.body.decode("utf-8", errors="ignore")
        if not raw_text:
            try:
                raw_text = str(resp.get_all_text())
            except Exception:
                raw_text = ""
        text = raw_text

        if status >= 400:
            return f"HTTP {status}: request failed\n{_clean(text[:2000])}"

        # Truncate output.
        max_chars = a.get("max_chars", 15000)
        if len(text) > max_chars:
            result = _clean(text[:max_chars]) + f"\n\n[truncated: {len(text)} chars total, showing first {max_chars}]"
        else:
            result = _clean(text)

        return result

    except Exception as e:
        return _format_browser_error("Scrapling fetch failed", e)


def tool_web_click(a: dict) -> str:
    """Click a page element with Patchright."""
    selector = a["selector"]
    print(c(CYAN, f"  🖱 [Scrapling/Click] {selector[:60]}"))

    page = _get_page()
    if not page:
        return f"ERROR: browser unavailable - {_browser_error}"

    try:
        page.click(selector, timeout=10000)
        page.wait_for_load_state("domcontentloaded", timeout=5000)
        return f"OK: clicked {selector}"
    except Exception as e:
        return _format_browser_error(f"click failed ({selector})", e)


def tool_web_screenshot(a: dict) -> str:
    """
    Capture a page screenshot with Patchright.
    Forces output under SAFE_WORKSPACE.
    Syncs _current_url when web_fetch has just fetched a page.
    """
    global _current_url
    url = a.get("url", _current_url)
    filename = a.get("filename", "")
    if not filename:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{ts}.png"

    save_path = _safe_path(filename)
    print(c(CYAN, f"  [Scrapling/Screenshot] {url or '(current page)'} -> {save_path}"))

    page = _get_page()
    if not page:
        return f"ERROR: browser unavailable - {_browser_error}"

    try:
        # If fetch set a URL but Patchright has not navigated yet, sync it.
        if url:
            _ensure_page_url(url)

        page.screenshot(path=save_path, full_page=True)
        if os.path.exists(save_path):
            size_kb = os.path.getsize(save_path) / 1024
            return f"OK: screenshot saved: {save_path} ({size_kb:.1f} KB)"
        return "ERROR: screenshot file was not generated"
    except Exception as e:
        return _format_browser_error("screenshot failed", e)


def tool_web_select(a: dict) -> str:
    """Extract page elements with a CSS selector."""
    selector = a["selector"]
    attribute = a.get("attribute", "text")
    print(c(CYAN, f"  🔍 [Scrapling/Select] {selector[:60]}"))

    page = _get_page()
    if not page:
        return f"ERROR: browser unavailable - {_browser_error}"

    try:
        elements = page.query_selector_all(selector)
        if not elements:
            return f"No matching elements found: {selector}"

        results = []
        for i, el in enumerate(elements):
            if attribute == "text":
                val = el.text_content() or ""
            elif attribute == "href":
                val = el.get_attribute("href") or ""
            elif attribute == "src":
                val = el.get_attribute("src") or ""
            elif attribute == "value":
                val = el.get_attribute("value") or ""
            else:
                val = el.get_attribute(attribute) or ""
            results.append(_clean(val.strip()))

        return "\n".join(results) if results else f"Elements exist but content is empty: {selector}"

    except Exception as e:
        return _format_browser_error(f"selector query failed ({selector})", e)


def tool_web_type(a: dict) -> str:
    """Fill text into a form element."""
    selector = a["selector"]
    text = a["text"]
    print(c(CYAN, f"  [Scrapling/Type] {selector[:40]} -> {text[:40]}"))

    page = _get_page()
    if not page:
        return f"ERROR: browser unavailable - {_browser_error}"

    try:
        page.fill(selector, text, timeout=10000)
        return f"OK: typed {len(text)} chars into {selector}"
    except Exception as e:
        return _format_browser_error(f"type failed ({selector})", e)


def tool_web_navigate(a: dict) -> str:
    """Navigate the browser to a URL with Patchright."""
    global _current_url
    url = a["url"]
    print(c(CYAN, f"  🧭 [Scrapling/Navigate] {url[:80]}"))
    err, warnings = _validate_browser_url(url)
    if err:
        return err
    if warnings and _user_mode():
        for warning in warnings:
            print(c(YELLOW, trust_notice(warning)))

    page = _get_page()
    if not page:
        return f"ERROR: browser unavailable - {_browser_error}"

    try:
        timeout = int(a.get("timeout", BROWSER_CONFIG["timeout"]))
        page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        _current_url = url
        title = page.title()
        return f"OK: navigated to {url}\n  Title: {title}"
    except Exception as e:
        return _format_browser_error(f"navigation failed ({url})", e)


# ════════════════════════════════════════════════════════
# Status checks.
# ════════════════════════════════════════════════════════

_scrapling_ok = False
_patchright_ok = False

try:
    from scrapling import StealthyFetcher as _SF  # noqa: F401
    _scrapling_ok = True
except ImportError:
    pass

try:
    from patchright.sync_api import sync_playwright as _sp  # noqa: F401
    _patchright_ok = True
except ImportError:
    pass


def browser_tool_status() -> str:
    """Return browser tool availability status."""
    parts = [
        ("Scrapling",       _scrapling_ok,    "pip install 'pawnlogic[browser]'" if not _scrapling_ok else "installed"),
        ("Patchright",      _patchright_ok,   "pip install 'pawnlogic[browser]' && patchright install chromium" if not _patchright_ok else "installed"),
        ("Browser instance", _page is not None and not (_page.is_closed() if _page else True),
                                               "not started; starts automatically on first use" if _page is None else "connected"),
        ("Screenshot dir",   True,             SCREENSHOT_DIR),
    ]

    lines = []
    for name, avail, note in parts:
        tag = c(GREEN, "✓") if avail else c(GRAY, "✗")
        lines.append(f"  {tag} {name:20} {c(GRAY, note)}")

    if _browser_error:
        lines.append(f"  {c(RED, '⚠')} {_browser_error}")

    return "\n".join(lines)


# ════════════════════════════════════════════════════════
# Schema definitions registered by session.py.
# ════════════════════════════════════════════════════════

BROWSER_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "Fetch a web page with Scrapling StealthyFetcher without MCP overhead.\n"
                "Uses the Camoufox anti-detection engine, handles some Cloudflare/JS-rendered pages, and returns plain text.\n"
                "After fetching, automatically syncs the URL to the browser so web_screenshot aligns with it.\n"
                "Stronger than fetch_url for Cloudflare and JS-rendered pages."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url":       {"type": "string", "description": "Target URL."},
                    "timeout":   {"type": "integer", "description": f"Timeout seconds (default {BROWSER_CONFIG['timeout']})."},
                    "max_chars": {"type": "integer", "description": "Maximum returned characters (default 15000)."},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_click",
            "description": (
                "Click a page element.\n"
                "selector supports CSS selectors.\n"
                "Use web_navigate or web_fetch first to open a page."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector."},
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_screenshot",
            "description": (
                "Capture a screenshot of the current page with Patchright.\n"
                "Files are forced into ~/.pawnlogic/workspace/screenshots/.\n"
                "Automatically syncs a URL recently fetched by web_fetch; no manual navigate is needed.\n"
                "Returns a local file path that can be passed to analyze_local_image."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url":      {"type": "string", "description": "Optional screenshot target URL; defaults to the last fetch/navigate URL."},
                    "filename": {"type": "string", "description": "Filename; defaults to a generated timestamp name."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_select",
            "description": (
                "Extract page element content with a CSS selector.\n"
                "attribute can be text (default), href, src, value, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selector":  {"type": "string", "description": "CSS selector."},
                    "attribute": {"type": "string", "description": "Attribute to extract; default text."},
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_type",
            "description": (
                "Type text into a page form element.\n"
                "Useful for login boxes, search fields, and similar inputs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "Target input CSS selector."},
                    "text":     {"type": "string", "description": "Text to type."},
                },
                "required": ["selector", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_navigate",
            "description": (
                "Navigate the browser to a URL.\n"
                "Useful for multi-step web workflows."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Target URL."},
                },
                "required": ["url"],
            },
        },
    },
]
