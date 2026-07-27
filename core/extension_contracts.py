"""Stable contracts for the optional PawnLogic Extension Runtime.

The contracts in this module deliberately contain no discovery or startup
logic.  They are the small, frozen value/protocol surface shared by the host
and independently distributed Extensions.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, TypeAlias

from core.tool_registry import ToolSpec


class ExtensionState(str, Enum):
    """Lifecycle states exposed by the Extension Runtime."""

    DISCOVERED = "discovered"
    VALIDATING = "validating"
    STARTING = "starting"
    ENABLED = "enabled"
    STOPPING = "stopping"
    DISABLED = "disabled"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


# ``ExtensionStatusState`` is a descriptive alias for callers that prefer a
# status-specific name; the enum remains a single stable value set.
ExtensionStatusState = ExtensionState


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _is_json_value(value: object) -> bool:
    if value is None or isinstance(value, (str, bool, int, float)):
        return True
    if isinstance(value, Mapping):
        return all(isinstance(key, str) and _is_json_value(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return all(_is_json_value(item) for item in value)
    return False


@dataclass(frozen=True, slots=True)
class ExtensionDescriptor:
    """Non-importing discovery metadata for an installed Extension."""

    name: str
    distribution: str
    version: str
    entry_point: str
    enabled: bool
    compatible: bool | None
    error: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.name, "name")
        _require_text(self.distribution, "distribution")
        _require_text(self.version, "version")
        _require_text(self.entry_point, "entry_point")
        if self.error is not None and not isinstance(self.error, str):
            raise TypeError("error must be a string or None")


@dataclass(frozen=True, slots=True)
class ExtensionManifest:
    """Enablement-time identity, compatibility, capability, and config data."""

    name: str
    version: str
    core_version_spec: str
    api_version: int
    description: str = ""
    capabilities: frozenset[str] = frozenset()
    config_schema: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.name, "name")
        _require_text(self.version, "version")
        _require_text(self.core_version_spec, "core_version_spec")
        if not isinstance(self.api_version, int) or isinstance(self.api_version, bool):
            raise TypeError("api_version must be an integer")
        if not isinstance(self.description, str):
            raise TypeError("description must be a string")
        capabilities = frozenset(self.capabilities)
        if any(not isinstance(item, str) or not item.strip() for item in capabilities):
            raise ValueError("capabilities must contain non-empty strings")
        if not isinstance(self.config_schema, Mapping) or not _is_json_value(self.config_schema):
            raise ValueError("config_schema must contain JSON-compatible values")
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "config_schema", dict(self.config_schema))


@dataclass(frozen=True, slots=True)
class CommandContribution:
    """A command contribution held by the manager until startup integration."""

    name: str
    handler: Callable[..., object] | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.name, "command name")
        if not callable(self.handler) and self.handler is not None:
            raise TypeError("command handler must be callable or None")
        if not isinstance(self.metadata, Mapping) or not _is_json_value(self.metadata):
            raise ValueError("command metadata must contain JSON-compatible values")
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class PhaseContribution:
    """A named phase contribution held by the manager."""

    name: str
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.name, "phase name")
        if not isinstance(self.metadata, Mapping) or not _is_json_value(self.metadata):
            raise ValueError("phase metadata must contain JSON-compatible values")
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class PromptContribution:
    """A prompt fragment contribution held by the manager."""

    name: str
    text: str
    priority: int = 0

    def __post_init__(self) -> None:
        _require_text(self.name, "prompt name")
        if not isinstance(self.text, str):
            raise TypeError("prompt text must be a string")
        if not isinstance(self.priority, int) or isinstance(self.priority, bool):
            raise TypeError("prompt priority must be an integer")


# Explicit aliases make the ownership in the public contract apparent while
# keeping concise names pleasant for Extension authors.
ExtensionCommandContribution = CommandContribution
ExtensionPhaseContribution = PhaseContribution
ExtensionPromptContribution = PromptContribution


@dataclass(frozen=True, slots=True)
class ExtensionContributions:
    """All contributions returned by one Extension start transaction."""

    tools: tuple[ToolSpec, ...] = ()
    commands: tuple[CommandContribution, ...] = ()
    phases: tuple[PhaseContribution, ...] = ()
    prompts: tuple[PromptContribution, ...] = ()

    def __post_init__(self) -> None:
        tools = tuple(self.tools)
        commands = tuple(self.commands)
        phases = tuple(self.phases)
        prompts = tuple(self.prompts)
        if any(not isinstance(item, ToolSpec) for item in tools):
            raise TypeError("tools must contain ToolSpec values")
        if any(not isinstance(item, CommandContribution) for item in commands):
            raise TypeError("commands must contain CommandContribution values")
        if any(not isinstance(item, PhaseContribution) for item in phases):
            raise TypeError("phases must contain PhaseContribution values")
        if any(not isinstance(item, PromptContribution) for item in prompts):
            raise TypeError("prompts must contain PromptContribution values")
        object.__setattr__(self, "tools", tools)
        object.__setattr__(self, "commands", commands)
        object.__setattr__(self, "phases", phases)
        object.__setattr__(self, "prompts", prompts)


@dataclass(frozen=True, slots=True)
class ExtensionStatus:
    """Redacted lifecycle snapshot returned by manager operations."""

    name: str
    state: ExtensionState
    enabled: bool
    compatible: bool | None = None
    error: str | None = None
    manifest: ExtensionManifest | None = None
    persisted_enabled: bool = False

    @property
    def status(self) -> ExtensionState:
        """Compatibility property for callers using ``status.status``."""
        return self.state


class ExtensionToolRegistrar(Protocol):
    """Manager-owned Tool contribution collector."""

    def register_many(self, specs: Sequence[ToolSpec]) -> None: ...


class ExtensionCommandRegistrar(Protocol):
    """Manager-owned command contribution collector."""

    def register_many(self, contributions: Sequence[CommandContribution]) -> None: ...


class ExtensionPhaseRegistrar(Protocol):
    """Manager-owned phase contribution collector."""

    def register_many(self, contributions: Sequence[PhaseContribution]) -> None: ...


class ExtensionPromptRegistrar(Protocol):
    """Manager-owned prompt contribution collector."""

    def register_many(self, contributions: Sequence[PromptContribution]) -> None: ...


class ExtensionEventSink(Protocol):
    """Narrow event boundary; the first runtime keeps it intentionally inert."""

    def emit(self, event: Mapping[str, object]) -> None: ...


@dataclass(frozen=True, slots=True)
class ExtensionContext:
    """Controlled host capabilities passed to an enabled Extension.

    ``recontribute`` is the Extension's own handle for asking the host to
    rebuild its contributions while it stays enabled. It is optional so a host
    that does not support rebuilding simply leaves it unset, and an Extension
    that needs it can detect the absence instead of discovering it mid-call.
    """

    name: str
    core_version: str
    runtime_home: Path
    config: Mapping[str, object]
    tools: ExtensionToolRegistrar
    commands: ExtensionCommandRegistrar
    prompts: ExtensionPromptRegistrar
    events: ExtensionEventSink
    phases: ExtensionPhaseRegistrar | None = None
    recontribute: Callable[[], ExtensionStatus] | None = None


class ExtensionImplementation(Protocol):
    """Lifecycle object exported by an Extension entry point."""

    manifest: ExtensionManifest

    def start(self, context: ExtensionContext) -> ExtensionContributions | None: ...

    def stop(self) -> None: ...


class ExtensionRecontributing(Protocol):
    """Optional capability for an Extension whose contributions change at runtime.

    An Extension gated on external state - an authorization record, a licence, a
    reachable dependency - cannot decide its final Tool set at ``start``. It
    implements this method so the host can ask again later. ``contribute`` must
    return the *complete* current contribution set, not a delta, because the
    host swaps the whole set atomically and a delta could not be rolled back.
    """

    def contribute(self, context: ExtensionContext) -> ExtensionContributions | None: ...


ExtensionFactory: TypeAlias = Callable[[], ExtensionImplementation]
CommandHandler: TypeAlias = Callable[..., object]
CommandRegister: TypeAlias = Callable[
    [str, Sequence[tuple[str, CommandHandler]]], None
]
CommandUnregister: TypeAlias = Callable[[str], None]


class ExtensionManagerProtocol(Protocol):
    """Host lifecycle interface implemented by ``core.extensions``."""

    def discover(self) -> tuple[ExtensionDescriptor, ...]: ...

    def refresh_discovery(self) -> tuple[ExtensionDescriptor, ...]: ...

    def activate_persisted(self) -> tuple[ExtensionStatus, ...]: ...

    def enable(self, name: str) -> ExtensionStatus: ...

    def disable(self, name: str) -> ExtensionStatus: ...

    def recontribute(self, name: str) -> ExtensionStatus: ...

    def status(self, name: str | None = None) -> tuple[ExtensionStatus, ...]: ...

    def shutdown(self) -> None: ...


# The ADR names this protocol ExtensionManager; keep that spelling available
# without making the contracts module import its concrete implementation.
ExtensionManager = ExtensionManagerProtocol


__all__ = [
    "CommandContribution",
    "CommandHandler",
    "CommandRegister",
    "CommandUnregister",
    "ExtensionCommandContribution",
    "ExtensionContext",
    "ExtensionContributions",
    "ExtensionDescriptor",
    "ExtensionEventSink",
    "ExtensionFactory",
    "ExtensionImplementation",
    "ExtensionManager",
    "ExtensionManagerProtocol",
    "ExtensionManifest",
    "ExtensionPhaseContribution",
    "ExtensionPhaseRegistrar",
    "ExtensionPromptContribution",
    "ExtensionPromptRegistrar",
    "ExtensionState",
    "ExtensionStatus",
    "ExtensionStatusState",
    "ExtensionToolRegistrar",
    "PhaseContribution",
    "PromptContribution",
]
