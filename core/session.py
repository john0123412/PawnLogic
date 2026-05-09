"""
core/session.py — AgentSession · Agentic Loop
1.1 (Expert Edition — Plan-as-Key Architecture)

本次修改摘要（Plan-as-Key + 教练模式 CoT Guard）：
  [1] 常量重构：
        · 移除 _PLAN_REQUIRED_MSG / _SELF_CORRECTION_MSG
        · 新增 _PLAN_MISSING_SIGNAL（工具结果后注入，attention 贴近推理层）
        · 新增 _PLAN_EXEMPT_TOOLS + _is_plan_exempt()（只读工具豁免检查）
        · 新增 _MAX_SOFT_CORRECTIONS / _MAX_HARD_KILLS（阈值常量化）
  [2] _PlanRenderer 升级：
        · 新增子标签渲染：<intent> <tool> <why> <next> <anchor> <correction>
        · 向后兼容旧 <action> <verify> 格式
  [3] Execution Protocol（系统提示词）更新：
        · Plan 格式改为 <intent>/<tool>/<why>/<next> 子标签结构
        · 新增 Self-Correction Protocol、Anti-Drift Anchor、Long Output Management
  [4] run_turn CoT Guard 重构（教练模式）：
        · 豁免：只读工具（pwn_env / list_dir / git_op 只读操作）跳过 plan 检查
        · 软拦截 × _MAX_SOFT_CORRECTIONS：工具执行，结果后注入 PLAN_MISSING 信号
        · 硬终止 × _MAX_HARD_KILLS：软拦截耗尽后触发，撤销上一条 user 消息

所有原有功能（GSA、Anti-Loop 并发截断、Pwn 约束、自动直觉检索等）均保留。
"""

import os, json, sys, threading, time
from datetime import datetime
from pathlib import Path
from config import (
    DYNAMIC_CONFIG, MODELS, DEFAULT_MODEL,
    validate_api_key, VERSION, GLOBAL_SKILLS_PATH,
    QUIET_MODE, smart_truncate,
    AGENT_PHASES,
    USER_MODE, user_friendly_error,
    SKILLS_DIR,
)
from utils.ansi import c, BOLD, DIM, GRAY, CYAN, GREEN, YELLOW, RED, MAGENTA
from core.api_client import stream_request, ensure_tool_call_id, APIEmptyResponseError
from core.memory import (
    init_db, _gen_id, save_messages,
    search_knowledge, format_knowledge_for_prompt,
    # P0: Failure Pattern DB
    write_failure, check_failure, count_failure,
    format_failures_for_prompt,
)
from core.gsa import load_relevant_skills, bump_skill, sink_failure_to_gsa  # ★ GSA

from tools.file_ops  import (tool_read_file, tool_read_file_lines, tool_write_file,
                              tool_patch_file, tool_list_dir, tool_find_files,
                              tool_run_shell, _session_cwd, FILE_SCHEMAS)
from tools.web_ops   import tool_web_search, tool_fetch_url, tool_git_op, WEB_SCHEMAS
from tools.sandbox   import tool_run_code, SANDBOX_SCHEMAS
from tools.pwn_chain import (tool_pwn_env, tool_inspect_binary, tool_pwn_rop,
                              tool_pwn_cyclic, tool_pwn_disasm, tool_pwn_libc,
                              tool_pwn_debug, tool_pwn_one_gadget,
                              tool_pwn_timed_debug, PWN_SCHEMAS)
from tools.vision    import analyze_local_image, VISION_SCHEMAS
from core.logger import logger, audit_tool_call

# P3 + P4: Docker 容器化（可选依赖，不可用时静默跳过）
try:
    from tools.docker_sandbox import (
        tool_run_code_docker, tool_pwn_container,
        tool_install_package, docker_prune_resources,   # P4.2 / P4.3 新增
        DOCKER_SCHEMAS,
    )
except ImportError:
    tool_run_code_docker   = None
    tool_pwn_container     = None
    tool_install_package   = None   # P4.2
    docker_prune_resources = None   # P4.3
    DOCKER_SCHEMAS         = []

# P5: Scrapling 浏览器武器库（可选依赖，不可用时静默跳过）
try:
    from tools.browser_ops import (
        tool_web_fetch, tool_web_click, tool_web_screenshot,
        tool_web_select, tool_web_type, tool_web_navigate,
        BROWSER_SCHEMAS,
    )
except ImportError:
    tool_web_fetch      = None
    tool_web_click      = None
    tool_web_screenshot = None
    tool_web_select     = None
    tool_web_type       = None
    tool_web_navigate   = None
    BROWSER_SCHEMAS     = []

# P6: 环境嗅探工具（可选依赖，不可用时静默跳过）
try:
    from tools.recon_ops import tool_check_service, RECON_SCHEMAS
except ImportError:
    tool_check_service = None
    RECON_SCHEMAS      = []

TOOL_MAP: dict = {
    "read_file":           tool_read_file,
    "read_file_lines":     tool_read_file_lines,
    "write_file":          tool_write_file,
    "patch_file":          tool_patch_file,
    "list_dir":            tool_list_dir,
    "find_files":          tool_find_files,
    "run_shell":           tool_run_shell,
    "web_search":          tool_web_search,
    "fetch_url":           tool_fetch_url,
    "git_op":              tool_git_op,
    "run_code":            tool_run_code,
    "pwn_env":             tool_pwn_env,
    "inspect_binary":      tool_inspect_binary,
    "pwn_rop":             tool_pwn_rop,
    "pwn_cyclic":          tool_pwn_cyclic,
    "pwn_disasm":          tool_pwn_disasm,
    "pwn_libc":            tool_pwn_libc,
    "pwn_debug":           tool_pwn_debug,
    "pwn_one_gadget":      tool_pwn_one_gadget,
    "pwn_timed_debug":     tool_pwn_timed_debug,
    "analyze_local_image": analyze_local_image,
}

# P3 + P4: Docker 工具注册（可选）
if tool_run_code_docker:
    TOOL_MAP["run_code_docker"]    = tool_run_code_docker
if tool_pwn_container:
    TOOL_MAP["pwn_container"]      = tool_pwn_container
if tool_install_package:                                    # P4.2
    TOOL_MAP["tool_install_package"] = tool_install_package
if docker_prune_resources:                                  # P4.3
    TOOL_MAP["docker_prune_resources"] = docker_prune_resources

# P5: Scrapling 浏览器工具注册（可选）
if tool_web_fetch:
    TOOL_MAP["web_fetch"]      = tool_web_fetch
if tool_web_click:
    TOOL_MAP["web_click"]      = tool_web_click
if tool_web_screenshot:
    TOOL_MAP["web_screenshot"] = tool_web_screenshot
if tool_web_select:
    TOOL_MAP["web_select"]     = tool_web_select
if tool_web_type:
    TOOL_MAP["web_type"]       = tool_web_type
if tool_web_navigate:
    TOOL_MAP["web_navigate"]   = tool_web_navigate

# P6: 环境嗅探工具注册（可选）
if tool_check_service:
    TOOL_MAP["check_service"]  = tool_check_service

TOOLS_SCHEMA: list = (
    FILE_SCHEMAS + WEB_SCHEMAS + SANDBOX_SCHEMAS
    + PWN_SCHEMAS + VISION_SCHEMAS + DOCKER_SCHEMAS
    + BROWSER_SCHEMAS + RECON_SCHEMAS
)

# ── switch_phase：全局路由工具（强制附加，不受 Phase 过滤）───────────
# 注意：实际执行逻辑在 run_turn 中拦截，TOOL_MAP 条目仅作保底占位。
_SWITCH_PHASE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "switch_phase",
        "description": (
            "当前阶段的工具无法满足需求，或你已完成本阶段任务时，调用此工具切换工作阶段。\n"
            "切换后系统将为你加载下一批专业工具，请根据任务需要选择目标阶段。\n"
            f"可用阶段: {', '.join(AGENT_PHASES.keys())}\n"
            "  RECON    — 侦察：环境检测、目录浏览、二进制初步分析\n"
            "  VULN_DEV — 漏洞开发：偏移计算、反汇编、ROP/libc 分析\n"
            "  EXPLOIT  — 利用：编写 exploit、动态调试、交互式验证\n"
            "  WEB_PEN  — Web 渗透：Scrapling 反爬抓取、自适应定位、浏览器自动化\n"
            "  GENERAL  — 通用：文件操作、联网、后备场景"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phase": {
                    "type": "string",
                    "enum": list(AGENT_PHASES.keys()),
                    "description": "目标阶段名称，必须是上述可用阶段之一",
                },
                "reason": {
                    "type": "string",
                    "description": "切换原因（一句话说明为什么需要切换）",
                },
            },
            "required": ["phase"],
        },
    },
}

TOOL_MAP["switch_phase"] = lambda a: (
    f"[switch_phase] 阶段切换请求已接收，目标: {a.get('phase', '?')}。"
    "（此消息不应出现，应由 run_turn 拦截处理）"
)
TOOLS_SCHEMA.append(_SWITCH_PHASE_SCHEMA)

# ── ★ bump_skill 工具（GSA 闭环反馈）─────────────────────────────────
def tool_bump_skill(args: dict) -> str:
    """
    当你利用某个 GSA 技能成功解决了问题，调用此工具增加该技能的使用计数并刷新时间戳。
    这是 GSA 知识库的闭环反馈入口，请在 <verify> 通过后主动调用。
    """
    skill_name = args.get("skill_name", "").strip()
    if not skill_name:
        return "ERROR: skill_name 参数不能为空"
    try:
        ok, msg = bump_skill(skill_name)
        return msg
    except Exception as e:
        return f"ERROR: bump_skill 异常: {e}"

_BUMP_SKILL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "bump_skill",
        "description": (
            "GSA 闭环反馈工具。当你成功使用了某个 global_skills.md 中的技能来解决问题时，"
            "调用此工具以增加该技能的 hits 计数、刷新 last_used 日期、提升 confidence。"
            "这有助于知识库的质量演化——高频验证的技能在未来检索中会获得更高优先级。\n"
            "请在 <verify> 通过后、GSA 存档之前调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type":        "string",
                    "description": "技能的精确名称（## 标题文本，不含 '## ' 前缀）",
                },
            },
            "required": ["skill_name"],
        },
    },
}

TOOL_MAP["bump_skill"] = tool_bump_skill
TOOLS_SCHEMA.append(_BUMP_SKILL_SCHEMA)

# ── P0: audit_payload 工具（防御性审计）───────────────────
# 需要审计的危险工具集合
_AUDITED_TOOLS = {"run_code", "run_shell", "run_interactive"}


def tool_audit_payload(args: dict) -> str:
    """
    Payload 投前审计工具。
    查询指定工具的历史失败记录，返回警告和建议。
    """
    tool_name   = args.get("tool_name", "").strip()
    payload_hint = args.get("payload_preview", "").strip()

    if not tool_name:
        return "ERROR: tool_name 参数不能为空"

    rows = check_failure(tool_name, args_keywords=payload_hint, limit=3)
    if not rows:
        return f"✓ 审计通过: {tool_name} 无历史失败记录。"

    warning = format_failures_for_prompt(rows)
    return (
        f"⚠ 审计警告: {tool_name} 存在 {len(rows)} 条历史失败记录\n\n"
        f"{warning}\n\n"
        f"建议: 修改 Payload 或换用其他方案后再试。"
    )


