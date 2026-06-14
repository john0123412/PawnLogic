"""Tool registry: the single registration interface for executable tools.

Holds the mutable name→handler map and name→schema map, and exposes snapshot
reads for session and tool consumers. Built-in tools, optional toolkits, and
external MCP tools all register through this one interface; the legacy
``TOOL_MAP`` / ``TOOLS_SCHEMA`` module globals in ``core.session`` are kept only
as compatibility mirrors of this registry.
"""

from __future__ import annotations

from collections.abc import Callable

Handler = Callable[[dict], object]


class ToolRegistry:
    """Mutable tool registry with snapshot reads for session/tool consumers."""

    def __init__(self) -> None:
        self._tool_map: dict[str, Handler] = {}
        self._schemas: dict[str, dict] = {}

    def register(self, name: str, handler, schema: dict | None = None) -> None:
        """Register or update a tool.

        A falsy name is ignored. A ``None`` handler registers schema-only (the
        tool is advertised but not executable); a ``None`` schema leaves any
        existing schema untouched.
        """
        if not name:
            return
        if handler is not None:
            self._tool_map[name] = handler
        if schema is not None:
            self._schemas[name] = schema

    def unregister(self, name: str) -> None:
        """Remove a tool's handler and schema, if present."""
        self._tool_map.pop(name, None)
        self._schemas.pop(name, None)

    def get_handler(self, name: str):
        """Return the executable handler for ``name`` or ``None``."""
        return self._tool_map.get(name)

    def live_map(self) -> dict[str, Handler]:
        """Return the live tool map by reference (mutations are visible).

        Used to back the legacy ``TOOL_MAP`` mirror so dynamically registered
        tools appear without an explicit refresh.
        """
        return self._tool_map

    def snapshot_map(self) -> dict[str, Handler]:
        """Return a shallow copy of the name→handler map."""
        return dict(self._tool_map)

    def snapshot_schemas(self) -> list[dict]:
        """Return the registered schemas as a fresh list."""
        return [self._schemas[name] for name in self._schemas]

    def set_schemas(self, schemas: list[dict]) -> None:
        """Bulk-register schemas keyed by their function name."""
        for schema in schemas:
            name = schema.get("function", {}).get("name")
            if name:
                self._schemas[name] = schema


__all__ = ["Handler", "ToolRegistry"]
