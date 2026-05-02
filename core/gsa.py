"""
core/gsa.py — Global Skills Archive (GSA) Engine
PawnLogic 1.1

职责：
  · 读取 / 初始化 global_skills.md
  · 提取现有分类（一级 # 标题）
  · 调用 LLM 自动分类并格式化技能块
  · 防重复检测（同名技能 → 追加 Case N）
  · 将技能块写入文件（基于 SEARCH/REPLACE）

对外接口：
  write_skill(model_alias, content, topic_hint="")
      → (ok: bool, message: str)

  load_toc()
      → 提取所有 # / ## 标题行，供 System Prompt 注入

  load_relevant_skills(query, top_k=3)
      → (skills_markdown: str, conflict_warning: str)
      使用 FinalScore（FSRS 幂律衰减 + 稳定性 + 底分保护）+ 冲突检测

  bump_skill(skill_name)
      → (ok: bool, message: str)
      闭环反馈——成功使用后调用，增加 hits，刷新 last_used

  prune_zombie_skills(min_hits, max_idle_days)
      → (pruned_count: int, pruned_names: list[str])
      垃圾回收——清理长期闲置的低频技能

被调用方：
  · session.py  → _reset_system_prompt 注入 TOC 及相关技能
  · session.py  → TOOL_MAP 中的 tool_bump_skill
  · main.py     → /memo 命令

─────────────────────────────────────────────────────────────
衰减算法说明
─────────────────────────────────────────────────────────────
  采用 FSRS（间隔重复算法）的个性化稳定性锚定衰减，解决全局指数衰减
  （牛顿冷却）导致的"用户长期离线后整个技能库同步崩溃"问题。

  · 每个技能的"个性化稳定性 S"由被验证次数（hits）和置信度决定：
        S = S_MIN × (1 + hits)^GROWTH × confidence × 2
        hits=0,  conf=0.70  →  S ≈  20 天
        hits=5,  conf=0.85  →  S ≈  62 天
        hits=15, conf=1.00  →  S ≈ 130 天
  · 衰减用幂律公式（比指数更"记忆友好"）：
        R(t, S) = (1 + t / (9×S))^(-0.5)
  · 底分保护（SCORE_FLOOR）：即使长期离线，相关技能仍可被召回，
    只是排名会被近期验证的技能压后。
  · 综合评分：FinalScore = max(
        (sim + Hits_Bonus) × R(t,S) × confidence,
        sim × SCORE_FLOOR
    )
─────────────────────────────────────────────────────────────
"""

import re, json, math
from pathlib import Path
from datetime import datetime
from config import GLOBAL_SKILLS_PATH, DEFAULT_MODEL

# ════════════════════════════════════════════════════════
# 文件初始化
# ════════════════════════════════════════════════════════

_STUB_TEMPLATE = """\
# 🗂️ PawnLogic Global Skills Archive

> 自动生成于 {ts}
> 由 PawnLogic GSA 系统维护，记录跨会话的可复用技术知识。
> 勿手动删除此文件头部的 `#` 行，分类结构依赖其存在。

"""

def _ensure_file() -> str:
    """确保 global_skills.md 存在，若为空则写入存根。返回当前文件内容。"""
    GLOBAL_SKILLS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not GLOBAL_SKILLS_PATH.exists() or GLOBAL_SKILLS_PATH.stat().st_size == 0:
        stub = _STUB_TEMPLATE.format(ts=datetime.now().strftime("%Y-%m-%d %H:%M"))
        GLOBAL_SKILLS_PATH.write_text(stub, encoding="utf-8")
        return stub
    return GLOBAL_SKILLS_PATH.read_text(encoding="utf-8")

# ════════════════════════════════════════════════════════
# TOC 提取（供 System Prompt 注入）
# ════════════════════════════════════════════════════════

def load_toc(max_lines: int = 60) -> str:
    """
    读取 global_skills.md 的前 max_lines 行，
    提取所有 # 和 ## 标题，返回紧凑的目录字符串。
    用于 System Prompt 注入，让 AI 知道现有分类。
    """
    try:
        content = _ensure_file()
    except Exception:
        return ""

    lines    = content.splitlines()[:max_lines]
    headings = [l for l in lines if re.match(r'^#{1,2}\s', l)]
    if not headings:
        return "(global_skills.md 暂无分类)"
    return "\n".join(headings)

