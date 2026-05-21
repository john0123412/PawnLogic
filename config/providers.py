"""
config/providers.py — API Provider 与模型注册表

所有 API Key 通过环境变量注入，代码中无任何硬编码凭证。
"""
import os
import json
from pathlib import Path

PROVIDERS: dict[str, dict] = {
    "deepseek": {
        "base_url":    "https://api.deepseek.com/v1/chat/completions",
        "api_key_env": "DEEPSEEK_API_KEY",
        "label":       "DeepSeek",
        "api_format":  "openai",
    },
    "openai": {
        "base_url":    "https://api.openai.com/v1/chat/completions",
        "api_key_env": "OPENAI_API_KEY",
        "label":       "OpenAI",
        "api_format":  "openai",
    },
    "anthropic": {
        "base_url":    "https://api.anthropic.com/v1/messages",
        "api_key_env": "ANTHROPIC_API_KEY",
        "label":       "Anthropic (Claude)",
        "api_format":  "anthropic",
    },
}

MODELS: dict[str, dict] = {
    "ds-v4-flash": {
        "id":       "deepseek-v4-flash",
        "provider": "deepseek",
        "desc":     "DeepSeek V4 Flash — 默认主力，快速低成本",
        "color":    "\033[32m",
        "vision":   False,
    },
    "ds-v4-pro": {
        "id":       "deepseek-v4-pro",
        "provider": "deepseek",
        "desc":     "DeepSeek V4 Pro — 旗舰推理",
        "color":    "\033[92m",
        "vision":   False,
    },
    "gpt-4o": {
        "id":       "gpt-4o",
        "provider": "openai",
        "desc":     "OpenAI GPT-4o — 视觉+多模态",
        "color":    "\033[97m",
        "vision":   True,
    },
    "gpt-4.1": {
        "id":       "gpt-4.1",
        "provider": "openai",
        "desc":     "OpenAI GPT-4.1 — 代码与指令跟随",
        "color":    "\033[37m",
        "vision":   False,
    },
    "o3": {
        "id":       "o3",
        "provider": "openai",
        "desc":     "OpenAI o3 — 复杂推理",
        "color":    "\033[96m",
        "vision":   False,
    },
    "claude-sonnet": {
        "id":       "claude-sonnet-4-6",
        "provider": "anthropic",
        "desc":     "Claude Sonnet 4.6 — 均衡主力",
        "color":    "\033[95m",
        "vision":   True,
    },
    "claude-haiku": {
        "id":       "claude-haiku-4-5-20251001",
        "provider": "anthropic",
        "desc":     "Claude Haiku 4.5 — 快速低成本",
        "color":    "\033[35m",
        "vision":   True,
    },
}

DEFAULT_MODEL = "ds-v4-flash"

NAMING_MODEL_CHAIN: list = [
    "claude-haiku",
    "ds-v4-flash",
    "gpt-4.1",
]

VISION_PRIORITY = ["gpt-4o", "claude-sonnet"]

CUSTOM_PROVIDERS_PATH = Path.home() / ".pawnlogic" / "custom_providers.json"


def _normalize_url(raw: str, api_format: str = "openai") -> str:
    """Ensure base_url ends with the correct chat endpoint path."""
    raw = raw.rstrip("/")
    if raw.endswith("/chat/completions") or raw.endswith("/messages"):
        return raw
    suffix = "/messages" if api_format == "anthropic" else "/chat/completions"
    if raw.endswith("/v1"):
        return raw + suffix
    return raw + "/v1" + suffix


_FAST_KEYWORDS = {"flash", "haiku", "mini", "turbo", "lite"}


def is_fast_model(model_alias: str) -> bool:
    """Return True if the model id contains a fast-tier keyword."""
    mid = MODELS.get(model_alias, {}).get("id", model_alias).lower()
    return any(k in mid for k in _FAST_KEYWORDS)


def find_fast_peer(model_alias: str) -> str | None:
    """
    Given a pro-tier model alias, return the alias of a fast-tier model
    from the same provider that has a valid API key.
    Returns None if no fast peer is found.
    """
    m = MODELS.get(model_alias)
    if not m:
        return None
    provider = m.get("provider", "")
    for alias, cfg in MODELS.items():
        if cfg.get("provider") != provider:
            continue
        if not is_fast_model(alias):
            continue
        ok, _ = validate_api_key(alias)
        if ok:
            return alias
    return None


