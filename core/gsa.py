"""
core/gsa.py — Global Skills Archive (GSA) Engine
PawnLogic

Responsibilities:
  · Read and initialize global_skills.md.
  · Extract existing categories (# headings).
  · Use an LLM to classify and format reusable skill blocks.
  · Detect duplicates (same skill name -> append Case N).
  · Write skill blocks through SEARCH/REPLACE patches.

Public API:
  write_skill(model_alias, content, topic_hint="")
      → (ok: bool, message: str)

  load_toc()
      → Extract all # / ## headings for System Prompt injection.

  load_relevant_skills(query, top_k=3)
      → (skills_markdown: str, conflict_warning: str)
      Uses FinalScore (FSRS power-law decay + stability + score floor)
      plus conflict detection.

  bump_skill(skill_name)
      → (ok: bool, message: str)
      Closed-loop feedback after successful use: increases hits and refreshes last_used.

  prune_zombie_skills(min_hits, max_idle_days)
      → (pruned_count: int, pruned_names: list[str])
      Garbage collection for long-idle, low-frequency skills.

Callers:
  · session.py  → _reset_system_prompt injects TOC and relevant skills.
  · session.py  → tool_bump_skill in TOOL_MAP.
  · main.py     → /memo command.

─────────────────────────────────────────────────────────────
Decay Algorithm Notes
─────────────────────────────────────────────────────────────
  Uses FSRS-style personalized stability anchoring to avoid the
  whole archive collapsing after a long offline period, which can happen
  with global exponential decay.

  · Each skill's personalized stability S is derived from hits and confidence:
        S = S_MIN × (1 + hits)^GROWTH × confidence × 2
        hits=0,  conf=0.70  →  S ≈  20 days
        hits=5,  conf=0.85  →  S ≈  62 days
        hits=15, conf=1.00  →  S ≈ 130 days
  · Decay uses a power-law formula, which is more memory-friendly than exponentials:
        R(t, S) = (1 + t / (9×S))^(-0.5)
  · Score floor: related skills remain retrievable after long idle periods,
    though recently verified skills rank above them.
  · Composite score: FinalScore = max(
        (sim + Hits_Bonus) × R(t,S) × confidence,
        sim × SCORE_FLOOR
    )
─────────────────────────────────────────────────────────────
"""

import re, json
from datetime import datetime
from config import GLOBAL_SKILLS_PATH

# ════════════════════════════════════════════════════════
# File initialization.
# ════════════════════════════════════════════════════════

_STUB_TEMPLATE = """\
# 🗂️ PawnLogic Global Skills Archive

> Automatically generated at {ts}.
> Maintained by the PawnLogic GSA system for reusable cross-session technical knowledge.
> Do not manually remove the `#` heading lines at the top; category structure depends on them.

"""

def _ensure_file() -> str:
    """Ensure global_skills.md exists; write a stub when empty and return content."""
    GLOBAL_SKILLS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not GLOBAL_SKILLS_PATH.exists() or GLOBAL_SKILLS_PATH.stat().st_size == 0:
        stub = _STUB_TEMPLATE.format(ts=datetime.now().strftime("%Y-%m-%d %H:%M"))
        GLOBAL_SKILLS_PATH.write_text(stub, encoding="utf-8")
        return stub
    return GLOBAL_SKILLS_PATH.read_text(encoding="utf-8")

# ════════════════════════════════════════════════════════
# TOC extraction for System Prompt injection.
# ════════════════════════════════════════════════════════

def load_toc(max_lines: int = 60) -> str:
    """
    Read the first max_lines from global_skills.md, extract # and ## headings,
    and return a compact directory string for System Prompt injection.
    """
    try:
        content = _ensure_file()
    except Exception:
        return ""

    lines    = content.splitlines()[:max_lines]
    headings = [l for l in lines if re.match(r'^#{1,2}\s', l)]
    if not headings:
        return "(global_skills.md has no categories yet)"
    return "\n".join(headings)

