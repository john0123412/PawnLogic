"""Tests for token estimation and context budget resolution."""

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.context_window import resolve_context_budget
from core.token_estimate import estimate_tokens


class TestEstimateTokens:
    def test_empty_input_is_zero(self):
        assert estimate_tokens("") == 0

    def test_ascii_runs_four_chars_per_token(self):
        # 8 ASCII chars -> ceil(8 / 4) = 2 tokens
        assert estimate_tokens("abcdefgh") == 2

    def test_ascii_remainder_rounds_up(self):
        # 5 ASCII chars -> ceil(5 / 4) = 2 tokens
        assert estimate_tokens("abcde") == 2

    def test_cjk_counts_one_token_per_char(self):
        # "\u4e0a\u4e0b\u6587\u7a97\u53e3" is a five-character CJK string.
        assert estimate_tokens("\u4e0a\u4e0b\u6587\u7a97\u53e3") == 5

    def test_mixed_text_combines_both_scales(self):
        # 5 CJK chars (5 tokens) + 8 ASCII chars (2 tokens)
        assert estimate_tokens("\u4e0a\u4e0b\u6587\u7a97\u53e3abcdefgh") == 7

    def test_monotonically_orders_languages_within_one_budget(self):
        # The estimator exists because a char budget drifts across languages:
        # the same char count must map to clearly different token counts.
        english = "a" * 300
        # "\u4e0a" is a single CJK ideograph.
        cjk = "\u4e0a" * 300
        assert estimate_tokens(english) < estimate_tokens(cjk)


class TestResolveContextBudget:
    def test_token_keys_are_authoritative(self):
        cfg = {
            "ctx_max_tokens": 48_000,
            "ctx_trim_tokens": 36_000,
            # Legacy keys must be ignored when token keys are present.
            "ctx_max_chars": 999_999,
            "ctx_trim_to": 999_999,
        }
        assert resolve_context_budget(cfg) == (48_000, 36_000)

    def test_legacy_char_keys_are_converted(self):
        cfg = {"ctx_max_chars": 150_000, "ctx_trim_to": 110_000}
        max_tokens, trim_tokens = resolve_context_budget(cfg)
        assert max_tokens == 50_000
        assert trim_tokens == 36_666

    def test_legacy_only_max_key_uses_default_trim(self):
        max_tokens, trim_tokens = resolve_context_budget({"ctx_max_chars": 90_000})
        assert max_tokens == 30_000
        assert trim_tokens == 30_000

    def test_trim_never_exceeds_max(self):
        cfg = {"ctx_max_tokens": 10_000, "ctx_trim_tokens": 99_999}
        assert resolve_context_budget(cfg) == (10_000, 10_000)

    def test_garbage_values_fall_back_to_medium_preset(self):
        # Both token keys present but unparseable -> medium-preset fallback.
        cfg = {"ctx_max_tokens": "not-a-number", "ctx_trim_tokens": 36_000}
        assert resolve_context_budget(cfg) == (48_000, 36_000)

    def test_null_token_keys_convert_legacy_char_keys(self):
        # A None token key is "absent", so the legacy conversion applies.
        cfg = {"ctx_max_tokens": None, "ctx_trim_tokens": None,
               "ctx_max_chars": 90_000}
        assert resolve_context_budget(cfg) == (30_000, 30_000)

    def test_partial_token_keys_fall_back_to_legacy_conversion(self):
        cfg = {"ctx_max_tokens": None, "ctx_trim_tokens": 36_000,
               "ctx_max_chars": 90_000}
        assert resolve_context_budget(cfg)[0] == 30_000

    def test_max_token_key_alone_does_not_hit_legacy_defaults(self):
        # Per-key resolution: an override of only ctx_max_tokens (the shape
        # hand-built configs pass to prompt_builder) keeps its value, and
        # the missing trim inherits the max budget.
        assert resolve_context_budget({"ctx_max_tokens": 128_000}) == (
            128_000,
            128_000,
        )
