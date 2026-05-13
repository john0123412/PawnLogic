#!/usr/bin/env python3
"""
PawnLogic 1.1 (Expert Edition) — main.py
多 Provider · 多模态视觉 · SQLite · CoT 引导 · GSA 技能存档 · 规格驱动 · GSD架构

快速部署（WSL2 Ubuntu）:
  cp -r PawnLogic_1.1 ~/.local/share/pawnlogic
  chmod +x ~/.local/share/pawnlogic/main.py
  ln -sf ~/.local/share/pawnlogic/pawn.sh ~/.local/bin/pawn
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
  source ~/.bashrc
  pawn   # 首次运行会自动进入 API Key 配置向导
"""
import os, sys, shutil, getpass, argparse, time, re
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    print("\033[91m  ✗ 缺少 nest_asyncio，请执行: pip install nest_asyncio\033[0m")
    sys.exit(1)
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
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.formatted_text import StyleAndTextTuples
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

import config  # for config.QUIET_MODE / config.USER_MODE mutation after argparse
from config import (
    VERSION, DYNAMIC_CONFIG, NORMAL_CONFIG,
    TIER_LOW, TIER_MID, TIER_DEEP, TIER_MAX,
    MODELS, DEFAULT_MODEL, DB_PATH, PROVIDERS,
    validate_api_key, list_vision_models,
    user_friendly_error,
    get_api_format, get_provider_config,
    save_custom_provider, remove_custom_provider,
    CUSTOM_PROVIDERS_PATH,
)
from utils.ansi       import c, cp, rl_wrap, BOLD, DIM, GRAY, CYAN, GREEN, YELLOW, RED, MAGENTA, Spinner
from core.session     import AgentSession, _ctx_chars, STATE_FILENAME
from core.api_client  import stream_request
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
                               session_delete, session_rename, memorize)
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
    ("7", "ANTHROPIC_API_KEY",  "Anthropic",      "claude-opus-4-7 · claude-sonnet-4-6", False),
    ("8", None,                 "本地 Ollama",    "需先运行 ollama serve，无需 Key",        True),
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
                "ANTHROPIC_API_KEY":  "https://console.anthropic.com/settings/keys",
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


