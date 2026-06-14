"""Tests for stateless tool result processing helpers (Phase 1)."""

from core.tool_result import (
    DEFAULT_VERBOSE_TOOLS,
    REDUNDANT_PATTERNS,
    SHELL_ERROR_SIGNALS,
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
