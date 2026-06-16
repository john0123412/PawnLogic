"""
core/provider_tui.py — Interactive TUI for Provider Management
4-panel stack: Main → Detail → AddWizard → ModelSelection
All UI text in English. API Keys never displayed in plain text.
"""
from __future__ import annotations
import asyncio, json, os
from typing import Optional

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window, FloatContainer, Float, ConditionalContainer
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea, Frame
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import StyleAndTextTuples

from config.providers import (
    PROVIDERS, MODELS, CUSTOM_PROVIDERS_PATH,
    init_providers, save_custom_provider, remove_custom_provider,
    is_provider_active,
    register_provider, remove_provider, remove_model, remove_models_for_provider,
)
from core.provider_runtime import (
    candidate_save_alias as _candidate_save_alias,
    connection_result_from_response as _connection_result_from_response,
    fetch_models as _fetch_models,
    filter_supported_chat_models as _filter_supported_chat_models,
    first_provider_chat_model as _first_provider_chat_model,
    format_alias_preview as _format_alias_preview,
    format_model_sync_notice as _format_model_sync_notice,
    model_alias_changes as _model_alias_changes,
    model_is_chat_candidate as _model_is_chat_candidate,
    model_rejection_reason as _model_rejection_reason,
    normalize_base_url as _normalize_base_url,
    probe_openai_chat_model as _probe_openai_chat_model,
    REASONING_KEYWORDS as _REASONING_KEYWORDS,
    record_sync_time as _record_sync_time,
    save_key as _save_key_to_env,
    set_active as _runtime_set_active,
    sync_models_to_runtime as _sync_models_to_runtime,
    test_connection as _test_connection,
)
from core.file_store import atomic_write_text
from core.logger import logger

__all__ = [
    "ProviderTUI",
    "run_provider_tui",
    "TUI_STYLE",
    "_candidate_save_alias",
    "_connection_result_from_response",
    "_fetch_models",
    "_filter_supported_chat_models",
    "_first_provider_chat_model",
    "_format_alias_preview",
    "_format_model_sync_notice",
    "_model_alias_changes",
    "_model_is_chat_candidate",
    "_model_rejection_reason",
    "_normalize_base_url",
    "_probe_openai_chat_model",
    "_save_key_to_env",
    "_test_connection",
]

_BUILTIN = {"deepseek", "openai", "anthropic"}
_ALWAYS_ACTIVE = {"deepseek"}
_PAGE = 20  # rows per page in model selector
load_custom_providers = init_providers

TUI_STYLE = Style.from_dict({
    "title":        "#00afff bold",
    "subtitle":     "#888888",
    "cursor":       "#00ff00 bold",
    "key-ok":       "#00d700",
    "key-missing":  "#ff5555",
    "badge-builtin":"#888888",
    "badge-custom": "#00afff",
    "status":       "bg:#1a1a2e #888888",
    "status-key":   "bg:#1a1a2e #00afff bold",
    "dialog-title": "#ffaa00 bold",
    "dialog-body":  "#cccccc",
    "btn-focus":    "bg:#00afff #000000 bold",
    "btn-normal":   "#888888",
    "field-focus":  "bg:#1e3a5f #ffffff",
    "field-normal": "#888888",
    "error":        "#ff5555",
    "success":      "#00d700",
    "warning":      "#ffaa00",
    "spinner":      "#00afff bold",
    "dialog-bg":    "bg:#1a1a2e #cccccc",
})

# ── helpers ───────────────────────────────────────────────────────────────────

def _mask_key(key: str) -> str:
    if not key:
        return "— Not Configured"
    return f"{key[:4]}{'•' * 8}{key[-4:]}" if len(key) > 8 else "••••••••"


def _provider_snapshot() -> dict[str, dict]:
    return {name: dict(cfg) for name, cfg in PROVIDERS.items()}


def _model_items_snapshot() -> list[tuple[str, dict]]:
    return [(alias, dict(cfg)) for alias, cfg in MODELS.items()]


def _provider_key(pname: str) -> str:
    env_var = _provider_snapshot().get(pname, {}).get("api_key_env", "")
    return os.getenv(env_var, "") if env_var else ""


def _model_count(pname: str) -> int:
    return sum(1 for _a, m in _model_items_snapshot() if m.get("provider") == pname)


