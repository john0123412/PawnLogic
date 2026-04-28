"""Anthropic (Claude) LLM provider."""

from __future__ import annotations

from typing import Any

from pawnlogic.core.message import Message, Role
from pawnlogic.providers.base import LLMProvider, LLMResponse

_DEFAULT_MAX_TOKENS = 1024


class AnthropicProvider(LLMProvider):
    """LLM provider backed by the Anthropic API (Claude models).

    Requires the ``anthropic`` extra to be installed::

        pip install "pawnlogic[anthropic]"

    Example::

        provider = AnthropicProvider(api_key="sk-ant-...")
        response = provider.complete(
            [Message.user("Explain quantum entanglement.")],
            model="claude-3-5-sonnet-20241022",
        )
        print(response.content)
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        **client_kwargs: Any,
    ) -> None:
        """Initialise the provider.

        Args:
            api_key: Anthropic API key.  Falls back to the
                ``ANTHROPIC_API_KEY`` environment variable when ``None``.
            base_url: Override the default API base URL.
            **client_kwargs: Additional keyword arguments forwarded to the
                ``anthropic.Anthropic`` constructor.
        """
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "The 'anthropic' package is required for AnthropicProvider. "
                "Install it with: pip install 'pawnlogic[anthropic]'"
            ) from exc

        init_kwargs: dict[str, Any] = {**client_kwargs}
        if api_key is not None:
            init_kwargs["api_key"] = api_key
        if base_url is not None:
            init_kwargs["base_url"] = base_url

        self._client = anthropic.Anthropic(**init_kwargs)
        # Store init params for consistent async-client creation.
        self._init_kwargs = init_kwargs

    @property
    def name(self) -> str:
        return "anthropic"

    @staticmethod
    def _split_system(messages: list[Message]) -> tuple[str | None, list[Message]]:
        """Extract an optional leading system message from the conversation."""
        system: str | None = None
        rest: list[Message] = []
        for msg in messages:
            if msg.role == Role.SYSTEM and system is None and not rest:
                system = msg.content
            else:
                rest.append(msg)
        return system, rest

    def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        system, non_system = self._split_system(messages)
        payload = [msg.to_dict() for msg in non_system]
        effective_max_tokens = max_tokens if max_tokens is not None else _DEFAULT_MAX_TOKENS

        call_kwargs: dict[str, Any] = {
            "model": model,
            "messages": payload,
            "temperature": temperature,
            "max_tokens": effective_max_tokens,
            **kwargs,
        }
        if system is not None:
            call_kwargs["system"] = system

        raw = self._client.messages.create(**call_kwargs)
        content = raw.content[0].text if raw.content else ""
        usage: dict[str, int] = {
            "input_tokens": raw.usage.input_tokens,
            "output_tokens": raw.usage.output_tokens,
        }
        return LLMResponse(content=content, model=raw.model, usage=usage, raw=raw)

    async def complete_async(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "The 'anthropic' package is required for AnthropicProvider. "
                "Install it with: pip install 'pawnlogic[anthropic]'"
            ) from exc

        async_client = anthropic.AsyncAnthropic(**self._init_kwargs)
        system, non_system = self._split_system(messages)
        payload = [msg.to_dict() for msg in non_system]
        effective_max_tokens = max_tokens if max_tokens is not None else _DEFAULT_MAX_TOKENS

        call_kwargs: dict[str, Any] = {
            "model": model,
            "messages": payload,
            "temperature": temperature,
            "max_tokens": effective_max_tokens,
            **kwargs,
        }
        if system is not None:
            call_kwargs["system"] = system

        raw = await async_client.messages.create(**call_kwargs)
        content = raw.content[0].text if raw.content else ""
        usage: dict[str, int] = {
            "input_tokens": raw.usage.input_tokens,
            "output_tokens": raw.usage.output_tokens,
        }
        return LLMResponse(content=content, model=raw.model, usage=usage, raw=raw)
