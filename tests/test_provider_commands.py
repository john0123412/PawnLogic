"""Regression tests for provider management commands."""

from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

from prompt_toolkit.document import Document
from prompt_toolkit.application import Application

import main as pawn_main
import pawnlogic.cli as pawn_cli
from config import providers as provider_config
from core.api_errors import format_http_error
from core import provider_runtime, provider_tui
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


def test_provider_tui_add_wizard_navigation_moves_real_input_focus():
    tui = provider_tui.ProviderTUI()
    tui._panel = "wizard"
    kb = tui._build_kb()
    app = Application(
        layout=tui._build_layout(),
        key_bindings=kb,
        style=provider_tui.TUI_STYLE,
        full_screen=False,
    )
    tui._app = app
    next_handler = next(binding.handler for binding in kb.bindings if binding.handler.__name__ == "_w_next")

    assert app.layout.current_control is tui._wiz_inputs[0].control

    next_handler(SimpleNamespace(app=app))

    assert tui._wiz_focus == 1
    assert app.layout.current_control is tui._wiz_inputs[1].control

    next_handler(SimpleNamespace(app=app))
    next_handler(SimpleNamespace(app=app))

    assert tui._wiz_focus == 3
    assert app.layout.current_control is tui._wiz_inputs[2].control


def test_provider_tui_model_search_field_accepts_pasted_text():
    tui = provider_tui.ProviderTUI()
    pasted_model_name = "provider-prefix/some-long-model-name-v1"

    tui._ms_search_ta.text = pasted_model_name

    tui._sync_model_search_from_input()

    assert tui._ms_search == pasted_model_name


def test_pawn_completer_includes_live_visible_models_without_rebuild():
    completer = pawn_main.PawnCompleter(
        ["/model", "/model ds-v4-flash"],
        meta_dict={"/model": "switch", "/model ds-v4-flash": "DeepSeek"},
        dynamic_model_provider=lambda: {
            "1:gpt-5.5": {"desc": "Dynamically fetched model"},
        },
    )

    completions = list(completer.get_completions(Document("/model"), None))
    words = [completion.text for completion in completions]
    meta_by_word = {completion.text: completion.display_meta_text for completion in completions}

    assert "/model 1:gpt-5.5" in words
    assert meta_by_word["/model 1:gpt-5.5"] == "Dynamically fetched model"
    assert "/model 1:gpt-5.5" not in completer.meta_dict


def test_packaged_cli_completer_includes_live_visible_models_without_rebuild():
    completer = pawn_cli.PawnCompleter(
        ["/model", "/model ds-v4-flash"],
        meta_dict={"/model": "switch", "/model ds-v4-flash": "DeepSeek"},
        dynamic_model_provider=lambda: {
            "1:gpt-5.5": {"desc": "Dynamically fetched model"},
        },
    )

    completions = list(completer.get_completions(Document("/model"), None))
    words = [completion.text for completion in completions]
    meta_by_word = {completion.text: completion.display_meta_text for completion in completions}

    assert "/model 1:gpt-5.5" in words
    assert meta_by_word["/model 1:gpt-5.5"] == "Dynamically fetched model"
    assert "/model 1:gpt-5.5" not in completer.meta_dict


def test_provider_model_name_filter_hides_non_chat_and_legacy_models():
    assert provider_tui._model_is_chat_candidate("gpt-4o") is True
    assert provider_tui._model_is_chat_candidate("gpt-4o-mini-vision") is True
    assert provider_tui._model_is_chat_candidate("text-embedding-3-large") is False
    assert provider_tui._model_is_chat_candidate("gpt-3.5-turbo-instruct") is False
    assert provider_tui._model_is_chat_candidate("davinci-002") is False
    assert provider_tui._model_is_chat_candidate("gpt-image-2") is False
    assert provider_tui._model_is_chat_candidate("gpt-image-1") is False
    assert provider_tui._model_is_chat_candidate("gpt-image-1.5") is False
    assert provider_tui._model_is_chat_candidate("gpt-4o-realtime-preview") is False
    assert provider_tui._model_is_chat_candidate("tts-1") is False