def load_h1_categories() -> list[str]:
    """
    Return all level-1 headings for classification decisions.
    Emoji are stripped so callers receive plain text.
    """
    try:
        content = _ensure_file()
    except Exception:
        return []
    cats = []
    for line in content.splitlines():
        m = re.match(r'^#\s+(.+)', line)
        if m:
            # Strip emoji and keep plain text.
            text = re.sub(r'[^\w\s/+#\-.]', '', m.group(1)).strip()
            cats.append(text)
    return cats


# ════════════════════════════════════════════════════════
# Metadata system.
#
# Storage format, inserted directly under ## Skill Name and invisible in Markdown:
#   <!-- meta: hits=3 last_used=2025-04-25 confidence=0.85 -->
#
# hits        : int   — total successful bump_skill calls
# last_used   : str   — ISO date of the latest successful use
# confidence  : float — starts at 0.70; each bump adds 0.05 up to 1.0
# ════════════════════════════════════════════════════════

_META_RE  = re.compile(
    r'^<!-- meta: hits=(\d+) last_used=([\d-]+) confidence=([\d.]+) -->$',
    re.MULTILINE,
)
_META_FMT = "<!-- meta: hits={hits} last_used={last_used} confidence={confidence:.2f} -->"

# FSRS stability-anchored decay parameters.
# Personalized stability: S = S_MIN × (1 + hits)^GROWTH × confidence × 2
_S_MIN:         float = 14.0   # Minimum half-life for new skills: 14 days.
_GROWTH:        float = 0.6    # Power-law growth exponent; avoids over-stretching high hits.

# Power-law decay: R(t, S) = (1 + t / (9×S))^POWER
# POWER = -0.5 is the FSRS-style standard parameter.
_FSRS_POWER:    float = -0.5

# Score floor: even very old skills keep FinalScore >= sim × SCORE_FLOOR.
# This prevents relevant skills from disappearing after long offline periods.
_SCORE_FLOOR:   float = 0.05

# Denominator for the hits bonus; hits=20 reaches the max bonus +0.5.
_HITS_SCALE: float = 20.0
_HITS_CAP:   float = 0.5


def _parse_meta(block: str) -> dict:
    """Parse a meta comment from a skill block, with old-format defaults."""
    m = _META_RE.search(block)
    if not m:
        return {"hits": 0, "last_used": "1970-01-01", "confidence": 0.70}
    return {
        "hits":       int(m.group(1)),
        "last_used":  m.group(2),
        "confidence": float(m.group(3)),
    }


def _update_meta_in_block(block: str, meta: dict) -> str:
    """Serialize and replace or insert a meta dict in a skill block."""
    meta_line = _META_FMT.format(**meta)
    if _META_RE.search(block):
        return _META_RE.sub(meta_line, block)
    # Insert directly under the ## heading when no meta line exists.
    lines = block.splitlines()
    result = [lines[0], meta_line] + lines[1:]
    return "\n".join(result)


def _add_initial_meta(skill_block: str) -> str:
    """
    Inject an initial meta comment into a new skill block.
    Call before write_skill persists the final block.
    """
    if _META_RE.search(skill_block):
        return skill_block   # Already present.
    today    = datetime.now().strftime("%Y-%m-%d")
    meta_line = _META_FMT.format(hits=0, last_used=today, confidence=0.70)
    lines    = skill_block.splitlines()
    if lines and lines[0].startswith("## "):
        return "\n".join([lines[0], meta_line] + lines[1:])
    return skill_block


# ════════════════════════════════════════════════════════
# FSRS stability-anchored decay + FinalScore.
#
# Fixes the earlier long-offline archive collapse problem:
#   · Each skill has personalized stability S derived from its validation history.
#   · High-hit skills keep a far longer half-life than newly written skills.
#   · Never-validated zombie skills naturally sink quickly.
#   · SCORE_FLOOR keeps relevant skills retrievable when the user returns.
# ════════════════════════════════════════════════════════

