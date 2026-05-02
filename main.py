#!/usr/bin/env python3
"""
PawnLogic 1.1 (Expert Edition) — main.py
多 Provider · 多模态视觉 · SQLite · CoT 引导 · GSA 技能存档 · 规格驱动 · GSD架构

快速部署（WSL2 Ubuntu）:
  cp -r PawnLogic_1.1 ~/.local/share/pawnlogic
  chmod +x ~/.local/share/pawnlogic/main.py
  ln -sf ~/.local/share/pawnlogic/main.py ~/.local/bin/pawn
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
  source ~/.bashrc
  pawn   # 首次运行会自动进入 API Key 配置向导
"""

import os, sys, shutil, getpass, argparse, time
try:
    import readline  # noqa  — Windows 原生无此模块，Tab 补全见 main() 内
except ImportError:
    readline = None
from pathlib import Path

# ── P2: CLI UX — prompt_toolkit / rich 可用性检测 ────────
_HAS_PROMPT_TOOLKIT = False
_HAS_RICH = False
_PT_IMPORT_ERROR = None
_RICH_IMPORT_ERROR = None
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter, FuzzyCompleter, Completion
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.styles import Style as _PTStyle
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.shortcuts import CompleteStyle
    _HAS_PROMPT_TOOLKIT = True
except Exception as _e:
    _PT_IMPORT_ERROR = str(_e)
    PromptSession = None

try:
    from rich.console import Console as _RichConsole
    from rich.markdown import Markdown as _RichMarkdown
    _rich_console = _RichConsole(force_terminal=True, highlight=False)
    _HAS_RICH = True
except Exception as _e:
    _RICH_IMPORT_ERROR = str(_e)
    _rich_console = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── 启动时加载 .env（必须在 import config 之前）───────────
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent / ".env"
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path)
    else:
        print(f"\033[93m  ⚠ 警告: 未找到 {_env_path} 文件\033[0m")
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

import config  # for config.QUIET_MODE mutation after argparse
from config import (
    VERSION, DYNAMIC_CONFIG, NORMAL_CONFIG,
    TIER_LOW, TIER_MID, TIER_DEEP,
    MODELS, DEFAULT_MODEL, DB_PATH, PROVIDERS,
    validate_api_key, list_vision_models,
)
from utils.ansi       import c, cp, rl_wrap, BOLD, DIM, GRAY, CYAN, GREEN, YELLOW, RED, MAGENTA
from core.session     import AgentSession, _ctx_chars, STATE_FILENAME
from core.memory import (
    init_db, list_knowledge, delete_knowledge,
    search_knowledge, pin_message_by_seq,
    # 2.1.0 新增
    full_text_search, get_session_messages_pretty,
    export_session_to_markdown,
    tag_session, untag_session, find_sessions_by_tag,
    link_sessions, unlink_sessions, get_linked_sessions,
    # P0: Failure Pattern DB
    list_failures, clear_failures,
)
from core.persistence import (session_save, session_load, session_list,
                               session_delete, memorize)
from tools.web_ops    import web_tool_status
from tools.pwn_chain  import tool_pwn_env
from tools.file_ops   import _session_cwd, tool_read_file
# ★ 新增：loguru 日志模块
from core.logger import logger, setup_logger

# ════════════════════════════════════════════════════════
# 模块 2：交互式 API Key 配置向导
# ════════════════════════════════════════════════════════

_WIZARD_PROVIDERS = [
    # (序号标签, env_var, label, hint, 是否可跳过key)
    ("1", "PAWN_API_KEY",       "PawnLogic Engine",  "hermes · hermes405",           False),
    ("2", "DEEPSEEK_API_KEY",   "DeepSeek",       "ds-chat (V3 强推理)",                  False),
    ("3", "OPENROUTER_API_KEY", "OpenRouter",     "多模型聚合，含 gpt-4o 视觉",            False),
    ("4", "SILICON_API_KEY",    "SiliconFlow",    "ds-coder · qwen 等国产模型",            False),
    ("5", "ZHIPU_API_KEY",      "ZhipuAI 智谱",  "glm-4v-plus 视觉识图（国内直连）",      False),
    ("6", "XIAOMI_API_KEY",     "Xiaomi MiMo",   "mimo-v2.5-pro · mimo-v2-omni",       False),
    ("7", None,                 "本地 Ollama",    "需先运行 ollama serve，无需 Key",        True),
]

def _detect_shell_config() -> Path | None:
    """检测用户使用的 shell 配置文件。"""
    shell = os.environ.get("SHELL", "")
    home  = Path.home()
    if "zsh"  in shell and (home / ".zshrc").exists():  return home / ".zshrc"
    if "bash" in shell:
        for f in [".bashrc", ".bash_profile", ".profile"]:
            if (home / f).exists(): return home / f
        return home / ".bashrc"   # 新建
    return home / ".bashrc"

def _write_key_to_shell(env_var: str, key: str) -> str:
    """将 export 语句写入 shell 配置文件并立即注入 os.environ。返回写入路径。"""
    cfg_file = _detect_shell_config()
    export_line = f'\nexport {env_var}="{key}"\n'

    # 读取现有内容，避免重复写入
    existing = ""
    if cfg_file and cfg_file.exists():
        try: existing = cfg_file.read_text(encoding="utf-8")
        except: pass

    if env_var not in existing:
        try:
            with open(str(cfg_file), "a", encoding="utf-8") as f:
                f.write(export_line)
        except Exception as e:
            return f"写入失败: {e}"

    # 立即注入当前进程
    os.environ[env_var] = key
    return str(cfg_file)

def _run_key_wizard() -> bool:
    """
    模块 2：无 Key 时的交互式配置向导。
    返回 True 表示至少成功配置了一个 Key（可以继续启动）。
    """
    print(f"""
{c(BOLD+CYAN, "╔════════════════════════════════════════════════╗")}
{c(BOLD+CYAN, "║")}  {c(BOLD, f"PawnLogic {VERSION}")} — 首次配置向导              {c(BOLD+CYAN,"║")}
{c(BOLD+CYAN, "╚════════════════════════════════════════════════╝")}

{c(YELLOW,"⚠  未检测到任何 API Key。")}
请选择要配置的服务商（可多次配置）：

""")

    for num, env_var, label, hint, no_key in _WIZARD_PROVIDERS:
        # 检测是否已配置
        already = ""
        if env_var and os.environ.get(env_var):
            already = c(GREEN, "  [已配置 ✓]")
        print(f"  {c(CYAN, f'[{num}]')} {c(BOLD, f'{label:18}')} {c(GRAY, hint)}{already}")

    print(f"\n  {c(GRAY, '[0]')} 跳过，稍后手动配置（export KEY=sk-... 或 /setkey）")
    print()

    configured_any = False

    while True:
        try:
            choice = input(cp(BOLD, "  请输入序号（可输入多个，如 1 5）: ")).strip()
        except (EOFError, KeyboardInterrupt):
            print(); break

        if choice == "0" or not choice:
            break

        selected = [c.strip() for c in choice.split() if c.strip()]

        for sel in selected:
            matched = next((p for p in _WIZARD_PROVIDERS if p[0] == sel), None)
            if not matched:
                print(c(RED, f"  ✗ 无效序号 '{sel}'"))
                continue

            num, env_var, label, hint, no_key = matched

            if no_key:
                # 本地 Ollama — 无需 Key
                local_url = input(
                    c(GRAY, f"  Ollama API URL [默认: http://localhost:11434/v1/chat/completions]: ")
                ).strip()
                if local_url:
                    os.environ["LOCAL_API_URL"] = local_url
                    # 写入 shell config
                    _write_key_to_shell("LOCAL_API_URL", local_url)
                print(c(GREEN, f"  ✓ Ollama 配置完成。请确保 ollama serve 已在后台运行。"))
                configured_any = True
                continue

            # 普通 Key 输入
            print(c(GRAY, f"\n  获取 {label} Key:"))
            _KEY_URLS = {
                "PAWN_API_KEY":       "https://portal.nousresearch.com/api-keys",
                "DEEPSEEK_API_KEY":   "https://platform.deepseek.com/api_keys",
                "OPENROUTER_API_KEY": "https://openrouter.ai/keys",
                "SILICON_API_KEY":    "https://cloud.siliconflow.cn/account/ak",
                "ZHIPU_API_KEY":      "https://open.bigmodel.cn/usercenter/apikeys",
                "XIAOMI_API_KEY":     "https://token-plan-cn.xiaomimimo.com",
            }
            url = _KEY_URLS.get(env_var, "")
            if url:
                print(c(CYAN, f"  申请地址: {url}"))

            try:
                # 使用 getpass 隐藏 Key 输入（防截屏）
                key = getpass.getpass(c(BOLD, f"  粘贴 {env_var} (输入时不显示): ")).strip()
            except (EOFError, KeyboardInterrupt):
                print(); continue

            if not key:
                print(c(YELLOW, "  跳过（未输入）"))
                continue

            # 写入 shell 配置 + 即时注入
            written_to = _write_key_to_shell(env_var, key)
            print(c(GREEN, f"  ✓ {env_var} 已保存 → {written_to}"))
            print(c(GRAY,  f"  已即时注入当前进程，无需重启终端。"))
            configured_any = True

        # 询问是否继续配置其他 provider
        try:
            cont = input(cp(GRAY, "  继续配置其他服务商? [y/N]: ")).strip().lower()
            if cont != "y":
                break
        except (EOFError, KeyboardInterrupt):
            break

    if not configured_any:
        print(c(YELLOW, "\n  未配置任何 Key。启动后可用 /setkey 命令重新配置。\n"))

    return configured_any

