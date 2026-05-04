"""
tools/browser_ops.py — P5: Scrapling MCP 浏览器武器库
=====================================================
MCP 桥接器：连接 Scrapling MCP Server，提供 Web 渗透能力。

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
  · MCP Server 进程生命周期与模块绑定

依赖：
  · pip install mcp（可选，不强制）
  · npx（Node.js >= 18，用于启动 Scrapling MCP Server）
"""

import os
import json
import time
import shutil
import asyncio
import threading
from pathlib import Path
from datetime import datetime

from config import BROWSER_CONFIG
from utils.ansi import c, YELLOW, GREEN, RED, GRAY, CYAN, BOLD

# ════════════════════════════════════════════════════════
# 安全工作区（复用 P4 的定义，保持一致性）
# ════════════════════════════════════════════════════════

SAFE_WORKSPACE = os.path.abspath(os.path.expanduser("~/.pawnlogic/workspace"))
SCREENSHOT_DIR = os.path.join(SAFE_WORKSPACE, "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


# ════════════════════════════════════════════════════════
# MCP 客户端（同步化封装）
# ════════════════════════════════════════════════════════

_mcp_session = None
_mcp_loop    = None
_mcp_thread  = None
_mcp_error   = None
_mcp_ready   = False
_mcp_lock    = threading.Lock()


def _ensure_mcp_loop():
    """在后台线程运行 asyncio 事件循环（MCP 需要 async）。"""
    global _mcp_loop, _mcp_thread
    if _mcp_loop is not None:
        return
    _mcp_loop = asyncio.new_event_loop()

    def _run():
        asyncio.set_event_loop(_mcp_loop)
        _mcp_loop.run_forever()

    _mcp_thread = threading.Thread(target=_run, daemon=True, name="mcp-event-loop")
    _mcp_thread.start()


def _run_async(coro):
    """在后台事件循环中执行协程并同步等待结果。"""
    _ensure_mcp_loop()
    future = asyncio.run_coroutine_threadsafe(coro, _mcp_loop)
    return future.result(timeout=BROWSER_CONFIG["timeout"] + 10)


async def _connect_mcp():
    """连接 Scrapling MCP Server。"""
    global _mcp_session, _mcp_error, _mcp_ready

    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        _mcp_error = "未安装 mcp 库。修复: pip install mcp"
        return False

    if not shutil.which("npx"):
        _mcp_error = "未找到 npx 命令。需要 Node.js >= 18。"
        return False

    try:
        server_params = StdioServerParameters(
            command="npx",
            args=["-y", "@scrapling/mcp-server"],
            env={**os.environ},
        )

        # 启动 MCP Server 并建立会话
        transport = await stdio_client(server_params)
        read_stream, write_stream = transport
        _mcp_session = ClientSession(read_stream, write_stream)
        await _mcp_session.initialize()

        _mcp_ready = True
        return True

    except Exception as e:
        _mcp_error = f"MCP 连接失败: {type(e).__name__}: {e}"
        return False


def _get_session():
    """获取或初始化 MCP 会话（惰性）。"""
    global _mcp_session, _mcp_ready, _mcp_error
    with _mcp_lock:
        if _mcp_ready and _mcp_session:
            return _mcp_session
        ok = _run_async(_connect_mcp())
        if ok:
            return _mcp_session
        return None


async def _call_tool(tool_name: str, arguments: dict) -> str:
    """调用 MCP 工具并返回结果文本。"""
    session = _get_session()
    if not session:
        return f"ERROR: MCP 不可用 — {_mcp_error}"

    try:
        result = await session.call_tool(tool_name, arguments)
        # 提取文本内容
        if hasattr(result, "content"):
            parts = []
            for block in result.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
                else:
                    parts.append(str(block))
            return "\n".join(parts)
        return str(result)
    except Exception as e:
        return f"ERROR: MCP 工具调用失败 ({tool_name}): {type(e).__name__}: {e}"


def _safe_path(filename: str) -> str:
    """确保文件路径在 SAFE_WORKSPACE 内。"""
    full = os.path.abspath(os.path.join(SCREENSHOT_DIR, filename))
    if not full.startswith(os.path.abspath(SCREENSHOT_DIR)):
        raise PermissionError(f"路径越界: {filename}")
    return full


# ════════════════════════════════════════════════════════
# 工具函数
# ════════════════════════════════════════════════════════

def tool_web_fetch(a: dict) -> str:
    """
    使用 StealthyFetcher 抓取网页（默认开启反爬）。
    自动解 Cloudflare、返回 Markdown。
    """
    url = a["url"]
    timeout = int(a.get("timeout", BROWSER_CONFIG["timeout"]))
    print(c(CYAN, f"  🌐 [Scrapling/Fetch] {url[:80]}"))

    args = {
        "url": url,
        "timeout": timeout,
        "solve_cloudflare": True,
    }
    result = _run_async(_call_tool("fetch", args))
    # 编码清洗
    return result.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")


def tool_web_click(a: dict) -> str:
    """点击页面元素（自适应定位）。"""
    selector = a["selector"]
    print(c(CYAN, f"  🖱 [Scrapling/Click] {selector[:60]}"))

    args = {"selector": selector}
    result = _run_async(_call_tool("click", args))
    return result.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")


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

    args = {"path": save_path}
    result = _run_async(_call_tool("screenshot", args))

    if os.path.exists(save_path):
        size_kb = os.path.getsize(save_path) / 1024
        return f"✓ 截图已保存: {save_path} ({size_kb:.1f} KB)"
    return f"[Scrapling 返回]\n{result}"


def tool_web_select(a: dict) -> str:
    """使用自适应 CSS 选择器提取页面元素。"""
    selector = a["selector"]
    attribute = a.get("attribute", "text")
    print(c(CYAN, f"  🔍 [Scrapling/Select] {selector[:60]}"))

    args = {"selector": selector, "attribute": attribute}
    result = _run_async(_call_tool("adaptive_select", args))
    return result.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")


def tool_web_type(a: dict) -> str:
    """在表单元素中输入文本。"""
    selector = a["selector"]
    text = a["text"]
    print(c(CYAN, f"  ⌨ [Scrapling/Type] {selector[:40]} → {text[:40]}"))

    args = {"selector": selector, "text": text}
    result = _run_async(_call_tool("type", args))
    return result.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")


def tool_web_navigate(a: dict) -> str:
    """导航到指定 URL。"""
    url = a["url"]
    print(c(CYAN, f"  🧭 [Scrapling/Navigate] {url[:80]}"))

    args = {"url": url}
    result = _run_async(_call_tool("navigate", args))
    return result.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")


# ════════════════════════════════════════════════════════
# MCP 状态检测
# ════════════════════════════════════════════════════════

def browser_tool_status() -> str:
    """返回浏览器工具可用性状态。"""
    has_mcp = False
    try:
        import mcp  # noqa: F401
        has_mcp = True
    except ImportError:
        pass

    has_npx = bool(shutil.which("npx"))

    parts = [
        ("mcp 库",          has_mcp,   "pip install mcp" if not has_mcp else "已安装"),
        ("npx (Node.js)",   has_npx,   "需要 Node.js >= 18" if not has_npx else "已安装"),
        ("Scrapling MCP",   _mcp_ready,"未连接（首次使用时自动启动）" if not _mcp_ready else "已连接"),
        ("截图目录",         True,      SCREENSHOT_DIR),
    ]

    lines = []
    for name, avail, note in parts:
        tag = c(GREEN, "✓") if avail else c(GRAY, "✗")
        lines.append(f"  {tag} {name:20} {c(GRAY, note)}")

    if _mcp_error:
        lines.append(f"  {c(RED, '⚠')} {_mcp_error}")

    return "\n".join(lines)


# ════════════════════════════════════════════════════════
# Schema 定义（注册到 TOOLS_SCHEMA）
# ════════════════════════════════════════════════════════

BROWSER_SCHEMAS = [
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
