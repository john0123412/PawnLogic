"""Tests for tool result processing helpers and the per-turn processor."""

from core.tool_result import (
    DEFAULT_VERBOSE_TOOLS,
    REDUNDANT_PATTERNS,
    SHELL_ERROR_SIGNALS,
    AntiLoopInjection,
    ProcessedToolResult,
    ToolAuditEvent,
    ToolResultNotice,
    ToolResultProcessor,
    build_anti_code_loop_message,
    build_anti_loop_message,
    build_directory_intuition_hint,
    compact_redundant_tool_error_messages,
    detect_shell_error_signal,
    output_signature,
    truncate_tool_output,
)

# ── truncate_tool_output ─────────────────────────────────────────────


def test_truncate_keeps_short_non_verbose_output_unchanged():
    text = "line\n" * 5
    out = truncate_tool_output(
        text, tool_name="list_dir", user_mode=False, max_chars=1000
    )
    assert out == text


def test_truncate_hard_truncates_long_non_verbose_output():
    text = "x" * 5000
    out = truncate_tool_output(
        text, tool_name="list_dir", user_mode=False, max_chars=1000
    )
    assert "[truncated to 1000 chars]" in out
    assert out.startswith("x" * 500)
    assert out.endswith("x" * 250)


def test_truncate_verbose_tool_uses_smart_head_tail():
    text = "\n".join(f"line{i}" for i in range(200))
    out = truncate_tool_output(
        text, tool_name="run_shell", user_mode=False, max_chars=1000
    )
    assert "lines truncated for token efficiency" in out
    assert out.startswith("line0")
    assert out.endswith("line199")


def test_truncate_user_mode_uses_smart_head_tail_even_for_non_verbose():
    text = "\n".join(f"line{i}" for i in range(200))
    out = truncate_tool_output(
        text, tool_name="list_dir", user_mode=True, max_chars=1000
    )
    assert "lines truncated for token efficiency" in out


def test_default_verbose_tools_contains_expected_members():
    assert "run_shell" in DEFAULT_VERBOSE_TOOLS
    assert "read_file" in DEFAULT_VERBOSE_TOOLS
    assert "list_dir" not in DEFAULT_VERBOSE_TOOLS


# ── output_signature ─────────────────────────────────────────────────


def test_output_signature_is_stable_and_short():
    sig = output_signature("hello world")
    assert sig == output_signature("hello world")
    assert len(sig) == 12


def test_output_signature_ignores_content_past_500_chars():
    base = "a" * 500
    assert output_signature(base + "tail-one") == output_signature(base + "tail-two")


def test_output_signature_distinguishes_different_prefixes():
    assert output_signature("alpha") != output_signature("beta")


def test_output_signature_accepts_non_string():
    assert output_signature(12345) == output_signature("12345")


# ── detect_shell_error_signal ────────────────────────────────────────


def test_detect_shell_error_returns_first_match_in_order():
    # Both "ERROR:" and "command not found" present; "ERROR:" ranks first.
    assert detect_shell_error_signal("ERROR: command not found") == "ERROR:"


def test_detect_shell_error_matches_later_signal():
    assert (
        detect_shell_error_signal("bash: foo: command not found") == "command not found"
    )


def test_detect_shell_error_returns_empty_when_clean():
    assert detect_shell_error_signal("all good") == ""


def test_detect_shell_error_signal_order_is_preserved():
    assert SHELL_ERROR_SIGNALS[0] == "ERROR:"


# ── build_directory_intuition_hint ───────────────────────────────────


def test_directory_hint_includes_count_and_auto_result():
    out = build_directory_intuition_hint(3, "\n[auto] found something")
    assert "run 3 consecutive times" in out
    assert out.endswith("[auto] found something")
    assert "/chat find" in out


def test_directory_hint_without_auto_result():
    out = build_directory_intuition_hint(5)
    assert "run 5 consecutive times" in out


# ── compact_redundant_tool_error_messages ────────────────────────────


def _tool_msg(content: str) -> dict:
    return {"role": "tool", "tool_call_id": "x", "content": content}


