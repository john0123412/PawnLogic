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
import time
import types
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
from tests.helpers import fake_stream_request, fake_stream_response, fake_stream_sequence  # noqa: E402

# Heavy dependencies that session.py imports at module level — mock them
# so we don't need a real DB, API key, or full environment.
_MOCKS = [
    "core.memory", "core.gsa", "core.logger",
    "core.skill_manager", "core.mcp_client_manager",
    "tools.web_ops", "tools.sandbox",
    "tools.pwn_chain", "tools.vision",
    "tools.docker_sandbox", "tools.browser_ops", "tools.recon_ops",
    "tools.delegate_tool",
]


class _StubModule(types.ModuleType):
    def __getattr__(self, name: str):
        value = MagicMock(name=f"{self.__name__}.{name}")
        setattr(self, name, value)
        return value


def _mockable_module(name: str):
    module = sys.modules.get(name)
    if module is None:
        module = _StubModule(name)
        module.__file__ = f"<test-stub:{name}>"
        sys.modules[name] = module
        return module
    if isinstance(module, MagicMock):
        return module
    return None

# Patch specific attributes session.py reads at import time
_mock_deps = {_m: _mockable_module(_m) for _m in _MOCKS}

if _mock_deps["core.memory"] is not None:
    _mock_deps["core.memory"]._gen_id = lambda: "test_session_id_abc123"
    _mock_deps["core.memory"].init_db = lambda: None
    _mock_deps["core.memory"].search_knowledge = lambda *a, **kw: []
    _mock_deps["core.memory"].format_knowledge_for_prompt = lambda *a, **kw: ""
    _mock_deps["core.memory"].update_session_naming = MagicMock()
    _mock_deps["core.memory"].write_failure = MagicMock()
    _mock_deps["core.memory"].check_failure = MagicMock(return_value=[])
    _mock_deps["core.memory"].count_failure = MagicMock(return_value=0)
    _mock_deps["core.memory"].format_failures_for_prompt = MagicMock(return_value="")
if _mock_deps["core.gsa"] is not None:
    _mock_deps["core.gsa"].load_relevant_skills = MagicMock(return_value=("", ""))
    _mock_deps["core.gsa"].bump_skill = MagicMock(return_value=(True, "ok"))
    _mock_deps["core.gsa"].sink_failure_to_gsa = MagicMock(return_value=(False, ""))
    _mock_deps["core.gsa"].load_toc = MagicMock(return_value="")
if _mock_deps["core.logger"] is not None:
    _mock_deps["core.logger"].logger = MagicMock()
    _mock_deps["core.logger"].audit_tool_call = MagicMock()
if _mock_deps["tools.web_ops"] is not None:
    _mock_deps["tools.web_ops"].WEB_SCHEMAS = []
if _mock_deps["tools.sandbox"] is not None:
    _mock_deps["tools.sandbox"].SANDBOX_SCHEMAS = []
if _mock_deps["tools.pwn_chain"] is not None:
    _mock_deps["tools.pwn_chain"].PWN_SCHEMAS = []
if _mock_deps["tools.vision"] is not None:
    _mock_deps["tools.vision"].VISION_SCHEMAS = []
if _mock_deps["tools.docker_sandbox"] is not None:
    _mock_deps["tools.docker_sandbox"].DOCKER_SCHEMAS = []
if _mock_deps["tools.browser_ops"] is not None:
    _mock_deps["tools.browser_ops"].BROWSER_SCHEMAS = []
if _mock_deps["tools.recon_ops"] is not None:
    _mock_deps["tools.recon_ops"].RECON_SCHEMAS = []

# Mock SkillScanner used at module level
if _mock_deps["core.skill_manager"] is not None:
    _mock_scanner = MagicMock()
    _mock_scanner.match.return_value = []
    _mock_scanner.format_for_prompt.return_value = ""
    _mock_scanner.format_user_message.return_value = ""
    _mock_deps["core.skill_manager"].SkillScanner = MagicMock(return_value=_mock_scanner)

# Now import the real session functions
from core.session import (  # noqa: E402
    AgentSession,
    TurnInterrupted,
    _ThinkingSpinner,
    _ctx_chars,
    _drop_dangling_tool_call_messages,
    _trim_and_compact_context,
    _is_plan_exempt,
    _tool_call_missing_plan,
    _PlanRenderer,
)

