"""Per-model ``api_format`` override.

OpenAI serves GPT-6 tool calling only on the Responses API, while the built-in
``openai`` provider speaks Chat Completions. A model may therefore declare its
own ``api_format``; the endpoint, protocol and effort placement must all follow
the model, while every other model on the provider keeps the provider format.
"""

from __future__ import annotations

import json
import sys

import pytest

GPT6 = ("gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna")


def _providers():
    # Resolve the live module: other test files evict ``config`` from
    # sys.modules, so a top-level import can be a stale object.
    import config.providers  # noqa: F401

    return sys.modules["config.providers"]


@pytest.fixture
def restore_dynamic_config():
    from core.state import runtime_config

    cfg = runtime_config()
    previous = dict(cfg)
    yield
    cfg.clear()
    cfg.update(previous)


def _set_effort(level: str) -> None:
    from core.state import update_dynamic_config

    update_dynamic_config({"effort_level": level})


@pytest.mark.parametrize("alias", GPT6)
def test_gpt6_routes_to_the_responses_endpoint(alias):
    cfg = _providers().get_provider_config(alias)
    assert cfg["api_format"] == "responses"
    assert cfg["base_url"] == "https://api.openai.com/v1/responses"
    assert _providers().get_api_format(alias) == "responses"


@pytest.mark.parametrize("alias", ("gpt-5.5", "gpt-5.4-mini", "o3"))
def test_other_openai_models_keep_chat_completions(alias):
    cfg = _providers().get_provider_config(alias)
    assert cfg["api_format"] == "openai"
    assert cfg["base_url"] == "https://api.openai.com/v1/chat/completions"


def test_gpt6_shares_the_openai_provider_and_key():
    models = _providers().MODELS
    for alias in GPT6:
        assert models[alias]["provider"] == "openai"
    assert _providers().get_api_config("gpt-6-astra")[0].endswith("/v1/responses")


def test_unknown_model_format_raises_instead_of_falling_back():
    providers = _providers()
    with pytest.raises(ValueError):
        providers._model_api_format(
            {"api_format": "carrier-pigeon"}, providers.PROVIDERS["openai"]
        )


def test_override_on_a_bare_v1_base_appends_the_model_suffix():
    providers = _providers()
    url, fmt = providers._model_endpoint(
        {"api_format": "responses"}, {"base_url": "https://relay.example/v1"}
    )
    assert (url, fmt) == ("https://relay.example/v1/responses", "responses")


def test_gpt6_effort_ladders_match_the_published_values(restore_dynamic_config):
    from core.api_payloads import resolve_reasoning_effort

    for alias in ("gpt-6-astra", "gpt-6.1-sol"):
        _set_effort("off")
        assert resolve_reasoning_effort(alias) is None, alias
        _set_effort("max")
        assert resolve_reasoning_effort(alias) == "max", alias
    _set_effort("off")
    assert resolve_reasoning_effort("gpt-6-luna") == "none"


_CALLS: list[dict] = []


class _Recorder:
    """Fake connection: records the request and answers 401 without I/O."""



    def __init__(self, url: str):
        self.url = url

    def request(self, method, path, body=None, headers=None):
        _CALLS.append(
            {"url": self.url, "path": path, "body": json.loads(body), "headers": headers}
        )

    def getresponse(self):
        class _Resp:
            status = 401
            reason = "Unauthorized"

            def read(self, *_a):
                return b'{"error":{"message":"test"}}'

            def getheader(self, *_a, **_k):
                return None

        return _Resp()

    def close(self):
        pass


def test_stream_request_sends_a_responses_body_to_the_responses_url(
    monkeypatch, restore_dynamic_config
):
    import core.api_client as api_client

    _CALLS.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(
        api_client,
        "_open_connection",
        lambda url, proxy, timeout: (_Recorder(url), "/v1/responses"),
    )
    _set_effort("high")
    tools = [{
        "type": "function",
        "function": {"name": "noop", "description": "x", "parameters": {"type": "object"}},
    }]
    deltas = list(api_client.stream_request(
        [{"role": "user", "content": "hi"}], "gpt-6-astra", tools_schema=tools
    ))

    assert _CALLS, "no request was issued"
    call = _CALLS[0]
    assert call["url"] == "https://api.openai.com/v1/responses"
    body = call["body"]
    assert body["model"] == "gpt-6-astra"
    assert "input" in body and "messages" not in body
    assert body["reasoning"] == {"effort": "high"}
    assert "reasoning_effort" not in body
    assert body["tools"][0]["type"] == "function"
    assert any("_error" in d for d in deltas)
