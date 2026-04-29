"""
core/session.py — AgentSession · Agentic Loop
1.0 (Expert Edition — Plan-as-Key Architecture)

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

import os, json, sys, threading
from datetime import datetime
from pathlib import Path
from config import (
    DYNAMIC_CONFIG, MODELS, DEFAULT_MODEL,
    validate_api_key, VERSION, GLOBAL_SKILLS_PATH,
    QUIET_MODE, smart_truncate,
    AGENT_PHASES,
)
from utils.ansi import c, BOLD, DIM, GRAY, CYAN, GREEN, YELLOW, RED, MAGENTA
from core.api_client import stream_request, ensure_tool_call_id
from core.memory import (
    init_db, _gen_id, save_messages,
    search_knowledge, format_knowledge_for_prompt,
)
from core.gsa import load_relevant_skills, bump_skill   # ★ GSA 衰减检索 + 反馈工具

from tools.file_ops  import (tool_read_file, tool_read_file_lines, tool_write_file,
                              tool_patch_file, tool_list_dir, tool_find_files,
                              tool_run_shell, _session_cwd, FILE_SCHEMAS)
from tools.web_ops   import tool_web_search, tool_fetch_url, tool_git_op, WEB_SCHEMAS
from tools.sandbox   import tool_run_code, SANDBOX_SCHEMAS
from tools.pwn_chain import (tool_pwn_env, tool_inspect_binary, tool_pwn_rop,
                              tool_pwn_cyclic, tool_pwn_disasm, tool_pwn_libc,
                              tool_pwn_debug, tool_pwn_one_gadget, PWN_SCHEMAS)
from tools.vision    import analyze_local_image, VISION_SCHEMAS
from core.logger import logger

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
    "analyze_local_image": analyze_local_image,
}

TOOLS_SCHEMA: list = (
    FILE_SCHEMAS + WEB_SCHEMAS + SANDBOX_SCHEMAS
    + PWN_SCHEMAS + VISION_SCHEMAS
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
    "pwn_env",   # 环境探测，无副作用
    "list_dir",  # 目录列出，无副作用
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

def _trim_context(msgs: list) -> int:
    if _ctx_chars(msgs) <= DYNAMIC_CONFIG["ctx_max_chars"]:
        return 0
    dropped = 0; i = 1
    while _ctx_chars(msgs) > DYNAMIC_CONFIG["ctx_trim_to"] and i < len(msgs) - 1:
        if msgs[i].get("_pinned"):
            i += 1; continue
        msgs.pop(i); dropped += 1
    return dropped

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
        self._reset_system_prompt()
        self._save_lock = threading.Lock()
        # ── Usage & audit counters (cumulative across all turns) ──
        self.total_prompt_tokens     = 0
        self.total_completion_tokens = 0
        self.total_tool_calls        = 0
        # Per-turn snapshots, reset at start of each run_turn
        self._turn_prompt_tokens     = 0
        self._turn_completion_tokens = 0
        self._turn_tool_calls        = 0

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
        skills_toc   = _load_skills_toc()

        # ── ★ GSA 相关技能动态检索（衰减评分版）────────────
        _relevant_skills_md  = ""
        _conflict_warning    = ""
        if knowledge_query:
            try:
                _relevant_skills_md, _conflict_warning = load_relevant_skills(
                    knowledge_query, top_k=3
                )
            except Exception:
                pass   # 降级：无相关技能注入，不中断主流程

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

            "=== Memory & History Awareness ===\n"
            "You have a persistent conversation database. While you have no spontaneous memory,\n"
            "you CAN and SHOULD use /chat commands when the user asks about past sessions.\n"
            "NEVER claim you have no memory — you have History tools.\n\n"

            "=== Available Tools ===\n"
            "  File     : read_file · read_file_lines · write_file · patch_file · list_dir · find_files\n"
            "  Shell    : run_shell · git_op\n"
            "  Web      : web_search → fetch_url (Jina / Pandoc / regex fallback)\n"
            "  Sandbox  : run_code  (python / c / cpp / javascript / bash / rust / go / java)\n"
            "  Vision   : analyze_local_image  (jpg/png/gif/webp — glm-4v / gpt-4o)\n"
            "  CTF/Pwn  : pwn_env · inspect_binary · pwn_rop · pwn_cyclic · pwn_disasm\n"
            "             pwn_libc · pwn_debug · pwn_one_gadget\n"
            "  Advanced : delegate_task  (fresh context sub-agent)\n"
            "  History  : /chat list · /chat view · /chat find · /chat tag · /chat related\n\n"

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
            # ★ 修改 2：放宽工具调用说明，加入文本兜底容错指引
            # ════════════════════════════════════════════════
            "<CRITICAL_EXECUTION_CONTRACT>\n"
            "  ⚠ NO WAITING RULE: Output the <plan> block AND invoke the tool in the EXACT SAME\n"
            "  response. Do NOT output a plan then wait for user confirmation.\n\n"
            "  [TOOL INVOCATION: Trigger the native function calling API immediately after </plan>.\n"
            "  If native calling fails, you MAY fallback to outputting raw JSON wrapped EXACTLY in\n"
            "  <tool_call>{\"name\": \"...\", \"arguments\": {...}}</tool_call> tags.]\n"
            "</CRITICAL_EXECUTION_CONTRACT>\n\n"

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
            "Pwn/CTF:\n"
            "  pwn_env → inspect_binary → pwn_cyclic gen → pwn_debug (find offset) "
            "→ pwn_rop (gadgets) → pwn_libc → write exploit (run_code, use_venv=true) → test\n"
            "  NX enabled path: skip shellcode → use pwn_rop + pwn_one_gadget instead.\n\n"
            "Research:\n"
            "  web_search → fetch_url (full page) → synthesize → write_file\n\n"
            "History:\n"
            "  /chat find <keywords>  →  /chat view <id>  →  answer user\n\n"
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

    # ── 主轮次 ────────────────────────────────────────────
    def run_turn(self, user_input: str):
        self._reset_system_prompt(knowledge_query=user_input)
        self.messages.append({"role": "user", "content": user_input})

        dropped = _trim_context(self.messages)
        if dropped:
            print(c(YELLOW, f"  ⚠ 上下文过长，已裁剪最旧 {dropped} 条"))
            logger.warning(
                "Context trimmed | session={} dropped={} model={}",
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

        for iteration in range(max_iter):
            text_buf = ""; tc_buf: dict = {}

            for delta in stream_request(
                self.messages, self.model_alias,
                tools_schema=current_tools,
                max_tokens=current_max_tokens,
            ):
                if "_error" in delta:
                    _err_detail = delta["_error"]
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

                for tcd in d.get("tool_calls", []):
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
            if leftover: sys.stdout.write(leftover); sys.stdout.flush()
            print()

            # --- Fallback Parser: 捕获文本中的 <tool_call> 幻觉 ---
            import re
            if not tc_buf and "<tool_call>" in text_buf:
                # 兼容模型忘记写 </tool_call> 的情况（非贪婪匹配到末尾）
                match = re.search(r"<tool_call>\s*(\{.*)", text_buf, re.DOTALL)
                if match:
                    json_str = match.group(1)
                    # 清理尾部可能的残缺标签或啰嗦废话
                    json_str = re.sub(r"</tool_call>.*$", "", json_str, flags=re.DOTALL).strip()
                    try:
                        # strict=False 是灵魂！它允许 JSON 字符串中存在真实的换行符（专治代码生成器）
                        parsed_tc = json.loads(json_str, strict=False)
                        if "name" in parsed_tc and "arguments" in parsed_tc:
                            args_str = json.dumps(parsed_tc["arguments"]) if isinstance(parsed_tc["arguments"],
                                                                                        dict) else str(
                                parsed_tc["arguments"])
                            tc_buf[0] = {
                                "id": f"call_fallback_{iteration}",
                                "name": parsed_tc["name"],
                                "args": args_str,
                            }
                            text_buf = text_buf[:match.start()]
                            print(c(GRAY, "  ⚙ [Fallback Parser] 成功拦截并解析异常工具调用 (终极容错模式)"))
                            # ★ 记录到文件，便于分析哪些模型频繁触发 Fallback
                            logger.info(
                                "Fallback Parser: intercepted tool call | "
                                "model={} session={} iteration={} tool_name={}",
                                self.model_alias, self.session_id[:8],
                                iteration, parsed_tc["name"],
                            )
                    except json.JSONDecodeError as e:
                        print(c(RED, f"  ✗ [Fallback Parser] 模型生成的 JSON 彻底损坏: {e}"))
                        # ★ 完整记录原始损坏 JSON，是排查模型输出格式问题的关键证据
                        logger.error(
                            "Fallback Parser: JSON completely corrupted | "
                            "model={} session={} iteration={} exc={!r}\n"
                            "--- RAW JSON (truncated to 4096 chars) ---\n{}\n"
                            "--- END RAW JSON ---",
                            self.model_alias, self.session_id[:8],
                            iteration, e, json_str[:4096],
                        )
            # --------------------------------------------------------

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
            need_plan   = not has_plan and not is_exempt

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
                tc = tc_buf[i]; name = tc["name"]
                fn_args = {}
                if tc["args"].strip():
                    try:    fn_args = json.loads(tc["args"])
                    except json.JSONDecodeError:
                        try:    fn_args = json.loads(tc["args"].strip().lstrip("\ufeff"))
                        except: fn_args = {"_raw_args": tc["args"]}

                preview  = ", ".join(f"{k}={repr(v)[:40]}" for k, v in fn_args.items())
                iter_tag = c(GRAY, f"[{iteration+1}/{max_iter}]")
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
                    result = TOOL_MAP[name](fn_args) if name in TOOL_MAP else f"ERROR: 未知工具 '{name}'"

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
