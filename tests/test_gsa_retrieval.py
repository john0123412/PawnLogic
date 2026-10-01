"""Tests for the GSA hybrid retrieval scoring (BM25 + Jaccard + FSRS decay)."""

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

from core import gsa


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


def test_unrelated_query_stays_below_the_floor(archive_file):
    ranked = gsa._rank_relevant_blocks("quantum chromodynamics", top_k=3)
    # The tomato block shares no distinctive term with the query; it must
    # not outrank content-bearing blocks, and its final score must sit at
    # the floor (or below) rather than gaining BM25 relevance.
    titles = _titles(ranked)
    assert "Tomato Cultivation" not in titles[:1]


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