def test_compact_collapses_repeats_beyond_threshold():
    messages = [{"role": "system", "content": "sys"}]
    # Five identical short errors; first 3 stay, occurrences > 3 get compacted.
    for _ in range(5):
        messages.append(_tool_msg("cat: foo: No such file or directory"))

    compacted = compact_redundant_tool_error_messages(messages)

    assert compacted == 2
    rewritten = [m for m in messages if m["content"].startswith("(compacted:")]
    assert len(rewritten) == 2
    assert "similar errors have appeared" in rewritten[0]["content"]


def test_compact_leaves_threshold_or_fewer_untouched():
    messages = [{"role": "system", "content": "sys"}]
    for _ in range(3):
        messages.append(_tool_msg("Permission denied"))

    compacted = compact_redundant_tool_error_messages(messages)

    assert compacted == 0
    assert all(m["content"] == "Permission denied" for m in messages[1:])


def test_compact_ignores_long_output_and_non_tool_roles():
    long_err = "Permission denied " + "x" * 400  # >= 300 chars, not eligible
    messages = [{"role": "system", "content": "sys"}]
    for _ in range(5):
        messages.append(_tool_msg(long_err))
    messages.append({"role": "user", "content": "Permission denied"})

    compacted = compact_redundant_tool_error_messages(messages)

    assert compacted == 0


def test_compact_skips_system_message_even_if_it_matches():
    messages = [{"role": "system", "content": "Permission denied"}]
    for _ in range(5):
        messages.append(_tool_msg("Permission denied"))

    compact_redundant_tool_error_messages(messages)

    assert messages[0]["content"] == "Permission denied"


def test_redundant_patterns_first_entry_used_in_placeholder_count():
    assert REDUNDANT_PATTERNS[0] == "No such file or directory"


# ── ToolResultProcessor (Phase 2) ────────────────────────────────────

def _make_processor(search_result: str = "") -> ToolResultProcessor:
    return ToolResultProcessor(
        auto_intuitive_search=lambda query: search_result,
        session_label="testsess",
    )


def _process(
    proc: ToolResultProcessor,
    result: str,
    tool_name: str,
    *,
    fn_args: dict | None = None,
    audit_ok: bool = True,
    failure_warning: str = "",
    user_mode: bool = False,
    max_chars: int = 100_000,
    iteration: int = 0,
    elapsed_ms: int = 5,
    args_preview: str = "cmd",
) -> ProcessedToolResult:
    return proc.process(
        result=result,
        tool_name=tool_name,
        fn_args=fn_args or {},
        args_preview=args_preview,
        audit_ok=audit_ok,
        elapsed_ms=elapsed_ms,
        failure_warning=failure_warning,
        iteration=iteration,
        user_mode=user_mode,
        max_chars=max_chars,
    )


def test_process_appends_failure_warning_to_content():
    proc = _make_processor()
    out = _process(proc, "tool output", "read_file", failure_warning="HEADS UP")
    assert "tool output" in out.content
    assert out.content.endswith("HEADS UP")
    assert "\n\nHEADS UP" in out.content


def test_process_audit_event_fields_complete():
    proc = _make_processor()
    out = _process(
        proc, "ok", "read_file",
        audit_ok=True, elapsed_ms=42, iteration=7, args_preview="path='x'",
    )
    ev = out.audit_event
    assert isinstance(ev, ToolAuditEvent)
    assert ev.tool_name == "read_file"
    assert ev.args_summary == "path='x'"
    assert ev.elapsed_ms == 42
    assert ev.iteration == 7
    assert ev.success is True
    assert ev.result_len == len("ok")


def test_process_audit_result_len_is_pretruncation():
    proc = _make_processor()
    long_text = "x" * 5000
    out = _process(proc, long_text, "list_dir", max_chars=1000)
    # Audit records the pre-truncation length; content is truncated.
    assert out.audit_event.result_len == 5000
    assert len(out.content) < 5000


def test_process_audit_event_is_not_written_by_processor(capsys):
    # The processor has no audit_tool_call dependency; it only returns the event.
    proc = _make_processor()
    out = _process(proc, "ok", "read_file")
    assert out.audit_event is not None
    assert capsys.readouterr().out == ""


