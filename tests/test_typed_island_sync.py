"""Guard against the typed-island module list drifting across its three homes.

The typed island is described in three places that are easy to update
inconsistently:

1. the ``mypy typed island`` step in ``.github/workflows/main_ci.yml`` — the
   authoritative list, because a module outside it is never checked;
2. the ``[[tool.mypy.overrides]]`` module list in ``pyproject.toml`` — this is
   what actually turns on ``disallow_untyped_defs`` for a module;
3. the ``Typed Island`` section of ``AGENT.md`` — the documented claim.

A module present in (1) but missing from (2) is checked only under the weak
base config, and a module claimed in (3) but absent from (1) is checked by
nothing at all. Both are silent: nothing fails until the code regresses.

The lists are parsed with regexes rather than ``tomllib`` because the project
supports Python 3.10, which has no stdlib TOML reader, and this guard must not
add a runtime or dev dependency of its own.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "main_ci.yml"
PYPROJECT = REPO_ROOT / "pyproject.toml"
AGENT_MD = REPO_ROOT / "AGENT.md"

# A bare repo-relative module path, e.g. core/session.py or tools/text_patch.py
_MODULE_PATH = r"[A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*\.py"
# A dotted module name, e.g. core.session or tools.text_patch
_DOTTED_MODULE = r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"


def _ci_island_modules() -> set[str]:
    """Module paths passed to mypy by the ``mypy typed island`` CI step."""
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    match = re.search(
        r"name:\s*mypy typed island\b.*?python -m mypy\s*\\(?P<body>.*?)(?:\n\s*\n|\Z)",
        text,
        re.DOTALL,
    )
    assert match, "could not find the 'mypy typed island' step in main_ci.yml"
    return set(re.findall(_MODULE_PATH, match.group("body")))


def _pyproject_island_modules() -> set[str]:
    """Module names in the [[tool.mypy.overrides]] list."""
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(
        r"\[\[tool\.mypy\.overrides\]\]\s*\nmodule\s*=\s*\[(?P<body>.*?)\]",
        text,
        re.DOTALL,
    )
    assert match, "could not find [[tool.mypy.overrides]] in pyproject.toml"
    return set(re.findall(rf'"({_DOTTED_MODULE})"', match.group("body")))


def _agent_md_island_modules() -> set[str]:
    """Module paths named in AGENT.md's ``Typed Island`` section.

    Only the ``Current stable modules:`` list is read. The surrounding prose
    legitimately mentions other files (the CI workflow, this test) and the
    "not in the island" caveat names two modules that are explicitly *not*
    members, so scanning the whole section would report false drift.
    """
    text = AGENT_MD.read_text(encoding="utf-8")
    start = text.index("## Typed Island")
    end = text.index("\n## ", start + 1)
    section = text[start:end]
    list_start = section.index("Current stable modules:")
    # The list is a single paragraph; stop at the blank line that follows it so
    # the "not in the island" caveat below is not read as a membership claim.
    paragraph = section[list_start:].split("\n\n")[0]
    # AGENT.md writes the names without the ``.py`` suffix.
    names = set(re.findall(r"`((?:core|pawnlogic|tools|frontends|config)/[A-Za-z_][A-Za-z0-9_]*)`", paragraph))
    return {name + ".py" for name in names}


def _dotted_to_path(dotted: str) -> str:
    return dotted.replace(".", "/") + ".py"


def test_ci_and_pyproject_name_the_same_modules() -> None:
    ci = _ci_island_modules()
    overrides = {_dotted_to_path(name) for name in _pyproject_island_modules()}

    assert ci - overrides == set(), (
        "these modules are checked by CI but the pyproject override does not "
        "enable disallow_untyped_defs for them, so they are only held to the "
        f"weak base config: {sorted(ci - overrides)}"
    )
    assert overrides - ci == set(), (
        "these pyproject overrides never reach CI because the file is not "
        f"passed to mypy: {sorted(overrides - ci)}"
    )


def test_agent_md_documents_exactly_the_island() -> None:
    ci = _ci_island_modules()
    documented = _agent_md_island_modules()

    assert documented - ci == set(), (
        "AGENT.md claims these modules are in the typed island but CI never "
        f"checks them: {sorted(documented - ci)}"
    )
    assert ci - documented == set(), (
        "CI checks these typed-island modules but AGENT.md does not list "
        f"them: {sorted(ci - documented)}"
    )


def test_documented_island_is_not_empty() -> None:
    """Guard the parser itself: an empty section would pass both assertions."""
    assert len(_ci_island_modules()) >= 40