_AUDIT_PAYLOAD_SCHEMA = {
    "type": "function",
    "function": {
        "name": "audit_payload",
        "description": (
            "Payload 投前审计工具。在调用 run_code / run_shell / run_interactive 执行危险操作之前，\n"
            "使用此工具检查是否有同类历史失败记录。如果有，系统会返回失败原因和修改建议。\n"
            "适用场景：执行 exploit 脚本、运行 shellcode、调用 GDB 调试前。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "目标工具名：run_code / run_shell / run_interactive",
                },
                "payload_preview": {
                    "type": "string",
                    "description": "Payload 或参数摘要（用于模糊匹配历史失败记录）",
                },
            },
            "required": ["tool_name"],
        },
    },
}

TOOL_MAP["audit_payload"] = tool_audit_payload
TOOLS_SCHEMA.append(_AUDIT_PAYLOAD_SCHEMA)

# ── ★ P6: search_skills 工具（自动化利用链检索）─────────────────────
def tool_search_skills(args: dict) -> str:
    """
    根据探测到的目标指纹（如 'Fastjson', 'Shiro', 'Log4j'）搜索本地技能包。
    返回匹配的技能包列表及脚本执行指引。
    """
    query = args.get("query", "").strip()
    if not query:
        return "ERROR: query 参数不能为空。请输入目标指纹或关键词，如 'Fastjson'、'Shiro'。"

    try:
        packs = _skill_scanner.match(query, top_k=int(args.get("top_k", 3)))
    except Exception as e:
        return f"ERROR: search_skills 异常: {e}"

    if not packs:
        return f"未找到与 '{query}' 匹配的技能包。可尝试：1. /skillpack rescan  2. 检查 skills/ 目录"

    # 使用 format_for_prompt 获取完整指引（含脚本执行命令）
    result = _skill_scanner.format_for_prompt(packs)

    # USER_MODE 简洁输出
    if USER_MODE:
        names = [p.get("name", "?") for p in packs]
        print(c(GREEN, f"  🚀 [P6] 已匹配 {len(packs)} 个技能包: {', '.join(names)}"))

    return result


_SEARCH_SKILLS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_skills",
        "description": (
            "P6 自动化利用链：根据目标指纹搜索本地技能包。\n"
            "在侦察阶段探测到 Web 框架指纹（如 Fastjson/Shiro/Log4j/Spring）后，\n"
            "调用此工具检索对应的自动化利用脚本和指南。\n"
            "返回结果包含：技能包名称、描述、guide.md 路径、可用脚本及执行命令。\n"
            "你必须优先执行返回的脚本，禁止在未尝试脚本前自主编写长段 Payload。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type":        "string",
                    "description": "目标指纹或关键词，如 'Fastjson', 'Shiro', 'log4j', 'spring', 'sql注入'",
                },
                "top_k": {
                    "type":        "integer",
                    "description": "返回的最大技能包数量（默认 3）",
                    "default":     3,
                },
            },
            "required": ["query"],
        },
    },
}

TOOL_MAP["search_skills"] = tool_search_skills
TOOLS_SCHEMA.append(_SEARCH_SKILLS_SCHEMA)

def _try_load_delegate():
    try:
        from tools.delegate_tool import tool_delegate_task, DELEGATE_SCHEMA
        TOOL_MAP["delegate_task"] = tool_delegate_task
        TOOLS_SCHEMA.append(DELEGATE_SCHEMA)
    except ImportError:
        pass

_try_load_delegate()

# ════════════════════════════════════════════════════════
# ★ 改动 [1]：_PLAN_REQUIRED_MSG → 温和引导语气
#   不再是 "ERROR: Rule Violation"，改为 "Notice"，
#   只在终端打印，不注入对话上下文（避免上下文污染）。
# ════════════════════════════════════════════════════════

_MAX_CONCURRENT_TOOLS  = 3
_MAX_SOFT_CORRECTIONS  = 2   # 软拦截最大次数（工具仍执行，追加修正信号）
_MAX_HARD_KILLS        = 1   # 软拦截耗尽后的硬终止阈值

# ════════════════════════════════════════════════════════
# P1: 时间感知调度 — URGENT_MODE 常量
# ════════════════════════════════════════════════════════

_URGENT_THRESHOLD_SEC = 30   # 剩余 < 30s 时触发 URGENT_MODE

# 极速模型候选（时间紧迫时自动切换）
_URGENT_MODEL_CANDIDATES = [
    "ds-v4-flash",
    "glm-4.5-air",
    "qwen-turbo",
    "groq-llama3",
]

_URGENT_SIGNAL = (
    "[SYSTEM: URGENT_MODE — time budget nearly exhausted]\n"
    "Time remaining is critically low. You MUST:\n"
    "  1. SKIP <plan> blocks — invoke tools directly.\n"
    "  2. Use the SHORTEST possible answers.\n"
    "  3. Do NOT invoke GSA / bump_skill / audit_payload.\n"
    "  4. Focus ONLY on the core deliverable.\n"
    "  5. If a tool call fails, do NOT retry — report partial results.\n"
)

# ── PLAN_MISSING 信号 ─────────────────────────────────────────────
# 注入位置：tool 结果追加完毕后（而非 user 消息），
# 使 attention 权重贴近当前推理层，修正效果优于旧 _SELF_CORRECTION_MSG。
_PLAN_MISSING_SIGNAL = (
    "[SYSTEM: PLAN_MISSING — your last tool call was intercepted by the executor]\n"
    "The tool executor requires a <plan> block to authorize tool usage.\n"
    "Recovery: output <plan><intent>your original intent</intent></plan> "
    "then re-emit your tool call. Do NOT apologize or repeat previous text."
)

# ── 豁免名单：以下工具无副作用，允许跳过 <plan> 检查 ─────────────
# 可减轻轻量模型在简单只读操作上的认知负担。
_PLAN_EXEMPT_TOOLS = {
    "pwn_env",        # 环境探测，无副作用
    "list_dir",       # 目录列出，无副作用
    "search_skills",  # P6: 技能包检索，只读操作
    "check_service",  # P6: 环境嗅探，只读操作
    # git_op 仅只读操作豁免（见 _is_plan_exempt）
}

def _is_plan_exempt(tc_buf: dict) -> bool:
    """若本次所有工具调用均属于豁免名单（只读），允许跳过 <plan> 检查。"""
    for idx in tc_buf:
        name = tc_buf[idx]["name"]
        if name not in _PLAN_EXEMPT_TOOLS and name != "git_op":
            return False
        if name == "git_op":
            try:
                args = json.loads(tc_buf[idx]["args"])
                if args.get("action") not in ("status", "log", "diff", "branch"):
                    return False
            except Exception:
                return False
    return True

# ════════════════════════════════════════════════════════
# GSA 辅助：读取 global_skills.md TOC
# ════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════
# P6.5: 技能引擎 — SkillScanner 文件夹包模式
# ════════════════════════════════════════════════════════

from core.skill_manager import SkillScanner
_skill_scanner = SkillScanner(SKILLS_DIR)


def _load_skills_toc() -> str:
    try:
        from core.gsa import load_toc
        return load_toc(max_lines=80)
    except Exception:
        pass
    try:
        if not GLOBAL_SKILLS_PATH.exists():
            return "(global_skills.md 尚未创建，AI 可在首次存档时自主创建第一个分类)"
        lines    = GLOBAL_SKILLS_PATH.read_text(encoding="utf-8").splitlines()[:80]
        headings = [l for l in lines if l.startswith("#")]
        return "\n".join(headings) if headings else "(global_skills.md 暂无分类)"
    except Exception:
        return "(无法读取 global_skills.md)"

# ════════════════════════════════════════════════════════
# 上下文管理
# ════════════════════════════════════════════════════════

def _ctx_chars(msgs: list) -> int:
    return sum(len(str(m.get("content") or "")) for m in msgs)

def _trim_and_compact_context(msgs: list) -> int:
    """
    上下文压缩（Tool Clearing）：
    Token 溢出时，保留系统提示词 + 最新 10 条消息。
    被清理的老消息不直接丢弃，而是：
      · role=tool   → 内容替换为占位符
      · role=user/assistant → 截断保留前 100 字符
    再将这些消息合并为一条 role=assistant 的摘要插回 system 之后。
    """
    if _ctx_chars(msgs) <= DYNAMIC_CONFIG["ctx_max_chars"]:
        return 0

    KEEP_TAIL = 10
    # system 占 index 0；至少要有可压缩空间
    if len(msgs) <= KEEP_TAIL + 1:
        return 0

    cutoff = len(msgs) - KEEP_TAIL   # [1 : cutoff] 为待压缩区间

    old_msgs = msgs[1:cutoff]

    compacted_lines: list[str] = []
    for m in old_msgs:
        role    = m.get("role", "unknown")
        content = m.get("content") or ""
        if role == "tool":
            compacted_lines.append(f"[tool/{m.get('tool_call_id', '')}]: "
                                   "(Tool output compacted to save context)")
        elif role in ("user", "assistant"):
            snippet = str(content)[:100]
            ellipsis = "…" if len(str(content)) > 100 else ""
            compacted_lines.append(f"[{role}]: {snippet}{ellipsis}")
        # assistant with tool_calls: note the call names only
        if role == "assistant" and m.get("tool_calls"):
            names = [tc.get("function", {}).get("name", "?")
                     for tc in (m.get("tool_calls") or [])]
            compacted_lines.append(f"  └─ tool_calls: {', '.join(names)}")

    summary_content = (
        "📝 [Context Compacted]:\n"
        + "\n".join(compacted_lines)
    )
    summary_msg = {
        "role":     "assistant",
        "content":  summary_content,
        "_pinned":  True,   # 防止摘要本身在下次压缩时被再次弹出
    }

    # 用摘要替换老消息区间
    del msgs[1:cutoff]
    msgs.insert(1, summary_msg)

    return len(old_msgs)

# ════════════════════════════════════════════════════════
# XML Plan 渲染器（含"憋尿"修复）
# ════════════════════════════════════════════════════════

_TAG_PAIRS = [
    ("<plan>",       "</plan>"),
    ("<action>",     "</action>"),
    ("<verify>",     "</verify>"),
    # ── 新增子标签（v2.1）────────────────────────────────
    ("<intent>",     "</intent>"),
    ("<tool>",       "</tool>"),
    ("<why>",        "</why>"),
    ("<next>",       "</next>"),
    ("<anchor>",     "</anchor>"),
    ("<correction>", "</correction>"),
]
_ALL_TAGS = [t for pair in _TAG_PAIRS for t in pair]
_TAG_MAX  = max(len(t) for t in _ALL_TAGS) + 2

# 子标签的前缀标签与颜色映射
_SUBTAG_OPEN: dict = {
    "<action>":     (GRAY,          "  📋 "),
    "<verify>":     (CYAN,          "  🔬 验证: "),
    "<intent>":     (MAGENTA,       "  🎯 意图: "),
    "<tool>":       (CYAN,          "  🔧 工具: "),
    "<why>":        (GRAY,          "  💡 理由: "),
    "<next>":       (GRAY + DIM,    "  ⏭  下步: "),
    "<anchor>":     (YELLOW,        "  ⚓ 锚点:\n"),
    "<correction>": (YELLOW,        ""),          # silent flag, no display
}

