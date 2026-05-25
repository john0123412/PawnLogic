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
        _msg("user", "分析这个二进制文件"),
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "run_shell"}}]},
        _msg("tool", "output"),
    ]
    assert should_name_session(msgs) is True


def test_should_name_with_long_user_message():
    msgs = [_msg("user", "请帮我写一个完整的 Python HTTP 服务器，需要支持并发")]
    assert should_name_session(msgs) is True


def test_should_name_with_multiple_short_messages():
    # Two user messages totaling >= 40 chars triggers naming
    msgs = [
        _msg("user", "请帮我分析这个二进制文件的内存漏洞利用点"),  # 21 chars
        _msg("assistant", "好的，我来分析"),
        _msg("user", "继续帮我完成完整的 exploit 利用脚本"),  # 21 chars
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
