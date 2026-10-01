"""core/provider_tui_rows.py - The provider wizard's row layout.

The wizard's row indices were positional magic in two budgeted modules at
once: ``_ROW_FORMAT``/``_ROW_KEY``/``range(5)`` in ``core.provider_tui_form``
and bare ``2``, ``3``, ``4``, ``% 2`` in ``core.provider_tui``. Adding the Auth
row meant touching all of them, and the index shift that follows is exactly
the kind of edit that leaves one map pointing at the wrong widget -- invisible
in a two-row test, wrong on screen.

So the layout lives here, once. Both modules import the row constants and the
dropdown tables rather than restating them, and the dropdowns are generated
from ``core.provider_formats``, so a fourth protocol arrives with its menu
already wired instead of as a patch to six call sites.

Row order is the display order. ``wiz_fields`` is indexed by these constants,
never by literal.
"""

from __future__ import annotations

from typing import Any

from core.provider_formats import (
    AUTH_LABELS,
    AUTH_SCHEMES,
    FORMAT_LABELS,
    FORMAT_VALUES,
)

__all__ = [
    "ADD_ONLY_ROWS",
    "DROPDOWN_ROWS",
    "ROW_AUTH",
    "ROW_FORMAT",
    "ROW_KEY",
    "ROW_NAME",
    "ROW_SAVE",
    "ROW_URL",
    "TEXT_INPUT_SLOTS",
    "WIZ_FIELDS",
    "WIZ_LABELS",
    "cursor_for_value",
    "default_wiz_fields",
    "dropdown_values",
    "focus_cycle",
    "input_slot_for_row",
    "locked_rows",
    "menu_choice",
    "menu_lines",
    "menu_options",
    "menu_range",
    "panel_filter",
    "prompt_menu",
    "row_options",
    "set_from_cursor",
    "sync_fields_from_inputs",
]

ROW_NAME, ROW_URL, ROW_FORMAT, ROW_AUTH, ROW_KEY, ROW_SAVE = range(6)

WIZ_LABELS: tuple[str, ...] = (
    "Name",
    "Base URL",
    "Format",
    "Auth",
    "API Key",
)

#: Rows that only "add a new provider" may change.
ADD_ONLY_ROWS = (ROW_NAME, ROW_KEY)

#: Rows rendered as a dropdown rather than a text field, with their options.
DROPDOWN_ROWS: dict[int, tuple[str, ...]] = {
    ROW_FORMAT: FORMAT_VALUES,
    ROW_AUTH: AUTH_SCHEMES,
}

#: Text rows and which ``TextArea`` in ``ProviderTUI._wiz_inputs`` backs them.
#: The dropdown rows have no widget at all.
TEXT_INPUT_SLOTS: dict[int, int] = {
    ROW_NAME: 0,
    ROW_URL: 1,
    ROW_KEY: 2,
}

#: Initial ``wiz_fields`` contents, indexed by row constant.
WIZ_FIELDS: tuple[str, ...] = ("", "", "openai", "auto", "")


def default_wiz_fields() -> list[str]:
    return list(WIZ_FIELDS)


def locked_rows(editing: bool) -> tuple[int, ...]:
    """Rows the wizard must not change while editing an existing provider.

    Name and key are excluded from the focus cycle rather than validated on
    save: a row in the cycle but refused on save looks broken, and a locked
    row still in the cycle silently swallows keystrokes.
    """
    return ADD_ONLY_ROWS if editing else ()


def focus_cycle(editing: bool) -> list[int]:
    """Rows the arrow keys cycle through, in display order."""
    locked = set(locked_rows(editing))
    return [row for row in range(len(WIZ_LABELS) + 1) if row not in locked]


def input_slot_for_row(row: int) -> int | None:
    """Which ``_wiz_inputs`` index backs ``row``, or None for dropdowns."""
    return TEXT_INPUT_SLOTS.get(row)


def row_options(row: int) -> tuple[str, ...]:
    """The selectable values for a dropdown row."""
    return DROPDOWN_ROWS.get(row, ())


def dropdown_values(row: int) -> list[str]:
    """Human-readable option labels for a dropdown row."""
    if row == ROW_AUTH:
        return [AUTH_LABELS[value] for value in row_options(row)]
    return list(FORMAT_LABELS)


def cursor_for_value(row: int, value: str) -> int:
    """Index of ``value`` in the row's options, defaulting to the first.

    An unrecognized stored value lands on 0 rather than raising: a config
    written by a newer build must still open in the editor.
    """
    options = row_options(row)
    try:
        return options.index(value)
    except ValueError:
        return 0