def _stability(hits: int, confidence: float) -> float:
    """
    Calculate a skill's personalized stability S, in days.

    S = S_MIN × (1 + hits)^GROWTH × (confidence × 2)

    Examples (S_MIN=14, GROWTH=0.6):
      hits=0,  confidence=0.70  →  S ≈ 14 × 1.00 × 1.40 ≈  20 days
      hits=5,  confidence=0.85  →  S ≈ 14 × 2.63 × 1.70 ≈  62 days
      hits=10, confidence=0.95  →  S ≈ 14 × 3.73 × 1.90 ≈  99 days
      hits=15, confidence=1.00  →  S ≈ 14 × 4.64 × 2.00 ≈ 130 days
      hits=20, confidence=1.00  →  S ≈ 14 × 5.28 × 2.00 ≈ 148 days

    Frequently validated skills can be 7x+ more stable than new skills.
    """
    conf_mult = max(0.0, confidence) * 2.0
    s = _S_MIN * ((1 + hits) ** _GROWTH) * conf_mult
    return max(s, 1.0)   # Minimum 1 day to avoid divide-by-zero.


def _retrieval_strength(days: int, S: float) -> float:
    """
    FSRS-style power-law decay: R(t, S) = (1 + t / (9×S))^POWER

    Compared with exponential decay (S=20 days):
      t=7   days: exponential(λ=0.02)->0.87  power-law->0.97
      t=30  days: exponential->0.55          power-law->0.83
      t=90  days: exponential->0.16          power-law->0.63

    For S=112 days (a high-hit skill):
      t=90  days: power-law->0.91
      t=180 days: power-law->0.82
    """
    return (1.0 + days / (9.0 * S)) ** _FSRS_POWER


def _decay_days(last_used_str: str) -> int:
    """Return days since last_used; parse failures count as very old (365 days)."""
    try:
        last = datetime.strptime(last_used_str, "%Y-%m-%d")
        return max(0, (datetime.now() - last).days)
    except ValueError:
        return 365


def _final_score(similarity: float, meta: dict) -> float:
    """
    FinalScore = max(
        (sim + Hits_Bonus) × R(t, S) × confidence,
        sim × SCORE_FLOOR
    )

    The score floor ensures that semantically relevant skills (sim > 0) remain
    retrievable even after months offline.

    Example matrix (sim=0.8):
      New skill today (hits=0, S≈20, t=0)       → 0.8×1.0×0.70 = 0.56
      Active, hits=10, 7 days old, conf=0.95    → 1.2×0.96×0.95 ≈ 1.10
      High-hit, idle 6 months, conf=1.0         → 1.3×0.82×1.0 ≈ 1.07
      Zombie, idle 6 months, conf=0.70          → max(0.056, 0.04) = 0.056
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
# Lightweight similarity: Jaccard over word-token sets.
# ════════════════════════════════════════════════════════

def _jaccard_sim(str1: str, str2: str) -> float:
    """
    Jaccard similarity over lowercase word-token sets.
    Returns [0.0, 1.0], where exact equality returns 1.0.
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
# Conflict detection.
# ════════════════════════════════════════════════════════

_CASE_STRIP_RE = re.compile(r'\s+Case\s+\d+\s*$', re.IGNORECASE)


