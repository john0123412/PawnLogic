"""Tests for the provider wizard's row layout.

The row indices used to be positional magic in two modules at once. Adding the
Auth row shifted every index after Format, and the shift has to be right in
five separate places: the focus cycle, the widget-to-row maps, the dropdown
cursors, the save unpacking, and the form renderer. A one-off shift is
invisible in a two-row test and wrong on screen.

These tests pin the layout as data, so a row is added once.
"""

from __future__ import annotations

import pytest

from core import provider_tui_rows as rows
from core.provider_formats import (
    AUTH_LABELS,
    AUTH_SCHEMES,
    FORMAT_LABELS,
    FORMAT_VALUES,
)

# ── the layout itself ────────────────────────────────────────────


def test_rows_are_ordered_name_url_format_auth_key_save() -> None:
    assert rows.ROW_NAME == 0
    assert rows.ROW_URL == 1
    assert rows.ROW_FORMAT == 2
    assert rows.ROW_AUTH == 3
    assert rows.ROW_KEY == 4
    assert rows.ROW_SAVE == 5


def test_labels_line_up_with_row_indices() -> None:
    assert len(rows.WIZ_LABELS) == rows.ROW_SAVE
    assert rows.WIZ_LABELS[rows.ROW_NAME] == "Name"
    assert rows.WIZ_LABELS[rows.ROW_URL] == "Base URL"
    assert rows.WIZ_LABELS[rows.ROW_FORMAT] == "Format"
    assert rows.WIZ_LABELS[rows.ROW_AUTH] == "Auth"
    assert rows.WIZ_LABELS[rows.ROW_KEY] == "API Key"


def test_default_fields_have_one_entry_per_row() -> None:
    fields = rows.default_wiz_fields()
    assert len(fields) == len(rows.WIZ_LABELS)
    assert fields[rows.ROW_NAME] == ""
    assert fields[rows.ROW_URL] == ""
    assert fields[rows.ROW_FORMAT] == "openai"
    # The default must reproduce pre-change behaviour exactly: auto resolves to
    # each protocol's own historical scheme.
    assert fields[rows.ROW_AUTH] == "auto"
    assert fields[rows.ROW_KEY] == ""


def test_default_fields_returns_a_fresh_list_each_call() -> None:
    first = rows.default_wiz_fields()
    first[rows.ROW_NAME] = "mutated"
    assert rows.default_wiz_fields()[rows.ROW_NAME] == ""


# ── dropdowns are generated from the registry ─────────────────────


def test_format_dropdown_lists_every_registered_format() -> None:
    assert rows.row_options(rows.ROW_FORMAT) == FORMAT_VALUES
    assert len(FORMAT_VALUES) == 3


def test_auth_dropdown_lists_every_auth_scheme() -> None:
    assert rows.row_options(rows.ROW_AUTH) == AUTH_SCHEMES


def test_dropdown_labels_match_their_values_in_order() -> None:
    assert rows.dropdown_values(rows.ROW_AUTH) == [
        AUTH_LABELS[value] for value in AUTH_SCHEMES
    ]
    assert rows.dropdown_values(rows.ROW_FORMAT) == list(FORMAT_LABELS)


def test_text_rows_have_widgets_and_dropdown_rows_do_not() -> None:
    for row in range(rows.ROW_SAVE):
        if row in rows.DROPDOWN_ROWS:
            assert rows.input_slot_for_row(row) is None
        else:
            assert rows.input_slot_for_row(row) is not None


def test_text_slots_are_distinct() -> None:
    slots = list(rows.TEXT_INPUT_SLOTS.values())
    assert len(set(slots)) == len(slots)


# ── cursor <-> value round trip ───────────────────────────────────


@pytest.mark.parametrize("value", FORMAT_VALUES)
def test_format_cursor_round_trips(value: str) -> None:
    cursor = rows.cursor_for_value(rows.ROW_FORMAT, value)
    assert rows.set_from_cursor(rows.ROW_FORMAT, cursor) == value


@pytest.mark.parametrize("value", AUTH_SCHEMES)
def test_auth_cursor_round_trips(value: str) -> None:
    cursor = rows.cursor_for_value(rows.ROW_AUTH, value)
    assert rows.set_from_cursor(rows.ROW_AUTH, cursor) == value


