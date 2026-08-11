"""
core/skill_tui.py — Unified Interactive TUI for Skill Pack Management.

Single interface combining enable/disable, sync, rescan, and status display.
Launched via /skills. Replaces the separate /sp command surface.
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
        "msg-ok": "#00d700",
        "msg-err": "#ff5555",
    }
)


class SkillPackTUI:
    """Unified interactive TUI for skill pack management."""

    def __init__(self, scanner: SkillScanner) -> None:
        self._scanner = scanner
        self._all_packs = scanner.scan_all(include_disabled=True)
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
        self._msg = ""  # status message
        self._msg_style = ""  # style class for message
        self._app: Application | None = None

    # ── filtering ──────────────────────────────────────────────────────────

    def _filtered(self) -> list[tuple[int, dict]]:
        if not self._search:
            return [(i, p) for i, p in enumerate(self._all_packs)]
        q = self._search.lower()
        return [
            (i, p)
            for i, p in enumerate(self._all_packs)
            if q in p.get("name", "").lower()
            or q in p.get("_folder", "").lower()
            or q in p.get("description", "").lower()
            or q in p.get("_md_file", "").name.lower()
        ]

    def _folder_key(self, pack: dict) -> str:
        return _canonical_skill_name(pack.get("_folder", ""))

    # ── render ─────────────────────────────────────────────────────────────

    def _render(self) -> StyleAndTextTuples:
        filtered = self._filtered()
        total = len(filtered)
        enabled_count = sum(
            1 for _, p in filtered if self._folder_key(p) in self._selected
        )
        all_count = len(self._all_packs)

        f: StyleAndTextTuples = [
            ("class:title", "\n  Skill Pack Manager\n"),
            (
                "class:subtitle",
                f"  {all_count} packs  |  {enabled_count}/{total} enabled"
                f"{f'  |  filter: {self._search}' if self._search else ''}\n\n",
            ),
        ]

        # Search bar
        sb_cls = "class:search-focus" if self._search_focus else "class:search-normal"
        cur_ch = "▌" if self._search_focus else ""
        f.append((sb_cls, f"  Search: {self._search}{cur_ch}\n\n"))

        # Pack list
        start = self._viewport
        end = min(start + _PAGE, total)
        for idx in range(start, end):
            _, pack = filtered[idx]
            key = self._folder_key(pack)
            checked = "✓" if key in self._selected else " "
            cur = "▶" if idx == self._cursor and not self._search_focus else " "
            name = pack.get("name", "?")
            folder = pack.get("_folder", "")
            desc = pack.get("description", "")[:45]
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
            f.append(
                ("class:subtitle", f"\n  {start+1}-{end} of {total}  (PgUp/PgDn)\n")
            )

        # Message area
        if self._msg:
            f.append(("", "\n"))
            f.append((self._msg_style, f"  {self._msg}\n"))

        # Buttons
        btn_base = total
        names = ["Save", "Sync", "Rescan", "Cancel"]
        f.append(("", "\n"))
        for i, label in enumerate(names):
            cls = (
                "class:btn-focus"
                if self._cursor == btn_base + i and not self._search_focus
                else "class:btn-normal"
            )
            f.append((cls, f"  [ {label} ]"))
        f.append(("", "\n"))

        return f

    def _render_status(self) -> StyleAndTextTuples:
        return [
            ("class:status-key", " ↑↓jk "),
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
            ("class:status-key", "S "),
            ("class:status", "Sync  "),
            ("class:status-key", "R "),
            ("class:status", "Rescan  "),
            ("class:status-key", "Enter "),
            ("class:status", "OK  "),
            ("class:status-key", "Esc "),
            ("class:status", "Quit  "),
        ]

    # ── actions ────────────────────────────────────────────────────────────

    def _do_sync(self) -> None:
        results = self._scanner.sync_packs()
        if not results:
            self._msg = "No git-backed skill packs found"
            self._msg_style = "class:subtitle"
            return
        ok = sum(1 for r in results if r["status"] == "ok")
        err = len(results) - ok
        self._msg = f"Sync done: {ok} updated, {err} failed"
        self._msg_style = "class:msg-ok" if err == 0 else "class:msg-err"
        # Refresh pack list
        self._all_packs = self._scanner.scan_all(include_disabled=True)
        self._adjust_cursor()

    def _do_rescan(self) -> None:
        self._scanner.invalidate_cache()
        self._all_packs = self._scanner.scan_all(include_disabled=True)
        self._adjust_cursor()
        self._msg = f"Rescanned: {len(self._all_packs)} packs found"
        self._msg_style = "class:msg-ok"

    def _adjust_cursor(self) -> None:
        total = len(self._filtered())
        btn_count = 4  # Save, Sync, Rescan, Cancel
        max_idx = total + btn_count - 1
        if self._cursor > max_idx:
            self._cursor = max_idx

    # ── key bindings ───────────────────────────────────────────────────────

    def _build_kb(self) -> KeyBindings:
        kb = KeyBindings()

        def inv():
            if self._app:
                self._app.invalidate()

        filtered_len = lambda: len(self._filtered())
        btn_count = 4  # Save, Sync, Rescan, Cancel

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
            total = filtered_len() + btn_count
            if total > 0:
                self._cursor = (self._cursor - 1) % total
                self._ensure_viewport()
            inv()

        @kb.add("down", filter=_listing)
        @kb.add("j", filter=_listing)
        def _down(e):
            total = filtered_len() + btn_count
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
            total = filtered_len() + btn_count
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
            btn_idx = self._cursor - total
            if self._cursor < total:
                _, pack = filtered[self._cursor]
                key = self._folder_key(pack)
                if key in self._selected:
                    self._selected.discard(key)
                else:
                    self._selected.add(key)
                inv()
                return
            if btn_idx == 0:  # Save
                self._save_and_exit()
            elif btn_idx == 1:  # Sync
                self._do_sync()
                inv()
            elif btn_idx == 2:  # Rescan
                self._do_rescan()
                inv()
            elif btn_idx == 3:  # Cancel
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

        @kb.add("s", filter=_listing)
        def _sync(e):
            self._do_sync()
            inv()

        @kb.add("r", filter=_listing)
        @kb.add("R", filter=_listing)
        def _rescan(e):
            self._do_rescan()
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