def _detect_conflicts(
    scored_blocks: list[tuple[float, str, str]]
) -> str:
    """
    Detect whether Top-K contains multiple variants from the same Case series.

    scored_blocks: [(final_score, title, block_text), ...]

    Conflict condition:
      · 2+ skills share the same base name after stripping a Case suffix.

    Returns a formatted <conflict_warning> string when conflicts exist,
    otherwise an empty string.
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
# Upgraded load_relevant_skills with decay scoring and conflict detection.
# ════════════════════════════════════════════════════════

def load_relevant_skills(
    query: str,
    top_k: int = 3,
) -> tuple[str, str]:
    """
    Dynamically load the Top-K most relevant skill blocks from global_skills.md.

    Improvements:
      · Replaces global exponential decay with personalized FSRS power-law decay.
      · High-hit skills keep a much longer half-life.
      · SCORE_FLOOR keeps related old skills retrievable.
      · Filtering is stricter than score > 0 for cleaner results.

    Returns:
      skills_markdown : joined Markdown for System Prompt injection
      conflict_warning: non-empty when Case-series conflicts are detected
    """
    try:
        content = _ensure_file()
    except Exception:
        return "", ""

    if not content.strip():
        return "", ""

    # Split by "## " while preserving heading lines.
    raw_blocks = re.split(r'(?=^## )', content, flags=re.MULTILINE)
    # (final_score, title, block_text)
    scored: list[tuple[float, str, str]] = []

    for block in raw_blocks:
        block = block.strip()
        if not block.startswith("## "):
            continue
        first_line = block.splitlines()[0]
        title      = re.sub(r'^##\s+', '', first_line).strip()
        # Strip meta comments before Jaccard to avoid date-string noise.
        clean_title = _CASE_STRIP_RE.sub("", title).strip()
        sim         = _jaccard_sim(query, clean_title)
        meta        = _parse_meta(block)
        score       = _final_score(sim, meta)
        scored.append((score, title, block))

    if not scored:
        return "", ""

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]

    # Filter truly unrelated entries below the floor while keeping at least one.
    threshold = _SCORE_FLOOR * 0.5   # Slightly relaxed to avoid false negatives.
    filtered = [(s, t, b) for s, t, b in top if s >= threshold]
    if not filtered:
        filtered = [top[0]]

    # Conflict detection.
    conflict_warning = _detect_conflicts(filtered)

    skills_md = "\n\n".join(b for _, _, b in filtered)
    return skills_md, conflict_warning


# ════════════════════════════════════════════════════════
# Closed-loop feedback tool: bump_skill.
# ════════════════════════════════════════════════════════

def bump_skill(skill_name: str) -> tuple[bool, str]:
    """
    Call after the main agent successfully uses a skill to solve a problem.

    Effects:
      · hits += 1
      · last_used = today
      · confidence = min(confidence + 0.05, 1.0)

    Args:
      skill_name — exact ## heading without the "## " prefix

    Returns:
      (True, update summary) or (False, error message)
    """
    try:
        content = GLOBAL_SKILLS_PATH.read_text(encoding="utf-8")
    except Exception as e:
        return False, f"Failed to read global_skills.md: {e}"

    # Lenient match: allow ## prefix and trailing spaces, case-insensitive.
    pattern = re.compile(
        r'^## ' + re.escape(skill_name.strip()) + r'\s*$',
        re.MULTILINE | re.IGNORECASE,
    )
    match = pattern.search(content)
    if not match:
        # Second pass: strip Case N suffix and fuzzy-match the base.
        base  = _CASE_STRIP_RE.sub("", skill_name.strip())
        alt   = re.compile(
            r'^## ' + re.escape(base) + r'(\s+Case\s+\d+)?\s*$',
            re.MULTILINE | re.IGNORECASE,
        )
        match = alt.search(content)
        if not match:
            return False, f"Skill '{skill_name}' was not found in global_skills.md"

    # Locate the skill block boundaries.
    block_start = match.start()
    rest        = content[match.end():]
    next_block  = re.search(r'^## ', rest, re.MULTILINE)
    block_end   = match.end() + next_block.start() if next_block else len(content)
    old_block   = content[block_start:block_end]

    # Update meta.
    meta               = _parse_meta(old_block)
    meta["hits"]      += 1
    meta["last_used"]  = datetime.now().strftime("%Y-%m-%d")
    meta["confidence"] = min(meta["confidence"] + 0.05, 1.0)

    new_block   = _update_meta_in_block(old_block, meta)
    new_content = content[:block_start] + new_block + content[block_end:]

    try:
        GLOBAL_SKILLS_PATH.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return False, f"Write failed: {e}"

    actual_title = match.group(0).lstrip("#").strip()
    return True, (
        f"✓ bump_skill OK: '{actual_title}'\n"
        f"  hits={meta['hits']}  last_used={meta['last_used']}  "
        f"confidence={meta['confidence']:.2f}"
    )


# ════════════════════════════════════════════════════════
# Garbage collection: prune_zombie_skills.
# ════════════════════════════════════════════════════════

def prune_zombie_skills(
    min_hits:      int = 1,
    max_idle_days: int = 90,
) -> tuple[int, list[str]]:
    """
    Physically remove zombie skill blocks where hits < min_hits and idle > max_idle_days.

    Default thresholds:
      · hits < 1 (never validated)
      · idle > 90 days

    Returns:
      (pruned_count, pruned_names_list)

    This operation is irreversible. Back up or track global_skills.md in git first.
    """
    try:
        content = _ensure_file()
    except Exception:
        return 0, []

    # Split by ## while preserving the file header.
    raw_blocks = re.split(r'(?=^## )', content, flags=re.MULTILINE)
    kept:   list[str] = []
    pruned: list[str] = []

    for block in raw_blocks:
        # Preserve the file header, comments, and blank lines.
        if not block.strip().startswith("## "):
            kept.append(block)
            continue

        first_line = block.splitlines()[0]
        title      = re.sub(r'^##\s+', '', first_line).strip()
        meta       = _parse_meta(block)

        # Calculate idle days.
        try:
            last      = datetime.strptime(meta["last_used"], "%Y-%m-%d")
            idle_days = max(0, (datetime.now() - last).days)
        except ValueError:
            idle_days = 9999   # Parse failure counts as very old.

        if meta["hits"] < min_hits and idle_days > max_idle_days:
            pruned.append(title)
        else:
            kept.append(block)

    if pruned:
        try:
            GLOBAL_SKILLS_PATH.write_text("".join(kept), encoding="utf-8")
        except Exception:
            return 0, []   # IO failure: return conservatively.

    return len(pruned), pruned


# ════════════════════════════════════════════════════════
# P0: automatic failure pattern sinking (Anti-Pattern DB).
#
# When the same tool + error type appears at least SINK_THRESHOLD times,
# write the failure pattern into the # ❌ Failure Patterns section of global_skills.md.
# Format: ## <tool_name> — <error_type>, with trigger conditions and the right response.
# ════════════════════════════════════════════════════════

_SINK_THRESHOLD = 3   # Same-class failures >= 3 trigger sinking.


def _ensure_failure_section(content: str) -> str:
    """Ensure global_skills.md contains the # ❌ Failure Patterns section."""
    if "❌ Failure Patterns" in content:
        return content
    # Append to the file tail.
    section = (
        "\n\n# ❌ Failure Patterns\n\n"
        "> Automatically generated failure-pattern guardrail. When the same tool "
        "+ error type appears at least 3 times, it is recorded here.\n"
        "> Do not manually delete this section; the agent checks it before dangerous tool calls.\n\n"
    )
    return content + section


