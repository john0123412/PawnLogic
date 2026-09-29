"""Provider runtime tests that do not import prompt_toolkit UI code."""

from __future__ import annotations

import asyncio

import pytest
from types import SimpleNamespace
import stat

from core import provider_runtime


def test_provider_runtime_connection_result_formats_http_status():
    response = SimpleNamespace(
        status_code=500,
        text='{"error":{"message":"upstream unavailable"}}',
        json=lambda: {"error": {"message": "upstream unavailable"}},
    )

    ok, message = provider_runtime.connection_result_from_listing(response, 23)

    assert ok is False
    assert "HTTP 500" in message
    assert "upstream unavailable" in message


def test_filter_supported_chat_models_uses_free_metadata_only():
    """Filtering reads the listing metadata; it never calls the provider.

    The candidates here carry `source_item`, the raw `/v1/models` entry. A
    model that declares a non-text output modality is hidden; one that
    declares text, and one that declares nothing at all, are both kept.
    """
    supported, removed, filter_stats = asyncio.run(
        provider_runtime.filter_supported_chat_models(
            "https://api.example.com/v1",
            "test-key",
            [
                ("text-model", {"id": "text-model", "source_item": {
                    "architecture": {"output_modalities": ["text"]}}}),
                ("vision-model", {"id": "vision-model", "source_item": {
                    "architecture": {"output_modalities": ["text", "image"]}}}),
                ("audio-out", {"id": "audio-out", "source_item": {
                    "architecture": {"output_modalities": ["audio"]}}}),
                ("bare", {"id": "bare"}),
            ],
        )
    )

    assert [model_id for model_id, _cfg in supported] == [
        "text-model", "vision-model", "bare",
    ]
    assert removed == 1
    assert filter_stats == {
        "kept_unknown": 0,
        "hidden_reasons": {"non_chat_output": 1},
    }


def test_provider_runtime_fetch_models_builds_candidates_and_stats(monkeypatch):
    class FakeResponse:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {"id": "gpt-5.4-mini"},
                    {"id": "gpt-image-2"},
                    {"id": "relay-chat"},
                ],
                "has_more": False,
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

        async def get(self, _url, headers):
            assert headers == {
                "Authorization": "Bearer test-key",
                "content-type": "application/json",
            }
            return FakeResponse()

    async def fake_filter(_base_url, _api_key, candidates, _api_format="openai"):
        return [(mid, cfg) for mid, cfg in candidates if mid != "relay-chat"], 1, {
            "kept_unknown": 0,
            "hidden_reasons": {"non_chat_output": 1},
        }

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout: FakeClient())
    monkeypatch.setattr(provider_runtime, "filter_supported_chat_models", fake_filter)

    candidates, err, stats = asyncio.run(
        provider_runtime.fetch_models("https://api.example.com/v1", "test-key", "openai")
    )

    assert err == ""
    assert [model_id for model_id, _cfg in candidates] == ["gpt-5.4-mini"]
    assert stats == {
        "returned": 3,
        "hidden_by_name": 1,
        "hidden_by_metadata": 1,
        "hidden_reasons": {"non_chat_output": 1},
        "selectable": 1,
    }
    assert candidates[0][1]["desc"] == "Dynamically fetched model; 1 unsupported hidden"


def test_provider_runtime_fetch_filters_non_chat_models_before_probe(monkeypatch):
    class FakeResponse:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {"id": "text-embedding-3-large"},
                    {"id": "gpt-image-2"},
                    {"id": "gpt-3.5-turbo-instruct"},
                    {"id": "relay-chat"},
                    {"id": "relay-pro"},
                ],
                "has_more": False,
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

        async def get(self, _url, headers):
            assert headers == {
                "Authorization": "Bearer test-key",
                "content-type": "application/json",
            }
            return FakeResponse()

    seen_candidate_ids: list[str] = []

    async def fake_filter(_base_url, _api_key, candidates, _api_format="openai"):
        seen_candidate_ids.extend(mid for mid, _cfg in candidates)
        return candidates, 0, {"kept_unknown": 0, "hidden_reasons": {}}

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout: FakeClient())
    monkeypatch.setattr(provider_runtime, "filter_supported_chat_models", fake_filter)

    candidates, err, stats = asyncio.run(
        provider_runtime.fetch_models("https://api.example.com/v1", "test-key", "openai")
    )

    assert err == ""
    assert seen_candidate_ids == ["relay-chat", "relay-pro"]
    assert [model_id for model_id, _cfg in candidates] == seen_candidate_ids
    assert stats["hidden_by_name"] == 3