# core.session is now imported with its dependency stubs bound. Drop the
# core.mcp_client_manager stub from sys.modules so a test module collected after
# this one (e.g. test_mcp_config) imports the real implementation rather than
# inheriting a MagicMock. session.py only imports it lazily, so core.session's
# existing bindings are unaffected, and this module's own MCP test monkeypatches
# the real module.
if isinstance(sys.modules.get("core.mcp_client_manager"), _StubModule):
    del sys.modules["core.mcp_client_manager"]


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
    assert 'elif _plan_decision.action == "soft":' in source
    assert source.index('elif _plan_decision.action == "soft":') < source.index(
        "_plan_signal_injected = True"
    )


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
        from core.runtime_context import RuntimeContext
        s.runtime_context = RuntimeContext.for_test(
            cwd=s.cwd,
            workspace_dir=s.workspace_dir,
        )
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


def test_reset_system_prompt_delegates_to_prompt_builder(monkeypatch):
    import core.session as session_mod
    from core.prompt_builder import PromptBuildResult

    s = _make_session()
    s.messages = []
    s._loaded_skill_packs = [{"name": "old"}]

    captured = {}

    def fake_build_session_prompt(**kwargs):
        captured.update(kwargs)
        return PromptBuildResult(prompt="NEW PROMPT", loaded_skill_packs=[{"name": "new"}])

    monkeypatch.setattr(session_mod, "build_session_prompt", fake_build_session_prompt)

    s._reset_system_prompt("heap overflow")

    assert s.messages == [{"role": "system", "content": "NEW PROMPT"}]
    assert s._loaded_skill_packs == [{"name": "new"}]
    assert captured["cwd"] == s.cwd
    assert captured["current_phase"] == s.current_phase
    assert captured["model_alias"] == s.model_alias
    assert captured["model"] == s.model
    assert captured["urgent_mode"] is False
    assert captured["knowledge_query"] == "heap overflow"
    assert captured["agent_phases"] is session_mod.AGENT_PHASES
    assert captured["load_state_md"] is session_mod._load_state_md
    assert captured["load_skills_toc"] is session_mod._load_skills_toc
    assert captured["skill_scanner"] is session_mod._skill_scanner


def test_reset_system_prompt_keeps_loaded_packs_when_builder_does_not_update(monkeypatch):
    import core.session as session_mod
    from core.prompt_builder import PromptBuildResult

    s = _make_session()
    s.messages = [{"role": "system", "content": "OLD PROMPT"}]
    s._loaded_skill_packs = [{"name": "old"}]

    monkeypatch.setattr(
        session_mod,
        "build_session_prompt",
        lambda **_kwargs: PromptBuildResult(prompt="UPDATED PROMPT", loaded_skill_packs=None),
    )

    s._reset_system_prompt()

    assert s.messages == [{"role": "system", "content": "UPDATED PROMPT"}]
    assert s._loaded_skill_packs == [{"name": "old"}]


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

    s, session_mod = _prepare_run_turn_session(monkeypatch)
    monkeypatch.setitem(session_mod.TOOL_MAP, "write_file", lambda _args: "OK: fake write")

    monkeypatch.setattr(
        session_mod,
        "stream_request",
        fake_stream_sequence(
            ({
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
            },),
            ({
                "choices": [{"delta": {"content": "done"}}],
            },),
        ),
    )

    s.run_turn("write a file")

    assert any(
        m.get("role") == "user" and "PLAN_MISSING" in str(m.get("content", ""))
        for m in s.messages
    )


def _tool_call_response(name, args=None, *, call_id="call_tool", include_plan=True):
    import json

    events = []
    if include_plan:
        events.append({"choices": [{"delta": {"content": "<plan><intent>run tool</intent></plan>"}}]})
    events.append({
        "choices": [{
            "delta": {
                "tool_calls": [{
                    "index": 0,
                    "id": call_id,
                    "function": {
                        "name": name,
                        "arguments": json.dumps(args or {}),
                    },
                }],
            },
        }],
    })
    return tuple(events)


