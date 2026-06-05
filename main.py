#!/usr/bin/env python3
"""
PawnLogic — main.py
多 Provider · 多模态视觉 · SQLite · CoT 引导 · GSA 技能存档 · 规格驱动 · GSD架构

快速部署（WSL2 Ubuntu）:
  cp -r PawnLogic ~/.local/share/pawnlogic
  chmod +x ~/.local/share/pawnlogic/main.py
  ln -sf ~/.local/share/pawnlogic/pawn.sh ~/.local/bin/pawn
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
  source ~/.bashrc
  pawn   # 首次运行会自动进入 API Key 配置向导
"""
import os, sys, shutil, argparse, time, asyncio

# ── 退出哨兵值（handle_slash 返回此值表示用户请求退出）────
# Re-exported from core.commands._common; the new system.py /exit handler
# returns the same sentinel object so identity comparison still works.
from core.commands._common import EXIT_SENTINEL as _EXIT_SENTINEL

# ── 延迟渲染队列：/load /resume 入口主动 set，主循环在 prompt_async 前消费。
# 迁移后状态存于 core/commands/_common.py，这里仅保留函数引用。
from core.commands._common import set_deferred_history, take_deferred_history

# Provider/key helpers used by main()'s startup wizard. Their canonical
# definitions live in core/commands/provider.py (loaded eagerly by
# core.commands.__init__).
from core.commands.provider import _run_key_wizard, _visible_models

try:
    import readline  # noqa  — Windows 原生无此模块，Tab 补全见 main() 内
except ImportError:
    readline = None
from pathlib import Path

# ── P2: CLI UX — prompt_toolkit / rich 可用性检测 ────────
# 读取环境变量 PROMPT_TOOLKIT_ENABLED，0/false 时强制禁用（E2E 测试用）
_FORCE_DISABLE_PT = os.getenv("PROMPT_TOOLKIT_ENABLED", "1").lower() in ("0", "false")

_HAS_PROMPT_TOOLKIT = False
_HAS_RICH = False
_PT_IMPORT_ERROR = None
_RICH_IMPORT_ERROR = None
try:
    if _FORCE_DISABLE_PT:
        raise ImportError("Prompt toolkit disabled by PROMPT_TOOLKIT_ENABLED=0")
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.formatted_text import StyleAndTextTuples
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.styles import Style as _PTStyle
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.shortcuts import CompleteStyle
    from prompt_toolkit.patch_stdout import patch_stdout as _patch_stdout
    _HAS_PROMPT_TOOLKIT = True
except Exception as _e:
    _PT_IMPORT_ERROR = str(_e)
    PromptSession = None
    _patch_stdout = None
    # Define dummy classes to prevent NameError in class definitions below
    class Completer:
        pass
    class Completion:
        pass
    class AutoSuggestFromHistory:
        pass

try:
    from rich.console import Console as _RichConsole
    from rich.markdown import Markdown as _RichMarkdown
    from rich.theme import Theme
    _pawn_rich_theme = Theme({
        "markdown.code": "dim cyan",
        "markdown.code_block": "dim cyan",
        "markdown.link": "underline cyan",
        "markdown.link_url": "dim blue",
    })
    _rich_console = _RichConsole(
        force_terminal=True,
        highlight=True,
        theme=_pawn_rich_theme,
        soft_wrap=True,
    )
    _HAS_RICH = True
except Exception as _e:
    _RICH_IMPORT_ERROR = str(_e)
    _rich_console = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── 启动时加载 .env（必须在 import config 之前）───────────
_PAWNLOGIC_DIR = Path.home() / ".pawnlogic"
_ENV_PATH = _PAWNLOGIC_DIR / ".env"

try:
    from dotenv import load_dotenv
    if _ENV_PATH.exists():
        load_dotenv(dotenv_path=_ENV_PATH)
    else:
        print(f"\033[93m  ⚠ 警告: 未找到 {_ENV_PATH} 文件\033[0m")
except ImportError:
    print("\033[93m  ⚠ 警告: 未安装 python-dotenv！请执行 pip install python-dotenv\033[0m")

# ── 代理（最先初始化）────────────────────────────────────
import urllib.request

def _install_proxy():
    hp  = os.environ.get("HTTP_PROXY")  or os.environ.get("http_proxy")
    hsp = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if hp or hsp:
        h = {}
        if hp:  h["http"]  = hp
        if hsp: h["https"] = hsp
        urllib.request.install_opener(
            urllib.request.build_opener(urllib.request.ProxyHandler(h)))
        return hsp or hp
    return None

PROXY_STATUS = _install_proxy()

import config  # kept for backward-compat attribute access
from core.state import state as _runtime_state
from config import (
    VERSION, DYNAMIC_CONFIG,
    MODELS, DB_PATH, PROVIDERS,
    validate_api_key, list_vision_models,
)
from utils.ansi       import c, cp, rl_wrap, BOLD, GRAY, CYAN, GREEN, YELLOW, RED, MAGENTA
from core.session     import (
    AgentSession, STATE_FILENAME,
    attach_external_mcp_tools, detach_external_mcp_tools,
)
from core.memory import init_db
from core.persistence import session_load, _display_session_history
# ★ 新增：loguru 日志模块
from core.logger import logger, setup_logger

# ════════════════════════════════════════════════════════
# 模块 2：交互式 API Key 配置向导
# ════════════════════════════════════════════════════════





# ════════════════════════════════════════════════════════
# 帮助文本
# ════════════════════════════════════════════════════════

