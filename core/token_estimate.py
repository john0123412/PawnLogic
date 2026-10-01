"""Dependency-free token estimation for context budgeting.

Context budgets are denominated in estimated tokens because a character
budget drifts 3-4x with content language (English/code is roughly 4 chars
per token while CJK prose is roughly 1 token per char), so the same
character limit means a very different share of the model window depending
on what the session looks like.

This module is a deliberately conservative heuristic, not a tokenizer: it
slightly overestimates CJK and punctuation-heavy text so compaction fires a
little early rather than after the provider rejects an over-window request.
It must stay dependency-free and deterministic — it runs on every request
build, including tests and offline tooling.
"""

from __future__ import annotations

_CHARS_PER_TOKEN_ASCII = 4

# Modern BPE tokenizers emit roughly one token per character across these
# ranges: CJK radicals/kana/unified ideographs, Hangul syllables, CJK
# compatibility ideographs, and fullwidth/halfwidth forms.
_CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x2E80, 0x9FFF),
    (0xAC00, 0xD7AF),
    (0xF900, 0xFAFF),
    (0xFF00, 0xFFEF),
)


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return any(start <= code <= end for start, end in _CJK_RANGES)


def estimate_tokens(text: str) -> int:
    """Estimate the token count of one text blob.

    CJK characters count as one token each; everything else counts as one
    token per four characters (rounded up). Empty input estimates to zero.
    """
    if not text:
        return 0
    cjk = 0
    other = 0
    for char in text:
        if _is_cjk(char):
            cjk += 1
        else:
            other += 1
    return cjk + (other + _CHARS_PER_TOKEN_ASCII - 1) // _CHARS_PER_TOKEN_ASCII