def _assistant_done_response(text="done"):
    return ({"choices": [{"delta": {"content": text}}]},)


def test_run_turn_unknown_tool_appends_error_tool_result(monkeypatch):
    s, session_mod = _prepare_run_turn_session(monkeypatch)
    audit_tool_call = MagicMock()
    monkeypatch.setattr(session_mod, "audit_tool_call", audit_tool_call)

    monkeypatch.setattr(
        session_mod,
        "stream_request",
        fake_stream_sequence(
            _tool_call_response("pytest_unknown_tool", {"value": 1}, call_id="call_unknown"),
            _assistant_done_response(),
        ),
    )

    s.run_turn("use unknown tool")

    tool_msg = next(m for m in s.messages if m.get("role") == "tool")
    assert tool_msg["tool_call_id"] == "call_unknown"
    assert tool_msg["content"] == "ERROR: Unknown tool 'pytest_unknown_tool'"
    audit_tool_call.assert_called()
    assert audit_tool_call.call_args.kwargs["tool_name"] == "pytest_unknown_tool"
    assert audit_tool_call.call_args.kwargs["success"] is False


def test_run_turn_tool_exception_appends_error_result(monkeypatch):
    s, session_mod = _prepare_run_turn_session(monkeypatch)
    monkeypatch.setattr(session_mod._runtime_state, "user_mode", False)

    def broken_tool(_args):
        raise ValueError("bad tool args")

    session_mod._TOOL_REGISTRY.register("pytest_broken_tool", broken_tool)
    try:
        monkeypatch.setattr(
            session_mod,
            "stream_request",
            fake_stream_sequence(
                _tool_call_response("pytest_broken_tool", {"x": 1}, call_id="call_broken"),
                _assistant_done_response(),
            ),
        )

        s.run_turn("run broken tool")
    finally:
        session_mod._TOOL_REGISTRY.unregister("pytest_broken_tool")

    tool_msg = next(m for m in s.messages if m.get("role") == "tool")
    assert tool_msg["tool_call_id"] == "call_broken"
    assert tool_msg["content"] == "ERROR: ValueError: bad tool args"


def test_run_turn_switch_phase_updates_phase_and_refreshes_prompt(monkeypatch):
    s, session_mod = _prepare_run_turn_session(monkeypatch)
    assert "EXPLOIT" in session_mod.AGENT_PHASES

    monkeypatch.setattr(
        session_mod,
        "stream_request",
        fake_stream_sequence(
            _tool_call_response(
                "switch_phase",
                {"phase": "EXPLOIT", "reason": "need exploit tools"},
                call_id="call_switch",
            ),
            _assistant_done_response(),
        ),
    )

    s.run_turn("switch phase")

    assert s.current_phase == "EXPLOIT"
    s._reset_system_prompt.assert_called()
    tool_msg = next(m for m in s.messages if m.get("role") == "tool")
    assert "[Phase Switch] RECON" in tool_msg["content"]
    assert "EXPLOIT" in tool_msg["content"]
    assert "need exploit tools" in tool_msg["content"]


def test_run_turn_audited_tool_prefaces_failure_warning(monkeypatch):
    s, session_mod = _prepare_run_turn_session(monkeypatch)
    check_failure = MagicMock(return_value=[{"id": 1, "error_type": "Timeout"}])
    format_failures_for_prompt = MagicMock(return_value="PREVIOUS FAILURE WARNING")
    monkeypatch.setattr(session_mod, "check_failure", check_failure)
    monkeypatch.setattr(session_mod, "format_failures_for_prompt", format_failures_for_prompt)
    monkeypatch.setitem(session_mod.TOOL_MAP, "run_shell", lambda _args: "OK: shell")
    monkeypatch.setattr(
        session_mod,
        "stream_request",
        fake_stream_sequence(
            _tool_call_response("run_shell", {"command": "echo ok"}, call_id="call_shell"),
            _assistant_done_response(),
        ),
    )

    s.run_turn("run shell with audit warning")

    tool_msg = next(m for m in s.messages if m.get("role") == "tool")
    assert "OK: shell" in tool_msg["content"]
    assert "PREVIOUS FAILURE WARNING" in tool_msg["content"]
    check_failure.assert_called_once()
    assert check_failure.call_args.args[0] == "run_shell"


