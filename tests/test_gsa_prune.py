"""Pruning zombie skills must never take a category header with it.

``prune_zombie_skills`` used to split the archive on ``## `` only, so the last
skill of a ``# `` category swallowed the *next* category's header and the note
under it. Removing that skill deleted the header too, and with it the section
heading the agent's GSA protocol and ``/memo`` rely on. Retrieval had the same
split bug and was fixed on its own; pruning writes the file back, so it was the
one that destroyed data. Both now share ``gsa._archive_segments``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

from core import gsa

RECENT = "2026-10-01"
OLD = "2020-01-01"


def _skill(title: str, *, hits: int, last_used: str, body: str) -> str:
    return (
        f"## {title}\n"
        f"<!-- meta: hits={hits} last_used={last_used} confidence=0.80 -->\n"
        f"{body}\n\n"
    )


FILE_HEAD = "# 🗂️ PawnLogic Global Skills Archive\n\n> Header note kept verbatim.\n\n"
RECON_HEAD = "# 🛡️ Pwn/Recon\n\n> Recon note: it belongs to its category.\n\n"
KEEP_RECON = _skill("Keep Recon", hits=3, last_used=RECENT, body="Check protections with checksec.")
ZOMBIE_RECON = _skill("Stale Recon Zombie", hits=0, last_used=OLD, body="Never validated, long idle.")
FAILURE_HEAD = "# ❌ Failure Patterns\n\n> Automatically generated guardrail note: do not edit this section.\n\n"
KEEP_FAILURE = _skill(
    "run_shell — Timeout", hits=1, last_used=OLD, body="Validated once, so idle alone does not make it a zombie."
)
DOCKER_HEAD = "# 🐳 Docker/Container\n\n> Docker note.\n\n"
KEEP_DOCKER = _skill(
    "Keep Docker Notes",
    hits=2,
    last_used=OLD,
    body="Steps:\n```bash\n# 1. a shell comment inside a fence is not a heading\ndocker run -d demo\n```\nDone.",
)
ZOMBIE_DOCKER = _skill(
    "Airlock Zombie",
    hits=0,
    last_used=OLD,
    body="Shell steps:\n```bash\n# 2. this comment goes with the zombie\ndocker network connect bridge demo\n```",
)
MISC_HEAD = "# 🧰 Misc\n\n> Misc note.\n\n"
ZOMBIE_MISC = _skill(
    "Stale Misc Zombie", hits=0, last_used=OLD, body="The last skill of the last category, at the end of the file."
)

ZOMBIES = (ZOMBIE_RECON, ZOMBIE_DOCKER, ZOMBIE_MISC)
PARTS = (
    FILE_HEAD,
    RECON_HEAD, KEEP_RECON, ZOMBIE_RECON,
    FAILURE_HEAD, KEEP_FAILURE,
    DOCKER_HEAD, KEEP_DOCKER, ZOMBIE_DOCKER,
    MISC_HEAD, ZOMBIE_MISC,
)
ARCHIVE = "".join(PARTS)
EXPECTED = "".join(part for part in PARTS if part not in ZOMBIES)


@pytest.fixture()
def archive_file(tmp_path, monkeypatch):
    path = tmp_path / "global_skills.md"
    path.write_text(ARCHIVE, encoding="utf-8")
    monkeypatch.setattr(gsa, "GLOBAL_SKILLS_PATH", path)
    return path


def test_pruning_removes_exactly_the_zombie_skills_and_nothing_else(archive_file):
    count, names = gsa.prune_zombie_skills()

    assert (count, names) == (3, ["Stale Recon Zombie", "Airlock Zombie", "Stale Misc Zombie"])
    assert archive_file.read_text(encoding="utf-8") == EXPECTED


def test_pruning_the_last_skill_of_a_category_keeps_the_next_header_and_note(archive_file):
    gsa.prune_zombie_skills()
    result = archive_file.read_text(encoding="utf-8")

    # Each of these followed a zombie as the next ``# `` block of the file.
    for kept in (
        "# ❌ Failure Patterns\n\n> Automatically generated guardrail note: do not edit this section.",
        "# 🐳 Docker/Container\n\n> Docker note.",
        "# 🧰 Misc\n\n> Misc note.",
        "> Recon note: it belongs to its category.",
        "> Header note kept verbatim.",
    ):
        assert kept in result
    # A category whose only skill was pruned stays, empty, for the next one.
    assert "Stale Misc Zombie" not in result
    assert result.rstrip().endswith("> Misc note.")


def test_a_fenced_shell_comment_travels_with_its_skill_in_both_directions(archive_file):
    gsa.prune_zombie_skills()
    result = archive_file.read_text(encoding="utf-8")

    # The zombie's own fenced comment is part of that skill and goes with it ...
    assert "# 2. this comment goes with the zombie" not in result
    # ... and a kept skill's fenced comment must not have cut it short.
    assert "# 1. a shell comment inside a fence is not a heading" in result
    assert KEEP_DOCKER in result


def test_pruned_archive_is_still_split_into_the_surviving_skills(archive_file):
    gsa.prune_zombie_skills()

    blocks = gsa._skill_blocks(archive_file.read_text(encoding="utf-8"))

    assert [block.splitlines()[0] for block in blocks] == [
        "## Keep Recon",
        "## run_shell — Timeout",
        "## Keep Docker Notes",
    ]


def test_pruning_is_idempotent(archive_file):
    gsa.prune_zombie_skills()
    after_first = archive_file.read_text(encoding="utf-8")

    assert gsa.prune_zombie_skills() == (0, [])
    assert archive_file.read_text(encoding="utf-8") == after_first


def test_nothing_is_written_when_no_skill_is_a_zombie(tmp_path, monkeypatch):
    path = tmp_path / "global_skills.md"
    path.write_text(FILE_HEAD + RECON_HEAD + KEEP_RECON + FAILURE_HEAD + KEEP_FAILURE, encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    monkeypatch.setattr(gsa, "GLOBAL_SKILLS_PATH", path)

    writes = []
    # Recorded, not raised: prune_zombie_skills swallows write errors (it must not
    # lose the archive to an I/O failure), so an exception here would pass silently.
    monkeypatch.setattr(gsa, "atomic_write_text", lambda *args, **kwargs: writes.append(args))

    assert gsa.prune_zombie_skills() == (0, [])
    assert writes == []
    assert path.read_text(encoding="utf-8") == before


def test_thresholds_still_decide_what_is_a_zombie(archive_file):
    # hits=1 and hits=2 skills are validated; raising min_hits makes them zombies.
    count, names = gsa.prune_zombie_skills(min_hits=3)

    assert "run_shell — Timeout" in names and "Keep Docker Notes" in names
    assert "Keep Recon" not in names  # hits=3 is not below 3
    assert "# ❌ Failure Patterns" in archive_file.read_text(encoding="utf-8")
    assert count == len(names)


def test_segments_reassemble_the_archive_exactly():
    segments = gsa._archive_segments(ARCHIVE)

    assert "".join(text for _, text in segments) == ARCHIVE
    assert all(text.startswith("## ") for is_skill, text in segments if is_skill)
    assert not any(text.startswith("## ") for is_skill, text in segments if not is_skill)