def get_api_config(model_alias: str) -> tuple[str, str]:
    """返回 (base_url, api_key)。Key 从环境变量读取，永不硬编码。"""
    m    = MODELS.get(model_alias, MODELS[DEFAULT_MODEL])
    prov = PROVIDERS.get(m["provider"], list(PROVIDERS.values())[0])
    key  = os.getenv(prov["api_key_env"], "")
    fmt  = prov.get("api_format", "openai")
    return _normalize_url(prov["base_url"], fmt), key


def get_api_format(model_alias: str) -> str:
    """返回 'openai' 或 'anthropic'。"""
    m    = MODELS.get(model_alias, MODELS[DEFAULT_MODEL])
    prov = PROVIDERS.get(m["provider"], {})
    return prov.get("api_format", "openai")


def get_provider_config(model_alias: str) -> dict:
    """返回完整 provider 配置字典。"""
    m    = MODELS.get(model_alias, MODELS[DEFAULT_MODEL])
    prov = PROVIDERS.get(m["provider"], list(PROVIDERS.values())[0])
    key  = os.getenv(prov["api_key_env"], "")
    fmt  = prov.get("api_format", "openai")
    return {
        "base_url":   _normalize_url(prov["base_url"], fmt),
        "api_key":    key,
        "api_format": fmt,
        "label":      prov.get("label", ""),
    }


def validate_api_key(model_alias: str) -> tuple[bool, str]:
    """检查指定模型的 Key 是否已正确配置。返回 (ok, missing_env_var)。"""
    _, key = get_api_config(model_alias)
    if not key:
        m    = MODELS.get(model_alias, MODELS[DEFAULT_MODEL])
        prov = PROVIDERS.get(m["provider"], {})
        return False, prov.get("api_key_env", "")
    return True, ""


def list_configured_models() -> list[str]:
    """返回所有已配置 Key 的模型别名列表。"""
    return [alias for alias in MODELS if validate_api_key(alias)[0]]


def get_best_vision_model() -> tuple[str | None, str | None, str | None]:
    """按优先级找到第一个已配置 Key 的视觉模型。"""
    for alias in VISION_PRIORITY:
        m = MODELS.get(alias)
        if not m or not m.get("vision"):
            continue
        url, key = get_api_config(alias)
        if key:
            return alias, url, key
    return None, None, None


def list_vision_models() -> list[str]:
    """返回所有标记了 vision=True 的模型别名。"""
    return [alias for alias, m in MODELS.items() if m.get("vision")]


def load_custom_providers() -> None:
    """从 custom_providers.json 加载用户自定义 provider，合并进 PROVIDERS/MODELS。"""
    # Reload .env so keys added after startup (e.g. via wizard) are available
    try:
        from dotenv import load_dotenv
        _env = Path.home() / ".pawnlogic" / ".env"
        if _env.exists():
            load_dotenv(_env, override=True)
    except ImportError:
        pass
    if not CUSTOM_PROVIDERS_PATH.exists():
        return
    try:
        data = json.loads(CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    for name, prov in data.get("providers", {}).items():
        if name not in PROVIDERS:
            prov.setdefault("api_format", "openai")
            PROVIDERS[name] = prov
    for alias, model in data.get("models", {}).items():
        if alias not in MODELS:
            model.setdefault("color", "\033[37m")
            model.setdefault("vision", False)
            MODELS[alias] = model


def save_custom_provider(name: str, prov_cfg: dict, models_cfg: dict) -> None:
    """将自定义 provider 持久化到 custom_providers.json（不含 Key）。"""
    CUSTOM_PROVIDERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {"providers": {}, "models": {}}
    if CUSTOM_PROVIDERS_PATH.exists():
        try:
            data = json.loads(CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    data["providers"][name] = prov_cfg
    data["models"].update(models_cfg)
    CUSTOM_PROVIDERS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def remove_custom_provider(name: str) -> bool:
    """从 JSON 文件删除自定义 provider。返回是否成功。"""
    if not CUSTOM_PROVIDERS_PATH.exists():
        return False
    try:
        data = json.loads(CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return False
    if name not in data.get("providers", {}):
        return False
    del data["providers"][name]
    to_remove = [a for a, m in data.get("models", {}).items()
                 if m.get("provider") == name]
    for a in to_remove:
        del data["models"][a]
    CUSTOM_PROVIDERS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return True


# 模块加载时自动读取自定义 provider
load_custom_providers()