def test_run_turn_audited_tool_failure_records_failure(monkeypatch):
    s, session_mod = _prepare_run_turn_session(monkeypatch)
    write_failure = MagicMock(return_value=123)
    audit_tool_call = MagicMock()
    monkeypatch.setattr(session_mod, "check_failure", MagicMock(return_value=[]))
    monkeypatch.setattr(session_mod, "write_failure", write_failure)
    monkeypatch.setattr(session_mod, "count_failure", MagicMock(return_value=1))
    monkeypatch.setattr(session_mod, "audit_tool_call", audit_tool_call)
    monkeypatch.setitem(
        session_mod.TOOL_MAP,
        "run_shell",
        lambda _args: "ERROR: PermissionError: denied",
    )
    monkeypatch.setattr(
        session_mod,
        "stream_request",
        fake_stream_sequence(
            _tool_call_response("run_shell", {"command": "./target"}, call_id="call_fail"),
            _assistant_done_response(),
        ),
    )

    s.run_turn("run failing shell")

    write_failure.assert_called_once()
    assert write_failure.call_args.kwargs["tool_name"] == "run_shell"
    assert write_failure.call_args.kwargs["error_type"] == "Permission"
    assert audit_tool_call.call_args.kwargs["success"] is False


def test_run_turn_tool_keyboard_interrupt_raises_for_cli_rollback(monkeypatch):
    s, session_mod = _prepare_run_turn_session(monkeypatch)

    def interrupted_tool(_args):
        raise KeyboardInterrupt

    session_mod._TOOL_REGISTRY.register("pytest_interrupt_tool", interrupted_tool)
    try:
        monkeypatch.setattr(
            session_mod,
            "stream_request",
            fake_stream_request(*_tool_call_response("pytest_interrupt_tool", call_id="call_interrupt")),
        )

        with pytest.raises(TurnInterrupted):
            s.run_turn("interrupt during tool")
    finally:
        session_mod._TOOL_REGISTRY.unregister("pytest_interrupt_tool")

    s._autosave.assert_called()
    assert any(
        m.get("role") == "assistant"
        and m.get("tool_calls")
        and m["tool_calls"][0]["id"] == "call_interrupt"
        for m in s.messages
    )
    assert not any(m.get("role") == "tool" and m.get("tool_call_id") == "call_interrupt" for m in s.messages)


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
    monkeypatch.setattr(
        session_mod,
        "stream_request",
        fake_stream_request(
            {"choices": []},
            {"choices": [{
                "delta": {"content": "older turns summarized"},
            }]},
        ),
    )
    warning_mock = MagicMock()
    monkeypatch.setattr(session_mod.logger, "warning", warning_mock)

    s._maybe_update_summary(s.messages, current_turn_count=3)

    assert s._history_summary == "older turns summarized"
    warning_mock.assert_not_called()


def test_run_turn_interrupt_raises_for_cli_rollback(monkeypatch):
    s, session_mod = _prepare_run_turn_session(monkeypatch)

    def interrupted_stream(*_args, **_kwargs):
        raise KeyboardInterrupt
        yield  # pragma: no cover

    monkeypatch.setattr(session_mod, "stream_request", interrupted_stream)

    with pytest.raises(TurnInterrupted):
        s.run_turn("interrupt me")

    assert s.messages[-1]["role"] == "user"
    assert s.messages[-1]["content"] == "interrupt me"


def test_autoname_thread_swallows_keyboard_interrupt(monkeypatch):
    s = _make_session()
    import core.session as session_mod

    s._turn_count = 2
    s._naming_lock = threading.Lock()
    warning_mock = MagicMock()
    started = threading.Event()

    def interrupted_name(**_kwargs):
        started.set()
        raise KeyboardInterrupt

    monkeypatch.setattr(session_mod, "should_name_session", lambda _msgs: True)
    monkeypatch.setattr(session_mod, "pick_naming_model", lambda alias: alias)
    monkeypatch.setattr(session_mod, "generate_session_name", interrupted_name)
    monkeypatch.setattr(session_mod.logger, "warning", warning_mock)

    s._maybe_autoname([{"role": "user", "content": "please solve this"}])

    assert started.wait(timeout=1.0)
    for _ in range(100):
        if not s._naming_lock.locked():
            break
        time.sleep(0.01)

    assert not s._naming_lock.locked()
    warning_mock.assert_called()
    assert "Auto naming interrupted" in warning_mock.call_args.args[0]


