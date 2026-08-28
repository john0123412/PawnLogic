"""Tool-call protocol contract tests for the session prompt."""

from pathlib import Path

from core.prompt_builder import build_session_prompt


class _FakeSkillScanner:
    def match(self, _query: str, *, top_k: int) -> list[object]:
        assert top_k == 3
        return []

    def format_for_prompt(self, _packs: list[object]) -> str:
        return ""


def _build_prompt() -> str:
    result = build_session_prompt(
        cfg={
            "max_tokens": 1,
            "max_iter": 1,
            "ctx_max_chars": 1_000,
            "tool_max_chars": 1_000,
        },
        cwd="/tmp/fake-pawnlogic-project",
        current_phase="FAKE_PHASE",
        model_alias="fake-model",
        model={"id": "fake-provider/fake-model"},
        urgent_mode=False,
        knowledge_query="",
        version="fake-version",
        global_skills_path=Path("/tmp/fake-skills.md"),
        agent_phases={"FAKE_PHASE": ["fake_tool"]},
        load_state_md=lambda _cwd: "",
        load_skills_toc=lambda: "",
        search_knowledge=lambda _query, *, limit: [],
        format_knowledge_for_prompt=lambda _rows: "",
        load_relevant_skills=lambda _query, *, top_k: ("", ""),
        skill_scanner=_FakeSkillScanner(),
    )
    return result.prompt


def test_prompt_requires_wrapped_json_tool_calls_without_a_bare_json_alternative():
    """The model-facing protocol has one JSON envelope and plan sequencing rule."""
    prompt = _build_prompt()

    assert "Use exactly this text tool-call format:" in prompt
    assert '<tool_call>{"name":"tool_name","arguments":{"key":"value"}}</tool_call>' in prompt
    assert "Do not emit a bare JSON object as a tool call." in prompt
    assert "The first <tool_call> must immediately follow </plan>." in prompt
    assert "You have TWO output formats." not in prompt
    assert "[RULE 1: COMPACT JSON]" not in prompt
    assert 'Format: {"name":"tool_name","arguments":{"key":"val"}}' not in prompt
    assert '<call name="write_file">' not in prompt