def test_provider_active_state_defaults_deepseek_only_for_model_visibility(monkeypatch):
    monkeypatch.setattr(
        provider_config,
        "PROVIDERS",
        {
            "deepseek": {"api_key_env": "DEEPSEEK_API_KEY", "active": True},
            "relay": {"api_key_env": "RELAY_API_KEY", "active": False},
            "xiaomi": {"api_key_env": "XIAOMI_API_KEY", "active": True},
        },
    )
    monkeypatch.setattr(provider_cmd, "PROVIDERS", provider_config.PROVIDERS)
    monkeypatch.setattr(
        provider_cmd,
        "MODELS",
        {
            "ds-v4-flash": {"id": "deepseek-v4-flash", "provider": "deepseek"},
            "relay-chat": {"id": "relay-chat", "provider": "relay"},
            "mimo": {"id": "mimo", "provider": "xiaomi"},
        },
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("RELAY_API_KEY", "test-key")
    monkeypatch.setenv("XIAOMI_API_KEY", "test-key")

    visible = provider_cmd._visible_models()

    assert sorted(visible) == ["ds-v4-flash", "mimo"]


def test_load_custom_providers_defaults_only_deepseek_active_without_config(tmp_path, monkeypatch):
    path = tmp_path / "custom_providers.json"
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(
        provider_config,
        "PROVIDERS",
        {
            "deepseek": {"api_key_env": "DEEPSEEK_API_KEY"},
            "openai": {"api_key_env": "OPENAI_API_KEY"},
        },
    )
    monkeypatch.setattr(provider_config, "MODELS", {})

    provider_config.load_custom_providers()

    assert provider_config.PROVIDERS["deepseek"]["active"] is True
    assert provider_config.PROVIDERS["openai"]["active"] is False


def test_load_custom_providers_defaults_missing_model_desc(tmp_path, monkeypatch):
    path = tmp_path / "custom_providers.json"
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(
        provider_config,
        "PROVIDERS",
        {
            "deepseek": {"api_key_env": "DEEPSEEK_API_KEY"},
        },
    )
    monkeypatch.setattr(provider_config, "MODELS", {})
    path.write_text(
        json.dumps(
            {
                "providers": {
                    "relay": {
                        "base_url": "https://api.example.com/v1",
                        "api_key_env": "RELAY_API_KEY",
                        "label": "Relay",
                        "api_format": "openai",
                    }
                },
                "models": {
                    "relay-chat": {"id": "relay-chat", "provider": "relay"},
                    "relay-pro": {
                        "id": "relay-pro",
                        "provider": "relay",
                        "desc": "Existing description",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    provider_config.load_custom_providers()

    assert provider_config.MODELS["relay-chat"]["desc"] == "Custom model"
    assert provider_config.MODELS["relay-pro"]["desc"] == "Existing description"


def test_get_provider_config_lazily_initializes_custom_providers(tmp_path, monkeypatch):
    path = tmp_path / "custom_providers.json"
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(provider_config, "_providers_initialized", False)
    monkeypatch.setattr(
        provider_config,
        "PROVIDERS",
        {
            "deepseek": {
                "base_url": "https://api.deepseek.com/v1/chat/completions",
                "api_key_env": "DEEPSEEK_API_KEY",
                "api_format": "openai",
            },
        },
    )
    monkeypatch.setattr(
        provider_config,
        "MODELS",
        {
            "ds-v4-flash": {"id": "deepseek-v4-flash", "provider": "deepseek"},
        },
    )
    monkeypatch.setenv("RELAY_API_KEY", "relay-secret")
    path.write_text(
        json.dumps(
            {
                "providers": {
                    "relay": {
                        "base_url": "https://relay.example/v1",
                        "api_key_env": "RELAY_API_KEY",
                        "label": "Relay",
                        "api_format": "openai",
                    }
                },
                "models": {
                    "relay-chat": {"id": "relay-chat", "provider": "relay"},
                },
            }
        ),
        encoding="utf-8",
    )

    cfg = provider_config.get_provider_config("relay-chat")

    assert provider_config._providers_initialized is True
    assert cfg["base_url"] == "https://relay.example/v1/chat/completions"
    assert cfg["api_key"] == "relay-secret"
    assert provider_config.MODELS["relay-chat"]["desc"] == "Custom model"


def test_provider_set_active_persists_and_deepseek_cannot_deactivate(tmp_path, monkeypatch):
    path = tmp_path / "custom_providers.json"
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(
        provider_config,
        "PROVIDERS",
        {
            "deepseek": {"api_key_env": "DEEPSEEK_API_KEY", "active": True},
            "relay": {"api_key_env": "RELAY_API_KEY", "active": False},
        },
    )

    assert provider_config.set_provider_active("relay", True) is True
    assert provider_config.PROVIDERS["relay"]["active"] is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["provider_states"]["relay"]["active"] is True

    assert provider_config.set_provider_active("deepseek", False) is False
    assert provider_config.PROVIDERS["deepseek"]["active"] is True


def test_provider_model_probe_rejects_explicit_unsupported_response():
    assert (
        provider_tui._model_rejection_reason(
            '{"error":{"message":"The gpt-3.5-turbo model is not supported"}}'
        )
        == "unsupported"
    )


def test_provider_model_probe_accepts_non_model_specific_400():
    assert provider_tui._model_rejection_reason('{"error":{"message":"missing field"}}') == ""


def test_provider_filter_supported_chat_models_removes_unsupported(monkeypatch):
    async def fake_probe(_client, _endpoint, _api_key, model_id):
        return (model_id != "old-model", "unsupported" if model_id == "old-model" else "")

    monkeypatch.setattr(provider_runtime, "probe_openai_chat_model", fake_probe)

    supported, removed = asyncio.run(
        provider_runtime.filter_supported_chat_models(
            "https://api.example.com/v1",
            "test-key",
            [
                ("new-model", {"id": "new-model"}),
                ("old-model", {"id": "old-model"}),
            ],
        )
    )

    assert [mid for mid, _cfg in supported] == ["new-model"]
    assert removed == 1


def test_provider_sync_notice_reports_hidden_and_alias_changes():
    lines = provider_tui._format_model_sync_notice(
        {"returned": 5, "hidden_by_name": 2, "hidden_by_probe": 1, "selectable": 2},
        [("gpt-5.4-mini", "relay:gpt-5.4-mini")],
    )

    assert lines[0] == (
        "Sync summary: 5 returned; 2 hidden by type/name; "
        "1 hidden by chat probe; 2 selectable."
    )
    assert "gpt-5.4-mini -> relay:gpt-5.4-mini" in lines[1]


def test_provider_first_chat_model_prefers_registered_provider_chat_model(monkeypatch):
    monkeypatch.setattr(
        provider_runtime,
        "MODELS",
        {
            "gpt-image-2": {"id": "gpt-image-2", "provider": "relay"},
            "relay-chat": {"id": "relay-chat-id", "provider": "relay"},
            "other-chat": {"id": "other-chat-id", "provider": "other"},
        },
    )

    assert provider_tui._first_provider_chat_model("relay") == "relay-chat-id"


def test_provider_detail_test_uses_registered_provider_model(monkeypatch):
    alias = "pytest_detail_test"
    env_key = "PYTEST_DETAIL_TEST_API_KEY"
    tui = provider_tui.ProviderTUI()
    tui._detail_provider = alias
    monkeypatch.setenv(env_key, "test-key")
    monkeypatch.setattr(
        provider_tui,
        "PROVIDERS",
        {
            alias: {
                "base_url": "https://api.example.com/v1",
                "api_key_env": env_key,
                "api_format": "openai",
            }
        },
    )
    monkeypatch.setattr(
        provider_runtime,
        "MODELS",
        {
            "relay-chat": {"id": "relay-chat-id", "provider": alias},
        },
    )
    seen = {}

    async def fake_test_connection(base_url, api_key, api_format, model_id=None):
        seen["base_url"] = base_url
        seen["api_key"] = api_key
        seen["api_format"] = api_format
        seen["model_id"] = model_id
        return True, "Connected", 1

    monkeypatch.setattr(provider_tui, "_test_connection", fake_test_connection)

    asyncio.run(tui._run_test_detail(alias))

    assert seen == {
        "base_url": "https://api.example.com/v1",
        "api_key": "test-key",
        "api_format": "openai",
        "model_id": "relay-chat-id",
    }
    assert tui._detail_status == "✅ Connected"


def test_provider_detail_test_without_models_does_not_use_fallback_model(monkeypatch):
    alias = "pytest_detail_empty"
    env_key = "PYTEST_DETAIL_EMPTY_API_KEY"
    tui = provider_tui.ProviderTUI()
    monkeypatch.setenv(env_key, "test-key")
    monkeypatch.setattr(
        provider_tui,
        "PROVIDERS",
        {
            alias: {
                "base_url": "https://api.example.com/v1",
                "api_key_env": env_key,
                "api_format": "openai",
            }
        },
    )
    monkeypatch.setattr(provider_tui, "MODELS", {})
    monkeypatch.setattr(provider_runtime, "MODELS", {})
    called = False

    async def fake_test_connection(*_args, **_kwargs):
        nonlocal called
        called = True
        return True, "Connected", 1

    monkeypatch.setattr(provider_tui, "_test_connection", fake_test_connection)

    asyncio.run(tui._run_test_detail(alias))

    assert called is False
    assert "Fetch / Sync Models first" in tui._detail_status
    assert tui._detail_status_style == "class:warning"


def test_provider_tui_model_selector_enter_toggles_row_and_confirms_on_button(monkeypatch):
    tui = provider_tui.ProviderTUI()
    tui._panel = "models"
    tui._ms_all = [
        ("model-a", {"id": "model-a", "provider": "relay"}),
        ("model-b", {"id": "model-b", "provider": "relay"}),
    ]
    kb = tui._build_kb()
    app = Application(
        layout=tui._build_layout(),
        key_bindings=kb,
        style=provider_tui.TUI_STYLE,
        full_screen=False,
    )
    tui._app = app
    enter_handler = next(binding.handler for binding in kb.bindings if binding.handler.__name__ == "_ms_enter")
    saved = {"called": False}

    def fake_save_models():
        saved["called"] = True

    monkeypatch.setattr(tui, "_do_save_models", fake_save_models)

    enter_handler(SimpleNamespace(app=app))

    assert tui._ms_selected == {"model-a"}
    assert saved["called"] is False

    tui._ms_cursor = len(tui._ms_all)
    enter_handler(SimpleNamespace(app=app))

    assert saved["called"] is True


def test_provider_tui_model_selector_cancel_button_returns_to_caller():
    tui = provider_tui.ProviderTUI()
    tui._panel = "models"
    tui._ms_caller = "detail"
    tui._ms_all = [("model-a", {"id": "model-a", "provider": "relay"})]
    tui._ms_cursor = len(tui._ms_all) + 2
    kb = tui._build_kb()
    app = Application(
        layout=tui._build_layout(),
        key_bindings=kb,
        style=provider_tui.TUI_STYLE,
        full_screen=False,
    )
    tui._app = app
    enter_handler = next(binding.handler for binding in kb.bindings if binding.handler.__name__ == "_ms_enter")

    enter_handler(SimpleNamespace(app=app))

    assert tui._panel == "detail"
    assert tui._detail_status == "Model sync cancelled."


def test_provider_tui_model_selector_renders_prefixed_alias_hint():
    tui = provider_tui.ProviderTUI()
    tui._panel = "models"
    tui._ms_provider = "relay"
    tui._ms_all = [("gpt-5.4-mini", {"id": "gpt-5.4-mini", "provider": "relay"})]

    rendered = "".join(text for _style, text in tui._render_model_select())

    assert "gpt-5.4-mini -> relay:gpt-5.4-mini" in rendered


def test_provider_tui_model_selector_load_close_exits_after_save(monkeypatch):
    alias = "relay"
    tui = provider_tui.ProviderTUI()
    tui._panel = "models"
    tui._ms_provider = alias
    tui._ms_all = [("model-a", {"id": "model-a", "provider": alias})]
    tui._ms_selected = {"model-a"}
    tui._ms_cursor = len(tui._ms_all) + 1
    monkeypatch.setattr(
        provider_tui,
        "PROVIDERS",
        {
            alias: {
                "base_url": "https://api.example.com/v1",
                "api_key_env": "RELAY_API_KEY",
                "api_format": "openai",
            }
        },
    )
    kb = tui._build_kb()
    app = Application(
        layout=tui._build_layout(),
        key_bindings=kb,
        style=provider_tui.TUI_STYLE,
        full_screen=False,
    )
    tui._app = app
    enter_handler = next(binding.handler for binding in kb.bindings if binding.handler.__name__ == "_ms_enter")
    saved = {"called": False}
    exited = {"called": False}

    def fake_save_custom_provider(*_args, **_kwargs):
        saved["called"] = True

    monkeypatch.setattr(provider_tui, "save_custom_provider", fake_save_custom_provider)
    monkeypatch.setattr(provider_tui, "_record_sync_time", lambda _pname: None)
    monkeypatch.setattr(provider_tui, "_sync_models_to_runtime", lambda: None)
    monkeypatch.setattr(app, "exit", lambda *args, **kwargs: exited.__setitem__("called", True))

    enter_handler(SimpleNamespace(app=app))

    assert saved["called"] is True
    assert exited["called"] is True


def test_provider_tui_save_models_prefixes_builtin_alias_collisions(monkeypatch):
    alias = "relay"
    tui = provider_tui.ProviderTUI()
    tui._ms_provider = alias
    tui._ms_all = [
        ("gpt-5.4-mini", {"id": "gpt-5.4-mini", "provider": alias}),
        ("relay-chat", {"id": "relay-chat", "provider": alias}),
    ]
    tui._ms_selected = {"gpt-5.4-mini", "relay-chat"}
    monkeypatch.setattr(
        provider_tui,
        "PROVIDERS",
        {
            alias: {
                "base_url": "https://api.example.com/v1",
                "api_key_env": "RELAY_API_KEY",
                "api_format": "openai",
            }
        },
    )
    saved = {}

    def fake_save_custom_provider(name, provider_cfg, models_cfg, replace_models=False):
        saved["name"] = name
        saved["models_cfg"] = models_cfg
        saved["replace_models"] = replace_models

    monkeypatch.setattr(provider_tui, "save_custom_provider", fake_save_custom_provider)
    monkeypatch.setattr(provider_tui, "_record_sync_time", lambda _pname: None)
    monkeypatch.setattr(provider_tui, "_sync_models_to_runtime", lambda: None)

    tui._do_save_models()

    assert saved["name"] == alias
    assert sorted(saved["models_cfg"]) == ["relay-chat", "relay:gpt-5.4-mini"]
    assert saved["models_cfg"]["relay:gpt-5.4-mini"]["id"] == "gpt-5.4-mini"
    assert saved["replace_models"] is True


def test_provider_tui_toggle_active_updates_provider_state(monkeypatch):
    alias = "relay"
    tui = provider_tui.ProviderTUI()
    tui._detail_provider = alias
    monkeypatch.setattr(
        provider_tui,
        "PROVIDERS",
        {
            alias: {
                "base_url": "https://api.example.com/v1",
                "api_key_env": "RELAY_API_KEY",
                "active": False,
            }
        },
    )
    seen = {}

    def fake_runtime_set_active(name, active):
        seen["name"] = name
        seen["active"] = active
        provider_tui.PROVIDERS[name]["active"] = active
        return True, "Provider is now active."

    monkeypatch.setattr(provider_tui, "is_provider_active", lambda _name: False)
    monkeypatch.setattr(provider_tui, "_runtime_set_active", fake_runtime_set_active)

    tui._toggle_provider_active(alias)

    assert seen == {"name": alias, "active": True}
    assert tui._detail_status == "✅ Provider is now active."


def test_provider_tui_connection_accepts_nonstandard_success_response():
    response = SimpleNamespace(
        status_code=200,
        text='{"id":"one"}{"id":"two"}',
        json=lambda: json.loads('{"id":"one"}{"id":"two"}'),
    )

    ok, message, ms = provider_tui._connection_result_from_response(response, 12)

    assert ok is True
    assert ms == 12
    assert message == "Connected (12ms; non-standard response)"


def test_provider_tui_connection_reports_http_400_body_when_json_invalid():
    response = SimpleNamespace(
        status_code=400,
        text='{"error":"bad request"}{"extra":"chunk"}',
        json=lambda: json.loads('{"error":"bad request"}{"extra":"chunk"}'),
    )

    ok, message, ms = provider_tui._connection_result_from_response(response, 34)

    assert ok is False
    assert ms == 34
    assert "HTTP 400" in message
    assert "bad request" in message
    assert "Extra data" not in message


def test_provider_tui_and_cli_share_http_error_message(monkeypatch, capsys):
    body = '{"error":{"message":"missing entitlement","type":"auth","code":"forbidden"}}'
    expected = format_http_error(403, body)
    response = SimpleNamespace(
        status_code=403,
        text=body,
        json=lambda: {"error": {"message": "missing entitlement"}},
    )

    ok, tui_message, ms = provider_tui._connection_result_from_response(response, 41)

    assert ok is False
    assert ms == 41
    assert tui_message == expected

    alias = "pytest_http_error"
    env_key = "PYTEST_HTTP_ERROR_API_KEY"
    provider_cmd.PROVIDERS[alias] = {
        "base_url": "https://api.example.com/v1",
        "api_key_env": env_key,
        "label": "Relay",
        "api_format": "openai",
    }
    monkeypatch.setenv(env_key, "test-key")

    async def fake_fetch_models(_base_url, _api_key, _api_format):
        return [], expected, {"returned": 0, "hidden_by_name": 0, "hidden_by_probe": 0, "selectable": 0}

    monkeypatch.setattr(provider_cmd, "fetch_models", fake_fetch_models)

    try:
        asyncio.run(provider_cmd._provider_fetch(alias))
    finally:
        provider_cmd.PROVIDERS.pop(alias, None)

    assert expected in capsys.readouterr().out


def test_provider_tui_add_wizard_saves_without_testing_connection(monkeypatch):
    alias = "pytest_save_only"
    env_key = "PYTEST_SAVE_ONLY_API_KEY"
    tui = provider_tui.ProviderTUI()
    tui._wiz_inputs[0].text = alias
    tui._wiz_inputs[1].text = "http://127.0.0.1:8080/v1"
    tui._wiz_fields[2] = "openai"
    tui._wiz_inputs[2].text = "test-key"
    provider_tui.PROVIDERS.pop(alias, None)

    saved = {}

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("add wizard should not test connection")

    def fake_save_key_to_env(env_var, key):
        saved["env_var"] = env_var
        saved["key"] = key

    def fake_save_custom_provider(name, provider_cfg, models_cfg):
        saved["name"] = name
        saved["provider_cfg"] = provider_cfg
        saved["models_cfg"] = models_cfg

    monkeypatch.setattr(provider_tui, "_test_connection", fail_if_called)
    monkeypatch.setattr(provider_tui, "_save_key_to_env", fake_save_key_to_env)
    monkeypatch.setattr(provider_tui, "save_custom_provider", fake_save_custom_provider)
    monkeypatch.setattr(provider_tui, "init_providers", lambda force=False: None)

    try:
        asyncio.run(tui._wizard_confirm())
    finally:
        provider_tui.PROVIDERS.pop(alias, None)

    assert saved["name"] == alias
    assert saved["env_var"] == env_key
    assert saved["key"] == "test-key"
    assert saved["provider_cfg"]["base_url"] == "http://127.0.0.1:8080/v1"
    assert tui._panel == "main"


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


def test_save_custom_provider_prefixes_builtin_model_alias_collision(tmp_path, monkeypatch):
    path = tmp_path / "custom_providers.json"
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)

    provider_config.save_custom_provider(
        "relay",
        {
            "base_url": "https://api.example.com/v1/chat/completions",
            "api_key_env": "RELAY_API_KEY",
            "label": "Relay",
            "api_format": "openai",
        },
        {"gpt-5.4-mini": {"id": "gpt-5.4-mini", "provider": "relay"}},
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert "gpt-5.4-mini" not in data["models"]
    assert data["models"]["relay:gpt-5.4-mini"]["id"] == "gpt-5.4-mini"


def test_load_custom_providers_ignores_existing_non_chat_models(tmp_path, monkeypatch):
    path = tmp_path / "custom_providers.json"
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    provider_config.MODELS.pop("relay:gpt-5.4-mini", None)
    provider_config.MODELS.pop("gpt-image-2", None)
    path.write_text(
        json.dumps(
            {
                "providers": {
                    "relay": {
                        "base_url": "https://api.example.com/v1/chat/completions",
                        "api_key_env": "RELAY_API_KEY",
                        "label": "Relay",
                        "api_format": "openai",
                    }
                },
                "models": {
                    "gpt-5.4-mini": {"id": "gpt-5.4-mini", "provider": "relay"},
                    "gpt-image-2": {"id": "gpt-image-2", "provider": "relay"},
                },
            }
        ),
        encoding="utf-8",
    )

    try:
        provider_config.load_custom_providers()

        assert "relay:gpt-5.4-mini" in provider_config.MODELS
        assert "gpt-image-2" not in provider_config.MODELS
    finally:
        provider_config.PROVIDERS.pop("relay", None)
        provider_config.MODELS.pop("relay:gpt-5.4-mini", None)
        provider_config.MODELS.pop("gpt-image-2", None)


def test_provider_add_cli_fetches_without_nested_event_loop(monkeypatch):
    alias = "pytest_relay"
    env_key = "PYTEST_RELAY_API_KEY"
    assert provider_cmd.provider_config is provider_config
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
    monkeypatch.setattr(provider_config, "init_providers", lambda force=False: None)

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


def test_provider_fetch_prints_filter_and_alias_summary(monkeypatch, capsys):
    alias = "pytest_fetch_summary"
    env_key = "PYTEST_FETCH_SUMMARY_API_KEY"
    assert provider_cmd.provider_config is provider_config
    monkeypatch.setenv(env_key, "test-key")
    provider_cmd.PROVIDERS[alias] = {
        "base_url": "https://api.example.com/v1",
        "api_key_env": env_key,
        "label": "Relay",
        "api_format": "openai",
    }
    saved = {}

    async def fake_selector(entries):
        return [mid for mid, _cfg in entries]

    def fake_save_custom_provider(name, _provider_cfg, models_cfg, replace_models=False):
        saved["name"] = name
        saved["models_cfg"] = models_cfg
        saved["replace_models"] = replace_models

    async def fake_fetch_models(_base_url, _api_key, _api_format):
        return (
            [
                (
                    "gpt-5.4-mini",
                    {
                        "id": "gpt-5.4-mini",
                        "provider": "",
                        "desc": "Dynamically fetched model",
                    },
                ),
                (
                    "relay-chat",
                    {
                        "id": "relay-chat",
                        "provider": "",
                        "desc": "Dynamically fetched model",
                    },
                ),
            ],
            "",
            {"returned": 4, "hidden_by_name": 1, "hidden_by_probe": 1, "selectable": 2},
        )

    monkeypatch.setattr(provider_cmd, "fetch_models", fake_fetch_models)
    monkeypatch.setattr(provider_cmd, "_provider_fetch_selector", fake_selector)
    monkeypatch.setattr(provider_config, "save_custom_provider", fake_save_custom_provider)
    monkeypatch.setattr(provider_config, "init_providers", lambda force=False: None)

    try:
        asyncio.run(provider_cmd._provider_fetch(alias))
    finally:
        provider_cmd.PROVIDERS.pop(alias, None)

    out = capsys.readouterr().out
    assert "Sync summary: 4 returned" in out
    assert "1 hidden by type/name" in out
    assert "1 hidden by chat probe" in out
    assert "gpt-5.4-mini -> pytest_fetch_summary:gpt-5.4-mini" in out
    assert saved["name"] == alias
    assert sorted(saved["models_cfg"]) == [
        "pytest_fetch_summary:gpt-5.4-mini",
        "relay-chat",
    ]
    assert saved["replace_models"] is True


def test_provider_activate_command_updates_active_state(monkeypatch, capsys):
    alias = "pytest_active_cmd"
    provider_cmd.PROVIDERS[alias] = {"api_key_env": "PYTEST_ACTIVE_CMD_API_KEY", "active": False}
    seen = {}

    def fake_runtime_set_active(name, active):
        seen["name"] = name
        seen["active"] = active
        provider_cmd.PROVIDERS[name]["active"] = active
        return True, "Provider is now active."

    monkeypatch.setattr(provider_cmd, "runtime_set_active", fake_runtime_set_active)

    try:
        asyncio.run(provider_cmd._handle_provider_cmd("activate", alias, SimpleNamespace()))
    finally:
        provider_cmd.PROVIDERS.pop(alias, None)

    out = capsys.readouterr().out
    assert seen == {"name": alias, "active": True}
    assert "is now active" in out


def test_model_command_rejects_inactive_provider_model(monkeypatch, capsys):
    alias = "inactive-model"
    provider_name = "inactive-provider"
    session = SimpleNamespace(model_alias="ds-v4-flash")
    monkeypatch.setattr(
        provider_config,
        "PROVIDERS",
        {provider_name: {"api_key_env": "INACTIVE_PROVIDER_API_KEY", "active": False}},
    )
    monkeypatch.setattr(provider_cmd, "PROVIDERS", provider_config.PROVIDERS)
    monkeypatch.setattr(
        provider_cmd,
        "MODELS",
        {alias: {"id": alias, "provider": provider_name, "color": "\033[37m"}},
    )

    asyncio.run(
        provider_cmd.cmd_model(
            SimpleNamespace(arg=alias, arg2="", session=session, sink=None)
        )
    )

    out = capsys.readouterr().out
    assert "is not active" in out
    assert session.model_alias == "ds-v4-flash"


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
    monkeypatch.setattr(provider_config, "init_providers", lambda force=False: None)

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