HELP_TEXT = f"""
{c(BOLD+CYAN, f"PawnLogic {VERSION} — Commands")}

{c(BOLD,"── 对话控制 ──")}
  {c(YELLOW,"/mode")}            切换 USER / DEV 输出模式
  {c(YELLOW,"/model [alias]")}   切换模型  支持: {", ".join(MODELS.keys())}
  {c(YELLOW,"/clear")}           清空上下文（保留 Pin 消息，State.md 持续注入）
  {c(YELLOW,"/context")}         上下文大小 / token 估算
  {c(YELLOW,"/pin [n]")}         从尾部固定最近 n 条（默认 2）
  {c(YELLOW,"/pin msg <n>")}     精准 Pin：按 /history 中的序号固定
  {c(YELLOW,"/unpin")}           解除所有 Pin
  {c(YELLOW,"/undo [n]")}        撤回最近 n 轮对话（默认 1）
  {c(YELLOW,"/compact")}         压缩上下文（轻量模型总结 + 清空历史）
  {c(YELLOW,"/think <prompt>")}  单次推理模式（自动切换推理 Worker）
  {c(YELLOW,"/ping")}            保活请求，刷新缓存 TTL
  {c(YELLOW,"/cd <path>")}       切换工作目录
  {c(YELLOW,"/file <path>")}     载入文件到上下文
  {c(YELLOW,"/history")}         消息历史（含序号，用于精准 Pin）

{c(BOLD,"── API Key 管理 ──")}
  {c(CYAN,"/setkey")}            重新运行 Key 配置向导
  {c(CYAN,"/keys")}              显示各 Provider Key 配置状态

{c(BOLD,"── API Provider 管理 ──")}
  {c(CYAN,"/provider")}            Provider 管理面板（查看/添加/删除/测试）
  {c(CYAN,"/provider list")}       列出所有 Provider 状态
  {c(CYAN,"/provider add")}        添加自定义 Provider（支持 OpenAI / Anthropic 格式）
  {c(CYAN,"/provider remove <n>")} 删除自定义 Provider
  {c(CYAN,"/provider test <model>")} 测试 Provider 连通性

{c(BOLD,"── 会话持久化（SQLite）──")}
  {c(CYAN,"/save [name]")}   保存当前会话 → ~/.pawnlogic/pawn.db
  {c(CYAN,"/load <name|n>")} 加载历史会话（名称子串/序号）
  {c(CYAN,"/sessions")}      列出所有会话
  {c(CYAN,"/del <name|n>")}  删除指定会话
  {c(CYAN,"/rename <n> <name>")} 重命名已保存会话
  {c(CYAN,"/resume [n]")}    恢复会话并显示对话历史

{c(BOLD,"── 知识库 RAG ──")}
  {c(MAGENTA,"/memorize [topic]")}   AI 总结对话 → 存入知识库（每次新 session 自动召回）
  {c(MAGENTA,"/knowledge [query]")}  搜索/列出知识条目
  {c(MAGENTA,"/forget <id>")}        删除指定知识条目

{c(BOLD,"── 技能包管理 ──")}
  {c(CYAN,"/skillpack [/sp]")}    列出本地技能包（skills/ 目录）
  {c(CYAN,"/sp rescan")}          重新扫描 skills/ 目录
  {c(CYAN,"/sp sync")}            同步所有带 .git 的技能包（git pull）
  {c(CYAN,"/sp install <url>")}   从远程仓库安装新技能包
  {c(CYAN,"/sp <名称>")}          查看指定技能包详情
  {c(CYAN,"/skills")}             查看全局技能存档（GSA）

{c(BOLD,"── 项目状态（GSD）──")}
  {c(YELLOW,"/init_project [desc]")} 在当前目录生成 .pawn_state.md（项目大目标）
  {c(YELLOW,"/state")}               查看当前目录的 .pawn_state.md

{c(BOLD,"── 四档预设 ──")}
  {c(GREEN,  "/low")}     日常/算法 · tokens=4k  ctx=40k  iter=10
  {c(YELLOW, "/mid")}     开发/Pwn  · tokens=8k  ctx=150k iter=30  ← 默认
  {c(MAGENTA,"/deep")}    全火力    · tokens=32k ctx=400k iter=50
  {c(RED,    "/max")}     极限火力  · tokens=32k ctx=600k iter=100 60min
  {c(GRAY,   "/normal")}  重置到 /mid

{c(BOLD,"── 细粒度调节 ──")}
  {c(YELLOW,"/tokens /ctx /iter /toolsize /fetchsize <n>")}
  {c(YELLOW,"/limits")}  查看所有当前限制
  {c(YELLOW,"/worker [alias|auto]")}  子任务 Worker 模型选择
  {c(YELLOW,"/time [秒数]")}  时间预算（CTF 倒计时）

{c(BOLD,"── 工具状态 ──")}
  {c(YELLOW,"/webstatus")}  Jina / Pandoc / Lynx 状态
  {c(YELLOW,"/browserstatus")}  Scrapling 浏览器工具状态
  {c(YELLOW,"/pwnenv")}     CTF 工具链完整性
  {c(YELLOW,"/docker")}     Docker 容器状态 / 镜像 / 容器管理

{c(BOLD,"── 用量审计 ──")}
  {c(CYAN,"/stats")}        本次会话 Token 用量 & 工具调用统计
  {c(CYAN,"/failures [N]")}  查看失败记录（防御性审计数据库）
  {c(CYAN,"/failures clear")} 清空所有失败记录

{c(BOLD,"── 对话历史浏览（新）──")}
  {c(CYAN,"/chat list [n]")}       列出最近 n 个会话（默认20）
  {c(CYAN,"/chat view <id|n>")}    查看某个会话的完整对话内容
  {c(CYAN,"/chat export <id|n> [文件路径]")}  导出对话为 Markdown 文件
  {c(CYAN,"/chat find <关键词>")}  跨所有会话全文搜索内容
  {c(CYAN,"/chat tag <id|n> <标签>")}   给会话打标签（逗号分隔）
  {c(CYAN,"/chat untag <id|n> <标签>")} 移除会话标签
  {c(CYAN,"/chat bytag <标签>")}   按标签筛选会话
  {c(CYAN,"/chat link <id1> <id2> [备注]")}  关联两个会话
  {c(CYAN,"/chat unlink <id1> <id2>")}  取消关联
  {c(CYAN,"/chat related <id|n>")} 查看与指定会话相关联的所有会话

{c(BOLD,"── Workspace 维护 ──")}
  {c(CYAN,"/workspace status")}             查看 workspace 概览（大小/文件数/DB 一致性）
  {c(CYAN,"/workspace cleanup")}            生成清理清单（=plan，只读 + 自动备份）
  {c(CYAN,"/workspace cleanup execute")}    按清单归档 + DB workspace_dir 补写
  {c(CYAN,"/workspace cleanup restore")}    从最近 tar 备份回滚整个 workspace
  
{c(BOLD,"── 典型任务 ──")}
  # 视觉：直接告知图片路径
  分析截图 ./screenshot.png，提取其中的代码并修复 bug

  # 委派子任务（Fresh Context）
  用 delegate_task 独立完成：搜索 asyncio 文档，整理为 ./notes/asyncio.md

  # Pwn + GDB 动态调试
  分析 ./challenge，用 pwn_debug 在 main 断点查看寄存器状态

  # 项目全流程（GSD）
  /init_project 实现一个命令行 JSON 美化工具
  → Agent 自动 plan → write → verify → git commit

  {c(YELLOW,"/exit")}  退出
"""


