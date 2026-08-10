"""
core/skill_tui.py — Interactive TUI for Skill Pack Management.

Checklist interface: space to toggle, search, bulk select/clear, save/cancel.
Reuses prompt_toolkit patterns from core/provider_tui.py.
"""

from __future__ import annotations

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import StyleAndTextTuples

from core.skill_manager import SkillScanner, _canonical_skill_name

_PAGE = 20

TUI_STYLE = Style.from_dict(
    {
        "title": "#00afff bold",
        "subtitle": "#888888",
        "cursor": "#00ff00 bold",
        "checked": "#00d700",
        "unchecked": "#888888",
        "search-focus": "#00afff",
        "search-normal": "#888888",
        "btn-focus": "#00ff00 bold",
        "btn-normal": "#888888",
        "status-key": "#00afff bold",
        "status": "#888888",
        "warning": "#ffaf00",
        "error": "#ff5555",
        "info": "#5fafd7",
    }
)


class SkillPackTUI:
    """Interactive checklist for enabling/disabling skill packs."""

    def __init__(self, scanner: SkillScanner) -> None:
        self._scanner = scanner
        self._all_packs = scanner.scan_all(include_disabled=True)
        # Working copy of enabled set (canonical folder keys).
        enabled = scanner._read_enabled()
        if enabled is None:
            self._selected: set[str] = {
                _canonical_skill_name(p.get("_folder", "")) for p in self._all_packs
            }
        else:
            self._selected = set(enabled)
        self._cursor = 0
        self._viewport = 0
        self._search = ""
        self._search_focus = False
        self._saved = False
        self._app: Application | None = None

    # ── filtering ──────────────────────────────────────────────────────────

    def _filtered(self) -> list[tuple[int, dict]]:
        """Return (original_index, pack) tuples matching search."""
        if not self._search:
            return [(i, p) for i, p in enumerate(self._all_packs)]
        q = self._search.lower()
        return [
            (i, p)
            for i, p in enumerate(self._all_packs)
            if q in p.get("name", "").lower()
            or q in p.get("_folder", "").lower()
            or q in p.get("description", "").lower()
        ]

    def _folder_key(self, pack: dict) -> str:
        return _canonical_skill_name(pack.get("_folder", ""))

    # ── render ─────────────────────────────────────────────────────────────

    def _render(self) -> StyleAndTextTuples:
        filtered = self._filtered()
        total = len(filtered)
        f: StyleAndTextTuples = [
            ("class:title", "\n  📦 Skill Pack Manager\n"),
            (
                "class:subtitle",
                f"  {len(self._all_packs)} packs total. "
                f"Toggle with Space, save with Enter.\n\n",
            ),
        ]

        # Search bar
        sb_cls = "class:search-focus" if self._search_focus else "class:search-normal"
        cursor_char = "▌" if self._search_focus else ""
        f.append((sb_cls, f"  🔍 Search: {self._search}{cursor_char}\n\n"))

        # List
        start = self._viewport
        end = min(start + _PAGE, total)
        for idx in range(start, end):
            _, pack = filtered[idx]
            key = self._folder_key(pack)
            checked = "✓" if key in self._selected else " "
            cur = "▶" if idx == self._cursor and not self._search_focus else " "
            name = pack.get("name", "?")
            folder = pack.get("_folder", "")
            desc = pack.get("description", "")[:40]
            chk_cls = "class:checked" if checked == "✓" else "class:unchecked"
            row_cls = (
                "class:cursor" if idx == self._cursor and not self._search_focus else ""
            )
            f.append((row_cls, f"  {cur} "))
            f.append((chk_cls, f"[{checked}]"))
            f.append((row_cls, f" {name}"))
            if folder and folder != name:
                f.append(("class:subtitle", f" ({folder})"))
            if desc:
                f.append(("class:subtitle", f" — {desc}"))
            f.append(("", "\n"))

        if total > _PAGE:
            f.append(("class:subtitle", f"\n  Showing {start+1}-{end} of {total}\n"))

        # Count
        sel_count = sum(1 for _, p in filtered if self._folder_key(p) in self._selected)
        f.append(("", f"\n  {sel_count}/{total} enabled\n\n"))

        # Buttons
        btn_total = total
        save_cls = (
            "class:btn-focus"
            if self._cursor == btn_total and not self._search_focus
            else "class:btn-normal"
        )
        cancel_cls = (
            "class:btn-focus"
            if self._cursor == btn_total + 1 and not self._search_focus
            else "class:btn-normal"
        )
        f.append((save_cls, "  [ Save & Close ]  "))
        f.append((cancel_cls, "[ Cancel ]\n"))

        return f

    def _render_status(self) -> StyleAndTextTuples:
        return [
            ("class:status-key", " ↑↓ "),
            ("class:status", "Move  "),
            ("class:status-key", "Space "),
            ("class:status", "Toggle  "),
            ("class:status-key", "/ "),
            ("class:status", "Search  "),
            ("class:status-key", "A "),
            ("class:status", "All  "),
            ("class:status-key", "C "),
            ("class:status", "Clear  "),
            ("class:status-key", "I "),
            ("class:status", "Invert  "),
            ("class:status-key", "Enter "),
            ("class:status", "Confirm  "),
            ("class:status-key", "Esc "),
            ("class:status", "Cancel  "),
        ]

    # ── key bindings ───────────────────────────────────────────────────────

    def _build_kb(self) -> KeyBindings:
        kb = KeyBindings()

        def inv():
            if self._app:
                self._app.invalidate()

        filtered_len = lambda: len(self._filtered())
        btn_base = filtered_len

        # Search mode
        _searching = Condition(lambda: self._search_focus)

        @kb.add("escape", filter=_searching)
        def _search_esc(e):
            self._search_focus = False
            self._search = ""
            self._cursor = 0
            self._viewport = 0
            inv()

        @kb.add("enter", filter=_searching)
        def _search_enter(e):
            self._search_focus = False
            self._cursor = 0
            self._viewport = 0
            inv()

        # List mode
        _listing = Condition(lambda: not self._search_focus)

        @kb.add("up", filter=_listing)
        @kb.add("k", filter=_listing)
        def _up(e):
            total = btn_base() + 2  # +2 for buttons
            if total > 0:
                self._cursor = (self._cursor - 1) % total
                self._ensure_viewport()
            inv()

        @kb.add("down", filter=_listing)
        @kb.add("j", filter=_listing)
        def _down(e):
            total = btn_base() + 2
            if total > 0:
                self._cursor = (self._cursor + 1) % total
                self._ensure_viewport()
            inv()

        @kb.add("pageup", filter=_listing)
        def _pgup(e):
            self._cursor = max(0, self._cursor - _PAGE)
            self._ensure_viewport()
            inv()

        @kb.add("pagedown", filter=_listing)
        def _pgdn(e):
            total = btn_base() + 2
            self._cursor = min(total - 1, self._cursor + _PAGE)
            self._ensure_viewport()
            inv()

        @kb.add("space", filter=_listing)
        def _space(e):
            filtered = self._filtered()
            if self._cursor < len(filtered):
                _, pack = filtered[self._cursor]
                key = self._folder_key(pack)
                if key in self._selected:
                    self._selected.discard(key)
                else:
                    self._selected.add(key)
            inv()

        @kb.add("enter", filter=_listing)
        def _enter(e):
            filtered = self._filtered()
            total = len(filtered)
            if self._cursor < total:
                # Toggle current item
                _, pack = filtered[self._cursor]
                key = self._folder_key(pack)
                if key in self._selected:
                    self._selected.discard(key)
                else:
                    self._selected.add(key)
                inv()
                return
            if self._cursor == total:
                # Save & Close
                self._save_and_exit()
                return
            if self._cursor == total + 1:
                # Cancel
                self._saved = False
                if self._app:
                    self._app.exit()

        @kb.add("a", filter=_listing)
        @kb.add("A", filter=_listing)
        def _select_all(e):
            for _, p in self._filtered():
                self._selected.add(self._folder_key(p))
            inv()

        @kb.add("c", filter=_listing)
        @kb.add("C", filter=_listing)
        def _clear_all(e):
            for _, p in self._filtered():
                self._selected.discard(self._folder_key(p))
            inv()

        @kb.add("i", filter=_listing)
        @kb.add("I", filter=_listing)
        def _invert(e):
            for _, p in self._filtered():
                key = self._folder_key(p)
                if key in self._selected:
                    self._selected.discard(key)
                else:
                    self._selected.add(key)
            inv()

        @kb.add("/", filter=_listing)
        def _to_search(e):
            self._search_focus = True
            inv()

        @kb.add("escape", filter=_listing)
        def _esc(e):
            self._saved = False
            if self._app:
                self._app.exit()

        return kb

    def _ensure_viewport(self) -> None:
        if self._cursor < self._viewport:
            self._viewport = self._cursor
        elif self._cursor >= self._viewport + _PAGE:
            self._viewport = self._cursor - _PAGE + 1

    def _save_and_exit(self) -> None:
        self._scanner._write_enabled(self._selected)
        self._scanner.invalidate_cache()
        self._saved = True
        if self._app:
            self._app.exit()

    # ── run ────────────────────────────────────────────────────────────────

    def run(self) -> bool:
        """Run the TUI. Returns True if changes were saved."""
        body = FormattedTextControl(self._render)
        status = FormattedTextControl(self._render_status)

        root = HSplit(
            [
                Window(content=body, always_hide_cursor=True),
                Window(content=status, height=1),
            ]
        )

        self._app = Application(
            layout=Layout(root),
            key_bindings=self._build_kb(),
            style=TUI_STYLE,
            full_screen=False,
            mouse_support=False,
        )
        self._app.run()
        return self._saved


def run_skill_tui(scanner: SkillScanner) -> bool:
    """Launch the skill pack TUI. Returns True if saved."""
    tui = SkillPackTUI(scanner)
    return tui.run()
