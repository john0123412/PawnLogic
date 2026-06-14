"""Tests for session prompt construction."""

from pathlib import Path
from unittest.mock import MagicMock

from core.prompt_builder import build_session_prompt


class FakeSkillScanner:
    def __init__(self, packs=None, rendered="", error=None):
        self.packs = packs if packs is not None else []
        self.rendered = rendered
        self.error = error
        self.match = MagicMock(side_effect=self._match)
        self.format_for_prompt = MagicMock(return_value=rendered)

    def _match(self, query, top_k):
        if self.error:
            raise self.error
        return self.packs


def _build_prompt(**overrides):
    kwargs = {
        "cfg": {
            "max_tokens": 2048,
            "max_iter": 9,
            "ctx_max_chars": 128_000,
            "tool_max_chars": 16_000,
        },
        "cwd": "/tmp/pawnlogic-project",
        "current_phase": "RECON",
        "model_alias": "test-model",
        "model": {"id": "provider/model-id"},
        "urgent_mode": False,
        "knowledge_query": "",
        "version": "test-version",
        "global_skills_path": Path("/tmp/global_skills.md"),
        "agent_phases": {"RECON": ["list_dir", "read_file"], "EXPLOIT": ["run_code"]},
        "load_state_md": MagicMock(return_value=""),
        "load_skills_toc": MagicMock(return_value="# Pwn\n# Python"),
        "search_knowledge": MagicMock(return_value=[]),
        "format_knowledge_for_prompt": MagicMock(return_value=""),
        "load_relevant_skills": MagicMock(return_value=("", "")),
        "skill_scanner": FakeSkillScanner(),
    }
    kwargs.update(overrides)
    return build_session_prompt(**kwargs), kwargs


def test_build_session_prompt_injects_retrieved_context():
    packs = [{"name": "local-pack"}]
    search_knowledge = MagicMock(return_value=[{"id": 1}])
    format_knowledge = MagicMock(return_value="KNOWLEDGE BLOCK")
    load_relevant = MagicMock(return_value=("GSA SKILL", "CONFLICT WARNING"))
    scanner = FakeSkillScanner(packs=packs, rendered="LOCAL SKILL")

    result, kwargs = _build_prompt(
        knowledge_query="exploit flask",
        load_state_md=MagicMock(return_value="state checkpoint"),
        search_knowledge=search_knowledge,
        format_knowledge_for_prompt=format_knowledge,
        load_relevant_skills=load_relevant,
        skill_scanner=scanner,
    )

    prompt = result.prompt
    assert result.loaded_skill_packs is packs
    assert "You are PawnLogic test-version" in prompt
    assert "=== Current Agent Phase: RECON ===" in prompt
    assert "list_dir, read_file" in prompt
    assert "Other available phases: EXPLOIT" in prompt
    assert "Working dir : /tmp/pawnlogic-project" in prompt
    assert "Model       : test-model (provider/model-id)" in prompt
    assert "Limits      : max_tokens=2048  max_iter=9  ctx=128k  tool_out=16000" in prompt
    assert "=== Current GSA Categories (from global_skills.md) ===\n# Pwn\n# Python" in prompt
    assert "=== GSA Relevant Skills (ranked by recency" in prompt
    assert "GSA SKILL" in prompt
    assert "=== Local Skills (from ./skills/ directory) ===\nLOCAL SKILL" in prompt
    assert "CONFLICT WARNING" in prompt
    assert "KNOWLEDGE BLOCK" in prompt
    assert "=== Project State (.pawn_state.md) ===\nstate checkpoint" in prompt
    assert "<language_rule>" in prompt

    search_knowledge.assert_called_once_with("exploit flask", limit=3)
    format_knowledge.assert_called_once_with([{"id": 1}])
    load_relevant.assert_called_once_with("exploit flask", top_k=3)
    scanner.match.assert_called_once_with("exploit flask", top_k=3)
    scanner.format_for_prompt.assert_called_once_with(packs)
    kwargs["load_skills_toc"].assert_called_once_with()


def test_build_session_prompt_urgent_mode_skips_skill_injection():
    load_skills_toc = MagicMock(return_value="# Should not load")
    load_relevant = MagicMock(return_value=("SKILL", "WARNING"))
    scanner = FakeSkillScanner(packs=[{"name": "unused"}], rendered="LOCAL")

    result, kwargs = _build_prompt(
        urgent_mode=True,
        knowledge_query="",
        load_skills_toc=load_skills_toc,
        load_relevant_skills=load_relevant,
        skill_scanner=scanner,
    )

    assert result.loaded_skill_packs == []
    assert "=== Current GSA Categories (from global_skills.md) ===\n\n" in result.prompt
    assert "GSA Relevant Skills" not in result.prompt
    assert "Local Skills" not in result.prompt
    load_skills_toc.assert_not_called()
    load_relevant.assert_not_called()
    scanner.match.assert_not_called()
    scanner.format_for_prompt.assert_not_called()
    kwargs["search_knowledge"].assert_not_called()


def test_build_session_prompt_preserves_loaded_packs_when_scanner_fails():
    scanner = FakeSkillScanner(error=RuntimeError("scanner failed"))

    result, _kwargs = _build_prompt(skill_scanner=scanner)

    assert result.loaded_skill_packs is None
    assert "Local Skills" not in result.prompt
    scanner.match.assert_called_once_with("", top_k=3)
    scanner.format_for_prompt.assert_not_called()