# ════════════════════════════════════════════════════════
# 模块 4.4：/init_project 命令实现
# ════════════════════════════════════════════════════════





# ════════════════════════════════════════════════════════
# GSA 辅助：/memo 存档逻辑
# ════════════════════════════════════════════════════════







# ════════════════════════════════════════════════════════
# /provider 命令处理
# ════════════════════════════════════════════════════════




















# ════════════════════════════════════════════════════════
# Slash 命令
# ════════════════════════════════════════════════════════

async def handle_slash(cmd: str, session: AgentSession):
    """Thin entry shell. Parses the raw line into a CommandContext and
    forwards to the dispatcher in core.commands.
    """
    from core.commands import CommandContext, dispatch
    parts = cmd.strip().split(None, 2)
    ctx = CommandContext(
        verb = parts[0].lower(),
        arg  = parts[1].strip() if len(parts) > 1 else "",
        arg2 = parts[2].strip() if len(parts) > 2 else "",
        session = session,
    )
    return await dispatch(ctx)





# ════════════════════════════════════════════════════════
# main
# ════════════════════════════════════════════════════════

def _safe_write_history(path: str) -> None:
    """安全写入 readline 历史文件。"""
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        readline.write_history_file(path)
    except Exception:
        pass


# ════════════════════════════════════════════════════════
# P2.6: CC 风格内联模型选择器（替代 radiolist_dialog）
# ════════════════════════════════════════════════════════



# ════════════════════════════════════════════════════════
# P2: rich Markdown 渲染器（供 session.py 调用）
# ════════════════════════════════════════════════════════

def render_agent_output(text: str) -> None:
    """
    渲染 Agent 的文本输出。
    · rich 可用时：检测 Markdown 结构（代码块、表格、粗体）并渲染
    · rich 不可用时：直接 print
    """
    if not _HAS_RICH or not text.strip():
        print(text)
        return

    # 检测是否包含 Markdown 结构
    _md_indicators = ("```", "**", "| ", "## ", "- ", "1. ", "> ", "---", "===", "~~")
    has_md = any(indicator in text for indicator in _md_indicators)

    if has_md:
        try:
            _rich_console.print(_RichMarkdown(text, code_theme="monokai"))
            return
        except Exception:
            pass  # 渲染失败降级

    print(text)


# ════════════════════════════════════════════════════════
# P2.6.4: PawnCompleter — 内置模糊匹配，彻底不依赖 FuzzyCompleter
#
# 根因修复：FuzzyCompleter 内部用 get_word_before_cursor() 取模式串，
# '/' 属于非词字符，退格到 '/' 时返回 ""，重新计算 start_position=0
# 与内层 start_position=-N 冲突 → 菜单消失。
# 解法：自己做模糊匹配 + 自己做高亮，完全绕开 FuzzyCompleter。
# ════════════════════════════════════════════════════════

def _pawn_fuzzy_match(query: str, candidate: str):
    """
    子序列模糊匹配（大小写不敏感）。
    返回 (matched: bool, hit_indices: list[int])
    hit_indices 是 candidate 中被匹配到的字符位置，用于高亮。
    """
    q, c = query.lower(), candidate.lower()
    indices: list[int] = []
    ci = 0
    for qc in q:
        while ci < len(c) and c[ci] != qc:
            ci += 1
        if ci >= len(c):
            return False, []
        indices.append(ci)
        ci += 1
    return True, indices


class PawnCompleter(Completer):
    """
    PawnLogic 自定义补全器（内置模糊匹配版）。

    · 输入以 / 开头 → 始终激活，退格到单个 '/' 也不消失
    · 模糊匹配：'/mdl' 能命中 '/model'，'/model d' 能命中 '/model ds-chat'
    · start_position 始终为 -len(text)，替换整行输入，绝无冲突
    · display 高亮命中字符（荧光绿），display_meta 保留右侧灰色描述
    · 无需 FuzzyCompleter 包装
    """

    def __init__(self, words: list[str], meta_dict: dict[str, str] | None = None):
        self.words    = words
        self.meta_dict = meta_dict or {}

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # 只处理以 / 开头的输入；普通文本不触发命令补全
        if not text.startswith("/"):
            return

        results: list[tuple[bool, list[int], str]] = []  # (exact_prefix, indices, word)

        for word in self.words:
            matched, indices = _pawn_fuzzy_match(text, word)
            if not matched:
                continue
            # 精确前缀匹配优先排在前面
            exact = word.startswith(text)
            results.append((exact, indices, word))

        # 精确前缀 → 模糊匹配；同级按字典序
        results.sort(key=lambda t: (not t[0], t[2]))

        for _, indices, word in results:
            # 构建高亮 display：命中字符荧光绿，其余默认色
            index_set = set(indices)
            display: StyleAndTextTuples = [
                (
                    "class:completion-menu.completion.character-match" if i in index_set else "",
                    ch,
                )
                for i, ch in enumerate(word)
            ]

            yield Completion(
                word,
                start_position=-len(text),   # 替换整行 / 开头的内容
                display=display,
                display_meta=self.meta_dict.get(word, ""),
            )


# ════════════════════════════════════════════════════════
# 首次运行向导
# ════════════════════════════════════════════════════════

def _has_any_api_key() -> bool:
    """检查是否至少有一个可用的 API Key。"""
    return any(os.getenv(p["api_key_env"], "") for p in PROVIDERS.values())