def _prepare_run_turn_session(monkeypatch):
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
    return s, session_mod


def test_run_turn_starts_and_stops_thinking_spinner(monkeypatch):
    s, session_mod = _prepare_run_turn_session(monkeypatch)

    starts = []
    stops = []

    class FakeSpinner:
        def __init__(self, enabled, label="Thinking"):
            starts.append(("init", enabled, label))

        def start(self):
            starts.append(("start",))

        def stop(self):
            stops.append(("stop",))

    monkeypatch.setattr(session_mod, "_ThinkingSpinner", FakeSpinner)
    monkeypatch.setattr(
        session_mod,
        "stream_request",
        fake_stream_request({"choices": [{"delta": {"content": "done"}}]}),
    )

    s.run_turn("show spinner")

    assert ("init", True, "Thinking") in starts
    assert ("start",) in starts
    assert stops


def test_user_mode_reasoning_keeps_spinner_until_visible_output(monkeypatch):
    s, session_mod = _prepare_run_turn_session(monkeypatch)

    events = []

    class FakeSpinner:
        def __init__(self, enabled, label="Thinking"):
            events.append(("init", enabled, label))

        def start(self):
            events.append(("start",))

        def stop(self):
            events.append(("stop",))

    def fake_stream_request(*_args, **_kwargs):
        events.append(("yield", "usage"))
        yield {"_usage": {"prompt_tokens": 1, "completion_tokens": 0}}
        events.append(("yield", "reasoning"))
        yield {"choices": [{"delta": {"reasoning_content": "hidden thought"}}]}
        events.append(("yield", "content"))
        yield {"choices": [{"delta": {"content": "done"}}]}

    monkeypatch.setattr(session_mod, "_ThinkingSpinner", FakeSpinner)
    monkeypatch.setattr(session_mod, "stream_request", fake_stream_request)

    s.run_turn("keep spinner while reasoning")

    assert ("init", True, "Thinking") in events
    assert events.index(("yield", "usage")) < events.index(("yield", "reasoning"))
    assert events.index(("yield", "reasoning")) < events.index(("yield", "content"))
    assert ("stop",) not in events[:events.index(("yield", "content"))]
    assert ("stop",) in events[events.index(("yield", "content")):]


def test_usage_and_reasoning_only_response_retries_until_visible_output(monkeypatch):
    s, session_mod = _prepare_run_turn_session(monkeypatch)
    calls = []

    def fake_stream_request(*_args, **_kwargs):
        calls.append("call")
        if len(calls) == 1:
            return fake_stream_response(
                {"_usage": {"prompt_tokens": 1, "completion_tokens": 12}},
                {"choices": [{"delta": {"reasoning_content": "hidden only"}}]},
            )
        return fake_stream_response(
            {"choices": [{"delta": {"content": "visible answer"}}]},
        )

    monkeypatch.setattr(session_mod, "stream_request", fake_stream_request)
    monkeypatch.setattr(session_mod.time, "sleep", lambda _seconds: None)

    s.run_turn("retry empty visible response")

    assert len(calls) == 2
    assert s.messages[-1]["role"] == "assistant"
    assert s.messages[-1]["content"] == "visible answer"


def test_run_turn_prints_api_retry_notice_before_final_output(monkeypatch, capsys):
    s, session_mod = _prepare_run_turn_session(monkeypatch)

    monkeypatch.setattr(
        session_mod,
        "stream_request",
        fake_stream_request(
            {"_retry": "HTTP 502 Bad Gateway: provider gateway failed. Retrying in 0.1s (1/3)."},
            {"choices": [{"delta": {"content": "visible answer"}}]},
        ),
    )

    s.run_turn("retry notice")

    out = capsys.readouterr().out
    assert "HTTP 502" in out
    assert "Retrying" in out
    assert "visible answer" in out


