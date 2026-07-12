"""Static docs-workflow guardrails."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCS_WORKFLOW = ROOT / ".github" / "workflows" / "docs.yml"
MAIN_CI_WORKFLOW = ROOT / ".github" / "workflows" / "main_ci.yml"


def _load_workflow(path: Path) -> dict:
    """Load workflow YAML using BaseLoader so 'on' is not a boolean."""
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_docs_workflow_triggers_use_zh_cn_not_cn():
    """Docs workflow must watch _zh-CN files, not obsolete _CN names."""
    wf = _load_workflow(DOCS_WORKFLOW)

    for trigger in ("push", "pull_request"):
        paths = wf["on"][trigger]["paths"]
        assert "README_zh-CN.md" in paths, f"{trigger} must watch README_zh-CN.md"
        assert "GUIDE_zh-CN.md" in paths, f"{trigger} must watch GUIDE_zh-CN.md"
        assert (
            "README_CN.md" not in paths
        ), f"{trigger} must not watch obsolete README_CN.md"
        assert (
            "GUIDE_CN.md" not in paths
        ), f"{trigger} must not watch obsolete GUIDE_CN.md"


def test_docs_workflow_includes_plan_and_agent_paths():
    """Docs workflow must also trigger on agent docs, plans, and key root docs."""
    wf = _load_workflow(DOCS_WORKFLOW)

    for trigger in ("push", "pull_request"):
        paths = wf["on"][trigger]["paths"]
        assert "PROJECT_MEMORY.md" in paths, f"{trigger} must watch PROJECT_MEMORY.md"
        assert "CONTEXT.md" in paths, f"{trigger} must watch CONTEXT.md"
        assert "CONTRIBUTING.md" in paths, f"{trigger} must watch CONTRIBUTING.md"
        assert "docs/agents/**" in paths, f"{trigger} must watch docs/agents/**"
        assert "docs/plans/**" in paths, f"{trigger} must watch docs/plans/**"


def test_docs_workflow_has_structure_check_job():
    """Docs workflow must include a structure check step."""
    wf = _load_workflow(DOCS_WORKFLOW)
    assert "jobs" in wf
    assert "structure" in wf["jobs"]


def test_main_ci_has_required_docs_guard_job():
    """main_ci.yml must include a required docs-guard job."""
    wf = _load_workflow(MAIN_CI_WORKFLOW)
    assert "jobs" in wf
    assert "docs-guard" in wf["jobs"], "main_ci.yml must have a docs-guard job"

    guard = wf["jobs"]["docs-guard"]
    steps = guard.get("steps", [])
    step_names = [s.get("name", "") for s in steps]
    joined = " ".join(step_names)
    assert (
        "check_doc_structure" in joined or "doc structure" in joined.lower()
    ), "docs-guard must run doc structure check"
    assert (
        "release_consistency" in joined or "release consistency" in joined.lower()
    ), "docs-guard must run release consistency check"
    assert (
        "language" in joined.lower() or "repository_language" in joined
    ), "docs-guard must run repository language policy check"