def first_run_wizard() -> None:
    """
    首次运行配置向导。
    当 .env 不存在或没有任何可用 API Key 时自动触发。
    引导用户选择 API 格式、填入 URL 和 Key，写入 .env 和 custom_providers.json。
    """
    from config.providers import save_custom_provider

    print("\n" + "═" * 56)
    print("  欢迎使用 PawnLogic！检测到尚未配置任何 API。")
    print("  首次运行需要配置一个 AI 接口，仅需 1 分钟。")
    print("═" * 56 + "\n")

    print("第一步：选择 API 格式")
    print("  1. OpenAI 兼容格式（DeepSeek / Qwen / Ollama 等大多数服务）")
    print("  2. Anthropic 原生格式（仅限 Claude 官方 API）\n")

    while True:
        fmt = input("请输入 1 或 2（默认 1）：").strip() or "1"
        if fmt in ("1", "2"):
            break
        print("  请输入 1 或 2")

    api_format = "openai" if fmt == "1" else "anthropic"

    default_urls = {
        "openai": "https://api.deepseek.com/v1/chat/completions",
        "anthropic": "https://api.anthropic.com/v1/messages",
    }
    default_models = {
        "openai": "deepseek-chat",
        "anthropic": "claude-sonnet-4-6",
    }

    print(f"\n第二步：填入接口信息（{api_format.upper()} 格式）")
    default_url = default_urls[api_format]
    base_url = input(f"  API Base URL\n  直接回车使用默认：{default_url}\n  > ").strip()
    if not base_url:
        base_url = default_url

    api_key = ""
    while not api_key:
        api_key = input("\n  API Key（必填）：").strip()
        if not api_key:
            print("  API Key 不能为空")

    default_model = default_models[api_format]
    model_id = input(
        f"\n  模型 ID（直接回车使用默认：{default_model}）：\n  > "
    ).strip() or default_model

    alias = ""
    while not alias:
        alias = input(
            "\n  给这个模型起个别名（如 my-claude / my-deepseek）：\n  > "
        ).strip()
        if not alias:
            print("  别名不能为空")

    # 写入 .env（追加模式，避免覆盖已有内容）
    env_key = f"{alias.upper().replace('-', '_').replace(' ', '_')}_API_KEY"
    env_path = _ENV_PATH
    _PAWNLOGIC_DIR.mkdir(parents=True, exist_ok=True)
    with open(env_path, "a", encoding="utf-8") as f:
        f.write(f"\n# 由首次运行向导自动生成\n{env_key}={api_key}\n")

    # 写入 custom_providers.json（结构配置，不含 Key）
    save_custom_provider(
        name=alias,
        prov_cfg={
            "base_url": base_url,
            "api_key_env": env_key,
            "label": alias,
            "api_format": api_format,
        },
        models_cfg={
            alias: {
                "id": model_id,
                "provider": alias,
                "desc": f"用户配置 ({api_format})",
                "color": "\033[37m",
                "vision": False,
            }
        },
    )

    # 重新加载 .env，让当前进程能立即使用新 Key
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=True)
    except ImportError:
        os.environ[env_key] = api_key

    print(f"\n✓ 配置完成！")
    print(f"  模型别名：{alias}")
    print(f"  启动后使用 /model {alias} 确认切换\n")
    print("═" * 56 + "\n")


# ════════════════════════════════════════════════════════
# Stage-2: --eval single-shot execution mode
# ════════════════════════════════════════════════════════

async def _run_eval_mode(session: AgentSession, args, sink) -> None:
    """Single-shot run: execute one prompt and exit.

    Behavior:
      · If `--session <id>` is given, load that session first; on failure
        emit a structured error and exit non-zero.
      · Run `session.run_turn(args.eval)`. In human (default) mode, the
        agent's streaming output flows directly to stdout exactly as it
        would in the REPL.
      · In JSON mode the streaming output is captured (so the JSON wire
        stays clean), and a single structured `result` event is emitted
        from the final assistant message in `session.messages`.
      · Always shut down MCP subprocesses on exit.
    """
    is_json = bool(args.json)

    # 1. Optionally load a saved session before running.
    if args.session:
        result = session_load(session, args.session)
        if not result.startswith("OK"):
            if is_json:
                sink.print_json({
                    "type":  "error",
                    "stage": "session_load",
                    "query": args.session,
                    "detail": result,
                })
            else:
                sink.print(c(RED, f"  ✗ 会话加载失败: {result}"))
            detach_external_mcp_tools()
            sys.exit(2)

    # 2. Execute one turn.
    if is_json:
        # Suppress streaming prints so the JSON wire stays valid;
        # we re-emit the final assistant text as a structured event.
        import contextlib
        import io
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                session.run_turn(args.eval)
        except Exception as exc:  # noqa: BLE001
            sink.print_json({
                "type":   "error",
                "stage":  "run_turn",
                "detail": str(exc),
            })
            detach_external_mcp_tools()
            sys.exit(1)

        last_assistant = next(
            (m.get("content", "") for m in reversed(session.messages)
             if m.get("role") == "assistant" and m.get("content")),
            "",
        )
        sink.print_json({
            "type":         "result",
            "prompt":       args.eval,
            "response":     last_assistant,
            "session_id":   session.session_id,
            "model":        session.model_alias,
            "prompt_tokens":     session.total_prompt_tokens,
            "completion_tokens": session.total_completion_tokens,
            "tool_calls":        session.total_tool_calls,
        })
    else:
        # Human mode — let run_turn print directly, exactly as in the REPL.
        try:
            session.run_turn(args.eval)
        except Exception as exc:  # noqa: BLE001
            sink.print(c(RED, f"  ✗ {exc}"))
            detach_external_mcp_tools()
            sys.exit(1)

    # 3. Clean shutdown of MCP subprocesses.
    detach_external_mcp_tools()
    sys.exit(0)


