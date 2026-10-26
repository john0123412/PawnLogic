"""When a ``<plan>`` in the stream opens a plan block, and when it is just text.

The renderer used to open a plan at ANY ``<plan>``.  An answer that explained
the plan protocol -- quoting ``<plan>`` inside a code block, mid-line -- was
rendered as a plan from that point on: a "[plan start]" line appeared in the
middle of the answer, and the rest of the answer was printed dim gray, as plan
text, indistinguishable from the thinking stream, because no ``</plan>`` ever
followed.  The 421 stored replies that contain ``<plan>`` fix the rule: a real
plan opens outside code, at the start of a line or directly followed by a plan
sub-tag; a quoted one is inside code or mid-line in prose.
"""

from __future__ import annotations

import pytest

from core.plan_renderer import _PlanRenderer

PLAN_START = "[plan start]"

# The reply that exposed the bug, abridged: it explains the plan protocol.
QUOTED_IN_FENCE = (
    "**Plan-as-Key architecture** (`session.py` header):\n"
    "```\n"
    "user input → <plan>(intent+tool+reason) → tool call\n"
    "        ↓\n"
    "  read-only tools exempt\n"
    "```\n"
    "\n"
    "Anything else you want to explore?\n"
)
QUOTED_INLINE = "1. **Plan first**: before any task I output a short plan (`<plan>`) first.\n"
QUOTED_IN_PROSE = "The model writes a <plan> tag before calling a tool.\n"

REAL_AT_START = "<plan>\n  <intent>List the project files.</intent>\n</plan>\n"
REAL_AFTER_TEXT = "I will analyse the code.\n\n<plan>\n### Phase 1: Recon\n<action>run checksec</action>\n</plan>\n"
REAL_MID_LINE = "The page loaded; taking a screenshot:<plan><intent>Save a screenshot.</intent></plan>"


def _render(text: str, chunk: int) -> tuple[str, str]:
    """Feed ``text`` in ``chunk``-sized pieces; return (answer text, plan display)."""
    import io
    import sys

    captured = io.StringIO()
    original = sys.stdout
    sys.stdout = captured
    try:
        renderer = _PlanRenderer()
        out = "".join(renderer.feed(text[i : i + chunk]) for i in range(0, len(text), chunk))
        out += renderer.flush()
    finally:
        sys.stdout = original
    return out, captured.getvalue()


@pytest.mark.parametrize("chunk", [1, 2, 3, 7, 10_000])
@pytest.mark.parametrize(
    "text",
    [QUOTED_IN_FENCE, QUOTED_INLINE, QUOTED_IN_PROSE],
    ids=["code-fence", "inline-code", "prose"],
)
def test_a_quoted_plan_tag_is_answer_text(text: str, chunk: int) -> None:
    answer, display = _render(text, chunk)

    assert answer == text
    assert PLAN_START not in display


@pytest.mark.parametrize("chunk", [1, 2, 3, 7, 10_000])
@pytest.mark.parametrize(
    "text",
    [REAL_AT_START, REAL_AFTER_TEXT, REAL_MID_LINE],
    ids=["reply-start", "line-start-after-text", "mid-line-with-subtag"],
)
def test_a_real_plan_block_is_rendered_as_a_plan(text: str, chunk: int) -> None:
    answer, display = _render(text, chunk)

    assert PLAN_START in display
    assert "<plan>" not in answer
    assert "<intent>" not in answer and "<action>" not in answer


@pytest.mark.parametrize("chunk", [1, 3, 10_000])
def test_a_plan_after_a_closed_code_fence_is_still_a_plan(chunk: int) -> None:
    text = "Example:\n```\n<plan>quoted</plan>\n```\n<plan>\n  <intent>Act.</intent>\n</plan>\n"

    answer, display = _render(text, chunk)

    assert display.count(PLAN_START) == 1
    assert "<plan>quoted</plan>" in answer


def test_an_undecided_plan_tag_at_the_end_of_the_stream_is_answer_text() -> None:
    renderer = _PlanRenderer()

    out = renderer.feed("see the <plan>")
    out += renderer.flush()

    assert out == "see the <plan>"


def test_flush_resets_code_fence_state_for_the_next_stream() -> None:
    renderer = _PlanRenderer()
    renderer.feed("```\nunterminated fence\n")
    renderer.flush()

    out = renderer.feed("<plan>\n<intent>Act.</intent>\n</plan>\n")

    assert "<plan>" not in out
