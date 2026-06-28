from __future__ import annotations

from tools import check_doc_structure


def test_collect_headings_ignores_fenced_code_blocks(tmp_path):
    doc = tmp_path / "README.md"
    doc.write_text(
        "# Title\n\n"
        "```markdown\n"
        "## Not A Heading\n"
        "```\n\n"
        "## Real Heading\n",
        encoding="utf-8",
    )

    headings = check_doc_structure.collect_headings(doc)

    assert [(heading.level, heading.text) for heading in headings] == [
        (1, "Title"),
        (2, "Real Heading"),
    ]


def test_compare_pair_reports_heading_count_and_level_mismatches(monkeypatch, tmp_path):
    left = tmp_path / "left.md"
    right = tmp_path / "right.md"
    left.write_text("# Title\n\n## Install\n\n### CLI\n", encoding="utf-8")
    right.write_text("# Title CN\n\n### Install CN\n", encoding="utf-8")
    monkeypatch.setattr(check_doc_structure, "ROOT", tmp_path)

    errors = check_doc_structure.compare_pair("left.md", "right.md")

    assert any("left.md has 3 headings, but right.md has 2 headings" in e for e in errors)
    assert any("Heading level mismatch at position 2" in e for e in errors)
    assert any("Missing translated heading at position 3" in e for e in errors)


def test_check_agent_wrapper_requires_thin_delegating_file(monkeypatch, tmp_path):
    wrapper = tmp_path / "AGENTS.md"
    wrapper.write_text("Line without delegation\n## Duplicated Section\n", encoding="utf-8")
    monkeypatch.setattr(check_doc_structure, "ROOT", tmp_path)

    errors = check_doc_structure.check_agent_wrapper("AGENTS.md", "AGENT.md")

    assert "AGENTS.md must delegate to AGENT.md." in errors
    assert "AGENTS.md must not duplicate AGENT.md sections." in errors


def test_check_agent_wrapper_rejects_long_wrapper(monkeypatch, tmp_path):
    wrapper = tmp_path / "CLAUDE.md"
    wrapper.write_text("@AGENT.md\n" + "\n".join(f"line {i}" for i in range(25)), encoding="utf-8")
    monkeypatch.setattr(check_doc_structure, "ROOT", tmp_path)

    errors = check_doc_structure.check_agent_wrapper("CLAUDE.md", "@AGENT.md")

    assert any("should stay a thin wrapper" in error for error in errors)
