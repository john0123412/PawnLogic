"""
tools/web_ops.py — Web 搜索 + 内容抓取
策略（按优先级）：
  1. Jina Reader  https://r.jina.ai/<url>   → 反爬穿透，返回 Markdown
  2. Pandoc       pandoc -f html -t markdown  → 本地 HTML→Markdown（若已安装）
  3. 正则清洗     原版 regex strip             → 零依赖兜底方案
"""

import re, shutil, subprocess, random
import urllib.request, urllib.parse, urllib.error
from config import DYNAMIC_CONFIG, USER_AGENTS
from utils.ansi import c, BLUE, YELLOW, GRAY, GREEN, RED

# ── 检测本地工具 ─────────────────────────────────────────
_has_pandoc = bool(shutil.which("pandoc"))
_has_lynx   = bool(shutil.which("lynx"))

def _ua() -> str:
    """随机返回一个 User-Agent。"""
    return random.choice(USER_AGENTS)

# ── DuckDuckGo 搜索 ──────────────────────────────────────

def tool_web_search(a: dict) -> str:
    query = a["query"]
    print(c(BLUE, f"  🔍 {query}"))
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
        return "\n\n".join(results) if results else "未找到结果。"
    except Exception as e:
        return f"搜索失败: {e}"

# ── Jina Reader 抓取 ─────────────────────────────────────

def _fetch_jina(url: str, max_chars: int) -> str | None:
    """通过 Jina Reader 抓取，返回 Markdown 或 None（失败时）。"""
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
            text = text[:max_chars] + f"\n...[Jina: 截断至 {max_chars} 字符]..."
        return text
    except Exception:
        return None

# ── Pandoc 抓取 ──────────────────────────────────────────

def _fetch_pandoc(raw_html: str, max_chars: int) -> str | None:
    """用 pandoc 将 HTML 转为 Markdown。需要本地安装 pandoc。"""
    if not _has_pandoc:
        return None
    try:
        proc = subprocess.run(
            ["pandoc", "-f", "html", "-t", "markdown_strict", "--wrap=none"],
            input=raw_html, capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace"
        )
        text = proc.stdout.strip()
        if not text:
            return None
        # 清理 pandoc 生成的多余 backslash 转义
        text = re.sub(r'\\([`*_{}()\[\]#+.!|])', r'\1', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n...[Pandoc: 截断至 {max_chars} 字符]..."
        return text
    except Exception:
        return None

# ── 正则兜底清洗 ─────────────────────────────────────────

def _fetch_regex(raw_html: str, max_chars: int) -> str:
    """零依赖 regex 清洗 HTML → 纯文本。"""
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
        text = text[:max_chars] + f"\n...[Regex: 截断至 {max_chars} 字符]..."
    return text or "(页面为空)"

# ── 主入口 ───────────────────────────────────────────────

def tool_fetch_url(a: dict) -> str:
    url       = a["url"]
    max_chars = int(a.get("max_chars", DYNAMIC_CONFIG["fetch_max_chars"]))
    strategy  = a.get("strategy", "auto")   # auto | jina | pandoc | direct

    # ① Jina Reader（auto 或显式指定）
    if strategy in ("auto", "jina"):
        result = _fetch_jina(url, max_chars)
        if result:
            return f"[来源: Jina Reader]\n{result}"

    # ② 直接抓取原始 HTML
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
        return f"抓取失败: {e}"

    # ③ Pandoc（若已安装）
    if strategy in ("auto", "pandoc") and _has_pandoc:
        result = _fetch_pandoc(raw_html, max_chars)
        if result:
            return f"[来源: Pandoc 解析]\n{result}"

    # ④ 正则兜底
    return f"[来源: 正则清洗]\n{_fetch_regex(raw_html, max_chars)}"

# ── Git ──────────────────────────────────────────────────

def tool_git_op(a: dict) -> str:
    from tools.file_ops import _session_cwd
    action = a["action"]
    rp     = a.get("repo_path") or _session_cwd[0]
    cmds   = {
        "status": "git status",
        "diff":   "git diff",
        "log":    "git log --oneline -20",
        "stash":  "git stash",
    }
    if action in cmds:      cmd = cmds[action]
    elif action == "add":   cmd = f"git add {a.get('files','.')}"
    elif action == "commit":
        msg = a.get("message", "")
        if not msg: return "ERROR: commit 需要 'message' 参数"
        cmd = f"git commit -m '{msg.replace(chr(39), chr(39)+'\\\\'+chr(39)+chr(39))}'"
    elif action == "push":  cmd = f"git push {a.get('remote','origin')}"
    elif action == "pull":  cmd = f"git pull {a.get('remote','origin')}"
    elif action == "clone":
        url = a.get("url","")
        if not url: return "ERROR: clone 需要 'url' 参数"
        cmd = f"git clone {url}"
    elif action == "branch":
        cmd = f"git branch {a.get('branch','')}" if a.get("branch") else "git branch -a"
    elif action == "checkout":
        br = a.get("branch","")
        if not br: return "ERROR: checkout 需要 'branch' 参数"
        cmd = f"git checkout {br}"
    elif action == "raw":
        rc = a.get("raw_cmd","")
        if not rc: return "ERROR: raw 需要 'raw_cmd' 参数"
        cmd = f"git {rc}"
    else:
        return f"ERROR: 未知 action '{action}'"

    print(c(YELLOW, f"  🌿 {cmd}"))
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60, cwd=rp)
        return (res.stdout + res.stderr).strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "ERROR: git 超时"
    except Exception as e:
        return f"ERROR: {e}"

