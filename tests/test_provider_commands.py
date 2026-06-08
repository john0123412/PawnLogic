"""Regression tests for provider management commands."""

from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

from config import providers as provider_config
from core import provider_tui
from core.commands import provider as provider_cmd


def test_provider_tui_add_wizard_api_key_field_accepts_pasted_text():
    tui = provider_tui.ProviderTUI()
    pasted_key = "sk-pasted-key-with-symbols_1234567890"

    tui._wiz_inputs[0].text = "relay"
    tui._wiz_inputs[1].text = "https://api.example.com/v1"
    tui._wiz_fields[2] = "openai"
    tui._wiz_inputs[2].text = pasted_key

    tui._sync_wizard_fields_from_inputs()

    assert tui._wiz_fields == [
        "relay",
        "https://api.example.com/v1",
        "openai",
        pasted_key,
    ]


def test_provider_tui_model_search_field_accepts_pasted_text():
    tui = provider_tui.ProviderTUI()
    pasted_model_name = "provider-prefix/some-long-model-name-v1"

    tui._ms_search_ta.text = pasted_model_name

    tui._sync_model_search_from_input()

    assert tui._ms_search == pasted_model_name


def test_models_url_from_base_url_preserves_proxy_path():
    assert (
        provider_config.models_url_from_base_url(
            "https://relay.example.com/openai/v1/chat/completions"
        )
        == "https://relay.example.com/openai/v1/models"
    )
    assert (
        provider_config.models_url_from_base_url("https://relay.example.com/openai/v1")
        == "https://relay.example.com/openai/v1/models"
    )


def test_save_custom_provider_preserves_models_by_default(tmp_path, monkeypatch):
    path = tmp_path / "custom_providers.json"
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    path.write_text(
        json.dumps(
            {
                "providers": {
                    "relay": {
                        "base_url": "https://api.example.com/v1/chat/completions",
                        "api_key_env": "RELAY_API_KEY",
                        "label": "Relay",
                        "api_format": "openai",
                    },
                    "other": {
                        "base_url": "https://other.example.com/v1/chat/completions",
                        "api_key_env": "OTHER_API_KEY",
                        "label": "Other",
                        "api_format": "openai",
                    },
                },
                "models": {
                    "old-relay-model": {"id": "old", "provider": "relay"},
                    "other-model": {"id": "other", "provider": "other"},
                },
            }
        ),
        encoding="utf-8",
    )

    provider_config.save_custom_provider(
        "relay",
        {
            "base_url": "https://api.example.com/v1/chat/completions",
            "api_key_env": "RELAY_API_KEY",
            "label": "Relay",
            "api_format": "openai",
        },
        {"new-relay-model": {"id": "new", "provider": "relay"}},
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert sorted(data["models"]) == ["new-relay-model", "old-relay-model", "other-model"]


def test_save_custom_provider_can_replace_models_for_same_provider(tmp_path, monkeypatch):
    path = tmp_path / "custom_providers.json"
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    path.write_text(
        json.dumps(
            {
                "providers": {
                    "relay": {
                        "base_url": "https://api.example.com/v1/chat/completions",
                        "api_key_env": "RELAY_API_KEY",
                        "label": "Relay",
                        "api_format": "openai",
                    },
                    "other": {
                        "base_url": "https://other.example.com/v1/chat/completions",
                        "api_key_env": "OTHER_API_KEY",
                        "label": "Other",
                        "api_format": "openai",
                    },
                },
                "models": {
                    "old-relay-model": {"id": "old", "provider": "relay"},
                    "other-model": {"id": "other", "provider": "other"},
                },
            }
        ),
        encoding="utf-8",
    )

    provider_config.save_custom_provider(
        "relay",
        {
            "base_url": "https://api.example.com/v1/chat/completions",
            "api_key_env": "RELAY_API_KEY",
            "label": "Relay",
            "api_format": "openai",
        },
        {"new-relay-model": {"id": "new", "provider": "relay"}},
        replace_models=True,
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert sorted(data["models"]) == ["new-relay-model", "other-model"]


def test_provider_add_cli_fetches_without_nested_event_loop(monkeypatch):
    alias = "pytest_relay"
    env_key = "PYTEST_RELAY_API_KEY"
    monkeypatch.setenv(env_key, "test-key")
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    provider_cmd.PROVIDERS.pop(alias, None)

    saved = {}

    def fake_save_custom_provider(name, provider_cfg, models_cfg):
        saved["name"] = name
        saved["provider_cfg"] = provider_cfg
        saved["models_cfg"] = models_cfg

    fetch = AsyncMock()
    monkeypatch.setattr(provider_cmd, "_provider_fetch", fetch)
    monkeypatch.setattr(provider_cmd, "_provider_add", lambda: None)
    monkeypatch.setattr(provider_cmd, "_provider_list", lambda: None)
    monkeypatch.setattr(provider_cmd, "_provider_test", lambda _session, _arg: None)
    monkeypatch.setattr(provider_config, "save_custom_provider", fake_save_custom_provider)
    monkeypatch.setattr(provider_config, "load_custom_providers", lambda: None)

    try:
        asyncio.run(
            provider_cmd._handle_provider_cmd(
                "add",
                f"{alias} https://api.example.com/v1 {env_key}",
                SimpleNamespace(),
            )
        )
    finally:
        provider_cmd.PROVIDERS.pop(alias, None)

    assert saved["name"] == alias
    assert saved["provider_cfg"]["api_key_env"] == env_key
    fetch.assert_awaited_once_with(alias)


def test_provider_add_cli_does_not_prompt_for_fetch_on_piped_input(monkeypatch):
    alias = "pytest_piped_relay"
    env_key = "PYTEST_PIPED_RELAY_API_KEY"
    monkeypatch.setenv(env_key, "test-key")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    provider_cmd.PROVIDERS.pop(alias, None)

    input_called = False

    def fake_input(_prompt):
        nonlocal input_called
        input_called = True
        return ""

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(provider_config, "save_custom_provider", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(provider_config, "load_custom_providers", lambda: None)

    try:
        should_fetch = provider_cmd._provider_add_cli(
            alias,
            "https://api.example.com/v1",
            env_key,
        )
    finally:
        provider_cmd.PROVIDERS.pop(alias, None)

    assert should_fetch is False
    assert input_called is False
