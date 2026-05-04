"""
tools/browser_ops.py — P5: Scrapling 浏览器武器库
=====================================================
直接调用 Scrapling + Patchright 本地 Python API，无需 MCP 桥接。

核心能力：
  · web_fetch      — StealthyFetcher 反爬抓取（自动解 Cloudflare）
  · web_click      — 页面元素点击（自适应定位）
  · web_screenshot — 页面截图（存至 SAFE_WORKSPACE）
  · web_select     — 自适应 CSS 选择器提取
  · web_type       — 表单输入
  · web_navigate   — 页面导航

安全约束：
  · 所有下载文件强制存入 SAFE_WORKSPACE (~/.pawnlogic/workspace)
  · 编码清洗 errors='replace'，防止终端崩溃

依赖：
  · pip install 'scrapling[ai]'（含 patchright、playwright）
  · patchright install chromium（首次使用自动下载浏览器）
"""

import os
import json
import time
import shutil
import threading
from pathlib import Path
from datetime import datetime

from config import BROWSER_CONFIG
from utils.ansi import c, YELLOW, GREEN, RED, GRAY, CYAN, BOLD

# ── 常量 ──────────────────────────────────────────────────
SAFE_WORKSPACE = str(Path.home() / ".pawnlogic" / "workspace")
SCREENSHOT_DIR = os.path.join(SAFE_WORKSPACE, "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# ── 全局浏览器上下文（惰性创建）─────────────────────────
_browser_lock = threading.Lock()
_browser = None       # patchright Browser
_context = None        # patchright BrowserContext
_page = None           # patchright Page (当前活跃页面)
_browser_error = None  # 错误信息

# ── 一次性 fetch 用的 Scrapling 实例 ───────────────────
_stealthy_fetcher = None
_fetcher_lock = threading.Lock()


def _get_page():
    """获取或创建浏览器页面（惰性初始化）。"""
    global _browser, _context, _page, _browser_error

    with _browser_lock:
        if _page and not _page.is_closed():
            return _page

        try:
            from patchright.sync_api import sync_playwright
        except ImportError:
            _browser_error = "patchright 未安装。修复: pip install patchright && patchright install chromium"
            return None

        try:
            pw = sync_playwright().start()
            _browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            _context = _browser.new_context(
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
            )
            _page = _context.new_page()
            _browser_error = None
            return _page

        except Exception as e:
            _browser_error = f"浏览器启动失败: {type(e).__name__}: {e}"
            return None


def _get_stealthy_fetcher():
    """获取或创建 StealthyFetcher 实例。"""
    global _stealthy_fetcher
    with _fetcher_lock:
        if _stealthy_fetcher is None:
            try:
                from scrapling import StealthyFetcher
                _stealthy_fetcher = StealthyFetcher()
            except Exception as e:
                _stealthy_fetcher = f"ERROR: {e}"
        return _stealthy_fetcher


def _safe_path(filename: str) -> str:
    """确保文件路径在 SAFE_WORKSPACE 内。"""
    full = os.path.abspath(os.path.join(SCREENSHOT_DIR, filename))
    if not full.startswith(os.path.abspath(SCREENSHOT_DIR)):
        raise ValueError(f"路径越界: {filename}")
    return full


def _clean(text: str) -> str:
    """编码清洗，防止终端崩溃。"""
    if text is None:
        return ""
    return text.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")


# ════════════════════════════════════════════════════════
# 工具实现
# ════════════════════════════════════════════════════════

def tool_web_fetch(a: dict) -> str:
    """
    使用 StealthyFetcher 抓取网页。
    自动处理 Cloudflare 反爬、JS 渲染。
    """
    url = a["url"]
    timeout = int(a.get("timeout", BROWSER_CONFIG["timeout"]))
    print(c(CYAN, f"  🌐 [Scrapling/Fetch] {url[:80]}"))

    try:
        fetcher = _get_stealthy_fetcher()
        if isinstance(fetcher, str):
            return fetcher

        resp = fetcher.fetch(
            url,
            headless=True,
            timeout=timeout * 1000,  # scrapling 用毫秒
        )

        status = resp.status
        # Scrapling TextHandler 可能为 None；fallback 到 body 解码
        raw_text = str(resp.text) if resp.text else ""
        if not raw_text and resp.body:
            raw_text = resp.body.decode("utf-8", errors="replace")
        if not raw_text:
            try:
                raw_text = str(resp.get_all_text())
            except Exception:
                raw_text = ""
        text = raw_text

        if status >= 400:
            return f"HTTP {status}: 请求失败\n{_clean(text[:2000])}"

        # 截断输出
        max_chars = a.get("max_chars", 15000)
        if len(text) > max_chars:
            result = _clean(text[:max_chars]) + f"\n\n[截断: 共 {len(text)} 字符，显示前 {max_chars}]"
        else:
            result = _clean(text)

        return result

    except Exception as e:
        return f"ERROR: Scrapling 抓取失败: {type(e).__name__}: {e}"


def tool_web_click(a: dict) -> str:
    """点击页面元素（自适应定位）。"""
    selector = a["selector"]
    print(c(CYAN, f"  🖱 [Scrapling/Click] {selector[:60]}"))

    page = _get_page()
    if not page:
        return f"ERROR: 浏览器不可用 — {_browser_error}"

    try:
        page.click(selector, timeout=10000)
        # 等待可能的页面响应
        page.wait_for_load_state("domcontentloaded", timeout=5000)
        return f"✓ 已点击: {selector}"
    except Exception as e:
        return f"ERROR: 点击失败 ({selector}): {type(e).__name__}: {e}"


def tool_web_screenshot(a: dict) -> str:
    """
    页面截图，强制存入 SAFE_WORKSPACE。
    返回本地文件路径。
    """
    filename = a.get("filename", "")
    if not filename:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{ts}.png"

    save_path = _safe_path(filename)
    print(c(CYAN, f"  📸 [Scrapling/Screenshot] → {save_path}"))

    page = _get_page()
    if not page:
        return f"ERROR: 浏览器不可用 — {_browser_error}"

    try:
        page.screenshot(path=save_path, full_page=True)
        if os.path.exists(save_path):
            size_kb = os.path.getsize(save_path) / 1024
            return f"✓ 截图已保存: {save_path} ({size_kb:.1f} KB)"
        return "ERROR: 截图文件未生成"
    except Exception as e:
        return f"ERROR: 截图失败: {type(e).__name__}: {e}"


def tool_web_select(a: dict) -> str:
    """使用自适应 CSS 选择器提取页面元素。"""
    selector = a["selector"]
    attribute = a.get("attribute", "text")
    print(c(CYAN, f"  🔍 [Scrapling/Select] {selector[:60]}"))

    page = _get_page()
    if not page:
        return f"ERROR: 浏览器不可用 — {_browser_error}"

    try:
        elements = page.query_selector_all(selector)
        if not elements:
            return f"未找到匹配元素: {selector}"

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

        return "\n".join(results) if results else f"元素存在但内容为空: {selector}"

    except Exception as e:
        return f"ERROR: 选择器查询失败 ({selector}): {type(e).__name__}: {e}"


def tool_web_type(a: dict) -> str:
    """在表单元素中输入文本。"""
    selector = a["selector"]
    text = a["text"]
    print(c(CYAN, f"  ⌨ [Scrapling/Type] {selector[:40]} → {text[:40]}"))

    page = _get_page()
    if not page:
        return f"ERROR: 浏览器不可用 — {_browser_error}"

    try:
        page.fill(selector, text, timeout=10000)
        return f"✓ 已输入: {len(text)} 字符 → {selector}"
    except Exception as e:
        return f"ERROR: 输入失败 ({selector}): {type(e).__name__}: {e}"


def tool_web_navigate(a: dict) -> str:
    """导航到指定 URL。"""
    url = a["url"]
    print(c(CYAN, f"  🧭 [Scrapling/Navigate] {url[:80]}"))

    page = _get_page()
    if not page:
        return f"ERROR: 浏览器不可用 — {_browser_error}"

    try:
        timeout = int(a.get("timeout", BROWSER_CONFIG["timeout"]))
        page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        title = page.title()
        return f"✓ 已导航至: {url}\n  标题: {title}"
    except Exception as e:
        return f"ERROR: 导航失败 ({url}): {type(e).__name__}: {e}"


# ════════════════════════════════════════════════════════
# 状态检测
# ════════════════════════════════════════════════════════

_scrapling_ok = False
_patchright_ok = False

try:
    from scrapling import StealthyFetcher as _SF
    _scrapling_ok = True
except ImportError:
    pass

try:
    from patchright.sync_api import sync_playwright as _sp
    _patchright_ok = True
except ImportError:
    pass


def browser_tool_status() -> str:
    """返回浏览器工具可用性状态。"""
    parts = [
        ("Scrapling 库",    _scrapling_ok,    "pip install 'scrapling[ai]'" if not _scrapling_ok else "已安装"),
        ("Patchright",      _patchright_ok,   "pip install patchright" if not _patchright_ok else "已安装"),
        ("浏览器实例",       _page is not None and not (_page.is_closed() if _page else True),
                                              "未启动（首次使用时自动启动）" if _page is None else "已连接"),
        ("截图目录",         True,             SCREENSHOT_DIR),
    ]

    lines = []
    for name, avail, note in parts:
        tag = c(GREEN, "✓") if avail else c(GRAY, "✗")
        lines.append(f"  {tag} {name:20} {c(GRAY, note)}")

    if _browser_error:
        lines.append(f"  {c(RED, '⚠')} {_browser_error}")

    return "\n".join(lines)


# ════════════════════════════════════════════════════════
# Schema 定义（注册到 TOOLS_SCHEMA）
# ════════════════════════════════════════════════════════

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "使用 Scrapling StealthyFetcher 抓取网页内容。\n"
                "特性：默认开启反爬模式，自动解 Cloudflare 拦截，返回 Markdown 格式。\n"
                "适用：动态渲染页面、有反爬保护的目标站点。\n"
                "比 fetch_url 更强：能穿透 Cloudflare、JS 渲染等防护。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url":     {"type": "string", "description": "目标 URL"},
                    "timeout": {"type": "integer", "description": f"超时秒数（默认 {BROWSER_CONFIG['timeout']}）"},
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
                "点击页面元素（自适应定位）。\n"
                "selector 支持 CSS 选择器或 Scrapling 自适应表达式。\n"
                "需要先使用 web_navigate 或 web_fetch 打开页面。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS 选择器或自适应表达式"},
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
                "对当前页面截图，保存到安全工作区。\n"
                "文件强制存入 ~/.pawnlogic/workspace/screenshots/。\n"
                "返回本地文件路径，可用 analyze_local_image 进行视觉分析。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "文件名（默认自动生成时间戳名）"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_select",
            "description": (
                "使用自适应 CSS 选择器提取页面元素内容。\n"
                "Scrapling 的 adaptive_select 能自动应对 DOM 结构变化。\n"
                "attribute 可选: text（默认）| href | src | value 等。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selector":  {"type": "string", "description": "CSS 选择器或自适应表达式"},
                    "attribute": {"type": "string", "description": "提取的属性，默认 text"},
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
                "在页面表单元素中输入文本。\n"
                "适用于登录框、搜索栏等输入场景。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "目标输入框的 CSS 选择器"},
                    "text":     {"type": "string", "description": "要输入的文本"},
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
                "导航浏览器到指定 URL。\n"
                "用于多步骤 Web 渗透流程中的页面跳转。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "目标 URL"},
                },
                "required": ["url"],
            },
        },
    },
]
