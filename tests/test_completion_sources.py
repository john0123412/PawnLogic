"""Tests for live CLI completion source merging."""

from pawnlogic.completion_sources import merge_completion_sources


def test_merge_completion_sources_keeps_inputs_and_adds_live_entries():
    words = ["/model", "/extension"]
    meta = {"/model": "models"}

    merged_words, merged_meta = merge_completion_sources(
        words,
        meta,
        command_provider=lambda: ["/planguard"],
        model_provider=lambda: {"fast": {"desc": "Fast model"}},
        extension_provider=lambda: {"security": "Extension (disabled)"},
    )

    assert words == ["/model", "/extension"]
    assert meta == {"/model": "models"}
    assert "/planguard" in merged_words
    assert "/model fast" in merged_words
    assert "/agent policy model allow fast" in merged_words
    assert "/agent policy model deny fast" in merged_words
    assert "/extension enable security" in merged_words
    assert "/extension disable security" in merged_words
    assert "/extension status security" in merged_words
    assert merged_meta["/model fast"] == "Fast model"
    assert merged_meta["/agent policy model allow fast"] == "Fast model"


def test_failing_dynamic_sources_are_ignored():
    def fail():
        raise RuntimeError("unavailable")

    assert merge_completion_sources(
        ["/help"],
        {},
        model_provider=fail,
        extension_provider=fail,
    ) == (["/help"], {})
