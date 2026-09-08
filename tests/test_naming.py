"""
tests/test_naming.py — Unit tests for core/naming.py

Covers:
  - normalize_slug produces valid ASCII slugs
  - normalize_slug uses fallback when input is too short
  - should_name_session triggers on substantive conversations
  - should_name_session skips weak inputs (hi / hello / /)
  - _extract_json parses clean JSON
  - _extract_json strips markdown code fences
  - _extract_json raises ValueError on empty input
"""

import os
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

for _key in list(sys.modules):
    if _key == "config" or _key.startswith("config."):
        _f = getattr(sys.modules[_key], "__file__", "") or ""
        if ROOT not in _f:
            del sys.modules[_key]

import pytest  # noqa: E402
from core.naming import normalize_slug, should_name_session, _extract_json  # noqa: E402


# ── normalize_slug ────────────────────────────────────────

def test_normalize_slug_basic():
    slug = normalize_slug("CTF heap exploit", "fallback-slug")
    assert slug == "ctf-heap-exploit"


def test_normalize_slug_strips_special_chars():
    slug = normalize_slug("hello! @world#", "fallback-slug")
    assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in slug)


def test_normalize_slug_too_short_uses_fallback():
    slug = normalize_slug("hi", "my-fallback-slug")
    assert slug == "my-fallback-slug"


def test_normalize_slug_empty_uses_fallback():
    slug = normalize_slug("", "task-abc12345")
    assert slug == "task-abc12345"


def test_normalize_slug_max_length():
    long_input = "a" * 100
    slug = normalize_slug(long_input, "fallback")
    assert len(slug) <= 48


def test_normalize_slug_collapses_hyphens():
    slug = normalize_slug("a---b", "fallback-slug")
    assert "--" not in slug


# ── should_name_session ───────────────────────────────────

def _msg(role: str, content: str) -> dict:
    return {"role": role, "content": content}


def test_should_name_with_tool_call_and_user_text():
    msgs = [
        _msg("user", "analyze this binary file"),
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "run_shell"}}]},
        _msg("tool", "output"),
    ]
    assert should_name_session(msgs) is True


def test_should_name_with_long_user_message():
    msgs = [_msg("user", "please write a complete Python HTTP server with concurrency support")]
    assert should_name_session(msgs) is True


def test_should_name_with_multiple_short_messages():
    # Two user messages totaling >= 40 chars triggers naming
    msgs = [
        _msg("user", "analyze memory corruption in this binary"),
        _msg("assistant", "I will analyze it"),
        _msg("user", "continue and write the full exploit script"),
    ]
    assert should_name_session(msgs) is True


def test_should_not_name_on_greeting():
    msgs = [_msg("user", "hi")]
    assert should_name_session(msgs) is False


def test_should_not_name_on_slash_command():
    msgs = [_msg("user", "/model ds-v4-flash")]
    assert should_name_session(msgs) is False


def test_should_not_name_on_empty():
    assert should_name_session([]) is False


def test_should_not_name_weak_messages():
    msgs = [_msg("user", "hello"), _msg("user", "test")]
    # Two weak messages, both in _WEAK_USER_MESSAGES — should not trigger
    assert should_name_session(msgs) is False


# ── _extract_json ─────────────────────────────────────────

def test_extract_json_clean():
    data = _extract_json('{"title": "CTF Heap", "slug": "ctf-heap"}')
    assert data["title"] == "CTF Heap"
    assert data["slug"] == "ctf-heap"


def test_extract_json_with_markdown_fence():
    text = '```json\n{"title": "Test", "slug": "test-slug"}\n```'
    data = _extract_json(text)
    assert data["slug"] == "test-slug"


def test_extract_json_with_bare_fence():
    text = '```\n{"title": "A", "slug": "a-b-c-d-e-f"}\n```'
    data = _extract_json(text)
    assert data["title"] == "A"


def test_extract_json_with_surrounding_text():
    text = 'Here is the JSON: {"title": "X", "slug": "x-slug-here"} done.'
    data = _extract_json(text)
    assert data["slug"] == "x-slug-here"


def test_extract_json_empty_raises():
    with pytest.raises(ValueError, match="empty naming response"):
        _extract_json("")


def test_extract_json_whitespace_raises():
    with pytest.raises(ValueError, match="empty naming response"):
        _extract_json("   ")


# ── stable_workspace_dir: sessions/ vs workspace/ split ─────────

def _load_naming_module(monkeypatch, tmp_path: Path):
    """Import core.naming against an isolated PAWNLOGIC_HOME."""
    import importlib

    runtime_home = tmp_path / "pawn-home"
    monkeypatch.setenv("PAWNLOGIC_HOME", str(runtime_home))
    for key in list(sys.modules):
        if key == "config" or key.startswith("config.") or key == "core.naming":
            sys.modules.pop(key, None)
    core_pkg = sys.modules.get("core")
    if core_pkg is not None and hasattr(core_pkg, "naming"):
        delattr(core_pkg, "naming")
    return importlib.import_module("core.naming")


def test_stable_workspace_dir_creates_sessions_under_sessions_root(monkeypatch, tmp_path):
    naming = _load_naming_module(monkeypatch, tmp_path)
    path = Path(naming.stable_workspace_dir("sess0001"))

    sessions_root = tmp_path / "pawn-home" / "sessions"
    workspace_root = tmp_path / "pawn-home" / "workspace"
    assert path.parent == sessions_root
    assert path.name == "session_sess0001"
    assert path.is_dir()
    # The session scratch dir must not leak into the named-task workspace.
    assert not (workspace_root / "session_sess0001").exists()


def test_workspace_alias_lands_in_workspace_by_name(monkeypatch, tmp_path):
    naming = _load_naming_module(monkeypatch, tmp_path)
    sessions_dir = Path(naming.stable_workspace_dir("sess0002"))
    (sessions_dir / "finding.md").write_text("report", encoding="utf-8")

    alias = naming.create_workspace_alias(
        "sess0002", "ctf-heap-writeup", str(sessions_dir)
    )

    by_name = tmp_path / "pawn-home" / "workspace" / "by-name" / alias
    assert by_name.is_symlink()
    assert (by_name / "finding.md").read_text(encoding="utf-8") == "report"


def test_link_old_path_to_new_keeps_pre_swap_paths_resolvable(monkeypatch, tmp_path):
    naming = _load_naming_module(monkeypatch, tmp_path)
    home = tmp_path / "pawn-home"

    # Cross-root promotion: sessions/session_x -> workspace/<slug>.
    old = home / "sessions" / "session_x"
    old.mkdir(parents=True)
    (old / "finding.md").write_text("report", encoding="utf-8")
    new = home / "workspace" / "ctf-heap-writeup"
    new.parent.mkdir(parents=True, exist_ok=True)
    os.rename(old, new)

    naming.link_old_path_to_new(old, new)

    assert old.is_symlink()
    assert (old / "finding.md").read_text(encoding="utf-8") == "report"

    # Same-root rename: workspace/session_y -> workspace/<slug>.
    old2 = home / "workspace" / "session_y"
    old2.mkdir(parents=True)
    (old2 / "note.md").write_text("note", encoding="utf-8")
    new2 = home / "workspace" / "web-recon-notes"
    os.rename(old2, new2)

    naming.link_old_path_to_new(old2, new2)

    assert old2.is_symlink()
    assert (old2 / "note.md").read_text(encoding="utf-8") == "note"

    # An occupied old path is never clobbered by the fallback link.
    occupied = home / "workspace" / "occupied-real"
    occupied.mkdir()
    naming.link_old_path_to_new(occupied, new2)
    assert not occupied.is_symlink()