def load_h1_categories() -> list[str]:
    """
    返回所有一级标题（# 开头）字符串列表，供分类决策使用。
    去掉 emoji 后的纯文本形式。
    """
    try:
        content = _ensure_file()
    except Exception:
        return []
    cats = []
    for line in content.splitlines():
        m = re.match(r'^#\s+(.+)', line)
        if m:
            # 去 emoji，保留纯文本
            text = re.sub(r'[^\w\s/+#\-.]', '', m.group(1)).strip()
            cats.append(text)
    return cats


# ════════════════════════════════════════════════════════
# ★ 新增：元数据系统
#
# 存储格式（插在 ## Skill Name 正下方，Markdown 不可见）：
#   <!-- meta: hits=3 last_used=2025-04-25 confidence=0.85 -->
#
# hits        : int   — 累计被 bump_skill 调用次数（成功使用次数）
# last_used   : str   — ISO 日期，最后一次被使用的日期
# confidence  : float — 初始 0.70，每次 bump +0.05，上限 1.0
# ════════════════════════════════════════════════════════

_META_RE  = re.compile(
    r'^<!-- meta: hits=(\d+) last_used=([\d-]+) confidence=([\d.]+) -->$',
    re.MULTILINE,
)
_META_FMT = "<!-- meta: hits={hits} last_used={last_used} confidence={confidence:.2f} -->"

# ── FSRS 稳定性锚定衰减参数（v2.1.1）──────────────────────────────────
# 个性化稳定性：S = S_MIN × (1 + hits)^GROWTH × confidence × 2
_S_MIN:         float = 14.0   # 新技能最短半衰期 14 天
_GROWTH:        float = 0.6    # 幂律增长指数（防止高 hits 过度拉伸）

# 幂律衰减：R(t, S) = (1 + t / (9×S))^POWER
# POWER = -0.5 是 FSRS 风格的标准参数
_FSRS_POWER:    float = -0.5

# 底分保护：即使技能极旧，FinalScore 最低为 sim × SCORE_FLOOR
# 防止用户长期离线后相关技能被彻底排除出检索
_SCORE_FLOOR:   float = 0.05

# Hits 加成的分母（hits=20 时达到最大加成 +0.5）
_HITS_SCALE: float = 20.0
_HITS_CAP:   float = 0.5


def _parse_meta(block: str) -> dict:
    """从技能块中解析 meta 注释。若不存在则返回默认值（向后兼容旧格式）。"""
    m = _META_RE.search(block)
    if not m:
        return {"hits": 0, "last_used": "1970-01-01", "confidence": 0.70}
    return {
        "hits":       int(m.group(1)),
        "last_used":  m.group(2),
        "confidence": float(m.group(3)),
    }


def _update_meta_in_block(block: str, meta: dict) -> str:
    """将 meta dict 序列化并替换（或插入）到技能块中。"""
    meta_line = _META_FMT.format(**meta)
    if _META_RE.search(block):
        return _META_RE.sub(meta_line, block)
    # 无 meta 行时，插入到 ## 标题正下方
    lines = block.splitlines()
    result = [lines[0], meta_line] + lines[1:]
    return "\n".join(result)


def _add_initial_meta(skill_block: str) -> str:
    """
    向新生成的技能块注入初始 meta 注释。
    应在 write_skill 最终写入之前调用。
    """
    if _META_RE.search(skill_block):
        return skill_block   # 已存在，跳过
    today    = datetime.now().strftime("%Y-%m-%d")
    meta_line = _META_FMT.format(hits=0, last_used=today, confidence=0.70)
    lines    = skill_block.splitlines()
    if lines and lines[0].startswith("## "):
        return "\n".join([lines[0], meta_line] + lines[1:])
    return skill_block


# ════════════════════════════════════════════════════════
# ★ v2.1.1：FSRS 稳定性锚定衰减 + FinalScore
#
# 解决 v2.1.0 的"长期离线全库崩溃"问题：
#   · 每个技能拥有由自身验证历史决定的个性化稳定性 S
#   · 精华技能（hits 高）半衰期远大于新写入技能
#   · 从未验证的僵尸技能快速自然沉底
#   · SCORE_FLOOR 保证用户回归时相关技能仍可被检索到
# ════════════════════════════════════════════════════════

