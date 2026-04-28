"""Abstract base class for plugins (external tools)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PluginResult:
    """The result produced by a plugin execution.

    Attributes:
        success: Whether the plugin ran without errors.
        output: The primary text output of the plugin.
        data: Structured data payload (plugin-specific).
        error: Human-readable error description when ``success`` is ``False``.
    """

    success: bool
    output: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class Plugin(ABC):
    """Abstract base class that every PawnLogic plugin must implement.

    A *plugin* represents a discrete capability (tool) that an
    :class:`~pawnlogic.core.agent.Agent` can invoke during a task.

    Minimal example::

        class EchoPlugin(Plugin):
            @property
            def name(self) -> str:
                return "echo"

            @property
            def description(self) -> str:
                return "Echoes the provided text back to the caller."

            @property
            def parameters(self) -> dict:
                return {
                    "text": {"type": "string", "description": "Text to echo."}
                }

            def execute(self, **kwargs) -> PluginResult:
                text = kwargs.get("text", "")
                return PluginResult(success=True, output=text)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique plugin name used as a tool identifier."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what the plugin does."""

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON-Schema-compatible description of accepted parameters.

        Each key is a parameter name and each value is a dict with at
        minimum a ``"type"`` and ``"description"`` entry.
        """

    @abstractmethod
    def execute(self, **kwargs: Any) -> PluginResult:
        """Run the plugin with the supplied keyword arguments.

        Args:
            **kwargs: Plugin-specific parameters as declared in
                :attr:`parameters`.

        Returns:
            A :class:`PluginResult` describing the outcome.
        """

    async def execute_async(self, **kwargs: Any) -> PluginResult:
        """Async variant of :meth:`execute`.

        The default implementation delegates to the synchronous method via
        a thread-pool executor.  Override for native async support.
        """
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self.execute(**kwargs))

    def to_schema(self) -> dict[str, Any]:
        """Return an OpenAI-compatible function/tool schema for this plugin."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                },
            },
        }
