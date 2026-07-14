"""Authoritative metadata and executable-handler registry for tools."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from core.trust import TrustBoundaryKind

Handler = Callable[[dict], object]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Complete metadata required before a tool can be advertised."""

    name: str
    handler: Handler
    schema: dict[str, Any]
    phases: frozenset[str] = frozenset({"*"})
    trust: TrustBoundaryKind = TrustBoundaryKind.LOCAL
    capabilities: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("tool name cannot be empty")
        schema_name = self.schema.get("function", {}).get("name")
        if schema_name != self.name:
            raise ValueError(
                f"tool schema name {schema_name!r} does not match {self.name!r}"
            )
        if not self.phases:
            raise ValueError("tool phases cannot be empty")


class ToolRegistry:
    """Register complete tool specs and expose compatibility snapshots."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._tool_map: dict[str, Handler] = {}
        self._pending_capabilities: dict[str, frozenset[str]] = {}

    def register(
        self,
        spec_or_name: ToolSpec | str,
        handler: Handler | None = None,
        schema: dict[str, Any] | None = None,
        *,
        phases: frozenset[str] | None = None,
        trust: TrustBoundaryKind | None = None,
        capabilities: frozenset[str] | None = None,
    ) -> None:
        """Register a complete spec or use the temporary legacy adapter.

        The legacy form may register a handler before its schema is available,
        but the tool is not advertised until both exist. Schema-only entries
        are ignored, preventing models from seeing an unexecutable tool.
        """
        if isinstance(spec_or_name, ToolSpec):
            if handler is not None or schema is not None:
                raise TypeError("handler/schema cannot accompany ToolSpec")
            self._register_spec(spec_or_name)
            return

        name = spec_or_name
        if not name:
            return
        existing = self._specs.get(name)
        executable = handler or (existing.handler if existing else self._tool_map.get(name))
        if handler is not None:
            self._tool_map[name] = handler
        if capabilities is not None:
            self._pending_capabilities[name] = frozenset(capabilities)

        effective_schema = schema or (existing.schema if existing else None)
        if executable is None or effective_schema is None:
            return

        self._register_spec(
            ToolSpec(
                name=name,
                handler=executable,
                schema=effective_schema,
                phases=frozenset(phases or (existing.phases if existing else {"*"})),
                trust=trust or (existing.trust if existing else TrustBoundaryKind.LOCAL),
                capabilities=frozenset(
                    capabilities
                    if capabilities is not None
                    else (
                        existing.capabilities
                        if existing
                        else self._pending_capabilities.get(name, frozenset())
                    )
                ),
            )
        )

    def _register_spec(self, spec: ToolSpec) -> None:
        self._specs[spec.name] = spec
        self._tool_map[spec.name] = spec.handler
        self._pending_capabilities.pop(spec.name, None)

    def register_many(self, specs: Iterable[ToolSpec]) -> None:
        """Validate a batch before changing the registry."""
        pending = tuple(specs)
        names = [spec.name for spec in pending]
        if len(names) != len(set(names)):
            raise ValueError("duplicate tool names in registration batch")
        for spec in pending:
            if not isinstance(spec, ToolSpec):
                raise TypeError("register_many accepts ToolSpec values only")
        for spec in pending:
            self._register_spec(spec)

    def unregister(self, name: str) -> None:
        self._specs.pop(name, None)
        self._tool_map.pop(name, None)
        self._pending_capabilities.pop(name, None)

    def get_handler(self, name: str) -> Handler | None:
        return self._tool_map.get(name)

    def get_spec(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def get_capabilities(self, name: str) -> frozenset[str]:
        spec = self._specs.get(name)
        if spec is not None:
            return spec.capabilities
        return self._pending_capabilities.get(name, frozenset())

    def has_capability(self, name: str, capability: str) -> bool:
        return capability in self.get_capabilities(name)

    def visible_specs(self, phase: str) -> tuple[ToolSpec, ...]:
        """Return executable specs visible in ``phase`` in registration order."""
        return tuple(
            spec
            for spec in self._specs.values()
            if "*" in spec.phases or phase in spec.phases
        )

    def snapshot_specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._specs.values())

    def live_map(self) -> dict[str, Handler]:
        return self._tool_map

    def snapshot_map(self) -> dict[str, Handler]:
        return dict(self._tool_map)

    def snapshot_schemas(self) -> list[dict[str, Any]]:
        return [spec.schema for spec in self._specs.values()]

    def set_schemas(
        self,
        schemas: list[dict[str, Any]],
        *,
        phase_map: Mapping[str, Iterable[str]] | None = None,
    ) -> None:
        """Compatibility adapter that completes pending handler registrations."""
        phases_by_tool: dict[str, set[str]] = {}
        for phase, names in (phase_map or {}).items():
            for name in names:
                phases_by_tool.setdefault(name, set()).add(phase)
        for schema in schemas:
            name = schema.get("function", {}).get("name")
            handler = self._tool_map.get(name) if name else None
            if name and handler is not None:
                self.register(
                    name,
                    handler,
                    schema,
                    phases=frozenset(phases_by_tool.get(name, {"*"})),
                )


__all__ = ["Handler", "ToolRegistry", "ToolSpec"]