def _last_synced(pname: str) -> str:
    if not CUSTOM_PROVIDERS_PATH.exists():
        return "Never"
    try:
        data = json.loads(CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8"))
        return data.get("sync_times", {}).get(pname) or "Never"
    except Exception:
        return "Never"

# ══════════════════════════════════════════════════════════════════════════════
# ProviderTUI
# ══════════════════════════════════════════════════════════════════════════════

class ProviderTUI:
    def __init__(self):
        self._app: Optional[Application] = None
        self._panel: str = "main"
        # main
        self._main_cursor: int = 0
        # detail
        self._detail_provider: str = ""
        self._detail_cursor: int = 0
        self._detail_status: str = ""
        self._detail_status_style: str = ""
        self._detail_key_active: bool = False
        self._key_ta = TextArea(password=True, multiline=False, height=1, style="class:field-focus")
        # dialog: None | "security" | "delete" | "save_anyway"
        self._dialog: Optional[str] = None
        self._dialog_cursor: int = 0
        self._wiz_fields_pending: tuple = ()
        # wizard
        self._wiz_fields: list = ["", "", "openai", ""]
        self._wiz_inputs = [
            TextArea(multiline=False, height=1, style="class:field-focus"),
            TextArea(multiline=False, height=1, style="class:field-focus"),
            TextArea(password=True, multiline=False, height=1, style="class:field-focus"),
        ]
        self._wiz_focus: int = 0
        self._wiz_fmt_open: bool = False
        self._wiz_fmt_cursor: int = 0
        self._wiz_error: str = ""
        self._wiz_status: str = ""
        self._wiz_status_style: str = ""
        # model selector
        self._ms_all: list[tuple[str, dict]] = []   # full unfiltered list
        self._ms_selected: set[str] = set()          # selected model IDs (strings)
        self._ms_manual: list[str] = []              # manually added IDs
        self._ms_cursor: int = 0
        self._ms_viewport: int = 0                   # top row of visible window
        self._ms_provider: str = ""
        self._ms_caller: str = "main"
        self._ms_error: str = ""
        self._ms_search: str = ""
        self._ms_search_ta = TextArea(multiline=False, height=1, style="class:field-focus")
        self._ms_search_focus: bool = False
        self._ms_filter_cache: tuple = ("", [])
        self._ms_notice: list[str] = []
        self._ms_save_exit: bool = False
        # manage models panel
        self._mm_models: list[str] = []   # alias list for current provider
        self._mm_cursor: int = 0
        self._mm_provider: str = ""
        self._mm_status: str = ""
        self._mm_status_style: str = ""

    # ── helpers ───────────────────────────────────────────────────────────────

    def _provider_rows(self) -> list[str]:
        return list(_provider_snapshot())

    def _ms_filtered(self) -> list[tuple[str, dict]]:
        """Return entries filtered by search string. Result cached per search query."""
        q = self._ms_search.strip().lower()
        if not q:
            return self._ms_all
        if not hasattr(self, "_ms_filter_cache") or self._ms_filter_cache[0] != q:
            self._ms_filter_cache = (q, [(mid, cfg) for mid, cfg in self._ms_all if q in mid.lower()])
        return self._ms_filter_cache[1]

    def _sync_model_search_from_input(self) -> None:
        self._ms_search = self._ms_search_ta.text

    def _reset_wizard(self) -> None:
        self._wiz_fields = ["", "", "openai", ""]
        for field in self._wiz_inputs:
            field.text = ""
        self._wiz_focus = 0
        self._wiz_fmt_open = False
        self._wiz_fmt_cursor = 0
        self._wiz_error = ""
        self._wiz_status = ""
        self._wiz_status_style = ""

    def _sync_wizard_fields_from_inputs(self) -> None:
        self._wiz_fields[0] = self._wiz_inputs[0].text.strip()
        self._wiz_fields[1] = self._wiz_inputs[1].text.strip()
        self._wiz_fields[3] = self._wiz_inputs[2].text.strip()

    def _active_focus_target(self):
        if self._panel == "detail" and self._detail_key_active:
            return self._key_ta
        if self._panel == "wizard" and self._wiz_focus in (0, 1, 3) and not self._dialog:
            return self._wiz_inputs[{0: 0, 1: 1, 3: 2}[self._wiz_focus]]
        if self._panel == "models" and self._ms_search_focus:
            return self._ms_search_ta
        return None

    def _focus_active_input(self) -> None:
        if not self._app:
            return
        target = self._active_focus_target()
        if target is not None:
            self._app.layout.focus(target)
        self._app.invalidate()

    # ── render: main ─────────────────────────────────────────────────────────

    def _render_main(self) -> StyleAndTextTuples:
        rows = self._provider_rows()
        f: StyleAndTextTuples = [("class:title", "\n  🔌 Provider Manager\n\n")]
        if not rows:
            f.append(("class:subtitle", "  No providers configured. Press N to add one.\n"))
        for i, pname in enumerate(rows):
            key = _provider_key(pname)
            n = _model_count(pname)
            is_builtin = pname in _BUILTIN
            active = is_provider_active(pname)
            cur = "▶ " if i == self._main_cursor else "  "
            badge_s = "class:badge-builtin" if is_builtin else "class:badge-custom"
            badge = "[built-in]" if is_builtin else "[custom]"
            cs = "class:cursor" if i == self._main_cursor else ""
            f += [(cs, f"  {cur}● {pname:<22}"),
                  ("class:key-ok" if key else "class:key-missing",
                   "  ✓ Key Set" if key else "  ✗ Not Configured"),
                  ("class:subtitle", f"  {n} models  "),
                  ("class:key-ok" if active else "class:subtitle",
                   " active  " if active else " inactive  "),
                  (badge_s, badge), ("", "\n")]
        f.append(("", "\n"))
        return f

    def _render_status_main(self) -> StyleAndTextTuples:
        return [("class:status-key", " ↑↓ "), ("class:status", "Move  "),
                ("class:status-key", "Enter "), ("class:status", "Manage  "),
                ("class:status-key", "N "), ("class:status", "Add  "),
                ("class:status-key", "D "), ("class:status", "Delete  "),
                ("class:status-key", "Q "), ("class:status", "Quit ")]

    # ── render: detail ────────────────────────────────────────────────────────

    def _render_detail(self) -> StyleAndTextTuples:
        pname = self._detail_provider
        pinfo = _provider_snapshot().get(pname, {})
        key = _provider_key(pname)
        n = _model_count(pname)
        fmt = pinfo.get("api_format", "openai")
        fmt_label = "Anthropic Compatible" if fmt == "anthropic" else "OpenAI Compatible"
        active = is_provider_active(pname)
        f: StyleAndTextTuples = [("class:title", f"\n  ◀ {pname}\n\n")]
        f += [("class:subtitle", f"  {'Name':<12}│ {pname}\n"),
              ("class:subtitle", f"  {'Base URL':<12}│ {pinfo.get('base_url','')}\n"),
              ("class:subtitle", f"  {'Format':<12}│ {fmt_label}\n"),
              ("class:subtitle", f"  {'Active':<12}│ "),
              ("class:key-ok" if active else "class:warning",
               "Yes - visible in /model\n" if active else "No - hidden from /model\n")]
        if key:
            f += [("class:subtitle", f"  {'API Key':<12}│ "),
                  ("class:key-ok", f"{_mask_key(key)}   ● Configured\n")]
        else:
            f += [("class:subtitle", f"  {'API Key':<12}│ "),
                  ("class:key-missing", "— Not Configured\n")]
        f.append(("class:subtitle", f"  {'Models':<12}│ {n} loaded  (Last synced: {_last_synced(pname)})\n"))
        names = [a for a, m in _model_items_snapshot() if m.get("provider") == pname]
        if names:
            preview = ", ".join(names[:5])
            more = f"  ... and {len(names)-5} more" if len(names) > 5 else ""
            f.append(("class:subtitle", f"               │ {preview}{more}\n"))
        f.append(("", "\n"))
        if self._detail_key_active:
            f.append(("class:warning", "  New API Key (input hidden, Enter to save, Esc to cancel):\n"))
        active_action = "Deactivate Provider" if active else "Activate Provider"
        actions = ["Update API Key", "Fetch / Sync Models", "Test Connection",
                   "Manage Models", active_action, "Delete Provider"]
        for i, act in enumerate(actions):
            if i == self._detail_cursor and not self._detail_key_active:
                f.append(("class:cursor", f"  ▶ [ {act} ]\n"))
            else:
                f.append(("class:subtitle", f"    [ {act} ]\n"))
        f.append(("", "\n"))
        if self._detail_status:
            f.append((self._detail_status_style, f"  {self._detail_status}\n"))
        return f

    def _render_status_detail(self) -> StyleAndTextTuples:
        return [("class:status-key", " ↑↓ "), ("class:status", "Move  "),
                ("class:status-key", "Enter "), ("class:status", "Execute  "),
                ("class:status-key", "Esc "), ("class:status", "Back ")]

    # ── render: wizard ────────────────────────────────────────────────────────

    def _render_wizard(self) -> StyleAndTextTuples:
        labels = ["Name", "Base URL", "Format", "API Key"]
        f: StyleAndTextTuples = [("class:title", "\n  ✚ Add Provider\n\n")]
        self._sync_wizard_fields_from_inputs()
        for i, label in enumerate(labels):
            focused = (i == self._wiz_focus)
            s = "class:field-focus" if focused else "class:field-normal"
            val = self._wiz_fields[i]
            if i == 3:
                display = "•" * len(val) if val else ""
            elif i == 2:
                display = "Anthropic Compatible" if val == "anthropic" else "OpenAI Compatible"
            else:
                display = val
            f.append((s, f"  {'①②③④'[i]} {label:<10} [ {display:<40} ]\n"))
            if i == 2 and focused and self._wiz_fmt_open:
                for j, opt in enumerate(["OpenAI Compatible", "Anthropic Compatible"]):
                    cur = "▶ " if j == self._wiz_fmt_cursor else "  "
                    fs = "class:cursor" if j == self._wiz_fmt_cursor else "class:subtitle"
                    f.append((fs, f"       {cur}{opt}\n"))
        f.append(("", "\n"))
        bs = "class:btn-focus" if self._wiz_focus == 4 else "class:btn-normal"
        f.append((bs, "  [ Save Provider ]\n\n"))
        if self._wiz_error:
            f.append(("class:error", f"  ✗ {self._wiz_error}\n"))
        if self._wiz_status:
            f.append((self._wiz_status_style, f"  {self._wiz_status}\n"))
        return f

    def _render_status_wizard(self) -> StyleAndTextTuples:
        return [("class:status-key", " Tab "), ("class:status", "Next Field  "),
                ("class:status-key", "↑↓ "), ("class:status", "Move/Select  "),
                ("class:status-key", "Enter "), ("class:status", "Save  "),
                ("class:status-key", "Esc "), ("class:status", "Cancel ")]

    # ── render: model selector ────────────────────────────────────────────────

    def _render_model_select(self) -> StyleAndTextTuples:
        self._sync_model_search_from_input()
        filtered = self._ms_filtered()
        total = len(filtered)
        f: StyleAndTextTuples = [
            ("class:title", f"\n  📦 Select Models — {self._ms_provider}\n"),
            ("class:subtitle", f"  {len(self._ms_all)} models available. Choose which to load.\n\n"),
        ]
        for line in self._ms_notice:
            f.append(("class:warning", f"  {line}\n"))
        if self._ms_notice:
            f.append(("", "\n"))
        sb_s = "class:field-focus" if self._ms_search_focus else "class:field-normal"
        f.append((sb_s, f"  🔍 Search: {self._ms_search}{'▌' if self._ms_search_focus else ''}\n\n"))
        # Only render the visible viewport window — never all rows
        start = self._ms_viewport
        end = min(start + _PAGE, total)
        for i in range(start, end):
            mid, cfg = filtered[i]
            checked = "✓" if mid in self._ms_selected else " "
            cur = "▶" if i == self._ms_cursor and not self._ms_search_focus else " "
            vtag = " 📷" if cfg.get("vision") else ""
            manual = " [+]" if mid in self._ms_manual else ""
            alias = _candidate_save_alias(self._ms_provider, mid, cfg)
            alias_note = f" -> {alias}" if alias != mid else ""
            cs = "class:cursor" if i == self._ms_cursor and not self._ms_search_focus else ""
            f.append((cs, f"  {cur} [{checked}] {mid}{alias_note}{vtag}{manual}\n"))
        if total > _PAGE:
            f.append(("class:subtitle", f"\n  Showing {start+1}–{end} of {total}\n"))
        f.append(("", f"\n  {len(self._ms_selected)} selected\n\n"))
        load_style = "class:btn-focus" if self._ms_cursor == total and not self._ms_search_focus else "class:btn-normal"
        close_style = "class:btn-focus" if self._ms_cursor == total + 1 and not self._ms_search_focus else "class:btn-normal"
        cancel_style = "class:btn-focus" if self._ms_cursor == total + 2 and not self._ms_search_focus else "class:btn-normal"
        f.append((load_style, "  [ Load Selected ]  "))
        f.append((close_style, "[ Load & Close ]  "))
        f.append((cancel_style, "[ Cancel ]\n"))
        if self._ms_error:
            f.append(("class:error", f"\n  ⚠ {self._ms_error}\n"))
        return f

    def _render_status_ms(self) -> StyleAndTextTuples:
        return [("class:status-key", " ↑↓ "), ("class:status", "Move  "),
                ("class:status-key", "Space "), ("class:status", "Toggle  "),
                ("class:status-key", "/ "), ("class:status", "Search  "),
                ("class:status-key", "A "), ("class:status", "All  "),
                ("class:status-key", "C "), ("class:status", "Clear  "),
                ("class:status-key", "Enter "), ("class:status", "Confirm  "),
                ("class:status-key", "Esc "), ("class:status", "Back  "),
                ("class:status-key", "Q "), ("class:status", "Quit ")]

    # ── render: dialogs ───────────────────────────────────────────────────────

    def _render_dialog(self) -> StyleAndTextTuples:
        if self._dialog == "security":
            f: StyleAndTextTuples = [
                ("class:dialog-title", "  ⚠  Security Notice\n\n"),
                ("class:dialog-body", "  Updating the API Key will clear the existing key.\n"),
                ("class:dialog-body", "  You must paste the full key again.\n"),
                ("class:dialog-body", "  The key will never be displayed in plain text.\n\n"),
            ]
            for i, btn in enumerate(["Continue", "Cancel"]):
                f.append(("class:btn-focus" if i == self._dialog_cursor else "class:btn-normal",
                           f"  [ {btn} ]  "))
        elif self._dialog == "delete":
            pname = self._detail_provider
            f = [("class:dialog-title", "  🗑  Confirm Delete\n\n"),
                 ("class:dialog-body", f"  Delete provider '{pname}'? This cannot be undone.\n\n")]
            for i, btn in enumerate(["Cancel", "Delete"]):
                f.append(("class:btn-focus" if i == self._dialog_cursor else "class:btn-normal",
                           f"  [ {btn} ]  "))
        elif self._dialog == "save_anyway":
            f = [("class:dialog-title", "  ⚠  Connection Failed\n\n"),
                 ("class:dialog-body", "  Save provider anyway without testing?\n\n")]
            for i, btn in enumerate(["No — Edit", "Yes — Save"]):
                f.append(("class:btn-focus" if i == self._dialog_cursor else "class:btn-normal",
                           f"  [ {btn} ]  "))
        else:
            return []
        f.append(("", "\n"))
        return f

    def _render_manage_models(self) -> StyleAndTextTuples:
        pname = self._mm_provider
        f: StyleAndTextTuples = [("class:title", f"\n  🗂 Manage Models — {pname}\n\n")]
        if not self._mm_models:
            f.append(("class:subtitle", "  No models loaded. Use Fetch / Sync Models.\n"))
        for i, alias in enumerate(self._mm_models):
            cur = "▶" if i == self._mm_cursor else " "
            cs = "class:cursor" if i == self._mm_cursor else ""
            mid = MODELS.get(alias, {}).get("id", alias)
            f.append((cs, f"  {cur} {alias}  "))
            f.append(("class:subtitle", f"({mid})\n"))
        if self._mm_status:
            f.append((self._mm_status_style, f"\n  {self._mm_status}\n"))
        f.append(("", "\n"))
        return f

    def _render_status_mm(self) -> StyleAndTextTuples:
        return [("class:status-key", " ↑↓ "), ("class:status", "Move  "),
                ("class:status-key", "D "), ("class:status", "Delete model  "),
                ("class:status-key", "Esc "), ("class:status", "Back ")]

    # ── layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> Layout:
        def body():
            p = self._panel
            if p == "main":   return self._render_main()
            if p == "detail": return self._render_detail()
            if p == "wizard": return self._render_wizard()
            if p == "models": return self._render_model_select()
            if p == "manage": return self._render_manage_models()
            return []

        def status():
            p = self._panel
            if p == "main":   return self._render_status_main()
            if p == "detail": return self._render_status_detail()
            if p == "wizard": return self._render_status_wizard()
            if p == "models": return self._render_status_ms()
            if p == "manage": return self._render_status_mm()
            return []

        body_win = Window(content=FormattedTextControl(body), always_hide_cursor=True)
        status_win = Window(content=FormattedTextControl(status), height=1, always_hide_cursor=True)

        key_input = ConditionalContainer(
            content=HSplit([Window(height=1), self._key_ta, Window(height=1)]),
            filter=Condition(lambda: self._panel == "detail" and self._detail_key_active),
        )
        wiz_name_input = ConditionalContainer(
            content=HSplit([Window(height=1), self._wiz_inputs[0], Window(height=1)]),
            filter=Condition(lambda: self._panel == "wizard" and self._wiz_focus == 0
                             and not self._dialog),
        )
        wiz_url_input = ConditionalContainer(
            content=HSplit([Window(height=1), self._wiz_inputs[1], Window(height=1)]),
            filter=Condition(lambda: self._panel == "wizard" and self._wiz_focus == 1
                             and not self._dialog),
        )
        wiz_key_input = ConditionalContainer(
            content=HSplit([Window(height=1), self._wiz_inputs[2], Window(height=1)]),
            filter=Condition(lambda: self._panel == "wizard" and self._wiz_focus == 3
                             and not self._dialog),
        )
        model_search_input = ConditionalContainer(
            content=HSplit([Window(height=1), self._ms_search_ta, Window(height=1)]),
            filter=Condition(lambda: self._panel == "models" and self._ms_search_focus),
        )

        # Dialog: opaque background so text doesn't bleed through
        floats = []
        if self._dialog:
            floats = [Float(
                content=Frame(
                    body=Window(content=FormattedTextControl(self._render_dialog),
                                always_hide_cursor=True, style="class:dialog-bg"),
                    width=58, height=10, style="class:dialog-bg",
                ),
                transparent=False,
            )]

        root = FloatContainer(
            content=HSplit([
                body_win,
                key_input,
                wiz_name_input,
                wiz_url_input,
                wiz_key_input,
                model_search_input,
                status_win,
            ]),
            floats=floats,
        )
        focused = self._active_focus_target() or body_win
        return Layout(root, focused_element=focused)

    # ── key bindings ──────────────────────────────────────────────────────────

    def _build_kb(self) -> KeyBindings:
        kb = KeyBindings()

        def inv():
            if self._app:
                self._app.invalidate()

        def rebuild():
            if self._app:
                self._app.layout = self._build_layout()
                self._app.invalidate()

        # ── dialogs ───────────────────────────────────────────────────────────
        _dlg = Condition(lambda: self._dialog is not None)

        @kb.add("left",   filter=_dlg)
        @kb.add("right",  filter=_dlg)
        @kb.add("tab",    filter=_dlg)
        def _dlg_move(e): self._dialog_cursor ^= 1; inv()

        @kb.add("enter", filter=_dlg)
        def _dlg_enter(e):
            dlg, cur = self._dialog, self._dialog_cursor
            self._dialog = None; self._dialog_cursor = 0
            if dlg == "security" and cur == 0:
                self._detail_key_active = True
                self._key_ta.text = ""
            elif dlg == "delete" and cur == 1:
                self._do_delete_provider()
            elif dlg == "save_anyway" and cur == 1:
                self._do_save_provider_no_test()
            rebuild()

        @kb.add("escape", filter=_dlg)
        def _dlg_esc(e):
            self._dialog = None; self._dialog_cursor = 0; rebuild()

        # ── key input ─────────────────────────────────────────────────────────
        _key_active = Condition(lambda: self._panel == "detail" and self._detail_key_active and not self._dialog)

        @kb.add("enter", filter=_key_active)
        def _key_submit(e):
            new_key = self._key_ta.text.strip()
            self._detail_key_active = False
            if not new_key:
                self._detail_status = "Cancelled — no key entered."
                self._detail_status_style = "class:warning"
                rebuild(); return
            pname = self._detail_provider
            env_var = PROVIDERS.get(pname, {}).get("api_key_env", "")
            if env_var:
                _save_key_to_env(env_var, new_key)
            self._detail_status = "✅ Key saved. Testing..."
            self._detail_status_style = "class:spinner"
            rebuild()
            e.app.create_background_task(self._run_test_detail(pname))

        @kb.add("escape", filter=_key_active)
        def _key_cancel(e):
            self._detail_key_active = False; self._detail_status = ""; rebuild()

        # ── main ──────────────────────────────────────────────────────────────
        _main = Condition(lambda: self._panel == "main" and not self._dialog)

        @kb.add("up",    filter=_main)
        def _m_up(e):
            rows = self._provider_rows()
            if rows: self._main_cursor = (self._main_cursor - 1) % len(rows)
            inv()

        @kb.add("down",  filter=_main)
        def _m_dn(e):
            rows = self._provider_rows()
            if rows: self._main_cursor = (self._main_cursor + 1) % len(rows)
            inv()

        @kb.add("enter", filter=_main)
        def _m_enter(e):
            rows = self._provider_rows()
            if rows and self._main_cursor < len(rows):
                self._detail_provider = rows[self._main_cursor]
                self._detail_cursor = 0; self._detail_status = ""
                self._detail_key_active = False
                self._panel = "detail"; rebuild()

        @kb.add("n", filter=_main)
        @kb.add("N", filter=_main)
        def _m_add(e):
            self._reset_wizard()
            self._panel = "wizard"; rebuild()

        @kb.add("d", filter=_main)
        @kb.add("D", filter=_main)
        def _m_del(e):
            rows = self._provider_rows()
            if not rows: return
            pname = rows[self._main_cursor]
            if pname in _BUILTIN:
                return
            self._detail_provider = pname
            self._dialog = "delete"; self._dialog_cursor = 0; rebuild()

        @kb.add("q",      filter=_main)
        @kb.add("Q",      filter=_main)
        @kb.add("escape", filter=_main)
        def _m_quit(e): e.app.exit()

        # ── detail ────────────────────────────────────────────────────────────
        _det = Condition(lambda: self._panel == "detail" and not self._dialog and not self._detail_key_active)

        @kb.add("up",    filter=_det)
        def _d_up(e): self._detail_cursor = (self._detail_cursor - 1) % 6; inv()

        @kb.add("down",  filter=_det)
        def _d_dn(e): self._detail_cursor = (self._detail_cursor + 1) % 6; inv()

        @kb.add("enter", filter=_det)
        def _d_enter(e): e.app.create_background_task(self._detail_action())

        @kb.add("escape", filter=_det)
        def _d_esc(e): self._panel = "main"; rebuild()

        # ── manage models panel ───────────────────────────────────────────────
        _mm = Condition(lambda: self._panel == "manage")

        @kb.add("up",    filter=_mm)
        def _mm_up(e):
            if self._mm_models:
                self._mm_cursor = (self._mm_cursor - 1) % len(self._mm_models); inv()

        @kb.add("down",  filter=_mm)
        def _mm_dn(e):
            if self._mm_models:
                self._mm_cursor = (self._mm_cursor + 1) % len(self._mm_models); inv()

        @kb.add("d", filter=_mm)
        @kb.add("D", filter=_mm)
        def _mm_del(e):
            if not self._mm_models: return
            alias = self._mm_models[self._mm_cursor]
            # Remove from MODELS and custom_providers.json
            remove_model(alias)
            import json as _j
            if CUSTOM_PROVIDERS_PATH.exists():
                try:
                    data = _j.loads(CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8"))
                    data.get("models", {}).pop(alias, None)
                    atomic_write_text(
                        CUSTOM_PROVIDERS_PATH,
                        _j.dumps(data, ensure_ascii=False, indent=2),
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to remove model from custom_providers.json ({}): {!r}",
                        CUSTOM_PROVIDERS_PATH, exc,
                    )
                    self._mm_status = "Failed to update custom_providers.json."
                    self._mm_status_style = "class:error"
                    inv()
                    return
            self._mm_status = f"Deleted model: {alias}"
            self._mm_status_style = "class:success"
            self._mm_models = [a for a, m in _model_items_snapshot()
                               if m.get("provider") == self._mm_provider]
            self._mm_cursor = min(self._mm_cursor, max(0, len(self._mm_models) - 1))
            inv()

        @kb.add("escape", filter=_mm)
        def _mm_esc(e): self._panel = "detail"; rebuild()

        # ── wizard ────────────────────────────────────────────────────────────
        _wiz = Condition(lambda: self._panel == "wizard" and not self._dialog)
        _wiz_nav = Condition(lambda: self._panel == "wizard" and not self._dialog
                             and not (self._wiz_focus == 2 and self._wiz_fmt_open))
        _wiz_text = Condition(lambda: self._panel == "wizard" and self._wiz_focus in (0, 1, 3)
                              and not self._dialog and not self._wiz_fmt_open)

        @kb.add("tab",   filter=_wiz_nav)
        @kb.add("down",  filter=_wiz_nav)
        def _w_next(e):
            self._wiz_fmt_open = False
            self._wiz_focus = (self._wiz_focus + 1) % 5
            self._focus_active_input()

        @kb.add("s-tab", filter=_wiz_nav)
        @kb.add("up",    filter=_wiz_nav)
        def _w_prev(e):
            self._wiz_fmt_open = False
            self._wiz_focus = (self._wiz_focus - 1) % 5
            self._focus_active_input()

        _fmt_closed = Condition(lambda: self._panel == "wizard" and self._wiz_focus == 2
                                and not self._wiz_fmt_open and not self._dialog)
        _fmt_open   = Condition(lambda: self._panel == "wizard" and self._wiz_focus == 2
                                and self._wiz_fmt_open)

        @kb.add("enter", filter=_fmt_closed)
        @kb.add("space", filter=_fmt_closed)
        def _w_fmt_open(e):
            self._wiz_fmt_open = True
            self._wiz_fmt_cursor = 0 if self._wiz_fields[2] == "openai" else 1; inv()

        @kb.add("up",    filter=_fmt_open)
        def _w_fmt_up(e): self._wiz_fmt_cursor = (self._wiz_fmt_cursor - 1) % 2; inv()

        @kb.add("down",  filter=_fmt_open)
        def _w_fmt_dn(e): self._wiz_fmt_cursor = (self._wiz_fmt_cursor + 1) % 2; inv()

        @kb.add("enter", filter=_fmt_open)
        @kb.add("space", filter=_fmt_open)
        def _w_fmt_pick(e):
            self._wiz_fields[2] = "anthropic" if self._wiz_fmt_cursor == 1 else "openai"
            self._wiz_fmt_open = False; self._focus_active_input()

        _btn = Condition(lambda: self._panel == "wizard" and self._wiz_focus == 4
                         and not self._wiz_fmt_open and not self._dialog)

        @kb.add("enter", filter=_btn)
        def _w_confirm(e): e.app.create_background_task(self._wizard_confirm())

        @kb.add("escape", filter=_wiz)
        def _w_esc(e): self._panel = "main"; rebuild()

        @kb.add("enter", filter=_wiz_text)
        def _w_text_enter(e):
            self._sync_wizard_fields_from_inputs()
            self._wiz_focus = 2 if self._wiz_focus == 1 else self._wiz_focus + 1
            rebuild()
            self._focus_active_input()

        # ── model selector ────────────────────────────────────────────────────
        _ms = Condition(lambda: self._panel == "models")
        _ms_list = Condition(lambda: self._panel == "models" and not self._ms_search_focus)
        _ms_srch = Condition(lambda: self._panel == "models" and self._ms_search_focus)

        @kb.add("up",    filter=_ms_list)
        def _ms_up(e):
            self._ms_cursor = max(0, self._ms_cursor - 1)
            if self._ms_cursor < self._ms_viewport:
                self._ms_viewport = self._ms_cursor
            inv()

        @kb.add("down",  filter=_ms_list)
        def _ms_dn(e):
            filtered = self._ms_filtered()
            total = len(filtered)
            self._ms_cursor = min(total + 2, self._ms_cursor + 1)
            if self._ms_cursor >= self._ms_viewport + _PAGE:
                self._ms_viewport = self._ms_cursor - _PAGE + 1
            inv()

        @kb.add("pageup",   filter=_ms_list)
        def _ms_pgup(e):
            self._ms_cursor = max(0, self._ms_cursor - _PAGE)
            self._ms_viewport = max(0, self._ms_viewport - _PAGE); inv()

        @kb.add("pagedown", filter=_ms_list)
        def _ms_pgdn(e):
            filtered = self._ms_filtered()
            self._ms_cursor = min(len(filtered) + 2, self._ms_cursor + _PAGE)
            self._ms_viewport = min(max(0, len(filtered) - _PAGE),
                                    self._ms_viewport + _PAGE); inv()

        @kb.add("space", filter=_ms_list)
        def _ms_space(e):
            filtered = self._ms_filtered()
            if self._ms_cursor < len(filtered):
                mid = filtered[self._ms_cursor][0]
                if mid in self._ms_selected:
                    self._ms_selected.discard(mid)
                else:
                    self._ms_selected.add(mid)
            inv()

        @kb.add("a", filter=_ms_list)
        @kb.add("A", filter=_ms_list)
        def _ms_all(e):
            self._ms_selected = {mid for mid, _ in self._ms_all}; inv()

        @kb.add("c", filter=_ms_list)
        @kb.add("C", filter=_ms_list)
        def _ms_clr(e): self._ms_selected.clear(); inv()

        @kb.add("/",   filter=_ms_list)
        @kb.add("tab", filter=_ms_list)
        def _ms_to_search(e):
            self._ms_search_ta.text = self._ms_search
            self._ms_search_focus = True
            self._focus_active_input()

        @kb.add("enter", filter=_ms_list)
        def _ms_enter(e):
            filtered = self._ms_filtered()
            total = len(filtered)
            if self._ms_cursor < len(filtered):
                mid = filtered[self._ms_cursor][0]
                if mid in self._ms_selected:
                    self._ms_selected.discard(mid)
                else:
                    self._ms_selected.add(mid)
                inv()
                return
            if self._ms_cursor == total + 2:
                self._cancel_model_selector()
                return
            if not self._ms_selected:
                self._ms_error = "Select at least one model."; inv(); return
            self._ms_error = ""
            self._ms_save_exit = self._ms_cursor == total + 1
            self._do_save_models()

        @kb.add("escape", filter=_ms)
        def _ms_esc(e):
            if self._ms_search_focus:
                self._ms_search_focus = False; self._ms_search = ""; self._ms_search_ta.text = ""
                self._ms_cursor = 0; self._ms_viewport = 0; rebuild()
            else:
                self._cancel_model_selector()

        @kb.add("q", filter=_ms)
        @kb.add("Q", filter=_ms)
        def _ms_quit(e): self._cancel_model_selector(close=True)

        @kb.add("enter", filter=_ms_srch)
        def _ms_srch_enter(e):
            self._sync_model_search_from_input()
            q = self._ms_search.strip()
            if not q:
                self._ms_search_focus = False; inv(); return
            filtered = self._ms_filtered()
            if len(filtered) == 1:
                # exact single match — toggle and clear
                mid = filtered[0][0]
                if mid in self._ms_selected: self._ms_selected.discard(mid)
                else: self._ms_selected.add(mid)
                self._ms_search = ""; self._ms_search_ta.text = ""; self._ms_search_focus = False
            elif len(filtered) == 0:
                # manual add
                if q not in self._ms_manual:
                    self._ms_manual.append(q)
                    self._ms_all.insert(0, (q, {"id": q, "provider": self._ms_provider,
                                                "desc": "manual", "color": "\033[37m", "vision": False,
                                                "reasoning": any(k in q.lower() for k in _REASONING_KEYWORDS)}))
                self._ms_selected.add(q)
                self._ms_search = ""; self._ms_search_ta.text = ""; self._ms_search_focus = False
            else:
                # multiple matches — move focus to list
                self._ms_search_focus = False
            self._ms_cursor = 0; self._ms_viewport = 0; inv()

        @kb.add("tab",    filter=_ms_srch)
        def _ms_srch_tab(e):
            self._ms_search_focus = False; self._ms_search = ""; self._ms_search_ta.text = ""
            self._ms_cursor = 0; self._ms_viewport = 0; rebuild()

        return kb

    # ── actions ───────────────────────────────────────────────────────────────

    def _do_delete_provider(self):
        pname = self._detail_provider
        if pname in _BUILTIN:
            return
        remove_custom_provider(pname)
        remove_provider(pname)
        remove_models_for_provider(pname)
        rows = self._provider_rows()
        self._main_cursor = min(self._main_cursor, max(0, len(rows) - 1))
        self._panel = "main"
        if self._app:
            self._app.layout = self._build_layout()
            self._app.invalidate()

    def _toggle_provider_active(self, pname: str):
        if pname in _ALWAYS_ACTIVE:
            self._detail_status = "DeepSeek is always active."
            self._detail_status_style = "class:warning"
            if self._app:
                self._app.invalidate()
            return
        target = not is_provider_active(pname)
        ok, msg = _runtime_set_active(pname, target)
        if ok:
            self._detail_status = f"✅ {msg}"
            self._detail_status_style = "class:success"
        else:
            self._detail_status = f"✗ {msg}"
            self._detail_status_style = "class:error"
        if self._app:
            self._app.layout = self._build_layout()
            self._app.invalidate()

    def _cancel_model_selector(self, close: bool = False):
        if close:
            if self._app:
                self._app.exit()
            return
        self._panel = self._ms_caller
        self._detail_status = "Model sync cancelled."
        self._detail_status_style = "class:warning"
        if self._app:
            self._app.layout = self._build_layout()
            self._app.invalidate()

    def _do_save_models(self):
        pname = self._ms_provider
        models_cfg = {}
        alias_changes = []
        for mid in self._ms_selected:
            cfg = next((c for m, c in self._ms_all if m == mid), None)
            if cfg:
                alias = _candidate_save_alias(pname, mid, cfg)
                if alias != mid:
                    alias_changes.append((mid, alias))
                models_cfg[alias] = {**cfg, "provider": pname}
        prov_cfg = PROVIDERS.get(pname, {})
        save_custom_provider(pname, prov_cfg, models_cfg, replace_models=True)
        _record_sync_time(pname)
        _sync_models_to_runtime()
        self._detail_status = f"✅ Loaded {len(models_cfg)} model(s)."
        if alias_changes:
            self._detail_status += f" {len(alias_changes)} alias(es) prefixed."
        self._detail_status_style = "class:success"
        close_after_save = self._ms_save_exit
        self._ms_save_exit = False
        if close_after_save:
            if self._app:
                self._app.exit()
            return
        self._panel = self._ms_caller
        if self._app:
            self._app.layout = self._build_layout()
            self._app.invalidate()

    def _do_save_provider_no_test(self):
        if not self._wiz_fields_pending:
            return
        name, url, fmt, key, env_var = self._wiz_fields_pending
        _save_key_to_env(env_var, key)
        prov_cfg = {"base_url": url, "api_key_env": env_var,
                    "label": f"Custom ({name})", "api_format": fmt,
                    "active": False}
        save_custom_provider(name, prov_cfg, {})
        register_provider(name, prov_cfg)
        init_providers(force=True)
        self._panel = "main"
        if self._app:
            self._app.layout = self._build_layout()
            self._app.invalidate()

    async def _run_test_detail(self, pname: str):
        pinfo = _provider_snapshot().get(pname, {})
        key = _provider_key(pname)
        model_id = _first_provider_chat_model(pname)
        if not model_id:
            self._detail_status = "⚠ No chat models loaded. Use Fetch / Sync Models first."
            self._detail_status_style = "class:warning"
            if self._app:
                self._app.invalidate()
            return
        ok, msg, _ = await _test_connection(
            pinfo.get("base_url", ""), key, pinfo.get("api_format", "openai"), model_id)
        self._detail_status = f"✅ {msg}" if ok else f"✗ {msg}"
        self._detail_status_style = "class:success" if ok else "class:error"
        if self._app:
            self._app.invalidate()

    async def _open_model_selector(self, pname: str, caller: str):
        pinfo = _provider_snapshot().get(pname, {})
        key = _provider_key(pname)
        self._detail_status = "⟳ Fetching model list..."
        self._detail_status_style = "class:spinner"
        if self._app: self._app.invalidate()
        candidates, err, stats = await _fetch_models(
            pinfo.get("base_url", ""),
            key,
            pinfo.get("api_format", "openai"),
        )
        if err or not candidates:
            if err:
                self._detail_status = f"✗ Failed: {err}"
            else:
                summary = _format_model_sync_notice(stats, [])
                self._detail_status = f"✗ No selectable chat models. {summary[0]}"
            self._detail_status_style = "class:error"
            if self._app: self._app.invalidate()
            return
        # Bug 4: start all unchecked; pre-check only previously saved models
        existing = {
            str(m.get("id") or a)
            for a, m in _model_items_snapshot()
            if m.get("provider") == pname
        }
        self._ms_all = candidates
        self._ms_selected = {mid for mid, _ in candidates if mid in existing}
        self._ms_notice = _format_model_sync_notice(
            stats,
            _model_alias_changes(pname, candidates),
        )
        # do NOT pre-select all — user must choose
        self._ms_manual = []
        self._ms_cursor = 0; self._ms_viewport = 0
        self._ms_provider = pname; self._ms_caller = caller
        self._ms_error = ""; self._ms_search = ""; self._ms_search_focus = False
        self._ms_save_exit = False
        self._detail_status = ""
        self._panel = "models"
        if self._app:
            self._app.layout = self._build_layout()
            self._app.invalidate()

    async def _detail_action(self):
        pname = self._detail_provider
        cur = self._detail_cursor
        if cur == 0:
            self._dialog = "security"; self._dialog_cursor = 0
            if self._app:
                self._app.layout = self._build_layout()
                self._app.invalidate()
        elif cur == 1:
            await self._open_model_selector(pname, "detail")
        elif cur == 2:
            self._detail_status = "⟳ Testing..."
            self._detail_status_style = "class:spinner"
            if self._app: self._app.invalidate()
            await self._run_test_detail(pname)
            await asyncio.sleep(3)
            self._detail_status = ""
            if self._app: self._app.invalidate()
        elif cur == 3:  # Manage Models
            self._mm_provider = pname
            self._mm_models = [
                a for a, m in _model_items_snapshot() if m.get("provider") == pname
            ]
            self._mm_cursor = 0
            self._mm_status = ""
            self._mm_status_style = ""
            self._panel = "manage"
            if self._app:
                self._app.layout = self._build_layout()
                self._app.invalidate()
        elif cur == 4:
            self._toggle_provider_active(pname)
        elif cur == 5:  # Delete Provider
            if pname in _BUILTIN:
                self._detail_status = "Cannot delete built-in providers."
                self._detail_status_style = "class:warning"
                if self._app: self._app.invalidate()
            else:
                self._dialog = "delete"; self._dialog_cursor = 0
                if self._app:
                    self._app.layout = self._build_layout()
                    self._app.invalidate()

    async def _wizard_confirm(self):
        self._sync_wizard_fields_from_inputs()
        name, url, fmt, key = self._wiz_fields
        if not name:
            self._wiz_error = "Name is required."; self._app and self._app.invalidate(); return
        if name in PROVIDERS:
            self._wiz_error = "Name already exists."; self._app and self._app.invalidate(); return
        if not url:
            self._wiz_error = "Base URL is required."; self._app and self._app.invalidate(); return
        if not key:
            self._wiz_error = "API Key is required."; self._app and self._app.invalidate(); return

        self._wiz_error = ""
        env_var = f"{name.upper().replace('-','_').replace(' ','_')}_API_KEY"
        _save_key_to_env(env_var, key)
        prov_cfg = {"base_url": url, "api_key_env": env_var,
                    "label": f"Custom ({name})", "api_format": fmt,
                    "active": False}
        save_custom_provider(name, prov_cfg, {})
        register_provider(name, prov_cfg)
        init_providers(force=True)
        self._wiz_status = "✅ Saved inactive. Activate it from the detail panel to show models in /model."
        self._wiz_status_style = "class:success"
        self._panel = "main"
        if self._app:
            self._app.layout = self._build_layout()
            self._app.invalidate()

    # ── run ───────────────────────────────────────────────────────────────────

    async def run(self) -> None:
        kb = self._build_kb()
        self._app = Application(
            layout=self._build_layout(),
            key_bindings=kb,
            style=TUI_STYLE,
            mouse_support=False,
            full_screen=False,
        )
        await self._app.run_async()


async def run_provider_tui() -> None:
    await ProviderTUI().run()
