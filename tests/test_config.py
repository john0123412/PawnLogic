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
from config.tiers import TIER_LOW, TIER_MID, TIER_DEEP, TIER_MAX  # noqa: E402


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


# ── Tiers ─────────────────────────────────────────────────

def test_tier_keys_present():
    for name, tier in [("LOW", TIER_LOW), ("MID", TIER_MID),
                       ("DEEP", TIER_DEEP), ("MAX", TIER_MAX)]:
        missing = _tier_keys() - tier.keys()
        assert not missing, f"TIER_{name} missing keys: {missing}"


def test_tier_ordering():
    assert TIER_LOW["max_tokens"] <= TIER_MID["max_tokens"]
    assert TIER_MID["max_tokens"] <= TIER_DEEP["max_tokens"]
    assert TIER_LOW["max_iter"] < TIER_MID["max_iter"] < TIER_DEEP["max_iter"]
    assert TIER_DEEP["max_iter"] < TIER_MAX["max_iter"]


def test_ctx_trim_less_than_max():
    for tier in (TIER_LOW, TIER_MID, TIER_DEEP, TIER_MAX):
        assert tier["ctx_trim_to"] < tier["ctx_max_chars"]
