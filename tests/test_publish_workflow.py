"""Static release-workflow guardrails."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLISH_WORKFLOW = ROOT / ".github" / "workflows" / "publish.yml"


def _workflow_text() -> str:
    return PUBLISH_WORKFLOW.read_text(encoding="utf-8")


def _job_section(text: str, job_name: str) -> str:
    pattern = re.compile(
        rf"^  {re.escape(job_name)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    assert match, f"missing workflow job: {job_name}"
    return match.group("body")


def test_publish_workflow_uses_trusted_publishing_not_long_lived_tokens():
    text = _workflow_text()

    for forbidden in (
        "PYPI_TOKEN",
        "TEST_PYPI_TOKEN",
        "TWINE_PASSWORD",
        "TWINE_USERNAME",
        "twine upload",
    ):
        assert forbidden not in text

    assert text.count("pypa/gh-action-pypi-publish@release/v1") == 2


def test_build_job_has_no_oidc_permission_and_preserves_release_gates():
    build_job = _job_section(_workflow_text(), "build-distributions")

    assert "id-token: write" not in build_job
    assert "Validate release tag version" in build_job
    assert 'startsWith(github.ref, \'refs/tags/v\')' in build_job
    assert "python3 -m build" in build_job
    assert "python3 -m twine check dist/*" in build_job
    assert "Extract GitHub Release notes from CHANGELOG" in build_job
    assert "actions/upload-artifact@v7" in build_job
    assert "name: python-distributions" in build_job


def test_testpypi_publish_job_uses_oidc_environment():
    publish_job = _job_section(_workflow_text(), "publish-testpypi")

    assert "needs: build-distributions" in publish_job
    assert "github.event_name == 'workflow_dispatch'" in publish_job
    assert "inputs.target == 'testpypi'" in publish_job
    assert re.search(r"environment:\n\s+name: testpypi\n", publish_job)
    assert re.search(r"permissions:\n(?:\s+[A-Za-z-]+: [a-z]+\n)*\s+id-token: write\n", publish_job)
    assert "actions/download-artifact@v7" in publish_job
    assert "name: python-distributions" in publish_job
    assert "pypa/gh-action-pypi-publish@release/v1" in publish_job
    assert "repository-url: https://test.pypi.org/legacy/" in publish_job
    assert "skip-existing: true" in publish_job


def test_pypi_publish_job_uses_oidc_environment():
    publish_job = _job_section(_workflow_text(), "publish-pypi")

    assert "needs: build-distributions" in publish_job
    assert "github.event_name == 'push'" in publish_job
    assert "inputs.target == 'pypi'" in publish_job
    assert re.search(r"environment:\n\s+name: pypi\n", publish_job)
    assert re.search(r"permissions:\n(?:\s+[A-Za-z-]+: [a-z]+\n)*\s+id-token: write\n", publish_job)
    assert "actions/download-artifact@v7" in publish_job
    assert "name: python-distributions" in publish_job
    assert "pypa/gh-action-pypi-publish@release/v1" in publish_job
    assert "repository-url:" not in publish_job


def test_github_release_runs_only_after_pypi_publish():
    release_job = _job_section(_workflow_text(), "github-release")

    assert "needs: publish-pypi" in release_job
    assert "github.event_name == 'push'" in release_job
    assert "id-token: write" not in release_job
    assert "contents: write" in release_job
    assert "name: python-distributions" in release_job
    assert "name: github-release-notes" in release_job
    assert "softprops/action-gh-release@v3" in release_job
    assert "body_path: release_notes.md" in release_job
    assert "dist/*.whl" in release_job
    assert "dist/*.tar.gz" in release_job
