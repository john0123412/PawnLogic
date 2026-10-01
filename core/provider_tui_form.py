"""Rendering for the provider TUI's editable form and confirmation dialogs.

Split out of ``core.provider_tui`` purely to keep that module inside the
architecture budget ceiling for line count and branch complexity: the wizard,
its two editing modes, and the dialog stack are one visual concern and were
the largest remaining block.

The ``tui`` argument is the :class:`~core.provider_tui.ProviderTUI` instance.
It is typed ``Any`` on purpose — importing it would create a cycle, since
``core.provider_tui`` calls back into every function here. Only the
attributes listed in each function are used.
"""

from __future__ import annotations

from typing import Any

from prompt_toolkit.formatted_text import StyleAndTextTuples

from config.providers import is_provider_active
from core.provider_tui_rows import (
    ROW_SAVE,
    WIZ_LABELS,
    display_value,
    dropdown_values,
    focus_cycle,
    input_slot_for_row,
    locked_rows,
)

__all__ = [
    "detail_actions",
    "render_dialog",
    "render_status_wizard",
    "render_wizard",
    "wiz_focus_cycle",
]

#: Ornamented row markers, one per form row. Circled numerals keep the row
#: visually distinct from the dropdown option bullets below it.
_ROW_MARKS = "①②③④⑤"


def _row_mark(row: int) -> str:
    return _ROW_MARKS[row] if row < len(_ROW_MARKS) else str(row + 1)


def wiz_dropdown_cursor(state: Any, row: int) -> int:
    """Cursor position for a dropdown row, derived from its stored value."""
    from core.provider_tui_rows import cursor_for_value

    return cursor_for_value(row, state.wiz_fields[row])


def detail_actions(state: Any) -> list[str]:
    """The detail panel's action menu.

    Read by the renderer, the dispatcher, and the cursor bounds. These used to
    be two independent hardcoded lists: adding a row to one without shifting
    every index in the other made the highlighted row run a different action
    than the row it showed.
    """
    active = is_provider_active(state.detail_provider)
    return [
        "Update API Key",
        "Edit Provider",
        "Fetch / Sync Models",
        "Test Connection",
        "Manage Models",
        "Deactivate Provider" if active else "Activate Provider",
        "Delete Provider",
    ]


def wiz_focus_cycle(state: Any) -> list[int]:
    """Rows the arrow keys cycle through, in row order.

    Editing locks the name and the key, so those rows drop out of the cycle
    rather than swallowing keystrokes.
    """
    return focus_cycle(bool(state.wiz_edit))


def _wiz_locked(state: Any, row: int) -> bool:
    """Whether editing must not change this row.

    The name is locked because a rename is not atomic — it would have to
    re-point every model entry and the API key env var. The key is locked
    because it is never displayed, so it keeps its own Update API Key flow
    and its own security notice.
    """
    return bool(state.wiz_edit) and row in locked_rows(True)