@pytest.mark.parametrize("status", [403, 502])
def test_run_turn_api_error_terminates_turn_without_hanging(monkeypatch, capsys, status):
    s, session_mod = _prepare_run_turn_session(monkeypatch)

    monkeypatch.setattr(
        session_mod,
        "stream_request",
        fake_stream_request({"_error": f"HTTP {status} provider error"}),
    )

    s.run_turn("provider failure")

    out = capsys.readouterr().out
    assert f"HTTP {status}" in out
    assert s.messages == [{"role": "system", "content": "sys"}]


def test_run_turn_accepts_message_content_in_stream_choice(monkeypatch):
    s, session_mod = _prepare_run_turn_session(monkeypatch)

    monkeypatch.setattr(
        session_mod,
        "stream_request",
        fake_stream_request({
            "_usage": {"prompt_tokens": 1, "completion_tokens": 5},
            "choices": [{"message": {"content": "message fallback answer"}}],
        }),
    )

    s.run_turn("provider sends message content")

    assert s.messages[-1]["role"] == "assistant"
    assert s.messages[-1]["content"] == "message fallback answer"


def test_thinking_spinner_can_be_disabled_for_non_tty(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    spinner = _ThinkingSpinner(enabled=True)
    spinner.start()
    spinner.stop()
    assert spinner._thread is None


def test_thinking_spinner_stop_is_idempotent_after_clearing(monkeypatch):
    writes = []

    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "write", lambda text: writes.append(text))
    monkeypatch.setattr(sys.stdout, "flush", lambda: None)

    spinner = _ThinkingSpinner(enabled=True)
    spinner._printed = True
    spinner._thread = MagicMock()

    spinner.stop()
    spinner.stop()

    clear_writes = [text for text in writes if text.startswith("\r")]
    assert len(clear_writes) == 1


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


def test_tool_registry_snapshot_and_unregister():
    import core.session as session_mod

    session_mod._TOOL_REGISTRY.register(
        "pytest_tool",
        lambda _args: "ok",
        {"type": "function", "function": {"name": "pytest_tool", "parameters": {"type": "object"}}},
    )
    try:
        tool_map = session_mod._tool_map_snapshot()
        schemas = session_mod._tool_schema_snapshot()
        assert tool_map["pytest_tool"]({})
        assert any(s.get("function", {}).get("name") == "pytest_tool" for s in schemas)
    finally:
        session_mod._TOOL_REGISTRY.unregister("pytest_tool")


def test_delegate_schema_reader_uses_registry_snapshot():
    import importlib
    sys.modules.pop("tools.delegate_tool", None)
    delegate_tool = importlib.import_module("tools.delegate_tool")
    import core.session as session_mod

    session_mod._TOOL_REGISTRY.register(
        "pytest_schema_tool",
        lambda _args: "ok",
        {"type": "function", "function": {"name": "pytest_schema_tool", "parameters": {"type": "object"}}},
    )
    try:
        assert "pytest_schema_tool" in delegate_tool._tool_map()
        assert any(
            s.get("function", {}).get("name") == "pytest_schema_tool"
            for s in delegate_tool._tools_schema()
        )
    finally:
        session_mod._TOOL_REGISTRY.unregister("pytest_schema_tool")


def test_tool_registry_skips_empty_name_and_schema_only_handler():
    import core.session as session_mod

    empty_schema = {"type": "function", "function": {"name": "", "parameters": {"type": "object"}}}
    schema_only = {
        "type": "function",
        "function": {"name": "pytest_schema_only_tool", "parameters": {"type": "object"}},
    }

    session_mod._TOOL_REGISTRY.register("", lambda _args: "bad", empty_schema)
    session_mod._TOOL_REGISTRY.register("pytest_schema_only_tool", None, schema_only)
    try:
        tool_map = session_mod._tool_map_snapshot()
        schemas = session_mod._tool_schema_snapshot()

        assert "" not in tool_map
        assert not any(s.get("function", {}).get("name") == "" for s in schemas)
        assert "pytest_schema_only_tool" not in tool_map
        assert any(s.get("function", {}).get("name") == "pytest_schema_only_tool" for s in schemas)
    finally:
        session_mod._TOOL_REGISTRY.unregister("pytest_schema_only_tool")
        session_mod._refresh_legacy_tool_globals()


