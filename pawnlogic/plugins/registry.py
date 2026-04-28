"""Plugin registry – central catalogue of available plugins."""

from __future__ import annotations

from typing import Iterable, Iterator

from pawnlogic.plugins.base import Plugin


class PluginRegistry:
    """Registry that maps plugin names to :class:`~pawnlogic.plugins.base.Plugin` instances.

    Agents use a registry to discover and invoke available tools.

    Example::

        registry = PluginRegistry()
        registry.register(CalculatorPlugin())
        registry.register(WebSearchPlugin())

        plugin = registry.get("calculator")
        result = plugin.execute(expression="2 + 2")
    """

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def register(self, plugin: Plugin) -> None:
        """Add *plugin* to the registry.

        Args:
            plugin: Plugin instance to register.

        Raises:
            ValueError: If a plugin with the same name is already registered.
        """
        if plugin.name in self._plugins:
            raise ValueError(
                f"A plugin named '{plugin.name}' is already registered. "
                "Use replace() to overwrite it."
            )
        self._plugins[plugin.name] = plugin

    def replace(self, plugin: Plugin) -> None:
        """Register *plugin*, overwriting any previously registered plugin with the same name."""
        self._plugins[plugin.name] = plugin

    def unregister(self, name: str) -> None:
        """Remove the plugin called *name* from the registry.

        Raises:
            KeyError: If no plugin with that name exists.
        """
        if name not in self._plugins:
            raise KeyError(f"No plugin named '{name}' is registered.")
        del self._plugins[name]

    def register_many(self, plugins: Iterable[Plugin]) -> None:
        """Convenience method to register multiple plugins at once."""
        for plugin in plugins:
            self.register(plugin)

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def get(self, name: str) -> Plugin:
        """Return the plugin called *name*.

        Raises:
            KeyError: If no plugin with that name is registered.
        """
        if name not in self._plugins:
            raise KeyError(f"No plugin named '{name}' is registered.")
        return self._plugins[name]

    def __contains__(self, name: str) -> bool:
        return name in self._plugins

    def __iter__(self) -> Iterator[Plugin]:
        return iter(self._plugins.values())

    def __len__(self) -> int:
        return len(self._plugins)

    def names(self) -> list[str]:
        """Return a sorted list of registered plugin names."""
        return sorted(self._plugins.keys())

    def schemas(self) -> list[dict]:
        """Return OpenAI-compatible tool schemas for all registered plugins."""
        return [plugin.to_schema() for plugin in self._plugins.values()]
