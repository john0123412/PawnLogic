"""Tests for the GSA hybrid retrieval scoring (BM25 + Jaccard + FSRS decay)."""

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

from core import gsa


# A Chinese prompt ("hello, who are you, look at the project source, explain it"),
# written as escapes: repository files outside *_zh-CN are English-only.
CJK_PROMPT = "\u4f60\u597d\uff0c\u4f60\u662f\u8c01\uff0c\u67e5\u770b\u5f53\u524d\u9879\u76ee\u7684\u6e90\u4ee3\u7801\uff0c\u7ed9\u6211\u89e3\u91ca"

RECENT = "2026-10-01"
OLD = "2020-01-01"

ARCHIVE = """\
# 🗂️ PawnLogic Global Skills Archive

## Stack Pivoting
<!-- meta: hits=5 last_used={recent} confidence=0.90 -->
Technique notes. Groom the allocator with a heap feng shui layout, then
overwrite the tcache pointer to complete the pivot.

## Format String Basics
<!-- meta: hits=2 last_used={recent} confidence=0.80 -->
printf %n writes to memory; positional specifiers leak stack values.

## Tomato Cultivation
<!-- meta: hits=0 last_used={old} confidence=0.70 -->
Water the tomatoes weekly and keep the soil warm.
"""


@pytest.fixture()
def archive_file(tmp_path, monkeypatch):
    path = tmp_path / "global_skills.md"
    path.write_text(ARCHIVE.format(recent=RECENT, old=OLD), encoding="utf-8")
    monkeypatch.setattr(gsa, "GLOBAL_SKILLS_PATH", path)
    return path


def _titles(ranked):
    return [title for _, title, _ in ranked]


def test_bm25_recovers_body_match_when_title_wording_differs(archive_file):
    # "heap feng shui" appears only in the Stack Pivoting BODY, never in its
    # title — Jaccard over the title scores it 0, so only BM25 can surface it.
    ranked = gsa._rank_relevant_blocks("heap feng shui layout", top_k=3)
    assert _titles(ranked)[0] == "Stack Pivoting"

    # The old pure-Jaccard path scored this block below the threshold and
    # returned the archive stub heading instead; assert it is actually ranked.
    assert "Stack Pivoting" in _titles(ranked)


def test_title_match_still_outranks_body_match(archive_file):
    # Jaccard title overlap remains the strongest signal for exact wording.
    ranked = gsa._rank_relevant_blocks("format string basics", top_k=3)
    assert _titles(ranked)[0] == "Format String Basics"


def test_unrelated_query_injects_nothing(archive_file):
    # No block shares a term with the query. The old filter kept "at least one"
    # and returned the best-ranked block anyway, so the previous assertion
    # (the tomato block is not ranked FIRST) held while an unrelated skill was
    # still injected. Nothing relevant means nothing at all, on every entry
    # point that feeds the prompt.
    assert gsa._rank_relevant_blocks("quantum chromodynamics", top_k=3) == []
    assert gsa.load_relevant_skills("quantum chromodynamics", top_k=3) == ("", "")
    assert gsa.search_gsa_hits("quantum chromodynamics", top_k=3) == ()


@pytest.mark.parametrize(
    "query",
    [
        CJK_PROMPT,  # no ASCII word characters
        "\u4f60\u662f\u8c01",
        "\uff01\uff1f\u3002",
        "",
        "   ",
        "hi",  # a token, but no block contains it
        "123",
    ],
)
def test_query_without_overlap_injects_nothing(archive_file, query):
    assert gsa._rank_relevant_blocks(query, top_k=3) == []


def test_mixed_language_query_still_matches_on_its_ascii_terms(archive_file):
    ranked = gsa._rank_relevant_blocks("\u8bf7\u89e3\u91ca heap feng shui \u7684\u539f\u7406", top_k=3)
    assert _titles(ranked)[:1] == ["Stack Pivoting"]


CATEGORIZED_ARCHIVE = """\
# 🗂️ PawnLogic Global Skills Archive

# 🛡️ Pwn/Recon

## CTF Recon Essentials
<!-- meta: hits=3 last_used={recent} confidence=0.90 -->
Check the binary protections with checksec before anything else.

# ❌ Failure Patterns

> Automatically generated guardrail note: do not edit this section.

## run_shell — Timeout
<!-- meta: hits=1 last_used={recent} confidence=0.80 -->
A shell command that waits for input never returns; add a timeout.

# 🐳 Docker/Container

## Airlock Network Conflict
<!-- meta: hits=1 last_used={recent} confidence=0.80 -->
Reconnect the container by hand when the airlock refuses:
```bash
# 1. create the container with a bridge network
docker run -d demo
# 2. connect it manually
docker network connect bridge demo
```
Remember the cleanup step afterwards.
"""


@pytest.fixture()
def categorized_archive(tmp_path, monkeypatch):
    path = tmp_path / "global_skills.md"
    path.write_text(CATEGORIZED_ARCHIVE.format(recent=RECENT), encoding="utf-8")
    monkeypatch.setattr(gsa, "GLOBAL_SKILLS_PATH", path)
    return path


def test_category_header_is_not_glued_to_the_skill_above_it(categorized_archive):
    ranked = gsa._rank_relevant_blocks("checksec binary protections", top_k=3)

    block = ranked[0][2]
    assert block.startswith("## CTF Recon Essentials")
    # The next category's header and its note used to ride along at the tail,
    # so a retrieved skill dragged an unrelated section into the prompt.
    assert "Failure Patterns" not in block
    assert "Automatically generated" not in block
    assert "\n# " not in block


