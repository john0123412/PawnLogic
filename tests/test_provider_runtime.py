"""Provider runtime tests that do not import prompt_toolkit UI code."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from core import provider_runtime


def test_provider_runtime_connection_result_formats_http_status():
    response = SimpleNamespace(
        status_code=403,
        text='{"error":{"message":"missing entitlement"}}',
        json=lambda: {"error": {"message": "missing entitlement"}},
    )

    ok, message, ms = provider_runtime.connection_result_from_response(response, 23)

    assert ok is False
    assert ms == 23
    assert "HTTP 403" in message
    assert "missing entitlement" in message


def test_provider_runtime_filter_supported_chat_models_uses_probe(monkeypatch):
    async def fake_probe(_client, _endpoint, _api_key, model_id):
        return model_id != "old-model", "unsupported"

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

    assert [model_id for model_id, _cfg in supported] == ["new-model"]
    assert removed == 1


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
            assert headers == {"Authorization": "Bearer test-key"}
            return FakeResponse()

    async def fake_filter(_base_url, _api_key, candidates, _api_format="openai"):
        return [(mid, cfg) for mid, cfg in candidates if mid != "relay-chat"], 1

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
        "hidden_by_probe": 1,
        "selectable": 1,
    }
    assert candidates[0][1]["desc"] == "Dynamically fetched model; 1 unsupported hidden"


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
