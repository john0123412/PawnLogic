"""
tests/test_providers.py — Unit tests for config/providers.py

Covers:
  - _normalize_url appends correct endpoint suffix
  - validate_api_key returns (False, env_var) when key missing
  - validate_api_key returns (True, '') when key present
  - get_api_format returns 'openai' or 'anthropic'
  - list_vision_models returns only vision-capable aliases
  - is_fast_model detects flash/haiku/mini/turbo/lite keywords
  - PROVIDERS and MODELS dicts are structurally valid
"""

import os
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

for _key in list(sys.modules):
    if _key == "config" or _key.startswith("config."):
        _f = getattr(sys.modules[_key], "__file__", "") or ""
        if ROOT not in _f:
            del sys.modules[_key]

from config.providers import (  # noqa: E402
    PROVIDERS, MODELS, DEFAULT_MODEL,
    _normalize_url, validate_api_key, get_api_format,
    list_vision_models, is_fast_model, find_fast_peer,
    get_best_vision_model, list_configured_models,
    register_provider, remove_provider,
    register_model, remove_model, remove_models_for_provider,
    provider_snapshot, model_snapshot,
)
import config.providers as _provider_config


# ── _normalize_url ────────────────────────────────────────

def test_normalize_url_already_complete_openai():
    url = "https://api.example.com/v1/chat/completions"
    assert _normalize_url(url, "openai") == url


def test_normalize_url_already_complete_anthropic():
    url = "https://api.anthropic.com/v1/messages"
    assert _normalize_url(url, "anthropic") == url


def test_normalize_url_v1_suffix_openai():
    assert _normalize_url("https://api.example.com/v1", "openai") == \
        "https://api.example.com/v1/chat/completions"


def test_normalize_url_v1_suffix_anthropic():
    assert _normalize_url("https://api.example.com/v1", "anthropic") == \
        "https://api.example.com/v1/messages"


def test_normalize_url_bare_domain_openai():
    result = _normalize_url("https://api.example.com", "openai")
    assert result.endswith("/chat/completions")


def test_normalize_url_bare_domain_anthropic():
    result = _normalize_url("https://api.example.com", "anthropic")
    assert result.endswith("/messages")


def test_normalize_url_strips_trailing_slash():
    result = _normalize_url("https://api.example.com/v1/", "openai")
    assert "//" not in result.replace("://", "@@")


# ── validate_api_key ──────────────────────────────────────

def test_validate_api_key_missing_returns_false(monkeypatch):
    # Temporarily ensure the env var is unset
    model = DEFAULT_MODEL
    prov_key = PROVIDERS[MODELS[model]["provider"]]["api_key_env"]
    monkeypatch.setattr(_provider_config, "_providers_initialized", True)
    original = os.environ.pop(prov_key, None)
    try:
        ok, env = validate_api_key(model)
        assert ok is False
        assert env == prov_key
    finally:
        if original is not None:
            os.environ[prov_key] = original


def test_validate_api_key_present_returns_true():
    model = DEFAULT_MODEL
    prov_key = PROVIDERS[MODELS[model]["provider"]]["api_key_env"]
    original = os.environ.get(prov_key)
    os.environ[prov_key] = "sk-test-key-12345"
    try:
        ok, env = validate_api_key(model)
        assert ok is True
        assert env == ""
    finally:
        if original is None:
            os.environ.pop(prov_key, None)
        else:
            os.environ[prov_key] = original


# ── get_api_format ────────────────────────────────────────

def test_get_api_format_openai_model():
    assert get_api_format("ds-v4-flash") == "openai"
    assert get_api_format("gpt-4o") == "openai"


def test_get_api_format_anthropic_model():
    assert get_api_format("claude-sonnet") == "anthropic"
    assert get_api_format("claude-haiku") == "anthropic"


# ── list_vision_models ────────────────────────────────────

def test_list_vision_models_not_empty():
    vision = list_vision_models()
    assert len(vision) > 0


def test_list_vision_models_all_have_vision_flag():
    for alias in list_vision_models():
        assert MODELS[alias].get("vision") is True, \
            f"{alias} is in vision list but vision=False"


def test_list_vision_models_no_non_vision():
    non_vision = [a for a, m in MODELS.items() if not m.get("vision")]
    vision_set = set(list_vision_models())
    overlap = vision_set & set(non_vision)
    assert not overlap, f"Non-vision models in vision list: {overlap}"


# ── is_fast_model ─────────────────────────────────────────

def test_is_fast_model_flash():
    assert is_fast_model("ds-v4-flash") is True


def test_is_fast_model_haiku():
    assert is_fast_model("claude-haiku") is True


def test_is_fast_model_pro_is_not_fast():
    assert is_fast_model("ds-v4-pro") is False
    assert is_fast_model("claude-sonnet") is False


# ── PROVIDERS / MODELS structural validation ─────────────

def test_providers_required_keys():
    required = {"base_url", "api_key_env", "api_format"}
    for name, prov in PROVIDERS.items():
        missing = required - prov.keys()
        assert not missing, f"PROVIDERS[{name!r}] missing: {missing}"


def test_models_required_keys():
    required = {"id", "provider", "desc", "color", "vision"}
    for alias, m in MODELS.items():
        missing = required - m.keys()
        assert not missing, f"MODELS[{alias!r}] missing: {missing}"


