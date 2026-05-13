"""
core/persistence.py — 会话持久化对外接口
底层改为 SQLite（core/memory.py），废弃原 JSON 文件方案。
新增：memorize() — 调用 API 总结对话片段存入 knowledge 表。
"""

import json
import sys
import urllib.request, urllib.error
from config import DYNAMIC_CONFIG, DEFAULT_MODEL, MODELS, get_api_config
from core.memory import (
    init_db, upsert_session, list_sessions, get_session, delete_session,
    rename_session, save_messages, load_messages, pin_message_by_seq,
    add_knowledge, search_knowledge, format_knowledge_for_prompt, _gen_id,
)
from core.naming import stable_workspace_dir
from utils.ansi import c, CYAN, GRAY, GREEN, RED, YELLOW, BOLD, DIM

# ── 优先使用 prompt_toolkit 的渲染通道（绕过可能被接管的 stdout）──
try:
    from prompt_toolkit import print_formatted_text as _print_ptk
    from prompt_toolkit.formatted_text import ANSI as _ANSI
    _HAS_PTK = True
except Exception:
    _print_ptk = None
    _ANSI = None
    _HAS_PTK = False

# ── rich 渲染：Markdown + Panel 高保真历史回放 ────────────
try:
    from rich.console import Console as _RichConsole
    from rich.markdown import Markdown as _RichMarkdown
    from rich.panel import Panel as _RichPanel
    from rich.text import Text as _RichText
    from rich.markup import escape as _rich_escape
    _HAS_RICH = True
except Exception:
    _HAS_RICH = False
    # 兜底：rich 不可用时 escape 退化为 str 转换
    def _rich_escape(text):
        return str(text) if text is not None else ""

# ════════════════════════════════════════════════════════
# Session 保存 / 加载
# ════════════════════════════════════════════════════════

def session_save(session, name: str = "") -> str:
    """将当前 session 写入 SQLite。返回 session_id。"""
    init_db()
    manual_name = name.strip()
    upsert_session(
        session_id  = session.session_id,
        name        = manual_name,
        model       = session.model_alias,
        cwd         = session.cwd,
        config_dict = dict(DYNAMIC_CONFIG),
        workspace_dir = getattr(session, "workspace_dir", ""),
        name_source = "manual" if manual_name else "",
    )
    save_messages(session.session_id, session.messages)
    return session.session_id

def session_load(session, query: str) -> str:
    """按序号或名称子串加载会话。"""
    init_db()
    rows = list_sessions(50)
    if not rows:
        return "ERROR: 数据库中没有已保存的会话。"

    matched = _resolve_session(rows, query)
    if not matched:
        listing = "\n".join(
            f"  [{i+1}] {r['id']}  {r['name'] or r['auto_name'] or r['workspace_alias'] or '(unnamed)'}  {r['updated_at'][:16]}"
            for i, r in enumerate(rows[:10])
        )
        return f"ERROR: 找不到匹配 '{query}' 的会话。\n已有:\n{listing}"

    sid  = matched["id"]
    full = get_session(sid)
    if not full:
        return f"ERROR: session {sid} 元数据丢失"

    # 还原 messages
    msgs = load_messages(sid)
    session.messages.clear()

    # ── 模型别名归一化：若 DB 中残留已失效的旧名（如 "mimo"），
    #    降级到 DEFAULT_MODEL 并打印警告，避免下游 MODELS[...] 崩溃。──
    loaded_alias = full["model"]
    if loaded_alias in MODELS:
        session.model_alias = loaded_alias
    else:
        print(c(YELLOW,
            f"  ⚠ 会话中的模型别名 '{loaded_alias}' 已失效，"
            f"降级到默认模型 '{DEFAULT_MODEL}'"))
        session.model_alias = DEFAULT_MODEL

    session.cwd         = full["cwd"]
    session.workspace_dir = full["workspace_dir"] or stable_workspace_dir(sid)
    if not full["workspace_dir"]:
        upsert_session(
            session_id=sid,
            name="",
            model=session.model_alias,
            cwd=session.cwd,
            config_dict=dict(DYNAMIC_CONFIG),
            workspace_dir=session.workspace_dir,
        )
    try:
        cfg = json.loads(full["config"])
        DYNAMIC_CONFIG.update(cfg)
    except Exception:
        pass

    from tools.file_ops import _session_cwd, _session_workspace_dir
    _session_cwd[0] = session.cwd
    _session_workspace_dir[0] = session.workspace_dir
    session._reset_system_prompt()
    session.messages.extend(msgs)
    session.session_id = sid
    if hasattr(session, "_naming_done"):
        session._naming_done = bool(full["auto_name"])
    if hasattr(session, "_naming_attempted_at"):
        session._naming_attempted_at = 0.0

    # 显示对话历史（恢复时显示全部）— 延迟到调用方打印，避免被 prompt_toolkit 滚动覆盖

    display_name = full["name"] or full["auto_name"] or matched["name"] or sid
    return f"OK: 已加载 [{sid}] {display_name} ({len(msgs)} 条消息)"

