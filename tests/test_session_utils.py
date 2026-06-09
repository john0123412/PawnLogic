"""
tests/test_session_utils.py — Unit tests for core/session.py utility functions

Targets zero-dependency or minimal-dependency functions only:
  - _ctx_chars
  - _trim_and_compact_context
  - _is_plan_exempt
  - _PlanRenderer.feed / flush
  - AgentSession._count_turns
  - AgentSession._extract_calls (Hybrid XML/JSON parser)
  - AgentSession.undo
"""

import sys
import inspect
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ── Evict any mock config left by test_api_empty_response ────────────
for _key in list(sys.modules):
    if _key == "config" or _key.startswith("config."):
        _f = getattr(sys.modules[_key], "__file__", "") or ""
        if ROOT not in _f:
            del sys.modules[_key]

# ── Import real config first, then patch heavy session.py deps ───────
import config  # noqa: E402 — force-cache real package
assert config.VERSION

# Heavy dependencies that session.py imports at module level — mock them
# so we don't need a real DB, API key, or full environment.
_MOCKS = [
    "core.api_client", "core.memory", "core.gsa", "core.logger",
    "core.skill_manager", "core.mcp_client_manager",
    "tools.file_ops", "tools.web_ops", "tools.sandbox",
    "tools.pwn_chain", "tools.vision",
    "tools.docker_sandbox", "tools.browser_ops", "tools.recon_ops",
    "tools.delegate_tool",
]
for _m in _MOCKS:
    if _m not in sys.modules:
        sys.modules[_m] = MagicMock()

# Patch specific attributes session.py reads at import time
sys.modules["core.memory"]._gen_id = lambda: "test_session_id_abc123"
sys.modules["core.memory"].init_db = lambda: None
sys.modules["core.memory"].search_knowledge = lambda *a, **kw: []
sys.modules["core.memory"].format_knowledge_for_prompt = lambda *a, **kw: ""
sys.modules["core.memory"].update_session_naming = MagicMock()
sys.modules["core.memory"].write_failure = MagicMock()
sys.modules["core.memory"].check_failure = MagicMock(return_value=[])
sys.modules["core.memory"].count_failure = MagicMock(return_value=0)
sys.modules["core.memory"].format_failures_for_prompt = MagicMock(return_value="")
sys.modules["core.gsa"].load_relevant_skills = MagicMock(return_value=("", ""))
sys.modules["core.gsa"].bump_skill = MagicMock(return_value=(True, "ok"))
sys.modules["core.gsa"].sink_failure_to_gsa = MagicMock(return_value=(False, ""))
sys.modules["core.gsa"].load_toc = MagicMock(return_value="")
sys.modules["core.logger"].logger = MagicMock()
sys.modules["core.logger"].audit_tool_call = MagicMock()
sys.modules["core.api_client"].stream_request = MagicMock(return_value=iter([]))
sys.modules["core.api_client"].ensure_tool_call_id = lambda tc, i, idx: f"id_{i}_{idx}"
sys.modules["tools.file_ops"]._session_cwd = [""]
sys.modules["tools.file_ops"]._session_workspace_dir = [""]
sys.modules["tools.file_ops"].FILE_SCHEMAS = []
sys.modules["tools.web_ops"].WEB_SCHEMAS = []
sys.modules["tools.sandbox"].SANDBOX_SCHEMAS = []
sys.modules["tools.pwn_chain"].PWN_SCHEMAS = []
sys.modules["tools.vision"].VISION_SCHEMAS = []
sys.modules["tools.docker_sandbox"].DOCKER_SCHEMAS = []
sys.modules["tools.browser_ops"].BROWSER_SCHEMAS = []
sys.modules["tools.recon_ops"].RECON_SCHEMAS = []

# Mock SkillScanner used at module level
_mock_scanner = MagicMock()
_mock_scanner.match.return_value = []
_mock_scanner.format_for_prompt.return_value = ""
_mock_scanner.format_user_message.return_value = ""
sys.modules["core.skill_manager"].SkillScanner = MagicMock(return_value=_mock_scanner)

# Now import the real session functions
from core.session import (  # noqa: E402
    AgentSession,
    TurnInterrupted,
    _ctx_chars,
    _drop_dangling_tool_call_messages,
    _trim_and_compact_context,
    _is_plan_exempt,
    _tool_call_missing_plan,
    _PlanRenderer,
)