def _stability(hits: int, confidence: float) -> float:
    """
    计算技能的"个性化稳定性 S"（单位：天）。

    S = S_MIN × (1 + hits)^GROWTH × (confidence × 2)

    示例（S_MIN=14, GROWTH=0.6）：
      hits=0,  confidence=0.70  →  S ≈ 14 × 1.00 × 1.40 ≈  20 天
      hits=5,  confidence=0.85  →  S ≈ 14 × 2.63 × 1.70 ≈  62 天
      hits=10, confidence=0.95  →  S ≈ 14 × 3.73 × 1.90 ≈  99 天
      hits=15, confidence=1.00  →  S ≈ 14 × 4.64 × 2.00 ≈ 130 天
      hits=20, confidence=1.00  →  S ≈ 14 × 5.28 × 2.00 ≈ 148 天

    高频验证的精华技能稳定性是新技能的 7x+，可以抵御用户数月不活跃。
    """
    conf_mult = max(0.0, confidence) * 2.0
    s = _S_MIN * ((1 + hits) ** _GROWTH) * conf_mult
    return max(s, 1.0)   # 最低 1 天，防止除零


def _retrieval_strength(days: int, S: float) -> float:
    """
    FSRS 风格幂律衰减：R(t, S) = (1 + t / (9×S))^POWER

    与指数衰减对比（S=20 天为例）：
      t=7   天：指数(λ=0.02)→0.87  幂律→0.97  （新技能第一周几乎无损）
      t=30  天：指数→0.55        幂律→0.83  （一个月后仍有 83%）
      t=90  天：指数→0.16        幂律→0.63  （三个月后仍有 63%）

    对于 S=112 天（hits=15 的精华技能）：
      t=90  天：幂律→0.91        （三个月后 91% 的检索强度）
      t=180 天：幂律→0.82        （半年后 82% 的检索强度）
    """
    return (1.0 + days / (9.0 * S)) ** _FSRS_POWER


def _decay_days(last_used_str: str) -> int:
    """从 last_used 字符串计算距今天数。解析失败视为极旧（365 天）。"""
    try:
        last = datetime.strptime(last_used_str, "%Y-%m-%d")
        return max(0, (datetime.now() - last).days)
    except ValueError:
        return 365


def _final_score(similarity: float, meta: dict) -> float:
    """
    FinalScore = max(
        (sim + Hits_Bonus) × R(t, S) × confidence,
        sim × SCORE_FLOOR          ← 底分保护
    )

    底分保护确保：即使用户离线数月导致 R(t,S) 很低，
    只要技能与当前 query 语义相关（sim > 0），它仍能以 sim×5% 的保底分
    出现在检索结果中，避免"一朝离线，经验清零"。

    对比矩阵（sim=0.8）：
      新技能，今天写入（hits=0, S≈20, t=0）   → 0.8×1.0×0.70 = 0.56
      活跃，hits=10, 7天前，conf=0.95          → 1.2×0.96×0.95 ≈ 1.10
      精华，hits=20, 用户离线6月，conf=1.0      → 1.3×0.82×1.0 ≈ 1.07  （≫底分）
      僵尸，hits=0, 离线6月，conf=0.70          → max(0.056, 0.04) = 0.056
    """
    hits       = meta.get("hits", 0)
    confidence = meta.get("confidence", 0.70)
    days       = _decay_days(meta.get("last_used", "1970-01-01"))

    S           = _stability(hits, confidence)
    R           = _retrieval_strength(days, S)
    hits_bonus  = min(hits / _HITS_SCALE, _HITS_CAP)

    raw_score   = (similarity + hits_bonus) * R * confidence
    floor_score = similarity * _SCORE_FLOOR
    return max(raw_score, floor_score)


# ════════════════════════════════════════════════════════
# 轻量级相似度（Jaccard，基于词 token 集合）
# ════════════════════════════════════════════════════════

def _jaccard_sim(str1: str, str2: str) -> float:
    """
    基于小写词 token 集合的 Jaccard 相似度。
    返回 [0.0, 1.0]，完全相同返回 1.0。
    """
    def _tokens(s: str) -> set[str]:
        return set(re.findall(r'[a-z0-9_\-]+', s.lower()))
    a, b = _tokens(str1), _tokens(str2)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ════════════════════════════════════════════════════════
# ★ 新增：冲突检测
# ════════════════════════════════════════════════════════

_CASE_STRIP_RE = re.compile(r'\s+Case\s+\d+\s*$', re.IGNORECASE)


