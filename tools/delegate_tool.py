"""
tools/delegate_tool.py — 模块 4.1：无污染子任务委派（Fresh Context）

delegate_task(task_description)：
  · 在后台实例化一个全新的 _SubAgentSession（仅含系统提示 + 当前任务）
  · 静默运行完整 Agentic Loop（工具调用照常执行，但不打印到主 stdout）
  · 捕获子 agent 的工具调用日志和最终回复，精简后返回给主 Session
  · 主 Session 上下文不增长，只获得结果摘要

避免循环导入：
  · 本模块不在顶层 import core/session.py
  · TOOL_MAP 和 TOOLS_SCHEMA 在工具被调用时通过函数懒加载
  · _sub_stream() 直接使用 core/api_client.stream_request（无 session 依赖）
"""

import sys, io, json, contextlib, threading
from datetime import datetime
from config import (
    DYNAMIC_CONFIG, DEFAULT_MODEL, MODELS, get_api_config,
)
from core.api_client import stream_request, ensure_tool_call_id
from core.memory     import _gen_id
from tools.file_ops  import _session_cwd
from utils.ansi      import c, YELLOW, GRAY, GREEN, RED, MAGENTA, BOLD

# ── 递归深度保护 ──────────────────────────────────────────
_delegate_ctx = threading.local()   # .depth 表示当前线程的委派深度
_MAX_DEPTH    = 2                   # 子 Agent 最大嵌套层数

# ════════════════════════════════════════════════════════
# 懒加载：避免与 session.py 的循环导入
# ════════════════════════════════════════════════════════

def _tool_map():
    """在调用时才导入 session.TOOL_MAP，此时循环已解开。"""
    from core.session import TOOL_MAP
    return TOOL_MAP

def _tools_schema():
    from core.session import TOOLS_SCHEMA
    return TOOLS_SCHEMA

# ════════════════════════════════════════════════════════
# 子 Agent Session（静默运行）
# ════════════════════════════════════════════════════════

