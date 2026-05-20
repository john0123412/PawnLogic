"""
core/provider_tui.py — Interactive TUI for Provider Management

4-panel stack: Main → Detail → AddWizard → ModelSelection
Dialogs: SecurityWarning, DeleteConfirm (floating overlays)
All UI text in English. API Keys never displayed in plain text.
"""
from __future__ import annotations
import asyncio, os, time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

# ── prompt_toolkit imports ────────────────────────────────────────────────────
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import (
    HSplit, VSplit, Window, FloatContainer, Float, ConditionalContainer,
)
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension as D
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea, Frame
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import StyleAndTextTuples

# ── project imports ───────────────────────────────────────────────────────────
from config.providers import (
    PROVIDERS, MODELS, CUSTOM_PROVIDERS_PATH,
    save_custom_provider, load_custom_providers, remove_custom_provider,
)

_PAWNLOGIC_DIR = Path.home() / ".pawnlogic"
_ENV_PATH = _PAWNLOGIC_DIR / ".env"
_BUILTIN = {"deepseek", "openai", "anthropic"}

_NOISE = {"embedding", "rerank", "tts", "whisper", "moderation", "davinci", "babbage"}

TUI_STYLE = Style.from_dict({
    "title":        "#00afff bold",
    "subtitle":     "#888888",
    "cursor":       "#00ff00 bold",
    "selected":     "#00ff00 bold",
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
})


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _mask_key(key: str) -> str:
    if not key:
        return "— Not Configured"
    if len(key) <= 8:
        return "••••••••"
    return f"{key[:4]}{'•' * 8}{key[-4:]}"


def _provider_key(pname: str) -> str:
    env_var = PROVIDERS.get(pname, {}).get("api_key_env", "")
    return os.getenv(env_var, "") if env_var else ""


def _model_count(pname: str) -> int:
    return sum(1 for m in MODELS.values() if m.get("provider") == pname)


def _last_synced(pname: str) -> str:
    """Return last-synced timestamp from custom_providers.json, or 'Never'."""
    if not CUSTOM_PROVIDERS_PATH.exists():
        return "Never"
    try:
        import json
        data = json.loads(CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8"))
        ts = data.get("sync_times", {}).get(pname)
        return ts if ts else "Never"
    except Exception:
        return "Never"


def _save_key_to_env(env_var: str, key: str) -> None:
    """Append/update KEY=value in ~/.pawnlogic/.env and inject into os.environ."""
    _PAWNLOGIC_DIR.mkdir(parents=True, exist_ok=True)
    existing = _ENV_PATH.read_text(encoding="utf-8") if _ENV_PATH.exists() else ""
    lines = existing.splitlines()
    new_lines = [l for l in lines if not l.startswith(f"{env_var}=")]
    new_lines.append(f"{env_var}={key}")
    _ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.environ[env_var] = key


def _record_sync_time(pname: str) -> None:
    import json, datetime
    _PAWNLOGIC_DIR.mkdir(parents=True, exist_ok=True)
    data: dict = {"providers": {}, "models": {}, "sync_times": {}}
    if CUSTOM_PROVIDERS_PATH.exists():
        try:
            data = json.loads(CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    data.setdefault("sync_times", {})[pname] = (
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    )
    CUSTOM_PROVIDERS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


async def _test_connection(base_url: str, api_key: str, api_format: str) -> tuple[bool, str, int]:
    """
    Send a minimal request. Returns (ok, message, ms).
    Does NOT require a registered model alias.
    """
    import httpx, json as _json
    t0 = time.monotonic()
    try:
        if api_format == "anthropic":
            payload = {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}],
            }
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
        else:
            payload = {
                "model": "gpt-3.5-turbo",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}],
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "content-type": "application/json",
            }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(base_url, json=payload, headers=headers)
        ms = int((time.monotonic() - t0) * 1000)
        if resp.status_code in (200, 400):
            # 400 can mean wrong model id but auth passed
            body = resp.json()
            if resp.status_code == 200 or "error" in body:
                return True, f"Connected ({ms}ms)", ms
        return False, f"HTTP {resp.status_code}: {resp.text[:120]}", ms
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return False, str(e)[:120], ms


