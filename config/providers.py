"""
config/providers.py - API provider and model registry.

All API keys are injected through environment variables. No credentials are
hard-coded in source.
"""
import os
import json
from urllib.parse import urlparse

from .paths import PAWNLOGIC_HOME

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
        "id":        "deepseek-v4-flash",
        "provider":  "deepseek",
        "desc":      "DeepSeek V4 Flash - default primary model, fast and low-cost",
        "color":     "\033[32m",
        "vision":    False,
        "reasoning": True,   # Returns reasoning_content and must be echoed back.
    },
    "ds-v4-pro": {
        "id":        "deepseek-v4-pro",
        "provider":  "deepseek",
        "desc":      "DeepSeek V4 Pro - flagship reasoning model",
        "color":     "\033[92m",
        "vision":    False,
        "reasoning": True,
    },
    "gpt-5.5": {
        "id":        "gpt-5.5",
        "provider":  "openai",
        "desc":      "OpenAI GPT-5.5 - latest flagship for complex reasoning and coding",
        "color":     "\033[97m",
        "vision":    True,
        "reasoning": False,
    },
    "gpt-5.4": {
        "id":        "gpt-5.4",
        "provider":  "openai",
        "desc":      "OpenAI GPT-5.4 - coding and professional work",
        "color":     "\033[37m",
        "vision":    True,
        "reasoning": False,
    },
    "gpt-5.4-mini": {
        "id":        "gpt-5.4-mini",
        "provider":  "openai",
        "desc":      "OpenAI GPT-5.4 Mini - low-latency and low-cost",
        "color":     "\033[36m",
        "vision":    True,
        "reasoning": False,
    },
    "gpt-5.4-nano": {
        "id":        "gpt-5.4-nano",
        "provider":  "openai",
        "desc":      "OpenAI GPT-5.4 Nano - lowest-cost option",
        "color":     "\033[90m",
        "vision":    True,
        "reasoning": False,
    },
    "gpt-4o": {
        "id":        "gpt-4o",
        "provider":  "openai",
        "desc":      "OpenAI GPT-4o - vision and multimodal",
        "color":     "\033[97m",
        "vision":    True,
        "reasoning": False,
    },
    "gpt-4.1": {
        "id":        "gpt-4.1",
        "provider":  "openai",
        "desc":      "OpenAI GPT-4.1 - coding and instruction following",
        "color":     "\033[37m",
        "vision":    False,
        "reasoning": False,
    },
    "o3": {
        "id":        "o3",
        "provider":  "openai",
        "desc":      "OpenAI o3 - complex reasoning",
        "color":     "\033[96m",
        "vision":    False,
        "reasoning": False,  # OpenAI o-series reasoning is internalized.
    },
    "claude-opus": {
        "id":        "claude-opus-4-6",
        "provider":  "anthropic",
        "desc":      "Claude Opus 4.6 - frontier reasoning flagship",
        "color":     "\033[95m",
        "vision":    True,
        "reasoning": False,
    },
    "claude-sonnet": {
        "id":        "claude-sonnet-4-6",
        "provider":  "anthropic",
        "desc":      "Claude Sonnet 4.6 - balanced primary model",
        "color":     "\033[95m",
        "vision":    True,
        "reasoning": False,  # Anthropic format uses its own API path.
    },
    "claude-haiku": {
        "id":        "claude-haiku-4-5-20251001",
        "provider":  "anthropic",
        "desc":      "Claude Haiku 4.5 - fast and low-cost",
        "color":     "\033[35m",
        "vision":    True,
        "reasoning": False,
    },
}

DEFAULT_MODEL = "ds-v4-flash"

NAMING_MODEL_CHAIN: list = [
    "claude-haiku",
    "ds-v4-flash",
    "gpt-5.4-mini",
]

VISION_PRIORITY = ["gpt-5.5", "gpt-4o", "claude-sonnet"]