def session_list() -> str:
    init_db()
    rows = list_sessions(20)
    if not rows:
        return "  (暂无已保存会话)"
    lines = []
    for i, r in enumerate(rows):
        display_name = r["name"] or r["auto_name"] or r["workspace_alias"] or "(unnamed)"
        lines.append(
            c(GRAY, f"  [{i+1:2d}] ") +
            c(CYAN, f"{r['id']}") +
            c(GRAY, f"  '{display_name}'  "
                    f"{r['updated_at'][:16]}  {r['msg_count']}msgs  model={r['model']}")
        )
    return "\n".join(lines)

def session_delete(session, query: str) -> str:
    rows = list_sessions(50)
    matched = _resolve_session(rows, query)
    if not matched: return f"ERROR: 找不到 '{query}'"
    delete_session(matched["id"])
    return f"OK: 已删除会话 {matched['id']}"


def _resolve_session(rows, query: str):
    """从 list_sessions 结果中按序号或名称子串查找会话。返回 Row 或 None。"""
    query = query.strip()
    try:
        idx = int(query) - 1
        if 0 <= idx < len(rows):
            return rows[idx]
    except ValueError:
        pass
    q = query.lower()
    return next(
        (r for r in rows if
         q in (r["name"] or "").lower() or
         q in (r["auto_name"] or "").lower() or
         q in (r["workspace_alias"] or "").lower() or
         q in r["id"]),
        None,
    )


def session_rename(session, query: str, new_name: str) -> str:
    """按序号或名称子串找到会话并重命名。"""
    init_db()
    rows = list_sessions(50)
    matched = _resolve_session(rows, query)
    if not matched:
        return f"ERROR: 找不到匹配 '{query}' 的会话"
    rename_session(matched["id"], new_name.strip())
    return f"OK: 已重命名 [{matched['id']}] → '{new_name.strip()}'"


def _display_session_history(msgs: list, show_recent: int = 0) -> None:
    """
    打印会话历史到终端（副作用函数，无返回值）。

    渲染通道（按优先级）：
      · rich: Markdown + Panel 高保真回放，不截断
          - user     : [bold green]▶ You > [/bold green]<content>
          - assistant: reasoning_content → Panel(title="🧠 Thinking", dim)；
                       content → Markdown 渲染
          - tool     : [yellow]└─ [tool][/yellow] 完整结果
      · prompt_toolkit (降级): ANSI 行级输出
      · print (兜底): 纯文本

    参数 show_recent:
      · 0  或 >= total → 全量显示（不截断）
      · 1..total-1    → 仅显示最新 N 条，其余折叠提示

    末尾显式 sys.stdout.flush() 强制刷新，衔接主循环"预渲染策略"。
    """
    displayable = [m for m in msgs if m.get("role") in ("user", "assistant", "tool")]
    total = len(displayable)

    if total == 0:
        print("  (空会话)")
        sys.stdout.flush()
        return

    folded = 0
    if show_recent and 0 < show_recent < total:
        folded = total - show_recent
        displayable = displayable[-show_recent:]

    if _HAS_RICH:
        _rich_render_history(displayable, total, folded)
    else:
        _fallback_render_history(displayable, total, folded)

    sys.stdout.flush()


def _rich_render_history(msgs: list, total: int, folded: int) -> None:
    """
    rich 路径：Markdown + Panel 完整渲染，不截断。

    Markup 转义策略：
      · f-string 里直接插值的用户/工具内容统一用 _rich_escape() 转义，
        避免 shell 输出的 [/path] / [^] / [tool] 被误认为关闭标签
        引发 MarkupError 崩溃。
      · 字面量 "[tool]" 需用反斜杠转义 "\\[tool\\]" 才能显示为文本。
      · Markdown / Text 构造器走独立解析路径，不重解析 rich 标签，
        无需手工 escape。
    """
    console = _RichConsole(force_terminal=True, soft_wrap=True)
    console.rule(f"[bold]对话历史 ({total} 条)[/bold]")
    if folded:
        console.print(f"[dim]... 已折叠 {folded} 条较早消息 ...[/dim]")

    for m in msgs:
        role    = m.get("role", "")
        content = m.get("content") or ""

        if role == "user":
            # 🛡 转义 content：用户输入可能含 [path] 等误伤 rich 解析器的字符
            console.print(f"[bold green]▶ You > [/bold green]{_rich_escape(content)}")

        elif role == "assistant":
            # ★ 先渲染 reasoning_content（若存在）→ 独立 Panel 折叠展示
            # _RichText 构造器不解析 markup，天然安全，无需 escape
            reasoning = m.get("reasoning_content")
            if reasoning:
                console.print(_RichPanel(
                    _RichText(str(reasoning), style="dim"),
                    title="🧠 Thinking",
                    title_align="left",
                    border_style="dim",
                ))

            tool_calls = m.get("tool_calls")
            if tool_calls and not content:
                names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
                # 🛡 转义工具名（防御性，正常函数名不含 []）
                names_safe = _rich_escape(", ".join(names))
                console.print(
                    f"[bold cyan]🤖 A:[/bold cyan] [dim]调用工具: {names_safe}[/dim]"
                )
            elif content:
                console.print("[bold cyan]🤖 A:[/bold cyan]")
                # _RichMarkdown 走独立解析路径，不重解析 rich 标签，天然安全
                try:
                    console.print(_RichMarkdown(str(content)))
                except Exception:
                    # 极端输入（未闭合 Markdown 等）→ 降级为无 markup 纯文本
                    console.print(str(content), markup=False)
            else:
                console.print("[bold cyan]🤖 A:[/bold cyan] [dim](空)[/dim]")

        elif role == "tool":
            # 🛡 **主犯修复点**：shell 工具输出最常含 [/home/...] / [~] / [^]
            # 等字符。字面量 "[tool]" 用反斜杠转义 "[" 避免被当作 rich 标签
            # （rich markup 中 "]" 不需要转义，只需转义 "["）。
            console.print(
                f"[yellow]└─ \\[tool][/yellow] {_rich_escape(content)}"
            )

    console.rule()