def _handle_workspace_cmd(arg: str, arg2: str, session):
    """``/workspace`` 子命令分派器。

    支持：
        /workspace                         — 等价 status
        /workspace status                  — 概览
        /workspace cleanup                 — 等价 cleanup plan
        /workspace cleanup plan            — 生成清理清单（只读 + 备份）
        /workspace cleanup execute         — 按清单归档 + DB 同步
        /workspace cleanup restore [path]  — 从备份回滚
    """
    from core import workspace_cleanup as wc

    sub  = (arg or "status").strip().lower()
    sub2 = (arg2 or "").strip().lower()

    # ── status ─────────────────────────────────────────
    if sub == "status":
        info = wc.workspace_status()
        if not info.get("exists"):
            print(c(RED, "  workspace 目录不存在"))
            return
        print(c(BOLD, "\n  Workspace 状态:"))
        print(f"  路径        : {c(CYAN, info['path'])}")
        print(f"  总大小      : {c(GREEN, info['size_human'])}")
        print(f"  文件数      : {info['n_files']}")
        print(f"  子目录      : {info['n_dirs']}（其中 session_*: {info['session_dirs']}）")
        print(f"  symlinks   : {info['n_symlinks']}")
        print(c(GRAY, f"  DB 会话数  : {info['db_sessions']}（workspace_dir 为空: {info['db_empty']}）"))
        if info["last_backup"]:
            print(c(GRAY, f"  最近备份   : {info['last_backup']}"))
        print()
        return

    # ── cleanup ────────────────────────────────────────
    if sub == "cleanup":
        action = sub2 or "plan"

        if action == "plan":
            print(c(YELLOW, "  ▶ Phase 0: 生成全量备份..."))
            try:
                bak = wc.make_backup()
                print(c(GREEN, f"    ✓ 备份: {bak.name} ({bak.stat().st_size // 1024} KB)"))
            except Exception as exc:
                print(c(RED, f"    ✗ 备份失败: {exc}"))
                return

            print(c(YELLOW, "  ▶ Phase 1: 扫描 + 分类 (只读)..."))
            rows, db = wc.scan()
            plan_path = wc.render_plan(rows, db)
            stats = {}
            for r in rows:
                stats[r["confidence"]] = stats.get(r["confidence"], 0) + 1
            print(c(GREEN, f"    ✓ 清单: {plan_path}"))
            print(c(BOLD, "\n  扫描结果:"))
            for k in ("LOCKED", "SAFE", "MID", "HIGH", "SENSITIVE"):
                cnt = stats.get(k, 0)
                if cnt:
                    print(f"    {wc._CONF_ICON[k]} {k:10} {cnt}")
            print(c(GRAY, "\n  审阅清单后，使用 /workspace cleanup execute 按建议归档"))
            print(c(GRAY, "  或编辑清单文件后再 execute（人工确认 SENSITIVE 项）"))
            return

        elif action == "execute":
            print(c(YELLOW, "  ▶ 重新扫描以获取最新状态..."))
            rows, db = wc.scan()
            plan_action_count = sum(1 for r in rows if r["action"] == "ARCHIVE")
            if plan_action_count == 0:
                print(c(GREEN, "  ✓ 没有可归档项，workspace 已经整洁"))
                return
            print(c(YELLOW, f"  ▶ 即将归档 {plan_action_count} 项 + DB workspace_dir 补写..."))
            try:
                result = wc.execute_cleanup(rows, db)
                print(c(GREEN, f"    ✓ 归档: {len(result['moved'])} 项"))
                print(c(GRAY,  f"      跳过: {len(result['skipped'])} 项"))
                print(c(GREEN, f"    ✓ DB 补写: {result['db_updated']} 条会话"))
                print(c(GRAY,  f"    归档目录: {result['archive_root']}"))
                print(c(GRAY,  f"    Manifest: {result['manifest']}"))
            except Exception as exc:
                logger.error("cleanup execute failed | exc={!r}", exc)
                print(c(RED, f"    ✗ 失败: {exc}"))
            return

        elif action == "restore":
            backup_arg = parts[3].strip() if (parts := arg2.split(None, 1)) and len(parts) > 1 else ""
            backup_path = Path(backup_arg).expanduser() if backup_arg else None
            print(c(YELLOW, "  ⚠ 即将从备份回滚 workspace（当前内容会被重命名为 _replaced_<ts>/）"))
            try:
                from core.workspace_cleanup import restore_from_backup
                result = restore_from_backup(backup_path)
                if result["ok"]:
                    print(c(GREEN, f"    ✓ 已回滚: {result['restored_from']}"))
                    if result.get("old_workspace_renamed_to"):
                        print(c(GRAY, f"      旧 workspace 备份: {result['old_workspace_renamed_to']}"))
                else:
                    print(c(RED, f"    ✗ {result.get('error')}"))
            except Exception as exc:
                logger.error("cleanup restore failed | exc={!r}", exc)
                print(c(RED, f"    ✗ 失败: {exc}"))
            return

        else:
            print(c(RED, f"  未知子命令 'cleanup {action}'"))
            print(c(GRAY, "  可用: plan / execute / restore"))
            return

    print(c(RED, f"  未知子命令 'workspace {sub}'"))
    print(c(GRAY, "  可用: status | cleanup [plan|execute|restore]"))


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
            display_name = r["name"] or r["auto_name"] or r["workspace_alias"]
            name_str = c(YELLOW, display_name) if display_name else c(GRAY, "(未命名)")
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
        display_name = meta["name"] or meta["auto_name"] or meta["workspace_alias"] or "(未命名)"
        print(c(BOLD, f"\n  ╔ 会话 {sid}"))
        print(c(GRAY, f"  ║ 名称  : {display_name}"))
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
# /provider 命令处理
# ════════════════════════════════════════════════════════

def _handle_provider_cmd(sub: str, sub_arg: str, session):
    """处理 /provider 子命令。"""
    import getpass

    # ── /provider 无参数 — 交互式面板 ─────────────────
    if not sub:
        print(f"""
{c(BOLD+CYAN, "  ╔══════════════════════════════════════════╗")}
{c(BOLD+CYAN, "  ║")}  {c(BOLD, "Provider 管理面板")}                      {c(BOLD+CYAN, "║")}
{c(BOLD+CYAN, "  ╚══════════════════════════════════════════╝")}

  {c(CYAN, "[1]")} 查看所有 Provider
  {c(CYAN, "[2]")} 添加自定义 Provider
  {c(CYAN, "[3]")} 删除自定义 Provider
  {c(CYAN, "[4]")} 测试连通性
  {c(GRAY, "[0]")} 返回
""")
        try:
            choice = input(cp(BOLD, "  请输入序号: ")).strip()
        except (EOFError, KeyboardInterrupt):
            print(); return
        if choice == "1":
            _provider_list()
        elif choice == "2":
            _provider_add()
        elif choice == "3":
            _provider_remove()
        elif choice == "4":
            _provider_test(session)
        return

    # ── /provider list ────────────────────────────────
    if sub == "list":
        _provider_list()
    elif sub == "add":
        _provider_add()
    elif sub == "remove":
        _provider_remove(sub_arg)
    elif sub == "test":
        _provider_test(session, sub_arg)
    else:
        print(c(RED, f"  ✗ 未知子命令 '{sub}'。可用: list · add · remove · test"))


def _provider_list():
    """列出所有 Provider 状态。"""
    print(c(BOLD, "\n  Provider 列表："))
    for pname, pinfo in PROVIDERS.items():
        fmt   = pinfo.get("api_format", "openai")
        label = pinfo.get("label", pname)
        env   = pinfo.get("api_key_env", "")
        val   = os.environ.get(env, "") if env else ""
        if val:
            masked = val[:8] + "..." + val[-4:] if len(val) > 12 else "***"
            ktag = c(GREEN, f"✓ ({masked})")
        elif not env:
            ktag = c(GRAY, "无需 Key")
        else:
            ktag = c(RED, "✗ 未配置")
        fmt_tag = c(MAGENTA, "[Anthropic]") if fmt == "anthropic" else c(GRAY, "[OpenAI]")
        hint = pinfo.get("models_hint", "")
        print(f"  {c(CYAN, f'{pname:16}')}{fmt_tag:14} {label:24} {ktag}")
        if hint:
            print(f"  {'':16}{c(GRAY, hint)}")
    print(c(GRAY, f"\n  自定义配置: {CUSTOM_PROVIDERS_PATH}"))
    print()