CUSTOM_PROVIDERS_PATH = PAWNLOGIC_HOME / "custom_providers.json"
CUSTOM_MODEL_DESC = "Custom model"
FETCHED_MODEL_DESC = "Dynamically fetched model"
BUILTIN_PROVIDER_NAMES = set(PROVIDERS)
BUILTIN_MODEL_ALIASES = set(MODELS)
ALWAYS_ACTIVE_PROVIDERS = {"deepseek"}
NON_CHAT_MODEL_KEYWORDS = {
    "embedding",
    "embed",
    "rerank",
    "tts",
    "whisper",
    "moderation",
    "davinci",
    "babbage",
    "image",
    "dall-e",
    "dalle",
    "audio",
    "video",
    "realtime",
    "transcribe",
    "transcription",
    "speech",
    "sora",
}
LEGACY_MODEL_KEYWORDS = ("instruct", "babbage", "davinci", "curie", "ada", "legacy")
_CUSTOM_PROVIDER_ALLOWED_SCHEMES = {"http", "https"}
_providers_initialized = False


def is_chat_model_candidate(model_id: str) -> bool:
    """Return whether a discovered model id is suitable for chat completions."""
    ml = str(model_id).lower()
    if any(noise in ml for noise in NON_CHAT_MODEL_KEYWORDS):
        return False
    if any(legacy in ml for legacy in LEGACY_MODEL_KEYWORDS):
        return False
    return True


def _alias_prefix(provider_name: str) -> str:
    prefix = "".join(
        ch if ch.isalnum() or ch in "._-" else "-"
        for ch in str(provider_name).strip()
    ).strip("-")
    return prefix or "custom"


def custom_model_alias(
    provider_name: str,
    model_id: str,
    alias: str | None = None,
    *,
    force_prefix: bool = False,
) -> str:
    """Return a custom model alias that cannot hide or be hidden by built-ins."""
    raw_alias = str(alias or model_id).strip()
    raw_model_id = str(model_id or raw_alias).strip()
    if not force_prefix and raw_alias not in BUILTIN_MODEL_ALIASES:
        return raw_alias
    return f"{_alias_prefix(provider_name)}:{raw_model_id or raw_alias}"


def _provider_active_from_data(name: str, prov_cfg: dict | None, data: dict) -> bool:
    if name in ALWAYS_ACTIVE_PROVIDERS:
        return True
    states = data.get("provider_states", {})
    state = states.get(name, {}) if isinstance(states, dict) else {}
    if isinstance(state, dict) and "active" in state:
        return bool(state.get("active"))
    if prov_cfg and "active" in prov_cfg:
        return bool(prov_cfg.get("active"))
    return False


def is_provider_active(name: str) -> bool:
    """Return whether a provider's models should be visible in /model."""
    if name in ALWAYS_ACTIVE_PROVIDERS:
        return True
    return bool(PROVIDERS.get(name, {}).get("active", False))


