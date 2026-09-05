"""
core/skill_tui.py — Unified Interactive TUI for Skill Pack Management.

Single interface combining enable/disable, sync, rescan, and status display.
Launched via /skills. Arrow keys + Enter for all operations.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import StyleAndTextTuples

from core.skill_manager import SkillScanner, _canonical_skill_name
from pawnlogic.selectors import ModalSpec

_PAGE = 12
_BTN_NAMES = ["Save", "All", "Clear", "Invert", "Sync", "Rescan", "Cancel"]
_BTN_COUNT = len(_BTN_NAMES)

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
        "btn-active": "#ffffff bg:#005f00 bold",
        "status-key": "#00afff bold",
        "status": "#888888",
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
        self._cursor = 0  # position in list
        self._btn_cursor = 0  # position in button row
        self._focus = "list"  # "list" or "buttons"
        self._viewport = 0
        self._search = ""
        self._search_focus = False
        self._saved = False
        self._msg = ""
        self._msg_style = ""
        self._flash_btn = -1  # button index to flash on activation
        self._app: Application | None = None
        self._embedded = False
        self._modal_close: Callable[[Any], None] | None = None
        self._modal_refresh: Callable[[ModalSpec], None] | None = None
        self._modal_key_bindings: Any = None
        self._modal_closed = False

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
        in_list = self._focus == "list"
        for idx in range(start, end):
            _, pack = filtered[idx]
            key = self._folder_key(pack)
            checked = "✓" if key in self._selected else " "
            cur = (
                "▶"
                if idx == self._cursor and in_list and not self._search_focus
                else " "
            )
            name = pack.get("name", "?")
            folder = pack.get("_folder", "")
            desc = pack.get("description", "")[:45]
            chk_cls = "class:checked" if checked == "✓" else "class:unchecked"
            row_cls = (
                "class:cursor"
                if idx == self._cursor and in_list and not self._search_focus
                else ""
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

        # Button row
        f.append(("", "\n  "))
        for i, label in enumerate(_BTN_NAMES):
            if i == self._flash_btn:
                cls = "class:btn-active"
            elif i == self._btn_cursor and self._focus == "buttons":
                cls = "class:btn-focus"
            else:
                cls = "class:btn-normal"
            f.append((cls, f" [ {label} ]"))
        f.append(("", "\n"))

        return f

    def _render_status(self) -> StyleAndTextTuples:
        if self._search_focus:
            return [
                ("class:status-key", " Enter "),
                ("class:status", "Confirm  "),
                ("class:status-key", "Esc "),
                ("class:status", "Cancel  "),
            ]
        if self._focus == "buttons":
            return [
                ("class:status-key", " ←→ "),
                ("class:status", "Move  "),
                ("class:status-key", "Enter "),
                ("class:status", "Activate  "),
                ("class:status-key", "Tab "),
                ("class:status", "Back to list  "),
                ("class:status-key", "Esc "),
                ("class:status", "Quit  "),
            ]
        return [
            ("class:status-key", " ↑↓ "),
            ("class:status", "Move  "),
            ("class:status-key", "Space "),
            ("class:status", "Toggle  "),
            ("class:status-key", "Tab "),
            ("class:status", "Buttons  "),
            ("class:status-key", "PgUp/Dn "),
            ("class:status", "Page  "),
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
        self._all_packs = self._scanner.scan_all(include_disabled=True)
        self._adjust_cursor()

    def _do_rescan(self) -> None:
        self._scanner.invalidate_cache()
        self._all_packs = self._scanner.scan_all(include_disabled=True)
        self._adjust_cursor()
        self._msg = f"Rescanned: {len(self._all_packs)} packs found"
        self._msg_style = "class:msg-ok"

    def _do_select_all(self) -> None:
        for _, p in self._filtered():
            self._selected.add(self._folder_key(p))

    def _do_clear(self) -> None:
        for _, p in self._filtered():
            self._selected.discard(self._folder_key(p))

    def _do_invert(self) -> None:
        for _, p in self._filtered():
            key = self._folder_key(p)
            if key in self._selected:
                self._selected.discard(key)
            else:
                self._selected.add(key)

    def _adjust_cursor(self) -> None:
        total = len(self._filtered())
        if self._cursor >= total:
            self._cursor = max(0, total - 1)

    def _activate_button(self, idx: int) -> None:
        """Activate a button by index with a brief flash."""
        self._flash_btn = idx
        if self._app:
            self._app.invalidate()
        name = _BTN_NAMES[idx]
        if name == "Save":
            self._save_and_exit()
        elif name == "All":
            self._do_select_all()
        elif name == "Clear":
            self._do_clear()
        elif name == "Invert":
            self._do_invert()
        elif name == "Sync":
            self._do_sync()
        elif name == "Rescan":
            self._do_rescan()
        elif name == "Cancel":
            self._saved = False
            self._finish(False)
        # Reset flash after a short delay (next invalidate cycle)
        self._flash_btn = -1

    # ── key bindings ───────────────────────────────────────────────────────

    def _build_kb(self) -> KeyBindings:
        kb = KeyBindings()

        def inv():
            if self._app:
                self._app.invalidate()

        # ── search mode ────────────────────────────────────────────────────
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

        # ── button focus mode ──────────────────────────────────────────────
        _buttons = Condition(
            lambda: not self._search_focus and self._focus == "buttons"
        )

        @kb.add("left", filter=_buttons)
        def _btn_left(e):
            self._btn_cursor = (self._btn_cursor - 1) % _BTN_COUNT
            inv()

        @kb.add("right", filter=_buttons)
        def _btn_right(e):
            self._btn_cursor = (self._btn_cursor + 1) % _BTN_COUNT
            inv()

        @kb.add("enter", filter=_buttons)
        def _btn_enter(e):
            self._activate_button(self._btn_cursor)
            inv()

        @kb.add("tab", filter=_buttons)
        def _btn_tab(e):
            self._focus = "list"
            inv()

        @kb.add("escape", filter=_buttons)
        def _btn_esc(e):
            self._saved = False
            self._finish(False)

        # ── list focus mode ────────────────────────────────────────────────
        _listing = Condition(lambda: not self._search_focus and self._focus == "list")

        @kb.add("up", filter=_listing)
        def _list_up(e):
            total = len(self._filtered())
            if total > 0:
                self._cursor = (self._cursor - 1) % total
                self._ensure_viewport()
            inv()

        @kb.add("down", filter=_listing)
        def _list_down(e):
            total = len(self._filtered())
            if total > 0:
                self._cursor = (self._cursor + 1) % total
                self._ensure_viewport()
            inv()

        @kb.add("pageup", filter=_listing)
        def _list_pgup(e):
            self._cursor = max(0, self._cursor - _PAGE)
            self._ensure_viewport()
            inv()

        @kb.add("pagedown", filter=_listing)
        def _list_pgdn(e):
            total = len(self._filtered())
            self._cursor = min(total - 1, self._cursor + _PAGE)
            self._ensure_viewport()
            inv()

        @kb.add("space", filter=_listing)
        def _list_space(e):
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
        def _list_enter(e):
            filtered = self._filtered()
            if self._cursor < len(filtered):
                _, pack = filtered[self._cursor]
                key = self._folder_key(pack)
                if key in self._selected:
                    self._selected.discard(key)
                else:
                    self._selected.add(key)
            inv()

        @kb.add("tab", filter=_listing)
        def _list_tab(e):
            self._focus = "buttons"
            inv()

        @kb.add("/", filter=_listing)
        def _list_search(e):
            self._search_focus = True
            inv()

        @kb.add("escape", filter=_listing)
        def _list_esc(e):
            self._saved = False
            self._finish(False)

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
        self._finish(True)

    def bind_application(self, application: Application) -> None:
        """Use the host application's loop when mounted as a live modal."""
        self._app = application

    def _build_layout(self) -> Layout:
        """Build the skill panel container for either run mode."""
        body = FormattedTextControl(self._render)
        status = FormattedTextControl(self._render_status)
        root = HSplit(
            [
                Window(content=body, always_hide_cursor=True),
                Window(content=status, height=1),
            ]
        )
        return Layout(root)

    def _refresh_layout(self) -> None:
        """Refresh the panel without replacing the host application's layout."""
        layout = self._build_layout()
        if self._embedded and self._modal_refresh is not None:
            self._modal_refresh(
                ModalSpec(
                    container=layout.container,
                    key_bindings=self._modal_key_bindings,
                    focus=layout.current_window,
                )
            )
            return
        if self._app:
            self._app.layout = layout
            self._app.invalidate()

    def _finish(self, result: Any = None) -> None:
        """Finish the embedded modal or the standalone TUI."""
        if self._embedded:
            self._modal_closed = True
            callback = self._modal_close
            if callback is not None:
                callback(result if result is not None else self._saved)
            return
        if self._app:
            self._app.exit()

    @property
    def is_closed(self) -> bool:
        return self._modal_closed

    def close(self, result: Any = None) -> None:
        """Close the embedded selector when the host resolves its future."""
        self._modal_closed = True
        if result is not None:
            self._saved = bool(result)

    def build_modal(
        self,
        on_close: Callable[[Any], None],
        on_refresh: Callable[[ModalSpec], None],
    ) -> ModalSpec:
        """Build the skill panel as a view owned by the live Application."""
        if self._app is None:
            raise RuntimeError("bind_application() is required before build_modal()")
        self._embedded = True
        self._modal_close = on_close
        self._modal_refresh = on_refresh
        self._modal_closed = False
        layout = self._build_layout()
        self._modal_key_bindings = self._build_kb()
        return ModalSpec(
            container=layout.container,
            key_bindings=self._modal_key_bindings,
            focus=layout.current_window,
        )

    # ── run ────────────────────────────────────────────────────────────────

    async def run(self) -> bool:
        """Run the TUI. Returns True if changes were saved."""
        self._embedded = False
        layout = self._build_layout()
        self._app = Application(
            layout=layout,
            key_bindings=self._build_kb(),
            style=TUI_STYLE,
            full_screen=False,
            mouse_support=False,
        )
        await self._app.run_async()
        return self._saved


async def run_skill_tui(scanner: SkillScanner) -> bool:
    """Launch the skill pack TUI. Returns True if saved."""
    tui = SkillPackTUI(scanner)
    return await tui.run()