def _detect_conflicts(
    scored_blocks: list[tuple[float, str, str]]
) -> str:
    """
    检测 Top-K 中是否存在同一"Case 系列"的多个变体。

    scored_blocks: [(final_score, title, block_text), ...]

    冲突条件：
      · 2+ 个技能具有相同的去 Case 后缀基名
        （如 "FOO" 与 "FOO Case 2" 会被识别为同一集群）

    返回：
      · 如有冲突 → 格式化的 <conflict_warning> 字符串
      · 无冲突   → 空字符串
    """
    base_groups: dict[str, list[tuple[float, str]]] = {}
    for score, title, _ in scored_blocks:
        base = _CASE_STRIP_RE.sub("", title).strip()
        base_groups.setdefault(base, []).append((score, title))

    conflicts = {k: v for k, v in base_groups.items() if len(v) > 1}
    if not conflicts:
        return ""

    lines: list[str] = [
        "<conflict_warning>",
        "ATTENTION: Multiple skill variants found for the same domain.",
        "MANDATORY Meta-Reasoning required in your <plan> block before proceeding:\n",
    ]
    for base, variants in conflicts.items():
        lines.append(f"  Conflict cluster: '{base}'")
        for score, title in sorted(variants, key=lambda x: -x[0]):
            lines.append(f"    • [score={score:.3f}] ## {title}")
        lines.append(
            "  → EVALUATE each variant's applicability to THIS specific context.\n"
            "  → SELECT the best-matching one and STATE your choice in <plan><why>.\n"
            "  → REJECT the other(s) with a brief rationale.\n"
        )
    lines.append("</conflict_warning>")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════
# ★ 升级版：load_relevant_skills（衰减评分 + 冲突检测）
# ════════════════════════════════════════════════════════

def load_relevant_skills(
    query: str,
    top_k: int = 3,
) -> tuple[str, str]:
    """
    根据 query 从 global_skills.md 动态加载最相关的 Top-K 技能块。

    ★ v2.1.1 升级点（相比 v2.1.0）：
      · 衰减从全局指数（牛顿冷却）升级为个性化 FSRS 幂律衰减
      · 精华技能（hits 高）半衰期显著更长，长期离线不导致全库崩溃
      · 引入 SCORE_FLOOR 底分保护，相关技能即使旧了也不会消失
      · 过滤阈值从 score>0 收紧为 score >= SCORE_FLOOR（更干净的结果）

    返回：
      skills_markdown : str  — 拼接后的 Markdown，用于 System Prompt 注入
      conflict_warning: str  — 若检测到 Case 系列冲突则非空，否则为 ""
    """
    try:
        content = _ensure_file()
    except Exception:
        return "", ""

    if not content.strip():
        return "", ""

    # 按 "## " 拆分技能块（保留标题行）
    raw_blocks = re.split(r'(?=^## )', content, flags=re.MULTILINE)
    # (final_score, title, block_text)
    scored: list[tuple[float, str, str]] = []

    for block in raw_blocks:
        block = block.strip()
        if not block.startswith("## "):
            continue
        first_line = block.splitlines()[0]
        title      = re.sub(r'^##\s+', '', first_line).strip()
        # 去除 meta 注释行后再做 Jaccard（避免日期字符串干扰）
        clean_title = _CASE_STRIP_RE.sub("", title).strip()
        sim         = _jaccard_sim(query, clean_title)
        meta        = _parse_meta(block)
        score       = _final_score(sim, meta)
        scored.append((score, title, block))

    if not scored:
        return "", ""

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]

    # 过滤掉底分以下的完全不相关项，但至少保留 1 个
    # v2.1.1：改用 SCORE_FLOOR 而非 0，让僵尸技能真正被过滤
    threshold = _SCORE_FLOOR * 0.5   # 轻微放宽，避免误杀语义相关但旧的技能
    filtered = [(s, t, b) for s, t, b in top if s >= threshold]
    if not filtered:
        filtered = [top[0]]

    # 冲突检测
    conflict_warning = _detect_conflicts(filtered)

    skills_md = "\n\n".join(b for _, _, b in filtered)
    return skills_md, conflict_warning


# ════════════════════════════════════════════════════════
# ★ 新增：闭环反馈工具 bump_skill
# ════════════════════════════════════════════════════════