class _PlanRenderer:
    def __init__(self):
        self.in_plan       = False
        self.in_action     = False
        self.in_verify     = False
        self.in_intent     = False
        self.in_tool_tag   = False
        self.in_why        = False
        self.in_next       = False
        self.in_anchor     = False
        self.in_correction = False
        self.tail = ""

    def _in_subtag(self) -> bool:
        return (self.in_action or self.in_verify or self.in_intent
                or self.in_tool_tag or self.in_why or self.in_next
                or self.in_anchor or self.in_correction)

    def _color(self, text: str) -> str:
        if self.in_verify:     return c(CYAN,       text)
        if self.in_intent:     return c(MAGENTA,    text)
        if self.in_tool_tag:   return c(CYAN,       text)
        if self.in_why:        return c(GRAY,        text)
        if self.in_next:       return c(GRAY + DIM, text)
        if self.in_anchor:     return c(YELLOW,      text)
        if self.in_correction: return ""               # never display <correction> value
        if self.in_action:     return c(GRAY,        text)
        return c(GRAY + DIM,   text)

    def _set_subtag(self, tag: str, val: bool):
        if tag in ("<action>",     "</action>"):     self.in_action     = val
        elif tag in ("<verify>",   "</verify>"):     self.in_verify     = val
        elif tag in ("<intent>",   "</intent>"):     self.in_intent     = val
        elif tag in ("<tool>",     "</tool>"):       self.in_tool_tag   = val
        elif tag in ("<why>",      "</why>"):        self.in_why        = val
        elif tag in ("<next>",     "</next>"):       self.in_next       = val
        elif tag in ("<anchor>",   "</anchor>"):     self.in_anchor     = val
        elif tag in ("<correction>","</correction>"): self.in_correction = val

    def feed(self, chunk: str) -> str:
        self.tail += chunk
        output = ""
        while self.tail:
            if "<" not in self.tail:
                if not self.in_plan: output += self.tail
                else:
                    col = self._color(self.tail)
                    if col: sys.stdout.write(col); sys.stdout.flush()
                self.tail = ""; break

            lt = self.tail.find("<")
            if lt > 0:
                safe = self.tail[:lt]
                if not self.in_plan: output += safe
                else:
                    col = self._color(safe)
                    if col: sys.stdout.write(col); sys.stdout.flush()
                self.tail = self.tail[lt:]; continue

            ep = len(self.tail); et = None
            for tag in _ALL_TAGS:
                pos = self.tail.find(tag)
                if pos != -1 and pos < ep: ep = pos; et = tag

            if not et:
                if len(self.tail) > _TAG_MAX:
                    if not self.in_plan: output += self.tail[0]
                    else: sys.stdout.write(self._color(self.tail[0])); sys.stdout.flush()
                    self.tail = self.tail[1:]
                else: break
            elif not self.in_plan:
                output += self.tail[:ep]; self.tail = self.tail[ep:]
                if et == "<plan>":
                    sys.stdout.write(c(GRAY + DIM, "\n  💭 [计划开始]\n")); sys.stdout.flush()
                    self.in_plan = True; self.tail = self.tail[len("<plan>"):]
                else:
                    output += self.tail[:len(et)]; self.tail = self.tail[len(et):]
            else:
                # inside <plan> — handle open and close subtags
                col = self._color(self.tail[:ep])
                if col: sys.stdout.write(col); sys.stdout.flush()
                self.tail = self.tail[ep:]
                if et == "</plan>":
                    sys.stdout.write(c(GRAY, "\n  [计划结束]\n")); sys.stdout.flush()
                    self.in_plan = self.in_action = self.in_verify = False
                    self.in_intent = self.in_tool_tag = self.in_why = False
                    self.in_next = self.in_anchor = self.in_correction = False
                    self.tail = self.tail[len("</plan>"):]
                elif et in _SUBTAG_OPEN:
                    # opening subtag
                    color, prefix = _SUBTAG_OPEN[et]
                    if prefix:
                        sys.stdout.write(c(color, prefix)); sys.stdout.flush()
                    self._set_subtag(et, True)
                    self.tail = self.tail[len(et):]
                elif et.startswith("</"):
                    # closing subtag
                    self._set_subtag(et, False)
                    self.tail = self.tail[len(et):]
                    sys.stdout.write("\n"); sys.stdout.flush()
                else:
                    self.tail = self.tail[len(et):]
        return output

    def flush(self) -> str:
        leftover = ""
        if self.in_plan: sys.stdout.write(c(GRAY + DIM, self.tail)); sys.stdout.flush()
        else: leftover = self.tail
        self.tail = ""
        self.in_plan = self.in_action = self.in_verify = False
        self.in_intent = self.in_tool_tag = self.in_why = False
        self.in_next = self.in_anchor = self.in_correction = False
        return leftover

# ════════════════════════════════════════════════════════
# State.md
# ════════════════════════════════════════════════════════

STATE_FILENAME = ".pawn_state.md"

def _load_state_md(cwd: str) -> str:
    p = Path(cwd) / STATE_FILENAME
    if p.exists() and p.is_file():
        try: return p.read_text(encoding="utf-8").strip()
        except Exception: pass
    return ""

# ════════════════════════════════════════════════════════
# AgentSession
# ════════════════════════════════════════════════════════