import subprocess   # noqa: E402 (already imported above via shutil section)

# ── Schema ───────────────────────────────────────────────

WEB_SCHEMAS = [
    {"type":"function","function":{
        "name":"web_search",
        "description":"通过 DuckDuckGo 搜索网页，返回最多8条结果（标题、URL、摘要）。搜索后用 fetch_url 读全文。",
        "parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}},

    {"type":"function","function":{
        "name":"fetch_url",
        "description":(
            "抓取 URL 并返回可读文本。"
            "优先使用 Jina Reader（穿透反爬），备用 Pandoc，最后正则清洗。"
            "strategy 可选 auto|jina|pandoc|direct。"
        ),
        "parameters":{"type":"object","properties":{
            "url":{"type":"string"},
            "max_chars":{"type":"integer","description":"最大返回字符数"},
            "strategy":{"type":"string","description":"auto|jina|pandoc|direct，默认 auto"}},
        "required":["url"]}}},

    {"type":"function","function":{
        "name":"git_op",
        "description":"Git 操作：status/diff/log/add/commit/push/pull/clone/branch/checkout/stash/raw",
        "parameters":{"type":"object","properties":{
            "action":{"type":"string","enum":["status","diff","log","add","commit","push","pull","clone","branch","checkout","stash","raw"]},
            "message":{"type":"string"},
            "files":{"type":"string"},
            "branch":{"type":"string"},
            "remote":{"type":"string"},
            "url":{"type":"string"},
            "raw_cmd":{"type":"string"},
            "repo_path":{"type":"string"}},
        "required":["action"]}}},
]

# ── 启动时打印工具状态 ────────────────────────────────────

def web_tool_status() -> str:
    parts = []
    parts.append(("Jina Reader", True, "自动穿透反爬"))
    parts.append(("Pandoc",      _has_pandoc, "HTML→Markdown 高质量解析" if _has_pandoc else "未安装 (apt install pandoc)"))
    parts.append(("Lynx",        _has_lynx,   "字符浏览器备用" if _has_lynx else "未安装"))
    lines = []
    for name, avail, note in parts:
        from utils.ansi import GREEN, GRAY
        tag = c(GREEN, "✓") if avail else c(GRAY, "✗")
        lines.append(f"  {tag} {name:14} {c(GRAY, note)}")
    return "\n".join(lines)
