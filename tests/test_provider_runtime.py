"""Provider runtime tests that do not import prompt_toolkit UI code."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import stat

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
        return model_id != "old-model", "unsupported" if model_id == "old-model" else ""

    monkeypatch.setattr(provider_runtime, "probe_openai_chat_model", fake_probe)

    supported, removed, probe_stats = asyncio.run(
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
    assert probe_stats == {"kept_unknown": 0, "hidden_reasons": {"unsupported": 1}}


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
            "hidden_reasons": {"model_rejected": 1},
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
        "hidden_by_probe": 1,
        "probe_kept_unknown": 0,
        "probe_hidden_reasons": {"model_rejected": 1},
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


def test_probe_openai_chat_model_treats_5xx_as_pass():
    """5xx responses indicate transient server unavailability, not an unsupported
    model.  The probe must treat all 5xx status codes as PASS so that temporarily
    unavailable models are not permanently excluded from the selection list.
    """
    import asyncio
    from types import SimpleNamespace
    from core import provider_runtime

    for status in (500, 502, 503, 504):
        fixed_resp = SimpleNamespace(
            status_code=status,
            text="Service Unavailable",
        )

        class FakeClient:
            async def post(self, *_a, _resp=fixed_resp, **_kw):
                return _resp

        ok, reason = asyncio.run(
            provider_runtime.probe_openai_chat_model(
                FakeClient(), "https://api.example.com/v1/chat/completions", "test-key", "some-model"
            )
        )
        assert ok is True, f"Expected PASS for HTTP {status}, got FAIL with reason={reason!r}"
        assert reason == ""


class _StaticResp:
    def __init__(self, status_code, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


def test_classify_probe_response_alive_paths():
    alive = provider_runtime.classify_probe_response
    assert alive(200, "") == ("alive", "")
    # Parameter complaints prove the model exists; only the payload was wrong.
    assert alive(400, '{"error":"max_tokens must be greater than 2"}') == ("alive", "param_error")
    assert alive(
        400, "Unsupported parameter: 'max_tokens' is not supported with this model"
    ) == ("alive", "param_error")
    # Entitlement failures (e.g. deposit required) are not evidence that the
    # model id is invalid; the real chat call will surface the error later.
    assert alive(403, '{"error":{"message":"Deposit required to unlock premium models."}}') == ("alive", "")
    assert alive(500, "upstream exploded") == ("alive", "")


def test_classify_probe_response_hidden_paths():
    hidden = provider_runtime.classify_probe_response
    assert hidden(404, "") == ("hidden", "http_404")
    assert hidden(
        400, '{"error":{"message":"The model gpt-x does not exist"}}'
    ) == ("hidden", "model_rejected")
    # Marker text must not outrank a 404-independent transient code that also
    # carries it only as part of the model identity rejection.
    assert hidden(422, "model_not_found") == ("hidden", "model_rejected")


def test_classify_probe_response_rate_limited_is_unknown():
    assert provider_runtime.classify_probe_response(429, "") == ("unknown", "rate_limited")


def test_probe_retries_rate_limit_and_passes(monkeypatch):
    monkeypatch.setattr(provider_runtime, "_retry_delay", lambda *a, **k: 0)
    calls = []

    class FlakyClient:
        async def post(self, _url, json=None, headers=None):
            calls.append(json["model"])
            if len(calls) == 1:
                return _StaticResp(429, "")
            return _StaticResp(200, "")

    ok, reason = asyncio.run(
        provider_runtime.probe_openai_chat_model(
            FlakyClient(), "https://api.example.com/v1/chat/completions", "key", "m"
        )
    )
    assert ok is True
    assert reason == ""
    assert len(calls) == 2


def test_probe_keeps_model_alive_when_rate_limit_persists(monkeypatch):
    monkeypatch.setattr(provider_runtime, "_retry_delay", lambda *a, **k: 0)

    class Always429Client:
        async def post(self, _url, json=None, headers=None):
            return _StaticResp(429, "", headers={"Retry-After": "30"})

    ok, reason = asyncio.run(
        provider_runtime.probe_openai_chat_model(
            Always429Client(), "https://api.example.com/v1/chat/completions", "key", "m"
        )
    )
    # Persistent rate limits stay "unknown": the model must remain selectable.
    assert ok is True
    assert reason == "rate_limited"


def test_probe_hides_on_definitive_404_without_retry(monkeypatch):
    calls = []

    class NotFoundClient:
        async def post(self, _url, json=None, headers=None):
            calls.append(1)
            return _StaticResp(404, "")

    ok, reason = asyncio.run(
        provider_runtime.probe_openai_chat_model(
            NotFoundClient(), "https://api.example.com/v1/chat/completions", "key", "m"
        )
    )
    assert ok is False
    assert reason == "http_404"
    assert len(calls) == 1


def test_probe_retries_transport_failure_then_reports_unreachable(monkeypatch):
    monkeypatch.setattr(provider_runtime, "_retry_delay", lambda *a, **k: 0)
    calls = []

    class BrokenClient:
        async def post(self, _url, json=None, headers=None):
            calls.append(1)
            raise ConnectionError("boom")

    ok, reason = asyncio.run(
        provider_runtime.probe_openai_chat_model(
            BrokenClient(), "https://api.example.com/v1/chat/completions", "key", "m"
        )
    )
    assert ok is True
    assert reason == "probe_unreachable"
    assert len(calls) == 2


def test_filter_supported_chat_models_reports_probe_stats(monkeypatch):
    import httpx

    monkeypatch.setattr(provider_runtime, "_retry_delay", lambda *a, **k: 0)

    responses = {
        "ok-model": _StaticResp(200, ""),
        "gone-model": _StaticResp(404, ""),
        "limited-model": _StaticResp(429, ""),
    }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, _url, json=None, headers=None):
            return responses[json["model"]]

    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout: FakeClient())

    supported, removed, probe_stats = asyncio.run(
        provider_runtime.filter_supported_chat_models(
            "https://api.example.com/v1",
            "key",
            [
                ("ok-model", {"id": "ok-model"}),
                ("gone-model", {"id": "gone-model"}),
                ("limited-model", {"id": "limited-model"}),
            ],
        )
    )

    assert [mid for mid, _cfg in supported] == ["ok-model", "limited-model"]
    assert removed == 1
    assert probe_stats == {
        "kept_unknown": 1,
        "hidden_reasons": {"http_404": 1},
    }