def test_models_provider_exists():
    for alias, m in MODELS.items():
        assert m["provider"] in PROVIDERS, \
            f"MODELS[{alias!r}].provider={m['provider']!r} not in PROVIDERS"


def test_default_model_exists():
    assert DEFAULT_MODEL in MODELS


# ── provider store interface ──────────────────────────────

def test_register_and_remove_provider_roundtrip():
    register_provider("pytest_store_prov", {"api_key_env": "X", "active": False})
    try:
        assert "pytest_store_prov" in provider_snapshot()
    finally:
        removed = remove_provider("pytest_store_prov")
    assert removed == {"api_key_env": "X", "active": False}
    assert "pytest_store_prov" not in provider_snapshot()


def test_register_provider_ignores_empty_name():
    before = set(provider_snapshot())
    register_provider("", {"api_key_env": "X"})
    assert set(provider_snapshot()) == before


def test_register_and_remove_model_roundtrip():
    register_model("pytest:store_model", {"id": "m", "provider": "pytest_store_prov"})
    try:
        assert "pytest:store_model" in model_snapshot()
    finally:
        remove_model("pytest:store_model")
    assert "pytest:store_model" not in model_snapshot()


def test_remove_models_for_provider_removes_only_owned():
    register_model("pytest:a", {"id": "a", "provider": "pytest_owner"})
    register_model("pytest:b", {"id": "b", "provider": "pytest_owner"})
    register_model("pytest:c", {"id": "c", "provider": "other"})
    try:
        removed = sorted(remove_models_for_provider("pytest_owner"))
        assert removed == ["pytest:a", "pytest:b"]
        assert "pytest:c" in model_snapshot()
    finally:
        remove_model("pytest:c")


def test_snapshot_is_detached_copy():
    snap = model_snapshot()
    snap["pytest:ghost"] = {"id": "ghost"}
    assert "pytest:ghost" not in model_snapshot()


def test_provider_store_lock_is_reentrant_for_snapshot_reads():
    with _provider_config._PROVIDER_STORE_LOCK:
        register_model("pytest:locked", {"id": "locked", "provider": "pytest"})
        try:
            assert "pytest:locked" in model_snapshot()
        finally:
            remove_model("pytest:locked")


def test_provider_auto_routing_respects_inactive_providers(monkeypatch):
    monkeypatch.setattr(
        _provider_config,
        "PROVIDERS",
        {
            "relay": {"api_key_env": "RELAY_API_KEY", "active": False},
            "active": {
                "base_url": "https://active.example.com/v1/chat/completions",
                "api_key_env": "ACTIVE_API_KEY",
                "active": True,
            },
        },
    )
    monkeypatch.setattr(
        _provider_config,
        "MODELS",
        {
            "ds-v4-flash": {"id": "deepseek-v4-flash", "provider": "relay", "vision": False},
            "relay-pro": {"id": "relay-pro", "provider": "relay", "vision": True},
            "relay-fast": {"id": "relay-flash", "provider": "relay", "vision": True},
            "active-vision": {"id": "active-mini", "provider": "active", "vision": True},
        },
    )
    monkeypatch.setattr(_provider_config, "VISION_PRIORITY", ["relay-pro", "active-vision"])
    monkeypatch.setattr(_provider_config, "_providers_initialized", True)
    monkeypatch.setenv("RELAY_API_KEY", "relay-key")
    monkeypatch.setenv("ACTIVE_API_KEY", "active-key")

    assert find_fast_peer("relay-pro") is None
    assert list_configured_models() == ["active-vision"]
    assert get_best_vision_model()[0] == "active-vision"


def test_load_custom_providers_logs_on_malformed_json(tmp_path, monkeypatch):
    bad = tmp_path / "custom_providers.json"
    bad.write_text("{ this is not valid json ", encoding="utf-8")
    monkeypatch.setattr(_provider_config, "CUSTOM_PROVIDERS_PATH", bad)

    logged = {}

    class _FakeLogger:
        def warning(self, msg, *args):
            logged["msg"] = msg

    import core.logger as _core_logger
    monkeypatch.setattr(_core_logger, "logger", _FakeLogger())

    # Must not raise, and must surface the failure to the logger (not silent).
    _provider_config.load_custom_providers()
    assert "Failed to load custom_providers.json" in logged.get("msg", "")


def test_set_provider_active_logs_and_preserves_malformed_json(tmp_path, monkeypatch):
    bad = tmp_path / "custom_providers.json"
    bad.write_text("{ this is not valid json ", encoding="utf-8")
    monkeypatch.setattr(_provider_config, "CUSTOM_PROVIDERS_PATH", bad)
    monkeypatch.setattr(
        _provider_config,
        "PROVIDERS",
        {"relay": {"api_key_env": "RELAY_API_KEY", "active": False}},
    )

    logged = {}

    class _FakeLogger:
        def warning(self, msg, *args):
            logged["msg"] = msg.format(*args)

    import core.logger as _core_logger
    monkeypatch.setattr(_core_logger, "logger", _FakeLogger())

    assert _provider_config.set_provider_active("relay", True) is False
    assert bad.read_text(encoding="utf-8") == "{ this is not valid json "
    assert "Failed to update provider state in custom_providers.json" in logged.get("msg", "")