def sink_failure_to_gsa(
    tool_name: str,
    error_type: str,
    error_msg: str,
    args_preview: str,
) -> tuple[bool, str]:
    """
    Sink a failure pattern into the Failure Patterns section of global_skills.md.
    Call only when same-class failures reach SINK_THRESHOLD.

    Returns
    -------
    (True, success message) or (False, reason)
    """
    try:
        content = _ensure_file()
    except Exception as e:
        return False, f"Failed to read global_skills.md: {e}"

    # Check whether the pattern already exists.
    skill_name = f"{tool_name} — {error_type}"
    pattern = re.compile(
        r'^##\s+' + re.escape(skill_name) + r'\s*$',
        re.MULTILINE | re.IGNORECASE,
    )
    if pattern.search(content):
        return False, f"Failure pattern '{skill_name}' already exists; skipped duplicate write"

    # Build the skill block.
    today = datetime.now().strftime("%Y-%m-%d")
    skill_block = (
        f"## {skill_name}\n"
        f"<!-- meta: hits=0 last_used={today} confidence=0.70 -->\n\n"
        f"**What**: Tool `{tool_name}` repeatedly failed under these conditions:\n"
        f"  - Error type: `{error_type}`\n"
        f"  - Typical args: `{args_preview[:120]}`\n\n"
        f"**Error**:\n```\n{error_msg[:300]}\n```\n\n"
        f"**Rule**: Before calling `{tool_name}`, check whether the arguments match "
        f"the failure condition above. If they match, use another approach or fix "
        f"the arguments before retrying.\n"
    )

    # Ensure the Failure Patterns section exists.
    content = _ensure_failure_section(content)

    # Insert at the end of the Failure Patterns section.
    try:
        from tools.file_ops import _apply_patch_blocks
        # Use the last ## line in the Failure Patterns section as the anchor.
        lines = content.splitlines(keepends=True)
        anchor_idx = None
        in_section = False
        for i, line in enumerate(lines):
            if "❌ Failure Patterns" in line:
                in_section = True
                continue
            if in_section and line.startswith("# ") and "❌" not in line:
                # Reached the next top-level heading; anchor to the previous line.
                anchor_idx = i - 1
                break
            if in_section and line.startswith("## "):
                anchor_idx = i
        if anchor_idx is None:
            # The section is the last block; append to the tail.
            content += f"\n{skill_block}\n"
            GLOBAL_SKILLS_PATH.write_text(content, encoding="utf-8")
            return True, f"✓ Failure pattern recorded: ## {skill_name}"

        anchor_line = lines[anchor_idx].rstrip("\n")
        patch = (
            f"<<<<<<< SEARCH\n{anchor_line}\n=======\n"
            f"{anchor_line}\n\n{skill_block}\n>>>>>>> REPLACE"
        )
        result_msg = _apply_patch_blocks(str(GLOBAL_SKILLS_PATH), patch)
        if result_msg.startswith("OK"):
            return True, f"✓ Failure pattern recorded: ## {skill_name}"
        # Patch failed; degrade to append.
        with open(GLOBAL_SKILLS_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n{skill_block}\n")
        return True, f"⚠ Fallback append: ## {skill_name}"
    except Exception as e:
        return False, f"Write failed: {e}"


# ════════════════════════════════════════════════════════
# Duplicate detection.
# ════════════════════════════════════════════════════════

def _find_duplicate(content: str, skill_name: str) -> int:
    """
    Find ## skill_name or variants like ## skill_name Case N in the file.
    Returns the largest existing Case number: 0 = absent, 1 = original exists,
    2 = Case 2 exists, and so on.
    """
    base = re.escape(skill_name.strip())
    # Match ## skill_name or ## skill_name Case N.
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
# LLM classification and formatting.
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
    """Use the LLM for classification and formatting; return parsed dict or None."""
    try:
        from core.api_client import call_once
    except ImportError:
        return None

    categories_str = "\n".join(f"  - {c}" for c in existing_cats) if existing_cats else "  (none yet)"
    prompt = _CLASSIFY_PROMPT_TMPL.format(
        categories  = categories_str,
        content     = content[:2000],   # Avoid an oversized payload.
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

    # Strip possible leftover markdown fences.
    cleaned = text.strip()
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
    cleaned = re.sub(r'\s*```$', '',        cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to extract a JSON object from surrounding text.
        m = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if m:
            try:    return json.loads(m.group(0))
            except Exception: pass
    return None

# ════════════════════════════════════════════════════════
# SEARCH/REPLACE writing.
# ════════════════════════════════════════════════════════

def _build_patch(content: str, category_heading: str,
                 skill_block: str, is_new_category: bool) -> str | None:
    """
    Build a SEARCH/REPLACE patch_blocks string.

    Strategy:
      · If is_new_category: append a new # heading plus the skill block.
      · Existing category: insert after the last ## in that # section, or after the heading.

    Returns patch_blocks or None when no anchor can be located.
    """
    lines = content.splitlines(keepends=True)

    if is_new_category:
        # Append to file tail: SEARCH last line, REPLACE with original + new section.
        if not lines:
            # Empty file; caller will write directly when None is returned.
            return None
        last_line = lines[-1].rstrip("\n")
        new_section = f"\n# {category_heading}\n\n{skill_block}\n"
        return (
            f"<<<<<<< SEARCH\n{last_line}\n=======\n{last_line}{new_section}>>>>>>> REPLACE"
        )
    else:
        # Insert under an existing category.
        # Locate the target # heading line.
        target_h1 = None
        for i, line in enumerate(lines):
            if re.match(r'^#\s+', line) and category_heading.lower() in line.lower():
                target_h1 = i
                break
        if target_h1 is None:
            return None

        # Find this # heading block tail: last line before the next # heading.
        block_end = len(lines) - 1
        for j in range(target_h1 + 1, len(lines)):
            if re.match(r'^#\s+', lines[j]):
                block_end = j - 1
                break

        # SEARCH anchor: last non-empty line.
        anchor_idx = block_end
        while anchor_idx > target_h1 and not lines[anchor_idx].strip():
            anchor_idx -= 1

        anchor_line = lines[anchor_idx].rstrip("\n")

        new_content = f"{anchor_line}\n\n{skill_block}\n"
        return (
            f"<<<<<<< SEARCH\n{anchor_line}\n=======\n{new_content}>>>>>>> REPLACE"
        )

# ════════════════════════════════════════════════════════
# Main entry point.
# ════════════════════════════════════════════════════════

def write_skill(
    model_alias: str,
    content: str,
    topic_hint: str = "",
) -> tuple[bool, str]:
    """
    Complete GSA write flow.

    Args:
      model_alias — LLM model alias used for classification, usually current session model
      content     — technical content to archive
      topic_hint  — optional classification hint, e.g. "pwn rop chain"

    Returns:
      (True, summary message) or (False, error message)
    """
    # Step 1: ensure the file exists.
    try:
        file_content = _ensure_file()
    except Exception as e:
        return False, f"Failed to initialize global_skills.md: {e}"

    existing_cats = load_h1_categories()

    # Step 2: LLM classification and formatting.
    result = _call_llm_classify(model_alias, content, topic_hint, existing_cats)
    if not result:
        return False, "LLM classification failed (network error or malformed model response)"

    category    = result.get("category", "").strip()
    is_new      = bool(result.get("is_new_category", False))
    skill_name  = result.get("skill_name", "Unnamed Skill").strip()
    skill_block = result.get("skill_block", "").strip()

    if not category or not skill_block:
        return False, f"LLM returned an incomplete schema: {result}"

    # Step 3: duplicate detection.
    dup_level = _find_duplicate(file_content, skill_name)
    if dup_level > 0:
        # Exact name already exists; append Case N.
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
        # Semantic similarity check against existing skill names via Jaccard.
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
            # TODO: LLM semantic merge. Current policy: high similarity appends Case 2.
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

    # Step 3.5: inject initial metadata.
    skill_block = _add_initial_meta(skill_block)

    # Step 4: build SEARCH/REPLACE patch.
    file_content = GLOBAL_SKILLS_PATH.read_text(encoding="utf-8")   # Re-read latest content.
    patch_blocks = _build_patch(file_content, category, skill_block, is_new)

    if patch_blocks is None:
        # Extreme case: empty file or no anchor; append directly.
        try:
            new_section = f"\n# {category}\n\n{skill_block}\n"
            with open(GLOBAL_SKILLS_PATH, "a", encoding="utf-8") as f:
                f.write(new_section)
            return True, f"✓ Appended new category '# {category}' -> '{skill_name}'"
        except Exception as e:
            return False, f"Write failed: {e}"

    # Step 5: apply patch.
    try:
        from tools.file_ops import _apply_patch_blocks
        result_msg = _apply_patch_blocks(str(GLOBAL_SKILLS_PATH), patch_blocks)
        if result_msg.startswith("OK"):
            dup_note = f" (deduplicated -> Case {dup_level+1})" if dup_level > 0 else ""
            return True, (
                f"✓ Skill written to global_skills.md\n"
                f"  Category: # {category}  {'<- new' if is_new else ''}\n"
                f"  Skill: ## {skill_name}{dup_note}\n"
                f"  Path: {GLOBAL_SKILLS_PATH}"
            )
        else:
            # Patch failed; degrade to append so data is not lost.
            new_section = f"\n# {category}\n\n{skill_block}\n" if is_new else f"\n{skill_block}\n"
            with open(GLOBAL_SKILLS_PATH, "a", encoding="utf-8") as f:
                f.write(new_section)
            return True, (
                f"⚠ SEARCH/REPLACE failed ({result_msg[:60]}); fell back to append.\n"
                f"  Skill: ## {skill_name}  ->  {GLOBAL_SKILLS_PATH}"
            )
    except Exception as e:
        return False, f"Exception while applying patch: {e}"