def set_from_cursor(row: int, cursor: int) -> str:
    """The value a dropdown row takes when the user picks index ``cursor``."""
    options = row_options(row)
    if not options:
        return ""
    return options[cursor % len(options)]


def display_value(row: int, value: str, *, editing: bool) -> str:
    """What a row shows in the form, which is not always its stored value."""
    if row == ROW_KEY and editing:
        return "unchanged — use Update API Key"
    if row == ROW_KEY:
        return "•" * len(value) if value else ""
    if row in DROPDOWN_ROWS:
        cursor = cursor_for_value(row, value)
        return dropdown_values(row)[cursor]
    return value


def is_text_row(row: int) -> bool:
    return row in TEXT_INPUT_SLOTS


def sync_fields_from_inputs(fields: list[str], inputs: list[Any]) -> None:
    """Copy the live TextArea contents into ``fields``, by row not by index."""
    for row, slot in TEXT_INPUT_SLOTS.items():
        if slot < len(inputs):
            fields[row] = str(inputs[slot].text).strip()


# ── the numbered menus /provider add prints ───────────────────────
#
# The Format and Auth prompts are the same shape over two option lists, and both
# are generated from the registry so a fourth protocol cannot be unselectable
# outside the TUI. Keeping them here rather than inline in
# ``core/commands/provider.py`` also keeps that module off its complexity
# ceiling, which is where the third format's cost would otherwise land.


def menu_options(row: int) -> list[tuple[str, str]]:
    """``(number, label)`` pairs for a dropdown row, in selection order.

    Returned unrendered so the caller can colour the number and the label
    independently, which is what ``/provider add`` does.
    """
    return [
        (f"[{i}]", label) for i, label in enumerate(dropdown_values(row), start=1)
    ]


def menu_lines(row: int, *, indent: str = "    ") -> list[str]:
    """The numbered option lines for a dropdown row, in selection order."""
    return [
        f"{indent}{number} {label}" for number, label in menu_options(row)
    ]


def menu_range(row: int) -> str:
    """The ``[1-N]`` count shown in a menu prompt, so it tracks the registry."""
    return f"[1-{len(dropdown_values(row))}]"


def menu_choice(row: int, answer: str) -> str:
    """Map a typed answer onto a dropdown row's value.

    An empty answer means the first option, which is what the original
    hand-written ``[1/2]`` prompt did; anything unparseable or out of range
    raises ``ValueError`` so the caller can refuse rather than silently store
    a protocol the user did not pick.
    """
    options = row_options(row)
    index = (int(answer) if answer else 1) - 1
    if not 0 <= index < len(options):
        raise ValueError(f"Invalid selection: {answer}")
    return options[index]


def prompt_menu(
    ask: Any, row: int, *, write: Any = print, header: str = "",
    note: str = "", style: Any = None,
) -> str | None:
    """Print a registry-generated menu, read a choice, and resolve it.

    Returns ``None`` when the user aborts or types something out of range, so
    the caller can simply return; that keeps three copies of the same
    interrupt/parse guard out of the budgeted ``core/commands/provider.py``.

    ``write`` is the caller's printer -- ``core.commands.provider`` routes
    through a sink-aware ``_print``, not the builtin, so a plain ``print``
    would bypass headless capture.
    """
    if header:
        write(f"\n  {style(header) if style else header}")
    if note:
        write(f"  {style(note) if style else note}")
    for number, label in menu_options(row):
        write(f"    {style(number) if style else number} {label}")
    try:
        answer = ask(f"  Select {menu_range(row)}: ").strip()
    except (EOFError, KeyboardInterrupt):
        write("")
        return None
    try:
        return menu_choice(row, answer)
    except ValueError:
        return None


def panel_filter(tui: Any, predicate: Any = None) -> Any:
    """A Prompt Toolkit ``Condition`` for the wizard panel.

    The wizard's five key filters differ only in the row state they test, so
    the panel and dialog guards are stated once here. Building it here rather
    than inline in ``core/provider_tui.py`` keeps that budgeted module off its
    line ceiling, which is where a second dropdown row's filters would land.
    """
    from prompt_toolkit.filters import Condition

    test = predicate or (lambda: True)
    return Condition(
        lambda: tui._panel == "wizard" and not tui._dialog and test()
    )


def state_fields(state: Any) -> list[str]:
    return state.wiz_fields