# ── helpers ───────────────────────────────────────────────

def _msg(role, content="", **kw):
    m = {"role": role, "content": content}
    m.update(kw)
    return m


# ══════════════════════════════════════════════════════════
# _ctx_chars
# ══════════════════════════════════════════════════════════

def test_ctx_chars_basic():
    msgs = [_msg("user", "hello"), _msg("assistant", "world")]
    assert _ctx_chars(msgs) == 10


def test_ctx_chars_includes_reasoning_content():
    msgs = [{"role": "assistant", "content": "hi", "reasoning_content": "think"}]
    assert _ctx_chars(msgs) == len("hi") + len("think")


def test_ctx_chars_none_content():
    msgs = [{"role": "assistant", "content": None}]
    assert _ctx_chars(msgs) == 0


def test_ctx_chars_empty():
    assert _ctx_chars([]) == 0


def test_cot_guard_soft_intercept_branch_is_reachable():
    source = inspect.getsource(AgentSession.run_turn)
    assert "elif _plan_rejected > 0:" in source
    assert source.index("elif _plan_rejected > 0:") < source.index("_plan_signal_injected = True")


# ══════════════════════════════════════════════════════════
# _trim_and_compact_context
# ══════════════════════════════════════════════════════════

def test_trim_no_op_when_under_limit(monkeypatch):
    from config import DYNAMIC_CONFIG
    monkeypatch.setitem(DYNAMIC_CONFIG, "ctx_max_chars", 100_000)
    msgs = [_msg("system", "sys"), _msg("user", "hi"), _msg("assistant", "ok")]
    original = list(msgs)
    result = _trim_and_compact_context(msgs)
    assert result == 0
    assert msgs == original


def test_trim_compacts_when_over_limit(monkeypatch):
    from config import DYNAMIC_CONFIG
    monkeypatch.setitem(DYNAMIC_CONFIG, "ctx_max_chars", 10)  # tiny limit
    msgs = [
        _msg("system", "sys"),
        *[_msg("user", f"message_{i}" * 5) for i in range(20)],
    ]
    original_len = len(msgs)
    result = _trim_and_compact_context(msgs)
    assert result > 0
    assert len(msgs) < original_len
    # system prompt always preserved at index 0
    assert msgs[0]["role"] == "system"
    # summary injected at index 1
    assert msgs[1]["role"] == "assistant"
    assert "Context Compacted" in msgs[1]["content"]


def test_trim_returns_zero_if_too_few_msgs(monkeypatch):
    from config import DYNAMIC_CONFIG
    monkeypatch.setitem(DYNAMIC_CONFIG, "ctx_max_chars", 1)
    msgs = [_msg("system", "s"), _msg("user", "u")]  # only 2 msgs
    result = _trim_and_compact_context(msgs)
    assert result == 0


# ══════════════════════════════════════════════════════════
# _is_plan_exempt
# ══════════════════════════════════════════════════════════

def test_is_plan_exempt_for_exempt_tools():
    tc_buf = {0: {"name": "pwn_env", "args": "{}"}}
    assert _is_plan_exempt(tc_buf) is True

    tc_buf = {0: {"name": "list_dir", "args": "{}"}}
    assert _is_plan_exempt(tc_buf) is True

    tc_buf = {0: {"name": "search_skills", "args": "{}"}}
    assert _is_plan_exempt(tc_buf) is True


def test_is_plan_exempt_false_for_write_tool():
    tc_buf = {0: {"name": "write_file", "args": "{}"}}
    assert _is_plan_exempt(tc_buf) is False


def test_is_plan_exempt_git_op_readonly():
    import json
    tc_buf = {0: {"name": "git_op", "args": json.dumps({"action": "status"})}}
    assert _is_plan_exempt(tc_buf) is True


def test_is_plan_exempt_git_op_write():
    import json
    tc_buf = {0: {"name": "git_op", "args": json.dumps({"action": "commit"})}}
    assert _is_plan_exempt(tc_buf) is False


def test_is_plan_exempt_mixed_fails():
    tc_buf = {
        0: {"name": "pwn_env", "args": "{}"},
        1: {"name": "run_shell", "args": "{}"},
    }
    assert _is_plan_exempt(tc_buf) is False


def test_tool_call_missing_plan_false_without_tool_calls():
    assert _tool_call_missing_plan("plain text", {}) is False


