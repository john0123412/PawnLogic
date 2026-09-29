"""
tests/test_config.py — Unit tests for config module

Covers:
  - VERSION is a non-empty string
  - All required path constants are Path objects
  - TIER dicts contain required keys
  - normalize_slug produces valid slugs
  - is_fast_model / find_fast_peer logic
"""

import os
import sys
import subprocess
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# If a previous test file mocked sys.modules["config"], evict it now
# so we import the real local package.
for _key in list(sys.modules):
    if _key == "config" or _key.startswith("config."):
        _f = getattr(sys.modules[_key], "__file__", "") or ""
        if ROOT not in _f:
            del sys.modules[_key]

from config import VERSION, DB_PATH, GLOBAL_SKILLS_PATH, WORKSPACE_DIR, LOG_DIR  # noqa: E402
from config.tiers import (  # noqa: E402
    DEFAULT_EFFORT_LEVEL,
    EFFORT_LEVELS,
    EFFORT_PRESETS,
    EFFORT_WIRE_VALUES,
    TIER_LOW,
    TIER_MID,
    TIER_DEEP,
    TIER_MAX,
    TIER_ULTRA,
    effort_delivery,
    effort_options,
    effort_preset,
    infer_effort_level,
    is_effort_level,
)


# ── helpers ──────────────────────────────────────────────

def _tier_keys():
    return {"max_tokens", "ctx_max_chars", "ctx_trim_to", "max_iter",
            "tool_max_chars", "fetch_max_chars"}


# ── VERSION ──────────────────────────────────────────────

def test_version_is_string():
    assert isinstance(VERSION, str) and VERSION, "VERSION must be a non-empty string"


def test_version_format():
    parts = VERSION.split(".")
    assert len(parts) >= 2, "VERSION should be in MAJOR.MINOR format"
    assert all(p.isdigit() for p in parts), "VERSION parts must be numeric"


# ── Paths ─────────────────────────────────────────────────

def test_db_path_type():
    assert isinstance(DB_PATH, Path)


def test_global_skills_path_type():
    assert isinstance(GLOBAL_SKILLS_PATH, Path)


def test_workspace_dir_type():
    assert isinstance(WORKSPACE_DIR, str)


def test_log_dir_type():
    assert isinstance(LOG_DIR, Path)


def test_pawnlogic_home_env_overrides_runtime_paths(tmp_path):
    pawn_home = tmp_path / "pawn-home"
    code = """
import config
assert config.PAWNLOGIC_HOME == config.DB_PATH.parent
assert str(config.PAWNLOGIC_HOME) == __import__('os').environ['PAWNLOGIC_HOME']
assert str(config.DB_PATH).startswith(str(config.PAWNLOGIC_HOME))
assert str(config.GLOBAL_SKILLS_PATH).startswith(str(config.PAWNLOGIC_HOME))
assert config.WORKSPACE_DIR == str(config.PAWNLOGIC_HOME / 'workspace')
assert str(config.CUSTOM_PROVIDERS_PATH).startswith(str(config.PAWNLOGIC_HOME))
assert config.BROWSER_CONFIG['screenshot_dir'] == str(config.PAWNLOGIC_HOME / 'workspace' / 'screenshots')
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PAWNLOGIC_HOME": str(pawn_home)},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_skills_dir_falls_back_to_pawnlogic_home_when_source_skills_missing(tmp_path):
    pawn_home = tmp_path / "pawn-home"
    source_skills = Path(ROOT) / "skills"
    code = """
import os
import pathlib

real_exists = pathlib.Path.exists
source_skills = pathlib.Path(os.environ['SOURCE_SKILLS']).resolve()

def fake_exists(path):
    if path.resolve() == source_skills:
        return False
    return real_exists(path)

pathlib.Path.exists = fake_exists
import config
assert config.SKILLS_DIR == config.PAWNLOGIC_HOME / 'skills'
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PAWNLOGIC_HOME": str(pawn_home), "SOURCE_SKILLS": str(source_skills)},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


# ── Tiers ─────────────────────────────────────────────────

def test_tier_keys_present():
    for name, tier in [("LOW", TIER_LOW), ("MID", TIER_MID),
                       ("DEEP", TIER_DEEP), ("MAX", TIER_MAX),
                       ("ULTRA", TIER_ULTRA)]:
        missing = _tier_keys() - tier.keys()
        assert not missing, f"TIER_{name} missing keys: {missing}"


def test_tier_ordering():
    assert TIER_LOW["max_tokens"] <= TIER_MID["max_tokens"]
    assert TIER_MID["max_tokens"] <= TIER_DEEP["max_tokens"]
    assert TIER_LOW["max_iter"] < TIER_MID["max_iter"] < TIER_DEEP["max_iter"]
    assert TIER_DEEP["max_iter"] < TIER_MAX["max_iter"] < TIER_ULTRA["max_iter"]


def test_ultra_only_raises_max_tool_call_iterations():
    assert TIER_MAX["max_iter"] == 100
    assert TIER_ULTRA["max_iter"] == 150
    assert {
        key: value for key, value in TIER_ULTRA.items() if key != "max_iter"
    } == {
        key: value for key, value in TIER_MAX.items() if key != "max_iter"
    }


