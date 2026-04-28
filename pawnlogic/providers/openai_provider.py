"""OpenAI LLM provider."""

from __future__ import annotations

from typing import Any

from pawnlogic.core.message import Message, Role
from pawnlogic.providers.base import LLMProvider, LLMResponse


class OpenAIProvider(LLMProvider):
    """LLM provider backed by the OpenAI API.

    Requires the ``openai`` extra to be installed::

        pip install "pawnlogic[openai]"

    Example::

        provider = OpenAIProvider(api_key="sk-...")
        response = provider.complete(
            [Message.user("What is 2+2?")],
            model="gpt-4o",
        )
        print(response.content)
    """

    def __init__(
        self,
        api_key: str | None = None,
        organization: str | None = None,
        base_url: str | None = None,
        **client_kwargs: Any,
    ) -> None:
        """Initialise the provider.

        Args:
            api_key: OpenAI API key.  Falls back to the ``OPENAI_API_KEY``
                environment variable when ``None``.
            organization: Optional OpenAI organization identifier.
            base_url: Override the default API base URL (useful for proxies
                or Azure OpenAI deployments).
            **client_kwargs: Additional keyword arguments forwarded to the
                ``openai.OpenAI`` constructor.
        """
        try:
            import openai
        except ImportError as exc:
            raise ImportError(
                "The 'openai' package is required for OpenAIProvider. "
                "Install it with: pip install 'pawnlogic[openai]'"
            ) from exc

        self._client = openai.OpenAI(
            api_key=api_key,
            organization=organization,
            base_url=base_url,
            **client_kwargs,
        )
        # Store init params for consistent async-client creation.
        self._init_kwargs: dict[str, Any] = {
            "api_key": api_key,
            "organization": organization,
            "base_url": base_url,
            **client_kwargs,
        }

    @property
    def name(self) -> str:
        return "openai"

    def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        payload = [msg.to_dict() for msg in messages]
        call_kwargs: dict[str, Any] = {
            "model": model,
            "messages": payload,
            "temperature": temperature,
            **kwargs,
        }
        if max_tokens is not None:
            call_kwargs["max_tokens"] = max_tokens

        raw = self._client.chat.completions.create(**call_kwargs)
        content = raw.choices[0].message.content or ""
        usage: dict[str, int] = {}
        if raw.usage:
            usage = {
                "prompt_tokens": raw.usage.prompt_tokens,
                "completion_tokens": raw.usage.completion_tokens,
                "total_tokens": raw.usage.total_tokens,
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
            import openai
        except ImportError as exc:
            raise ImportError(
                "The 'openai' package is required for OpenAIProvider. "
                "Install it with: pip install 'pawnlogic[openai]'"
            ) from exc

        async_client = openai.AsyncOpenAI(**self._init_kwargs)
        payload = [msg.to_dict() for msg in messages]
        call_kwargs: dict[str, Any] = {
            "model": model,
            "messages": payload,
            "temperature": temperature,
            **kwargs,
        }
        if max_tokens is not None:
            call_kwargs["max_tokens"] = max_tokens

        raw = await async_client.chat.completions.create(**call_kwargs)
        content = raw.choices[0].message.content or ""
        usage: dict[str, int] = {}
        if raw.usage:
            usage = {
                "prompt_tokens": raw.usage.prompt_tokens,
                "completion_tokens": raw.usage.completion_tokens,
                "total_tokens": raw.usage.total_tokens,
            }
        return LLMResponse(content=content, model=raw.model, usage=usage, raw=raw)