def test_tool_call_missing_plan_false_for_exempt_tool():
    tc_buf = {0: {"name": "list_dir", "args": "{}"}}
    assert _tool_call_missing_plan("", tc_buf) is False


def test_tool_call_missing_plan_true_for_write_tool_without_plan():
    tc_buf = {0: {"name": "write_file", "args": "{}"}}
    assert _tool_call_missing_plan("I will write the file", tc_buf) is True


def test_tool_call_missing_plan_false_when_required_plan_present():
    tc_buf = {0: {"name": "run_shell", "args": "{}"}}
    text = "<plan><intent>Run verification</intent></plan>"
    assert _tool_call_missing_plan(text, tc_buf) is False


# ══════════════════════════════════════════════════════════
# _PlanRenderer
# ══════════════════════════════════════════════════════════

def test_plan_renderer_passthrough_before_plan():
    r = _PlanRenderer()
    out = r.feed("hello world")
    assert out == "hello world"


def test_plan_renderer_suppresses_plan_content(capsys):
    r = _PlanRenderer()
    r.feed("<plan>")
    r.feed("some plan text")
    r.feed("</plan>")
    out = r.feed("after plan")
    assert out == "after plan"


def test_plan_renderer_flush_clears_state():
    # feed() already drains non-plan text; flush() clears remaining tail
    r = _PlanRenderer()
    # Inject text with a partial tag so feed() holds it in tail
    r.tail = "<pla"  # simulate partial tag buffered in tail
    leftover = r.flush()
    # After flush, tail is cleared and leftover contains what was in tail
    assert r.tail == ""
    assert leftover == "<pla"


def test_plan_renderer_initial_state():
    r = _PlanRenderer()
    assert r.in_plan is False
    assert r.tail == ""


# ══════════════════════════════════════════════════════════
# AgentSession._count_turns (via minimal session instance)
# ══════════════════════════════════════════════════════════

def _make_session():
    """Build a minimal AgentSession without triggering real I/O."""
    with patch("core.session.stable_workspace_dir", return_value="/tmp/test_ws"), \
         patch("core.session.init_db"), \
         patch("core.session.AgentSession._reset_system_prompt"):
        from core.session import AgentSession
        s = object.__new__(AgentSession)
        s.session_id = "test_session_id_abc123"
        s.model_alias = "ds-v4-flash"
        s.messages = [{"role": "system", "content": "sys"}]
        s.cwd = "/tmp"
        s.workspace_dir = "/tmp/test_ws"
        s.current_phase = "RECON"
        s._history_summary = ""
        s._summary_turn_count = 0
        s._turn_count = 0
        s._naming_done = False
        s._naming_attempted_at = 0.0
        s._urgent_mode = False
        s._loaded_skill_packs = []
        return s


def test_count_turns_empty():
    s = _make_session()
    s.messages = [_msg("system", "sys")]
    assert s._count_turns(s.messages) == []


def test_count_turns_one_turn():
    s = _make_session()
    s.messages = [
        _msg("system", "sys"),
        _msg("user", "hello"),
        _msg("assistant", "hi"),
    ]
    turns = s._count_turns(s.messages)
    assert len(turns) == 1
    assert turns[0] == (1, 3)


def test_count_turns_two_turns():
    s = _make_session()
    s.messages = [
        _msg("system", "sys"),
        _msg("user", "q1"),
        _msg("assistant", "a1"),
        _msg("user", "q2"),
        _msg("assistant", "a2"),
    ]
    turns = s._count_turns(s.messages)
    assert len(turns) == 2


def test_count_turns_with_tool_messages():
    s = _make_session()
    s.messages = [
        _msg("system", "sys"),
        _msg("user", "run"),
        _msg("assistant", "", tool_calls=[{"function": {"name": "run_shell"}}]),
        _msg("tool", "output", tool_call_id="id_0"),
        _msg("assistant", "done"),
    ]
    turns = s._count_turns(s.messages)
    assert len(turns) == 1
    assert turns[0][0] == 1   # start after system


def test_drop_dangling_tool_call_messages_removes_unmatched_assistant_calls():
    msgs = [
        _msg("system", "sys"),
        _msg("user", "q"),
        _msg("assistant", "", tool_calls=[{"id": "call_a", "function": {"name": "find_files"}}]),
        _msg("user", "next question"),
    ]

    cleaned = _drop_dangling_tool_call_messages(msgs)

    assert [m["role"] for m in cleaned] == ["system", "user", "user"]
    assert msgs[-2]["role"] == "assistant"