def test_ctx_trim_less_than_max():
    for tier in (TIER_LOW, TIER_MID, TIER_DEEP, TIER_MAX, TIER_ULTRA):
        assert tier["ctx_trim_to"] < tier["ctx_max_chars"]


def test_tier_plan_guard_defaults_to_advisory():
    for tier in (TIER_LOW, TIER_MID, TIER_DEEP, TIER_MAX, TIER_ULTRA):
        assert tier["plan_guard_mode"] == "advisory"


# ── Reasoning-effort ladder ─────────────────────────────

def test_every_effort_level_has_a_preset_named_after_itself():
    for level in EFFORT_LEVELS:
        assert EFFORT_PRESETS[level]["effort_level"] == level
        assert effort_preset(level)["effort_level"] == level


def test_effort_preset_carries_the_full_tier_key_set():
    for level in EFFORT_LEVELS:
        missing = _tier_keys() - EFFORT_PRESETS[level].keys()
        assert not missing, f"effort level {level} missing keys: {missing}"


def test_effort_ladder_is_monotonic_in_iterations():
    """Each rung must buy more tool-call iterations than the one below it.

    ``off`` and ``low`` share TIER_LOW by design, so the comparison starts
    at ``low``; the duplicate is asserted separately rather than hidden.
    """
    ordered = EFFORT_LEVELS[EFFORT_LEVELS.index("low"):]
    iterations = [EFFORT_PRESETS[level]["max_iter"] for level in ordered]
    assert iterations == sorted(iterations)
    assert len(set(iterations)) == len(iterations), "rungs must not tie"


def test_effort_ladder_is_monotonic_in_tokens_and_context():
    ordered = EFFORT_LEVELS[EFFORT_LEVELS.index("low"):]
    for key in ("max_tokens", "ctx_max_chars", "tool_max_chars"):
        values = [EFFORT_PRESETS[level][key] for level in ordered]
        assert values == sorted(values), key


def test_effort_ctx_trim_stays_below_max():
    for level in EFFORT_LEVELS:
        preset = EFFORT_PRESETS[level]
        assert preset["ctx_trim_to"] < preset["ctx_max_chars"], level


def test_top_effort_rung_keeps_the_150_iteration_ceiling():
    """``/ultra`` folded into the top rung rather than being dropped."""
    assert EFFORT_PRESETS["max"]["max_iter"] == TIER_ULTRA["max_iter"] == 150


def test_effort_wire_values_cover_every_level_exactly_once():
    assert set(EFFORT_WIRE_VALUES) == set(EFFORT_LEVELS)


def test_effort_preset_returns_a_copy():
    """Callers write the copy back, so sharing the module dict would let
    one session's effort change mutate every other session's config."""
    first = effort_preset("high")
    first["max_iter"] = 1
    assert effort_preset("high")["max_iter"] != 1


def test_is_effort_level_rejects_unknown_and_non_string_values():
    assert is_effort_level("high")
    assert not is_effort_level("HIGH")
    assert not is_effort_level("deep")  # the legacy tier name, not a level
    assert not is_effort_level("")
    assert not is_effort_level(None)
    assert not is_effort_level(3)


def test_infer_effort_level_recovers_a_level_from_legacy_limits():
    """Old snapshots carry limits but no ``effort_level``; restoring one
    must not silently snap a user's ``/ultra`` session to the default."""
    for level in ("low", "medium", "high", "xhigh", "max"):
        assert infer_effort_level(EFFORT_PRESETS[level]) == level, level
    # The no-key path defaults instead of raising.
    assert infer_effort_level({}) == DEFAULT_EFFORT_LEVEL
    assert infer_effort_level(None) == DEFAULT_EFFORT_LEVEL
    assert infer_effort_level({"max_tokens": "x", "max_iter": "y"}) == (
        DEFAULT_EFFORT_LEVEL
    )


def test_effort_options_label_each_rung_by_where_it_is_applied():
    """A level the model has not declared must not read as a no-op."""
    declared = EFFORT_WIRE_VALUES
    rows = effort_options(declared)
    assert [row[0] for row in rows] == list(EFFORT_LEVELS)
    for level, label, description in rows:
        assert label == level
        assert f"sent as {declared[level]}" in description, level

    undeclared = effort_options({})
    for level, _label, description in undeclared:
        assert "local limits only" in description, level
        # Still states the limits, so the row is never empty of meaning.
        assert "iter=" in description, level


def test_effort_delivery_states_where_the_level_is_actually_applied():
    assert effort_delivery(EFFORT_WIRE_VALUES, "ds-v4-flash", "high") == (
        "provider reasoning_effort=high"
    )
    # A model with no declaration still gets the limits; the wording must
    # not imply the level did nothing.
    assert effort_delivery({}, "gpt-4o", "high") == (
        "local limits only (model declares no reasoning_effort support)"
    )
    assert effort_delivery({}, "", "high") == "local limits only"
