"""Orchestrator – manages a pool of agents for complex task decomposition."""

from __future__ import annotations

from typing import Any

from pawnlogic.core.agent import Agent
from pawnlogic.providers.base import LLMResponse


class Orchestrator:
    """Manages a named pool of :class:`~pawnlogic.core.agent.Agent` instances.

    The :class:`Orchestrator` acts as a coordinator: it holds references to
    multiple specialised agents and can route messages to the appropriate one.

    Example::

        orchestrator = Orchestrator()
        orchestrator.register("planner", planner_agent)
        orchestrator.register("executor", executor_agent)

        response = orchestrator.chat("planner", "Break down the task: ...")
    """

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    # ------------------------------------------------------------------
    # Agent management
    # ------------------------------------------------------------------

    def register(self, name: str, agent: Agent) -> None:
        """Add *agent* under *name*.

        Args:
            name: Unique name for the agent within this orchestrator.
            agent: The agent instance to register.

        Raises:
            ValueError: If an agent with *name* is already registered.
        """
        if name in self._agents:
            raise ValueError(
                f"An agent named '{name}' is already registered. "
                "Use replace() to overwrite it."
            )
        self._agents[name] = agent

    def replace(self, name: str, agent: Agent) -> None:
        """Register *agent* under *name*, overwriting any existing entry."""
        self._agents[name] = agent

    def unregister(self, name: str) -> None:
        """Remove the agent called *name*.

        Raises:
            KeyError: If no agent with that name exists.
        """
        if name not in self._agents:
            raise KeyError(f"No agent named '{name}' is registered.")
        del self._agents[name]

    def get(self, name: str) -> Agent:
        """Return the agent called *name*.

        Raises:
            KeyError: If no agent with that name is registered.
        """
        if name not in self._agents:
            raise KeyError(f"No agent named '{name}' is registered.")
        return self._agents[name]

    def __contains__(self, name: str) -> bool:
        return name in self._agents

    def __len__(self) -> int:
        return len(self._agents)

    def names(self) -> list[str]:
        """Return a sorted list of registered agent names."""
        return sorted(self._agents.keys())

    # ------------------------------------------------------------------
    # Routing helpers
    # ------------------------------------------------------------------

    def chat(self, agent_name: str, user_message: str, **kwargs: Any) -> LLMResponse:
        """Route *user_message* to the agent called *agent_name*.

        Args:
            agent_name: Name of the target agent.
            user_message: The user's input text.
            **kwargs: Forwarded to :meth:`~pawnlogic.core.agent.Agent.chat`.

        Returns:
            The agent's :class:`~pawnlogic.providers.base.LLMResponse`.
        """
        return self.get(agent_name).chat(user_message, **kwargs)

    async def chat_async(
        self, agent_name: str, user_message: str, **kwargs: Any
    ) -> LLMResponse:
        """Async variant of :meth:`chat`."""
        return await self.get(agent_name).chat_async(user_message, **kwargs)

    def broadcast(self, user_message: str, **kwargs: Any) -> dict[str, LLMResponse]:
        """Send *user_message* to **every** registered agent.

        Returns:
            A mapping of agent name → :class:`~pawnlogic.providers.base.LLMResponse`.
        """
        return {
            name: agent.chat(user_message, **kwargs)
            for name, agent in self._agents.items()
        }

    async def broadcast_async(
        self, user_message: str, **kwargs: Any
    ) -> dict[str, LLMResponse]:
        """Async variant of :meth:`broadcast`."""
        import asyncio

        tasks = {
            name: agent.chat_async(user_message, **kwargs)
            for name, agent in self._agents.items()
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        return dict(zip(tasks.keys(), results))