def test_provider_runtime_set_active_delegates_to_provider_config(monkeypatch):
    monkeypatch.setattr(provider_runtime, "PROVIDERS", {"relay": {"active": False}})
    seen = {}

    def fake_set_provider_active(name, active):
        seen["name"] = name
        seen["active"] = active
        return True

    monkeypatch.setattr(provider_runtime.provider_config, "set_provider_active", fake_set_provider_active)
    monkeypatch.setattr(provider_runtime, "init_providers", lambda force=False: None)

    ok, message = provider_runtime.set_active("relay", True)

    assert ok is True
    assert message == "Provider is now active."
    assert seen == {"name": "relay", "active": True}


def test_provider_runtime_refuses_to_deactivate_deepseek(monkeypatch):
    monkeypatch.setattr(provider_runtime, "PROVIDERS", {"deepseek": {"active": True}})

    def fail_set_provider_active(_name, _active):
        raise AssertionError("DeepSeek deactivate should be blocked before persistence")

    monkeypatch.setattr(
        provider_runtime.provider_config,
        "set_provider_active",
        fail_set_provider_active,
    )

    ok, message = provider_runtime.set_active("deepseek", False)

    assert ok is False
    assert message == "DeepSeek is always active."


def test_provider_runtime_save_key_writes_env_atomically_with_private_mode(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    monkeypatch.setattr(provider_runtime, "PAWNLOGIC_DIR", tmp_path)
    monkeypatch.setattr(provider_runtime, "ENV_PATH", env_path)
    monkeypatch.delenv("RELAY_API_KEY", raising=False)

    provider_runtime.save_key("RELAY_API_KEY", "secret-value")

    assert env_path.read_text(encoding="utf-8") == "RELAY_API_KEY=secret-value\n"
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600


def test_provider_runtime_record_sync_time_logs_and_preserves_malformed_json(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "custom_providers.json"
    path.write_text("{bad json", encoding="utf-8")
    logged: list[str] = []

    class FakeLogger:
        def warning(self, msg, *args):
            logged.append(msg.format(*args))

    monkeypatch.setattr(provider_runtime, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(provider_runtime, "logger", FakeLogger())

    provider_runtime.record_sync_time("relay")

    assert path.read_text(encoding="utf-8") == "{bad json"
    assert "Failed to update provider sync time" in logged[0]


def test_save_provider_with_rollback_rolls_back_on_persistence_failure(monkeypatch):
    """save_provider_with_rollback must revert live registry if disk write fails."""
    from config.providers import PROVIDERS

    original_providers = dict(PROVIDERS)

    def fail_save(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(provider_runtime.provider_config, "save_custom_provider", fail_save)

    ok, err = provider_runtime.save_provider_with_rollback(
        "relay",
        {"base_url": "https://x.com/v1", "api_key_env": "K", "api_format": "openai"},
        {},
    )

    assert ok is False
    assert "disk full" in err
    # Live registry must not have been modified.
    assert original_providers == PROVIDERS


def test_fetch_models_rejects_non_list_data_field(monkeypatch):
    """fetch_models must reject responses where 'data' is not a list."""
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def get(self, _url, headers=None):
            class Resp:
                status_code = 200
                text = ""

                def raise_for_status(self_):
                    return None

                def json(self_):
                    return {"data": "not-a-list"}

            return Resp()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())

    candidates, err, _stats = asyncio.run(
        provider_runtime.fetch_models("https://api.example.com/v1", "key", "openai")
    )

    assert candidates == []
    assert "invalid" in err.lower() or "data" in err.lower()


def test_fetch_models_skips_entries_with_missing_id(monkeypatch):
    """fetch_models must skip model entries that have no 'id' field."""
    class FakeResponse:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {"id": "gpt-5.4-mini"},
                    {"no_id_field": True},
                    {"id": ""},
                    {"id": "relay-chat"},
                ],
                "has_more": False,
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

        async def get(self, _url, headers=None):
            return FakeResponse()

    async def fake_filter(_base_url, _api_key, candidates, _api_format="openai"):
        return candidates, 0, {"kept_unknown": 0, "hidden_reasons": {}}

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout: FakeClient())
    monkeypatch.setattr(provider_runtime, "filter_supported_chat_models", fake_filter)

    candidates, err, _stats = asyncio.run(
        provider_runtime.fetch_models("https://api.example.com/v1", "test-key", "openai")
    )

    assert err == ""
    model_ids = [mid for mid, _cfg in candidates]
    assert "gpt-5.4-mini" in model_ids
    assert "relay-chat" in model_ids
    # Entries with missing or empty id must be skipped.
    assert len(model_ids) == 2


def test_filter_supported_chat_models_counts_hidden_reasons():
    """Every non-text output modality is counted by its own reason."""
    supported, removed, filter_stats = asyncio.run(
        provider_runtime.filter_supported_chat_models(
            "https://api.example.com/v1",
            "key",
            [
                ("a", {"id": "a", "source_item": {
                    "architecture": {"output_modalities": ["audio"]}}}),
                ("b", {"id": "b", "source_item": {
                    "architecture": {"output_modalities": ["audio"]}}}),
                ("c", {"id": "c", "source_item": {
                    "architecture": {"output_modalities": ["embedding"]}}}),
            ],
        )
    )

    assert supported == []
    assert removed == 3
    assert filter_stats == {
        "kept_unknown": 0,
        "hidden_reasons": {"non_chat_output": 3},
    }


def test_update_custom_provider_rewrites_endpoint_and_preserves_identity(monkeypatch):
    """Editing an endpoint must not disturb the name, key env var, or models.

    Saving with an empty models map and replace_models=False is what keeps the
    provider's loaded models on disk; a name change would require migrating
    every model entry plus the env var, which is deliberately out of scope.
    """
    existing = {
        "base_url": "https://old.example.com/v1",
        "api_key_env": "MYRELAY_API_KEY",
        "label": "Custom (myrelay)",
        "api_format": "openai",
        "active": True,
    }
    monkeypatch.setitem(provider_runtime.PROVIDERS, "myrelay", dict(existing))
    monkeypatch.setattr(provider_runtime.provider_config, "save_custom_provider",
                        lambda *a, **k: None)
    registered = []
    monkeypatch.setattr(provider_runtime.provider_config, "register_provider",
                        lambda name, cfg: registered.append((name, cfg)))
    monkeypatch.setattr(provider_runtime, "init_providers", lambda force=False: None)

    ok, err = provider_runtime.update_custom_provider(
        "myrelay", base_url="https://new.example.com/v1", api_format="anthropic")

    assert (ok, err) == (True, "")
    assert registered[0][0] == "myrelay"
    saved = registered[0][1]
    assert saved["base_url"] == "https://new.example.com/v1"
    assert saved["api_format"] == "anthropic"
    assert saved["api_key_env"] == "MYRELAY_API_KEY"
    assert saved["label"] == "Custom (myrelay)"
    assert saved["active"] is True


def test_update_custom_provider_passes_empty_models_without_replacing(monkeypatch):
    """The persistence call must not wipe the provider's loaded models."""
    monkeypatch.setitem(provider_runtime.PROVIDERS, "myrelay", {"api_key_env": "K"})
    seen = {}

    def fake_save(name, cfg, models_cfg, *, replace_models=False):
        seen["models_cfg"] = models_cfg
        seen["replace_models"] = replace_models

    monkeypatch.setattr(provider_runtime.provider_config, "save_custom_provider", fake_save)
    monkeypatch.setattr(provider_runtime.provider_config, "register_provider",
                        lambda name, cfg: None)
    monkeypatch.setattr(provider_runtime, "init_providers", lambda force=False: None)

    ok, _err = provider_runtime.update_custom_provider(
        "myrelay", base_url="https://x.example.com/v1", api_format="openai")

    assert ok is True
    assert seen["models_cfg"] == {}
    assert seen["replace_models"] is False


def test_update_custom_provider_rejects_builtin_and_missing(monkeypatch):
    monkeypatch.setitem(provider_runtime.PROVIDERS, "deepseek", {"api_key_env": "K"})

    ok, err = provider_runtime.update_custom_provider(
        "deepseek", base_url="https://x.example.com/v1", api_format="openai")
    assert ok is False and "built-in" in err

    ok, err = provider_runtime.update_custom_provider(
        "ghost", base_url="https://x.example.com/v1", api_format="openai")
    assert ok is False and "not found" in err


def test_update_custom_provider_reports_persistence_failure(monkeypatch):
    monkeypatch.setitem(provider_runtime.PROVIDERS, "myrelay", {"api_key_env": "K"})

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(provider_runtime.provider_config, "save_custom_provider", boom)
    monkeypatch.setattr(provider_runtime.provider_config, "register_provider",
                        lambda name, cfg: None)
    monkeypatch.setattr(provider_runtime, "init_providers", lambda force=False: None)

    ok, err = provider_runtime.update_custom_provider(
        "myrelay", base_url="https://x.example.com/v1", api_format="openai")

    assert ok is False
    assert "disk full" in err


def test_fetch_models_never_issues_an_inference_request():
    """`/provider fetch` must not spend money.

    Every candidate used to be probed with a real
    `POST /chat/completions {"model": id, "max_tokens": 8, ...}`. openrouter
    returns hundreds of models, so one fetch produced hundreds of billable
    inferences and took minutes. Filtering now reads only the free metadata
    that `/v1/models` already returned, so no chat request is ever made.
    """
    import httpx

    posted: list[str] = []

    class FakeResponse:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {
                        "id": "vendor/chat-model",
                        "architecture": {"output_modalities": ["text"]},
                        "pricing": {"prompt": "0.000002", "completion": "0.00001"},
                        "top_provider": {"context_length": 128000},
                    },
                    {
                        # Named so that no name-based keyword filter can catch
                        # it: only the free modality metadata reveals that it
                        # cannot emit text.
                        "id": "vendor/omni-router",
                        "architecture": {"output_modalities": ["audio"]},
                        "pricing": {"prompt": "0.0000001", "completion": "0"},
                    },
                    {"id": "vendor/plain-llm"},
                ],
                "has_more": False,
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

        async def get(self, _url, headers):
            return FakeResponse()

        async def post(self, *args, **kwargs):  # pragma: no cover - must not run
            posted.append(str(args))
            raise AssertionError("fetch_models must not POST to a chat endpoint")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(httpx, "AsyncClient", lambda *a, **kw: FakeClient())
    try:
        candidates, err, stats = asyncio.run(
            provider_runtime.fetch_models(
                "https://api.example.com/v1", "test-key", "openai"
            )
        )
    finally:
        monkey.undo()

    assert err == ""
    assert posted == []
    ids = [model_id for model_id, _cfg in candidates]
    # The non-chat entry is hidden from free metadata alone; the entry with
    # no metadata is kept, because absence of evidence is not evidence of
    # absence and it may simply be a provider that omits the fields.
    assert "vendor/omni-router" not in ids
    assert "vendor/chat-model" in ids
    assert "vendor/plain-llm" in ids
    assert stats["hidden_by_metadata"] == 1
    assert stats["hidden_reasons"] == {"non_chat_output": 1}