def set_provider_active(name: str, active: bool) -> bool:
    """Persist a provider's active flag. DeepSeek stays active by design."""
    if name not in PROVIDERS:
        return False
    if name in ALWAYS_ACTIVE_PROVIDERS and not active:
        PROVIDERS[name]["active"] = True
        return False

    CUSTOM_PROVIDERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {"providers": {}, "models": {}, "provider_states": {}}
    if CUSTOM_PROVIDERS_PATH.exists():
        try:
            data = json.loads(CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    data.setdefault("providers", {})
    data.setdefault("models", {})
    data.setdefault("provider_states", {})
    data["provider_states"][name] = {"active": bool(active)}
    CUSTOM_PROVIDERS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    PROVIDERS[name]["active"] = bool(active) or name in ALWAYS_ACTIVE_PROVIDERS
    return True


def _normalise_custom_model_entries(
    provider_name: str,
    models_cfg: dict,
    existing_models: dict | None = None,
) -> dict:
    normalised: dict = {}
    existing_models = existing_models or {}
    for alias, model in models_cfg.items():
        if not isinstance(model, dict):
            continue
        model_copy = dict(model)
        model_copy.setdefault("id", alias)
        model_provider = model_copy.get("provider") or provider_name
        model_copy["provider"] = model_provider
        model_id = str(model_copy.get("id") or alias)
        if not is_chat_model_candidate(model_id):
            continue
        resolved_alias = custom_model_alias(model_provider, model_id, str(alias))
        existing_owner = existing_models.get(resolved_alias, {}).get("provider")
        if existing_owner and existing_owner != model_provider:
            resolved_alias = custom_model_alias(
                model_provider,
                model_id,
                str(alias),
                force_prefix=True,
            )
        normalised[resolved_alias] = model_copy
    return normalised


def _normalize_url(raw: str, api_format: str = "openai") -> str:
    """Ensure base_url ends with the correct chat endpoint path."""
    raw = raw.rstrip("/")
    if raw.endswith("/chat/completions") or raw.endswith("/messages"):
        return raw
    suffix = "/messages" if api_format == "anthropic" else "/chat/completions"
    if raw.endswith("/v1"):
        return raw + suffix
    return raw + "/v1" + suffix


def _validate_base_url(raw: str) -> str:
    parsed = urlparse(str(raw).strip())
    if parsed.scheme not in _CUSTOM_PROVIDER_ALLOWED_SCHEMES:
        raise ValueError(
            f"unsupported provider base_url scheme '{parsed.scheme or '(missing)'}'; "
            "only http:// and https:// are allowed"
        )
    if not parsed.netloc:
        raise ValueError("provider base_url must include a network location")
    return str(raw).strip()


def _validated_custom_provider_data(data: dict) -> tuple[dict, dict]:
    providers = data.get("providers", {})
    models = data.get("models", {})
    if not isinstance(providers, dict):
        raise ValueError("custom providers file: 'providers' must be an object")
    if not isinstance(models, dict):
        raise ValueError("custom providers file: 'models' must be an object")
    provider_states = data.get("provider_states", {})
    if provider_states is not None and not isinstance(provider_states, dict):
        raise ValueError("custom providers file: 'provider_states' must be an object")

    validated_providers: dict = {}
    for name, prov in providers.items():
        if not isinstance(prov, dict):
            raise ValueError(f"provider '{name}' must be an object")
        base_url = _validate_base_url(prov.get("base_url", ""))
        api_key_env = str(prov.get("api_key_env", "")).strip()
        api_format = str(prov.get("api_format", "openai")).strip().lower() or "openai"
        if api_format not in {"openai", "anthropic"}:
            raise ValueError(f"provider '{name}' has unsupported api_format '{api_format}'")
        if not api_key_env:
            raise ValueError(f"provider '{name}' must declare api_key_env")
        validated_providers[name] = {
            **prov,
            "base_url": base_url,
            "api_key_env": api_key_env,
            "api_format": api_format,
        }

    validated_models: dict = {}
    for alias, model in models.items():
        if not isinstance(model, dict):
            raise ValueError(f"model '{alias}' must be an object")
        validated_models[alias] = dict(model)

    return validated_providers, validated_models


def init_providers(force: bool = False) -> None:
    global _providers_initialized
    if _providers_initialized and not force:
        return
    load_custom_providers()
    _providers_initialized = True


def models_url_from_base_url(raw: str) -> str:
    """Return the provider's OpenAI-compatible model-list endpoint."""
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(raw.strip().rstrip("/"))
    path = parsed.path.rstrip("/")
    if path.endswith("/v1/models"):
        models_path = path
    else:
        for suffix in ("/chat/completions", "/messages"):
            if path.endswith(suffix):
                path = path[: -len(suffix)]
                break
        if path.endswith("/v1"):
            path = path[: -len("/v1")]
        models_path = f"{path}/v1/models" if path else "/v1/models"
    return urlunparse((parsed.scheme, parsed.netloc, models_path, "", "", ""))


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
    """Return (base_url, api_key). Keys are read from environment variables."""
    m    = MODELS.get(model_alias, MODELS[DEFAULT_MODEL])
    prov = PROVIDERS.get(m["provider"], list(PROVIDERS.values())[0])
    key  = os.getenv(prov["api_key_env"], "")
    fmt  = prov.get("api_format", "openai")
    return _normalize_url(prov["base_url"], fmt), key


def get_api_format(model_alias: str) -> str:
    """Return 'openai' or 'anthropic'."""
    m    = MODELS.get(model_alias, MODELS[DEFAULT_MODEL])
    prov = PROVIDERS.get(m["provider"], {})
    return prov.get("api_format", "openai")


def get_provider_config(model_alias: str) -> dict:
    """Return the full provider configuration dictionary."""
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
    """Check whether the model's key is configured. Return (ok, missing_env_var)."""
    _, key = get_api_config(model_alias)
    if not key:
        m    = MODELS.get(model_alias, MODELS[DEFAULT_MODEL])
        prov = PROVIDERS.get(m["provider"], {})
        return False, prov.get("api_key_env", "")
    return True, ""


def list_configured_models() -> list[str]:
    """Return all model aliases whose provider keys are configured."""
    return [alias for alias in MODELS if validate_api_key(alias)[0]]


def get_best_vision_model() -> tuple[str | None, str | None, str | None]:
    """Return the first configured vision model by priority."""
    for alias in VISION_PRIORITY:
        m = MODELS.get(alias)
        if not m or not m.get("vision"):
            continue
        url, key = get_api_config(alias)
        if key:
            return alias, url, key
    return None, None, None


def list_vision_models() -> list[str]:
    """Return all model aliases marked with vision=True."""
    return [alias for alias, m in MODELS.items() if m.get("vision")]


def load_custom_providers() -> None:
    """Load custom providers from custom_providers.json into PROVIDERS/MODELS."""
    # Reload .env so keys added after startup (e.g. via wizard) are available
    try:
        from dotenv import load_dotenv
        _env = PAWNLOGIC_HOME / ".env"
        if _env.exists():
            load_dotenv(_env, override=True)
    except ImportError:
        pass
    if not CUSTOM_PROVIDERS_PATH.exists():
        for name, prov in PROVIDERS.items():
            prov["active"] = name in ALWAYS_ACTIVE_PROVIDERS
        for name in list(PROVIDERS):
            if name not in BUILTIN_PROVIDER_NAMES:
                del PROVIDERS[name]
        for alias in list(MODELS):
            if alias not in BUILTIN_MODEL_ALIASES:
                del MODELS[alias]
        return
    try:
        data = json.loads(CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8"))
        custom_providers, custom_models = _validated_custom_provider_data(data)
    except Exception:
        return
    for name, prov in PROVIDERS.items():
        prov["active"] = _provider_active_from_data(name, prov, data)
    for name in list(PROVIDERS):
        if name not in BUILTIN_PROVIDER_NAMES and name not in custom_providers:
            del PROVIDERS[name]
    for alias in list(MODELS):
        if alias not in BUILTIN_MODEL_ALIASES:
            del MODELS[alias]
    for name, prov in custom_providers.items():
        if name in BUILTIN_PROVIDER_NAMES:
            continue
        prov.setdefault("api_format", "openai")
        prov["active"] = _provider_active_from_data(name, prov, data)
        PROVIDERS[name] = prov
    normalised_models: dict = {}
    for name in custom_providers:
        normalised_models.update(
            _normalise_custom_model_entries(
                name,
                {
                    alias: model
                    for alias, model in custom_models.items()
                    if isinstance(model, dict) and model.get("provider") == name
                },
                normalised_models,
            )
        )
    for alias, model in normalised_models.items():
        if alias in BUILTIN_MODEL_ALIASES:
            continue
        model.setdefault("desc", CUSTOM_MODEL_DESC)
        model.setdefault("color", "\033[37m")
        model.setdefault("vision", False)
        MODELS[alias] = model


def save_custom_provider(
    name: str,
    prov_cfg: dict,
    models_cfg: dict,
    *,
    replace_models: bool = False,
) -> None:
    """Persist a custom provider to custom_providers.json without storing keys."""
    CUSTOM_PROVIDERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {"providers": {}, "models": {}}
    if CUSTOM_PROVIDERS_PATH.exists():
        try:
            data = json.loads(CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    data.setdefault("providers", {})
    data.setdefault("models", {})
    data.setdefault("provider_states", {})
    prov_cfg = dict(prov_cfg)
    prov_cfg["base_url"] = _validate_base_url(prov_cfg.get("base_url", ""))
    prov_cfg["active"] = _provider_active_from_data(name, prov_cfg, data)
    data["providers"][name] = prov_cfg
    if replace_models:
        data["models"] = {
            alias: model
            for alias, model in data.get("models", {}).items()
            if model.get("provider") != name
        }
    data["models"].update(
        _normalise_custom_model_entries(name, models_cfg, data.get("models", {}))
    )
    CUSTOM_PROVIDERS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def remove_custom_provider(name: str) -> bool:
    """Remove a custom provider from the JSON file. Return whether it changed."""
    if not CUSTOM_PROVIDERS_PATH.exists():
        return False
    try:
        data = json.loads(CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return False
    if name not in data.get("providers", {}):
        return False
    del data["providers"][name]
    data.get("provider_states", {}).pop(name, None)
    to_remove = [a for a, m in data.get("models", {}).items()
                 if m.get("provider") == name]
    for a in to_remove:
        del data["models"][a]
    CUSTOM_PROVIDERS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return True
