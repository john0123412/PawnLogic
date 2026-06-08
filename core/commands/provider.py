"""
API key, provider and model selection commands.

Migrated from main.py's _legacy_slash_dispatch in stage-1 step 4.

Commands in this module:
    /setkey                       run the interactive key configuration wizard
    /keys                         show API key status for every provider
    /provider [sub] [args]        TUI / list / add / fetch / update / remove / test
    /model [alias]                switch the session's model (interactive picker)

Module-private helpers (provider/key/model setup; only used by these
commands and by main.py's startup wizard, which imports `_run_key_wizard`,
`_visible_models` and `_write_key_to_shell` from here):

    _detect_shell_config       detect ~/.bashrc, ~/.zshrc, etc.
    _write_key_to_shell        append `export KEY=...` to shell config
    _run_key_wizard            interactive first-run / /setkey wizard
    _visible_models            MODELS subset whose API key is configured

    _handle_provider_cmd       dispatcher for /provider sub-commands
    _provider_list             display all providers and their key status
    _provider_add              interactive: add a custom provider
    _provider_add_cli          non-interactive: /provider add <a> <url> <env>
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
    models_url_from_base_url,
    remove_custom_provider, save_custom_provider,
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

# (序号标签, env_var, label, hint, 是否可跳过 key)
_WIZARD_PROVIDERS = [
    ("1", "PAWN_API_KEY",       "PawnLogic Engine",  "hermes · hermes405",                  False),
    ("2", "DEEPSEEK_API_KEY",   "DeepSeek",          "ds-chat (V3 强推理)",                 False),
    ("3", "OPENROUTER_API_KEY", "OpenRouter",        "多模型聚合，含 gpt-4o 视觉",          False),
    ("4", "SILICON_API_KEY",    "SiliconFlow",       "ds-coder · qwen 等国产模型",          False),
    ("5", "ZHIPU_API_KEY",      "ZhipuAI 智谱",      "glm-4v-plus 视觉识图（国内直连）",    False),
    ("6", "XIAOMI_API_KEY",     "Xiaomi MiMo",       "mimo-v2.5-pro · mimo-v2-omni",        False),
    ("7", "ANTHROPIC_API_KEY",  "Anthropic",         "claude-opus-4-7 · claude-sonnet-4-6", False),
    ("8", None,                 "本地 Ollama",       "需先运行 ollama serve，无需 Key",      True),
]


def _detect_shell_config() -> Path | None:
    """检测用户使用的 shell 配置文件。"""
    shell = os.environ.get("SHELL", "")
    home = Path.home()
    if "zsh" in shell and (home / ".zshrc").exists():
        return home / ".zshrc"
    if "bash" in shell:
        for f in [".bashrc", ".bash_profile", ".profile"]:
            if (home / f).exists():
                return home / f
        return home / ".bashrc"   # 新建
    return home / ".bashrc"


def _write_key_to_shell(env_var: str, key: str) -> str:
    """将 export 语句写入 shell 配置文件并立即注入 os.environ。返回写入路径。"""
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
            return f"写入失败: {e}"

    os.environ[env_var] = key
    return str(cfg_file)


def _run_key_wizard() -> bool:
    """模块 2：无 Key 时的交互式配置向导。
    返回 True 表示至少成功配置了一个 Key（可以继续启动）。
    """
    print(f"""
{c(BOLD+CYAN, "╔════════════════════════════════════════════════╗")}
{c(BOLD+CYAN, "║")}  {c(BOLD, f"PawnLogic {VERSION}")} — 首次配置向导              {c(BOLD+CYAN,"║")}
{c(BOLD+CYAN, "╚════════════════════════════════════════════════╝")}

{c(YELLOW,"⚠  未检测到任何 API Key。")}
请选择要配置的服务商（可多次配置）：