def test_directory_search_triggers_intuition_on_third():
    proc = _make_processor(search_result="\n[history hit]")
    fn_args = {"path": "/tmp/foo"}

    first = _process(proc, "listing", "list_dir", fn_args=fn_args)
    second = _process(proc, "listing", "list_dir", fn_args=fn_args)
    assert "consecutive times" not in first.content
    assert "consecutive times" not in second.content
    assert first.notices == []

    third = _process(proc, "listing", "list_dir", fn_args=fn_args)
    assert "directory search has run 3 consecutive times" in third.content
    assert third.content.endswith("[history hit]")
    assert any("Auto-Intuition" in n.message for n in third.notices)


def test_non_directory_tool_resets_directory_counter():
    proc = _make_processor(search_result="\n[hit]")
    fn_args = {"path": "/tmp/foo"}
    _process(proc, "listing", "list_dir", fn_args=fn_args)
    _process(proc, "listing", "list_dir", fn_args=fn_args)
    # A non-directory tool resets the streak.
    _process(proc, "done", "read_file")
    third = _process(proc, "listing", "list_dir", fn_args=fn_args)
    assert "consecutive times" not in third.content


def test_shell_error_triggers_anti_loop_injection_on_third():
    proc = _make_processor()
    fn_args = {"command": "cat missing"}

    for _ in range(2):
        _process(proc, "bash: No such file", "run_shell", fn_args=fn_args, audit_ok=False)
        assert proc.maybe_anti_loop_injection(0) is None

    _process(proc, "bash: No such file", "run_shell", fn_args=fn_args, audit_ok=False)
    injection = proc.maybe_anti_loop_injection(3)
    assert isinstance(injection, AntiLoopInjection)
    assert injection.injection == build_anti_loop_message(3)
    assert any(n.level == "debug" for n in injection.notices)


def test_anti_loop_injection_is_consumed_once():
    proc = _make_processor()
    fn_args = {"command": "cat missing"}
    for _ in range(3):
        _process(proc, "No such file", "run_shell", fn_args=fn_args, audit_ok=False)
    assert proc.maybe_anti_loop_injection(3) is not None
    # Count was reset on consumption; no second injection.
    assert proc.maybe_anti_loop_injection(4) is None


def test_shell_error_streak_breaks_on_different_error():
    proc = _make_processor()
    _process(proc, "No such file", "run_shell", fn_args={"command": "a"}, audit_ok=False)
    _process(proc, "No such file", "run_shell", fn_args={"command": "a"}, audit_ok=False)
    # Different command/error pair resets the consecutive counter.
    _process(proc, "Permission denied", "run_shell", fn_args={"command": "b"}, audit_ok=False)
    assert proc.maybe_anti_loop_injection(3) is None


def test_code_output_triggers_anti_code_loop_on_third():
    proc = _make_processor()
    first = _process(proc, "identical", "run_code")
    second = _process(proc, "identical", "run_code")
    assert first.injections == []
    assert second.injections == []

    third = _process(proc, "identical", "run_code")
    assert third.injections == [build_anti_code_loop_message(3)]
    assert any("Anti-Code-Loop" in n.message for n in third.notices)


def test_code_output_loop_resets_on_change():
    proc = _make_processor()
    _process(proc, "a", "run_code")
    _process(proc, "a", "run_code")
    third = _process(proc, "DIFFERENT", "run_code")
    assert third.injections == []


def test_process_notices_are_returned_not_printed(capsys):
    proc = _make_processor(search_result="\n[hit]")
    fn_args = {"path": "/tmp/foo"}
    for _ in range(3):
        out = _process(proc, "listing", "list_dir", fn_args=fn_args)
    # Notices are returned for the caller; the processor prints nothing.
    assert out.notices
    assert capsys.readouterr().out == ""


def test_reset_directory_counter_clears_streak():
    proc = _make_processor(search_result="\n[hit]")
    fn_args = {"path": "/tmp/foo"}
    _process(proc, "listing", "list_dir", fn_args=fn_args)
    _process(proc, "listing", "list_dir", fn_args=fn_args)
    proc.reset_directory_counter()
    third = _process(proc, "listing", "list_dir", fn_args=fn_args)
    assert "consecutive times" not in third.content


def test_notice_and_processed_result_defaults():
    notice = ToolResultNotice("always", "\033[93m", "hi")
    assert notice.level == "always"
    result = ProcessedToolResult(content="x")
    assert result.injections == []
    assert result.notices == []
    assert result.audit_event is None