def test_attach_external_mcp_tools_skips_empty_schema_and_refreshes_legacy_globals(monkeypatch):
    import core.session as session_mod
    import core.mcp_client_manager as mcp_mod
    from config import AGENT_PHASES

    handler = lambda _args: "mcp ok"

    class FakeManager:
        def build_pawnlogic_handlers(self):
            return {"pytest_mcp_tool": handler}

        def build_pawnlogic_schemas(self):
            return [
                {"type": "function", "function": {"name": "", "parameters": {"type": "object"}}},
                {
                    "type": "function",
                    "function": {"name": "pytest_mcp_tool", "parameters": {"type": "object"}},
                },
            ]

        def get_phase_mapping(self):
            return {"pytest_mcp_tool": "GENERAL"}

    monkeypatch.setattr(mcp_mod, "init_external_mcp", lambda: FakeManager())
    before_general = list(AGENT_PHASES.get("GENERAL", []))
    try:
        session_mod.attach_external_mcp_tools()

        assert session_mod._tool_map_snapshot()["pytest_mcp_tool"]({}) == "mcp ok"
        assert "pytest_mcp_tool" in session_mod.TOOL_MAP
        assert any(s.get("function", {}).get("name") == "pytest_mcp_tool" for s in session_mod.TOOLS_SCHEMA)
        assert "" not in session_mod._tool_map_snapshot()
        assert not any(s.get("function", {}).get("name") == "" for s in session_mod._tool_schema_snapshot())
        assert "pytest_mcp_tool" in AGENT_PHASES["GENERAL"]
    finally:
        session_mod._TOOL_REGISTRY.unregister("pytest_mcp_tool")
        session_mod._refresh_legacy_tool_globals()
        AGENT_PHASES["GENERAL"] = before_general


def _load_real_sandbox_module():
    import importlib
    import tools

    sys.modules.pop("tools.sandbox", None)
    if hasattr(tools, "sandbox"):
        delattr(tools, "sandbox")
    return importlib.import_module("tools.sandbox")


def test_sandbox_timeout_kills_process_group_before_parent(monkeypatch, tmp_path):
    sandbox = _load_real_sandbox_module()
    calls = []

    class FakeProc:
        pid = 12345

        def communicate(self, input=None, timeout=None):
            if timeout is not None:
                raise sandbox.subprocess.TimeoutExpired(cmd="fake", timeout=timeout)
            calls.append("communicate_after_timeout")
            return b"", None

        def kill(self):
            calls.append("kill")

    monkeypatch.setattr(sandbox.subprocess, "Popen", lambda *args, **kwargs: FakeProc())
    monkeypatch.setattr(sandbox.os, "killpg", lambda pid, sig: calls.append(("killpg", pid, sig)))

    out, rc = sandbox._run_limited(["fake"], timeout=1, cwd=str(tmp_path))

    assert out == "[execution timed out after 1s]"
    assert rc == 1
    assert ("killpg", 12345, sandbox.signal.SIGKILL) in calls
    assert "kill" not in calls


def test_sandbox_timeout_falls_back_to_parent_kill(monkeypatch, tmp_path):
    sandbox = _load_real_sandbox_module()
    calls = []

    class FakeProc:
        pid = 12345

        def communicate(self, input=None, timeout=None):
            if timeout is not None:
                raise sandbox.subprocess.TimeoutExpired(cmd="fake", timeout=timeout)
            calls.append("communicate_after_timeout")
            return b"", None

        def kill(self):
            calls.append("kill")

    def fail_killpg(_pid, _sig):
        calls.append("killpg")
        raise OSError

    monkeypatch.setattr(sandbox.subprocess, "Popen", lambda *args, **kwargs: FakeProc())
    monkeypatch.setattr(sandbox.os, "killpg", fail_killpg)

    out, rc = sandbox._run_limited(["fake"], timeout=1, cwd=str(tmp_path))

    assert out == "[execution timed out after 1s]"
    assert rc == 1
    assert calls.count("killpg") == 1
    assert calls.count("kill") == 1