def test_build_api_messages_drops_dangling_tail_tool_calls():
    s = _make_session()
    s.messages = [
        _msg("system", "sys"),
        _msg("user", "q"),
        _msg("assistant", "", tool_calls=[{"id": "call_a", "function": {"name": "find_files"}}]),
    ]

    built = s._build_api_messages()

    assert [m["role"] for m in built] == ["system", "user"]
    assert all(not m.get("tool_calls") for m in built)


def test_build_api_messages_drops_dangling_tool_calls_before_new_user():
    s = _make_session()
    s.messages = [
        _msg("system", "sys"),
        _msg("user", "q"),
        _msg("assistant", "", tool_calls=[{"id": "call_a", "function": {"name": "find_files"}}]),
        _msg("user", "next"),
    ]

    built = s._build_api_messages()

    assert [m["role"] for m in built] == ["system", "user", "user"]
    assert all(not m.get("tool_calls") for m in built)


def test_run_turn_injects_plan_missing_for_non_exempt_tool(monkeypatch):
    import json
    from config import DYNAMIC_CONFIG
    import core.session as session_mod

    s = _make_session()
    s._time_budget_sec = 0
    s._turn_prompt_tokens = 0
    s._turn_completion_tokens = 0
    s._turn_tool_calls = 0
    s.total_prompt_tokens = 0
    s.total_completion_tokens = 0
    s.total_tool_calls = 0
    s._save_lock = threading.Lock()
    s._naming_lock = threading.Lock()

    monkeypatch.setitem(DYNAMIC_CONFIG, "max_iter", 3)
    monkeypatch.setattr(session_mod, "validate_api_key", lambda _m: (True, ""))
    monkeypatch.setattr(s, "_reset_system_prompt", MagicMock())
    monkeypatch.setattr(s, "_maybe_update_summary", MagicMock())
    monkeypatch.setattr(s, "_autosave", MagicMock())
    monkeypatch.setitem(session_mod.TOOL_MAP, "write_file", lambda _args: "OK: fake write")

    calls = iter([
        [{
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "call_missing_plan",
                        "function": {
                            "name": "write_file",
                            "arguments": json.dumps({"path": "x.txt", "content": "x"}),
                        },
                    }],
                },
            }],
        }],
        [{"choices": [{"delta": {"content": "done"}}]}],
    ])

    def fake_stream_request(*_args, **_kwargs):
        return iter(next(calls))

    monkeypatch.setattr(session_mod, "stream_request", fake_stream_request)

    s.run_turn("write a file")

    assert any(
        m.get("role") == "user" and "PLAN_MISSING" in str(m.get("content", ""))
        for m in s.messages
    )


def test_history_summary_skips_empty_stream_choices(monkeypatch):
    from config import DYNAMIC_CONFIG
    import core.session as session_mod

    s = _make_session()
    s.messages = [
        _msg("system", "sys"),
        _msg("user", "q1"),
        _msg("assistant", "a1"),
        _msg("user", "q2"),
        _msg("assistant", "a2"),
        _msg("user", "q3"),
        _msg("assistant", "a3"),
    ]

    monkeypatch.setitem(DYNAMIC_CONFIG, "ctx_summary_threshold", 3)
    monkeypatch.setitem(DYNAMIC_CONFIG, "ctx_sliding_turns", 1)
    monkeypatch.setattr(session_mod, "stream_request", lambda *_a, **_kw: iter([
        {"choices": []},
        {"choices": [{"delta": {"content": "older turns summarized"}}]},
    ]))
    warning_mock = MagicMock()
    monkeypatch.setattr(session_mod.logger, "warning", warning_mock)

    s._maybe_update_summary(s.messages, current_turn_count=3)

    assert s._history_summary == "older turns summarized"
    warning_mock.assert_not_called()