# ════════════════════════════════════════════════════════
# 帮助文本
# ════════════════════════════════════════════════════════

HELP_TEXT = f"""
{c(BOLD+CYAN, f"PawnLogic {VERSION} — Commands")}

{c(BOLD,"── 对话控制 ──")}
  {c(YELLOW,"/model [alias]")}   切换模型  支持: {", ".join(MODELS.keys())}
  {c(YELLOW,"/clear")}           清空上下文（保留 Pin 消息，State.md 持续注入）
  {c(YELLOW,"/context")}         上下文大小 / token 估算
  {c(YELLOW,"/pin [n]")}         从尾部固定最近 n 条（默认 2）
  {c(YELLOW,"/pin msg <n>")}     精准 Pin：按 /history 中的序号固定
  {c(YELLOW,"/unpin")}           解除所有 Pin
  {c(YELLOW,"/cd <path>")}       切换工作目录
  {c(YELLOW,"/file <path>")}     载入文件到上下文
  {c(YELLOW,"/history")}         消息历史（含序号，用于精准 Pin）

{c(BOLD,"── API Key 管理 ──")}
  {c(CYAN,"/setkey")}            重新运行 Key 配置向导
  {c(CYAN,"/keys")}              显示各 Provider Key 配置状态

{c(BOLD,"── 会话持久化（SQLite）──")}
  {c(CYAN,"/save [name]")}   保存当前会话 → ~/.pawnlogic/pawn.db
  {c(CYAN,"/load <name|n>")} 加载历史会话（名称子串/序号）
  {c(CYAN,"/sessions")}      列出所有会话
  {c(CYAN,"/del <name|n>")}  删除指定会话

{c(BOLD,"── 知识库 RAG ──")}
  {c(MAGENTA,"/memorize [topic]")}   AI 总结对话 → 存入知识库（每次新 session 自动召回）
  {c(MAGENTA,"/knowledge [query]")}  搜索/列出知识条目
  {c(MAGENTA,"/forget <id>")}        删除指定知识条目

{c(BOLD,"── 项目状态（GSD）──")}
  {c(YELLOW,"/init_project [desc]")} 在当前目录生成 .pawn_state.md（项目大目标）
  {c(YELLOW,"/state")}               查看当前目录的 .pawn_state.md

{c(BOLD,"── 三档预设 ──")}
  {c(GREEN,  "/low")}     日常/算法 · tokens=4k  ctx=40k  iter=10
  {c(YELLOW, "/mid")}     开发/Pwn  · tokens=8k  ctx=150k iter=30  ← 默认
  {c(MAGENTA,"/deep")}    全火力    · tokens=32k ctx=400k iter=50
  {c(GRAY,   "/normal")}  重置到 /mid

{c(BOLD,"── 细粒度调节 ──")}
  {c(YELLOW,"/tokens /ctx /iter /toolsize /fetchsize <n>")}
  {c(YELLOW,"/limits")}  查看所有当前限制
  {c(YELLOW,"/worker [alias|auto]")}  子任务 Worker 模型选择
  {c(YELLOW,"/time [秒数]")}  时间预算（CTF 倒计时）

{c(BOLD,"── 工具状态 ──")}
  {c(YELLOW,"/webstatus")}  Jina / Pandoc / Lynx 状态
  {c(YELLOW,"/pwnenv")}     CTF 工具链完整性

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
# 配置显示
# ════════════════════════════════════════════════════════

def _fmt_config() -> str:
    cfg = DYNAMIC_CONFIG
    return (
        f"  max_tokens      : {c(CYAN,str(cfg['max_tokens']))}  (每次 API 输出上限)\n"
        f"  ctx_max_chars   : {c(CYAN,str(cfg['ctx_max_chars']))}  (~{cfg['ctx_max_chars']//4:,} tokens)\n"
        f"  max_iter        : {c(CYAN,str(cfg['max_iter']))}  (工具调用轮次上限)\n"
        f"  tool_max_chars  : {c(CYAN,str(cfg['tool_max_chars']))}\n"
        f"  fetch_max_chars : {c(CYAN,str(cfg['fetch_max_chars']))}\n"
    )

# ════════════════════════════════════════════════════════
# 模块 4.4：/init_project 命令实现
# ════════════════════════════════════════════════════════

_STATE_TEMPLATE = """\
# PawnLogic Project State
Created: {ts}
Directory: {cwd}

## 🎯 Project Goal
{goal}

## 📋 Current Tasks
- [ ] 初始规划

## ✅ Completed
(none yet)

## 📝 Architecture Notes
(agent will update this as work progresses)