def bump_skill(skill_name: str) -> tuple[bool, str]:
    """
    当主 Agent 成功利用某技能解决问题后调用。
    效果：
      · hits += 1
      · last_used = today
      · confidence = min(confidence + 0.05, 1.0)

    参数：
      skill_name — 技能的 ## 标题（精确匹配，不含 "## " 前缀）

    返回：
      (True, 更新摘要)  — 成功
      (False, 错误消息) — 技能名未找到或 IO 异常
    """
    try:
        content = GLOBAL_SKILLS_PATH.read_text(encoding="utf-8")
    except Exception as e:
        return False, f"读取 global_skills.md 失败: {e}"

    # 宽松匹配：允许开头的 ## 及末尾空格，不区分大小写
    pattern = re.compile(
        r'^## ' + re.escape(skill_name.strip()) + r'\s*$',
        re.MULTILINE | re.IGNORECASE,
    )
    match = pattern.search(content)
    if not match:
        # 二次尝试：去掉 Case N 后缀后模糊匹配
        base  = _CASE_STRIP_RE.sub("", skill_name.strip())
        alt   = re.compile(
            r'^## ' + re.escape(base) + r'(\s+Case\s+\d+)?\s*$',
            re.MULTILINE | re.IGNORECASE,
        )
        match = alt.search(content)
        if not match:
            return False, f"技能 '{skill_name}' 未在 global_skills.md 中找到"

    # 定位技能块边界
    block_start = match.start()
    rest        = content[match.end():]
    next_block  = re.search(r'^## ', rest, re.MULTILINE)
    block_end   = match.end() + next_block.start() if next_block else len(content)
    old_block   = content[block_start:block_end]

    # 更新 meta
    meta               = _parse_meta(old_block)
    meta["hits"]      += 1
    meta["last_used"]  = datetime.now().strftime("%Y-%m-%d")
    meta["confidence"] = min(meta["confidence"] + 0.05, 1.0)

    new_block   = _update_meta_in_block(old_block, meta)
    new_content = content[:block_start] + new_block + content[block_end:]

    try:
        GLOBAL_SKILLS_PATH.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return False, f"写入失败: {e}"

    actual_title = match.group(0).lstrip("#").strip()
    return True, (
        f"✓ bump_skill OK: '{actual_title}'\n"
        f"  hits={meta['hits']}  last_used={meta['last_used']}  "
        f"confidence={meta['confidence']:.2f}"
    )


# ════════════════════════════════════════════════════════
# ★ 新增：垃圾回收 prune_zombie_skills
# ════════════════════════════════════════════════════════

def prune_zombie_skills(
    min_hits:      int = 1,
    max_idle_days: int = 90,
) -> tuple[int, list[str]]:
    """
    物理删除"僵尸技能"：hits < min_hits 且 闲置 > max_idle_days 的技能块。

    默认阈值：
      · hits < 1（从未被验证使用）
      · 闲置 > 90 天（三个月未被召回）

    返回：
      (pruned_count, pruned_names_list)

    注意：此操作不可逆。建议在调用前备份或使用 git 跟踪 global_skills.md。
    """
    try:
        content = _ensure_file()
    except Exception as e:
        return 0, []

    # 按 ## 拆分，保留文件头部（非技能块内容）
    raw_blocks = re.split(r'(?=^## )', content, flags=re.MULTILINE)
    kept:   list[str] = []
    pruned: list[str] = []

    for block in raw_blocks:
        # 文件头（# 一级标题 / 说明文字 / 空行）直接保留
        if not block.strip().startswith("## "):
            kept.append(block)
            continue

        first_line = block.splitlines()[0]
        title      = re.sub(r'^##\s+', '', first_line).strip()
        meta       = _parse_meta(block)

        # 计算闲置天数
        try:
            last      = datetime.strptime(meta["last_used"], "%Y-%m-%d")
            idle_days = max(0, (datetime.now() - last).days)
        except ValueError:
            idle_days = 9999   # 无法解析 → 视为极旧

        if meta["hits"] < min_hits and idle_days > max_idle_days:
            pruned.append(title)
        else:
            kept.append(block)

    if pruned:
        try:
            GLOBAL_SKILLS_PATH.write_text("".join(kept), encoding="utf-8")
        except Exception:
            return 0, []   # IO 失败，保守返回

    return len(pruned), pruned


# ════════════════════════════════════════════════════════
# P0: Failure Pattern 自动沉淀（Anti-Pattern DB）
#
# 当同一工具 + 同一错误类型出现 ≥ SINK_THRESHOLD 次时，
# 自动将失败模式写入 global_skills.md 的 # ❌ Failure Patterns 分区。
# 格式：## <工具名> — <错误类型>，含触发条件 + 正确做法。
# ════════════════════════════════════════════════════════

_SINK_THRESHOLD = 3   # 同类失败 ≥ 3 次触发沉淀


def _ensure_failure_section(content: str) -> str:
    """确保 global_skills.md 中存在 # ❌ Failure Patterns 分区。"""
    if "❌ Failure Patterns" in content:
        return content
    # 追加到文件末尾
    section = (
        "\n\n# ❌ Failure Patterns\n\n"
        "> 自动生成的失败防雷区。当同一工具 + 同一错误类型出现 ≥ 3 次时自动记录。\n"
        "> 请勿手动删除，Agent 会在调用危险工具前自动比对此分区。\n\n"
    )
    return content + section