def test_run_turn_interrupt_raises_for_cli_rollback(monkeypatch):
    from config import DYNAMIC_CONFIG
    import core.session as session_mod

    s = _make_session()
    s._time_budget_sec = 0
    s._turn_prompt_tokens = 0
    s._turn_completion_tokens = 0
    s._turn_tool_calls = 0
    s.total_prompt_tokens = 0
    s.total_completion_tokens = 0
    s.total_tool_calls = 0
    s._save_lock = threading.Lock()
    s._naming_lock = threading.Lock()

    monkeypatch.setitem(DYNAMIC_CONFIG, "max_iter", 3)
    monkeypatch.setattr(session_mod, "validate_api_key", lambda _m: (True, ""))
    monkeypatch.setattr(s, "_reset_system_prompt", MagicMock())
    monkeypatch.setattr(s, "_maybe_update_summary", MagicMock())
    monkeypatch.setattr(s, "_build_api_messages", lambda: s.messages)
    monkeypatch.setattr(s, "_autosave", MagicMock())

    def interrupted_stream(*_args, **_kwargs):
        raise KeyboardInterrupt
        yield  # pragma: no cover

    monkeypatch.setattr(session_mod, "stream_request", interrupted_stream)

    with pytest.raises(TurnInterrupted):
        s.run_turn("interrupt me")

    assert s.messages[-1]["role"] == "user"
    assert s.messages[-1]["content"] == "interrupt me"


# ══════════════════════════════════════════════════════════
# AgentSession.undo
# ══════════════════════════════════════════════════════════

def test_undo_basic():
    s = _make_session()
    s.messages = [
        _msg("system", "sys"),
        _msg("user", "hello"),
        _msg("assistant", "hi"),
    ]
    removed, last_text = s.undo(1)
    assert removed >= 1
    assert last_text == "hello"
    assert all(m["role"] != "user" or m.get("content") != "hello"
               for m in s.messages)


def test_undo_preserves_system():
    s = _make_session()
    s.messages = [
        _msg("system", "sys"),
        _msg("user", "q"),
        _msg("assistant", "a"),
    ]
    s.undo(10)  # undo more than available
    assert s.messages[0]["role"] == "system"


def test_undo_preserves_pinned():
    s = _make_session()
    s.messages = [
        _msg("system", "sys"),
        _msg("assistant", "pinned", _pinned=True),
        _msg("user", "q"),
        _msg("assistant", "a"),
    ]
    s.undo(1)
    assert any(m.get("_pinned") for m in s.messages)


def test_undo_empty_returns_zero():
    s = _make_session()
    s.messages = [_msg("system", "sys")]
    removed, text = s.undo(1)
    assert removed == 0
    assert text == ""


# ══════════════════════════════════════════════════════════
# AgentSession._extract_calls (Hybrid XML/JSON parser)
# ══════════════════════════════════════════════════════════

def test_extract_calls_xml_full():
    s = _make_session()
    text = '<call name="run_shell"><command>ls -la</command></call>'
    calls = s._extract_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "run_shell"
    assert calls[0]["args"]["command"] == "ls -la"
    assert calls[0]["_source"] == "xml"


def test_extract_calls_xml_multiline():
    s = _make_session()
    text = '<call name="write_file">\n<path>test.py</path>\n<content>print("hi")\n</content>\n</call>'
    calls = s._extract_calls(text)
    assert len(calls) == 1
    assert calls[0]["args"]["path"] == "test.py"
    assert "print" in calls[0]["args"]["content"]


def test_extract_calls_xml_type_coercion():
    s = _make_session()
    text = '<call name="run_code"><timeout>30</timeout><code>x=1</code></call>'
    calls = s._extract_calls(text)
    assert calls[0]["args"]["timeout"] == 30  # int, not str
    assert calls[0]["args"]["code"] == "x=1"


def test_extract_calls_xml_bool_coercion():
    s = _make_session()
    text = '<call name="run_code"><use_venv>true</use_venv></call>'
    calls = s._extract_calls(text)
    assert calls[0]["args"]["use_venv"] is True


def test_extract_calls_json_fallback():
    s = _make_session()
    import json
    text = '<tool_call>' + json.dumps({"name": "list_dir", "arguments": {"path": "/tmp"}}) + '</tool_call>'
    calls = s._extract_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "list_dir"
    assert calls[0]["_source"] == "json"


def test_extract_calls_empty():
    s = _make_session()
    assert s._extract_calls("plain text no calls") == []


def test_extract_calls_multiple_xml():
    s = _make_session()
    text = (
        '<call name="read_file"><path>a.py</path></call>'
        '<call name="run_shell"><command>echo hi</command></call>'
    )
    calls = s._extract_calls(text)
    assert len(calls) == 2
    assert {c["name"] for c in calls} == {"read_file", "run_shell"}
