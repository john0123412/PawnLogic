from __future__ import annotations

import json
from pathlib import Path

from tools import merge_ctf_skills


def _write_source(root: Path) -> Path:
    skill_dir = root / "skills" / "ctf-pwn"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "# Pwn Basics\n\nExploit stack overflows with controlled offsets.\n",
        encoding="utf-8",
    )
    (skill_dir / "rop.md").write_text("# ROP Chains\n\nUse gadgets.\n", encoding="utf-8")
    return root


def test_dry_run_reports_planned_copies_without_writing_files(tmp_path, capsys):
    src = _write_source(tmp_path / "source")
    dst = tmp_path / "target"

    rc = merge_ctf_skills.merge_skill_tree(src, dst, dry_run=True)

    assert rc == 0
    assert "DRY-RUN ctf_pwn/" in capsys.readouterr().out
    assert not (dst / "ctf_pwn").exists()


def test_existing_destination_files_are_not_overwritten_without_force(tmp_path, capsys):
    src = _write_source(tmp_path / "source")
    dst = tmp_path / "target"
    existing = dst / "ctf_pwn"
    existing.mkdir(parents=True)
    (existing / "skill.md").write_text("existing", encoding="utf-8")
    (existing / "manifest.json").write_text('{"name":"existing"}', encoding="utf-8")

    rc = merge_ctf_skills.merge_skill_tree(src, dst)

    assert rc == 0
    assert "SKIP ctf_pwn/" in capsys.readouterr().out
    assert (existing / "skill.md").read_text(encoding="utf-8") == "existing"
    assert json.loads((existing / "manifest.json").read_text(encoding="utf-8")) == {
        "name": "existing",
    }


def test_force_overwrites_existing_destination_files(tmp_path):
    src = _write_source(tmp_path / "source")
    dst = tmp_path / "target"
    existing = dst / "ctf_pwn"
    existing.mkdir(parents=True)
    (existing / "skill.md").write_text("existing", encoding="utf-8")

    rc = merge_ctf_skills.merge_skill_tree(src, dst, force=True)

    assert rc == 0
    merged = (existing / "skill.md").read_text(encoding="utf-8")
    assert "Pwn Basics" in merged
    assert "Source: rop.md" in merged
    manifest = json.loads((existing / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "CTF Pwn"
    assert "pwn" in manifest["keywords"]
    assert manifest["source"] == {
        "upstream": "MateoBogo/claude-skills-ctf",
        "category": "ctf-pwn",
        "commit": "",
        "license": "unknown",
    }
    assert manifest["redistribution"]["status"] == "blocked"
    assert manifest["redistribution"]["decision"] == "review_pending"
    assert "THIRD_PARTY_NOTICES.md" in manifest["redistribution"]["reason"]


def test_invalid_source_directories_return_nonzero_and_clear_error(tmp_path, capsys):
    missing = tmp_path / "missing"

    assert merge_ctf_skills.merge_skill_tree(missing, tmp_path / "target") == 1
    assert "path does not exist" in capsys.readouterr().out

    no_skills = tmp_path / "no-skills"
    no_skills.mkdir()
    assert merge_ctf_skills.merge_skill_tree(no_skills, tmp_path / "target") == 1
    assert "skills directory not found" in capsys.readouterr().out
