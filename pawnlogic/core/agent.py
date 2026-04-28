"""Core agent engine."""

from __future__ import annotations

from typing import Any

from pawnlogic.core.message import Message, Role
from pawnlogic.plugins.base import Plugin, PluginResult
from pawnlogic.plugins.registry import PluginRegistry
from pawnlogic.providers.base import LLMProvider, LLMResponse


class Agent:
    """The central reasoning and execution unit of PawnLogic.

    An :class:`Agent` wraps an :class:`~pawnlogic.providers.base.LLMProvider`
    and an optional :class:`~pawnlogic.plugins.registry.PluginRegistry`.  It
    maintains a conversation history and exposes simple :meth:`chat` and
    :meth:`chat_async` methods for sending user messages and receiving model
    replies.

    When a *system prompt* is supplied it is prepended to the history as a
    :attr:`~pawnlogic.core.message.Role.SYSTEM` message on the first call.

    Example::

        from pawnlogic import Agent
        from pawnlogic.providers.openai_provider import OpenAIProvider

        provider = OpenAIProvider(api_key="sk-...")
        agent = Agent(
            provider=provider,
            model="gpt-4o",
            system_prompt="You are a helpful assistant.",
        )
        response = agent.chat("What is the capital of France?")
        print(response.content)
    """

    def __init__(
        self,
        provider: LLMProvider,
        *,
        model: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        plugin_registry: PluginRegistry | None = None,
    ) -> None:
        """Initialise the agent.

        Args:
            provider: The LLM provider used to generate responses.
            model: Model identifier passed to the provider on each call.
            system_prompt: Optional system instruction prepended to history.
            temperature: Sampling temperature forwarded to the provider.
            max_tokens: Optional token limit forwarded to the provider.
            plugin_registry: Registry of available plugins/tools.  When
                ``None``, the agent operates without tool access.
        """
        self._provider = provider
        self._model = model
        self._system_prompt = system_prompt
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._registry = plugin_registry or PluginRegistry()
        self._history: list[Message] = []

        if system_prompt:
            self._history.append(Message.system(system_prompt))

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def provider(self) -> LLMProvider:
        """The underlying LLM provider."""
        return self._provider

    @property
    def model(self) -> str:
        """Model identifier used for completions."""
        return self._model

    @property
    def history(self) -> list[Message]:
        """Ordered conversation history (read-only view)."""
        return list(self._history)

    @property
    def plugin_registry(self) -> PluginRegistry:
        """The plugin registry attached to this agent."""
        return self._registry

    # ------------------------------------------------------------------
    # Conversation
    # ------------------------------------------------------------------

    def chat(self, user_message: str, **kwargs: Any) -> LLMResponse:
        """Send *user_message* to the model and return the response.

        The user message and assistant reply are appended to :attr:`history`.

        Args:
            user_message: The user's input text.
            **kwargs: Extra keyword arguments forwarded to the provider's
                ``complete`` method.

        Returns:
            The provider's :class:`~pawnlogic.providers.base.LLMResponse`.
        """
        self._history.append(Message.user(user_message))
        response = self._provider.complete(
            self._history,
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            **kwargs,
        )
        self._history.append(Message.assistant(response.content))
        return response

    async def chat_async(self, user_message: str, **kwargs: Any) -> LLMResponse:
        """Async variant of :meth:`chat`."""
        self._history.append(Message.user(user_message))
        response = await self._provider.complete_async(
            self._history,
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            **kwargs,
        )
        self._history.append(Message.assistant(response.content))
        return response

    # ------------------------------------------------------------------
    # Tool / plugin execution
    # ------------------------------------------------------------------

    def use_plugin(self, plugin_name: str, **kwargs: Any) -> PluginResult:
        """Invoke a registered plugin by name.

        Args:
            plugin_name: Name of the plugin to run.
            **kwargs: Arguments forwarded to :meth:`~pawnlogic.plugins.base.Plugin.execute`.

        Returns:
            A :class:`~pawnlogic.plugins.base.PluginResult` describing the outcome.

        Raises:
            KeyError: If *plugin_name* is not in the registry.
        """
        plugin: Plugin = self._registry.get(plugin_name)
        result = plugin.execute(**kwargs)
        # Record the tool result in history so the model can see it.
        self._history.append(
            Message.tool(
                content=result.output if result.success else (result.error or ""),
                name=plugin_name,
            )
        )
        return result

    async def use_plugin_async(self, plugin_name: str, **kwargs: Any) -> PluginResult:
        """Async variant of :meth:`use_plugin`."""
        plugin: Plugin = self._registry.get(plugin_name)
        result = await plugin.execute_async(**kwargs)
        self._history.append(
            Message.tool(
                content=result.output if result.success else (result.error or ""),
                name=plugin_name,
            )
        )
        return result

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear conversation history, keeping the system prompt if set."""
        self._history = []
        if self._system_prompt:
            self._history.append(Message.system(self._system_prompt))