async def _fetch_models(base_url: str, api_key: str) -> tuple[list[tuple[str, dict]], str]:
    """Returns (candidates, error_msg). candidates = [(id, cfg_dict), ...]"""
    import httpx
    parsed = urlparse(base_url)
    models_url = f"{parsed.scheme}://{parsed.netloc}/v1/models"
    all_data: list = []
    url = f"{models_url}?limit=200"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            while url:
                resp = await client.get(
                    url, headers={"Authorization": f"Bearer {api_key}"}
                )
                resp.raise_for_status()
                body = resp.json()
                all_data.extend(body.get("data", []))
                if not body.get("has_more"):
                    break
                cursor = body.get("next_cursor") or body.get("next_page")
                if not cursor:
                    break
                url = f"{models_url}?limit=200&after={cursor}"
    except Exception as e:
        return [], str(e)[:120]

    candidates = []
    for item in all_data:
        mid = item.get("id", "")
        if not mid or any(n in mid.lower() for n in _NOISE):
            continue
        vision = any(k in mid.lower() for k in ("vision", "vl", "visual"))
        candidates.append((mid, {
            "id": mid, "provider": "", "desc": "fetched",
            "color": "\033[37m", "vision": vision,
        }))
    return candidates, ""


# ══════════════════════════════════════════════════════════════════════════════
# ProviderTUI — main class
# ══════════════════════════════════════════════════════════════════════════════

