"""Tests for LLMProvider base class and mock providers."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from pawnlogic.core.message import Message
from pawnlogic.providers.base import LLMProvider, LLMResponse


class EchoProvider(LLMProvider):
    """Minimal concrete provider that echoes back the last user message."""

    @property
    def name(self) -> str:
        return "echo"

    def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        last_user = next(
            (m for m in reversed(messages) if m.role.value == "user"), None
        )
        content = last_user.content if last_user else ""
        return LLMResponse(content=f"Echo: {content}", model=model)


def test_provider_name():
    provider = EchoProvider()
    assert provider.name == "echo"


def test_provider_complete_returns_response():
    provider = EchoProvider()
    msgs = [Message.user("Hello")]
    response = provider.complete(msgs, model="echo-v1")
    assert isinstance(response, LLMResponse)
    assert response.content == "Echo: Hello"
    assert response.model == "echo-v1"


def test_provider_complete_empty_usage_by_default():
    provider = EchoProvider()
    response = provider.complete([Message.user("Hi")], model="m")
    assert response.usage == {}


def test_provider_async_complete_uses_sync_fallback():
    provider = EchoProvider()
    msgs = [Message.user("async hello")]
    response = asyncio.run(provider.complete_async(msgs, model="echo-v1"))
    assert response.content == "Echo: async hello"


def test_llm_response_dataclass():
    r = LLMResponse(content="hi", model="x", usage={"total_tokens": 5})
    assert r.content == "hi"
    assert r.model == "x"
    assert r.usage["total_tokens"] == 5
    assert r.raw is None