class _SubAgentSession:
    """
    轻量级子 Agent，只持有 system + task 消息，不与主 Session 共享状态。
    所有工具调用效果（文件写入、shell 执行）会真实发生，但输出被捕获。
    """

    MAX_ITER = 15   # 子任务硬上限，防止无限循环

    def __init__(self, task: str, model_alias: str = DEFAULT_MODEL):
        self.session_id  = "sub_" + _gen_id()
        self.model_alias = model_alias

        # ── 继承父 Agent 的关键事实 ────────────────────────
        inherited_ctx = ""
        try:
            from core.memory import search_facts, format_facts_for_prompt
            # 取高优先级事实（priority >= 2），最多 5 条
            rows = search_facts(query="", priority_min=2, limit=5)
            if rows:
                inherited_ctx = (
                    "\n[Inherited Context from Parent Agent]\n"
                    + format_facts_for_prompt(rows, max_chars=400)
                    + "\n"
                )
        except Exception:
            inherited_ctx = ""

        self.messages: list = [
            {
                "role":    "system",
                "content": (
                    "You are a focused sub-agent executing ONE specific delegated task.\n"
                    "Complete the task thoroughly using available tools.\n"
                    f"Working directory: {_session_cwd[0]}\n"
                    f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                    f"{inherited_ctx}\n"
                    "Rules:\n"
                    "- Use tools as needed. Be thorough.\n"
                    "- When done, return a concise summary of what was accomplished.\n"
                    "- Do NOT explain your plan, just act.\n"
                    "- Do NOT call delegate_task again (no nested delegation allowed).\n"
                ),
            },
            {"role": "user", "content": task},
        ]
        self._tool_log: list[str] = []

    def run(self) -> str:
        """
        静默运行 Agentic Loop。
        标准输出被重定向，工具调用仍正常执行（副作用真实发生）。
        返回：子 agent 的最终文本回复。
        """
        tool_map    = _tool_map()
        # 物理阉割：子 Agent 不得再次委派
        tools_sch   = [s for s in _tools_schema()
                       if s.get("function", {}).get("name") != "delegate_task"]
        cap         = io.StringIO()

        for iteration in range(self.MAX_ITER):
            text_buf = ""; tc_buf: dict = {}

            # 重定向 stdout（隐藏工具调用打印）
            with contextlib.redirect_stdout(cap):
                for delta in stream_request(
                    self.messages, self.model_alias,
                    tools_schema=tools_sch,
                    max_tokens=min(DYNAMIC_CONFIG["max_tokens"], 8192),
                ):
                    if "_error" in delta:
                        return f"[Sub-agent error] {delta['_error']}"
                    choices = delta.get("choices", [])
                    if not choices:
                        continue
                    d     = choices[0].get("delta", {})
                    chunk = d.get("content") or ""
                    text_buf += chunk
                    for tcd in d.get("tool_calls", []):
                        idx = tcd.get("index", 0)
                        if idx not in tc_buf:
                            tc_buf[idx] = {
                                "id":   ensure_tool_call_id(tcd, iteration, idx),
                                "name": "",
                                "args": "",
                            }
                        fn = tcd.get("function", {})
                        tc_buf[idx]["name"] += fn.get("name", "")
                        tc_buf[idx]["args"] += fn.get("arguments", "")

            # 无工具调用 → 子任务完成
            if not tc_buf:
                return text_buf.strip() or "(sub-agent returned no output)"

            # 追加 assistant 消息
            self.messages.append({
                "role":    "assistant",
                "content": text_buf or None,
                "tool_calls": [
                    {
                        "id":       tc_buf[i]["id"],
                        "type":     "function",
                        "function": {
                            "name":      tc_buf[i]["name"],
                            "arguments": tc_buf[i]["args"],
                        },
                    }
                    for i in sorted(tc_buf)
                ],
            })

            # 执行工具
            for i in sorted(tc_buf):
                tc   = tc_buf[i]; name = tc["name"]
                try:    fn_args = json.loads(tc["args"]) if tc["args"].strip() else {}
                except: fn_args = {}

                self._tool_log.append(f"  [{iteration+1}] {name}({list(fn_args.keys())})")

                if name in tool_map:
                    result = tool_map[name](fn_args)
                else:
                    result = f"ERROR: unknown tool '{name}'"

                limit = min(DYNAMIC_CONFIG["tool_max_chars"], 6000)
                if len(result) > limit:
                    result = result[:limit//2] + "\n...[truncated]...\n" + result[-500:]

                self.messages.append({
                    "role":         "tool",
                    "tool_call_id": tc["id"],
                    "content":      result,
                })

        return f"[Sub-agent hit max_iter={self.MAX_ITER}]"

# ════════════════════════════════════════════════════════
# Tool 入口
# ════════════════════════════════════════════════════════

def tool_delegate_task(a: dict) -> str:
    """
    委派子任务工具的入口函数。
    在主 Session 内被调用，执行完整子任务后返回精简结果。
    """
    task        = a.get("task_description", "").strip()
    model_alias = a.get("model_alias", DEFAULT_MODEL)
    verbose     = bool(a.get("verbose", False))

    if not task:
        return "ERROR: task_description 不能为空"
    if model_alias not in MODELS:
        model_alias = DEFAULT_MODEL

    # ── 递归深度保护 ──────────────────────────────────────
    current_depth = getattr(_delegate_ctx, "depth", 0)
    if current_depth >= _MAX_DEPTH:
        return (
            f"ERROR: 已达最大委派深度 {_MAX_DEPTH}，拒绝嵌套委派。\n"
            f"请直接使用工具完成任务，而非再次调用 delegate_task。"
        )

    print(c(MAGENTA, f"  🤖 [Sub-agent] 启动委派任务..."))
    print(c(GRAY,    f"  任务: {task[:80]}{'...' if len(task)>80 else ''}"))
    print(c(GRAY,    f"  模型: {model_alias}  深度: {current_depth+1}/{_MAX_DEPTH}  上限: {_SubAgentSession.MAX_ITER} 轮"))

    sub    = _SubAgentSession(task, model_alias)

    _delegate_ctx.depth = current_depth + 1
    try:
        result = sub.run()
    finally:
        _delegate_ctx.depth = current_depth

    # 汇报工具调用摘要
    if sub._tool_log:
        tool_summary = "\n".join(sub._tool_log[-10:])  # 最多显示最后10条
        print(c(GRAY, f"\n  [Sub-agent 工具调用摘要]\n{tool_summary}"))

    print(c(GREEN, f"  ✓ [Sub-agent] 完成，结果长度: {len(result)} 字符"))

    if verbose:
        return (
            f"[Sub-agent 完成]\n"
            f"--- 工具调用记录 ---\n"
            f"{chr(10).join(sub._tool_log) or '(无工具调用)'}\n\n"
            f"--- 最终结果 ---\n"
            f"{result}"
        )
    else:
        return f"[Sub-agent 完成]\n{result}"

# ════════════════════════════════════════════════════════
# Schema
# ════════════════════════════════════════════════════════

DELEGATE_SCHEMA = {
    "type": "function",
    "function": {
        "name":        "delegate_task",
        "description": (
            "将复杂子任务委派给一个全新的子 Agent 执行（Fresh Context）。\n"
            "子 Agent 拥有独立的上下文，使用所有工具完成任务后只返回精简结果。\n"
            "主 Agent 的上下文不会因子任务的工具调用而膨胀。\n"
            "适用场景：大型重构的某个模块、独立的搜索+整理任务、多步骤测试流程。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_description": {
                    "type":        "string",
                    "description": "子任务的详细描述，越具体越好",
                },
                "model_alias": {
                    "type":        "string",
                    "description": "子 Agent 使用的模型（默认与主 Agent 相同）",
                },
                "verbose": {
                    "type":        "boolean",
                    "description": "True 时在结果中包含完整工具调用日志（默认 False）",
                },
            },
            "required": ["task_description"],
        },
    },
}