def test_an_unknown_stored_value_falls_back_to_the_first_option() -> None:
    # A config written by a newer build must still open in the editor.
    assert rows.cursor_for_value(rows.ROW_FORMAT, "gemini") == 0
    assert rows.cursor_for_value(rows.ROW_AUTH, "oauth") == 0


def test_cursor_past_the_end_wraps_rather_than_raising() -> None:
    assert rows.set_from_cursor(rows.ROW_AUTH, len(AUTH_SCHEMES)) == AUTH_SCHEMES[0]


# ── display ───────────────────────────────────────────────────────


def test_each_format_row_shows_its_own_label() -> None:
    # The old renderer collapsed the row with a two-way ternary, so a third
    # format displayed as "OpenAI Compatible".
    seen = {
        rows.display_value(rows.ROW_FORMAT, value, editing=False)
        for value in FORMAT_VALUES
    }
    assert seen == set(FORMAT_LABELS)


def test_each_auth_row_shows_its_own_label() -> None:
    seen = {
        rows.display_value(rows.ROW_AUTH, value, editing=False)
        for value in AUTH_SCHEMES
    }
    assert len(seen) == len(AUTH_SCHEMES)


def test_auth_row_shows_the_auto_recommendation_first() -> None:
    assert (
        rows.display_value(rows.ROW_AUTH, "auto", editing=False) == AUTH_LABELS["auto"]
    )


def test_key_row_masks_in_add_and_says_unchanged_in_edit() -> None:
    assert rows.display_value(rows.ROW_KEY, "sk-secret", editing=False) == "•" * len(
        "sk-secret"
    )
    assert rows.display_value(rows.ROW_KEY, "sk-secret", editing=True).startswith(
        "unchanged"
    )


def test_name_and_url_rows_show_their_raw_value() -> None:
    assert rows.display_value(rows.ROW_NAME, "acme", editing=False) == "acme"
    assert (
        rows.display_value(rows.ROW_URL, "https://x/v1", editing=True) == "https://x/v1"
    )


# ── focus cycle ───────────────────────────────────────────────────


def test_add_mode_cycles_through_every_row_including_save() -> None:
    assert rows.focus_cycle(editing=False) == [0, 1, 2, 3, 4, 5]


def test_edit_mode_locks_name_and_key_out_of_the_cycle() -> None:
    cycle = rows.focus_cycle(editing=True)
    assert rows.ROW_NAME not in cycle
    assert rows.ROW_KEY not in cycle
    assert rows.ROW_SAVE in cycle
    assert rows.ROW_AUTH in cycle


def test_edit_cycle_is_still_ordered() -> None:
    cycle = rows.focus_cycle(editing=True)
    assert cycle == sorted(cycle)


# ── widget <-> row syncing ────────────────────────────────────────


class _FakeTextArea:
    def __init__(self, text: str) -> None:
        self.text = text


def test_sync_writes_each_text_row_from_its_own_widget() -> None:
    fields = rows.default_wiz_fields()
    rows.sync_fields_from_inputs(
        fields,
        [
            _FakeTextArea("  acme  "),
            _FakeTextArea(" https://x/v1 "),
            _FakeTextArea(" sk-key "),
        ],
    )
    assert fields[rows.ROW_NAME] == "acme"
    assert fields[rows.ROW_URL] == "https://x/v1"
    assert fields[rows.ROW_KEY] == "sk-key"


def test_sync_does_not_clobber_a_dropdown_row() -> None:
    # The widget list has three entries but the format/auth rows have no
    # widget; a positional zip would write widget contents into them.
    fields = rows.default_wiz_fields()
    fields[rows.ROW_FORMAT] = "responses"
    fields[rows.ROW_AUTH] = "bearer"
    rows.sync_fields_from_inputs(
        fields,
        [_FakeTextArea("acme"), _FakeTextArea("https://x/v1"), _FakeTextArea("sk-key")],
    )
    assert fields[rows.ROW_FORMAT] == "responses"
    assert fields[rows.ROW_AUTH] == "bearer"