""")

    for num, env_var, label, hint, no_key in _WIZARD_PROVIDERS:
        already = ""
        if env_var and os.environ.get(env_var):
            already = c(GREEN, "  [已配置 ✓]")
        print(f"  {c(CYAN, f'[{num}]')} {c(BOLD, f'{label:18}')} {c(GRAY, hint)}{already}")

    print(f"\n  {c(GRAY, '[0]')} 跳过，稍后手动配置（export KEY=sk-... 或 /setkey）")
    print()

    configured_any = False

    while True:
        try:
            choice = input(cp(BOLD, "  请输入序号（可输入多个，如 1 5）: ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if choice == "0" or not choice:
            break

        selected = [s.strip() for s in choice.split() if s.strip()]

        for sel in selected:
            matched = next((p for p in _WIZARD_PROVIDERS if p[0] == sel), None)
            if not matched:
                print(c(RED, f"  ✗ 无效序号 '{sel}'"))
                continue

            num, env_var, label, hint, no_key = matched

            if no_key:
                local_url = input(
                    c(GRAY, "  Ollama API URL [默认: http://localhost:11434/v1/chat/completions]: ")
                ).strip()
                if local_url:
                    os.environ["LOCAL_API_URL"] = local_url
                    _write_key_to_shell("LOCAL_API_URL", local_url)
                print(c(GREEN, "  ✓ Ollama 配置完成。请确保 ollama serve 已在后台运行。"))
                configured_any = True
                continue

            print(c(GRAY, f"\n  获取 {label} Key:"))
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
                print(c(CYAN, f"  申请地址: {url}"))

            try:
                key = ptk_prompt(f"  粘贴 {env_var}（回车确认）: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                continue

            if not key:
                print(c(YELLOW, "  跳过（未输入）"))
                continue

            written_to = _write_key_to_shell(env_var, key)
            print(c(GREEN, f"  ✓ {env_var} 已保存 → {written_to}"))
            print(c(GRAY,  "  已即时注入当前进程，无需重启终端。"))
            configured_any = True

        try:
            cont = input(cp(GRAY, "  继续配置其他服务商? [y/N]: ")).strip().lower()
            if cont != "y":
                break
        except (EOFError, KeyboardInterrupt):
            break

    if not configured_any:
        print(c(YELLOW, "\n  未配置任何 Key。启动后可用 /setkey 命令重新配置。\n"))

    return configured_any


# ════════════════════════════════════════════════════════
# Visible models helper
# ════════════════════════════════════════════════════════

def _visible_models() -> dict:
    """返回当前进程环境中已配置 API Key 的模型子集（动态，每次调用实时检查）。"""
    return {
        alias: cfg
        for alias, cfg in MODELS.items()
        if os.getenv(PROVIDERS.get(cfg.get("provider", ""), {}).get("api_key_env", ""), "")
    }


# ════════════════════════════════════════════════════════
# Provider management — list / add / remove / test / fetch
# ════════════════════════════════════════════════════════

def _provider_list() -> None:
    """列出所有 Provider 状态。人读路径（sub-commands of /provider 不带 ctx）。

    JSON 路径从进程级 active sink 读取；如果是 JsonSink，发射结构化数据，
    否则保持原有的彩色表格输出。
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
                "models":     models_for_provider,
            })
        sink.print_json(data)
        return

    print(c(BOLD, "\n  Provider 列表："))
    for pname, pinfo in PROVIDERS.items():
        fmt = pinfo.get("api_format", "openai")
        label = pinfo.get("label", pname)
        env = pinfo.get("api_key_env", "")
        val = os.environ.get(env, "") if env else ""
        if val:
            ktag = c(GREEN, f"✓ ({mask_key(val)})")
        elif not env:
            ktag = c(GRAY, "无需 Key")
        else:
            ktag = c(RED, "✗ 未配置")
        fmt_tag = c(MAGENTA, "[Anthropic]") if fmt == "anthropic" else c(GRAY, "[OpenAI]")
        hint = pinfo.get("models_hint", "")
        print(f"  {c(CYAN, f'{pname:16}')}{fmt_tag:14} {label:24} {ktag}")
        if hint:
            print(f"  {'':16}{c(GRAY, hint)}")
    print(c(GRAY, f"\n  自定义配置: {CUSTOM_PROVIDERS_PATH}"))
    print()


def _provider_add() -> None:
    """交互式添加自定义 Provider。"""
    print(c(BOLD, "\n  添加自定义 Provider"))
    print(c(GRAY, "  （Key 存入 .env，配置存入 ~/.pawnlogic/custom_providers.json）\n"))

    try:
        name = input(cp(BOLD, "  Provider 名称 (短ID，如 my_relay): ")).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if not name or name in PROVIDERS:
        print(c(RED, f"  ✗ 名称无效或已存在: {name}"))
        return

    print(f"\n  {c(BOLD, 'API 格式:')}")
    print(f"    {c(CYAN, '[1]')} OpenAI Chat Completions 格式")
    print(f"    {c(CYAN, '[2]')} Anthropic Messages 格式")
    try:
        fmt_choice = input(cp(BOLD, "  选择 [1/2]: ")).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    api_format = "anthropic" if fmt_choice == "2" else "openai"

    try:
        base_url = input(cp(BOLD, "  Base URL (如 https://api.example.com/v1/chat/completions): ")).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if not base_url:
        print(c(RED, "  ✗ URL 不能为空"))
        return

    env_var_name = f"{name.upper().replace('-', '_')}_API_KEY"
    try:
        key = ptk_prompt(f"  粘贴 API Key（回车确认，存入 .env → {env_var_name}）: ").strip()
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
        print(c(GREEN, f"  ✓ Key 已保存 → .env ({env_var_name})"))

    prov_cfg = {
        "base_url":    base_url,
        "api_key_env": env_var_name,
        "label":       f"Custom ({name})",
        "api_format":  api_format,
    }

    save_custom_provider(name, prov_cfg, {})
    PROVIDERS[name] = prov_cfg

    print(c(GREEN, f"\n  ✓ Provider '{name}' 已添加"))
    print(c(GRAY,  f"    格式: {api_format}"))
    print(c(GRAY,  f"    URL:  {base_url}"))
    print(c(GRAY,  f"    配置: {CUSTOM_PROVIDERS_PATH}"))
    print(c(CYAN,  f"    接下来运行 /provider fetch {name} 拉取模型列表"))
    print()