class ProviderTUI:
    """
    Single Application instance. Panel navigation via _panel stack.
    Call await ProviderTUI().run() from an async context.
    """

    def __init__(self):
        self._app: Optional[Application] = None
        # panel stack: each entry is a string tag
        self._panel: str = "main"
        # shared state
        self._main_cursor: int = 0
        self._detail_provider: str = ""
        self._detail_cursor: int = 0          # 0-3 action items
        self._dialog: Optional[str] = None    # "security" | "delete" | None
        self._dialog_cursor: int = 0          # button index
        # add wizard state
        self._wiz_fields = ["", "", "openai", ""]  # name, url, format, key
        self._wiz_focus: int = 0
        self._wiz_fmt_open: bool = False
        self._wiz_fmt_cursor: int = 0         # 0=openai 1=anthropic
        self._wiz_error: str = ""
        self._wiz_status: str = ""            # spinner / result text
        self._wiz_status_style: str = ""
        # model selection state
        self._ms_entries: list[tuple[str, dict]] = []
        self._ms_selected: set[int] = set()
        self._ms_cursor: int = 0
        self._ms_provider: str = ""
        self._ms_caller: str = "main"         # panel to return to
        self._ms_error: str = ""
        # detail panel inline state
        self._detail_status: str = ""
        self._detail_status_style: str = ""
        self._detail_key_input_active: bool = False
        self._detail_key_ta: Optional[TextArea] = None
        # key input widget (reused)
        self._key_ta = TextArea(
            password=True, multiline=False, height=1,
            style="class:field-focus",
        )

    # ── provider list helper ──────────────────────────────────────────────────
    def _provider_rows(self) -> list[str]:
        return list(PROVIDERS.keys())

    # ══════════════════════════════════════════════════════════════════════════
    # RENDER FUNCTIONS
    # ══════════════════════════════════════════════════════════════════════════

    def _render_main(self) -> StyleAndTextTuples:
        rows = self._provider_rows()
        f: StyleAndTextTuples = []
        f.append(("class:title", "\n  🔌 Provider Manager\n\n"))
        if not rows:
            f.append(("class:subtitle", "  No providers configured. Press N to add one.\n"))
        for i, pname in enumerate(rows):
            key = _provider_key(pname)
            n_models = _model_count(pname)
            is_builtin = pname in _BUILTIN
            cursor = "▶ " if i == self._main_cursor else "  "
            badge = "[built-in]" if is_builtin else "[custom]"
            badge_style = "class:badge-builtin" if is_builtin else "class:badge-custom"
            if key:
                key_tag = ("class:key-ok", "  ✓ Key Set")
            else:
                key_tag = ("class:key-missing", "  ✗ Not Configured")
            cur_style = "class:cursor" if i == self._main_cursor else ""
            f.append((cur_style, f"  {cursor}"))
            f.append((cur_style, f"● {pname:<20}"))
            f.append(key_tag)
            f.append(("class:subtitle", f"  {n_models} models  "))
            f.append((badge_style, badge))
            f.append(("", "\n"))
        f.append(("", "\n"))
        return f

    def _render_status_main(self) -> StyleAndTextTuples:
        return [
            ("class:status-key", " ↑↓ "), ("class:status", "Move  "),
            ("class:status-key", "Enter "), ("class:status", "Manage  "),
            ("class:status-key", "N "), ("class:status", "Add  "),
            ("class:status-key", "D "), ("class:status", "Delete  "),
            ("class:status-key", "Q "), ("class:status", "Quit "),
        ]

    def _render_detail(self) -> StyleAndTextTuples:
        pname = self._detail_provider
        pinfo = PROVIDERS.get(pname, {})
        key = _provider_key(pname)
        n_models = _model_count(pname)
        synced = _last_synced(pname)
        fmt = pinfo.get("api_format", "openai")
        fmt_label = "Anthropic Compatible" if fmt == "anthropic" else "OpenAI Compatible"
        f: StyleAndTextTuples = []
        f.append(("class:title", f"\n  ◀ {pname}\n\n"))
        # info table
        f.append(("class:subtitle", f"  {'Name':<12}│ {pname}\n"))
        f.append(("class:subtitle", f"  {'Base URL':<12}│ {pinfo.get('base_url','')}\n"))
        f.append(("class:subtitle", f"  {'Format':<12}│ {fmt_label}\n"))
        if key:
            f.append(("class:subtitle", f"  {'API Key':<12}│ "))
            f.append(("class:key-ok", f"{_mask_key(key)}   ● Configured\n"))
        else:
            f.append(("class:subtitle", f"  {'API Key':<12}│ "))
            f.append(("class:key-missing", "— Not Configured\n"))
        f.append(("class:subtitle", f"  {'Models':<12}│ {n_models} loaded  (Last synced: {synced})\n"))
        # model preview
        model_names = [a for a, m in MODELS.items() if m.get("provider") == pname]
        if model_names:
            preview = model_names[:5]
            f.append(("class:subtitle", "               │ " + ", ".join(preview)))
            if len(model_names) > 5:
                f.append(("class:subtitle", f"  ... and {len(model_names)-5} more"))
            f.append(("", "\n"))
        f.append(("", "\n"))
        # key input area (shown when active)
        if self._detail_key_input_active:
            f.append(("class:warning", "  New API Key (input hidden):\n"))
        # action menu
        actions = [
            "Update API Key",
            "Fetch / Sync Models",
            "Test Connection",
            "Delete Provider",
        ]
        for i, act in enumerate(actions):
            if i == self._detail_cursor and not self._detail_key_input_active:
                f.append(("class:cursor", f"  ▶ [ {act} ]\n"))
            else:
                f.append(("class:subtitle", f"    [ {act} ]\n"))
        f.append(("", "\n"))
        # status line
        if self._detail_status:
            f.append((self._detail_status_style, f"  {self._detail_status}\n"))
        return f

    def _render_status_detail(self) -> StyleAndTextTuples:
        return [
            ("class:status-key", " ↑↓ "), ("class:status", "Move  "),
            ("class:status-key", "Enter "), ("class:status", "Execute  "),
            ("class:status-key", "Esc "), ("class:status", "Back "),
        ]

    def _render_wizard(self) -> StyleAndTextTuples:
        labels = ["Name", "Base URL", "Format", "API Key"]
        f: StyleAndTextTuples = []
        f.append(("class:title", "\n  ✚ Add Provider\n\n"))
        for i, label in enumerate(labels):
            focused = (i == self._wiz_focus)
            style = "class:field-focus" if focused else "class:field-normal"
            val = self._wiz_fields[i]
            if i == 3:  # key field — mask
                display = "•" * len(val) if val else ""
            elif i == 2:  # format
                display = "Anthropic Compatible" if val == "anthropic" else "OpenAI Compatible"
            else:
                display = val
            f.append((style, f"  {'①②③④'[i]} {label:<10} [ {display:<40} ]\n"))
            # inline format dropdown
            if i == 2 and focused and self._wiz_fmt_open:
                opts = ["OpenAI Compatible", "Anthropic Compatible"]
                for j, opt in enumerate(opts):
                    cur = "▶ " if j == self._wiz_fmt_cursor else "  "
                    s = "class:cursor" if j == self._wiz_fmt_cursor else "class:subtitle"
                    f.append((s, f"       {cur}{opt}\n"))
        f.append(("", "\n"))
        # confirm button
        btn_style = "class:btn-focus" if self._wiz_focus == 4 else "class:btn-normal"
        f.append((btn_style, "  [ Confirm & Test Connection ]\n\n"))
        if self._wiz_error:
            f.append(("class:error", f"  ✗ {self._wiz_error}\n"))
        if self._wiz_status:
            f.append((self._wiz_status_style, f"  {self._wiz_status}\n"))
        return f

    def _render_status_wizard(self) -> StyleAndTextTuples:
        return [
            ("class:status-key", " Tab "), ("class:status", "Next Field  "),
            ("class:status-key", "↑↓ "), ("class:status", "Move/Select  "),
            ("class:status-key", "Enter "), ("class:status", "Confirm  "),
            ("class:status-key", "Esc "), ("class:status", "Cancel "),
        ]

    def _render_model_select(self) -> StyleAndTextTuples:
        entries = self._ms_entries
        f: StyleAndTextTuples = []
        f.append(("class:title", f"\n  📦 Select Models — {self._ms_provider}\n"))
        f.append(("class:subtitle", f"  {len(entries)} models available. Choose which to load.\n\n"))
        for i, (mid, cfg) in enumerate(entries):
            checked = "✓" if i in self._ms_selected else " "
            cursor = "▶" if i == self._ms_cursor else " "
            vtag = " 📷" if cfg.get("vision") else ""
            style = "class:cursor" if i == self._ms_cursor else ""
            f.append((style, f"  {cursor} [{checked}] {mid}{vtag}\n"))
        f.append(("", f"\n  {len(self._ms_selected)} selected\n\n"))
        btn_style = "class:btn-focus" if self._ms_cursor == len(entries) else "class:btn-normal"
        f.append((btn_style, "  [ Load Selected Models ]\n"))
        if self._ms_error:
            f.append(("class:error", f"\n  ✗ {self._ms_error}\n"))
        return f

    def _render_status_ms(self) -> StyleAndTextTuples:
        return [
            ("class:status-key", " ↑↓ "), ("class:status", "Move  "),
            ("class:status-key", "Space "), ("class:status", "Toggle  "),
            ("class:status-key", "A "), ("class:status", "All  "),
            ("class:status-key", "C "), ("class:status", "Clear  "),
            ("class:status-key", "Enter "), ("class:status", "Confirm  "),
            ("class:status-key", "Esc "), ("class:status", "Cancel "),
        ]

    def _render_dialog_security(self) -> StyleAndTextTuples:
        f: StyleAndTextTuples = []
        f.append(("class:dialog-title", "  ⚠  Security Notice\n\n"))
        f.append(("class:dialog-body", "  Updating the API Key will clear the existing key.\n"))
        f.append(("class:dialog-body", "  You must paste the full key again.\n"))
        f.append(("class:dialog-body", "  The key will never be displayed in plain text.\n\n"))
        for i, btn in enumerate(["Continue", "Cancel"]):
            s = "class:btn-focus" if i == self._dialog_cursor else "class:btn-normal"
            f.append((s, f"  [ {btn} ]  "))
        f.append(("", "\n"))
        return f

    def _render_dialog_delete(self) -> StyleAndTextTuples:
        pname = self._detail_provider
        f: StyleAndTextTuples = []
        f.append(("class:dialog-title", "  🗑  Confirm Delete\n\n"))
        f.append(("class:dialog-body", f"  Delete provider '{pname}'? This cannot be undone.\n\n"))
        for i, btn in enumerate(["Cancel", "Delete"]):
            s = "class:btn-focus" if i == self._dialog_cursor else "class:btn-normal"
            f.append((s, f"  [ {btn} ]  "))
        f.append(("", "\n"))
        return f

    # ══════════════════════════════════════════════════════════════════════════
    # LAYOUT BUILDER
    # ══════════════════════════════════════════════════════════════════════════

    def _build_layout(self) -> Layout:
        def body_content():
            if self._panel == "main":
                return self._render_main()
            elif self._panel == "detail":
                return self._render_detail()
            elif self._panel == "wizard":
                return self._render_wizard()
            elif self._panel == "models":
                return self._render_model_select()
            return []

        def status_content():
            if self._panel == "main":
                return self._render_status_main()
            elif self._panel == "detail":
                return self._render_status_detail()
            elif self._panel == "wizard":
                return self._render_status_wizard()
            elif self._panel == "models":
                return self._render_status_ms()
            return []

        def dialog_content():
            if self._dialog == "security":
                return self._render_dialog_security()
            elif self._dialog == "delete":
                return self._render_dialog_delete()
            return []

        body = Window(content=FormattedTextControl(body_content), always_hide_cursor=True)
        status = Window(content=FormattedTextControl(status_content),
                        height=1, always_hide_cursor=True)

        # key input widget shown in detail panel when active
        key_input_container = ConditionalContainer(
            content=HSplit([
                Window(height=1),
                self._key_ta,
                Window(height=1),
            ]),
            filter=Condition(lambda: (
                self._panel == "detail" and self._detail_key_input_active
            )),
        )

        main_body = HSplit([body, key_input_container])

        dialog_float = Float(
            content=Frame(
                body=Window(
                    content=FormattedTextControl(dialog_content),
                    always_hide_cursor=True,
                ),
                width=56, height=10,
            ),
            transparent=True,
        )

        root = FloatContainer(
            content=HSplit([main_body, status]),
            floats=[dialog_float],
        )

        return Layout(root, focused_element=self._key_ta if (
            self._panel == "detail" and self._detail_key_input_active
        ) else body)

    # ══════════════════════════════════════════════════════════════════════════
    # KEY BINDINGS
    # ══════════════════════════════════════════════════════════════════════════

    def _build_kb(self) -> KeyBindings:
        kb = KeyBindings()

        def inv():
            if self._app:
                self._app.invalidate()

        # ── dialog bindings ───────────────────────────────────────────────────
        @kb.add("left",  filter=Condition(lambda: self._dialog is not None))
        @kb.add("right", filter=Condition(lambda: self._dialog is not None))
        @kb.add("tab",   filter=Condition(lambda: self._dialog is not None))
        def _dlg_move(event):
            n = 2
            self._dialog_cursor = (self._dialog_cursor + 1) % n
            inv()

        @kb.add("enter", filter=Condition(lambda: self._dialog is not None))
        def _dlg_enter(event):
            dlg = self._dialog
            cur = self._dialog_cursor
            self._dialog = None
            self._dialog_cursor = 0
            if dlg == "security":
                if cur == 0:  # Continue
                    self._detail_key_input_active = True
                    self._key_ta.text = ""
                    self._app.layout = self._build_layout()
            elif dlg == "delete":
                if cur == 1:  # Delete
                    self._do_delete_provider()
            inv()

        @kb.add("escape", filter=Condition(lambda: self._dialog is not None))
        def _dlg_esc(event):
            self._dialog = None
            self._dialog_cursor = 0
            inv()

        # ── key input (detail panel) ──────────────────────────────────────────
        @kb.add("enter", filter=Condition(lambda: (
            self._panel == "detail" and self._detail_key_input_active
            and self._dialog is None
        )))
        def _key_submit(event):
            new_key = self._key_ta.text.strip()
            self._detail_key_input_active = False
            if not new_key:
                self._detail_status = "Cancelled — no key entered."
                self._detail_status_style = "class:warning"
                self._app.layout = self._build_layout()
                inv()
                return
            pname = self._detail_provider
            env_var = PROVIDERS.get(pname, {}).get("api_key_env", "")
            if env_var:
                _save_key_to_env(env_var, new_key)
            self._detail_status = "✅ Key saved. Testing connection..."
            self._detail_status_style = "class:spinner"
            self._app.layout = self._build_layout()
            inv()
            asyncio.get_event_loop().create_task(self._run_test_detail(pname))

        @kb.add("escape", filter=Condition(lambda: (
            self._panel == "detail" and self._detail_key_input_active
            and self._dialog is None
        )))
        def _key_cancel(event):
            self._detail_key_input_active = False
            self._detail_status = ""
            self._app.layout = self._build_layout()
            inv()

        # ── main panel ────────────────────────────────────────────────────────
        _main_active = Condition(lambda: (
            self._panel == "main" and self._dialog is None
        ))

        @kb.add("up",    filter=_main_active)
        def _main_up(event):
            rows = self._provider_rows()
            if rows:
                self._main_cursor = (self._main_cursor - 1) % len(rows)
            inv()

        @kb.add("down",  filter=_main_active)
        def _main_down(event):
            rows = self._provider_rows()
            if rows:
                self._main_cursor = (self._main_cursor + 1) % len(rows)
            inv()

        @kb.add("enter", filter=_main_active)
        def _main_enter(event):
            rows = self._provider_rows()
            if rows and self._main_cursor < len(rows):
                self._detail_provider = rows[self._main_cursor]
                self._detail_cursor = 0
                self._detail_status = ""
                self._detail_key_input_active = False
                self._panel = "detail"
                self._app.layout = self._build_layout()
            inv()

        @kb.add("n", filter=_main_active)
        @kb.add("N", filter=_main_active)
        def _main_add(event):
            self._wiz_fields = ["", "", "openai", ""]
            self._wiz_focus = 0
            self._wiz_fmt_open = False
            self._wiz_error = ""
            self._wiz_status = ""
            self._panel = "wizard"
            self._app.layout = self._build_layout()
            inv()

        @kb.add("d", filter=_main_active)
        @kb.add("D", filter=_main_active)
        def _main_delete(event):
            rows = self._provider_rows()
            if not rows:
                return
            pname = rows[self._main_cursor]
            if pname in _BUILTIN:
                self._detail_status = "Cannot delete built-in providers."
                inv()
                return
            self._detail_provider = pname
            self._dialog = "delete"
            self._dialog_cursor = 0  # default: Cancel
            inv()

        @kb.add("q",      filter=_main_active)
        @kb.add("Q",      filter=_main_active)
        @kb.add("escape", filter=_main_active)
        def _main_quit(event):
            event.app.exit()

        # ── detail panel ──────────────────────────────────────────────────────
        _detail_active = Condition(lambda: (
            self._panel == "detail" and self._dialog is None
            and not self._detail_key_input_active
        ))

        @kb.add("up",    filter=_detail_active)
        def _det_up(event):
            self._detail_cursor = (self._detail_cursor - 1) % 4
            inv()

        @kb.add("down",  filter=_detail_active)
        def _det_down(event):
            self._detail_cursor = (self._detail_cursor + 1) % 4
            inv()

        @kb.add("enter", filter=_detail_active)
        def _det_enter(event):
            asyncio.get_event_loop().create_task(self._detail_action())

        @kb.add("escape", filter=_detail_active)
        def _det_esc(event):
            self._panel = "main"
            self._app.layout = self._build_layout()
            inv()

        # ── wizard panel ──────────────────────────────────────────────────────
        _wiz_active = Condition(lambda: (
            self._panel == "wizard" and self._dialog is None
        ))

        @kb.add("tab",       filter=_wiz_active)
        @kb.add("down",      filter=Condition(lambda: (
            self._panel == "wizard" and self._dialog is None
            and not (self._wiz_focus == 2 and self._wiz_fmt_open)
        )))
        def _wiz_next(event):
            self._wiz_fmt_open = False
            self._wiz_focus = (self._wiz_focus + 1) % 5  # 0-3 fields + 4 button
            inv()

        @kb.add("s-tab",  filter=_wiz_active)
        @kb.add("up",     filter=Condition(lambda: (
            self._panel == "wizard" and self._dialog is None
            and not (self._wiz_focus == 2 and self._wiz_fmt_open)
        )))
        def _wiz_prev(event):
            self._wiz_fmt_open = False
            self._wiz_focus = (self._wiz_focus - 1) % 5
            inv()

        # format field: open dropdown on enter/space
        @kb.add("enter", filter=Condition(lambda: (
            self._panel == "wizard" and self._wiz_focus == 2
            and not self._wiz_fmt_open and self._dialog is None
        )))
        @kb.add("space", filter=Condition(lambda: (
            self._panel == "wizard" and self._wiz_focus == 2
            and not self._wiz_fmt_open and self._dialog is None
        )))
        def _wiz_fmt_open_dd(event):
            self._wiz_fmt_open = True
            self._wiz_fmt_cursor = 0 if self._wiz_fields[2] == "openai" else 1
            inv()

        @kb.add("up", filter=Condition(lambda: (
            self._panel == "wizard" and self._wiz_focus == 2
            and self._wiz_fmt_open
        )))
        def _wiz_fmt_up(event):
            self._wiz_fmt_cursor = (self._wiz_fmt_cursor - 1) % 2
            inv()

        @kb.add("down", filter=Condition(lambda: (
            self._panel == "wizard" and self._wiz_focus == 2
            and self._wiz_fmt_open
        )))
        def _wiz_fmt_down(event):
            self._wiz_fmt_cursor = (self._wiz_fmt_cursor + 1) % 2
            inv()

        @kb.add("enter", filter=Condition(lambda: (
            self._panel == "wizard" and self._wiz_focus == 2
            and self._wiz_fmt_open
        )))
        @kb.add("space", filter=Condition(lambda: (
            self._panel == "wizard" and self._wiz_focus == 2
            and self._wiz_fmt_open
        )))
        def _wiz_fmt_confirm(event):
            self._wiz_fields[2] = "anthropic" if self._wiz_fmt_cursor == 1 else "openai"
            self._wiz_fmt_open = False
            inv()

        # confirm button
        @kb.add("enter", filter=Condition(lambda: (
            self._panel == "wizard" and self._wiz_focus == 4
            and not self._wiz_fmt_open and self._dialog is None
        )))
        def _wiz_confirm(event):
            asyncio.get_event_loop().create_task(self._wizard_confirm())

        @kb.add("escape", filter=_wiz_active)
        def _wiz_esc(event):
            self._panel = "main"
            self._app.layout = self._build_layout()
            inv()

        # character input for wizard text fields (0=name, 1=url, 3=key)
        @kb.add("<any>", filter=Condition(lambda: (
            self._panel == "wizard" and self._wiz_focus in (0, 1, 3)
            and self._dialog is None and not self._wiz_fmt_open
        )))
        def _wiz_char(event):
            key_str = event.key_sequence[0].key
            if len(key_str) == 1:
                self._wiz_fields[self._wiz_focus] += key_str
            elif key_str == "backspace" or key_str == "c-h":
                self._wiz_fields[self._wiz_focus] = self._wiz_fields[self._wiz_focus][:-1]
            inv()

        # ── model selection panel ─────────────────────────────────────────────
        _ms_active = Condition(lambda: self._panel == "models")

        @kb.add("up",    filter=_ms_active)
        def _ms_up(event):
            total = len(self._ms_entries) + 1  # +1 for confirm button
            self._ms_cursor = (self._ms_cursor - 1) % total
            inv()

        @kb.add("down",  filter=_ms_active)
        def _ms_down(event):
            total = len(self._ms_entries) + 1
            self._ms_cursor = (self._ms_cursor + 1) % total
            inv()

        @kb.add("space", filter=_ms_active)
        def _ms_space(event):
            if self._ms_cursor < len(self._ms_entries):
                if self._ms_cursor in self._ms_selected:
                    self._ms_selected.discard(self._ms_cursor)
                else:
                    self._ms_selected.add(self._ms_cursor)
            inv()

        @kb.add("a", filter=_ms_active)
        @kb.add("A", filter=_ms_active)
        def _ms_all(event):
            self._ms_selected = set(range(len(self._ms_entries)))
            inv()

        @kb.add("c", filter=_ms_active)
        @kb.add("C", filter=_ms_active)
        def _ms_clear(event):
            self._ms_selected.clear()
            inv()

        @kb.add("enter", filter=_ms_active)
        def _ms_enter(event):
            if self._ms_cursor == len(self._ms_entries) or True:
                if not self._ms_selected:
                    self._ms_error = "Select at least one model."
                    inv()
                    return
                self._ms_error = ""
                self._do_save_models()

        @kb.add("escape", filter=_ms_active)
        def _ms_esc(event):
            self._panel = self._ms_caller
            self._app.layout = self._build_layout()
            inv()

        return kb

    # ══════════════════════════════════════════════════════════════════════════
    # ACTIONS
    # ══════════════════════════════════════════════════════════════════════════

    def _do_delete_provider(self):
        pname = self._detail_provider
        if pname in _BUILTIN:
            return
        remove_custom_provider(pname)
        if pname in PROVIDERS:
            del PROVIDERS[pname]
        to_rm = [a for a, m in list(MODELS.items()) if m.get("provider") == pname]
        for a in to_rm:
            del MODELS[a]
        rows = self._provider_rows()
        self._main_cursor = min(self._main_cursor, max(0, len(rows) - 1))
        self._panel = "main"
        if self._app:
            self._app.layout = self._build_layout()
            self._app.invalidate()

    def _do_save_models(self):
        pname = self._ms_provider
        chosen = [self._ms_entries[i] for i in sorted(self._ms_selected)]
        models_cfg = {}
        for mid, cfg in chosen:
            models_cfg[mid] = {**cfg, "provider": pname}
        prov_cfg = PROVIDERS.get(pname, {})
        save_custom_provider(pname, prov_cfg, models_cfg)
        _record_sync_time(pname)
        load_custom_providers()
        self._panel = self._ms_caller
        if self._app:
            self._app.layout = self._build_layout()
            self._app.invalidate()

    async def _run_test_detail(self, pname: str):
        pinfo = PROVIDERS.get(pname, {})
        key = _provider_key(pname)
        ok, msg, ms = await _test_connection(
            pinfo.get("base_url", ""), key, pinfo.get("api_format", "openai")
        )
        self._detail_status = f"✅ {msg}" if ok else f"✗ {msg}"
        self._detail_status_style = "class:success" if ok else "class:error"
        if self._app:
            self._app.invalidate()

    async def _detail_action(self):
        pname = self._detail_provider
        cur = self._detail_cursor
        if cur == 0:  # Update API Key
            self._dialog = "security"
            self._dialog_cursor = 0
        elif cur == 1:  # Fetch / Sync Models
            self._detail_status = "⟳ Fetching model list..."
            self._detail_status_style = "class:spinner"
            if self._app:
                self._app.invalidate()
            pinfo = PROVIDERS.get(pname, {})
            key = _provider_key(pname)
            candidates, err = await _fetch_models(pinfo.get("base_url", ""), key)
            if err or not candidates:
                self._detail_status = f"✗ Failed: {err or 'No models returned'}"
                self._detail_status_style = "class:error"
            else:
                # pre-check already loaded models
                existing = {a for a, m in MODELS.items() if m.get("provider") == pname}
                self._ms_entries = candidates
                self._ms_selected = {
                    i for i, (mid, _) in enumerate(candidates) if mid in existing
                }
                if not self._ms_selected:
                    self._ms_selected = set(range(len(candidates)))
                self._ms_cursor = 0
                self._ms_provider = pname
                self._ms_caller = "detail"
                self._ms_error = ""
                self._detail_status = ""
                self._panel = "models"
                if self._app:
                    self._app.layout = self._build_layout()
        elif cur == 2:  # Test Connection
            self._detail_status = "⟳ Testing..."
            self._detail_status_style = "class:spinner"
            if self._app:
                self._app.invalidate()
            await self._run_test_detail(pname)
            await asyncio.sleep(3)
            self._detail_status = ""
            if self._app:
                self._app.invalidate()
        elif cur == 3:  # Delete
            if pname in _BUILTIN:
                self._detail_status = "Cannot delete built-in providers."
                self._detail_status_style = "class:warning"
            else:
                self._dialog = "delete"
                self._dialog_cursor = 0
        if self._app:
            self._app.invalidate()

    async def _wizard_confirm(self):
        name, url, fmt, key = self._wiz_fields
        # validate
        if not name:
            self._wiz_error = "Name is required."
            if self._app: self._app.invalidate()
            return
        if name in PROVIDERS:
            self._wiz_error = "Name already exists. Choose a different name."
            if self._app: self._app.invalidate()
            return
        if not url:
            self._wiz_error = "Base URL is required."
            if self._app: self._app.invalidate()
            return
        if not key:
            self._wiz_error = "API Key is required."
            if self._app: self._app.invalidate()
            return

        self._wiz_error = ""
        self._wiz_status = "⟳ Testing connection..."
        self._wiz_status_style = "class:spinner"
        if self._app: self._app.invalidate()

        ok, msg, ms = await _test_connection(url, key, fmt)

        env_var = f"{name.upper().replace('-','_').replace(' ','_')}_API_KEY"

        if ok:
            self._wiz_status = f"✅ {msg}"
            self._wiz_status_style = "class:success"
            if self._app: self._app.invalidate()
            # save
            _save_key_to_env(env_var, key)
            prov_cfg = {
                "base_url": url, "api_key_env": env_var,
                "label": f"Custom ({name})", "api_format": fmt,
            }
            save_custom_provider(name, prov_cfg, {})
            PROVIDERS[name] = prov_cfg
            load_custom_providers()
            # fetch models?
            await asyncio.sleep(0.8)
            self._wiz_status = "Fetching model list..."
            if self._app: self._app.invalidate()
            candidates, err = await _fetch_models(url, key)
            if candidates:
                self._ms_entries = candidates
                self._ms_selected = set(range(len(candidates)))
                self._ms_cursor = 0
                self._ms_provider = name
                self._ms_caller = "main"
                self._ms_error = ""
                self._panel = "models"
            else:
                self._panel = "main"
            if self._app:
                self._app.layout = self._build_layout()
                self._app.invalidate()
        else:
            self._wiz_status = f"✗ Connection failed: {msg}"
            self._wiz_status_style = "class:error"
            if self._app: self._app.invalidate()
            # save anyway? — handled via a simple inline prompt
            # We repurpose dialog_cursor: 0=No 1=Yes
            self._dialog = "save_anyway"
            self._dialog_cursor = 0
            self._wiz_fields_pending = (name, url, fmt, key, env_var)
            if self._app: self._app.invalidate()

    # ══════════════════════════════════════════════════════════════════════════
    # RUN
    # ══════════════════════════════════════════════════════════════════════════

    async def run(self) -> None:
        if not _HAS_PROMPT_TOOLKIT:
            # non-TTY fallback
            from config.providers import PROVIDERS as P
            print("Providers:", list(P.keys()))
            return

        # handle save_anyway dialog (not in _build_layout floats — use enter binding)
        kb = self._build_kb()

        # extra: save_anyway dialog
        @kb.add("enter", filter=Condition(lambda: self._dialog == "save_anyway"))
        def _sa_enter(event):
            cur = self._dialog_cursor
            self._dialog = None
            if cur == 1:  # Yes
                name, url, fmt, key, env_var = self._wiz_fields_pending
                _save_key_to_env(env_var, key)
                prov_cfg = {
                    "base_url": url, "api_key_env": env_var,
                    "label": f"Custom ({name})", "api_format": fmt,
                }
                save_custom_provider(name, prov_cfg, {})
                PROVIDERS[name] = prov_cfg
                load_custom_providers()
                self._panel = "main"
            else:
                self._wiz_status = ""
            if self._app:
                self._app.layout = self._build_layout()
                self._app.invalidate()

        @kb.add("left",  filter=Condition(lambda: self._dialog == "save_anyway"))
        @kb.add("right", filter=Condition(lambda: self._dialog == "save_anyway"))
        @kb.add("tab",   filter=Condition(lambda: self._dialog == "save_anyway"))
        def _sa_move(event):
            self._dialog_cursor = (self._dialog_cursor + 1) % 2
            if self._app: self._app.invalidate()

        @kb.add("escape", filter=Condition(lambda: self._dialog == "save_anyway"))
        def _sa_esc(event):
            self._dialog = None
            self._wiz_status = ""
            if self._app: self._app.invalidate()

        self._app = Application(
            layout=self._build_layout(),
            key_bindings=kb,
            style=TUI_STYLE,
            mouse_support=False,
            full_screen=False,
        )
        await self._app.run_async()


# ── module-level entry point ──────────────────────────────────────────────────
async def run_provider_tui() -> None:
    await ProviderTUI().run()
