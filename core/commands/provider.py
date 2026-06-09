"""
API key, provider and model selection commands.

Migrated from main.py's _legacy_slash_dispatch in stage-1 step 4.

Commands in this module:
    /setkey                       run the interactive key configuration wizard
    /keys                         show API key status for every provider
    /provider [sub] [args]        TUI / list / add / fetch / update / activate / deactivate / remove / test
    /model [alias]                switch the session's model (interactive picker)

Module-private helpers (provider/key/model setup; only used by these
commands and by main.py's startup wizard, which imports `_run_key_wizard`,
`_visible_models` and `_write_key_to_shell` from here):

    _detect_shell_config       detect ~/.bashrc, ~/.zshrc, etc.
    _write_key_to_shell        append `export KEY=...` to shell config
    _run_key_wizard            interactive first-run / /setkey wizard
    _visible_models            MODELS subset whose provider is active and key is configured

    _handle_provider_cmd       dispatcher for /provider sub-commands
    _provider_list             display all providers and their key status
    _provider_add              interactive: add a custom provider
    _provider_add_cli          non-interactive: /provider add <a> <url> <env>
    _provider_set_active       show or hide a provider's models in /model
    _provider_remove           remove a custom provider
    _provider_test             smoke-test an API connection
    _fetch_models_paginated    GET /v1/models with pagination
    _provider_fetch_selector   prompt_toolkit multi-select UI
    _provider_fetch            fetch + register models from a provider

    cc_style_model_selector    Claude-Code-style inline model picker
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from prompt_toolkit import prompt as ptk_prompt

from config import (
    CUSTOM_PROVIDERS_PATH, MODELS, PROVIDERS,
    get_api_format, get_provider_config, list_vision_models,
    is_provider_active,
    models_url_from_base_url,
    remove_custom_provider, save_custom_provider,
    set_provider_active,
    validate_api_key,
)
from config.paths import VERSION
from core.logger import logger
from utils.ansi import (
    c, cp, BOLD, CYAN, GRAY, GREEN, MAGENTA, RED, YELLOW,
)
from utils.key_utils import mask_key

from core.commands import CommandContext, register


# ────────────────────────────────────────────────────────
# prompt_toolkit availability (mirrors the detection in main.py)
# ────────────────────────────────────────────────────────
try:
    from prompt_toolkit.styles import Style as _PTStyle  # noqa: F401
    _HAS_PROMPT_TOOLKIT = True
except ImportError:
    _HAS_PROMPT_TOOLKIT = False
    _PTStyle = None  # type: ignore


# ────────────────────────────────────────────────────────
# Path constants (shared layout — same as main.py)
# ────────────────────────────────────────────────────────
from config.paths import PAWNLOGIC_HOME

_PAWNLOGIC_DIR = PAWNLOGIC_HOME
_ENV_PATH = _PAWNLOGIC_DIR / ".env"


# ════════════════════════════════════════════════════════
# Key wizard
# ════════════════════════════════════════════════════════

# (number label, env_var, label, hint, whether the key can be skipped)
_WIZARD_PROVIDERS = [
    ("1", "PAWN_API_KEY",       "PawnLogic Engine",  "hermes · hermes405",                  False),
    ("2", "DEEPSEEK_API_KEY",   "DeepSeek",          "ds-v4-flash / ds-v4-pro",             False),
    ("3", "OPENROUTER_API_KEY", "OpenRouter",        "multi-model routing, includes gpt-4o vision", False),
    ("4", "SILICON_API_KEY",    "SiliconFlow",       "ds-coder, qwen, and regional models",         False),
    ("5", "ZHIPU_API_KEY",      "ZhipuAI",           "glm-4v-plus vision with regional access",     False),
    ("6", "XIAOMI_API_KEY",     "Xiaomi MiMo",       "mimo-v2.5-pro · mimo-v2-omni",        False),
    ("7", "ANTHROPIC_API_KEY",  "Anthropic",         "claude-opus-4-7 · claude-sonnet-4-6", False),
    ("8", None,                 "Local Ollama",      "run ollama serve first; no key needed", True),
]


def _detect_shell_config() -> Path | None:
    """Detect the user's shell configuration file."""
    shell = os.environ.get("SHELL", "")
    home = Path.home()
    if "zsh" in shell and (home / ".zshrc").exists():
        return home / ".zshrc"
    if "bash" in shell:
        for f in [".bashrc", ".bash_profile", ".profile"]:
            if (home / f).exists():
                return home / f
        return home / ".bashrc"   # create if needed
    return home / ".bashrc"