def sink_failure_to_gsa(
    tool_name: str,
    error_type: str,
    error_msg: str,
    args_preview: str,
) -> tuple[bool, str]:
    """
    将失败模式沉淀到 global_skills.md 的 Failure Patterns 分区。
    仅当同类失败 ≥ SINK_THRESHOLD 次时调用。

    Returns
    -------
    (True, 成功消息) 或 (False, 原因)
    """
    try:
        content = _ensure_file()
    except Exception as e:
        return False, f"读取 global_skills.md 失败: {e}"

    # 检查是否已存在该失败模式
    skill_name = f"{tool_name} — {error_type}"
    pattern = re.compile(
        r'^##\s+' + re.escape(skill_name) + r'\s*$',
        re.MULTILINE | re.IGNORECASE,
    )
    if pattern.search(content):
        return False, f"失败模式 '{skill_name}' 已存在，跳过重复写入"

    # 构建技能块
    today = datetime.now().strftime("%Y-%m-%d")
    skill_block = (
        f"## {skill_name}\n"
        f"<!-- meta: hits=0 last_used={today} confidence=0.70 -->\n\n"
        f"**What**: 工具 `{tool_name}` 在以下条件下反复失败：\n"
        f"  - 错误类型: `{error_type}`\n"
        f"  - 典型参数: `{args_preview[:120]}`\n\n"
        f"**Error**:\n```\n{error_msg[:300]}\n```\n\n"
        f"**Rule**: 调用 `{tool_name}` 前必须检查参数是否匹配上述失败条件。"
        f"若匹配，应改用其他方案或修正参数后再试。\n"
    )

    # 确保 Failure Patterns 分区存在
    content = _ensure_failure_section(content)

    # 插入到 Failure Patterns 分区末尾
    try:
        from tools.file_ops import _apply_patch_blocks
        # 找到 Failure Patterns 分区的最后一个 ## 行作为锚点
        lines = content.splitlines(keepends=True)
        anchor_idx = None
        in_section = False
        for i, line in enumerate(lines):
            if "❌ Failure Patterns" in line:
                in_section = True
                continue
            if in_section and line.startswith("# ") and "❌" not in line:
                # 到达下一个一级标题，锚点为前一行
                anchor_idx = i - 1
                break
            if in_section and line.startswith("## "):
                anchor_idx = i
        if anchor_idx is None:
            # 分区是最后一个，追加到末尾
            content += f"\n{skill_block}\n"
            GLOBAL_SKILLS_PATH.write_text(content, encoding="utf-8")
            return True, f"✓ 失败模式已沉淀: ## {skill_name}"

        anchor_line = lines[anchor_idx].rstrip("\n")
        patch = (
            f"<<<<<<< SEARCH\n{anchor_line}\n=======\n"
            f"{anchor_line}\n\n{skill_block}\n>>>>>>> REPLACE"
        )
        result_msg = _apply_patch_blocks(str(GLOBAL_SKILLS_PATH), patch)
        if result_msg.startswith("OK"):
            return True, f"✓ 失败模式已沉淀: ## {skill_name}"
        # patch 失败 → 降级追加
        with open(GLOBAL_SKILLS_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n{skill_block}\n")
        return True, f"⚠ 降级追加: ## {skill_name}"
    except Exception as e:
        return False, f"写入失败: {e}"


# ════════════════════════════════════════════════════════
# 重复检测
# ════════════════════════════════════════════════════════

def _find_duplicate(content: str, skill_name: str) -> int:
    """
    在文件中查找 ## skill_name（或其变体 ## skill_name Case N）。
    返回已存在的相同前缀的最大 Case 编号（0 = 不存在，1 = 有一个原始版本，2 = 有 Case 2...）。
    """
    base = re.escape(skill_name.strip())
    # 匹配 ## skill_name 或 ## skill_name Case N
    pattern = re.compile(
        r'^##\s+' + base + r'(\s+Case\s+(\d+))?\s*$',
        re.IGNORECASE | re.MULTILINE
    )
    matches = pattern.findall(content)
    if not matches:
        return 0
    nums = [int(m[1]) if m[1] else 1 for m in matches]
    return max(nums)

# ════════════════════════════════════════════════════════
# LLM 分类 + 格式化（核心）
# ════════════════════════════════════════════════════════

_CLASSIFY_SYSTEM = (
    "You are a senior software engineer and security researcher. "
    "Your job is to classify a technical knowledge snippet and format it as a reusable Markdown skill block. "
    "Respond ONLY with valid JSON. No markdown fences, no explanation."
)

_CLASSIFY_PROMPT_TMPL = """\
Existing categories in global_skills.md (# headings):
{categories}

User content to archive:
{content}

Topic hint (may be empty): {topic_hint}

Instructions:
1. Choose the best matching existing category for this content.
   - If no category matches semantically, invent a NEW one.
   - New category format: "EMOJI Title/Subtitle" (e.g. "🛡️ Pwn/Stack", "🐍 Python/Async", "📐 Algorithms/DP")
   - Use a specific, descriptive emoji that reflects the domain.
2. Produce a concise skill name (≤ 6 words).
3. Write a high-quality Markdown skill block (## heading + content).
   - Include: core concept, key commands/code snippet, when to apply.
   - Be terse but technically precise. No filler sentences.
   - Code blocks use appropriate language fences (```python, ```c, ```bash, etc.)
4. Output ONLY this JSON:
{{
  "category": "EMOJI Category Name",     // full # heading text (with emoji)
  "is_new_category": true/false,
  "skill_name": "Short Skill Name",
  "skill_block": "## Short Skill Name\\n\\n...full markdown content..."
}}
"""

def _call_llm_classify(model_alias: str, content: str, topic_hint: str,
                        existing_cats: list[str]) -> dict | None:
    """调用 LLM 进行分类和格式化。返回解析后的 dict，或 None（失败时）。"""
    try:
        from core.api_client import call_once
    except ImportError:
        return None

    categories_str = "\n".join(f"  - {c}" for c in existing_cats) if existing_cats else "  (none yet)"
    prompt = _CLASSIFY_PROMPT_TMPL.format(
        categories  = categories_str,
        content     = content[:2000],   # 防止 payload 过大
        topic_hint  = topic_hint or "(none)",
    )

    text, err = call_once(
        messages    = [
            {"role": "system", "content": _CLASSIFY_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        model_alias = model_alias,
        max_tokens  = 800,
    )
    if err or not text:
        return None

    # 清理可能残留的 markdown fence
    cleaned = text.strip()
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
    cleaned = re.sub(r'\s*```$', '',        cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # 尝试从文本中提取 JSON 对象
        m = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if m:
            try:    return json.loads(m.group(0))
            except: pass
    return None

# ════════════════════════════════════════════════════════
# SEARCH/REPLACE 写入
# ════════════════════════════════════════════════════════

def _build_patch(content: str, category_heading: str,
                 skill_block: str, is_new_category: bool) -> str | None:
    """
    构建一个 SEARCH/REPLACE patch_blocks 字符串。

    策略：
      · 若 is_new_category：在文件末尾追加新的 # 标题 + 技能块
      · 若 existing category：在该 # 标题的最后一个 ## 之后（或标题行本身之后）插入

    返回 patch_blocks 字符串，或 None（无法定位时）。
    """
    lines = content.splitlines(keepends=True)

    if is_new_category:
        # 追加到文件末尾：SEARCH 文件最后一行，REPLACE 原内容 + 新分类 + 技能块
        if not lines:
            # 文件为空，直接写
            return None  # 调用方检测到 None 时直接 write_text
        last_line = lines[-1].rstrip("\n")
        new_section = f"\n# {category_heading}\n\n{skill_block}\n"
        return (
            f"<<<<<<< SEARCH\n{last_line}\n=======\n{last_line}{new_section}>>>>>>> REPLACE"
        )
    else:
        # 在现有分类下插入
        # 找到目标 # 标题的行号
        target_h1 = None
        for i, line in enumerate(lines):
            if re.match(r'^#\s+', line) and category_heading.lower() in line.lower():
                target_h1 = i
                break
        if target_h1 is None:
            return None

        # 找到这个 # 标题块的末尾：下一个 # 标题之前的最后一行
        block_end = len(lines) - 1
        for j in range(target_h1 + 1, len(lines)):
            if re.match(r'^#\s+', lines[j]):
                block_end = j - 1
                break

        # SEARCH: 最后一个非空行（锚点）
        anchor_idx = block_end
        while anchor_idx > target_h1 and not lines[anchor_idx].strip():
            anchor_idx -= 1

        anchor_line = lines[anchor_idx].rstrip("\n")

        new_content = f"{anchor_line}\n\n{skill_block}\n"
        return (
            f"<<<<<<< SEARCH\n{anchor_line}\n=======\n{new_content}>>>>>>> REPLACE"
        )

# ════════════════════════════════════════════════════════
# 主入口
# ════════════════════════════════════════════════════════

def write_skill(
    model_alias: str,
    content: str,
    topic_hint: str = "",
) -> tuple[bool, str]:
    """
    完整 GSA 写入流程。

    参数：
      model_alias — 用于分类的 LLM 模型别名（通常与主 session 相同）
      content     — 要存档的技术内容（自然语言描述或代码片段）
      topic_hint  — 可选的分类提示（如 "pwn rop chain"）

    返回：
      (True, 摘要消息)  — 成功
      (False, 错误消息) — 失败
    """
    # ── Step 1：确保文件存在 ─────────────────────────────
    try:
        file_content = _ensure_file()
    except Exception as e:
        return False, f"无法初始化 global_skills.md: {e}"

    existing_cats = load_h1_categories()

    # ── Step 2：LLM 分类 + 格式化 ──────────────────────
    result = _call_llm_classify(model_alias, content, topic_hint, existing_cats)
    if not result:
        return False, "LLM 分类调用失败（网络错误或模型返回格式异常）"

    category    = result.get("category", "").strip()
    is_new      = bool(result.get("is_new_category", False))
    skill_name  = result.get("skill_name", "Unnamed Skill").strip()
    skill_block = result.get("skill_block", "").strip()

    if not category or not skill_block:
        return False, f"LLM 返回格式不完整: {result}"

    # ── Step 3：防重复检测 ───────────────────────────────
    dup_level = _find_duplicate(file_content, skill_name)
    if dup_level > 0:
        # 已存在完全同名版本，追加 Case N
        next_case  = dup_level + 1
        skill_name = f"{skill_name} Case {next_case}"
        skill_block = re.sub(
            r'^##\s+.+',
            f"## {skill_name}",
            skill_block,
            count=1,
            flags=re.MULTILINE,
        )
    else:
        # ── 语义相似度检查：对同分类下现有技能做 Jaccard 比对 ──
        existing_skill_names: list[str] = []
        for line in file_content.splitlines():
            m = re.match(r'^##\s+(.+)', line)
            if m:
                existing_skill_names.append(m.group(1).strip())

        best_sim   = 0.0
        best_match = ""
        for existing in existing_skill_names:
            sim = _jaccard_sim(skill_name, existing)
            if sim > best_sim:
                best_sim   = sim
                best_match = existing

        if best_sim > 0.8:
            # TODO: LLM semantic merge — 当前策略：高相似度自动追加 Case 2
            next_case  = _find_duplicate(file_content, best_match) + 1
            if next_case < 2:
                next_case = 2
            skill_name  = f"{skill_name} Case {next_case}"
            skill_block = re.sub(
                r'^##\s+.+',
                f"## {skill_name}",
                skill_block,
                count=1,
                flags=re.MULTILINE,
            )

    # ── Step 3.5：★ 注入初始元数据 ──────────────────────
    skill_block = _add_initial_meta(skill_block)

    # ── Step 4：构建 SEARCH/REPLACE patch ────────────────
    file_content = GLOBAL_SKILLS_PATH.read_text(encoding="utf-8")   # 重新读取最新内容
    patch_blocks = _build_patch(file_content, category, skill_block, is_new)

    if patch_blocks is None:
        # 极端情况：文件为空或无法定位锚点，直接追加
        try:
            new_section = f"\n# {category}\n\n{skill_block}\n"
            with open(GLOBAL_SKILLS_PATH, "a", encoding="utf-8") as f:
                f.write(new_section)
            return True, f"✓ 已追加新分类 '# {category}' → '{skill_name}'"
        except Exception as e:
            return False, f"写入失败: {e}"

    # ── Step 5：应用 patch ───────────────────────────────
    try:
        from tools.file_ops import _apply_patch_blocks
        result_msg = _apply_patch_blocks(str(GLOBAL_SKILLS_PATH), patch_blocks)
        if result_msg.startswith("OK"):
            dup_note = f" (去重 → Case {dup_level+1})" if dup_level > 0 else ""
            return True, (
                f"✓ 技能已写入 global_skills.md\n"
                f"  分类: # {category}  {'← 新建' if is_new else ''}\n"
                f"  技能: ## {skill_name}{dup_note}\n"
                f"  路径: {GLOBAL_SKILLS_PATH}"
            )
        else:
            # patch 失败 → 降级为追加（保证不丢数据）
            new_section = f"\n# {category}\n\n{skill_block}\n" if is_new else f"\n{skill_block}\n"
            with open(GLOBAL_SKILLS_PATH, "a", encoding="utf-8") as f:
                f.write(new_section)
            return True, (
                f"⚠ SEARCH/REPLACE 失败（{result_msg[:60]}），已降级为追加写入。\n"
                f"  技能: ## {skill_name}  →  {GLOBAL_SKILLS_PATH}"
            )
    except Exception as e:
        return False, f"应用 patch 时异常: {e}"
