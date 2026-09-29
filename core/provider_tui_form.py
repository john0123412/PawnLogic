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

__all__ = [
    "detail_actions",
    "render_dialog",
    "render_status_wizard",
    "render_wizard",
    "wiz_focus_cycle",
]

# Row indices of the shared add/edit form: Name, Base URL, Format, API Key,
# then the save button.
_ROW_NAME, _ROW_URL, _ROW_FORMAT, _ROW_KEY, _ROW_SAVE = 0, 1, 2, 3, 4
# Rows that only the "add a new provider" mode may change.
_ADD_ONLY_ROWS = (_ROW_NAME, _ROW_KEY)
_FORMATS = ("OpenAI Compatible", "Anthropic Compatible")


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
    if state.wiz_edit:
        return [i for i in range(5) if i not in _ADD_ONLY_ROWS]
    return list(range(5))


def _wiz_locked(state: Any, row: int) -> bool:
    """Whether editing must not change this row.

    The name is locked because a rename is not atomic — it would have to
    re-point every model entry and the API key env var. The key is locked
    because it is never displayed, so it keeps its own Update API Key flow
    and its own security notice.
    """
    return bool(state.wiz_edit) and row in _ADD_ONLY_ROWS


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
    for i, label in enumerate(["Name", "Base URL", "Format", "API Key"]):
        focused = (i == state.wiz_focus) and not _wiz_locked(state, i)
        s = "class:field-focus" if focused else "class:field-normal"
        val = state.wiz_fields[i]
        if i == _ROW_KEY:
            if state.wiz_edit:
                display = "unchanged — use Update API Key"
            else:
                display = "•" * len(val) if val else ""
        elif i == _ROW_FORMAT:
            display = "Anthropic Compatible" if val == "anthropic" else _FORMATS[0]
        else:
            display = val
        # The form is drawn by hand, so nothing else marks the caret. Show it
        # at the real buffer position, or the user cannot tell where the next
        # keystroke lands. Format is a dropdown, not a text field, so it gets
        # the row marker only.
        if focused and i in (_ROW_NAME, _ROW_URL, _ROW_KEY) and not state.wiz_fmt_open:
            pos = tui._wiz_inputs[
                {_ROW_NAME: 0, _ROW_URL: 1, _ROW_KEY: 2}[i]
            ].buffer.cursor_position
            pos = max(0, min(pos, len(display)))
            display = f"{display[:pos]}▌{display[pos:]}"
        f.append(
            (
                s,
                f"  {'▶' if focused else ' '}{'①②③④'[i]} {label:<10} [ {display:<39} ]\n",
            )
        )
        if i == _ROW_FORMAT and focused and state.wiz_fmt_open:
            for j, opt in enumerate(_FORMATS):
                cur = "▶ " if j == state.wiz_fmt_cursor else "  "
                fs = "class:cursor" if j == state.wiz_fmt_cursor else "class:subtitle"
                f.append((fs, f"       {cur}{opt}\n"))
    f.append(("", "\n"))
    bs = "class:btn-focus" if state.wiz_focus == _ROW_SAVE else "class:btn-normal"
    save = "Save Changes" if state.wiz_edit else "Save Provider"
    f.append(
        (bs, "  " + ("▶" if state.wiz_focus == _ROW_SAVE else " ") + f" [ {save} ]\n\n")
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


def _dialog_buttons(state: Any, labels: list[str]) -> StyleAndTextTuples:
    """Dialog buttons, marking the focused one in text as well as colour.

    Colour was the only signal before, so the focused button disappeared
    whenever the terminal stripped colour or the output was piped — Enter then
    landed on whichever button the user could not see was selected.
    """
    out: StyleAndTextTuples = []
    for i, btn in enumerate(labels):
        focused = i == state.dialog_cursor
        style = "class:btn-focus" if focused else "class:btn-normal"
        out.append((style, f"  {'▶' if focused else ' '} [ {btn} ]  "))
    return out


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