def _write_key_to_shell(env_var: str, key: str) -> str:
    """Append an export line to the shell config and inject os.environ."""
    cfg_file = _detect_shell_config()
    export_line = f'\nexport {env_var}="{key}"\n'

    existing = ""
    if cfg_file and cfg_file.exists():
        try:
            existing = cfg_file.read_text(encoding="utf-8")
        except Exception:
            pass

    if env_var not in existing:
        try:
            with open(str(cfg_file), "a", encoding="utf-8") as f:
                f.write(export_line)
        except Exception as e:
            return f"write failed: {e}"

    os.environ[env_var] = key
    return str(cfg_file)


def _run_key_wizard() -> bool:
    """Interactive setup wizard shown when no API key is configured.
    Return True when at least one key was configured.
    """
    print(f"""
{c(BOLD+CYAN, "╔════════════════════════════════════════════════╗")}
{c(BOLD+CYAN, "║")}  {c(BOLD, f"PawnLogic {VERSION}")} - First-Run Setup Wizard     {c(BOLD+CYAN,"║")}
{c(BOLD+CYAN, "╚════════════════════════════════════════════════╝")}

{c(YELLOW,"⚠  No API key was detected.")}
Select providers to configure. You can run this multiple times:

""")

    for num, env_var, label, hint, no_key in _WIZARD_PROVIDERS:
        already = ""
        if env_var and os.environ.get(env_var):
            already = c(GREEN, "  [configured ✓]")
        print(f"  {c(CYAN, f'[{num}]')} {c(BOLD, f'{label:18}')} {c(GRAY, hint)}{already}")

    print(f"\n  {c(GRAY, '[0]')} Skip for now. Configure later with export KEY=sk-... or /setkey.")
    print()

    configured_any = False

    while True:
        try:
            choice = input(cp(BOLD, "  Enter number(s), e.g. 1 5: ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if choice == "0" or not choice:
            break

        selected = [s.strip() for s in choice.split() if s.strip()]

        for sel in selected:
            matched = next((p for p in _WIZARD_PROVIDERS if p[0] == sel), None)
            if not matched:
                print(c(RED, f"  ✗ Invalid selection '{sel}'"))
                continue

            num, env_var, label, hint, no_key = matched

            if no_key:
                local_url = input(
                    c(GRAY, "  Ollama API URL [default: http://localhost:11434/v1/chat/completions]: ")
                ).strip()
                if local_url:
                    os.environ["LOCAL_API_URL"] = local_url
                    _write_key_to_shell("LOCAL_API_URL", local_url)
                print(c(GREEN, "  ✓ Ollama configured. Make sure ollama serve is running."))
                configured_any = True
                continue

            print(c(GRAY, f"\n  Get a {label} key:"))
            _KEY_URLS = {
                "PAWN_API_KEY":       "https://portal.nousresearch.com/api-keys",
                "DEEPSEEK_API_KEY":   "https://platform.deepseek.com/api_keys",
                "OPENROUTER_API_KEY": "https://openrouter.ai/keys",
                "SILICON_API_KEY":    "https://cloud.siliconflow.cn/account/ak",
                "ZHIPU_API_KEY":      "https://open.bigmodel.cn/usercenter/apikeys",
                "XIAOMI_API_KEY":     "https://token-plan-cn.xiaomimimo.com",
                "ANTHROPIC_API_KEY":  "https://console.anthropic.com/settings/keys",
            }
            url = _KEY_URLS.get(env_var, "")
            if url:
                print(c(CYAN, f"  Key URL: {url}"))

            try:
                key = ptk_prompt(f"  Paste {env_var} and press Enter: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                continue

            if not key:
                print(c(YELLOW, "  Skipped: no value entered."))
                continue

            written_to = _write_key_to_shell(env_var, key)
            print(c(GREEN, f"  ✓ {env_var} saved -> {written_to}"))
            print(c(GRAY,  "  Injected into the current process; no terminal restart needed."))
            configured_any = True

        try:
            cont = input(cp(GRAY, "  Configure more providers? [y/N]: ")).strip().lower()
            if cont != "y":
                break
        except (EOFError, KeyboardInterrupt):
            break

    if not configured_any:
        print(c(YELLOW, "\n  No key configured. Use /setkey after startup to configure one.\n"))

    return configured_any


# ════════════════════════════════════════════════════════
# Visible models helper
# ════════════════════════════════════════════════════════

def _visible_models() -> dict:
    """Return keyed models whose providers are active in the current process."""
    return {
        alias: cfg
        for alias, cfg in MODELS.items()
        if is_provider_active(cfg.get("provider", ""))
        and os.getenv(PROVIDERS.get(cfg.get("provider", ""), {}).get("api_key_env", ""), "")
    }


# ════════════════════════════════════════════════════════
# Provider management — list / add / remove / test / fetch
# ════════════════════════════════════════════════════════

def _provider_list() -> None:
    """List provider status for the human-readable provider sub-command path.

    The JSON path reads the process-level active sink. If it is a JsonSink,
    emit structured data; otherwise keep the colored table output.
    """
    from core.commands._common import get_active_sink
    from core.output import JsonSink
    sink = get_active_sink()
    if isinstance(sink, JsonSink):
        data = []
        for pname, pinfo in PROVIDERS.items():
            env = pinfo.get("api_key_env", "")
            models_for_provider = [
                alias for alias, m in MODELS.items()
                if m.get("provider", "") == pname
            ]
            data.append({
                "name":       pname,
                "label":      pinfo.get("label", pname),
                "api_format": pinfo.get("api_format", "openai"),
                "base_url":   pinfo.get("base_url", ""),
                "key_env":    env,
                "key_set":    bool(os.environ.get(env, "")) if env else True,
                "active":     is_provider_active(pname),
                "models":     models_for_provider,
            })
        sink.print_json(data)
        return

    print(c(BOLD, "\n  Providers:"))
    for pname, pinfo in PROVIDERS.items():
        fmt = pinfo.get("api_format", "openai")
        label = pinfo.get("label", pname)
        env = pinfo.get("api_key_env", "")
        val = os.environ.get(env, "") if env else ""
        if val:
            ktag = c(GREEN, f"✓ ({mask_key(val)})")
        elif not env:
            ktag = c(GRAY, "No key required")
        else:
            ktag = c(RED, "✗ Not configured")
        fmt_tag = c(MAGENTA, "[Anthropic]") if fmt == "anthropic" else c(GRAY, "[OpenAI]")
        active_tag = c(GREEN, "active") if is_provider_active(pname) else c(GRAY, "inactive")
        hint = pinfo.get("models_hint", "")
        print(f"  {c(CYAN, f'{pname:16}')}{fmt_tag:14} {label:24} {ktag}  {active_tag}")
        if hint:
            print(f"  {'':16}{c(GRAY, hint)}")
    print(c(GRAY, f"\n  Custom config: {CUSTOM_PROVIDERS_PATH}"))
    print()


def _provider_set_active(alias: str, active: bool) -> None:
    if not alias:
        verb = "activate" if active else "deactivate"
        print(c(RED, f"  Usage: /provider {verb} <name>"))
        return
    if alias not in PROVIDERS:
        print(c(RED, f"  ✗ Provider not found: {alias}"))
        return
    if alias == "deepseek" and not active:
        print(c(YELLOW, "  ⚠ deepseek is the default provider and always stays active."))
        return
    if not set_provider_active(alias, active):
        print(c(RED, f"  ✗ Failed to update provider state: {alias}"))
        return
    state = "active" if active else "inactive"
    print(c(GREEN, f"  ✓ Provider '{alias}' is now {state}."))


def _provider_add() -> None:
    """Interactively add a custom provider."""
    print(c(BOLD, "\n  Add Custom Provider"))
    print(c(GRAY, "  Keys are stored in .env; provider config is stored in ~/.pawnlogic/custom_providers.json.\n"))

    try:
        name = input(cp(BOLD, "  Provider name (short ID, e.g. my_relay): ")).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if not name or name in PROVIDERS:
        print(c(RED, f"  ✗ Invalid or duplicate provider name: {name}"))
        return

    print(f"\n  {c(BOLD, 'API format:')}")
    print(f"    {c(CYAN, '[1]')} OpenAI Chat Completions format")
    print(f"    {c(CYAN, '[2]')} Anthropic Messages format")
    try:
        fmt_choice = input(cp(BOLD, "  Select [1/2]: ")).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    api_format = "anthropic" if fmt_choice == "2" else "openai"

    try:
        base_url = input(cp(BOLD, "  Base URL (e.g. https://api.example.com/v1/chat/completions): ")).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if not base_url:
        print(c(RED, "  ✗ URL cannot be empty."))
        return

    env_var_name = f"{name.upper().replace('-', '_')}_API_KEY"
    try:
        key = ptk_prompt(f"  Paste API key and press Enter; it will be stored in .env -> {env_var_name}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if key:
        env_path = _ENV_PATH
        env_line = f'\n{env_var_name}="{key}"\n'
        try:
            existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
            if env_var_name not in existing:
                env_path.write_text(existing + env_line, encoding="utf-8")
            os.environ[env_var_name] = key
        except Exception:
            os.environ[env_var_name] = key
        _write_key_to_shell(env_var_name, key)
        print(c(GREEN, f"  ✓ Key saved -> .env ({env_var_name})"))

    prov_cfg = {
        "base_url":    base_url,
        "api_key_env": env_var_name,
        "label":       f"Custom ({name})",
        "api_format":  api_format,
    }

    save_custom_provider(name, prov_cfg, {})
    PROVIDERS[name] = prov_cfg

    print(c(GREEN, f"\n  ✓ Provider '{name}' added."))
    print(c(GRAY,  f"    Format: {api_format}"))
    print(c(GRAY,  f"    URL:  {base_url}"))
    print(c(GRAY,  f"    Config: {CUSTOM_PROVIDERS_PATH}"))
    print(c(CYAN,  f"    Next: run /provider fetch {name} to fetch the model list."))
    print()


def _provider_remove(name: str = "") -> None:
    """Remove a custom provider."""
    if not name:
        if not CUSTOM_PROVIDERS_PATH.exists():
            print(c(GRAY, "\n  No custom providers."))
            return
        try:
            data = json.loads(CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8"))
        except Exception:
            print(c(RED, "\n  ✗ Failed to read the config file."))
            return
        custom = list(data.get("providers", {}).keys())
        if not custom:
            print(c(GRAY, "\n  No custom providers."))
            return
        print(c(BOLD, "\n  Custom Providers:"))
        for i, n in enumerate(custom, 1):
            print(f"    {c(CYAN, f'[{i}]')} {n}")
        try:
            choice = input(cp(BOLD, "  Enter index or name: ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if choice.isdigit() and 1 <= int(choice) <= len(custom):
            name = custom[int(choice) - 1]
        elif choice in custom:
            name = choice
        else:
            print(c(RED, f"  ✗ Invalid selection: {choice}"))
            return

    if remove_custom_provider(name):
        if name in PROVIDERS:
            del PROVIDERS[name]
        to_remove = [a for a, m in MODELS.items() if m.get("provider") == name]
        for a in to_remove:
            del MODELS[a]
        print(c(GREEN, f"  ✓ Removed provider '{name}'"))
    else:
        print(c(RED, f"  ✗ Custom provider not found: {name}"))


def _provider_test(session, model_alias: str = "") -> None:
    """Test provider connectivity."""
    if not model_alias:
        try:
            model_alias = input(cp(BOLD, "  Enter model alias to test: ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
    if model_alias not in MODELS:
        print(c(RED, f"  ✗ Unknown model: {model_alias}"))
        return

    ok, env = validate_api_key(model_alias)
    if not ok:
        print(c(RED, f"  ✗ {env} is not configured. Use /setkey or /provider add."))
        return

    cfg = get_provider_config(model_alias)
    print(c(GRAY, f"  Testing {model_alias} ({cfg['api_format']}) -> {cfg['base_url']} ..."))
    print(c(GRAY, "  Sending a max_tokens=1 test request..."))

    from core.api_client import call_once
    text, err = call_once(
        [{"role": "user", "content": "Say OK"}],
        model_alias, max_tokens=1,
    )
    if err:
        print(c(RED, f"  ✗ Test failed: {err}"))
    else:
        print(c(GREEN, f"  ✓ Connection succeeded. Response: {text[:80]}"))


def _provider_add_cli(alias: str, base_url: str, env_key: str, api_format: str = "openai") -> bool:
    """Non-interactive: /provider add <alias> <base_url> <ENV_KEY> [anthropic]."""
    from config.providers import save_custom_provider as _save_cp, load_custom_providers
    if alias in PROVIDERS:
        print(c(YELLOW, f"  ⚠ Provider '{alias}' already exists; config will be overwritten."))
    fmt = api_format if api_format in ("openai", "anthropic") else "openai"
    prov_cfg = {
        "base_url":    base_url,
        "api_key_env": env_key,
        "label":       f"Custom ({alias})",
        "api_format":  fmt,
        "active":      False,
    }
    _save_cp(alias, prov_cfg, {})
    PROVIDERS[alias] = prov_cfg
    load_custom_providers()
    print(c(GREEN, f"  ✓ Provider registered. Make sure {env_key} is configured in .env."))
    print(c(CYAN, f"  To show it in /model, run /provider activate {alias}."))
    if not os.getenv(env_key, ""):
        print(c(CYAN, f"  Next: run /provider fetch {alias} to fetch models."))
        return False
    if not sys.stdin.isatty():
        print(c(CYAN, f"  Next: run /provider fetch {alias} to fetch models."))
        return False
    try:
        ans = input(cp(BOLD, f"  Fetch {alias} models now? [Y/n]: ")).strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = "n"
    return ans in ("", "y")


def _fetch_models_paginated(models_url: str, api_key: str) -> list:
    """Request /v1/models with pagination and return all model entries."""
    import httpx
    all_data: list = []
    url = f"{models_url}?limit=200"
    while url:
        resp = httpx.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        all_data.extend(body.get("data", []))
        if not body.get("has_more"):
            break
        cursor = body.get("next_cursor") or body.get("next_page")
        if not cursor:
            break
        url = f"{models_url}?limit=200&after={cursor}"
    return all_data


async def _provider_fetch_selector(entries: list[tuple[str, dict]]) -> list[str]:
    """prompt_toolkit multi-select menu. Space toggles, Enter confirms, Esc cancels.
    Return the selected model IDs.
    """
    if not _HAS_PROMPT_TOOLKIT:
        return [mid for mid, _ in entries]

    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.containers import Window

    selected: set[int] = set(range(len(entries)))
    cursor_idx = 0

    def get_fragments():
        frags = []
        frags.append(("class:title", f"  Select models to register ({len(entries)} total)\n"))
        frags.append(("class:desc",  "  Space toggle  Up/Down move  A all  N none  Enter confirm  Esc cancel\n\n"))

        for i, (mid, cfg) in enumerate(entries):
            checked = "●" if i in selected else "○"
            cursor = "❯ " if i == cursor_idx else "  "
            vtag = " 📷" if cfg.get("vision") else ""
            style = "class:selected" if i == cursor_idx else ""
            frags.append((style, f"  {cursor}{checked} {mid}{vtag}\n"))
        frags.append(("", f"\n  Selected {len(selected)}/{len(entries)}\n"))
        return frags

    control = FormattedTextControl(get_fragments)
    kb = KeyBindings()

    @kb.add("up")
    def _(e):
        nonlocal cursor_idx
        cursor_idx = (cursor_idx - 1) % len(entries)

    @kb.add("down")
    def _(e):
        nonlocal cursor_idx
        cursor_idx = (cursor_idx + 1) % len(entries)

    @kb.add("space")
    def _(e):
        if cursor_idx in selected:
            selected.discard(cursor_idx)
        else:
            selected.add(cursor_idx)

    @kb.add("a")
    def _(e):
        selected.update(range(len(entries)))

    @kb.add("n")
    def _(e):
        selected.clear()

    @kb.add("enter")
    def _(e):
        e.app.exit(result=[entries[i][0] for i in sorted(selected)])

    @kb.add("escape")
    @kb.add("c-c")
    def _(e):
        e.app.exit(result=[])

    style = _PTStyle.from_dict({
        "title":    "#00afff bold",
        "desc":     "#888888",
        "selected": "#00ff00 bold",
    })
    app = Application(
        layout=Layout(Window(content=control, always_hide_cursor=True)),
        key_bindings=kb,
        style=style,
        mouse_support=False,
        full_screen=False,
    )
    return await app.run_async()


async def _provider_fetch(alias: str) -> None:
    """/provider fetch <alias>: fetch /v1/models with pagination and register selections."""
    from core.provider_tui import (
        _filter_supported_chat_models,
        _format_alias_preview,
        _model_alias_changes,
        _model_is_chat_candidate,
    )
    from config.providers import (
        custom_model_alias,
        save_custom_provider as _save_cp,
        load_custom_providers,
    )

    _BUILTIN = {"deepseek", "openai", "anthropic"}
    if alias in _BUILTIN:
        print(c(RED, f"  ✗ Refusing to modify built-in provider '{alias}'."))
        return

    prov = PROVIDERS.get(alias)
    if not prov:
        print(c(RED, f"  ✗ Provider '{alias}' not found. Run /provider add {alias} <url> <KEY> first."))
        return

    api_key = os.getenv(prov.get("api_key_env", ""), "")
    if not api_key:
        print(c(RED, f"  ✗ {prov.get('api_key_env')} is not configured. Set it in ~/.pawnlogic/.env first."))
        return

    models_url = models_url_from_base_url(prov["base_url"])
    print(c(GRAY, f"  Requesting {models_url} ..."))

    try:
        data = _fetch_models_paginated(models_url, api_key)
    except Exception as e:
        print(c(RED, f"  ✗ Request failed: {e}"))
        return

    candidates: list[tuple[str, dict]] = []
    hidden_by_name = 0
    for item in data:
        mid = item.get("id", "")
        if not mid or not _model_is_chat_candidate(mid):
            hidden_by_name += 1
            continue
        vision = any(k in mid.lower() for k in ("vision", "vl", "visual"))
        candidates.append((mid, {
            "id":       mid,
            "provider": alias,
            "desc":     "Fetched model",
            "color":    "\033[37m",
            "vision":   vision,
        }))

    candidates, removed = await _filter_supported_chat_models(
        prov["base_url"],
        api_key,
        candidates,
        prov.get("api_format", "openai"),
    )

    if not candidates:
        print(c(YELLOW, "  ⚠ No usable models were fetched. Check the API response format."))
        return

    print(
        c(
            GRAY,
            f"  Sync summary: {len(data)} returned; {hidden_by_name} hidden by type/name; "
            f"{removed} hidden by chat probe; {len(candidates)} selectable.",
        )
    )
    alias_changes = _model_alias_changes(alias, candidates)
    if alias_changes:
        print(
            c(
                GRAY,
                f"  Alias note: {len(alias_changes)} model IDs will be saved with provider prefixes: "
                f"{_format_alias_preview(alias_changes)}.",
            )
        )
    print(c(GREEN, f"  ✓ Fetched {len(candidates)} models. Select models to register:\n"))
    chosen_ids = await _provider_fetch_selector(candidates)

    if not chosen_ids:
        print(c(GRAY, "  Cancelled. No models were registered."))
        return

    models_cfg = {
        custom_model_alias(alias, str(cfg.get("id") or mid), mid): cfg
        for mid, cfg in candidates
        if mid in set(chosen_ids)
    }
    _save_cp(alias, PROVIDERS[alias], models_cfg, replace_models=True)
    load_custom_providers()

    print(c(GREEN, f"  ✓ Registered {len(models_cfg)} models."))
    if is_provider_active(alias):
        print(c(CYAN, "  Provider is active. You can select these models in /model."))
    else:
        print(c(CYAN, f"  To show them in /model, run /provider activate {alias}."))


# ════════════════════════════════════════════════════════
# /provider sub-command dispatcher
# ════════════════════════════════════════════════════════

async def _handle_provider_cmd(sub: str, sub_arg: str, session) -> None:
    """Handle /provider sub-commands."""

    # /provider without arguments opens the interactive TUI panel.
    if not sub:
        if _HAS_PROMPT_TOOLKIT:
            try:
                from core.provider_tui import run_provider_tui
                await run_provider_tui()
            except Exception as _tui_err:
                logger.error(f"[provider-tui] crashed: {_tui_err}")
                import traceback
                traceback.print_exc()
                _provider_list()
                return
            # Refresh completer if main.py exposed one. Names are
            # function-local in main(), so this swallows a NameError if
            # called outside that scope (existing behavior preserved).
            try:
                _new_words = list(_all_cmd_words)  # noqa: F821
                _new_meta: dict = dict(_cmd_meta)  # noqa: F821
                for _a, _m in _visible_models().items():
                    _w = f"/model {_a}"
                    _new_words.append(_w)
                    _new_meta[_w] = _m.get("desc", "")
                _pawn_completer.words = _new_words      # noqa: F821
                _pawn_completer.meta_dict = _new_meta   # noqa: F821
            except Exception:
                pass
        else:
            _provider_list()
        return

    # /provider list
    if sub == "list":
        _provider_list()
    elif sub == "add":
        parts_add = sub_arg.split() if sub_arg else []
        if len(parts_add) >= 3:
            should_fetch = _provider_add_cli(parts_add[0], parts_add[1], parts_add[2],
                                             parts_add[3] if len(parts_add) > 3 else "openai")
            if should_fetch:
                await _provider_fetch(parts_add[0])
        else:
            _provider_add()
    elif sub == "fetch":
        if not sub_arg:
            print(c(RED, "  Usage: /provider fetch <name>"))
        else:
            await _provider_fetch(sub_arg.strip())
    elif sub == "update":
        if not sub_arg:
            print(c(RED, "  Usage: /provider update <name>"))
        else:
            await _provider_fetch(sub_arg.strip())  # update = re-fetch
    elif sub in ("activate", "active"):
        _provider_set_active(sub_arg.strip(), True)
    elif sub == "deactivate":
        _provider_set_active(sub_arg.strip(), False)
    elif sub == "remove":
        _provider_remove(sub_arg)
    elif sub == "test":
        _provider_test(session, sub_arg)
    else:
        print(c(RED, f"  ✗ Unknown sub-command '{sub}'. Available: list · add · fetch · update · activate · deactivate · remove · test"))


# ════════════════════════════════════════════════════════
# Claude-Code-style inline model picker
# ════════════════════════════════════════════════════════

async def cc_style_model_selector(
    models: dict, current_alias: str,
) -> str | None:
    """Claude Code style inline model selector."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.containers import Window

    entries = list(models.items())
    selected_idx = 0

    def get_menu_fragments():
        fragments = []
        fragments.append(("class:title", "  Select model\n"))
        fragments.append(("class:desc",   "  Choose a model for this session\n"))
        fragments.append(("",             "\n"))

        for i, (alias, cfg_m) in enumerate(entries):
            if i == selected_idx:
                fragments.append(("class:cursor", "  ❯ "))
            else:
                fragments.append(("", "    "))

            fragments.append(("class:index", f"{i+1}."))

            is_current = (alias == current_alias)
            if i == selected_idx:
                fragments.append(("class:selected", f" {alias}"))
            else:
                fragments.append(("", f" {alias}"))

            if is_current:
                fragments.append(("class:current", " ✔"))

            desc = cfg_m.get("desc", "")[:45]
            if desc:
                if i == selected_idx:
                    fragments.append(("class:desc-hi", f"  {desc}"))
                else:
                    fragments.append(("class:desc", f"  {desc}"))

            if cfg_m.get("vision"):
                fragments.append(("class:vision", " 📷"))

            fragments.append(("", "\n"))

        fragments.append(("", "\n"))
        fragments.append(("class:help", "  Enter to confirm · Esc to exit\n"))

        return fragments

    control = FormattedTextControl(get_menu_fragments)
    kb = KeyBindings()

    @kb.add("up")
    def _(event):
        nonlocal selected_idx
        selected_idx = (selected_idx - 1) % len(entries)

    @kb.add("down")
    def _(event):
        nonlocal selected_idx
        selected_idx = (selected_idx + 1) % len(entries)

    @kb.add("enter")
    def _(event):
        event.app.exit(result=entries[selected_idx][0])

    @kb.add("escape")
    def _(event):
        event.app.exit(result=None)

    @kb.add("c-c")
    def _(event):
        event.app.exit(result=None)

    for _n in range(1, min(10, len(entries) + 1)):
        @kb.add(str(_n))
        def _(event, _idx=_n - 1):
            nonlocal selected_idx
            if _idx < len(entries):
                selected_idx = _idx

    body = Window(content=control, always_hide_cursor=True)

    style = _PTStyle.from_dict({
        "title":      "#00afff bold",
        "desc":       "#888888",
        "desc-hi":    "#aaaaaa",
        "cursor":     "#00ff00 bold",
        "selected":   "#00ff00 bold",
        "current":    "#00d700",
        "index":      "#666666",
        "vision":     "#00afff",
        "help":       "#555555",
    })

    app = Application(
        layout=Layout(body),
        key_bindings=kb,
        style=style,
        mouse_support=False,
        full_screen=False,
    )

    return await app.run_async()


# ════════════════════════════════════════════════════════
# Command handlers
# ════════════════════════════════════════════════════════

@register("/setkey")
async def cmd_setkey(ctx: CommandContext) -> None:
    _run_key_wizard()


@register("/keys")
async def cmd_keys(ctx: CommandContext) -> None:
    from core.output import JsonSink
    if isinstance(ctx.sink, JsonSink):
        data = {}
        for pinfo in PROVIDERS.values():
            env = pinfo.get("api_key_env")
            if not env:
                continue
            data[env] = bool(os.environ.get(env, ""))
        ctx.sink.print_json(data)
        return
    print(c(BOLD, "\n  API Key status:"))
    for pname, pinfo in PROVIDERS.items():
        env = pinfo.get("api_key_env")
        if not env:
            continue
        val = os.environ.get(env, "")
        if val:
            tag = c(GREEN, f"✓ Configured ({mask_key(val)})")
        else:
            tag = c(RED, "✗ Not configured")
        print(f"  {c(CYAN, f'{pname:14}')}{env:28} {tag}")
    print(c(GRAY, "\n  Vision models: " + ", ".join(list_vision_models())))


@register("/provider")
async def cmd_provider(ctx: CommandContext) -> None:
    await _handle_provider_cmd(ctx.arg, ctx.arg2, ctx.session)


@register("/model")
async def cmd_model(ctx: CommandContext) -> None:
    session = ctx.session
    arg = ctx.arg
    if not arg:
        # Claude Code style inline selector.
        _vm = _visible_models()
        if not _vm:
            print(c(YELLOW, "  ⚠ No models with configured API keys are available. Use /setkey first."))
        elif _HAS_PROMPT_TOOLKIT:
            from collections import defaultdict
            _groups: dict[str, list] = defaultdict(list)
            for _alias, _cfg_m in _vm.items():
                _prov_label = PROVIDERS.get(_cfg_m.get("provider", ""), {}).get("label", _cfg_m.get("provider", ""))
                _groups[_prov_label].append((_alias, _cfg_m))

            print(c(BOLD, "\n  Available models (active providers with configured keys):"))
            for _prov_label, _entries in _groups.items():
                print(c(CYAN, f"  {_prov_label}") + c(GRAY, f"  [{len(_entries)} models]"))

            result = await cc_style_model_selector(_vm, session.model_alias)
            if result:
                session.model_alias = result
                ok, env = validate_api_key(result)
                if not ok:
                    print(c(YELLOW, f"  ⚠ Switched to {result}, but {env} is not set. Configure it with /setkey."))
                else:
                    print(c(GREEN, f"  ✓ Switched to {c(MODELS[result]['color'], result)}"))
            else:
                print(c(GRAY, "  Cancelled"))
        else:
            # readline fallback: plain grouped list for active providers with keys.
            from collections import defaultdict
            _groups: dict[str, list] = defaultdict(list)
            for _alias, _cfg_m in _vm.items():
                _prov_label = PROVIDERS.get(_cfg_m.get("provider", ""), {}).get("label", _cfg_m.get("provider", ""))
                _groups[_prov_label].append((_alias, _cfg_m))

            print(c(BOLD, "\n  Available models:"))
            for _prov_label, _entries in _groups.items():
                print(c(CYAN, f"\n  ── {_prov_label} ──"))
                for _alias, _cfg_m in _entries:
                    tick = c(GREEN, " ◀ current") if _alias == session.model_alias else ""
                    _env_var = PROVIDERS.get(_cfg_m.get("provider", ""), {}).get("api_key_env", "")
                    _raw_key = os.getenv(_env_var, "")
                    ktag = c(GREEN, f"[{mask_key(_raw_key)}]")
                    vtag = c(CYAN, " 📷") if _cfg_m.get("vision") else ""
                    ftag = c(MAGENTA, " [A]") if get_api_format(_alias) == "anthropic" else ""
                    print(f"    {c(_cfg_m['color'], f'{_alias:14}')}{_cfg_m['desc']:30} {ktag}{vtag}{ftag}{tick}")
            print(c(GRAY, "\n  Usage: /model <alias>  📷=vision capable  [A]=Anthropic format"))
    elif arg in MODELS:
        provider_name = MODELS[arg].get("provider", "")
        if not is_provider_active(provider_name):
            print(c(YELLOW, f"  ⚠ Provider '{provider_name}' is not active. Run /provider activate {provider_name} first."))
            return
        session.model_alias = arg
        ok, env = validate_api_key(arg)
        if not ok:
            print(c(YELLOW, f"  ⚠ Switched to {arg}, but {env} is not set. Configure it with /setkey."))
        else:
            print(c(GREEN, f"  ✓ Switched to {c(MODELS[arg]['color'], arg)}"))
    else:
        print(c(RED, f"  ✗ Unknown model '{arg}'"))