def _provider_add():
    """交互式添加自定义 Provider。"""
    print(c(BOLD, "\n  添加自定义 Provider"))
    print(c(GRAY, "  （Key 存入 .env，配置存入 ~/.pawnlogic/custom_providers.json）\n"))

    try:
        name = input(cp(BOLD, "  Provider 名称 (短ID，如 my_relay): ")).strip()
    except (EOFError, KeyboardInterrupt):
        print(); return
    if not name or name in PROVIDERS:
        print(c(RED, f"  ✗ 名称无效或已存在: {name}"))
        return

    # API 格式选择
    print(f"\n  {c(BOLD, 'API 格式:')}")
    print(f"    {c(CYAN, '[1]')} OpenAI Chat Completions 格式")
    print(f"    {c(CYAN, '[2]')} Anthropic Messages 格式")
    try:
        fmt_choice = input(cp(BOLD, "  选择 [1/2]: ")).strip()
    except (EOFError, KeyboardInterrupt):
        print(); return
    api_format = "anthropic" if fmt_choice == "2" else "openai"

    # Base URL
    default_path = "/v1/messages" if api_format == "anthropic" else "/v1/chat/completions"
    try:
        base_url = input(cp(BOLD, f"  Base URL (如 https://my-relay.com{default_path}): ")).strip()
    except (EOFError, KeyboardInterrupt):
        print(); return
    if not base_url:
        print(c(RED, "  ✗ URL 不能为空"))
        return
    # 自动补全 path
    if not base_url.endswith(default_path) and not base_url.endswith("/"):
        base_url = base_url.rstrip("/") + default_path

    # API Key
    env_var_name = f"{name.upper().replace('-', '_')}_API_KEY"
    try:
        key = getpass.getpass(c(BOLD, f"  API Key (输入时不显示，存入 .env → {env_var_name}): ")).strip()
    except (EOFError, KeyboardInterrupt):
        print(); return

    # 模型 ID
    try:
        model_id = input(cp(BOLD, "  模型 ID (如 gpt-4o / claude-sonnet-4-6): ")).strip()
    except (EOFError, KeyboardInterrupt):
        print(); return
    if not model_id:
        print(c(RED, "  ✗ 模型 ID 不能为空"))
        return

    # 别名
    default_alias = model_id.split("/")[-1]
    try:
        alias = input(cp(BOLD, f"  模型别名 (用于 /model，默认 {default_alias}): ")).strip()
    except (EOFError, KeyboardInterrupt):
        print(); return
    if not alias:
        alias = default_alias

    # 写入 .env
    if key:
        env_path = Path(__file__).resolve().parent / ".env"
        env_line = f'\n{env_var_name}="{key}"\n'
        try:
            existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
            if env_var_name not in existing:
                env_path.write_text(existing + env_line, encoding="utf-8")
            os.environ[env_var_name] = key
        except Exception:
            os.environ[env_var_name] = key
        # 同时写入 shell config
        _write_key_to_shell(env_var_name, key)
        print(c(GREEN, f"  ✓ Key 已保存 → .env ({env_var_name})"))

    # 构建配置
    prov_cfg = {
        "base_url":    base_url,
        "api_key_env": env_var_name,
        "label":       f"Custom ({name})",
        "api_format":  api_format,
    }
    models_cfg = {
        alias: {
            "id":       model_id,
            "provider": name,
            "desc":     f"Custom {model_id} via {name}",
            "color":    "\033[37m",
            "vision":   False,
        }
    }

    # 保存到 JSON
    save_custom_provider(name, prov_cfg, models_cfg)

    # 热加载到内存
    PROVIDERS[name] = prov_cfg
    MODELS[alias] = models_cfg[alias]

    print(c(GREEN, f"\n  ✓ Provider '{name}' 已添加"))
    print(c(GRAY,  f"    格式: {api_format}"))
    print(c(GRAY,  f"    URL:  {base_url}"))
    print(c(GRAY,  f"    模型: {alias} → {model_id}"))
    print(c(GRAY,  f"    配置: {CUSTOM_PROVIDERS_PATH}"))
    print(c(CYAN,  f"    使用: /model {alias}"))
    print()