def test_skill_blocks_are_split_on_both_heading_levels(categorized_archive):
    blocks = gsa._skill_blocks(categorized_archive.read_text(encoding="utf-8"))

    assert [b.splitlines()[0] for b in blocks] == [
        "## CTF Recon Essentials",
        "## run_shell — Timeout",
        "## Airlock Network Conflict",
    ]
    assert all(not b.rstrip().endswith(("Failure Patterns", "Docker/Container")) for b in blocks)


def test_hash_comment_inside_a_code_fence_does_not_cut_its_skill(categorized_archive):
    ranked = gsa._rank_relevant_blocks("airlock network conflict", top_k=3)

    block = next(b for _, title, b in ranked if title == "Airlock Network Conflict")
    assert "# 2. connect it manually" in block
    assert "Remember the cleanup step afterwards." in block


def test_unbalanced_fence_does_not_swallow_the_skills_below_it():
    content = (
        "# Category\n\n"
        "## Broken Skill\nbody\n```bash\n# comment in a fence nobody closed\n\n"
        "## Healthy Skill\nstill retrievable\n\n"
        "# Next Category\n\n"
        "## Third Skill\nalso retrievable\n"
    )

    blocks = gsa._skill_blocks(content)

    assert [b.splitlines()[0] for b in blocks] == [
        "## Broken Skill",
        "## Healthy Skill",
        "## Third Skill",
    ]
    # The next skill starts with the fence state cleared, so the category
    # header below it still ends it instead of being read as a shell comment.
    assert blocks[1] == "## Healthy Skill\nstill retrievable"
    assert blocks[2] == "## Third Skill\nalso retrievable"


def test_chinese_query_does_not_match_a_chinese_titled_skill_by_emptiness(
    tmp_path, monkeypatch
):
    # Jaccard over two empty token sets is 1.0 ("identical"). A Chinese title
    # and a Chinese prompt both tokenize to nothing, so without the guard on
    # token-less queries they would score as a perfect match.
    path = tmp_path / "global_skills.md"
    path.write_text(
        "# Category\n\n## \u9006\u5411\u5206\u6790\n"
        f"<!-- meta: hits=3 last_used={RECENT} confidence=0.90 -->\n"
        "\u4e2d\u6587\u6b63\u6587\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gsa, "GLOBAL_SKILLS_PATH", path)

    assert gsa._rank_relevant_blocks("\u67e5\u770b\u6e90\u4ee3\u7801", top_k=3) == []
    assert gsa._rank_relevant_blocks("hi", top_k=3) == []


class _NoPacks:
    def match(self, _query, top_k=3):
        return []

    def format_for_prompt(self, _packs):
        return ""


def _turn_block(query):
    from core.prompt_builder import build_turn_context_block

    return build_turn_context_block(
        knowledge_query=query,
        search_knowledge=lambda *_a, **_k: [],
        format_knowledge_for_prompt=lambda _rows: "",
        load_relevant_skills=gsa.load_relevant_skills,
        skill_scanner=_NoPacks(),
    )


def test_a_prompt_that_overlaps_nothing_adds_no_retrieval_block(archive_file):
    assert _turn_block(CJK_PROMPT).block == ""
    assert _turn_block("hi").block == ""
    assert _turn_block("quantum chromodynamics").block == ""


def test_a_prompt_that_overlaps_a_skill_still_gets_its_block(archive_file):
    # Control for the tests above: suppression must not become blanket silence.
    block = _turn_block("heap feng shui layout").block

    assert block.startswith("[Retrieved Context")
    assert "## Stack Pivoting" in block
    assert "Tomato Cultivation" not in block


def test_fsrs_decay_still_orders_two_similar_blocks(archive_file):
    # Two blocks with identical bodies (identical BM25 and title Jaccard)
    # and identical hits/confidence: only the FSRS decay differs, so the
    # recently-used one must rank first.
    body = (
        "Groom the allocator with a heap feng shui layout, then overwrite\n"
        "    the tcache pointer to complete the pivot.\n"
    )
    archive = (
        "# 🗂️ PawnLogic Global Skills Archive\n\n"
        f"## Heap Trick Alpha\n"
        f"<!-- meta: hits=5 last_used={RECENT} confidence=0.90 -->\n{body}\n"
        f"## Heap Trick Beta\n"
        f"<!-- meta: hits=5 last_used={OLD} confidence=0.90 -->\n{body}\n"
    )
    archive_file.write_text(archive, encoding="utf-8")

    ranked = gsa._rank_relevant_blocks("heap feng shui", top_k=3)
    assert _titles(ranked)[:2] == ["Heap Trick Alpha", "Heap Trick Beta"]
    assert ranked[0][0] > ranked[1][0]


def test_algorithm_metadata_names_the_hybrid(archive_file):
    hits = gsa.search_gsa_hits("heap feng shui", top_k=1)
    assert hits
    assert hits[0].score_kind == "gsa_fsrs_bm25_jaccard"
    assert hits[0].provenance["retrieval_algorithm"] == "gsa_fsrs_bm25_jaccard"


def test_local_skill_packs_without_overlap_add_nothing(tmp_path):
    # The third per-turn retrieval path. It has a minimum score instead of a
    # forced fallback; this pins that, with a control that a real match is kept.
    from core.skill_manager import SkillScanner

    pack = tmp_path / "skills" / "pwn_stack"
    pack.mkdir(parents=True)
    (pack / "skill.md").write_text("# Stack overflow\nRet2libc on a stack overflow.\n", encoding="utf-8")
    scanner = SkillScanner(tmp_path / "skills")

    for query in (CJK_PROMPT, "hi", "123", ""):
        assert scanner.match(query, top_k=3) == []
    assert [p["name"] for p in scanner.match("pwn stack overflow", top_k=3)] == ["Stack overflow"]