class AgentSession:
    def __init__(self):
        self.session_id  = _gen_id()
        self.model_alias = DEFAULT_MODEL
        self.messages: list = []
        self.cwd         = os.getcwd()
        _session_cwd[0]  = self.cwd
        self.current_phase = "RECON"   # MoE 初始阶段
        init_db()
        # ── P1: Time-aware scheduling state（必须在 _reset_system_prompt 之前）──
        self._turn_start_time        = 0.0
        self._time_budget_sec        = 0   # 0 = 不限时间
        self._urgent_mode            = False
        self._save_lock = threading.Lock()
        # ── Usage & audit counters (cumulative across all turns) ──
        self.total_prompt_tokens     = 0
        self.total_completion_tokens = 0
        self.total_tool_calls        = 0
        # Per-turn snapshots, reset at start of each run_turn
        self._turn_prompt_tokens     = 0
        self._turn_completion_tokens = 0
        self._turn_tool_calls        = 0
        # ★ P6.5: 技能包匹配结果缓存
        self._loaded_skill_packs: list = []
        # 最后调用，因为它依赖上面所有属性
        self._reset_system_prompt()

    def _time_remaining(self) -> float:
        """返回当前 turn 的剩余秒数。time_budget=0 时返回 inf。"""
        if self._time_budget_sec <= 0:
            return float("inf")
        elapsed = time.monotonic() - self._turn_start_time
        return max(0.0, self._time_budget_sec - elapsed)

    def undo(self, n: int = 1) -> tuple[int, str]:
        """物理删除 messages 尾部消息对（user+assistant），不影响 pinned。
        返回 (实际删除的消息数, 被撤回的最后一条 user 文本)。
        user 文本供 Ctrl+C 回退编辑时作为 prompt default 使用。"""
        removed = 0
        last_user_text = ""
        for _ in range(n):
            # 从尾部向前扫描，跳过 system 和 pinned
            while self.messages:
                tail = self.messages[-1]
                if tail.get("role") == "system" or tail.get("_pinned"):
                    break
                # 记录被弹出的 user 文本
                if tail.get("role") == "user":
                    last_user_text = str(tail.get("content") or "")
                self.messages.pop()
                removed += 1
                # 如果弹出的是 assistant，继续弹出对应的 user 消息
                if tail.get("role") == "assistant":
                    while self.messages:
                        prev = self.messages[-1]
                        if prev.get("role") == "system" or prev.get("_pinned"):
                            break
                        if prev.get("role") == "user":
                            last_user_text = str(prev.get("content") or "")
                            self.messages.pop()
                            removed += 1
                            break
                        elif prev.get("role") == "assistant":
                            # 连续 assistant（多轮工具调用），继续弹
                            self.messages.pop()
                            removed += 1
                        else:
                            break
                    break
                # 如果弹出的是 user，也结束这一轮
                elif tail.get("role") == "user":
                    break
        return removed, last_user_text

    @property
    def model(self) -> dict:
        return MODELS[self.model_alias]

    def _reset_system_prompt(self, knowledge_query: str = ""):
        cfg = DYNAMIC_CONFIG
        knowledge_block = ""
        if knowledge_query:
            rows = search_knowledge(knowledge_query, limit=3)
            knowledge_block = format_knowledge_for_prompt(rows)
        state_block  = _load_state_md(self.cwd)

        # P1.8: URGENT_MODE 跳过 GSA 注入（节省 token）
        if self._urgent_mode:
            skills_toc = ""
            _relevant_skills_md = ""
            _conflict_warning = ""
            _local_skills_md = ""
            self._loaded_skill_packs = []
        else:
            skills_toc   = _load_skills_toc()

            # ── ★ GSA 相关技能动态检索（衰减评分版）────────────
            _relevant_skills_md  = ""
            _conflict_warning    = ""
            _local_skills_md     = ""
            if knowledge_query:
                try:
                    _relevant_skills_md, _conflict_warning = load_relevant_skills(
                        knowledge_query, top_k=3
                    )
                except Exception:
                    pass   # 降级：无相关技能注入，不中断主流程

            # ★ P6.5: 本地技能引擎检索（SkillScanner 文件夹包模式）
            # 始终尝试匹配：knowledge_query 为空时按关键词匹配可能返回空，
            # 但有 manifest.json triggers 的技能包仍可通过其他方式命中。
            try:
                _query = knowledge_query or ""
                _matched_packs = _skill_scanner.match(_query, top_k=3)
                _local_skills_md = _skill_scanner.format_for_prompt(_matched_packs)
                self._loaded_skill_packs = _matched_packs
            except Exception:
                pass   # 降级：无本地技能注入，不中断主流程

        # ── MoE Phase 感知块 ──────────────────────────────
        phase_tools  = AGENT_PHASES.get(self.current_phase, [])
        other_phases = [p for p in AGENT_PHASES if p != self.current_phase]
        phase_block  = (
            f"=== Current Agent Phase: {self.current_phase} ===\n"
            f"You are currently in the '{self.current_phase}' phase. "
            f"Only the following tools are available this phase:\n"
            f"  {', '.join(phase_tools)}\n"
            f"  (+ switch_phase is always available)\n"
            f"If these tools are insufficient, call switch_phase(phase=<target>) to unlock others.\n"
            f"Other available phases: {', '.join(other_phases)}\n\n"
        )

        prompt = (
            f"You are PawnLogic {VERSION}, an expert AI assistant running in Linux/WSL2.\n"
            "Core Expertise: C/C++ development, Python, Cybersecurity (Pwn/CTF reverse engineering), "
            "and academic paper processing.\n\n"

            + phase_block +

            "=== Pwn/Security Expert Mindset ===\n"
            "When analyzing binaries or writing exploits, follow this Security Researcher paradigm:\n"
            "  Phase 1 — Recon    : pwn_env (check tools) → inspect_binary (checksec, file, strings)\n"
            "  Phase 2 — Offset   : pwn_cyclic gen → pwn_debug (feed pattern, read crash offset)\n"
            "  Phase 3 — Weaponize: pwn_rop (find gadgets) → pwn_libc (leak & resolve) → build payload\n"
            "  Phase 4 — Exploit  : run_code (use_venv=true, install_deps='pwntools') → test\n\n"
            "RULE: ALL pwntools code MUST run inside run_code sandbox with use_venv=true.\n"
            "RULE: NEVER skip a phase. If Phase 2 gives no offset, debug before proceeding.\n"
            "RULE: You MUST NOT guess the overflow vector. Always confirm it with pwn_cyclic + pwn_debug.\n"
            "RULE: If tool 'inspect_binary' shows 'NX enabled', do NOT attempt shellcode injection on "
            "the stack. Use ROP chains (pwn_rop) or one_gadget (pwn_one_gadget) instead.\n"
            "RULE: If 'inspect_binary' shows 'Canary found', you MUST find a canary leak path before "
            "attempting any stack smashing exploit.\n\n"
            "=== VULN_DEV 漏洞开发纪律 ===\n"
            "你处于无头(Headless)终端。绝对禁止直接运行等待输入的 gdb/nc 等交互式命令！\n"
            "最佳实践：在漏洞开发阶段，优先编写包含 pwntools 的 exploit.py 脚本。利用 cyclic() 生成偏移数据、process() 启动程序、corefile 读取崩溃内存，然后使用 run_shell 执行 'python3 exploit.py' 来测试。这是最稳定的方式。\n\n"

            "=== Memory & History Awareness ===\n"
            "You have a persistent conversation database. While you have no spontaneous memory,\n"
            "you CAN and SHOULD use /chat commands when the user asks about past sessions.\n"
            "NEVER claim you have no memory — you have History tools.\n\n"

            "=== Available Tools ===\n"
            "  File     : read_file · read_file_lines · write_file · patch_file · list_dir · find_files\n"
            "  Shell    : run_shell · git_op\n"
            "  Web      : web_search → fetch_url (Jina / Pandoc / regex fallback)\n"
            "  Browser  : web_fetch (StealthyFetcher/反爬) · web_click · web_screenshot\n"
            "             web_select (自适应CSS) · web_type · web_navigate\n"
            "  Sandbox  : run_code  (python / c / cpp / javascript / bash / rust / go / java)\n"
            "  Docker   : run_code_docker (一次性容器) · pwn_container (持久化容器)\n"
            "  Vision   : analyze_local_image  (jpg/png/gif/webp — glm-4v / gpt-4o)\n"
            "  CTF/Pwn  : pwn_env · inspect_binary · pwn_rop · pwn_cyclic · pwn_disasm\n"
            "             pwn_libc · pwn_debug · pwn_one_gadget · pwn_timed_debug\n"
            "  Recon    : check_service (port → PID/进程名/路径/环境变量/动态库)\n"
            "  Advanced : delegate_task  (fresh context sub-agent)\n"
            "  Skills   : search_skills (P6: 按目标指纹检索本地技能包)\n"
            "  History  : /chat list · /chat view · /chat find · /chat tag · /chat related\n\n"

            "=== Scrapling Web Penetration (WEB_PEN Phase) ===\n"
            "Cloudflare / 动态页面 → Scrapling 自适应穿透：\n"
            "  · web_fetch 自动 StealthyFetcher + solve_cloudflare。\n"
            "  · web_select 自适应 CSS 定位，应对 DOM 变化。\n"
            "  · 截图/下载 → ~/.pawnlogic/workspace/screenshots/。\n"
            "  · 交互操作: web_navigate → web_type → web_click → web_screenshot。\n\n"

            "=== Auto-Exploit (P6) Protocol ===\n"
            "Web 目标必走闭环：\n\n"
            "  1. 侦察指纹 — web_fetch 提取 Server/X-Powered-By/Cookie/HTML 特征，识别框架。\n"
            "  2. 确认环境 — check_service(port) 获取 PID/路径/环境变量/动态库。\n"
            "  3. 检索武器 — search_skills(query='<框架名>')，空结果则尝试变体关键词。\n"
            "  4. 同步更新 — /sp sync 拉取最新，/sp install <url> 安装新包。\n"
            "  5. 阅读指南 — read_file(guide.md)，理解条件与参数。\n"
            "  6. 执行脚本 — 优先 run_shell(pack_path/script)，隔离用 run_code_docker。\n"
            "  7. 验证收尾 — 确认 Flag/Shell/回显，成功后 bump_skill 提升权重。\n\n"
            "  ⚡ 肌肉记忆: 侦察 → check_service → search_skills → install/sync → 执行\n\n"
            "  RULE: 禁止跳过 search_skills 直接编写 Exploit。\n"
            "  RULE: 脚本失败先读 guide.md 改参数重试，仅无匹配时从零编写。\n\n"

            f"Working dir : {self.cwd}\n"
            f"Time        : {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"Model       : {self.model_alias} ({self.model['id']})\n"
            f"Limits      : max_tokens={cfg['max_tokens']}  max_iter={cfg['max_iter']}  "
            f"ctx={cfg['ctx_max_chars']//1000}k  tool_out={cfg['tool_max_chars']}\n\n"

            # ════════════════════════════════════════════════
            # ★ 改动 [2]：Execution Protocol — 新版 plan 格式
            # ════════════════════════════════════════════════
            "=== Execution Protocol (MANDATORY) ===\n"

            "ARCHITECTURE NOTE: You are the 'Brain' in a pipeline:\n"
            "  User Input → [YOU] → <plan> parser → tool executor → result injector → [YOU again]\n"
            "The <plan> tag is NOT a formality. It is the KEY that unlocks the tool executor.\n"
            "Without <plan>, the executor cannot receive your intent and will return an error.\n\n"

            "Thinking Process: You are an autonomous agent. Like a human expert, you MUST think\n"
            "step-by-step. Before any tool_use or code block, output a <plan> to decompose\n"
            "the problem into concrete, ordered steps.\n\n"

            "BEFORE invoking ANY tool, output your thought process using the full plan format:\n\n"
            "<plan>\n"
            "  <intent>One sentence: what am I trying to accomplish right now?</intent>\n"
            "  <tool>Tool name I will call</tool>\n"
            "  <why>Why this specific tool? What do I expect to find?</why>\n"
            "  <next>If this succeeds, my next action will be: ...</next>\n"
            "</plan>\n\n"
            "Minimal plan (for simple single-tool calls):\n"
            "  <plan><intent>Check binary protections before analysis.</intent></plan>\n\n"
            "  · For pure conversation (no tools), a plan is optional.\n"
            "  · For even a single tool call, output AT MINIMUM: <plan><intent>reason</intent></plan>\n\n"
            # ════════════════════════════════════════════════
            # ★ 终极防线：打破 JSON 惯性，强化 XML 强制力
            # ════════════════════════════════════════════════
            "### === TOOL CALLING PROTOCOL (CRITICAL) ===\n"
            "You have TWO output formats. Choosing the wrong format will cause system crash.\n\n"
            "[RULE 1: COMPACT JSON]\n"
            "Use ONLY for simple parameters (short strings, numbers, NO newlines, NO quotes).\n"
            "Format: {\"name\":\"tool_name\",\"arguments\":{\"key\":\"val\"}}\n\n"
            "[RULE 2: XML TAGS (MANDATORY FOR CODE/TEXT)]\n"
            "You MUST use XML tags if your argument contains:\n"
            "- Bash scripts, Python code, or JSON payloads.\n"
            "- Multi-line text (newlines).\n"
            "- Quotes (\" or ').\n"
            "- Chinese characters.\n"
            "Specifically, tools like `write_file`, `patch_file`, `web_search` MUST use XML.\n\n"
            "Format:\n"
            "<call name=\"write_file\">\n"
            "  <path>report.md</path>\n"
            "  <content>\n"
            "# Write raw unescaped text here\n"
            "watch -n 1 \"grep -rnw /proc/net\"\n"
            "  </content>\n"
            "</call>\n\n"
            "🚨 DO NOT WRAP XML IN <tool_call> TAGS. JUST OUTPUT <call>.\n"
            "🚨 NEVER output JSON with unescaped quotes. Use XML to bypass escaping.\n\n"
            "⚠ NO WAITING RULE: Output the <plan> block AND invoke the tool in the EXACT SAME\n"
            "response. Do NOT output a plan then wait for user confirmation.\n\n"

            "Self-Correction Protocol (when you see PLAN_MISSING signal):\n"
            "  Do NOT apologize. Do NOT repeat failed call text.\n"
            "  Respond with ONLY:\n"
            "    <plan>\n"
            "      <intent>[your original intent]</intent>\n"
            "      <tool>[original tool name]</tool>\n"
            "      <why>[brief justification]</why>\n"
            "      <correction>true</correction>\n"
            "    </plan>\n"
            "    [re-emit the original tool call]\n\n"

            "Anti-Drift Anchor (use when iteration count > 15):\n"
            "  Prepend to your <plan>:\n"
            "    <anchor>\n"
            "      Current phase: [PHASE N — description]\n"
            "      Confirmed so far: [offset=X, NX=enabled/disabled, libc=X]\n"
            "      Still needed: [what remains for gate pass]\n"
            "    </anchor>\n\n"

            "Long Output Management:\n"
            "  When a tool result > 100 lines:\n"
            "    · EXTRACT only what is needed for the current phase.\n"
            "    · SUMMARIZE the rest in one sentence.\n"
            "    · Issue targeted follow-ups: run_shell('ROPgadget ... | grep pop rdi') rather than full dump.\n\n"

            "=== NEGATIVE CONSTRAINTS — DO NOT VIOLATE ===\n"
            "NEVER do the following (violations will be intercepted and cancelled by the system):\n\n"
            "  ✗  NEVER use 'sudo' in run_shell. The host is NOT your playground.\n"
            "       If you need root privileges, spin up a Docker container:\n"
            "       pwn_container(action='create', image='ubuntu22') → "
            "the container runs as root by default.\n\n"
            "  ✗  RW (read-write) mount is ONLY allowed inside ~/.pawnlogic/workspace.\n"
            "       Any path outside that directory MUST use mode='ro'.\n"
            "       The system will reject rw mounts to host paths outside the workspace.\n\n"
            "  ✗  NEVER blindly guess file paths.\n"
            "       Wrong: list_dir('.') → list_dir('src') → list_dir('src/lib') → ...\n"
            "       Right: find_files('target_name.c', root='.') once, then read directly.\n\n"
            "  ✗  NEVER call find_files or list_dir more than twice in succession.\n"
            "       If you still cannot find the file after 2 attempts, ASK the user for the path.\n\n"
            "  ✗  NEVER read a file > 2MB in one call. Use read_file_lines for large files.\n\n"
            "  ✗  NEVER use write_file to overwrite existing code files.\n"
            "       Use patch_file with SEARCH/REPLACE blocks for ALL code modifications.\n\n"
            "  ✗  NEVER call more than 3 tools concurrently. Plan them sequentially.\n\n"
            "  ✗  If list_dir or find_files has been called 2+ times without finding the target,\n"
            "       STOP and use /chat find <keyword> to check if you solved it in a past session.\n\n"

            "=== Workflow Guides ===\n"
            "Coding:\n"
            "  plan → find_files (max 1-2×) → read_file → patch_file → run_shell (verify) → git_op commit\n\n"
            "Code Search & Analysis:\n"
            "  · 查找函数调用/引用：优先使用 run_shell('grep -rn <关键词> .') 或专门的代码检索工具。\n"
            "  · 绝对禁止：不要为了搜索文本而专门写一个带有硬编码内容的 Python 脚本并调用 run_code，\n"
            "    这既低效又容易产生幻觉（模型会伪造文件内容而非真实读取）。\n\n"
            "Pwn/CTF:\n"
            "  pwn_env → inspect_binary → pwn_cyclic gen → pwn_debug (find offset) "
            "→ pwn_rop (gadgets) → pwn_libc → write exploit (run_code, use_venv=true) → test\n"
            "  NX enabled path: skip shellcode → use pwn_rop + pwn_one_gadget instead.\n\n"
            "Research:\n"
            "  web_search → fetch_url (full page) → synthesize → write_file\n\n"
            "History:\n"
            "  /chat find <keywords>  →  /chat view <id>  →  answer user\n\n"
            "Delegation (Smart Routing):\n"
            "  当需要阅读超过 500 行的长代码、分析巨型 Log 或进行深度全网搜索时，\n"
            "  MUST 使用 delegate_task。不要用自己的上下文硬扛。\n\n"
            "Environment & Files:\n"
            "  WSL Paths: Windows Desktop in WSL is '/mnt/c/Users/<username>/Desktop'.\n"
            "    ALWAYS start paths with '/'. 'mnt/c/...' (no leading slash) is WRONG.\n"
            "  Binary Files: read_file is ONLY for plain text / source code.\n"
            "    For .doc / .docx → run_shell: 'pandoc -t plain file.docx' or 'catdoc file.doc'\n"
            "    For .pdf         → run_shell: 'pandoc -t plain file.pdf' or 'pdftotext file.pdf -'\n"
            "    NEVER call read_file on binary formats — it produces garbage output.\n\n"

            "=== ATOMIC COMMITS ===\n"
            "After every patch_file / write_file that passes <verify>:\n"
            "  run_shell (verify) → if PASS → git_op action='commit' message='feat/fix/refactor: ...'\n\n"

            "=== Global Skills Archive (GSA) Protocol ===\n"
            f"Skills file: {GLOBAL_SKILLS_PATH}\n\n"
            "WHEN TO TRIGGER: After a task is fully solved AND the <verify> command passed.\n"
            "Only trigger GSA if the solution involved non-trivial technical insight "
            "(not for trivial lookups).\n\n"
            "GSA CONSOLIDATION STEPS (execute in order, no skipping):\n\n"
            "  Step 1 — Read current skill categories:\n"
            f"    read_file_lines(path='{GLOBAL_SKILLS_PATH}', start_line=1, end_line=50)\n"
            "    → Extract all # level-1 headings you see.\n\n"
            "  Step 2 — Semantic classification (DYNAMIC, no fixed categories):\n"
            "    Look at the existing # headings you just read.\n"
            "    Ask: which heading does this solution belong to semantically?\n"
            "      · MATCH → use that existing heading (exact text).\n"
            "      · NO MATCH → create a new heading with format: 'EMOJI Domain/Subdomain'\n"
            "        Examples: '🛡️ Pwn/Stack', '🔗 ROP/Ret2Libc', '🐍 Python/Decorators',\n"
            "                  '📐 Algo/DP', '🏗️ C++/Templates', '🔑 Crypto/RSA'\n"
            "        The emoji must semantically reflect the domain.\n\n"
            "  Step 3 — Draft the skill block:\n"
            "    Write a ## Skill Name block with:\n"
            "      · What: one-line technical summary\n"
            "      · When: trigger condition\n"
            "      · How: key commands/code snippet (fenced, ≤ 20 lines)\n"
            "      · Gotcha: one critical pitfall (optional)\n\n"
            "  Step 4 — Duplicate check:\n"
            "    Search for '## <your skill name>' in the file content you already read.\n"
            "    · Found once → rename to '## <Skill Name> Case 2'\n"
            "    · Found as 'Case N' → use 'Case N+1'\n\n"
            "  Step 5 — Write to file:\n"
            "    Use patch_file with a SEARCH/REPLACE block:\n"
            "      · To append under existing category: SEARCH = last non-empty line of that section\n"
            "        REPLACE = original_line + '\\n\\n' + skill_block\n"
            "      · To create new category: SEARCH = last line of entire file\n"
            "        REPLACE = original_line + '\\n\\n# NEW_CATEGORY\\n\\n' + skill_block\n\n"
            "IMPORTANT: GSA is OPTIONAL and SILENT. Do NOT announce it to the user unless asked.\n"
            "Just execute it after task completion. If it fails, log internally and continue.\n\n"

            f"=== Current GSA Categories (from global_skills.md) ===\n"
            f"{skills_toc}\n"
            "(Use these headings for semantic matching in Step 2 above.)\n\n"

            # ★ 动态注入：与当前任务相关的技能全文
            + (
                f"=== GSA Relevant Skills (ranked by recency × usage × similarity) ===\n"
                f"{_relevant_skills_md}\n"
                "(Above skills were auto-retrieved for this query. "
                "If one solves your problem, call bump_skill(skill_name=...) after <verify> passes.)\n\n"
                if _relevant_skills_md else ""
            )

            # ★ P6: 本地技能引擎 — 从 ./skills/ 检索相关技能
            + (
                f"=== Local Skills (from ./skills/ directory) ===\n"
                f"{_local_skills_md}\n"
                "(Above skills were auto-retrieved from local skill files. "
                "Follow their instructions if relevant to the current task.)\n\n"
                if _local_skills_md else ""
            )

            # ★ 冲突预警注入
            + (
                f"{_conflict_warning}\n\n"
                if _conflict_warning else ""
            )

            # ════════════════════════════════════════════════
            # ★ 修改 1：语言锁（动态匹配 + 防漂移）
            # ════════════════════════════════════════════════
            + "<language_rule>\n"
            "DYNAMIC LANGUAGE MATCHING & ANTI-DRIFT:\n"
            "1. You MUST respond in the EXACT language used by the user in their latest prompt "
            "(Simplified Chinese or English).\n"
            "2. Your internal <plan> tags MAY use English for technical precision, "
            "regardless of the user's language.\n"
            "3. ANTI-DRIFT CRITICAL: The Pwn context contains heavy English terminology. "
            "Do NOT let this cause language drift. "
            "NEVER output Korean, Japanese, or any other unprompted languages.\n"
            "</language_rule>\n"
        )

        if knowledge_block:
            prompt += f"\n{knowledge_block}\n"
        if state_block:
            prompt += (
                f"\n=== Project State (.pawn_state.md) ===\n{state_block}\n"
                "=== End of Project State ===\n"
                "(Keep the above goals in mind even after /clear)\n"
            )

        if self.messages and self.messages[0]["role"] == "system":
            self.messages[0]["content"] = prompt
        else:
            self.messages.insert(0, {"role": "system", "content": prompt})

    # ════════════════════════════════════════════════════
    # 模块 2：自动直觉检索辅助
    # ════════════════════════════════════════════════════

    @staticmethod
    def _auto_intuitive_search(query: str) -> str:
        try:
            rows = search_knowledge(query, limit=3)
            if not rows:
                return ""
            lines = [
                f"\n[🧠 Auto-Intuition — knowledge search for '{query}']\n"
                f"  Found {len(rows)} relevant entries from past sessions:\n"
            ]
            for row in rows:
                topic   = row.get("topic", "")
                snippet = str(row.get("content", ""))[:200]
                src     = row.get("source_session", "")
                lines.append(
                    f"  • [{topic}]  {snippet}{'...' if len(str(row.get('content','')))>200 else ''}\n"
                    f"    (from session: {src})\n"
                )
            lines.append(
                "  → If the above entries solve your search, stop directory traversal.\n"
            )
            return "".join(lines)
        except Exception:
            return ""

    # ════════════════════════════════════════════════════
    # Hybrid v2 双协议解析器
    # ════════════════════════════════════════════════════

    def _extract_calls(self, text_buf: str) -> list:
        """
        Hybrid v2 双协议解析器。

        优先级：
          1. XML <call name="...">...</call>   — 零转义，完美处理中文与多行代码
          2. JSON <tool_call>{...}</tool_call> — 紧凑格式，适合单行 ASCII 参数

        返回格式：
          [{"name": str, "args": dict, "_source": "xml"|"json"}, ...]

        容错：
          · XML 缺失 </call> 尾标签时，截取至字符串末尾尝试补全解析。
          · JSON 使用 strict=False 允许参数字符串中出现真实换行符。
        """
        import re
        results = []

        # ── 1. XML 路径：优先匹配完整 <call>…</call> ─────────────
        _XML_FULL = re.compile(
            r'<call\s+name="(?P<name>[^"]+)">(?P<args_block>.*?)</call>',
            re.DOTALL,
        )
        # 容错：模型忘记写 </call> 时，截取至字符串末尾
        _XML_PARTIAL = re.compile(
            r'<call\s+name="(?P<name>[^"]+)">(?P<args_block>.*)',
            re.DOTALL,
        )
        # XML 参数内部子标签匹配（递归解析 args_block）
        _XML_PARAM = re.compile(
            r'<(?P<key>[a-zA-Z_][a-zA-Z0-9_]*)>(?P<val>.*?)</(?P=key)>',
            re.DOTALL,
        )

        xml_matches = list(_XML_FULL.finditer(text_buf))
        _used_partial = False
        if not xml_matches:
            xml_matches = list(_XML_PARTIAL.finditer(text_buf))
            _used_partial = bool(xml_matches)

        if xml_matches:
            for m in xml_matches:
                name = m.group("name").strip()
                args_block = m.group("args_block")
                if _used_partial:
                    print(c(GRAY, "  ⚙ [XML Parser] 检测到未闭合 </call>，已启用容错补全解析"))

                args: dict = {}
                for pm in _XML_PARAM.finditer(args_block):
                    key = pm.group("key").strip()
                    # 🔑 零转义：仅 .strip() 去除标签周围空白，内容原样透传
                    val_raw = pm.group("val").strip()

                    # ── 类型自动纠正 ──────────────────────────────
                    if val_raw.lstrip("-").isdigit():
                        val: object = int(val_raw)
                    elif val_raw.lower() == "true":
                        val = True
                    elif val_raw.lower() == "false":
                        val = False
                    else:
                        val = val_raw   # 保留原始字符串（含换行符、中文等）

                    args[key] = val

                if name and args:
                    results.append({"name": name, "args": args, "_source": "xml"})

            if results:
                return results

        # ── 2. JSON 兜底：兼容 <tool_call>{...}</tool_call> 幻觉 ─
        if "<tool_call>" in text_buf:
            match = re.search(r"<tool_call>\s*(\{.*)", text_buf, re.DOTALL)
            if match:
                json_str = match.group(1)
                json_str = re.sub(
                    r"</tool_call>.*$", "", json_str, flags=re.DOTALL
                ).strip()
                try:
                    # strict=False 允许参数中存在真实换行符（专治代码生成器）
                    parsed_tc = json.loads(json_str, strict=False)
                    if "name" in parsed_tc and "arguments" in parsed_tc:
                        raw_args = parsed_tc["arguments"]
                        args_dict = (
                            raw_args
                            if isinstance(raw_args, dict)
                            else {"_raw_args": str(raw_args)}
                        )
                        results.append({
                            "name":    parsed_tc["name"],
                            "args":    args_dict,
                            "_source": "json",
                        })
                except json.JSONDecodeError as e:
                        # ── 脏 JSON 抢救逻辑：尝试修复未转义的双引号 ──
                        rescued = False
                        try:
                            import re as _re
                            # 贪婪匹配 content 字段中的所有内容
                            content_match = _re.search(r'"content"\s*:\s*"(.*)"\s*\}', json_str, _re.DOTALL)
                            if content_match:
                                bad_content = content_match.group(1)
                                # 将中间的双引号转义，但避免重复转义已转义的引号
                                fixed_content = _re.sub(r'(?<!\\)"', r'\"', bad_content)
                                fixed_j_str = json_str.replace(bad_content, fixed_content)

                                parsed_tc = json.loads(fixed_j_str, strict=False)
                                if "name" in parsed_tc and "arguments" in parsed_tc:
                                    raw_args = parsed_tc["arguments"]
                                    args_dict = (
                                        raw_args
                                        if isinstance(raw_args, dict)
                                        else {"_raw_args": str(raw_args)}
                                    )
                                    results.append({
                                        "name": parsed_tc["name"],
                                        "args": args_dict,
                                        "_source": "json_rescued",
                                    })
                                    rescued = True
                        except Exception:
                            pass

                        if not rescued:
                            logger.error(
                                "Hybrid Parser: JSON fallback corrupted | "
                                "model={} session={} exc={!r}\n"
                                "--- RAW (truncated 4096) ---\n{}\n--- END ---",
                                self.model_alias, self.session_id[:8], e, json_str[:4096],
                            )
                            if USER_MODE:
                                print(c(RED, "  ❌ 系统忙，请稍后重试"))
                            else:
                                print(c(RED, f"  ✗ [Hybrid Parser] JSON 兜底解析失败: {e}"))
                        else:
                            print(c(YELLOW, f"  ⚠ [Hybrid Parser] 探测到脏 JSON，已通过正则抢救成功！"))

        return results

    # ── 主轮次 ────────────────────────────────────────────
    def run_turn(self, user_input: str):
        self._reset_system_prompt(knowledge_query=user_input)
        self.messages.append({"role": "user", "content": user_input})

        dropped = _trim_and_compact_context(self.messages)
        if dropped:
            print(c(YELLOW,
                    f"  ⚠ 上下文过长，已将最旧 {dropped} 条消息压缩为摘要（Tool Clearing）"
                    ))
            logger.warning(
                "Context compacted (Tool Clearing) | session={} compacted={} model={}",
                self.session_id[:8], dropped, self.model_alias,
            )

        ok, env_name = validate_api_key(self.model_alias)
        if not ok:
            print(c(RED, f"  ✗ {self.model_alias} 需要 {env_name}，请 export {env_name}=sk-..."))
            logger.error(
                "API key missing | model={} required_env={}",
                self.model_alias, env_name,
            )
            return

        cfg = self.model
        print(c(cfg["color"] + BOLD, f"[{self.model_alias.upper()}]"), end=" ", flush=True)

        # Reset per-turn accounting
        self._turn_prompt_tokens     = 0
        self._turn_completion_tokens = 0
        self._turn_tool_calls        = 0

        # ── P1: 时间感知初始化 ──────────────────────────
        self._turn_start_time = time.monotonic()
        self._time_budget_sec = DYNAMIC_CONFIG.get("time_budget_sec", 0)
        self._urgent_mode     = False
        if self._time_budget_sec > 0:
            _mins = self._time_budget_sec // 60
            _secs = self._time_budget_sec % 60
            print(c(GRAY, f"  ⏱  时间预算: {_mins}m{_secs}s"))

        max_iter           = DYNAMIC_CONFIG["max_iter"]
        renderer           = _PlanRenderer()
        is_vision_model    = self.model.get("vision", False)
        current_max_tokens = 4096 if is_vision_model else DYNAMIC_CONFIG["max_tokens"]
        if is_vision_model:
            print(c(YELLOW, "  ℹ 视觉模型已禁用工具调用"))
            current_tools = None
        else:
            # ── MoE 动态工具裁剪 ──────────────────────────────
            phase_whitelist = set(AGENT_PHASES.get(self.current_phase, []))
            current_tools = [
                s for s in TOOLS_SCHEMA
                if s.get("function", {}).get("name") in phase_whitelist
                or s.get("function", {}).get("name") in ("switch_phase", "bump_skill")  # ★
            ]
            print(c(GRAY,
                f"  📡 [Phase:{self.current_phase}] "
                f"加载 {len(current_tools)} 个工具 "
                f"({', '.join(s['function']['name'] for s in current_tools)})"
            ))

        _plan_rejected    = 0
        _dir_search_count = 0
        _DIR_THRESHOLD    = 3

        # ── Logic Refresh 模块状态 ─────────────────────────
        _LOGIC_REFRESH_INTERVAL = 20   # 每 20 轮触发一次阶段性总结
        _REPEAT_ERROR_THRESHOLD = 3    # 连续相同错误阈值
        _recent_cmd_errors: list[tuple[str, str]] = []  # (cmd, error) 历史
        _repeat_error_count   = 0      # 当前连续相同错误计数

        for iteration in range(max_iter):
            # ── P6.5: 首轮迭代显示技能包加载状态 ────────
            if iteration == 0 and self._loaded_skill_packs:
                if USER_MODE:
                    print(c(GREEN, _skill_scanner.format_user_message(self._loaded_skill_packs)))
                else:
                    for _sp in self._loaded_skill_packs:
                        print(c(CYAN, f"  📦 [Skill Pack] {_sp.get('name', '?')} v{_sp.get('version', '1.0')}"))
                        _sp_path = _sp.get("_path", "")
                        if _sp.get("guide"):
                            print(c(GRAY, f"     guide: {_sp_path}/{_sp['guide']}"))
                        if _sp.get("scripts"):
                            print(c(GRAY, f"     scripts: {', '.join(_sp['scripts'])}"))

            # ── P1: 每轮迭代时间检查 ────────────────────
            _remaining = self._time_remaining()
            if _remaining <= 0:
                print(c(RED,
                    f"\n  ⏰ [Time Budget] 预算已耗尽（{self._time_budget_sec}s），任务终止。"
                ))
                logger.warning(
                    "Time budget exhausted | session={} budget={}s",
                    self.session_id[:8], self._time_budget_sec,
                )
                break

            if not self._urgent_mode and _remaining < _URGENT_THRESHOLD_SEC:
                # ── 触发 URGENT_MODE ──────────────────────
                self._urgent_mode = True
                print(c(RED,
                    f"  🚨 [URGENT_MODE] 剩余 {_remaining:.0f}s — "
                    f"切换至极速模式"
                ))
                logger.info(
                    "URGENT_MODE activated | session={} remaining={:.1f}s",
                    self.session_id[:8], _remaining,
                )

                # 注入 URGENT 信号到上下文
                self.messages.append({
                    "role": "user",
                    "content": _URGENT_SIGNAL,
                })

                # 自动切换到极速模型
                for _u_alias in _URGENT_MODEL_CANDIDATES:
                    if _u_alias in MODELS:
                        _u_ok, _ = validate_api_key(_u_alias)
                        if _u_ok and _u_alias != self.model_alias:
                            old_model = self.model_alias
                            self.model_alias = _u_alias
                            print(c(MAGENTA,
                                f"  🚨 [URGENT] 模型已切换: "
                                f"{old_model} → {_u_alias}（极速响应）"
                            ))
                            # 重建工具列表
                            phase_whitelist = set(AGENT_PHASES.get(self.current_phase, []))
                            current_tools = [
                                s for s in TOOLS_SCHEMA
                                if s.get("function", {}).get("name") in phase_whitelist
                                or s.get("function", {}).get("name") in ("switch_phase", "bump_skill")
                            ]
                            current_max_tokens = min(current_max_tokens, 4096)
                            break

            # ════════════════════════════════════════════════
            # Logic Refresh 模块：阶段性总结 + 冗余清理 + 错误检测
            # ════════════════════════════════════════════════

            # ── 1. 阶段性总结（每 N 轮触发）────────────────
            if iteration > 0 and iteration % _LOGIC_REFRESH_INTERVAL == 0:
                # 收集最近的 tool observation
                _recent_obs = []
                for _m in self.messages[-20:]:
                    if _m.get("role") == "tool" and _m.get("content"):
                        _recent_obs.append(_m["content"][:200])
                if _recent_obs:
                    _obs_text = "\n".join(_recent_obs[-10:])
                    _summary_prompt = (
                        f"[Logic Refresh — Iteration {iteration}]\n"
                        f"请对以下最近的探索路径进行简明总结（5 句话以内），"
                        f"提炼关键发现、已排除的路径和当前最佳方向：\n\n{_obs_text}"
                    )
                    self.messages.append({"role": "user", "content": _summary_prompt})
                    print(c(CYAN,
                        f"  🔄 [Logic Refresh] 已触发阶段性总结（iteration={iteration}）"
                    ))
                    logger.info(
                        "Logic Refresh: phase summary triggered | "
                        "session={} iteration={} obs_count={}",
                        self.session_id[:8], iteration, len(_recent_obs),
                    )

            # ── 2. 冗余数据清理（合并重复 ls/cat 报错）──────
            _REDUNDANT_PATTERNS = (
                "No such file or directory",
                "Permission denied",
                "command not found",
                "is a directory",
                "Not a directory",
            )
            _seen_errors: dict[str, int] = {}
            _msgs_to_compact = []
            for _mi, _m in enumerate(self.messages[1:], 1):  # skip system
                if _m.get("role") != "tool":
                    continue
                _content = _m.get("content") or ""
                for _rp in _REDUNDANT_PATTERNS:
                    if _rp in _content and len(_content) < 300:
                        _key = _rp
                        _seen_errors[_key] = _seen_errors.get(_key, 0) + 1
                        if _seen_errors[_key] > 3:
                            _msgs_to_compact.append(_mi)
                        break
            # 将重复报错压缩为单行占位
            for _mi in reversed(_msgs_to_compact):
                _old = self.messages[_mi]
                _old_content = _old.get("content") or ""
                # 只压缩短报错（长输出保留原文）
                if len(_old_content) < 300:
                    self.messages[_mi]["content"] = (
                        f"(已压缩: {_old_content[:60]}...) — 同类报错已出现 {_seen_errors.get(_REDUNDANT_PATTERNS[0], '?')} 次"
                    )

            # ── 3. 重复错误检测（连续 3 次相同命令+错误）───
            if _repeat_error_count >= _REPEAT_ERROR_THRESHOLD:
                _anti_loop_msg = (
                    "[System] 当前路径似乎不通：检测到连续 "
                    f"{_repeat_error_count} 次相同命令返回相同错误。"
                    "请重新审视 exploit 逻辑，考虑以下绕过方向：\n"
                    "  1. 软链接绕过（ln -s）\n"
                    "  2. open_basedir 绕过（php -d open_basedir=/）\n"
                    "  3. 路径编码绕过（../ ./ ..%2f）\n"
                    "  4. 切换工具或攻击向量\n"
                    "  5. 向用户确认目标环境信息"
                )
                self.messages.append({"role": "user", "content": _anti_loop_msg})
                print(c(YELLOW,
                    f"  🔁 [Anti-Loop] 检测到连续 {_repeat_error_count} 次相同错误，已注入绕过提示"
                ))
                logger.warning(
                    "Anti-Loop: repeated error detected | "
                    "session={} iteration={} count={}",
                    self.session_id[:8], iteration, _repeat_error_count,
                )
                _repeat_error_count = 0  # 重置，避免反复注入

            # ── API 调用 + 空响应重试（指数退避）─────────────
            _api_retry = 0
            _API_RETRY_MAX = 3
            text_buf = ""; tc_buf = {}

            while True:
                text_buf = ""; tc_buf = {}
                _tokens_before = self._turn_completion_tokens

                for delta in stream_request(
                    self.messages, self.model_alias,
                    tools_schema=current_tools,
                    max_tokens=current_max_tokens,
                ):
                    if "_error" in delta:
                        _err_detail = delta["_error"]
                        if USER_MODE:
                            print(c(RED, f"\n  {user_friendly_error(_err_detail)}"))
                        else:
                            print(c(RED, f"\nAPI Error: {_err_detail}"))
                        logger.error(
                            "API stream error | model={} session={} iteration={} raw_error={}",
                            self.model_alias, self.session_id[:8], iteration, _err_detail,
                        )
                        self.messages.pop(); return

                    choices = delta.get("choices", [])
                    if not choices: continue
                    d     = choices[0].get("delta", {})
                    chunk = d.get("content") or ""

                    # ── Usage accounting (_usage injected by api_client) ──
                    if "_usage" in delta:
                        u  = delta["_usage"]
                        pt = u.get("prompt_tokens", 0) or u.get("input_tokens", 0)
                        ct = u.get("completion_tokens", 0) or u.get("output_tokens", 0)
                        self._turn_prompt_tokens     += pt
                        self._turn_completion_tokens += ct
                        self.total_prompt_tokens     += pt
                        self.total_completion_tokens += ct

                    if chunk:
                        printable = renderer.feed(chunk)
                        if printable: sys.stdout.write(printable); sys.stdout.flush()
                        text_buf += chunk

                    for tcd in (d.get("tool_calls") or []):
                        idx = tcd.get("index", 0)
                        if idx not in tc_buf:
                            tc_buf[idx] = {
                                "id": ensure_tool_call_id(tcd, iteration, idx),
                                "name": "", "args": "",
                            }
                        fn = tcd.get("function", {})
                        tc_buf[idx]["name"] += fn.get("name") or ""
                        tc_buf[idx]["args"] += fn.get("arguments") or ""

                leftover = renderer.flush()

                # ── P2: rich Markdown 渲染（仅对非 plan 文本）──
                if leftover:
                    _md_indicators = ("```", "**", "| ", "## ", "- ", "1. ", "> ")
                    _has_md = any(ind in leftover for ind in _md_indicators)
                    _rendered = False
                    if _has_md:
                        try:
                            from main import render_agent_output
                            render_agent_output(leftover)
                            _rendered = True
                        except (ImportError, Exception):
                            pass
                    if not _rendered:
                        sys.stdout.write(leftover)
                        sys.stdout.flush()
                print()

                # ── Hybrid v2 Parser：XML 优先，JSON 兜底 ─────────────
                if not tc_buf and (
                    '<call name="' in text_buf or "<tool_call>" in text_buf
                ):
                    extracted = self._extract_calls(text_buf)
                    for i, call in enumerate(extracted):
                        source = call["_source"]
                        call_id = (
                            f"call_xml_{iteration}_{i}"
                            if source == "xml"
                            else f"call_fallback_{iteration}_{i}"
                        )
                        tc_buf[i] = {
                            "id":           call_id,
                            "name":         call["name"],
                            "args":         json.dumps(call["args"], ensure_ascii=False),
                            "_args_parsed": call["args"],
                        }
                        label = "XML" if source == "xml" else "JSON"
                        print(c(GRAY,
                            f"  ⚙ [Hybrid Parser/{label}] 拦截工具调用: {call['name']} "
                            f"(params: {list(call['args'].keys())})"
                        ))
                        logger.info(
                            "Hybrid Parser/{} intercepted | "
                            "model={} session={} iteration={} tool={}",
                            label, self.model_alias, self.session_id[:8],
                            iteration, call["name"],
                        )
                    import re as _re
                    _trim = _re.search(r'<call\s+name="|<tool_call>', text_buf)
                    if _trim and extracted:
                        text_buf = text_buf[:_trim.start()]
                # ─────────────────────────────────────────────────────────

                # ── 空响应检测 + 指数退避重试 ────────────────────
                _no_new_tokens = (self._turn_completion_tokens == _tokens_before)
                _empty_response = (not text_buf.strip() and not tc_buf and _no_new_tokens)

                if not _empty_response:
                    break   # 有效响应，退出重试循环

                _api_retry += 1
                if _api_retry >= _API_RETRY_MAX:
                    print(c(YELLOW,
                        f"\n  ⚠ [API Recovery] 连续 {_api_retry} 次收到空响应，注入恢复提示继续任务..."
                    ))
                    logger.warning(
                        "API empty response: retries exhausted | "
                        "model={} session={} iteration={} retries={}",
                        self.model_alias, self.session_id[:8], iteration, _api_retry,
                    )
                    self.messages.append({
                        "role": "user",
                        "content": (
                            "[System] 收到无效响应（空内容/0 Token），请重新审视任务目标并继续。"
                            "如果此问题反复出现，考虑切换模型（/model）或检查 API 密钥。"
                        ),
                    })
                    break   # 退出重试循环，进入下一个 iteration

                _wait = min(2 ** _api_retry, 8)
                print(c(YELLOW,
                    f"\n  ⚠ [API Recovery] 收到无效响应，正在尝试恢复... "
                    f"({_api_retry}/{_API_RETRY_MAX}，等待 {_wait}s)"
                ))
                logger.warning(
                    "API empty response detected, retrying | "
                    "model={} session={} iteration={} attempt={} wait={}s",
                    self.model_alias, self.session_id[:8], iteration, _api_retry, _wait,
                )
                time.sleep(_wait)
                continue   # 重试 API 调用

            # ── 如果重试耗尽仍为空响应，跳过工具执行 ─────────
            if _empty_response and _api_retry >= _API_RETRY_MAX:
                continue   # 进入下一个 iteration

            if not tc_buf:
                self.messages.append({"role": "assistant", "content": text_buf})
                self._print_turn_summary()
                self._autosave(); return

            # ════════════════════════════════════════════════
            # ★ 改动 [3]：CoT Guard 重构 — 教练模式
            #
            # 判断次序：
            #   1. 豁免检查（只读工具无需 plan）
            #   2. 软拦截 × MAX_SOFT_CORRECTIONS（工具照常执行，追加信号）
            #   3. 硬终止 × 1（软拦截耗尽后才触发）
            #
            # 信号注入：
            #   · 不阻断工具执行，让模型先看到结果
            #   · 信号以 "user" 角色追加在工具结果之后（attention 贴近推理层）
            # ════════════════════════════════════════════════
            has_plan    = "<plan>" in text_buf.lower()
            is_exempt   = _is_plan_exempt(tc_buf)
            # P1.7: URGENT_MODE 跳过 CoT Guard
            need_plan   = not has_plan and not is_exempt and not self._urgent_mode

            _plan_signal_injected = False

            if _plan_rejected > _MAX_SOFT_CORRECTIONS:
                # ── 硬终止：软拦截已耗尽 ──────────────────
                print(c(RED,
                        f"  ⛔ [CoT Guard] 连续 {_plan_rejected} 次未提供 <plan>，任务已终止。"
                        ))
                print(c(GRAY,
                        "  建议：1. 简化指令  2. 切换更强模型（/model ds-chat）"
                        ))
                logger.warning(
                    "CoT Guard: hard kill triggered | "
                    "model={} session={} iteration={} plan_rejected={}",
                    self.model_alias, self.session_id[:8],
                    iteration, _plan_rejected,
                )
                if self.messages and self.messages[-1]["role"] == "user":
                    self.messages.pop()  # 撤销上一条 user 消息，保持上下文干净
                return

                # ── 软拦截：工具仍执行，计划注入信号 ──────────
                print(c(YELLOW,
                    f"  💭 [CoT Soft #{_plan_rejected}/{_MAX_SOFT_CORRECTIONS}] "
                    "检测到缺失 <plan>，工具已执行，修正信号将在结果后注入..."
                ))
                logger.debug(
                    "CoT Guard: soft intercept #{} | model={} session={} iteration={}",
                    _plan_rejected, self.model_alias, self.session_id[:8], iteration,
                )
                _plan_signal_injected = True

            else:
                _plan_rejected = 0   # 成功输出 <plan>，重置计数

            # ── 模块 1B：并发截断 ──────────────────────────
            if len(tc_buf) > _MAX_CONCURRENT_TOOLS:
                orig = len(tc_buf)
                kept = sorted(tc_buf.keys())[:_MAX_CONCURRENT_TOOLS]
                tc_buf = {k: tc_buf[k] for k in kept}
                print(c(YELLOW, f"  ✂ [并发限制] {orig} 个工具调用已截断至前 {_MAX_CONCURRENT_TOOLS} 个。"))
                logger.warning(
                    "Concurrent tool limit | model={} session={} original={} kept={}",
                    self.model_alias, self.session_id[:8], orig, _MAX_CONCURRENT_TOOLS,
                )


            self.messages.append({
                "role":    "assistant",
                "content": text_buf or None,
                "tool_calls": [
                    {"id": tc_buf[i]["id"], "type": "function",
                     "function": {"name": tc_buf[i]["name"], "arguments": tc_buf[i]["args"]}}
                    for i in sorted(tc_buf)
                ],
            })

            # ── 执行所有工具 ───────────────────────────────
            for i in sorted(tc_buf):
                tc = tc_buf[i];
                name = tc["name"]

                # 🔑 优先使用 XML/Hybrid Parser 透传的零转义字典
                if "_args_parsed" in tc:
                    fn_args = tc["_args_parsed"]
                else:
                    fn_args = {}
                    if tc["args"].strip():
                        try:
                            fn_args = json.loads(tc["args"])
                        except json.JSONDecodeError:
                            try:
                                fn_args = json.loads(tc["args"].strip().lstrip("\ufeff"))
                            except:
                                fn_args = {"_raw_args": tc["args"]}

                preview  = ", ".join(f"{k}={repr(v)[:40]}" for k, v in fn_args.items())
                iter_tag = c(GRAY, f"[{iteration+1}/{max_iter}]")

                # P6: USER_MODE 下检测技能包脚本调用，简化输出
                _is_skill_call = False
                if USER_MODE and name == "run_shell":
                    _cmd = fn_args.get("command", "") or fn_args.get("_raw_args", "")
                    _skills_dir_str = str(SKILLS_DIR).replace("\\", "/")
                    if _skills_dir_str in _cmd.replace("\\", "/") and any(
                        _cmd.strip().endswith(ext) or f"python3 {_skills_dir_str}" in _cmd.replace("\\", "/")
                        for ext in (".py", ".sh")
                    ):
                        _is_skill_call = True
                        # 从命令中提取技能包名称
                        _parts = _cmd.replace("\\", "/").split("/skills/")
                        _pack_hint = _parts[1].split("/")[0] if len(_parts) > 1 else "unknown"
                        print(c(GREEN, f"  🚀 [P6] 正在调用针对 {_pack_hint} 的自动化验证脚本...") + f" {iter_tag}")

                if not _is_skill_call:
                    print(c(YELLOW, f"  🔧 {name}") + c(GRAY, f"({preview[:80]})") + f" {iter_tag}")

                # ── switch_phase 拦截（直接操作实例状态）────────
                if name == "switch_phase":
                    target = fn_args.get("phase", "").upper()
                    reason = fn_args.get("reason", "（未说明原因）")
                    if target in AGENT_PHASES:
                        old_phase = self.current_phase
                        self.current_phase = target
                        # 重建动态工具列表（下一轮迭代生效）
                        phase_whitelist = set(AGENT_PHASES[target])
                        current_tools = [
                            s for s in TOOLS_SCHEMA
                            if s.get("function", {}).get("name") in phase_whitelist
                            or s.get("function", {}).get("name") in ("switch_phase", "bump_skill")  # ★
                        ]
                        result = (
                            f"[Phase Switch] {old_phase} → {target}\n"
                            f"Reason: {reason}\n"
                            f"Now available: {', '.join(phase_whitelist)}\n"
                            f"switch_phase is always available.\n"
                            f"Reload: {len(current_tools)} tools active."
                        )
                        print(c(MAGENTA,
                            f"  🔀 [Phase Switch] {old_phase} → {target}  ({reason[:60]})"
                        ))
                        logger.info(
                            "Phase switch | model={} session={} {} → {} reason={}",
                            self.model_alias, self.session_id[:8],
                            old_phase, target, reason,
                        )
                        # 刷新系统提示词中的 Phase 感知块
                        self._reset_system_prompt()
                    else:
                        result = (
                            f"ERROR: 未知阶段 '{target}'。"
                            f"可用: {', '.join(AGENT_PHASES.keys())}"
                        )

                else:
                    _VERBOSE_TOOLS = {
                        "read_file", "read_file_lines",
                        "run_shell", "run_code",
                        "pwn_debug", "pwn_rop", "pwn_disasm", "pwn_cyclic", "pwn_libc",
                        "inspect_binary", "web_search", "fetch_url", "find_refs",
                    }

                    # ── P0.6: 投前失败审计（危险工具自动检查）───
                    _failure_warning = ""
                    if name in _AUDITED_TOOLS:
                        try:
                            _fail_rows = check_failure(name, args_keywords=preview[:200], limit=3)
                            if _fail_rows:
                                _failure_warning = format_failures_for_prompt(_fail_rows)
                                print(c(YELLOW,
                                    f"  ⚠ [Anti-Pattern] {name} 存在 "
                                    f"{len(_fail_rows)} 条历史失败记录"
                                ))
                        except Exception:
                            pass

                    # ── 审计计时 ────────────────────────────
                    _t0 = time.monotonic()
                    _audit_ok = True
                    try:
                        result = TOOL_MAP[name](fn_args) if name in TOOL_MAP else f"ERROR: 未知工具 '{name}'"

                        # ★ P0.7 增强：语义级失败判定
                        # 工具本身没抛异常，但 result 内容表明执行失败
                        _SEMANTIC_FAILURE_SIGNALS = (
                            "ERROR:", "Traceback", "Segmentation fault", "SIGSEGV",
                            "NameError", "SyntaxError", "TypeError", "AttributeError",
                            "ImportError", "ModuleNotFoundError", "FileNotFoundError",
                            "PermissionError", "RuntimeError", "ValueError",
                            "panic", "FATAL", "core dumped", "Aborted",
                            "编译失败", "exit 1", "exit 2", "exit 126", "exit 127",
                            "exit 134", "exit 139", "command not found",
                        )
                        if any(sig in str(result) for sig in _SEMANTIC_FAILURE_SIGNALS):
                            _audit_ok = False

                    except Exception as _tool_exc:
                        _raw_err = f"ERROR: {type(_tool_exc).__name__}: {_tool_exc}"
                        result = user_friendly_error(_raw_err) if USER_MODE else _raw_err
                        _audit_ok = False
                    _elapsed_ms = int((time.monotonic() - _t0) * 1000)

                    # ── P0.7: 失败自动记录 ──────────────────
                    if not _audit_ok and name in _AUDITED_TOOLS:
                        try:
                            _error_type = ""
                            _r = str(result)
                            _rl = _r.lower()
                            if "timeoutexpired" in _rl or "超时" in _r:
                                _error_type = "Timeout"
                            elif "segmentation fault" in _rl or "sigsegv" in _rl or "core dumped" in _rl:
                                _error_type = "Segfault"
                            elif "编译失败" in _r or "compileerror" in _rl:
                                _error_type = "CompileError"
                            elif "memoryerror" in _rl or "内存超限" in _r:
                                _error_type = "MemoryError"
                            elif "syntaxerror" in _rl or "indentationerror" in _rl:
                                _error_type = "SyntaxError"
                            elif "nameerror" in _rl or "attributeerror" in _rl or "typeerror" in _rl:
                                _error_type = "LogicError"
                            elif "importerror" in _rl or "modulenotfounderror" in _rl:
                                _error_type = "MissingModule"
                            elif "filenotfounderror" in _rl or "command not found" in _rl:
                                _error_type = "NotFound"
                            elif "permissionerror" in _rl:
                                _error_type = "Permission"
                            elif "panic" in _rl or "fatal" in _rl:
                                _error_type = "Panic"
                            elif "exit 139" in _r or "aborted" in _rl:
                                _error_type = "Crash"
                            elif "traceback" in _rl:
                                _error_type = "PythonError"
                            elif "ERROR" in _r:
                                _error_type = "RuntimeError"
                            else:
                                _error_type = "UnknownFailure"

                            _fid = write_failure(
                                tool_name    = name,
                                args_summary = preview[:200],
                                error_msg    = result[:500],
                                error_type   = _error_type,
                                session_id   = self.session_id,
                            )

                            # ── P0.9: 同类失败 ≥ 3 次自动沉淀到 GSA ──
                            if _error_type:
                                _fail_count = count_failure(name, _error_type)
                                if _fail_count >= 3:
                                    _ok, _msg = sink_failure_to_gsa(
                                        tool_name   = name,
                                        error_type  = _error_type,
                                        error_msg   = result[:300],
                                        args_preview= preview[:200],
                                    )
                                    if _ok:
                                        print(c(YELLOW, f"  📝 [GSA Sink] {_msg}"))
                        except Exception:
                            pass  # 失败记录不应阻断主流程

                    # ── 将投前审计警告追加到 tool result ─────
                    if _failure_warning:
                        result = result + "\n\n" + _failure_warning

                    # ── 写入审计日志 ────────────────────────
                    try:
                        audit_tool_call(
                            tool_name    = name,
                            args_summary = preview[:200],
                            result_len   = len(result),
                            elapsed_ms   = _elapsed_ms,
                            session_id   = self.session_id,
                            model_alias  = self.model_alias,
                            iteration    = iteration,
                            success      = _audit_ok,
                        )
                    except Exception:
                        pass  # 审计日志不应阻断主流程

                    if QUIET_MODE or name in _VERBOSE_TOOLS:
                        result = smart_truncate(result, head=30, tail=30)
                    else:
                        limit = DYNAMIC_CONFIG["tool_max_chars"]
                        if len(result) > limit:
                            result = result[:limit//2] + f"\n...[截断至{limit}字符]...\n" + result[-limit//4:]

                # Audit counter
                self._turn_tool_calls  += 1
                self.total_tool_calls  += 1

                # ── 目录搜索计数 & 自动直觉检索 ───────────
                if name in ("list_dir", "find_files"):
                    _dir_search_count += 1
                    if _dir_search_count >= _DIR_THRESHOLD:
                        search_query = (
                            fn_args.get("pattern") or fn_args.get("path") or ""
                        ).strip().strip("*./")
                        auto_result = ""
                        if search_query:
                            print(c(GRAY,
                                f"  🧠 [Auto-Intuition] 目录搜索 {_dir_search_count} 次，"
                                f"检索历史: '{search_query}'"
                            ))
                            auto_result = self._auto_intuitive_search(search_query)
                        hint = (
                            f"\n[System hint — 目录搜索已连续 {_dir_search_count} 次] "
                            "建议切换策略：/chat find <关键词> 检索历史，"
                            "或直接告知用户文件路径未知。"
                        )
                        result = result + hint + auto_result
                else:
                    _dir_search_count = 0

                self.messages.append({
                    "role": "tool", "tool_call_id": tc["id"], "content": result,
                })

                # ── Logic Refresh: 重复错误追踪 ──────────────
                if name == "run_shell" and not _audit_ok:
                    _cmd_key = fn_args.get("command", "") or preview[:80]
                    _err_sig = ""
                    for _sig in ("ERROR:", "Permission denied", "No such file",
                                 "command not found", "Segmentation fault",
                                 "timeout", "超时"):
                        if _sig in str(result):
                            _err_sig = _sig
                            break
                    if _err_sig:
                        _pair = (_cmd_key[:60], _err_sig)
                        if _recent_cmd_errors and _recent_cmd_errors[-1] == _pair:
                            _repeat_error_count += 1
                        else:
                            _repeat_error_count = 1
                        _recent_cmd_errors.append(_pair)
                        # 保留最近 20 条
                        if len(_recent_cmd_errors) > 20:
                            _recent_cmd_errors = _recent_cmd_errors[-20:]

            # ════════════════════════════════════════════════
            # ★ 改动 [3b]：所有工具结果追加完毕后，
            #   若触发了软拦截，注入 PLAN_MISSING 信号。
            #   · 使用 "user" 角色（attention 贴近推理层）
            #   · 工具已执行完毕，模型看到结果再修正，
            #     避免结果丢失导致的重复调用。
            # ════════════════════════════════════════════════
            if _plan_signal_injected:
                self.messages.append({
                    "role":    "user",
                    "content": _PLAN_MISSING_SIGNAL,
                })
                print(c(GRAY,
                    "  🔄 [CoT Self-Correction] 已注入 PLAN_MISSING 修正信号，"
                    "模型将在下一轮自我修正。"
                ))

        print(c(RED, f"\n[达到 max_iter={max_iter}，用 /mid /deep 或 /iter <n> 提升]"))
        logger.warning(
            "max_iter reached | model={} session={} max_iter={}",
            self.model_alias, self.session_id[:8], max_iter,
        )
        self._print_turn_summary()
        self._autosave()

    # ── Per-turn usage summary ───────────────────────────
    def _print_turn_summary(self):
        """Print token + tool-call summary after each turn.
        Uses config.QUIET_MODE (imported at module level) — no NameError.
        """
        pt = self._turn_prompt_tokens
        ct = self._turn_completion_tokens
        tt = self._turn_tool_calls
        if pt + ct + tt == 0:
            return   # nothing to show (no usage data from this provider)
        tot_pt = self.total_prompt_tokens
        tot_ct = self.total_completion_tokens
        tot_tt = self.total_tool_calls
        if QUIET_MODE:
            # Ultra-minimal single line
            cum = (f"  cum:↑{tot_pt:,}↓{tot_ct:,}🔧{tot_tt}"
                   if tot_pt != pt or tot_tt != tt else "")
            print(c(GRAY, f"  [↑{pt:,}tok ↓{ct:,}tok 🔧{tt}]{cum}"))
        else:
            total_turn = pt + ct
            cum_total  = tot_pt + tot_ct
            lines = [
                "",
                "  ┌─ Turn Usage ──────────────────────────────",
                f"  │  Prompt tokens    : {pt:>8,}" +
                (f"   (session: {tot_pt:,})" if tot_pt != pt else ""),
                f"  │  Completion tokens: {ct:>8,}" +
                (f"   (session: {tot_ct:,})" if tot_ct != ct else ""),
                f"  │  Total this turn  : {total_turn:>8,}" +
                (f"   (session: {cum_total:,})" if cum_total != total_turn else ""),
                f"  │  Tool calls       : {tt:>8,}" +
                (f"   (session: {tot_tt:,})" if tot_tt != tt else ""),
                "  └───────────────────────────────────────────",
            ]
            print(c(GRAY, "\n".join(lines)))

    # ── 后台异步自动保存 ──────────────────────────────────
    def _autosave(self):
        msgs_snapshot = [dict(m) for m in self.messages]
        sid, model_alias, cwd, cfg_snap = (
            self.session_id, self.model_alias, self.cwd, dict(DYNAMIC_CONFIG)
        )
        def _do():
            if not self._save_lock.acquire(blocking=False): return
            try:
                from core.memory import upsert_session, save_messages
                upsert_session(sid, "", model_alias, cwd, cfg_snap)
                save_messages(sid, msgs_snapshot)
            except Exception as _autosave_exc:
                # 原来是 pass（静默丢失错误），现在写入日志文件
                logger.error(
                    "Autosave failed | session={} model={} exc={!r}",
                    sid[:8], model_alias, _autosave_exc,
                )
            finally:
                self._save_lock.release()

        threading.Thread(target=_do, daemon=True, name=f"save-{sid[:8]}").start()