def _fallback_render_history(msgs: list, total: int, folded: int) -> None:
    """rich 不可用时：走 prompt_toolkit ANSI 输出（保留向后兼容）。"""
    def _emit(line: str) -> None:
        if _HAS_PTK:
            try:
                _print_ptk(_ANSI(line))
                return
            except Exception:
                pass
        print(line)

    sep = "─" * 44
    _emit(f"  ── 对话历史 ({total} 条) {sep}")
    if folded:
        _emit(f"  │ ... 已折叠 {folded} 条较早消息 ...")

    for j, m in enumerate(msgs):
        role = m.get("role", "")
        content = m.get("content") or ""
        is_last = (j == len(msgs) - 1)
        branch = "└" if is_last else "├"

        if role == "user":
            _emit(f"  {branch} [user]      {content}")
        elif role == "assistant":
            reasoning = m.get("reasoning_content")
            thinking_tag = ""
            if reasoning:
                thinking_tag = c(GRAY + DIM, f" 🧠[{len(str(reasoning))}字思考]")

            tool_calls = m.get("tool_calls")
            if tool_calls and not content:
                names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
                _emit(f"  {branch} [assistant]{thinking_tag} [调用工具: {','.join(names)}]")
            elif content:
                _emit(f"  {branch} [assistant]{thinking_tag} {content}")
            else:
                _emit(f"  {branch} [assistant]{thinking_tag} (空)")
        elif role == "tool":
            _emit(f"  {branch} [tool]      [结果] {content}")

    _emit(f"  {sep}")


# ════════════════════════════════════════════════════════
# /memorize — AI 摘要 → knowledge 表
# ════════════════════════════════════════════════════════

def memorize(session, topic: str, n_turns: int = 6) -> str:
    """
    取最近 n_turns 条 user/assistant 消息，调用 API 让模型总结，
    存入 knowledge 表。返回操作结果说明。
    """
    # 取最近若干轮对话
    relevant = [
        m for m in session.messages
        if m.get("role") in ("user", "assistant") and m.get("content")
    ][-n_turns * 2:]

    if not relevant:
        return "ERROR: 上下文中没有可供总结的对话。"

    history_text = "\n".join(
        f"[{m['role'].upper()}]: {str(m.get('content',''))[:500]}"
        for m in relevant
    )

    prompt = (
        f"以下是一段对话片段，请从中提取关于主题「{topic}」的核心知识点，"
        f"用简洁的中文（或英文，视内容而定）输出，不超过300字。\n\n"
        f"--- 对话 ---\n{history_text}\n--- 结束 ---\n\n"
        f"只输出知识内容本身，不要解释你在做什么，不要输出标题。"
    )

    base_url, api_key = get_api_config(session.model_alias)
    payload = {
        "model":      session.model["id"],
        "messages":   [{"role": "user", "content": prompt}],
        "max_tokens": 512,
        "stream":     False,
    }
    try:
        req = urllib.request.Request(
            base_url,
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data    = json.loads(resp.read())
            summary = data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"ERROR: 摘要 API 调用失败: {e}"

    # 自动提取简单 tags（取 topic 的词 + 会话 cwd 最后一节）
    tags_parts = [w.lower() for w in topic.split() if len(w) > 2]
    cwd_tag    = session.cwd.rstrip("/").split("/")[-1]
    tags       = ",".join(tags_parts + [cwd_tag])

    kid = add_knowledge(topic, summary, tags, source_session=session.session_id)
    return (
        f"OK: 知识已保存 (id={kid})\n"
        f"  topic : {topic}\n"
        f"  tags  : {tags}\n"
        f"  摘要  : {summary[:120]}{'...' if len(summary)>120 else ''}"
    )