def test_test_connection_never_sends_an_inference():
    """Test Connection must be free too.

    It used to POST `max_tokens=1` to the chat endpoint, which is a real
    billable inference. It now checks the same things a user actually cares
    about — is the configured base URL reachable, and does the provider
    accept this API key — against the free `/v1/models` listing derived from
    that base URL. No chat request is made.
    """
    import httpx

    posts: list[str] = []
    requested: list[str] = []

    class FakeResponse:
        status_code = 200
        text = '{"data": []}'

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": []}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url, headers=None):
            requested.append(str(url))
            return FakeResponse()

        async def post(self, *a, **k):  # pragma: no cover - must not run
            posts.append(str(a))
            raise AssertionError("Test Connection must not POST")

    mp = pytest.MonkeyPatch()
    mp.setattr(httpx, "AsyncClient", lambda *a, **kw: FakeClient())
    try:
        ok, msg, _ms = asyncio.run(
            provider_runtime.test_connection(
                "https://api.example.com/v1", "test-key", "openai", "some-model"
            )
        )
    finally:
        mp.undo()

    assert ok is True
    assert posts == []
    # The free listing under the configured root, not the chat endpoint.
    assert requested and all("/v1/models" in u for u in requested)
    # The user-visible result must not imply the model was exercised.
    assert "no inference sent" in msg


def test_test_connection_reports_a_rejected_key_without_inferring():
    """A bad key must still fail the check, from the free listing's status."""
    import httpx

    class FakeResponse:
        status_code = 401
        text = '{"error": {"message": "Invalid API key"}}'

        def raise_for_status(self):
            return None

        def json(self):
            return {"error": {"message": "Invalid API key"}}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, _url, headers=None):
            return FakeResponse()

        async def post(self, *a, **k):  # pragma: no cover - must not run
            raise AssertionError("Test Connection must not POST")

    mp = pytest.MonkeyPatch()
    mp.setattr(httpx, "AsyncClient", lambda *a, **kw: FakeClient())
    try:
        ok, msg, _ms = asyncio.run(
            provider_runtime.test_connection(
                "https://api.example.com/v1", "test-key", "openai", "some-model"
            )
        )
    finally:
        mp.undo()

    assert ok is False
    # A rejected key must be named as such, not reported as a bare status.
    assert "/setkey" in msg