## ⚠ Known Issues
(none)
"""

def _init_project(cwd: str, description: str) -> str:
    """在 cwd 生成 .pawn_state.md，返回成功/失败消息。"""
    state_path = Path(cwd) / STATE_FILENAME
    if state_path.exists():
        overwrite = input(
            c(YELLOW, f"  .pawn_state.md 已存在，覆盖? [y/N]: ")
        ).strip().lower()
        if overwrite != "y":
            return "已取消"

    content = _STATE_TEMPLATE.format(
        ts   = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
        cwd  = cwd,
        goal = description or "(未填写，请直接编辑 .pawn_state.md)",
    )
    state_path.write_text(content, encoding="utf-8")
    return str(state_path)

def _resolve_session_id(query: str, sessions_list=None) -> str | None:
    """
    将用户输入（序号或 id 子串）解析为完整 session_id。
    """
    from core.memory import list_sessions, get_session
    rows = sessions_list or list_sessions(50)
    if not rows:
        return None
    query = query.strip()
    # 按序号（1-indexed）
    try:
        idx = int(query) - 1
        if 0 <= idx < len(rows):
            return rows[idx]["id"]
    except ValueError:
        pass
    # 按 id 子串
    for r in rows:
        if query.lower() in r["id"].lower() or query.lower() in (r["name"] or "").lower():
            return r["id"]
    return None


# ════════════════════════════════════════════════════════
# GSA 辅助：/memo 存档逻辑
# ════════════════════════════════════════════════════════

def _memo_to_skills(session, content: str, verbose: bool = True) -> str:
    """
    /memo 命令核心：
      · content 为空时，自动提取上一条 assistant 回复
      · 调用 core.gsa.write_skill() 完成分类 → 格式化 → 去重 → 写入
      · 返回结果消息字符串（✓ 成功 / ⚠ 降级 / ERROR 失败）
    """
    try:
        from core.gsa import write_skill
    except ImportError:
        return "ERROR: core/gsa.py 未找到，请确认 GSA 模块已部署到 core/ 目录。"

    # 若无内容，提取上一轮 AI 回复
    if not content.strip():
        last_ai = next(
            (m.get("content", "") for m in reversed(session.messages)
             if m.get("role") == "assistant" and m.get("content")),
            ""
        )
        if not last_ai.strip():
            return "ERROR: 对话历史中没有可提取的 AI 回复，请在 /memo 后附上要存档的内容。"
        content = last_ai
        if verbose:
            print(c(GRAY, f"  (自动提取上一条 AI 回复，{len(content)} 字符)"))

    if verbose:
        print(c(YELLOW, f"  🧠 [GSA] 正在分类并存档（模型: {session.model_alias}）..."))

    ok, msg = write_skill(
        model_alias = session.model_alias,
        content     = content,
        topic_hint  = "",
    )
    return msg


def _handle_chat(arg: str, arg2: str, session):
    """
    处理所有 /chat 子命令。
    在 handle_slash 中被调用：
        elif verb == "/chat":
            _handle_chat(arg, arg2, session)
    """
    from core.memory import (
        list_sessions, get_session,
        full_text_search, get_session_messages_pretty, export_session_to_markdown,
        tag_session, untag_session, find_sessions_by_tag,
        link_sessions, unlink_sessions, get_linked_sessions,
    )
    from utils.ansi import c, BOLD, GRAY, CYAN, GREEN, YELLOW, RED, MAGENTA
    from pathlib import Path

    sub = arg.lower().strip() if arg else "list"
    # 将 arg2 分割为 rest（子命令后的所有参数）
    # /chat view 3          → sub=view  target=3
    # /chat export 3 ./out  → sub=export target=3  extra=./out
    # /chat link 1 2 note   → sub=link   target=1   extra="2 note"
    target = arg2.strip() if arg2 else ""

    # ── /chat list [n] ──────────────────────────────────
    if sub in ("list", "ls", ""):
        n = int(target) if target.isdigit() else 20
        rows = list_sessions(n)
        if not rows:
            print(c(GRAY, "  (暂无已保存会话)"))
            return
        print(c(BOLD, f"\n  对话历史（最近 {len(rows)} 条）："))
        for i, r in enumerate(rows):
            tags_str = c(CYAN, f"  [{r['tags']}]") if r["tags"] else ""
            name_str = c(YELLOW, r["name"]) if r["name"] else c(GRAY, "(未命名)")
            print(
                c(GRAY, f"  [{i + 1:2d}] ") +
                c(CYAN, f"{r['id'][:24]}") +
                f"  {name_str}{tags_str}\n"
                + c(GRAY, f"       {r['updated_at'][:16]}  {r['msg_count']}条消息  model={r['model']}")
            )

    # ── /chat view <id|n> ────────────────────────────────
    elif sub == "view":
        if not target:
            print(c(RED, "  用法: /chat view <序号 或 session_id 前缀>"))
            return
        sid = _resolve_session_id(target)
        if not sid:
            print(c(RED, f"  ✗ 找不到会话 '{target}'"))
            return
        meta = get_session(sid)
        msgs = get_session_messages_pretty(sid)
        print(c(BOLD, f"\n  ╔ 会话 {sid}"))
        print(c(GRAY, f"  ║ 名称  : {meta['name'] or '(未命名)'}"))
        print(c(GRAY, f"  ║ 模型  : {meta['model']}"))
        print(c(GRAY, f"  ║ 目录  : {meta['cwd']}"))
        print(c(GRAY, f"  ║ 标签  : {meta['tags'] or '-'}"))
        print(c(GRAY, f"  ║ 更新  : {meta['updated_at']}"))
        print(c(GRAY, f"  ╚ 共 {len(msgs)} 条消息"))
        print()

        for m in msgs:
            role = m["role"]
            seq_tag = c(GRAY, f"[{m['seq']:3d}]")
            pin_tag = c(GREEN, " 📌") if m["is_pinned"] else "   "
            ts = c(GRAY, m["created_at"][11:16] if m["created_at"] else "")

            if role == "system":
                continue  # system 消息不显示（太长）
            elif role == "user":
                print(c(BOLD + "\033[96m", f"  🧑 You") + f" {seq_tag}{pin_tag} {ts}")
                # 每行缩进显示
                for line in m["content_full"].splitlines()[:10]:
                    print(f"     {line}")
                if m["content_full"].count("\n") > 10:
                    print(c(GRAY, f"     ...（共 {m['content_full'].count(chr(10)) + 1} 行）"))
            elif role == "assistant":
                preview = m["preview"]
                print(c(BOLD + "\033[92m", f"  🤖 Agent") + f" {seq_tag}{pin_tag} {ts}")
                for line in m["content_full"].splitlines()[:8]:
                    print(f"     {line}")
                if m["content_full"].count("\n") > 8:
                    print(c(GRAY, f"     ...（共 {m['content_full'].count(chr(10)) + 1} 行）"))
            elif role == "tool":
                print(c(GRAY, f"  🔩 tool") + f" {seq_tag} {ts}  {m['preview']}")
            print()

    # ── /chat export <id|n> [path] ──────────────────────
    elif sub == "export":
        if not target:
            print(c(RED, "  用法: /chat export <序号 或 id> [输出文件路径]"))
            return
        # target 可能是 "3" 或 "3 ./out.md"
        parts = target.split(None, 1)
        id_part = parts[0]
        out_arg = parts[1].strip() if len(parts) > 1 else ""

        sid = _resolve_session_id(id_part)
        if not sid:
            print(c(RED, f"  ✗ 找不到会话 '{id_part}'"))
            return

        md_content = export_session_to_markdown(sid)
        if md_content.startswith("ERROR:"):
            print(c(RED, f"  {md_content}"))
            return

        if out_arg:
            out_path = Path(out_arg).expanduser()
        else:
            out_path = Path(session.cwd) / f"chat_{sid[:16]}.md"

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md_content, encoding="utf-8")
        print(c(GREEN, f"  ✓ 对话已导出 → {out_path}"))
        print(c(GRAY, f"  共 {len(md_content)} 字符 / {md_content.count(chr(10))} 行"))

    # ── /chat find <keywords> ────────────────────────────
    elif sub == "find":
        if not target:
            print(c(RED, "  用法: /chat find <搜索词（空格分隔多词）>"))
            return
        print(c(YELLOW, f"  🔍 跨会话搜索: '{target}' ..."))
        results = full_text_search(target, limit=10)
        if not results:
            print(c(GRAY, "  未找到匹配内容。"))
            return
        print(c(BOLD, f"\n  找到 {len(results)} 个会话含匹配内容："))
        for r in results:
            print(c(CYAN, f"\n  [{r['session_id'][:20]}]") +
                  c(YELLOW, f"  {r['session_name'] or '(未命名)'}") +
                  c(GRAY, f"  {r['updated_at'][:16]}  tags={r['tags'] or '-'}"))
            for hit in r["hits"]:
                role_icon = "🧑" if hit["role"] == "user" else ("🤖" if hit["role"] == "assistant" else "🔩")
                print(c(GRAY, f"    [{hit['seq']:3d}] {role_icon} ") + hit["snippet"])

    # ── /chat tag <id|n> <tags> ──────────────────────────
    elif sub == "tag":
        parts = target.split(None, 1)
        if len(parts) < 2:
            print(c(RED, "  用法: /chat tag <序号 或 id> <标签1,标签2,...>"))
            return
        sid = _resolve_session_id(parts[0])
        if not sid:
            print(c(RED, f"  ✗ 找不到会话 '{parts[0]}'"))
            return
        ok = tag_session(sid, parts[1])
        if ok:
            print(c(GREEN, f"  ✓ 已给会话 {sid[:20]}... 添加标签: {parts[1]}"))
        else:
            print(c(RED, f"  ✗ 操作失败"))

    # ── /chat untag <id|n> <tags> ────────────────────────
    elif sub == "untag":
        parts = target.split(None, 1)
        if len(parts) < 2:
            print(c(RED, "  用法: /chat untag <序号 或 id> <标签1,标签2,...>"))
            return
        sid = _resolve_session_id(parts[0])
        if not sid:
            print(c(RED, f"  ✗ 找不到会话 '{parts[0]}'"))
            return
        untag_session(sid, parts[1])
        print(c(GREEN, f"  ✓ 已移除标签: {parts[1]}"))

    # ── /chat bytag <tag> ────────────────────────────────
    elif sub == "bytag":
        if not target:
            print(c(RED, "  用法: /chat bytag <标签名>"))
            return
        rows = find_sessions_by_tag(target)
        if not rows:
            print(c(GRAY, f"  未找到带标签 '{target}' 的会话。"))
            return
        print(c(BOLD, f"\n  标签 '{target}' 的会话（{len(rows)} 个）："))
        for i, r in enumerate(rows):
            print(c(GRAY, f"  [{i + 1:2d}] ") + c(CYAN, r["id"][:24]) +
                  c(GRAY, f"  {r['updated_at'][:16]}  {r['msg_count']}条  tags={r['tags']}"))

    # ── /chat link <id1> <id2> [note] ────────────────────
    elif sub == "link":
        parts = target.split(None, 2)
        if len(parts) < 2:
            print(c(RED, "  用法: /chat link <id/序号1> <id/序号2> [关联备注]"))
            return
        sid_a = _resolve_session_id(parts[0])
        sid_b = _resolve_session_id(parts[1])
        note = parts[2] if len(parts) > 2 else ""
        if not sid_a or not sid_b:
            print(c(RED, f"  ✗ 无法解析会话 ID"))
            return
        if sid_a == sid_b:
            print(c(RED, "  ✗ 不能关联同一个会话"))
            return
        link_sessions(sid_a, sid_b, note)
        print(c(GREEN, f"  ✓ 已关联:"))
        print(c(GRAY, f"    {sid_a[:24]}"))
        print(c(GRAY, f"    {sid_b[:24]}"))
        if note: print(c(GRAY, f"    备注: {note}"))

    # ── /chat unlink <id1> <id2> ─────────────────────────
    elif sub == "unlink":
        parts = target.split(None, 1)
        if len(parts) < 2:
            print(c(RED, "  用法: /chat unlink <id/序号1> <id/序号2>"))
            return
        sid_a = _resolve_session_id(parts[0])
        sid_b = _resolve_session_id(parts[1])
        if not sid_a or not sid_b:
            print(c(RED, "  ✗ 无法解析会话 ID"))
            return
        unlink_sessions(sid_a, sid_b)
        print(c(GREEN, f"  ✓ 已取消关联 {sid_a[:20]} ↔ {sid_b[:20]}"))

    # ── /chat related <id|n> ─────────────────────────────
    elif sub == "related":
        if not target:
            print(c(RED, "  用法: /chat related <序号 或 id>"))
            return
        sid = _resolve_session_id(target)
        if not sid:
            print(c(RED, f"  ✗ 找不到会话 '{target}'"))
            return
        linked = get_linked_sessions(sid)
        if not linked:
            print(c(GRAY, f"  会话 {sid[:24]} 没有关联的对话。"))
            print(c(GRAY, "  使用 /chat link 创建关联。"))
            return
        print(c(BOLD, f"\n  会话 {sid[:24]} 的关联对话（{len(linked)} 个）："))
        for item in linked:
            m = item["meta"]
            note = item["note"]
            ts = item["linked_at"][:16]
            print(c(CYAN, f"  {m['id'][:24]}") +
                  c(GRAY, f"  {m['updated_at'][:16]}  {m['msg_count']}条  model={m['model']}"))
            if note: print(c(GRAY, f"    备注: {note}"))
            print()

    else:
        print(c(GRAY, (
            f"  未知子命令 '{sub}'。\n"
            "  可用: list · view · export · find · tag · untag · bytag · link · unlink · related"
        )))


# ════════════════════════════════════════════════════════
# Slash 命令
# ════════════════════════════════════════════════════════

def handle_slash(cmd: str, session: AgentSession):
    parts = cmd.strip().split(None, 2)
    verb  = parts[0].lower()
    arg   = parts[1].strip() if len(parts) > 1 else ""
    arg2  = parts[2].strip() if len(parts) > 2 else ""

    # ── 帮助 / 退出 ────────────────────────────────────
    if verb == "/help":
        print(HELP_TEXT)

    elif verb in ("/exit", "/quit", "/q"):
        print(c(CYAN, "\n  Goodbye! 👋")); sys.exit(0)

    # ── 模块 2：Key 管理 ────────────────────────────────
    elif verb == "/setkey":
        _run_key_wizard()

    elif verb == "/keys":
        print(c(BOLD, "\n  API Key 配置状态："))
        for pname, pinfo in PROVIDERS.items():
            env  = pinfo.get("api_key_env")
            if not env:
                continue
            val  = os.environ.get(env, "")
            if val:
                masked = val[:8] + "..." + val[-4:] if len(val) > 12 else "***"
                tag    = c(GREEN, f"✓ 已配置 ({masked})")
            else:
                tag    = c(RED,   "✗ 未配置")
            print(f"  {c(CYAN, f'{pname:14}')}{env:28} {tag}")
        print(c(GRAY, "\n  视觉模型: " + ", ".join(list_vision_models())))

    # ── 模型 ────────────────────────────────────────────
    elif verb == "/model":
        if not arg:
            # ── CC 风格内联选择器 ──────────────────────────
            if _HAS_PROMPT_TOOLKIT:
                result = cc_style_model_selector(MODELS, session.model_alias)
                if result:
                    session.model_alias = result
                    ok, env = validate_api_key(result)
                    if not ok:
                        print(c(YELLOW, f"  ⚠ 已切换到 {result}，但 {env} 未设置。用 /setkey 配置。"))
                    else:
                        print(c(GREEN, f"  ✓ 已切换到 {c(MODELS[result]['color'], result)}"))
                else:
                    print(c(GRAY, "  已取消"))
            else:
                # readline 降级：纯文本列表
                print(c(BOLD, "\n  可用模型："))
                for alias, cfg_m in MODELS.items():
                    tick   = c(GREEN, " ◀ 当前") if alias == session.model_alias else ""
                    ok, _  = validate_api_key(alias)
                    ktag   = c(GREEN, "[key✓]") if ok else c(RED, "[key✗]")
                    vtag   = c(CYAN,  " 📷")    if cfg_m.get("vision") else ""
                    print(f"    {c(cfg_m['color'], f'{alias:14}')}{cfg_m['desc']:30} {ktag}{vtag}{tick}")
                print(c(GRAY, "\n  用法: /model <alias>  📷=支持视觉"))
        elif arg in MODELS:
            session.model_alias = arg
            ok, env = validate_api_key(arg)
            if not ok:
                print(c(YELLOW, f"  ⚠ 已切换到 {arg}，但 {env} 未设置。用 /setkey 配置。"))
            else:
                print(c(GREEN, f"  ✓ 已切换到 {c(MODELS[arg]['color'], arg)}"))
        else:
            print(c(RED, f"  ✗ 未知模型 '{arg}'"))

    # ── 上下文 ─────────────────────────────────────────
    elif verb == "/clear":
        pinned = [m for m in session.messages if m.get("_pinned")]
        session.messages.clear(); session._reset_system_prompt()
        session.messages.extend(pinned)
        state_exists = (Path(session.cwd) / STATE_FILENAME).exists()
        state_note   = c(GREEN, "  (State.md 将在下轮自动注入)") if state_exists else ""
        print(c(GREEN, f"  ✓ 已清空（保留 {len(pinned)} 条 Pin 消息）{state_note}"))

    elif verb == "/context":
        msgs   = session.messages
        chars  = _ctx_chars(msgs)
        pct    = chars / DYNAMIC_CONFIG["ctx_max_chars"] * 100
        tok    = chars // 4
        pinned = sum(1 for m in msgs if m.get("_pinned"))
        filled = int(min(pct, 100)/100*30)
        bcol   = RED if pct > 80 else (YELLOW if pct > 50 else GREEN)
        bar    = c(bcol, "█"*filled) + c(GRAY, "░"*(30-filled))
        warn   = c(YELLOW, "  ⚠ 超80%，建议 /clear") if pct > 80 else ""
        print(f"\n  {c(BOLD,'上下文')}  {len(msgs)}条  Pin:{c(GREEN,str(pinned))}"
              f"  ~{tok:,} tokens\n  [{bar}] {pct:.1f}%  {warn}\n")

    elif verb == "/pin":
        if arg == "msg":
            try:
                seq      = int(arg2)
                non_sys  = [m for m in session.messages if m.get("role") != "system"]
                if 0 <= seq < len(non_sys):
                    non_sys[seq]["_pinned"] = True
                    pin_message_by_seq(session.session_id, seq, True)
                    role    = non_sys[seq].get("role", "?")
                    preview = str(non_sys[seq].get("content", ""))[:50].replace("\n", " ")
                    print(c(GREEN, f"  ✓ 精准 Pin [{seq}] [{role}]: {preview}"))
                else:
                    print(c(RED, f"  ✗ 序号 {seq} 超出范围（共 {len(non_sys)} 条非 system 消息）"))
            except ValueError:
                print(c(RED, "  用法: /pin msg <序号>  (先 /history 查看序号)"))
        else:
            n = int(arg) if arg.isdigit() else 2
            count = 0
            for m in reversed(session.messages):
                if m.get("role") == "system": break
                if not m.get("_pinned"):
                    m["_pinned"] = True; count += 1
                    if count >= n: break
            print(c(GREEN, f"  ✓ 已 Pin 最近 {count} 条"))

    elif verb == "/unpin":
        count = sum(1 for m in session.messages if m.pop("_pinned", None))
        print(c(GREEN, f"  ✓ 已解除 {count} 条 Pin"))

    elif verb == "/cd":
        target = arg or "~"
        try:
            os.chdir(Path(target).expanduser())
            session.cwd     = os.getcwd()
            _session_cwd[0] = session.cwd
            session._reset_system_prompt()
            state_exists = (Path(session.cwd) / STATE_FILENAME).exists()
            state_tag    = c(CYAN, "  [State.md 已检测]") if state_exists else ""
            print(c(GREEN, f"  ✓ cwd: {session.cwd}{state_tag}"))
        except Exception as e:
            print(c(RED, f"  ✗ {e}"))

    elif verb == "/file":
        if not arg: print(c(RED, "  用法: /file <path>"))
        else:
            content = tool_read_file({"path": arg})
            session.messages.append({"role":"user",
                "content": f"[Loaded: {arg}]\n```\n{content}\n```"})
            session.messages.append({"role":"assistant",
                "content": f"已载入 `{arg}` ({len(content)} 字符)"})
            print(c(GREEN, f"  ✓ 已载入 {arg}"))

    elif verb == "/history":
        print(c(CYAN, f"\n  {len(session.messages)} 条消息（序号不含 system）："))
        seq = 0
        for m in session.messages:
            role    = m.get("role", "?")
            content = str(m.get("content") or "")[:65].replace("\n", " ")
            pin_tag = c(GREEN, " 📌") if m.get("_pinned") else "   "
            if role == "system":
                print(c(GRAY,  f"  [{'sys':9}]     {content[:50]}"))
            else:
                print(c(GRAY, f"  [{role:9}]") + c(CYAN, f"[{seq:3d}]") + pin_tag + f" {content}")
                seq += 1

    # ── 会话持久化 ──────────────────────────────────────
    elif verb == "/save":
        sid = session_save(session, arg)
        print(c(GREEN, f"  ✓ 已保存 session_id={sid}"))

    elif verb == "/load":
        if not arg: print(c(RED, "  用法: /load <name 或 序号>"))
        else:
            result = session_load(session, arg)
            print(c(GREEN if result.startswith("OK") else RED, f"  {result}"))

    elif verb == "/sessions":
        print(c(BOLD, f"\n  已保存会话 (DB: {DB_PATH})："))
        print(session_list())

    elif verb == "/del":
        if not arg: print(c(RED, "  用法: /del <name 或 序号>"))
        else:
            result = session_delete(session, arg)
            print(c(GREEN if result.startswith("OK") else RED, f"  {result}"))

    # ── 知识库 ─────────────────────────────────────────
    elif verb == "/memorize":
        topic = (arg + " " + arg2).strip() or "general"
        print(c(YELLOW, f"  🧠 正在总结「{topic}」..."))
        result = memorize(session, topic)
        print(c(GREEN if result.startswith("OK") else RED, f"  {result}"))

    elif verb == "/knowledge":
        query = (arg + " " + arg2).strip()
        if query:
            rows = search_knowledge(query, limit=10)
            print(c(BOLD, f"\n  知识库搜索: '{query}' — {len(rows)} 条："))
        else:
            rows = list(list_knowledge(20))
            print(c(BOLD, f"\n  知识库（最近 {len(rows)} 条）："))
        if not rows:
            print(c(GRAY, "  (空)"))
        else:
            for r in rows:
                print(c(CYAN, f"  [{r['id']:3d}] ") + c(YELLOW, r["topic"]) +
                      c(GRAY, f"  {r['created_at'][:16]}  tags={r['tags'] or '-'}"))
                print(c(GRAY, f"       {str(r['content'])[:100]}"))

    elif verb == "/forget":
        if not arg: print(c(RED, "  用法: /forget <id>"))
        else:
            try:
                delete_knowledge(int(arg))
                print(c(GREEN, f"  ✓ 已删除知识条目 id={arg}"))
            except Exception as e:
                print(c(RED, f"  ✗ {e}"))

    # ── 模块 4.4：项目状态 ─────────────────────────────
    elif verb == "/init_project":
        desc   = (arg + " " + arg2).strip()
        result = _init_project(session.cwd, desc)
        if result == "已取消":
            print(c(YELLOW, "  已取消"))
        else:
            session._reset_system_prompt()   # 立即注入新的 State.md
            print(c(GREEN, f"  ✓ 已创建 {result}"))
            print(c(GRAY,  "  State.md 已注入 System Prompt，/clear 后也会保持。"))
            print(c(GRAY,  f"  提示：直接说出任务，Agent 将遵循规格驱动格式执行并自动提交 git。"))

    elif verb == "/state":
        p = Path(session.cwd) / STATE_FILENAME
        if p.exists():
            print(c(BOLD, f"\n  {p}："))
            print(p.read_text(encoding="utf-8"))
        else:
            print(c(GRAY, f"  当前目录没有 {STATE_FILENAME}。用 /init_project 创建。"))

    # ── 三档预设 ────────────────────────────────────────
    elif verb == "/low":
        DYNAMIC_CONFIG.update(TIER_LOW)
        session._reset_system_prompt()
        print(c(GREEN,        "  ✓ /low 模式（日常 / 算法）")); print(_fmt_config())

    elif verb == "/mid":
        DYNAMIC_CONFIG.update(TIER_MID)
        session._reset_system_prompt()
        print(c(YELLOW,       "  ✓ /mid 模式（开发 / Pwn）")); print(_fmt_config())

    elif verb == "/deep":
        DYNAMIC_CONFIG.update(TIER_DEEP)
        session._reset_system_prompt()
        print(c(BOLD+MAGENTA, "  🔥 /deep 全火力")); print(_fmt_config())

    elif verb == "/normal":
        DYNAMIC_CONFIG.update(NORMAL_CONFIG)
        session._reset_system_prompt()
        print(c(GREEN, "  ✓ 已重置到 /mid")); print(_fmt_config())

    elif verb == "/limits":
        print(c(BOLD, "\n  当前运行时限制：")); print(_fmt_config())
        print(c(GRAY, "  /low /mid /deep  |  /tokens /ctx /iter /toolsize /fetchsize"))

    # ── 细粒度调节 ──────────────────────────────────────
    elif verb == "/tokens":
        if not arg: print(c(GRAY, f"  当前: {DYNAMIC_CONFIG['max_tokens']}  /tokens <n>"))
        else:
            try:
                n = max(256, min(65536, int(arg)))
                DYNAMIC_CONFIG["max_tokens"] = n
                session._reset_system_prompt()
                print(c(GREEN, f"  ✓ max_tokens={n}"))
            except ValueError: print(c(RED, "  ✗ 无效数字"))

    elif verb == "/ctx":
        if not arg: print(c(GRAY, f"  当前: {DYNAMIC_CONFIG['ctx_max_chars']}  /ctx <n>"))
        else:
            try:
                n = max(10_000, int(arg))
                DYNAMIC_CONFIG["ctx_max_chars"] = n
                DYNAMIC_CONFIG["ctx_trim_to"]   = int(n * .75)
                session._reset_system_prompt()
                print(c(GREEN, f"  ✓ ctx_max_chars={n}"))
            except ValueError: print(c(RED, "  ✗ 无效数字"))

    elif verb == "/iter":
        if not arg: print(c(GRAY, f"  当前: {DYNAMIC_CONFIG['max_iter']}  /iter <n>"))
        else:
            try:
                n = max(1, int(arg))
                DYNAMIC_CONFIG["max_iter"] = n
                print(c(GREEN, f"  ✓ max_iter={n}"))
            except ValueError: print(c(RED, "  ✗ 无效数字"))

    elif verb == "/toolsize":
        if not arg: print(c(GRAY, f"  当前: {DYNAMIC_CONFIG['tool_max_chars']}"))
        else:
            try:
                DYNAMIC_CONFIG["tool_max_chars"] = max(1000, int(arg))
                print(c(GREEN, f"  ✓ tool_max_chars={DYNAMIC_CONFIG['tool_max_chars']}"))
            except ValueError: print(c(RED, "  ✗ 无效数字"))

    elif verb == "/fetchsize":
        if not arg: print(c(GRAY, f"  当前: {DYNAMIC_CONFIG['fetch_max_chars']}"))
        else:
            try:
                DYNAMIC_CONFIG["fetch_max_chars"] = max(1000, int(arg))
                print(c(GREEN, f"  ✓ fetch_max_chars={DYNAMIC_CONFIG['fetch_max_chars']}"))
            except ValueError: print(c(RED, "  ✗ 无效数字"))

    # ── 工具状态 ────────────────────────────────────────
    elif verb == "/webstatus":
        print(c(BOLD, "\n  网页抓取工具状态：")); print(web_tool_status())

    elif verb == "/pwnenv":
        print(tool_pwn_env({}))

    elif verb == "/stats":
        pt  = session.total_prompt_tokens
        ct  = session.total_completion_tokens
        tt  = session.total_tool_calls
        tot = pt + ct
        est_usd = tot / 1_000_000 * 1.50
        if tot + tt == 0:
            print(c(GRAY, "  (本次会话暂无 API 调用记录)"))
        elif config.QUIET_MODE:
            print(c(GRAY, f"  stats: ↑{pt:,} ↓{ct:,} total={tot:,} tools={tt} ~${est_usd:.4f}"))
        else:
            print(c(BOLD, "\n  ╔══ 会话用量审计 ════════════════════════════╗"))
            print(f"  ║  Prompt tokens    : {c(CYAN, f'{pt:>10,}')}               ║")
            print(f"  ║  Completion tokens: {c(CYAN, f'{ct:>10,}')}               ║")
            print(f"  ║  Total tokens     : {c(YELLOW, f'{tot:>10,}')}               ║")
            print(f"  ║  Tool calls       : {c(GREEN, f'{tt:>10,}')}               ║")
            print(f"  ║  Est. cost        : {c(GRAY, f'~${est_usd:.4f} USD'):>18}         ║")
            print(c(BOLD,  "  ╚══════════════════════════════════════════════╝"))
            print(c(GRAY, "  (成本估算基于 $1.50/1M tokens 均值，仅供参考)"))

    # ── P1: /time 命令 ───────────────────────────────────
    elif verb == "/time":
        budget = DYNAMIC_CONFIG.get("time_budget_sec", 0)
        if arg and arg.strip().isdigit():
            new_budget = max(0, int(arg.strip()))
            DYNAMIC_CONFIG["time_budget_sec"] = new_budget
            session._time_budget_sec = new_budget
            session._reset_system_prompt()
            if new_budget > 0:
                m, s = divmod(new_budget, 60)
                print(c(GREEN, f"  ✓ 时间预算已设为 {m}m{s}s"))
            else:
                print(c(GREEN, "  ✓ 时间预算已关闭（不限时）"))
        else:
            if budget > 0:
                m, s = divmod(budget, 60)
                elapsed = time.monotonic() - session._turn_start_time if session._turn_start_time else 0
                remaining = max(0, budget - elapsed)
                rm, rs = divmod(int(remaining), 60)
                mode = c(RED, " [URGENT]") if session._urgent_mode else ""
                print(c(BOLD, "\n  ⏱  时间预算："))
                print(f"  预算: {c(CYAN, f'{m}m{s}s')}")
                print(f"  已用: {c(YELLOW, f'{int(elapsed)}s')}")
                print(f"  剩余: {c(GREEN if remaining > 30 else RED, f'{rm}m{rs}s')}{mode}")
                print(c(GRAY, f"\n  /time <秒数> 修改 | /time 0 关闭"))
            else:
                print(c(GRAY, "  时间预算未设置（不限时）"))
                print(c(GRAY, "  /time <秒数> 设置 | 例: /time 300 = 5分钟"))

    # ── /worker：子任务 Worker 模型选择 ───────────────────
    elif verb == "/worker":
        from tools.delegate_tool import _WORKER_MODEL_CANDIDATES
        target = arg.lower().strip() if arg else ""

        if not target:
            # 无参数：显示交互式菜单
            current = DYNAMIC_CONFIG.get("preferred_worker", "auto")
            print(c(BOLD, "\n  子任务 Worker 模型（delegate_task 使用）："))
            for i, alias in enumerate(_WORKER_MODEL_CANDIDATES):
                if alias not in MODELS:
                    continue
                ok, env = validate_api_key(alias)
                ktag = c(GREEN, "[key✓]") if ok else c(RED, "[key✗]")
                desc = MODELS[alias].get("desc", "")
                tick = c(GREEN, " ◀ 当前") if alias == current else ""
                print(
                    c(GRAY, f"  [{i+1}] ")
                    + c(CYAN, f"{alias:16}")
                    + f" {desc:30} {ktag}{tick}"
                )
            # auto 选项
            auto_tick = c(GREEN, " ◀ 当前") if current == "auto" else ""
            print(
                c(GRAY, f"  [A] ")
                + c(YELLOW, f"{'auto':16}")
                + f" {'系统自动路由（按优先级选取首个可用模型）':30} {auto_tick}"
            )
            print(c(GRAY, f"\n  用法: /worker <alias> 或 /worker auto"))

        elif target == "auto":
            DYNAMIC_CONFIG["preferred_worker"] = "auto"
            session._reset_system_prompt()
            print(c(GREEN, "  ✓ Worker 已恢复为自动路由模式"))

        elif target in MODELS:
            ok, env = validate_api_key(target)
            if not ok:
                print(c(YELLOW, f"  ⚠ 已切换到 {target}，但 {env} 未设置。用 /setkey 配置。"))
            DYNAMIC_CONFIG["preferred_worker"] = target
            session._reset_system_prompt()
            print(c(GREEN, f"  ✓ Worker 已锁定为 {c(CYAN, target)}（子任务将强制使用此模型）"))

        else:
            # 尝试按序号匹配
            try:
                idx = int(target) - 1
                if 0 <= idx < len(_WORKER_MODEL_CANDIDATES):
                    alias = _WORKER_MODEL_CANDIDATES[idx]
                    DYNAMIC_CONFIG["preferred_worker"] = alias
                    session._reset_system_prompt()
                    print(c(GREEN, f"  ✓ Worker 已锁定为 {c(CYAN, alias)}"))
                else:
                    print(c(RED, f"  ✗ 序号超出范围"))
            except ValueError:
                print(c(RED, f"  ✗ 未知模型 '{target}'。用 /worker 查看候选列表。"))

    # ── P0: /failures 命令 ────────────────────────────────
    elif verb == "/failures":
        sub = arg.lower().strip() if arg else "list"
        if sub == "clear":
            n = clear_failures()
            print(c(GREEN, f"  ✓ 已清空 {n} 条失败记录"))
        elif sub == "list" or sub.isdigit():
            n = int(sub) if sub.isdigit() else 20
            rows = list_failures(n)
            if not rows:
                print(c(GREEN, "  ✓ 暂无失败记录（防御性审计数据库为空）"))
            else:
                print(c(BOLD, f"\n  失败记录（最近 {len(rows)} 条）："))
                for i, r in enumerate(rows):
                    etype = r["error_type"] or "?"
                    ts = r["created_at"][:16] if r["created_at"] else ""
                    tool = r["tool_name"]
                    msg = r["error_msg"][:80].replace("\n", " ")
                    print(
                        c(GRAY, f"  [{i+1:2d}] ")
                        + c(RED, f"{tool:20}")
                        + c(YELLOW, f" {etype:15}")
                        + c(GRAY, f" {ts}")
                    )
                    print(c(GRAY, f"       {msg}"))
        else:
            print(c(GRAY, "  用法: /failures [list|clear|N]"))

    # ── /memo ────────────────────────────────────────────
    elif verb == "/memo":
        raw_content = (arg + " " + arg2).strip()
        result = _memo_to_skills(session, raw_content, verbose=True)
        col = GREEN if result.startswith("✓") else (YELLOW if result.startswith("⚠") else RED)
        print(c(col, f"  {result}"))

    # ── /skills ──────────────────────────────────────────
    elif verb == "/skills":
        from config import GLOBAL_SKILLS_PATH
        sub = arg.lower().strip() if arg else "toc"

        if sub == "path":
            print(c(GRAY, f"  {GLOBAL_SKILLS_PATH}"))

        elif sub == "view":
            if not GLOBAL_SKILLS_PATH.exists():
                print(c(GRAY, "  global_skills.md 尚未创建。完成任务后由 AI 自动生成，或使用 /memo。"))
            else:
                lines_all = GLOBAL_SKILLS_PATH.read_text(encoding="utf-8").splitlines()
                total     = len(lines_all)
                page_size = 40
                try:    page = max(0, int(arg2) - 1) if arg2 and arg2.isdigit() else 0
                except: page = 0
                start = page * page_size
                end   = min(start + page_size, total)
                print(c(BOLD, f"\n  global_skills.md  ({total} 行，显示 {start+1}-{end})\n"))
                for l in lines_all[start:end]:
                    if l.startswith("# "):    print(c(CYAN, l))
                    elif l.startswith("## "): print(c(YELLOW, l))
                    else:                     print(f"  {l}")
                if end < total:
                    rem = (total - end + page_size - 1) // page_size
                    print(c(GRAY, f"\n  还有 {rem} 页，/skills view <页码> 继续"))

        else:
            # 默认：显示分类目录
            try:
                from core.gsa import load_toc
                toc = load_toc(max_lines=120)
            except ImportError:
                if not GLOBAL_SKILLS_PATH.exists():
                    toc = "(尚未创建)"
                else:
                    toc = "\n".join(
                        l for l in GLOBAL_SKILLS_PATH.read_text(encoding="utf-8").splitlines()[:80]
                        if l.startswith("#")
                    )
            if not GLOBAL_SKILLS_PATH.exists():
                print(c(GRAY,
                    f"  global_skills.md 尚未创建。\n"
                    f"  路径: {GLOBAL_SKILLS_PATH}\n"
                    "  完成任务后 AI 自动创建，或用 /memo 手动存档。"
                ))
            else:
                print(c(BOLD, f"\n  📚 Global Skills Archive — 分类目录"))
                print(c(GRAY,  f"  路径: {GLOBAL_SKILLS_PATH}\n"))
                for line in toc.splitlines():
                    if line.startswith("# "):    print(c(CYAN + BOLD, f"  {line}"))
                    elif line.startswith("## "): print(c(YELLOW,      f"    {line}"))
                    else:                        print(c(GRAY,         f"  {line}"))
                print(c(GRAY, "\n  /skills view → 完整内容  |  /memo → 手动存档"))

    elif verb == "/chat":
        _handle_chat(arg, arg2, session)
    else:
        print(c(GRAY, f"  未知命令 '{verb}'，输入 /help"))

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

def cc_style_model_selector(
    models: dict, current_alias: str
) -> str | None:
    """
    Claude Code 风格的内联交互式模型选择器。

    使用 prompt_toolkit 底层组件构建：
      · 标题行（青色加粗）+ 灰色描述
      · 数字序号列表，光标态用 ❯ + 绿色高亮
      · 当前模型后显示 ✔ 标记
      · 底部灰色帮助栏
      · 完全透明背景，无边框

    Parameters
    ----------
    models : dict
        MODELS 字典，键为 alias，值为包含 desc/color/vision 的 dict
    current_alias : str
        当前正在使用的模型别名

    Returns
    -------
    str | None
        用户选择的模型别名，或 None（按 Esc 取消）
    """
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout, HSplit
    from prompt_toolkit.widgets import Frame
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.containers import Window

    entries = list(models.items())
    selected_idx = 0

    # ── 构建 FormattedTextControl ─────────────────────────
    def get_menu_fragments():
        """动态生成菜单文本片段（每次渲染时调用）。"""
        fragments = []

        # 标题
        fragments.append(("class:title", "  Select model\n"))
        fragments.append(("class:desc",   "  Choose a model for this session\n"))
        fragments.append(("",             "\n"))

        # 选项列表
        for i, (alias, cfg_m) in enumerate(entries):
            # 光标指示器
            if i == selected_idx:
                fragments.append(("class:cursor", "  ❯ "))
            else:
                fragments.append(("", "    "))

            # 序号
            fragments.append(("class:index", f"{i+1}."))

            # 模型名
            is_current = (alias == current_alias)
            if i == selected_idx:
                fragments.append(("class:selected", f" {alias}"))
            else:
                fragments.append(("", f" {alias}"))

            # 当前标记
            if is_current:
                fragments.append(("class:current", " ✔"))

            # 描述
            desc = cfg_m.get("desc", "")[:45]
            if desc:
                if i == selected_idx:
                    fragments.append(("class:desc-hi", f"  {desc}"))
                else:
                    fragments.append(("class:desc", f"  {desc}"))

            # 视觉标记
            if cfg_m.get("vision"):
                fragments.append(("class:vision", " 📷"))

            fragments.append(("", "\n"))

        # 底部帮助
        fragments.append(("", "\n"))
        fragments.append(("class:help", "  Enter to confirm · Esc to exit\n"))

        return fragments

    control = FormattedTextControl(get_menu_fragments)

    # ── KeyBindings ────────────────────────────────────────
    kb = KeyBindings()

    @kb.add("up")
    def _(event):
        nonlocal selected_idx
        selected_idx = (selected_idx - 1) % len(entries)

    @kb.add("down")
    def _(event):
        nonlocal selected_idx
        selected_idx = (selected_idx + 1) % len(entries)

    @kb.add("enter")
    def _(event):
        event.app.exit(result=entries[selected_idx][0])

    @kb.add("escape")
    def _(event):
        event.app.exit(result=None)

    @kb.add("c-c")
    def _(event):
        event.app.exit(result=None)

    # 数字键快速跳转（1-9）
    for _n in range(1, min(10, len(entries) + 1)):
        @kb.add(str(_n))
        def _(event, _idx=_n - 1):
            nonlocal selected_idx
            if _idx < len(entries):
                selected_idx = _idx

    # ── Layout ─────────────────────────────────────────────
    body = Window(content=control, always_hide_cursor=True)

    # ── Style ──────────────────────────────────────────────
    style = _PTStyle.from_dict({
        "title":      "#00afff bold",
        "desc":       "#888888",
        "desc-hi":    "#aaaaaa",
        "cursor":     "#00ff00 bold",
        "selected":   "#00ff00 bold",
        "current":    "#00d700",
        "index":      "#666666",
        "vision":     "#00afff",
        "help":       "#555555",
    })

    # ── Application ────────────────────────────────────────
    app = Application(
        layout=Layout(body),
        key_bindings=kb,
        style=style,
        mouse_support=False,
        full_screen=False,
    )

    return app.run()


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
    _md_indicators = ("```", "**", "| ", "## ", "- ", "1. ", "> ")
    has_md = any(indicator in text for indicator in _md_indicators)

    if has_md:
        try:
            _rich_console.print(_RichMarkdown(text))
            return
        except Exception:
            pass  # 渲染失败降级

    print(text)


def main():
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
    args, _ = parser.parse_known_args()
    config.QUIET_MODE = args.quiet  # mutate the single canonical flag in config

    # ★ 初始化 loguru 双端输出
    # · QUIET_MODE 下终端只输出 WARNING 及以上，减少干扰
    # · 文件始终记录 DEBUG 级别，保留完整诊断信息
    setup_logger(
        stderr_level="WARNING" if config.QUIET_MODE else "INFO",
        file_level="DEBUG",
    )
    logger.info(
        "PawnLogic {} starting | model={} quiet={}",
        config.VERSION,
        args.model or config.DEFAULT_MODEL,
        config.QUIET_MODE,
    )

    init_db()

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

    if not config.QUIET_MODE:
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
  {c(YELLOW,'/help')} 命令  {c(GREEN,'/low')} {c(YELLOW,'/mid')} {c(MAGENTA,'/deep')}  {c(CYAN,'/save /load')}  {c(MAGENTA,'/memorize')}  {c(YELLOW,'/init_project')}
""")
    else:
        key_sym = "✓" if key_ok else "✗"
        prx_sym = f" proxy={PROXY_STATUS}" if PROXY_STATUS else ""
        print(c(GRAY, f"PawnLogic {VERSION}  model={session.model_alias}  key{key_sym}{prx_sym}  /help"))

    # ════════════════════════════════════════════════════════
    # P2: CLI UX — FuzzyCompleter + WordCompleter + Bottom Toolbar
    # ════════════════════════════════════════════════════════

    # ── 扁平命令列表 + 右侧灰色说明 ──────────────────────
    _all_cmd_words = [
        "/model", "/clear", "/context", "/pin", "/unpin", "/cd", "/file",
        "/history", "/setkey", "/keys", "/save", "/load", "/sessions", "/del",
        "/memorize", "/knowledge", "/forget", "/init_project", "/state",
        "/low", "/mid", "/deep", "/normal", "/limits",
        "/tokens", "/ctx", "/iter", "/toolsize", "/fetchsize",
        "/webstatus", "/pwnenv", "/stats", "/time",
        "/worker", "/failures", "/memo", "/skills",
        "/chat", "/help", "/exit",
    ]

    _cmd_meta = {
        "/model":         "切换 AI 模型（/model ds-r1）",
        "/clear":         "清空上下文（保留 Pin 消息）",
        "/context":       "查看上下文大小 / token 估算",
        "/pin":           "固定最近 N 条消息（/pin msg 5 按序号）",
        "/unpin":         "解除所有 Pin",
        "/cd":            "切换工作目录",
        "/file":          "载入文件到上下文",
        "/history":       "查看带序号的消息历史",
        "/setkey":        "重新运行 API Key 配置向导",
        "/keys":          "显示各厂商 Key 配置状态",
        "/save":          "保存当前会话到 SQLite",
        "/load":          "加载历史会话",
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
        "/normal":        "重置到 /mid",
        "/limits":        "查看所有运行时限制",
        "/tokens":        "设置 max_tokens",
        "/ctx":           "设置上下文上限",
        "/iter":          "设置最大迭代轮次",
        "/toolsize":      "设置工具输出截断大小",
        "/fetchsize":     "设置网页抓取截断大小",
        "/webstatus":     "Jina / Pandoc / Lynx 工具状态",
        "/pwnenv":        "CTF/Pwn 工具链完整性检查",
        "/stats":         "本次会话 Token 用量统计",
        "/time":          "时间预算（/time 300 = 5 分钟）",
        "/worker":        "子任务 Worker 模型选择",
        "/failures":      "查看 / 清空失败记录",
        "/memo":          "手动存档技能到 GSA",
        "/skills":        "查看全局技能存档目录",
        "/chat":          "会话浏览器（list/view/find/tag/link）",
        "/help":          "显示帮助",
        "/exit":          "退出 PawnLogic",
    }

    # 合并一级命令 + 模型别名 + 子命令
    _all_words = list(_all_cmd_words)
    _all_meta  = dict(_cmd_meta)
    for _alias, _minfo in MODELS.items():
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
    _all_words.extend(["/worker auto", "/skills view", "/skills path"])
    _all_meta["/worker auto"] = "恢复自动路由"
    _all_meta["/skills view"] = "查看完整技能文件"
    _all_meta["/skills path"] = "显示技能文件路径"

    # ── readline 历史文件路径 ─────────────────────────────
    _history_path = str(Path.home() / ".pawnlogic" / ".input_history")

    if _HAS_PROMPT_TOOLKIT:
        # ── WordCompleter + FuzzyCompleter（乱序/错别字匹配）──
        _word_completer = WordCompleter(
            _all_words,
            meta_dict=_all_meta,
            ignore_case=True,
            sentence=True,
        )
        _fuzzy = FuzzyCompleter(_word_completer)

        try:
            _pt_history = FileHistory(_history_path)
        except Exception:
            from prompt_toolkit.history import InMemoryHistory
            _pt_history = InMemoryHistory()

        # ── Bottom Toolbar：显示当前模型 / 档位 / 目录 ────
        def _bottom_toolbar():
            _m = session.model_alias
            _tier = "MID"
            if DYNAMIC_CONFIG["max_tokens"] <= 4096:
                _tier = "LOW"
            elif DYNAMIC_CONFIG["max_tokens"] >= 32768:
                _tier = "DEEP"
            _tb = DYNAMIC_CONFIG.get("time_budget_sec", 0)
            _time_str = f"  ⏱ {_tb}s" if _tb > 0 else ""
            return HTML(
                f" <b>Model:</b> {_m}"
                f"  <b>Tier:</b> {_tier}"
                f"  <b>Dir:</b> {session.cwd}"
                f"  <b>Phase:</b> {session.current_phase}"
                f"{_time_str}"
                f"  <b>Ctrl-C</b>=exit"
            )

        # ── 样式：彻底透明化，无灰色方块 ──────────────────
        _pawn_style = _PTStyle.from_dict({
            # 输入提示符
            "prompt": "ansigreen bold",
            "you":    "bold",

            # 1. 彻底清除所有容器的默认背景
            "completion-menu":                    "bg:default fg:#bbbbbb",
            "completion-menu.completion":         "bg:default fg:#bbbbbb",
            "completion-menu.meta.completion":    "bg:default fg:#666666",

            # 2. 选中行（极暗灰底 + 白字，meta 同步变暗）
            "completion-menu.completion.current":      "bg:#333333 fg:#ffffff",
            "completion-menu.meta.completion.current": "bg:#333333 fg:#aaaaaa",

            # 3. 模糊匹配字母高亮（荧光绿）
            "completion-menu.completion.character-match": "fg:#00d787 bold",

            # 4. 彻底隐形滚动条
            "scrollbar.background": "bg:default",
            "scrollbar.button":     "bg:default",

            # 5. 底部状态栏
            "bottom-toolbar": "bg:#222222 fg:#cccccc",
        })

        _pt_session = PromptSession(
            completer=_fuzzy,
            auto_suggest=AutoSuggestFromHistory(),
            history=_pt_history,
            complete_while_typing=True,
            complete_style=CompleteStyle.COLUMN,
            mouse_support=False,
            bottom_toolbar=_bottom_toolbar,
            reserve_space_for_menu=10,
        )

        if not config.QUIET_MODE:
            print(c(GRAY, "  🐚 FuzzyCompleter 就绪（模糊匹配 + 多列补全 + 底部工具栏）"))
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

        if not config.QUIET_MODE:
            print(c(GRAY, "  🐚 readline 降级模式（Tab 补全可用，无模糊匹配）"))
            if _PT_IMPORT_ERROR:
                print(c(YELLOW, f"  ⚠ prompt_toolkit 加载失败: {_PT_IMPORT_ERROR}"))
                print(c(YELLOW, f"     Python: {sys.executable}"))
                print(c(YELLOW, f"     修复: 在 venv 中执行 pip install prompt_toolkit rich"))
                print(c(YELLOW, f"     或重新安装: pip install -e ."))

    # ── 主循环 ────────────────────────────────────────────
    while True:
        try:
            print()  # 确保提示符在新行
            if _HAS_PROMPT_TOOLKIT:
                raw = _pt_session.prompt(
                    [("class:prompt", "▶ "), ("class:you", "You > ")],
                    style=_pawn_style,
                ).strip()
            else:
                raw = input(cp(BOLD+GREEN, "▶ ") + cp(BOLD, "You > ")).strip()
        except (EOFError, KeyboardInterrupt):
            print(c(CYAN, "\n  Goodbye! 👋")); break
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
                    if _cmd_rest:
                        _corrected_full = f"{_corrected} {_cmd_rest}"
                    else:
                        _corrected_full = _corrected
                    print(c(YELLOW, f"  ✔ 已自动修正: {_cmd_verb} → {_corrected}"))
                    raw = _corrected_full
            handle_slash(raw, session)
            continue
        try:
            session.run_turn(raw)
        except KeyboardInterrupt:
            print(c(YELLOW, "\n  [已中断]"))

if __name__ == "__main__":
    main()
