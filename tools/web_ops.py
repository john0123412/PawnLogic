"""
tools/web_ops.py - web search and content fetching.

Search fallback chain:
  1. Tavily API   https://api.tavily.com/search       AI search, requires TAVILY_API_KEY.
  2. Jina Search  https://s.jina.ai/<query>           free Markdown search, no key required.
  3. DuckDuckGo   https://html.duckduckgo.com/html/   regex fallback, zero dependency.

Fetch fallback chain:
  1. Jina Reader  https://r.jina.ai/<url>             anti-bot-friendly Markdown reader.
  2. Pandoc       pandoc -f html -t markdown          local HTML-to-Markdown when installed.
  3. Regex strip  original regex cleanup              zero-dependency fallback.
"""

import ipaddress
import json
import os
import random
import re
import shutil
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from config import USER_AGENTS, scrub_sensitive_env
from utils.ansi import c, BLUE, YELLOW, GRAY, GREEN
from core.state import state as _runtime_state, runtime_config
from core.trust import trust_notice

# Detect local tools.
_has_pandoc = bool(shutil.which("pandoc"))
_has_lynx   = bool(shutil.which("lynx"))
_URL_ALLOWED_SCHEMES = {"http", "https"}
_METADATA_HOSTS = {
    "metadata.google.internal",
    "metadata",
    "metadata.aliyun.com",
}
_URL_POLICY_WARN_ON_PRIVATE = os.environ.get(
    "PAWNLOGIC_WARN_PRIVATE_NETWORK",
    "1",
).strip().lower() not in {"0", "false", "no", "off"}


def _user_mode() -> bool:
    return bool(_runtime_state.user_mode)


def _is_private_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private