async def main():
    prompt_toolkit_enabled = _HAS_PROMPT_TOOLKIT
    # ── CLI 参数解析 ─────────────────────────────────────
    parser = argparse.ArgumentParser(
        prog="pawn",
        description="PawnLogic — AI Agent Terminal",
        add_help=True,
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        default=False,
        help="Quiet mode: suppress banner and decorative output.",
    )
    parser.add_argument(
        "--model", "-m",
        metavar="ALIAS",
        default=None,
        help="Start with a specific model alias (e.g. --model ds-chat).",
    )
    parser.add_argument(
        "--eval", "-e",
        metavar="PROMPT",
        help="Run a single prompt and exit (non-interactive).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON (use with --eval or query commands).",
    )
    parser.add_argument(
        "--session", "-s",
        metavar="ID",
        help="Resume a specific session by ID (use with --eval).",
    )
    args, _ = parser.parse_known_args()
    config.QUIET_MODE = args.quiet  # mutate the single canonical flag in config
    _runtime_state.quiet_mode = args.quiet  # sync to state

    # ── 输出 sink（阶段 2 接入点）──────────────────
    # 选择人读 / JSON 输出。同时写入进程级单例，以便 dispatch()
    # 在 ctx.sink 未填时自动注入。
    from core.output import HumanSink, JsonSink
    from core.commands._common import set_active_sink
    sink = JsonSink() if args.json else HumanSink()
    set_active_sink(sink)

    # ★ 初始化 loguru 双端输出
    # · QUIET_MODE 下终端只输出 WARNING 及以上，减少干扰
    # · --json 模式下同样强制 WARNING，避免 INFO/DEBUG 混入 NDJSON 消费者
    # · 文件始终记录 DEBUG 级别，保留完整诊断信息
    setup_logger(
        stderr_level=(
            "WARNING"
            if (args.json or _runtime_state.quiet_mode or _runtime_state.user_mode)
            else "INFO"
        ),
        file_level="DEBUG",
    )
    logger.info(
        "PawnLogic {} starting | model={} quiet={}",
        config.VERSION,
        args.model or config.DEFAULT_MODEL,
        _runtime_state.quiet_mode,
    )

    # 确保运行时数据目录存在（开源友好：基于 Path.home()，无硬路径）
    _PAWNLOGIC_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    attach_external_mcp_tools()
    # Sync custom providers/models into memory on every startup
    from config.providers import load_custom_providers as _lcp
    _lcp()

    # ── 首次运行向导（新）────────────────────────────────
    if not _ENV_PATH.exists() or not _has_any_api_key():
        from core.state import state as _st
        _st.is_first_run = True
        first_run_wizard()
        from config.providers import load_custom_providers
        load_custom_providers()

    # ── 模块 2：无 Key 时进入配置向导 ────────────────────
    any_key = any(
        os.environ.get(p["api_key_env"], "")
        not in ("", "YOUR_API_KEY_HERE")
        for p in PROVIDERS.values()
        if p.get("api_key_env")
    )
    if not any_key:
        configured = _run_key_wizard()
        if not configured:
            print(c(YELLOW,
                "\n  没有配置 Key，Agent 将无法调用 API。\n"
                "  你仍可用 /setkey 随时配置，或手动 export KEY=sk-...\n"
            ))

    session = AgentSession()

    # Apply --model startup flag
    if args.model:
        if args.model in MODELS:
            session.model_alias = args.model
        else:
            print(c(YELLOW, f"  ⚠ --model '{args.model}' 未知，使用默认模型"))

    # ── --eval / --session 单次执行模式（阶段 2 步骤 3）──────────────
    # 这里在 banner / wizard 之前拦截，避免装饰性输出污染 JSON 流。
    if args.eval:
        await _run_eval_mode(session, args, sink)
        return


    # 启动时工具可用性检测
    BIN_TOOLS = ["gcc","g++","gdb","node","ROPgadget","checksec","objdump","pandoc"]
    tool_tags = [c(GREEN, t) if shutil.which(t) else c(GRAY, f"{t}?") for t in BIN_TOOLS]

    proxy_line = (c(GREEN, f"  proxy : {PROXY_STATUS}") if PROXY_STATUS
                  else c(GRAY, "  proxy : 未设置"))

    key_ok, key_env = validate_api_key(session.model_alias)
    key_line = (c(GREEN,  f"  key   : {key_env} ✓")
                if key_ok else c(RED, f"  key   : {key_env} 未配置  ← /setkey 配置"))

    state_exists = (Path(session.cwd) / STATE_FILENAME).exists()
    state_line   = (c(GREEN, f"  state : {STATE_FILENAME} 已检测，目标已注入 ✓")
                    if state_exists else
                    c(GRAY,  f"  state : 无 {STATE_FILENAME}（/init_project 创建）"))

    vision_models = list_vision_models()
    vision_line   = c(
        GREEN if any(validate_api_key(m)[0] for m in vision_models) else GRAY,
        f"  vision: {', '.join(vision_models)}"
        + (" ✓" if any(validate_api_key(m)[0] for m in vision_models) else "  (需配置 Key)")
    )

    if not _runtime_state.quiet_mode:
        print(f"""
{c(BOLD+CYAN,"╔══════════════════════════════════════════════════════╗")}
{c(BOLD+CYAN,"║")}  {c(BOLD,f"PawnLogic {VERSION}")}  {c(GRAY,"· Plan · Vision · GSD · SQLite")}   {c(BOLD+CYAN,"║")}
{c(BOLD+CYAN,"║")}  {c(GRAY,"多模态 · 规格驱动 · 原子提交 · State.md · RAG")}  {c(BOLD+CYAN,"║")}
{c(BOLD+CYAN,"╚══════════════════════════════════════════════════════╝")}
  模型  : {c(MODELS[session.model_alias]['color'],session.model_alias)}  {c(GRAY,MODELS[session.model_alias]['desc'])}
  目录  : {c(GRAY,session.cwd)}
  档位  : {c(YELLOW,"[MID]")}  tokens={DYNAMIC_CONFIG['max_tokens']}  ctx={DYNAMIC_CONFIG['ctx_max_chars']//1000}k  iter={DYNAMIC_CONFIG['max_iter']}
  工具  : {"  ".join(tool_tags)}
  DB    : {c(GRAY,str(DB_PATH))}
{key_line}
{vision_line}
{state_line}
{proxy_line}
  {c(YELLOW,'/help')} 命令  {c(GREEN,'/low')} {c(YELLOW,'/mid')} {c(MAGENTA,'/deep')} {c(RED,'/max')}  {c(CYAN,'/save /load')}  {c(MAGENTA,'/memorize')}  {c(YELLOW,'/init_project')}
""")
    else:
        key_sym = "✓" if key_ok else "✗"
        prx_sym = f" proxy={PROXY_STATUS}" if PROXY_STATUS else ""
        print(c(GRAY, f"PawnLogic {VERSION}  model={session.model_alias}  key{key_sym}{prx_sym}  /help"))

    # ════════════════════════════════════════════════════════
    # 启动时会话恢复提示
    # ════════════════════════════════════════════════════════
    _startup_resume_done = False
    try:
        from core.memory import list_sessions as _list_sessions_startup
        _recent_sessions = _list_sessions_startup(5)
        if _recent_sessions:
            print(c(BOLD, "\n  最近会话："))
            for _i, _r in enumerate(_recent_sessions):
                _name = _r["name"] or "(未命名)"
                _ts   = str(_r["updated_at"])[:16] if _r["updated_at"] else ""
                _msgs = _r["msg_count"] if _r["msg_count"] else 0
                _model = _r["model"] if _r["model"] else ""
                print(
                    c(GRAY, f"  [{_i+1}] ") +
                    c(CYAN, _name) +
                    c(GRAY, f"  {_ts}  {_msgs}条  model={_model}")
                )
            print(c(GRAY, "  [Enter] 开始新会话"))
            try:
                _resume_choice = input(cp(BOLD, "  恢复会话 [1-5/Enter]: ")).strip()
                if _resume_choice.isdigit():
                    _idx = int(_resume_choice) - 1
                    if 0 <= _idx < len(_recent_sessions):
                        _sid = _recent_sessions[_idx]["id"]
                        _result = session_load(session, str(_idx + 1))
                        if _result.startswith("OK"):
                            print(c(GREEN, f"  ✓ {_result}"))
                            set_deferred_history(session.messages)
                            _startup_resume_done = True
                        else:
                            print(c(RED, f"  ✗ {_result}"))
                    else:
                        print(c(YELLOW, "  序号超出范围，开始新会话"))
                # Enter 或其他输入 → 新会话
            except (EOFError, KeyboardInterrupt):
                pass
    except Exception:
        pass

    # ════════════════════════════════════════════════════════
    # P2: CLI UX — FuzzyCompleter + WordCompleter + Bottom Toolbar
    # ════════════════════════════════════════════════════════

    # ── 扁平命令列表 + 右侧灰色说明 ──────────────────────
    _all_cmd_words = [
        "/mode", "/model", "/clear", "/context", "/pin", "/unpin", "/cd", "/file",
        "/undo", "/compact", "/think", "/ping",
        "/history", "/setkey", "/keys", "/save", "/load", "/resume", "/sessions", "/del",
        "/memorize", "/knowledge", "/forget", "/init_project", "/state",
        "/low", "/mid", "/deep", "/max", "/normal", "/limits",
        "/tokens", "/ctx", "/iter", "/toolsize", "/fetchsize",
        "/webstatus", "/browserstatus", "/pwnenv", "/stats", "/time", "/docker",
        "/worker", "/failures", "/memo", "/skills", "/skillpack", "/sp",
        "/chat", "/help", "/exit",
    ]

    _cmd_meta = {
        "/mode":          "切换 USER / DEV 输出模式",
        "/model":         "切换 AI 模型（/model ds-r1）",
        "/clear":         "清空上下文（保留 Pin 消息）",
        "/context":       "查看上下文大小 / token 估算",
        "/pin":           "固定最近 N 条消息（/pin msg 5 按序号）",
        "/unpin":         "解除所有 Pin",
        "/undo":          "撤回最近 N 轮对话（默认 1）",
        "/compact":       "压缩上下文（轻量模型总结 + 清空历史）",
        "/think":         "单次推理模式（/think <prompt>）",
        "/ping":          "保活请求，刷新缓存 TTL",
        "/cd":            "切换工作目录",
        "/file":          "载入文件到上下文",
        "/history":       "查看带序号的消息历史",
        "/setkey":        "重新运行 API Key 配置向导",
        "/keys":          "显示各厂商 Key 配置状态",
        "/save":          "保存当前会话到 SQLite",
        "/load":          "加载历史会话",
        "/resume":        "恢复最近会话（交互选择或 /resume n）",
        "/sessions":      "列出所有已保存会话",
        "/del":           "删除指定会话",
        "/memorize":      "AI 总结对话 → 存入知识库",
        "/knowledge":     "搜索 / 列出知识条目",
        "/forget":        "删除指定知识条目",
        "/init_project":  "初始化 .pawn_state.md 项目状态",
        "/state":         "查看当前项目 .pawn_state.md",
        "/low":           "日常模式（tokens=4k, ctx=40k）",
        "/mid":           "开发模式（tokens=8k, ctx=150k）← 默认",
        "/deep":          "全火力模式（tokens=32k, ctx=400k）",
        "/max":           "极限火力模式（tokens=32k, ctx=600k, iter=100, 60min）",
        "/normal":        "重置到 /mid",
        "/limits":        "查看所有运行时限制",
        "/tokens":        "设置 max_tokens",
        "/ctx":           "设置上下文上限",
        "/iter":          "设置最大迭代轮次",
        "/toolsize":      "设置工具输出截断大小",
        "/fetchsize":     "设置网页抓取截断大小",
        "/webstatus":     "Jina / Pandoc / Lynx 工具状态",
        "/browserstatus": "Scrapling 浏览器工具状态",
        "/pwnenv":        "CTF/Pwn 工具链完整性检查",
        "/stats":         "本次会话 Token 用量统计",
        "/time":          "时间预算（/time 300 = 5 分钟）",
        "/docker":        "Docker 容器管理（status/images/ps/pull）",
        "/worker":        "子任务 Worker 模型选择",
        "/failures":      "查看 / 清空失败记录",
        "/memo":          "手动存档技能到 GSA",
        "/skills":        "查看全局技能存档目录",
        "/skillpack":     "管理本地技能包（list/rescan/详情）",
        "/sp":            "/skillpack 简写",
        "/chat":          "会话浏览器（list/view/find/tag/link）",
        "/workspace":     "Workspace 维护工具（status/cleanup）",
        "/help":          "显示帮助",
        "/exit":          "退出 PawnLogic",
    }

    # 合并一级命令 + 模型别名（仅已配置 Key 的模型）+ 子命令
    _all_words = list(_all_cmd_words)
    _all_meta  = dict(_cmd_meta)
    for _alias, _minfo in _visible_models().items():
        _w = f"/model {_alias}"
        _all_words.append(_w)
        _all_meta[_w] = _minfo.get("desc", "")
    # 常用子命令
    for _sub in ("list", "view", "export", "find", "tag", "untag",
                 "bytag", "link", "unlink", "related"):
        _w = f"/chat {_sub}"
        _all_words.append(_w)
        _all_meta[_w] = f"会话 {_sub}"
    for _sub in ("clear", "list"):
        _w = f"/failures {_sub}"
        _all_words.append(_w)
        _all_meta[_w] = f"失败记录 {_sub}"
    _all_words.extend(["/worker auto", "/skills view", "/skills path", "/skills packs",
                       "/skillpack list", "/skillpack rescan", "/sp list", "/sp rescan",
                       "/sp sync", "/sp install",
                       "/workspace status", "/workspace cleanup",
                       "/workspace cleanup plan", "/workspace cleanup execute",
                       "/workspace cleanup restore"])
    _all_meta["/worker auto"] = "恢复自动路由"
    _all_meta["/skills view"] = "查看完整技能文件"
    _all_meta["/skills path"] = "显示技能文件路径"
    _all_meta["/skills packs"] = "列出本地技能包（skills/ 目录）"
    _all_meta["/skillpack list"] = "列出所有本地技能包"
    _all_meta["/skillpack rescan"] = "重新扫描 skills/ 目录"
    _all_meta["/sp list"] = "列出所有本地技能包"
    _all_meta["/sp rescan"] = "重新扫描 skills/ 目录"
    _all_meta["/sp sync"] = "同步所有带 .git 的技能包（git pull）"
    _all_meta["/sp install"] = "从远程仓库安装新技能包"
    _all_meta["/workspace status"]            = "查看 workspace 概览"
    _all_meta["/workspace cleanup"]           = "生成清理清单（plan）"
    _all_meta["/workspace cleanup plan"]      = "Phase 0+1: 备份+扫描，输出清单"
    _all_meta["/workspace cleanup execute"]   = "Phase 2+3: 按清单归档+DB同步"
    _all_meta["/workspace cleanup restore"]   = "从最近 tar 备份回滚 workspace"
    # Docker 子命令
    for _sub, _desc in [
        ("status", "查看 Docker 连接状态"),
        ("images", "列出本地 Docker 镜像"),
        ("ps",     "查看当前运行中的沙箱容器"),
        ("pull",   "从注册表拉取预设的 Pwn/环境镜像"),
        ("clean",  "清理停止的容器和悬空镜像"),
    ]:
        _w = f"/docker {_sub}"
        _all_words.append(_w)
        _all_meta[_w] = _desc
    # Provider 子命令
    for _sub, _desc in [
        ("list",   "列出所有 Provider 状态"),
        ("add",    "注册自定义 Provider（交互式或 add <alias> <url> <KEY> [anthropic]）"),
        ("fetch",  "自动嗅探并注册 Provider 的所有模型（交互多选）"),
        ("update", "重新拉取并更新已注册 Provider 的模型列表"),
        ("remove", "删除自定义 Provider"),
        ("test",   "测试 Provider 连通性"),
    ]:
        _w = f"/provider {_sub}"
        _all_words.append(_w)
        _all_meta[_w] = _desc

    # ── readline 历史文件路径 ─────────────────────────────
    _history_path = str(Path.home() / ".pawnlogic" / ".input_history")

    if prompt_toolkit_enabled:
        # ── 直接使用 PawnCompleter，内置模糊匹配，无需 FuzzyCompleter ──
        _pawn_completer = PawnCompleter(_all_words, meta_dict=_all_meta)

        try:
            _pt_history = FileHistory(_history_path)
        except Exception:
            from prompt_toolkit.history import InMemoryHistory
            _pt_history = InMemoryHistory()

        # ── Bottom Toolbar：显示当前模型 / 档位 / 目录 / Token / Ctx% ────
        def _bottom_toolbar():
            _m = session.model_alias
            _tier = "MID"
            if DYNAMIC_CONFIG["max_tokens"] <= 4096:
                _tier = "LOW"
            elif DYNAMIC_CONFIG["max_iter"] >= 100:
                _tier = "MAX"
            elif DYNAMIC_CONFIG["max_tokens"] >= 32768:
                _tier = "DEEP"
            _tb = DYNAMIC_CONFIG.get("time_budget_sec", 0)
            _time_str = f"  ⏱ {_tb}s" if _tb > 0 else ""
            # ★ Token 计数 + Ctx% 带颜色阈值
            _tk = session.total_prompt_tokens + session.total_completion_tokens
            _ctx_used = sum(len(str(m.get("content", ""))) for m in session.messages)
            _ctx_max = DYNAMIC_CONFIG["ctx_max_chars"]
            _ctx_pct = min(100, int(_ctx_used * 100 / _ctx_max)) if _ctx_max else 0
            if _ctx_pct >= 90:
                _ctx_color = "ansired"
            elif _ctx_pct >= 70:
                _ctx_color = "ansiyellow"
            else:
                _ctx_color = "ansigreen"
            return HTML(
                f" <b>Model:</b> {_m}"
                f"  <b>Tier:</b> {_tier}"
                f"  <b>Tk:</b> {_tk:,}"
                f"  <b>Ctx:</b> <{_ctx_color}>{_ctx_pct}%</{_ctx_color}>"
                f"  <b>Dir:</b> {session.cwd}"
                f"  <b>Phase:</b> {session.current_phase}"
                f"{_time_str}"
            )

        # ── 样式：彻底透明化，无灰色方块 ──────────────────
        _pawn_style = _PTStyle.from_dict({
            "prompt": "ansigreen bold",
            "you": "bold",
            "completion-menu": "bg:default fg:#bbbbbb",
            "completion-menu.completion": "bg:default fg:#bbbbbb",
            "completion-menu.meta.completion": "bg:default fg:#666666",
            "completion-menu.completion.current": "bg:#333333 fg:#ffffff",
            "completion-menu.meta.completion.current": "bg:#333333 fg:#aaaaaa",
            "completion-menu.completion.character-match": "fg:#00d787 bold",
            "scrollbar.background": "bg:default",
            "scrollbar.button": "bg:default",
            "bottom-toolbar": "bg:#222222 fg:#cccccc",
        })

        # ── 新增：拦截退格键，突破框架限制，强制触发补全 ───────────
        from prompt_toolkit.key_binding import KeyBindings
        _kb = KeyBindings()

        @_kb.add('backspace')
        @_kb.add('c-h')  # 兼容部分 Linux 终端的退格键值
        def _(event):
            b = event.app.current_buffer
            # 1. 执行原生的删除字符动作
            if b.text:
                b.delete_before_cursor(1)

            # 2. 核心魔法：如果删除后，输入框依然是以 '/' 开头的命令模式
            # 强行按头让 prompt_toolkit 重新弹出菜单！
            if b.text.startswith('/'):
                b.start_completion(select_first=False)

        # ──────────────────────────────────────────────────────────

        _pt_session = PromptSession(
            completer=_pawn_completer,
            key_bindings=_kb,  # ← 【关键】将我们的按键绑定注入到 Session 中
            auto_suggest=AutoSuggestFromHistory(),
            history=_pt_history,
            complete_while_typing=True,
            complete_in_thread=False,
            complete_style=CompleteStyle.COLUMN,
            mouse_support=False,
            bottom_toolbar=_bottom_toolbar,
            reserve_space_for_menu=4,
        )

        if not _runtime_state.quiet_mode:
            print(c(GRAY, "  🐚 PawnCompleter 就绪（内置模糊匹配 + 退格不消失 + 底部工具栏）"))
            if _HAS_RICH:
                print(c(GRAY, "  📝 rich 就绪（Markdown 渲染 + 代码高亮）"))
            elif _RICH_IMPORT_ERROR:
                print(c(YELLOW, f"  ⚠ rich 加载失败: {_RICH_IMPORT_ERROR}"))
    else:
        # ── readline 降级模式 ─────────────────────────────
        _ALL_COMMANDS = sorted(_all_words)

        def _completer_rl(text: str, state: int):
            line = readline.get_line_buffer()
            if line.startswith("/"):
                matches = [cmd for cmd in _ALL_COMMANDS if cmd.startswith(line)]
                if not matches:
                    matches = [cmd for cmd in _ALL_COMMANDS if cmd.startswith(text)]
            else:
                import glob
                matches = glob.glob(text + "*") if text else glob.glob("*")
                matches = [os.path.expanduser(m) + ("/" if os.path.isdir(m) else "") for m in matches]
            return matches[state] if state < len(matches) else None

        if readline is not None:
            readline.set_completer(_completer_rl)
            readline.set_completer_delims(" \t")
            readline.parse_and_bind("tab: complete")
            try:
                readline.read_history_file(_history_path)
            except FileNotFoundError:
                pass
            import atexit
            atexit.register(lambda: _safe_write_history(_history_path))

        if not _runtime_state.quiet_mode:
            print(c(GRAY, "  🐚 readline 降级模式（Tab 补全可用，无模糊匹配）"))
            if _PT_IMPORT_ERROR:
                print(c(YELLOW, f"  ⚠ prompt_toolkit 加载失败: {_PT_IMPORT_ERROR}"))
                print(c(YELLOW, f"     Python: {sys.executable}"))
                print(c(YELLOW, f"     修复: 在 venv 中执行 pip install prompt_toolkit rich"))
                print(c(YELLOW, f"     或重新安装: pip install -e ."))

    # ── 主循环 ────────────────────────────────────────────
    _re_edit_default = ""     # Ctrl+C 回退后，上一条用户文本作为 prompt default
    _last_sigint_time = 0.0   # 双击 Ctrl+C 退出计时
    _sigint_pending   = False # 第一次 Ctrl+C 已触发，等待第二次确认

    while True:
        try:
            # ════════════════════════════════════════════════════════
            # 【隐形历史修复】预渲染策略（Pre-Render Strategy）
            # 必须在调用任何 prompt_toolkit API 之前完成：
            #   [1] _display_session_history 内部 print_ptk(ANSI) + flush
            #   [2] sys.stdout.flush() 二次强制物理写入
            #   [3] print("\n") 撑开空白行，把 prompt_async 的接管点
            #       压到历史内容下方，避免初始化重绘吞掉历史
            # ════════════════════════════════════════════════════════
            if (_hist_msgs := take_deferred_history()) is not None:
                logger.debug("pre-render history: {} msgs", len(_hist_msgs))
                _display_session_history(_hist_msgs, show_recent=len(_hist_msgs))
                print("─" * 20 + " 以上为历史上下文 " + "─" * 20)
                sys.stdout.flush()
                print("\n")  # 强行撑开一行空间

            if prompt_toolkit_enabled:
                # ── 原生异步：patch_stdout 接管 stdout，避免 Agent 异步输出与输入行错乱 ──
                with _patch_stdout(raw=True):
                    raw = (await _pt_session.prompt_async(
                        [("class:prompt", "▶ "), ("class:you", "You > ")],
                        style=_pawn_style,
                        default=_re_edit_default,
                    )).strip()
            else:
                _label = _re_edit_default if _re_edit_default else ""
                raw = input(cp(BOLD+GREEN, "▶ ") + cp(BOLD, "You > ") + _label).strip()

            _re_edit_default = ""    # 消费后清空
            _sigint_pending  = False # 成功输入立即重置双击退出状态
            if not raw:
                continue
            if raw.startswith("/"):
                # ── 模糊命令修正（typo correction）──────────────
                _cmd_parts = raw.split(None, 1)
                _cmd_verb  = _cmd_parts[0]
                _cmd_rest  = _cmd_parts[1] if len(_cmd_parts) > 1 else ""
                if _cmd_verb not in _all_cmd_words and len(_cmd_verb) >= 3:
                    import difflib
                    _close = difflib.get_close_matches(
                        _cmd_verb, _all_cmd_words, n=1, cutoff=0.7
                    )
                    if _close:
                        _corrected = _close[0]
                        raw = f"{_corrected} {_cmd_rest}".strip() if _cmd_rest else _corrected
                        print(c(YELLOW, f"  ✔ 已自动修正: {_cmd_verb} → {_corrected}"))
                result = await handle_slash(raw, session)
                if result is _EXIT_SENTINEL:
                    print(c(CYAN, "\n  Goodbye! 👋"))
                    break
                continue
            try:
                session.run_turn(raw)
            except KeyboardInterrupt:
                print(c(YELLOW, "\n  [已中断]"))

        except KeyboardInterrupt:
            # ── 双击 Ctrl+C 退出（5 秒内第二次触发）──────────
            _now = time.monotonic()
            if _sigint_pending and (_now - _last_sigint_time < 5.0):
                print(c(CYAN, "\n  Goodbye! 👋"))
                break
            _last_sigint_time = _now
            _sigint_pending   = True
            removed, last_text = session.undo(1)
            if removed:
                _re_edit_default = last_text
            print(c(YELLOW, "\n  [提醒] 再按一次 Ctrl+C 退出应用"))
            continue
        except EOFError:
            # ── Ctrl+D 直接退出 ─────────────────────────────
            print(c(CYAN, "\n  Goodbye! 👋"))
            break
        except Exception as _loop_exc:
            logger.error("Main loop error: {!r}", _loop_exc)
            continue

    # ── 优雅退出：收割所有存活的 asyncio tasks ────────────
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
    for t in pending:
        t.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(c(CYAN, "\n\n  Goodbye! 👋"))
    except SystemExit:
        pass
    finally:
        detach_external_mcp_tools()


def run():
    """Synchronous entry point for the `pawn` CLI command (pip install)."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(c(CYAN, "\n\n  Goodbye! 👋"))
    except SystemExit:
        pass
    finally:
        detach_external_mcp_tools()