def _provider_remove(name: str = "") -> None:
    """删除自定义 Provider。"""
    if not name:
        if not CUSTOM_PROVIDERS_PATH.exists():
            print(c(GRAY, "\n  没有自定义 Provider。"))
            return
        try:
            data = json.loads(CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8"))
        except Exception:
            print(c(RED, "\n  ✗ 读取配置文件失败"))
            return
        custom = list(data.get("providers", {}).keys())
        if not custom:
            print(c(GRAY, "\n  没有自定义 Provider。"))
            return
        print(c(BOLD, "\n  自定义 Provider:"))
        for i, n in enumerate(custom, 1):
            print(f"    {c(CYAN, f'[{i}]')} {n}")
        try:
            choice = input(cp(BOLD, "  输入序号或名称: ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if choice.isdigit() and 1 <= int(choice) <= len(custom):
            name = custom[int(choice) - 1]
        elif choice in custom:
            name = choice
        else:
            print(c(RED, f"  ✗ 无效选择: {choice}"))
            return

    if remove_custom_provider(name):
        if name in PROVIDERS:
            del PROVIDERS[name]
        to_remove = [a for a, m in MODELS.items() if m.get("provider") == name]
        for a in to_remove:
            del MODELS[a]
        print(c(GREEN, f"  ✓ 已删除 Provider '{name}'"))
    else:
        print(c(RED, f"  ✗ 未找到自定义 Provider: {name}"))


def _provider_test(session, model_alias: str = "") -> None:
    """测试 Provider 连通性。"""
    if not model_alias:
        try:
            model_alias = input(cp(BOLD, "  输入要测试的模型别名: ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
    if model_alias not in MODELS:
        print(c(RED, f"  ✗ 未知模型: {model_alias}"))
        return

    ok, env = validate_api_key(model_alias)
    if not ok:
        print(c(RED, f"  ✗ {env} 未配置。用 /setkey 或 /provider add 配置。"))
        return

    cfg = get_provider_config(model_alias)
    print(c(GRAY, f"  测试 {model_alias} ({cfg['api_format']}) → {cfg['base_url']} ..."))
    print(c(GRAY, "  发送 max_tokens=1 测试请求..."))

    from core.api_client import call_once
    text, err = call_once(
        [{"role": "user", "content": "Say OK"}],
        model_alias, max_tokens=1,
    )
    if err:
        print(c(RED, f"  ✗ 测试失败: {err}"))
    else:
        print(c(GREEN, f"  ✓ 连通成功！响应: {text[:80]}"))


def _provider_add_cli(alias: str, base_url: str, env_key: str, api_format: str = "openai") -> bool:
    """非交互式：/provider add <alias> <base_url> <ENV_KEY> [anthropic]"""
    from config.providers import save_custom_provider as _save_cp, load_custom_providers
    if alias in PROVIDERS:
        print(c(YELLOW, f"  ⚠ Provider '{alias}' 已存在，将覆盖配置"))
    fmt = api_format if api_format in ("openai", "anthropic") else "openai"
    prov_cfg = {
        "base_url":    base_url,
        "api_key_env": env_key,
        "label":       f"Custom ({alias})",
        "api_format":  fmt,
    }
    _save_cp(alias, prov_cfg, {})
    PROVIDERS[alias] = prov_cfg
    load_custom_providers()
    print(c(GREEN, f"  ✓ 供应商注册成功！请确保已在 .env 中配置了 {env_key}。"))
    if not os.getenv(env_key, ""):
        print(c(CYAN, f"  接下来请运行 /provider fetch {alias} 以拉取模型。"))
        return False
    if not sys.stdin.isatty():
        print(c(CYAN, f"  接下来请运行 /provider fetch {alias} 以拉取模型。"))
        return False
    try:
        ans = input(cp(BOLD, f"  是否立即拉取 {alias} 的模型列表？[Y/n]: ")).strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = "n"
    return ans in ("", "y")


def _fetch_models_paginated(models_url: str, api_key: str) -> list:
    """带分页支持的 /v1/models 请求，返回所有 model 条目。"""
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
    """prompt_toolkit 多选菜单：Space 选中/取消，Enter 确认，Esc 全不选退出。
    返回选中的 model id 列表。
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
        frags.append(("class:title", f"  选择要注册的模型（共 {len(entries)} 个）\n"))
        frags.append(("class:desc",  "  Space 选中/取消  ↑↓ 移动  A 全选  N 全不选  Enter 确认  Esc 取消\n\n"))

        for i, (mid, cfg) in enumerate(entries):
            checked = "●" if i in selected else "○"
            cursor = "❯ " if i == cursor_idx else "  "
            vtag = " 📷" if cfg.get("vision") else ""
            style = "class:selected" if i == cursor_idx else ""
            frags.append((style, f"  {cursor}{checked} {mid}{vtag}\n"))
        frags.append(("", f"\n  已选 {len(selected)}/{len(entries)} 个\n"))
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
    """/provider fetch <alias>: 分页请求 /v1/models，交互多选后批量注册。"""
    from core.provider_tui import _filter_supported_chat_models, _model_is_chat_candidate
    from config.providers import (
        custom_model_alias,
        save_custom_provider as _save_cp,
        load_custom_providers,
    )

    _BUILTIN = {"deepseek", "openai", "anthropic"}
    if alias in _BUILTIN:
        print(c(RED, f"  ✗ 拒绝修改内置 Provider '{alias}'，保护核心资产。"))
        return

    prov = PROVIDERS.get(alias)
    if not prov:
        print(c(RED, f"  ✗ 未找到 Provider '{alias}'，请先运行 /provider add {alias} <url> <KEY>"))
        return

    api_key = os.getenv(prov.get("api_key_env", ""), "")
    if not api_key:
        print(c(RED, f"  ✗ {prov.get('api_key_env')} 未配置，请先在 ~/.pawnlogic/.env 中设置该变量。"))
        return

    models_url = models_url_from_base_url(prov["base_url"])
    print(c(GRAY, f"  正在请求 {models_url} ..."))

    try:
        data = _fetch_models_paginated(models_url, api_key)
    except Exception as e:
        print(c(RED, f"  ✗ 请求失败: {e}"))
        return

    candidates: list[tuple[str, dict]] = []
    for item in data:
        mid = item.get("id", "")
        if not mid or not _model_is_chat_candidate(mid):
            continue
        vision = any(k in mid.lower() for k in ("vision", "vl", "visual"))
        candidates.append((mid, {
            "id":       mid,
            "provider": alias,
            "desc":     "动态拉取模型",
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
        print(c(YELLOW, "  ⚠ 未获取到任何可用模型，请检查接口返回格式。"))
        return

    if removed:
        print(c(GRAY, f"  已隐藏 {removed} 个不可用于聊天的模型。"))
    print(c(GREEN, f"  ✓ 获取到 {len(candidates)} 个模型，请选择要注册的模型：\n"))
    chosen_ids = await _provider_fetch_selector(candidates)

    if not chosen_ids:
        print(c(GRAY, "  已取消，未注册任何模型。"))
        return

    models_cfg = {
        custom_model_alias(alias, str(cfg.get("id") or mid), mid): cfg
        for mid, cfg in candidates
        if mid in set(chosen_ids)
    }
    _save_cp(alias, PROVIDERS[alias], models_cfg, replace_models=True)
    load_custom_providers()

    print(c(GREEN, f"  ✓ 成功注册了 {len(models_cfg)} 个模型！输入 /model 即可无缝切换。"))


# ════════════════════════════════════════════════════════
# /provider sub-command dispatcher
# ════════════════════════════════════════════════════════

async def _handle_provider_cmd(sub: str, sub_arg: str, session) -> None:
    """处理 /provider 子命令。"""

    # ── /provider 无参数 — 全交互式 TUI 面板 ──────────
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

    # ── /provider list ────────────────────────────────
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
            print(c(RED, "  用法: /provider fetch <别名>"))
        else:
            await _provider_fetch(sub_arg.strip())
    elif sub == "update":
        if not sub_arg:
            print(c(RED, "  用法: /provider update <别名>"))
        else:
            await _provider_fetch(sub_arg.strip())  # update = re-fetch
    elif sub == "remove":
        _provider_remove(sub_arg)
    elif sub == "test":
        _provider_test(session, sub_arg)
    else:
        print(c(RED, f"  ✗ 未知子命令 '{sub}'。可用: list · add · fetch · update · remove · test"))


# ════════════════════════════════════════════════════════
# Claude-Code-style inline model picker
# ════════════════════════════════════════════════════════

async def cc_style_model_selector(
    models: dict, current_alias: str,
) -> str | None:
    """Claude Code 风格的内联交互式模型选择器。"""
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
    print(c(BOLD, "\n  API Key 配置状态："))
    for pname, pinfo in PROVIDERS.items():
        env = pinfo.get("api_key_env")
        if not env:
            continue
        val = os.environ.get(env, "")
        if val:
            tag = c(GREEN, f"✓ 已配置 ({mask_key(val)})")
        else:
            tag = c(RED, "✗ 未配置")
        print(f"  {c(CYAN, f'{pname:14}')}{env:28} {tag}")
    print(c(GRAY, "\n  视觉模型: " + ", ".join(list_vision_models())))


@register("/provider")
async def cmd_provider(ctx: CommandContext) -> None:
    await _handle_provider_cmd(ctx.arg, ctx.arg2, ctx.session)


@register("/model")
async def cmd_model(ctx: CommandContext) -> None:
    session = ctx.session
    arg = ctx.arg
    if not arg:
        # ── CC 风格内联选择器 ──────────────────────────
        _vm = _visible_models()
        if not _vm:
            print(c(YELLOW, "  ⚠ 当前没有已配置 API Key 的模型，请先用 /setkey 配置。"))
        elif _HAS_PROMPT_TOOLKIT:
            from collections import defaultdict
            _groups: dict[str, list] = defaultdict(list)
            for _alias, _cfg_m in _vm.items():
                _prov_label = PROVIDERS.get(_cfg_m.get("provider", ""), {}).get("label", _cfg_m.get("provider", ""))
                _groups[_prov_label].append((_alias, _cfg_m))

            print(c(BOLD, "\n  可用模型（仅已配置 Key）："))
            for _prov_label, _entries in _groups.items():
                print(c(CYAN, f"  {_prov_label}") + c(GRAY, f"  [{len(_entries)} 个]"))

            result = await cc_style_model_selector(_vm, session.model_alias)
            if result:
                session.model_alias = result
                ok, env = validate_api_key(result)
                if not ok:
                    print(c(YELLOW, f"  ⚠ 已切换到 {result}，但 {env} 未设置。用 /setkey 配置。"))
                else:
                    print(c(GREEN, f"  ✓ 已切换到 {c(MODELS[result]['color'], result)}"))
            else:
                print(c(GRAY, "  已取消"))
        else:
            # readline 降级：按 provider 分组的纯文本列表（仅已配置 Key 的模型）
            from collections import defaultdict
            _groups: dict[str, list] = defaultdict(list)
            for _alias, _cfg_m in _vm.items():
                _prov_label = PROVIDERS.get(_cfg_m.get("provider", ""), {}).get("label", _cfg_m.get("provider", ""))
                _groups[_prov_label].append((_alias, _cfg_m))

            print(c(BOLD, "\n  可用模型："))
            for _prov_label, _entries in _groups.items():
                print(c(CYAN, f"\n  ── {_prov_label} ──"))
                for _alias, _cfg_m in _entries:
                    tick = c(GREEN, " ◀ 当前") if _alias == session.model_alias else ""
                    _env_var = PROVIDERS.get(_cfg_m.get("provider", ""), {}).get("api_key_env", "")
                    _raw_key = os.getenv(_env_var, "")
                    ktag = c(GREEN, f"[{mask_key(_raw_key)}]")
                    vtag = c(CYAN, " 📷") if _cfg_m.get("vision") else ""
                    ftag = c(MAGENTA, " [A]") if get_api_format(_alias) == "anthropic" else ""
                    print(f"    {c(_cfg_m['color'], f'{_alias:14}')}{_cfg_m['desc']:30} {ktag}{vtag}{ftag}{tick}")
            print(c(GRAY, "\n  用法: /model <alias>  📷=支持视觉  [A]=Anthropic 格式"))
    elif arg in MODELS:
        session.model_alias = arg
        ok, env = validate_api_key(arg)
        if not ok:
            print(c(YELLOW, f"  ⚠ 已切换到 {arg}，但 {env} 未设置。用 /setkey 配置。"))
        else:
            print(c(GREEN, f"  ✓ 已切换到 {c(MODELS[arg]['color'], arg)}"))
    else:
        print(c(RED, f"  ✗ 未知模型 '{arg}'"))