def _is_loopback_ip(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_link_local_ip(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_link_local
    except ValueError:
        return False


def _resolved_host_ips(host: str) -> list:
    try:
        ipaddress.ip_address(host)
        return []
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return []

    ips = []
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        try:
            ips.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            continue
    return ips


def validate_fetch_url(url: str) -> tuple[str | None, list[str]]:
    """
    Validate a URL for fetch/browser tools.

    Returns (error_message_or_none, warnings).
    """
    parsed = urllib.parse.urlparse(str(url).strip())
    if parsed.scheme.lower() not in _URL_ALLOWED_SCHEMES:
        return (
            f"SECURITY BLOCK: unsupported URL scheme '{parsed.scheme or '(missing)'}'. "
            "Only http:// and https:// are allowed.",
            [],
        )
    if not parsed.netloc:
        return "SECURITY BLOCK: URL must include a network location.", []

    host = (parsed.hostname or "").strip().lower()
    if not host:
        return "SECURITY BLOCK: URL host is missing or invalid.", []

    if host == "localhost" or host.endswith(".localhost") or _is_loopback_ip(host):
        return (
            f"SECURITY BLOCK: loopback target '{host}' is denied for web/browser tools by default.",
            [],
        )

    if host in _METADATA_HOSTS or host.endswith(".internal"):
        return (
            f"SECURITY BLOCK: metadata/internal host '{host}' is denied for web/browser tools by default.",
            [],
        )

    if _is_link_local_ip(host):
        return (
            f"SECURITY BLOCK: link-local target '{host}' is denied for web/browser tools by default.",
            [],
        )

    resolved_ips = _resolved_host_ips(host)
    if any(ip.is_loopback for ip in resolved_ips):
        return (
            f"SECURITY BLOCK: target '{host}' resolves to a loopback address; denied by default.",
            [],
        )
    if any(ip.is_link_local for ip in resolved_ips):
        return (
            f"SECURITY BLOCK: target '{host}' resolves to a link-local address; denied by default.",
            [],
        )

    warnings: list[str] = []
    if _URL_POLICY_WARN_ON_PRIVATE and _is_private_ip(host):
        warnings.append(
            f"Private network target '{host}' is allowed, but this crosses the local trust boundary."
        )
    if _URL_POLICY_WARN_ON_PRIVATE and any(ip.is_private for ip in resolved_ips):
        warnings.append(
            f"Target '{host}' resolves to a private network address; this crosses the local trust boundary."
        )
    return None, warnings

def _ua() -> str:
    """Return a random User-Agent."""
    return random.choice(USER_AGENTS)

# Search stage 1: Tavily API.

def _search_tavily(query: str) -> str | None:
    """
    Search through Tavily API.
    Requires TAVILY_API_KEY.
    Returns formatted text on success, otherwise None.
    """
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        return None

    print(c(BLUE, f"  🔍 [Tavily] {query}"))
    payload = json.dumps({
        "api_key": key,
        "query": query,
        "search_depth": "basic",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": _ua(),
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))

        results = data.get("results", [])
        if not results:
            return None

        lines = []
        for i, item in enumerate(results[:8], start=1):
            title   = item.get("title", "").strip()
            url     = item.get("url", "").strip()
            content = item.get("content", "").strip()
            lines.append(f"[{i}] {title}\n    {url}\n    {content}")

        return "\n\n".join(lines) if lines else None

    except Exception:
        return None

# Search stage 2: Jina Search.

def _search_jina(query: str, max_chars: int = 4000) -> str | None:
    """
    Search through Jina Search and return a Markdown summary.
    No API key required, subject to free-tier limits.
    Returns truncated Markdown on success, otherwise None.
    """
    print(c(YELLOW, f"  🔍 [Jina Search] {query}"))
    jina_url = f"https://s.jina.ai/{urllib.parse.quote(query)}"

    try:
        req = urllib.request.Request(
            jina_url,
            headers={
                "Accept": "text/markdown",
                "User-Agent": _ua(),
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            text = resp.read(600_000).decode("utf-8", errors="replace").strip()

        if not text or len(text) < 50:
            return None

        if len(text) > max_chars:
            text = text[:max_chars] + f"\n...[Jina Search: truncated to {max_chars} chars]..."

        return text

    except Exception:
        return None

# Search stage 3: DuckDuckGo regex fallback.

def _search_ddg(query: str) -> str:
    """
    Search via DuckDuckGo HTML and extract title/URL/snippet with regex.
    Zero-dependency final fallback.
    """
    print(c(GRAY, f"  🔍 [DDG Fallback] {query}"))
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus(query)}"
        req = urllib.request.Request(url, headers={
            "User-Agent": _ua(),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        snips  = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
        titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>',        html, re.DOTALL)
        urls   = re.findall(r'uddg=(https?[^&"]+)',                      html)

        results = []
        for i, (t, s) in enumerate(zip(titles[:8], snips[:8])):
            tc = re.sub(r'<[^>]+>', '', t).strip()
            sc = re.sub(r'<[^>]+>', '', s).strip()
            uc = urllib.parse.unquote(urls[i]) if i < len(urls) else ""
            results.append(f"[{i+1}] {tc}\n    {uc}\n    {sc}")

        return "\n\n".join(results) if results else "No results found."

    except Exception as e:
        return f"Search failed: {e}"

# Main search entry with three-stage fallback.

def tool_web_search(a: dict) -> str:
    """
    Main three-stage fallback search:
      1. Tavily API when configured.
      2. Jina Search as free Markdown search.
      3. DuckDuckGo regex fallback.
    """
    query = a["query"]

    # 1. Tavily.
    result = _search_tavily(query)
    if result:
        return f"[Source: Tavily AI Search]\n{result}"

    # 2. Jina Search.
    result = _search_jina(query)
    if result:
        return f"[Source: Jina Search]\n{result}"

    # 3. DuckDuckGo fallback.
    result = _search_ddg(query)
    return f"[Source: DuckDuckGo Fallback]\n{result}"

# Jina Reader fetch.

def _fetch_jina(url: str, max_chars: int) -> str | None:
    """Fetch through Jina Reader and return Markdown, or None on failure."""
    jina_url = f"https://r.jina.ai/{url}"
    print(c(BLUE, f"  🌐 [Jina] {url[:70]}"))
    try:
        req = urllib.request.Request(jina_url, headers={
            "User-Agent": _ua(),
            "Accept": "text/markdown,text/plain,*/*",
            "X-Return-Format": "markdown",
        })
        with urllib.request.urlopen(req, timeout=25) as resp:
            text = resp.read(600_000).decode("utf-8", errors="replace")
        text = text.strip()
        if not text or len(text) < 50:
            return None
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n...[Jina: truncated to {max_chars} chars]..."
        return text
    except Exception:
        return None

# Pandoc fetch.

def _fetch_pandoc(raw_html: str, max_chars: int) -> str | None:
    """Convert HTML to Markdown with pandoc. Requires local pandoc."""
    if not _has_pandoc:
        return None
    try:
        proc = subprocess.run(
            ["pandoc", "-f", "html", "-t", "markdown_strict", "--wrap=none"],
            input=raw_html, capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace", env=scrub_sensitive_env(),
        )
        text = proc.stdout.strip()
        if not text:
            return None
        text = re.sub(r'\\([`*_{}()\[\]#+.!|])', r'\1', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n...[Pandoc: truncated to {max_chars} chars]..."
        return text
    except Exception:
        return None

# Regex fallback cleanup.

def _fetch_regex(raw_html: str, max_chars: int) -> str:
    """Clean HTML into plain text with zero-dependency regex stripping."""
    raw = re.sub(r'<script[^>]*>.*?</script>', '', raw_html, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r'<style[^>]*>.*?</style>',  '', raw,      flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r'<br\s*/?>', '\n',     raw, flags=re.IGNORECASE)
    raw = re.sub(r'<p[^>]*>',  '\n\n',  raw, flags=re.IGNORECASE)
    raw = re.sub(r'<li[^>]*>',  '\n• ', raw, flags=re.IGNORECASE)
    raw = re.sub(r'<h[1-6][^>]*>(.*?)</h[1-6]>', r'\n## \1\n', raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r'<[^>]+>', '', raw)
    raw = re.sub(r'\n{3,}', '\n\n', raw)
    raw = re.sub(r'[ \t]+', ' ', raw)
    text = raw.strip()
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n...[Regex: truncated to {max_chars} chars]..."
    return text or "(empty page)"

# Main fetch entry.

def tool_fetch_url(a: dict) -> str:
    url       = a["url"]
    max_chars = int(a.get("max_chars", runtime_config()["fetch_max_chars"]))
    strategy  = a.get("strategy", "auto")   # auto | jina | pandoc | direct
    err, warnings = validate_fetch_url(url)
    if err:
        return err
    if warnings and _user_mode():
        for warning in warnings:
            print(c(YELLOW, trust_notice(warning)))

    # 1. Jina Reader when auto or explicitly requested.
    if strategy in ("auto", "jina"):
        result = _fetch_jina(url, max_chars)
        if result:
            return f"[Source: Jina Reader]\n{result}"

    # 2. Direct raw HTML fetch.
    print(c(BLUE, f"  🌐 [direct] {url[:70]}"))
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _ua(),
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "identity",
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw_html = resp.read(600_000).decode("utf-8", errors="replace")
    except Exception as e:
        return f"Fetch failed: {e}"

    # 3. Pandoc if installed.
    if strategy in ("auto", "pandoc") and _has_pandoc:
        result = _fetch_pandoc(raw_html, max_chars)
        if result:
            return f"[Source: Pandoc]\n{result}"

    # 4. Regex fallback.
    return f"[Source: Regex cleanup]\n{_fetch_regex(raw_html, max_chars)}"

# ── Git ──────────────────────────────────────────────────

def tool_git_op(a: dict) -> str:
    from tools.file_ops import _session_cwd
    action = a["action"]
    rp     = a.get("repo_path") or _session_cwd[0]

    # Build argv safely to avoid shell injection.
    if action == "status":
        argv = ["git", "status"]
    elif action == "diff":
        argv = ["git", "diff"]
    elif action == "log":
        argv = ["git", "log", "--oneline", "-20"]
    elif action == "stash":
        argv = ["git", "stash"]
    elif action == "add":
        files = a.get("files", ".")
        argv = ["git", "add"] + files.split()
    elif action == "commit":
        msg = a.get("message", "")
        if not msg: return "ERROR: commit requires a 'message' parameter"
        argv = ["git", "commit", "-m", msg]
    elif action == "push":
        argv = ["git", "push", a.get("remote", "origin")]
    elif action == "pull":
        argv = ["git", "pull", a.get("remote", "origin")]
    elif action == "clone":
        url = a.get("url", "")
        if not url: return "ERROR: clone requires a 'url' parameter"
        argv = ["git", "clone", url]
    elif action == "branch":
        br = a.get("branch", "")
        argv = ["git", "branch"] + (br.split() if br else ["-a"])
    elif action == "checkout":
        br = a.get("branch", "")
        if not br: return "ERROR: checkout requires a 'branch' parameter"
        argv = ["git", "checkout", br]
    elif action == "raw":
        rc = a.get("raw_cmd", "")
        if not rc: return "ERROR: raw requires a 'raw_cmd' parameter"
        argv = ["git"] + rc.split()
    else:
        return f"ERROR: unknown action '{action}'"

    print(c(YELLOW, f"  🌿 {' '.join(argv)}"))
    try:
        res = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=rp,
            env=scrub_sensitive_env(),
        )
        return (res.stdout + res.stderr).strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "ERROR: git timed out"
    except Exception as e:
        return f"ERROR: {e}"

# ── Schema ───────────────────────────────────────────────

WEB_SCHEMAS = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": (
            "Three-stage fallback search that should usually return usable results. "
            "1. Tavily AI Search when TAVILY_API_KEY is configured. "
            "2. Jina Search as a free Markdown fallback. "
            "3. DuckDuckGo regex fallback when the first two fail. "
            "Use fetch_url after search to read full pages."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }},

    {"type": "function", "function": {
        "name": "fetch_url",
        "description": (
            "Fetch a URL and return readable text. "
            "Prefers Jina Reader, falls back to Pandoc, then regex cleanup. "
            "strategy may be auto|jina|pandoc|direct."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url":       {"type": "string"},
                "max_chars": {"type": "integer", "description": "Maximum returned characters."},
                "strategy":  {"type": "string",  "description": "auto|jina|pandoc|direct; default auto."},
            },
            "required": ["url"],
        },
    }},

    {"type": "function", "function": {
        "name": "git_op",
        "description": "Git operations: status/diff/log/add/commit/push/pull/clone/branch/checkout/stash/raw",
        "parameters": {
            "type": "object",
            "properties": {
                "action":    {"type": "string", "enum": ["status","diff","log","add","commit","push","pull","clone","branch","checkout","stash","raw"]},
                "message":   {"type": "string"},
                "files":     {"type": "string"},
                "branch":    {"type": "string"},
                "remote":    {"type": "string"},
                "url":       {"type": "string"},
                "raw_cmd":   {"type": "string"},
                "repo_path": {"type": "string"},
            },
            "required": ["action"],
        },
    }},
]

# Startup tool status.

def web_tool_status() -> str:
    _has_tavily = bool(os.getenv("TAVILY_API_KEY"))

    parts = [
        ("Tavily Search API", _has_tavily,  "AI search enabled" if _has_tavily else "TAVILY_API_KEY not configured; skipped"),
        ("Jina Search",       True,          "free Markdown search fallback"),
        ("DuckDuckGo",        True,          "regex search fallback"),
        ("Jina Reader",       True,          "URL fetch with anti-bot reader"),
        ("Pandoc",            _has_pandoc,   "high-quality HTML-to-Markdown parser" if _has_pandoc else "not installed (apt install pandoc)"),
        ("Lynx",              _has_lynx,     "text browser fallback" if _has_lynx else "not installed"),
    ]

    lines = []
    for name, avail, note in parts:
        tag = c(GREEN, "✓") if avail else c(GRAY, "✗")
        lines.append(f"  {tag} {name:20} {c(GRAY, note)}")
    return "\n".join(lines)