def render_wizard(tui: Any) -> StyleAndTextTuples:
    """Draw the shared Add / Edit Provider form."""
    state = tui._state
    title = (
        f"\n  ✎ Edit Provider — {state.wiz_edit}\n\n"
        if state.wiz_edit
        else "\n  ✚ Add Provider\n\n"
    )
    f: StyleAndTextTuples = [("class:title", title)]
    tui._sync_wizard_fields_from_inputs()
    for row, label in enumerate(WIZ_LABELS):
        focused = (row == state.wiz_focus) and not _wiz_locked(state, row)
        s = "class:field-focus" if focused else "class:field-normal"
        display = display_value(row, state.wiz_fields[row], editing=bool(state.wiz_edit))
        is_open = bool(state.wiz_dropdowns.get(row))
        # The form is drawn by hand, so nothing else marks the caret. Show it
        # at the real buffer position, or the user cannot tell where the next
        # keystroke lands. Dropdown rows are not text fields, so they get the
        # row marker only.
        if focused and input_slot_for_row(row) is not None and not is_open:
            pos = tui._wiz_inputs[input_slot_for_row(row)].buffer.cursor_position
            pos = max(0, min(pos, len(display)))
            display = f"{display[:pos]}▌{display[pos:]}"
        f.append(
            (
                s,
                f"  {'▶' if focused else ' '}{_row_mark(row)} {label:<10} [ {display:<39} ]\n",
            )
        )
        if focused and is_open:
            cursor = state.wiz_dropdown_cursors.get(row, 0)
            for j, opt in enumerate(dropdown_values(row)):
                cur = "▶ " if j == cursor else "  "
                fs = "class:cursor" if j == cursor else "class:subtitle"
                f.append((fs, f"       {cur}{opt}\n"))
    f.append(("", "\n"))
    bs = "class:btn-focus" if state.wiz_focus == ROW_SAVE else "class:btn-normal"
    save = "Save Changes" if state.wiz_edit else "Save Provider"
    f.append(
        (bs, "  " + ("▶" if state.wiz_focus == ROW_SAVE else " ") + f" [ {save} ]\n\n")
    )
    if state.wiz_error:
        f.append(("class:error", f"  ✗ {state.wiz_error}\n"))
    if state.wiz_status:
        f.append((state.wiz_status_style, f"  {state.wiz_status}\n"))
    return f


def render_status_wizard() -> StyleAndTextTuples:
    return [
        ("class:status-key", " Tab "),
        ("class:status", "Next Field  "),
        ("class:status-key", "↑↓ "),
        ("class:status", "Move/Select  "),
        ("class:status-key", "Enter "),
        ("class:status", "Save  "),
        ("class:status-key", "Esc "),
        ("class:status", "Cancel "),
    ]


def focus_buttons(
    labels: list[str], focused_index: int, *, trailing_newline: bool = False
) -> StyleAndTextTuples:
    """Buttons, marking the focused one in text as well as colour.

    Colour was the only signal before, so the focused button disappeared
    whenever the terminal stripped colour or the output was piped — Enter then
    landed on whichever button the user could not see was selected. The model
    selector's three actions were still colour-only for the same reason.
    """
    out: StyleAndTextTuples = []
    last = len(labels) - 1
    for i, btn in enumerate(labels):
        focused = i == focused_index
        style = "class:btn-focus" if focused else "class:btn-normal"
        tail = "\n" if (trailing_newline and i == last) else "  "
        out.append((style, f"  {'▶' if focused else ' '} [ {btn} ]{tail}"))
    return out


def _dialog_buttons(state: Any, labels: list[str]) -> StyleAndTextTuples:
    return focus_buttons(labels, state.dialog_cursor)


def render_dialog(tui: Any) -> StyleAndTextTuples:
    state = tui._state
    if state.dialog == "security":
        f: StyleAndTextTuples = [
            ("class:dialog-title", "  ⚠  Security Notice\n\n"),
            (
                "class:dialog-body",
                "  Updating the API Key will clear the existing key.\n",
            ),
            ("class:dialog-body", "  You must paste the full key again.\n"),
            (
                "class:dialog-body",
                "  The key will never be displayed in plain text.\n\n",
            ),
        ]
        f += _dialog_buttons(state, ["Continue", "Cancel"])
    elif state.dialog == "delete":
        pname = state.detail_provider
        f = [
            ("class:dialog-title", "  🗑  Confirm Delete\n\n"),
            (
                "class:dialog-body",
                f"  Delete provider '{pname}'? This cannot be undone.\n\n",
            ),
        ]
        f += _dialog_buttons(state, ["Cancel", "Delete"])
    elif state.dialog == "save_anyway":
        f = [
            ("class:dialog-title", "  ⚠  Connection Failed\n\n"),
            ("class:dialog-body", "  Save provider anyway without testing?\n\n"),
        ]
        f += _dialog_buttons(state, ["No — Edit", "Yes — Save"])
    else:
        return []
    f.append(("", "\n"))
    return f
