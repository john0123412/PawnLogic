"""The streaming repetition guard: when it trips and when it must not."""

from __future__ import annotations

import pytest

from core.stream_repetition import (
    MAX_LINE_REPEATS,
    StreamRepetitionGuard,
    guard_enabled,
)

LOOP_LINE = "I'll write a comprehensive analysis of the source code now.\n"


def _feed_all(text: str, *, chunk: int = 1000) -> StreamRepetitionGuard:
    guard = StreamRepetitionGuard()
    for i in range(0, len(text), chunk):
        if guard.feed(text[i : i + chunk]):
            break
    return guard


def test_a_sentence_repeated_until_max_tokens_trips_the_guard() -> None:
    guard = StreamRepetitionGuard()
    tripped_at = None
    for n in range(1, 60):
        if guard.feed(LOOP_LINE):
            tripped_at = n
            break
    assert tripped_at == MAX_LINE_REPEATS


@pytest.mark.parametrize("chunk", [1, 3, 17, 500])
def test_detection_is_independent_of_chunk_boundaries(chunk: int) -> None:
    guard = _feed_all(LOOP_LINE * 52, chunk=chunk)
    assert guard.tripped


def test_once_tripped_it_stays_tripped_and_ignores_more_text() -> None:
    guard = _feed_all(LOOP_LINE * 52)
    assert guard.tripped
    assert guard.feed("something completely different\n") is False
    assert guard.tripped


# --- must NOT trip on legitimate text -------------------------------------


def test_short_repeated_lines_do_not_trip() -> None:
    # Blank lines, rules, table separators, bullets, braces.
    noise = "\n---\n| --- | --- |\n- ok\n}\n" * 40
    assert not _feed_all(noise).tripped


def test_a_markdown_table_does_not_trip() -> None:
    table = "| name | role | file |\n| ---- | ---- | ---- |\n"
    table += "".join(
        f"| field_{i} | does something distinct number {i} | src/mod_{i}.py |\n"
        for i in range(60)
    )
    assert not _feed_all(table).tripped


def test_a_long_distinct_explanation_does_not_trip() -> None:
    prose = "".join(
        f"Paragraph {i}: this sentence explains a different idea than the last one, "
        f"with its own concrete detail about component number {i}.\n"
        for i in range(200)
    )
    assert not _feed_all(prose).tripped


def test_a_refrain_used_a_few_times_does_not_trip() -> None:
    body = ""
    for i in range(MAX_LINE_REPEATS - 1):
        body += "In summary, the key takeaway here is worth repeating clearly.\n"
        body += f"But first, here is distinct supporting point number {i} for it.\n"
    assert not _feed_all(body).tripped


def test_a_single_newline_free_run_trips_only_past_the_hard_cap() -> None:
    guard = StreamRepetitionGuard()
    assert not guard.feed("x" * 10_000)
    assert guard.feed("x" * 11_000)


def test_guard_enabled_respects_the_env_kill_switch(monkeypatch) -> None:
    monkeypatch.setenv("PAWNLOGIC_STREAM_LOOP_GUARD", "0")
    assert guard_enabled() is False
    monkeypatch.setenv("PAWNLOGIC_STREAM_LOOP_GUARD", "1")
    assert guard_enabled() is True
    monkeypatch.delenv("PAWNLOGIC_STREAM_LOOP_GUARD", raising=False)
    assert guard_enabled() is True


def test_rotating_filler_trips_on_the_window_ratio_before_any_line_hits_the_count() -> None:
    """A loop that cycles through several filler lines, none reaching the count.

    With 12 distinct lines cycled, no single line reaches MAX_LINE_REPEATS (6)
    before line 61, so a trip before then can only be the window-ratio signal.
    """
    cycle = [f"Filler sentence number {i} that is long enough to count here.\n" for i in range(12)]
    guard = StreamRepetitionGuard()
    fed = 0
    for i in range(600):
        fed += 1
        if guard.feed(cycle[i % len(cycle)]):
            break
    assert guard.tripped
    assert fed < 61  # before any of the 12 lines could reach its 6th occurrence