def _provider_remove(name: str = ""):
    """删除自定义 Provider。"""
    if not name:
        # 列出自定义 provider 供选择
        if not CUSTOM_PROVIDERS_PATH.exists():
            print(c(GRAY, "\n  没有自定义 Provider。"))
            return
        try:
            data = json.loads(CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8"))
        except Exception:
            print(c(RED, "\n  ✗ 读取配置文件失败"))
            return
        custom = list(data.get("providers", {}).keys())
        if not custom:
            print(c(GRAY, "\n  没有自定义 Provider。"))
            return
        print(c(BOLD, "\n  自定义 Provider:"))
        for i, n in enumerate(custom, 1):
            print(f"    {c(CYAN, f'[{i}]')} {n}")
        try:
            choice = input(cp(BOLD, "  输入序号或名称: ")).strip()
        except (EOFError, KeyboardInterrupt):
            print(); return
        if choice.isdigit() and 1 <= int(choice) <= len(custom):
            name = custom[int(choice) - 1]
        elif choice in custom:
            name = choice
        else:
            print(c(RED, f"  ✗ 无效选择: {choice}"))
            return

    if remove_custom_provider(name):
        # 从内存中移除
        if name in PROVIDERS:
            del PROVIDERS[name]
        to_remove = [a for a, m in MODELS.items() if m.get("provider") == name]
        for a in to_remove:
            del MODELS[a]
        print(c(GREEN, f"  ✓ 已删除 Provider '{name}'"))
    else:
        print(c(RED, f"  ✗ 未找到自定义 Provider: {name}"))


def _provider_test(session, model_alias: str = ""):
    """测试 Provider 连通性。"""
    if not model_alias:
        try:
            model_alias = input(cp(BOLD, "  输入要测试的模型别名: ")).strip()
        except (EOFError, KeyboardInterrupt):
            print(); return
    if model_alias not in MODELS:
        print(c(RED, f"  ✗ 未知模型: {model_alias}"))
        return

    ok, env = validate_api_key(model_alias)
    if not ok:
        print(c(RED, f"  ✗ {env} 未配置。用 /setkey 或 /provider add 配置。"))
        return

    cfg = get_provider_config(model_alias)
    print(c(GRAY, f"  测试 {model_alias} ({cfg['api_format']}) → {cfg['base_url']} ..."))
    print(c(GRAY, f"  发送 max_tokens=1 测试请求..."))

    from core.api_client import call_once
    text, err = call_once(
        [{"role": "user", "content": "Say OK"}],
        model_alias, max_tokens=1,
    )
    if err:
        print(c(RED, f"  ✗ 测试失败: {err}"))
    else:
        print(c(GREEN, f"  ✓ 连通成功！响应: {text[:80]}"))


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

    # ── Provider 管理 ──────────────────────────────────
    elif verb == "/provider":
        _handle_provider_cmd(arg, arg2, session)

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
                    fmt    = get_api_format(alias)
                    ftag   = c(MAGENTA, " [A]")  if fmt == "anthropic" else ""
                    print(f"    {c(cfg_m['color'], f'{alias:14}')}{cfg_m['desc']:30} {ktag}{vtag}{ftag}{tick}")
                print(c(GRAY, "\n  用法: /model <alias>  📷=支持视觉  [A]=Anthropic 格式"))
        elif arg in MODELS:
            session.model_alias = arg
            ok, env = validate_api_key(arg)
            if not ok:
                print(c(YELLOW, f"  ⚠ 已切换到 {arg}，但 {env} 未设置。用 /setkey 配置。"))
            else:
                print(c(GREEN, f"  ✓ 已切换到 {c(MODELS[arg]['color'], arg)}"))
        else:
            print(c(RED, f"  ✗ 未知模型 '{arg}'"))

    # ── P6: 双模输出 /mode ─────────────────────────────────
    elif verb == "/mode":
        config.USER_MODE = not config.USER_MODE
        if config.USER_MODE:
            print(c(GREEN, "  ✓ 已切换到 USER 模式（简洁输出，屏蔽底层错误）"))
        else:
            print(c(CYAN, "  ✓ 已切换到 DEV 模式（极致透明，显示所有细节）"))

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

    # ── 成本微操工具集 ───────────────────────────────────
    elif verb == "/undo":
        n = int(arg) if arg.isdigit() else 1
        removed, _last_text = session.undo(n)
        if removed:
            print(c(GREEN, f"  ↩ 已撤回 {removed} 条消息"))
        else:
            print(c(GRAY, "  ↩ 无可撤回的消息"))

    elif verb == "/compact":
        # 轻量模型总结 → 清空历史（保留 Pin）→ 总结作首条
        _summary_prompt = (
            "请用 3-5 句话总结以下对话的关键进展、已确认的结论和待办事项。"
            "保持技术细节（如偏移量、地址、文件路径）。仅输出总结，不要寒暄。"
        )
        # 构建临时消息：system + 对话历史 + 总结指令
        _compact_msgs = [
            m for m in session.messages
            if m.get("role") != "system" and not m.get("_pinned")
        ]
        if len(_compact_msgs) < 2:
            print(c(GRAY, "  ↕ 上下文太短，无需压缩"))
        else:
            print(c(CYAN, "  🔄 正在压缩上下文..."))
            _summarize_msgs = [
                {"role": "system", "content": "你是一个对话摘要助手。"},
                *_compact_msgs,
                {"role": "user", "content": _summary_prompt},
            ]
            _summary_buf = ""
            try:
                for delta in stream_request(
                    _summarize_msgs, session.model_alias,
                    max_tokens=1024, tools_schema=None,
                ):
                    if "_error" in delta:
                        print(c(RED, f"  ✗ 摘要生成失败: {delta['_error']}"))
                        _summary_buf = ""
                        break
                    choices = delta.get("choices") or []
                    if not choices:
                        continue
                    chunk = choices[0].get("delta", {}).get("content", "")
                    if chunk:
                        _summary_buf += chunk
            except Exception as e:
                print(c(RED, f"  ✗ 摘要异常: {e}"))
                _summary_buf = ""

            if _summary_buf:
                pinned = [m for m in session.messages if m.get("_pinned")]
                session.messages.clear()
                session._reset_system_prompt()
                session.messages.extend(pinned)
                session.messages.append({
                    "role": "assistant",
                    "content": f"📝 [Compact Summary]\n{_summary_buf}",
                    "_pinned": True,
                })
                _chars = _ctx_chars(session.messages)
                print(c(GREEN,
                    f"  ✓ 已压缩 | 保留 {len(pinned)} 条 Pin + 摘要 | "
                    f"上下文: {_chars//4:,} tokens"
                ))

    elif verb == "/think":
        if not arg:
            print(c(RED, "  用法: /think <prompt>  (单次触发推理模式)"))
        else:
            # 单次触发：在本次请求中切换到推理 Worker 或增加 thinking 预算
            _think_alias = None
            for _candidate in ("ds-r1", "qwq", "ds-chat"):
                _ok, _ = validate_api_key(_candidate)
                if _ok:
                    _think_alias = _candidate
                    break
            if _think_alias:
                old_alias = session.model_alias
                session.model_alias = _think_alias
                print(c(MAGENTA, f"  🧠 推理模式: {old_alias} → {_think_alias}"))
                try:
                    session.run_turn(arg)
                finally:
                    session.model_alias = old_alias
                    print(c(GRAY, f"  ↩ 已恢复模型: {old_alias}"))
            else:
                # 无推理 Worker，直接以当前模型执行（注入 thinking 指令）
                _think_prefix = (
                    "[THINKING MODE] 请逐步推理，展示完整思维链。\n\n"
                )
                session.run_turn(_think_prefix + arg)

    elif verb == "/ping":
        # 极简保活请求，刷新缓存 TTL
        _ping_msgs = [
            {"role": "system", "content": "respond with 'pong' only."},
            {"role": "user", "content": "ping"},
        ]
        _ping_buf = ""
        print(c(CYAN, "  🏓 ping..."), end="", flush=True)
        try:
            for delta in stream_request(
                _ping_msgs, session.model_alias,
                max_tokens=16, tools_schema=None,
            ):
                if "_error" in delta:
                    print(c(RED, f" ✗ {delta['_error']}"))
                    break
                choices = delta.get("choices") or []
                if not choices:
                    continue
                chunk = choices[0].get("delta", {}).get("content", "")
                _ping_buf += chunk
            if _ping_buf:
                print(c(GREEN, f" {_ping_buf.strip()} ✓"))
            else:
                print(c(GREEN, " pong ✓"))
        except Exception as e:
            print(c(RED, f" ✗ {e}"))

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

    elif verb == "/resume":
        if arg:
            # /resume <n> — 直接恢复指定序号
            result = session_load(session, arg)
            print(c(GREEN if result.startswith("OK") else RED, f"  {result}"))
        else:
            # /resume — 显示最近会话列表并交互选择
            from core.memory import list_sessions as _ls
            rows = _ls(10)
            if not rows:
                print(c(GRAY, "  暂无已保存会话"))
            else:
                print(c(BOLD, "\n  最近会话："))
                for i, r in enumerate(rows):
                    name = r["name"] or "(未命名)"
                    ts   = str(r["updated_at"])[:16] if r["updated_at"] else ""
                    msgs = r["msg_count"] if r["msg_count"] else 0
                    model = r["model"] if r["model"] else ""
                    print(
                        c(GRAY, f"  [{i+1:2d}] ") +
                        c(CYAN, name) +
                        c(GRAY, f"  {ts}  {msgs}条  model={model}")
                    )
                print(c(GRAY, "\n  输入序号恢复，或 Enter 取消"))
                try:
                    pick = input(cp(BOLD, "  选择 [1-" + str(len(rows)) + "]: ")).strip()
                    if pick.isdigit():
                        idx = int(pick) - 1
                        if 0 <= idx < len(rows):
                            result = session_load(session, str(idx + 1))
                            print(c(GREEN if result.startswith("OK") else RED, f"  {result}"))
                        else:
                            print(c(RED, "  序号超出范围"))
                except (EOFError, KeyboardInterrupt):
                    print()

    elif verb == "/sessions":
        print(c(BOLD, f"\n  已保存会话 (DB: {DB_PATH})："))
        print(session_list())

    elif verb == "/del":
        if not arg: print(c(RED, "  用法: /del <name 或 序号>"))
        else:
            result = session_delete(session, arg)
            print(c(GREEN if result.startswith("OK") else RED, f"  {result}"))

    elif verb == "/rename":
        if not arg or not arg2:
            print(c(RED, "  用法: /rename <序号或名称> <新名称>"))
        else:
            result = session_rename(session, arg, arg2)
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

    elif verb == "/max":
        DYNAMIC_CONFIG.update(TIER_MAX)
        session._reset_system_prompt()
        print(c(BOLD+RED, "  💀 /max 极限火力（iter=100, ctx=600k, 60min）")); print(_fmt_config())

    elif verb == "/normal":
        DYNAMIC_CONFIG.update(NORMAL_CONFIG)
        session._reset_system_prompt()
        print(c(GREEN, "  ✓ 已重置到 /mid")); print(_fmt_config())

    elif verb == "/limits":
        print(c(BOLD, "\n  当前运行时限制：")); print(_fmt_config())
        print(c(GRAY, "  /low /mid /deep /max  |  /tokens /ctx /iter /toolsize /fetchsize"))

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

    elif verb == "/browserstatus":
        try:
            from tools.browser_ops import browser_tool_status
            print(c(BOLD, "\n  Scrapling 浏览器工具状态：")); print(browser_tool_status())
        except ImportError:
            print(c(RED, "  ✗ browser_ops 模块未加载"))

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
    # ── P3: /docker 命令 ────────────────────────────────
    elif verb == "/docker":
        from tools.docker_sandbox import (
            _get_docker_client, docker_status, _active_containers, DEFAULT_DOCKER_IMAGES,
        )
        sub = arg.lower().strip() if arg else "status"
        if sub == "status":
            print(c(BOLD, "\n  Docker 状态："))
            print(docker_status())
            print(c(GRAY, f"\n  可用镜像别名: {', '.join(DEFAULT_DOCKER_IMAGES.keys())}"))
            print(c(GRAY, "  用法: /docker status | /docker images | /docker ps | /docker containers"))
        elif sub == "images":
            client = _get_docker_client()
            if not client:
                print(c(RED, f"  ✗ Docker 不可用"))
            else:
                images = client.images.list()
                print(c(BOLD, f"\n  本地镜像（{len(images)} 个）："))
                for img in images[:20]:
                    tags = ", ".join(img.tags) if img.tags else "<none>"
                    size_mb = img.attrs.get("Size", 0) / (1024 * 1024)
                    print(f"  {c(CYAN, tags):40} {c(GRAY, f'{size_mb:.0f}MB')}")
        elif sub in ("ps", "containers"):
            client = _get_docker_client()
            if not client:
                print(c(RED, f"  ✗ Docker 不可用"))
            else:
                containers = client.containers.list(all=True)
                pawn_containers = [ct for ct in containers if ct.labels.get("pawn") == "true"]
                print(c(BOLD, f"\n  PawnLogic 容器（{len(pawn_containers)} 个）："))
                for ct in pawn_containers:
                    name = ct.labels.get("pawn_name", ct.name)
                    status_color = GREEN if ct.status == "running" else RED
                    print(f"  {c(CYAN, name):20} {c(status_color, ct.status):12} {c(GRAY, ct.id[:12])}")
                if not pawn_containers:
                    print(c(GRAY, "  (无 PawnLogic 容器)"))
        elif sub == "pull":
            image = arg2.strip() if arg2 else ""
            if not image:
                print(c(RED, "  用法: /docker pull <镜像名或别名>"))
            else:
                from tools.docker_sandbox import _resolve_image
                resolved = _resolve_image(image)
                client = _get_docker_client()
                if not client:
                    print(c(RED, f"  ✗ Docker 不可用"))
                else:
                    print(c(YELLOW, f"  📥 正在拉取 {resolved} ..."))
                    try:
                        client.images.pull(resolved)
                        print(c(GREEN, f"  ✓ {resolved} 拉取完成"))
                    except Exception as e:
                        print(c(RED, f"  ✗ 拉取失败: {e}"))
        elif sub == "clean":
            from tools.docker_sandbox import docker_prune_resources
            print(c(YELLOW, "  🧹 正在清理 Docker 资源..."))
            result = docker_prune_resources()
            col = GREEN if result.startswith("✓") else RED
            print(c(col, f"  {result}"))
        else:
            print(c(GRAY, "  用法: /docker status | /docker images | /docker ps | /docker pull <镜像> | /docker clean"))

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

        elif sub == "packs":
            # 显示本地技能包列表
            from core.session import _skill_scanner
            from config import SKILLS_DIR
            packs = _skill_scanner.scan_all()
            if not packs:
                print(c(GRAY,
                    f"  skills/ 目录下暂无技能包。\n"
                    f"  路径: {SKILLS_DIR}\n"
                    "  创建: mkdir -p skills/my_skill && echo '# My Skill' > skills/my_skill/skill.md"
                ))
            else:
                print(c(BOLD, f"\n  📦 本地技能包（{len(packs)} 个）"))
                print(c(GRAY,  f"  路径: {SKILLS_DIR}\n"))
                print(_skill_scanner.format_list())
                print(c(GRAY, "\n  /skillpack rescan → 重新扫描  |  /skillpack <名称> → 查看详情"))

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
                print(c(GRAY, "\n  /skills view → 完整内容  |  /skills packs → 本地技能包  |  /memo → 手动存档"))

    # ── /skillpack：本地技能包管理 ──────────────────────────
    elif verb in ("/skillpack", "/sp"):
        from core.skill_manager import SkillScanner
        from config import SKILLS_DIR
        sub = arg.lower().strip() if arg else "list"

        if sub == "rescan":
            # 清除缓存并重新扫描
            from core.session import _skill_scanner
            _skill_scanner.invalidate_cache()
            packs = _skill_scanner.scan_all()
            print(c(GREEN, f"  ✓ 已重新扫描 skills/ 目录，发现 {len(packs)} 个技能包"))
            if packs:
                print(c(BOLD, "\n  本地技能包："))
                print(_skill_scanner.format_list())

        elif sub == "sync":
            # 全球同步：遍历所有带 .git 的技能包，git pull
            from core.session import _skill_scanner
            if config.USER_MODE:
                with Spinner("正在同步技能包"):
                    results = _skill_scanner.sync_packs()
            else:
                print(c(CYAN, "  🔄 正在同步所有带 .git 的技能包..."))
                results = _skill_scanner.sync_packs()
            if not results:
                print(c(GRAY, "  没有发现带 .git 的技能包目录"))
            else:
                ok_count = sum(1 for r in results if r["status"] == "ok")
                err_count = len(results) - ok_count
                print(c(GREEN, f"  ✓ 同步完成: {ok_count} 成功, {err_count} 失败"))
                for r in results:
                    tag = c(GREEN, "✓") if r["status"] == "ok" else c(RED, "✗")
                    detail = ""
                    if not config.USER_MODE:
                        detail = c(GRAY, f"  {r['detail']}")
                    print(f"    {tag} {r['name']}{detail}")
                if err_count > 0:
                    print(c(GRAY, "  提示: 手动进入失败的目录执行 git pull 查看详细错误"))

        elif sub == "install":
            # 克隆远程技能仓库
            repo_url = arg2.strip() if arg2 else ""
            if not repo_url:
                print(c(RED, "  用法: /sp install <repo_url>"))
                print(c(GRAY, "  例: /sp install https://github.com/user/exploit-pack.git"))
            else:
                from core.session import _skill_scanner
                if config.USER_MODE:
                    with Spinner("正在安装技能包"):
                        result = _skill_scanner.install_pack(repo_url)
                else:
                    print(c(CYAN, f"  📥 正在克隆 {repo_url} ..."))
                    result = _skill_scanner.install_pack(repo_url)
                if result["status"] == "ok":
                    print(c(GREEN, f"  ✓ {result['detail']}"))
                    # 显示安装后的包信息
                    packs = _skill_scanner.scan_all()
                    installed = [p for p in packs if result["name"] in p.get("_path", "").name]
                    if installed:
                        print(c(BOLD, f"\n  新安装的技能包:"))
                        for p in installed:
                            name = p.get("name", "?")
                            desc = p.get("description", "")
                            scripts = p.get("scripts", [])
                            print(c(GREEN, f"    📦 {name}"))
                            if desc:
                                print(c(GRAY, f"       {desc[:60]}"))
                            if scripts:
                                print(c(GRAY, f"       scripts: {', '.join(scripts)}"))
                else:
                    print(c(RED, f"  ✗ 安装失败: {result['detail']}"))

        elif sub == "list" or sub == "":
            from core.session import _skill_scanner
            packs = _skill_scanner.scan_all()
            if not packs:
                print(c(GRAY,
                    f"  skills/ 目录下暂无技能包。\n"
                    f"  路径: {SKILLS_DIR}\n"
                    "  创建: mkdir -p skills/my_skill && echo '# My Skill' > skills/my_skill/skill.md"
                ))
            else:
                print(c(BOLD, f"\n  📦 本地技能包（{len(packs)} 个）"))
                print(c(GRAY,  f"  路径: {SKILLS_DIR}\n"))
                print(_skill_scanner.format_list())
                print(c(GRAY, "\n  /sp rescan → 重新扫描  |  /sp sync → 同步更新  |  /sp install <url> → 安装新包  |  /sp <名称> → 查看详情"))

        else:
            # 按名称查看详情
            from core.session import _skill_scanner
            packs = _skill_scanner.scan_all()
            matched = [p for p in packs if sub in p.get("name", "").lower()
                       or sub in p.get("_path", "").name.lower()]
            if not matched:
                print(c(RED, f"  ✗ 未找到名为 '{sub}' 的技能包"))
                print(c(GRAY, f"  用 /skillpack 查看所有可用技能包"))
            else:
                for pack in matched:
                    name = pack.get("name", "?")
                    desc = pack.get("description", "")
                    ver  = pack.get("version", "1.0")
                    kw   = pack.get("keywords", [])
                    tr   = pack.get("triggers", [])
                    scripts = pack.get("scripts", [])
                    guide = pack.get("guide", "")
                    pack_path = pack.get("_path", "")

                    print(c(BOLD, f"\n  📦 {name} v{ver}"))
                    if desc:
                        print(f"  {desc}")
                    print(c(GRAY, f"  路径: {pack_path}"))
                    if kw:
                        print(c(CYAN, f"  关键词: {', '.join(kw)}"))
                    if tr:
                        print(c(CYAN, f"  触发词: {', '.join(tr)}"))
                    if guide:
                        print(c(GREEN, f"  指南: {pack_path / guide}"))
                        print(c(GRAY,  f"    → read_file(path='{pack_path / guide}')"))
                    if scripts:
                        print(c(GREEN, f"  脚本: {', '.join(scripts)}"))
                        print(c(GRAY,  f"    → 优先运行脚本而非即兴编码"))

    elif verb == "/chat":
        _handle_chat(arg, arg2, session)

    elif verb == "/workspace":
        _handle_workspace_cmd(arg, arg2, session)

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


def main():
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
    args, _ = parser.parse_known_args()
    config.QUIET_MODE = args.quiet  # mutate the single canonical flag in config

    # ★ 初始化 loguru 双端输出
    # · QUIET_MODE 下终端只输出 WARNING 及以上，减少干扰
    # · 文件始终记录 DEBUG 级别，保留完整诊断信息
    setup_logger(
        stderr_level="WARNING" if (config.QUIET_MODE or config.USER_MODE) else "INFO",
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

        # ── Bottom Toolbar：显示当前模型 / 档位 / 目录 ────
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
            return HTML(
                f" <b>Model:</b> {_m}"
                f"  <b>Tier:</b> {_tier}"
                f"  <b>Dir:</b> {session.cwd}"
                f"  <b>Phase:</b> {session.current_phase}"
                f"{_time_str}"
                f"  <b>Ctrl-C</b>=undo+re-edit"
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
            reserve_space_for_menu=10,
        )

        if not config.QUIET_MODE:
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

        if not config.QUIET_MODE:
            print(c(GRAY, "  🐚 readline 降级模式（Tab 补全可用，无模糊匹配）"))
            if _PT_IMPORT_ERROR:
                print(c(YELLOW, f"  ⚠ prompt_toolkit 加载失败: {_PT_IMPORT_ERROR}"))
                print(c(YELLOW, f"     Python: {sys.executable}"))
                print(c(YELLOW, f"     修复: 在 venv 中执行 pip install prompt_toolkit rich"))
                print(c(YELLOW, f"     或重新安装: pip install -e ."))

    # ── 主循环 ────────────────────────────────────────────
    _re_edit_default = ""   # Ctrl+C 回退后，上一条用户文本作为 prompt default
    _in_generation   = False  # 区分输入阶段 vs Agent 生成阶段

    # ── prompt_toolkit 会话工厂（Ctrl+C 后重建会话用）────
    def _create_pt_session():
        """创建新的 PromptSession，确保干净的 asyncio 事件循环状态。"""
        return PromptSession(
            completer=_pawn_completer,
            key_bindings=_kb,
            auto_suggest=AutoSuggestFromHistory(),
            history=_pt_history,
            complete_while_typing=True,
            complete_in_thread=False,
            complete_style=CompleteStyle.COLUMN,
            mouse_support=False,
            bottom_toolbar=_bottom_toolbar,
            reserve_space_for_menu=10,
        )

    while True:
        try:
            print()  # 确保提示符在新行
            if prompt_toolkit_enabled:
                raw = _pt_session.prompt(
                    [("class:prompt", "▶ "), ("class:you", "You > ")],
                    style=_pawn_style,
                    default=_re_edit_default,
                ).strip()
            else:
                _label = _re_edit_default if _re_edit_default else ""
                raw = input(cp(BOLD+GREEN, "▶ ") + cp(BOLD, "You > ") + _label).strip()
            _re_edit_default = ""  # 消费后清空
        except EOFError:
            print(c(CYAN, "\n  Goodbye! 👋")); break
        except KeyboardInterrupt:
            # ── 修复：Ctrl+C 打断 prompt_toolkit 后，其内部 asyncio
            #    事件循环残留 pending Future，下次 prompt() 会崩溃。
            #    解决方案：重建 PromptSession 以获取干净的事件循环。
            #    若重建失败，降级到 readline 模式避免死循环。
            if prompt_toolkit_enabled:
                try:
                    _pt_session = _create_pt_session()
                except Exception:
                    prompt_toolkit_enabled = False  # 降级到 readline
            # CC 风格：Ctrl+C 撤回上一轮，将用户文本作为 default 重新编辑
            removed, last_text = session.undo(1)
            if removed:
                _re_edit_default = last_text
            continue
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
            _in_generation = True
            session.run_turn(raw)
        except KeyboardInterrupt:
            # 生成阶段 Ctrl+C：保留已产出内容，安全停止
            print(c(YELLOW, "\n  [已中断]"))
        finally:
            _in_generation = False

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(c(CYAN, "\n\n  Goodbye! 👋"))
    except SystemExit:
        pass
