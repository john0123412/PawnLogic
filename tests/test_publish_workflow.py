"""Static release-workflow guardrails."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLISH_WORKFLOW = ROOT / ".github" / "workflows" / "publish.yml"
INSTALL_SMOKE = ROOT / "tools" / "release_install_smoke.sh"


def _workflow_text() -> str:
    return PUBLISH_WORKFLOW.read_text(encoding="utf-8")


def _jobs() -> dict:
    import yaml

    return yaml.load(_workflow_text(), Loader=yaml.BaseLoader)["jobs"]


def _transitive_needs(job_name: str) -> set[str]:
    """Every job that must succeed before `job_name` runs.

    Asserting on the transitive graph keeps the ordering guarantee even when a
    gate is inserted between two jobs, which a literal `needs:` string check
    would report as a regression.
    """
    jobs = _jobs()
    seen: set[str] = set()
    pending = [job_name]
    while pending:
        current = pending.pop()
        needs = jobs[current].get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        for dependency in needs:
            assert dependency in jobs, f"{current} needs unknown job {dependency}"
            if dependency not in seen:
                seen.add(dependency)
                pending.append(dependency)
    return seen


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
    # Production PyPI must NOT be reachable from workflow_dispatch.
    assert "workflow_dispatch" not in publish_job
    assert re.search(r"environment:\n\s+name: pypi\n", publish_job)
    assert re.search(r"permissions:\n(?:\s+[A-Za-z-]+: [a-z]+\n)*\s+id-token: write\n", publish_job)
    assert "actions/download-artifact@v7" in publish_job
    assert "name: python-distributions" in publish_job
    assert "pypa/gh-action-pypi-publish@release/v1" in publish_job
    assert "repository-url:" not in publish_job


def test_workflow_dispatch_allows_only_testpypi():
    """Manual dispatch must not offer production PyPI as a target."""
    text = _workflow_text()

    # The workflow_dispatch inputs.target.options must not include 'pypi'.
    # Only 'testpypi' should remain.
    import yaml

    wf = yaml.load(text, Loader=yaml.BaseLoader)
    options = wf["on"]["workflow_dispatch"]["inputs"]["target"]["options"]
    assert "testpypi" in options, "workflow_dispatch must offer testpypi"
    assert "pypi" not in options, "workflow_dispatch must NOT offer pypi"


def test_github_release_runs_only_after_pypi_publish():
    release_job = _job_section(_workflow_text(), "github-release")

    # A release must not be created before the package is published AND proven
    # installable, so assert the ordering guarantee rather than a literal name.
    assert "publish-pypi" in _transitive_needs("github-release")
    assert "smoke-pypi" in _transitive_needs("github-release")
    assert "github.event_name == 'push'" in release_job
    assert "id-token: write" not in release_job
    assert "contents: write" in release_job
    assert "name: python-distributions" in release_job
    assert "name: github-release-notes" in release_job
    assert "softprops/action-gh-release@v3" in release_job
    assert "body_path: release_notes.md" in release_job
    assert "dist/*.whl" in release_job
    assert "dist/*.tar.gz" in release_job


def test_production_tag_must_point_at_a_main_commit():
    """A release tag on an unreviewed commit must not reach production."""
    source_job = _job_section(_workflow_text(), "verify-release-source")

    assert "fetch-depth: 0" in source_job
    assert "merge-base --is-ancestor" in source_job
    assert "origin/main" in source_job

    # The gate must precede every publishing path.
    for job in ("publish-pypi", "publish-testpypi", "github-release"):
        assert "verify-release-source" in _transitive_needs(job), job

    # It must run unconditionally so a dispatch dry-run is not skipped away;
    # a skipped dependency would skip everything downstream.
    assert "if" not in _jobs()["verify-release-source"]


def test_pre_publish_tests_fetch_release_tags():
    """The candidate README must be checked against the latest public tag."""
    test_job = _job_section(_workflow_text(), "test-before-publish")

    assert "actions/checkout@v6" in test_job
    assert "fetch-depth: 0" in test_job


def test_pre_publish_tests_run_release_documentation_gates():
    """A tag must not bypass release consistency or translated-doc guards."""
    test_job = _job_section(_workflow_text(), "test-before-publish")

    assert "Validate release consistency" in test_job
    assert "python3 tools/check_release_consistency.py" in test_job
    assert "Validate translated document structure" in test_job
    assert "python3 tools/check_doc_structure.py" in test_job
    assert test_job.index("python3 tools/check_release_consistency.py") < test_job.index(
        "Run tests"
    )
    assert test_job.index("python3 tools/check_doc_structure.py") < test_job.index(
        "Run tests"
    )


def test_build_pins_artifact_identity_for_post_upload_comparison():
    """skip-existing must not be able to leave a stale file and still pass."""
    build_job = _job_section(_workflow_text(), "build-distributions")

    assert "sha256sum" in build_job
    assert "wheel_sha256=" in build_job
    for output in ("version", "wheel", "wheel_sha256"):
        assert f"{output}: ${{{{ steps.identity.outputs.{output} }}}}" in build_job


def test_published_distributions_are_reinstalled_and_smoke_tested():
    """Uploading is not evidence that the release is installable."""
    jobs = _jobs()

    for smoke, publish, index in (
        ("smoke-testpypi", "publish-testpypi", "https://test.pypi.org/simple/"),
        ("smoke-pypi", "publish-pypi", "https://pypi.org/simple/"),
    ):
        assert smoke in jobs, smoke
        smoke_job = _job_section(_workflow_text(), smoke)
        assert publish in _transitive_needs(smoke)
        assert "build-distributions" in _transitive_needs(smoke)
        assert f"INDEX_URL: {index}" in smoke_job
        assert "tools/release_install_smoke.sh" in smoke_job
        # The smoke must compare against what this run built, not any build.
        assert "needs.build-distributions.outputs.wheel_sha256" in smoke_job

    assert INSTALL_SMOKE.exists()
    assert INSTALL_SMOKE.stat().st_mode & 0o111, "smoke script must be executable"


def test_install_smoke_fails_closed_on_missing_inputs():
    """A smoke that silently skips its checks is worse than no smoke."""
    text = INSTALL_SMOKE.read_text(encoding="utf-8")

    assert "set -euo pipefail" in text
    # Every required input is validated before any work happens.
    for var in (
        "EXPECTED_VERSION",
        "EXPECTED_WHEEL",
        "EXPECTED_SHA256",
        "INDEX_URL",
    ):
        assert var in text
    # The script must never mask a failure.
    assert "|| true" not in text
    assert "continue-on-error" not in text


def test_install_smoke_retries_identity_download_before_install():
    """A newly uploaded wheel may reach different index views at different times."""
    text = INSTALL_SMOKE.read_text(encoding="utf-8")

    assert "if pip_download; then" in text
    assert "Download attempt ${attempt}/${attempts} failed" in text
    assert text.index("if pip_download; then") < text.index(
        'served_wheel="$download/$EXPECTED_WHEEL"'
    )
    assert text.index('served_sha="$(sha256sum "$served_wheel"') < text.index(
        '"$venv/bin/pip" install --no-cache-dir'
    )
