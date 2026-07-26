"""Contract tests for rebuilding an enabled Extension's contributions.

A scope-gated Extension publishes and withdraws Tools while it stays enabled.
These tests pin the property that matters for that: the host either has the new
contribution set or the previous one, never a partially applied mixture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.extension_contracts import (
    CommandContribution,
    ExtensionContributions,
    ExtensionManifest,
    ExtensionState,
)
from core.extensions import ExtensionManager
from core.tool_registry import ToolRegistry, ToolSpec


def _schema(name: str) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "parameters": {"type": "object"}},
    }


def _tool(name: str) -> ToolSpec:
    return ToolSpec(name=name, handler=lambda _args: name, schema=_schema(name))


class _Distribution:
    def __init__(self, name: str, version: str) -> None:
        self.name = name
        self.version = version


class _EntryPoint:
    def __init__(self, name: str, export: object) -> None:
        self.name = name
        self.value = f"{name}.extension:extension"
        self.dist = _Distribution(name, "1.0.0")
        self.export = export

    def load(self) -> object:
        return self.export


def _manifest(name: str = "security") -> ExtensionManifest:
    return ExtensionManifest(
        name=name,
        version="1.0.0",
        core_version_spec=">=0.2,<0.3",
        api_version=1,
        description="test Extension",
        capabilities=frozenset({"network"}),
        config_schema={"type": "object", "additionalProperties": False},
    )


@dataclass
class _ScopedExtension:
    """An Extension whose Tool set depends on state set after ``start``."""

    manifest: ExtensionManifest
    tools: tuple[ToolSpec, ...] = ()
    commands: tuple[CommandContribution, ...] = ()
    contribute_error: BaseException | None = None
    contribute_calls: int = 0
    reenter: bool = False
    started: int = 0
    stopped: int = 0
    context: object = field(default=None)

    def start(self, context):
        self.started += 1
        self.context = context
        # Commands only: the Tool set is not knowable until a scope is set.
        return ExtensionContributions(commands=self.commands)

    def contribute(self, context):
        self.contribute_calls += 1
        self.context = context
        if self.reenter and context.recontribute is not None:
            self.reentry_status = context.recontribute()
        if self.contribute_error is not None:
            raise self.contribute_error
        return ExtensionContributions(tools=self.tools, commands=self.commands)

    def stop(self) -> None:
        self.stopped += 1


@dataclass
class _PlainExtension:
    """An Extension from before the seam existed; it has no ``contribute``."""

    manifest: ExtensionManifest
    started: int = 0
    stopped: int = 0

    def start(self, context):
        self.started += 1
        return ExtensionContributions(tools=(_tool("plain_tool"),))

    def stop(self) -> None:
        self.stopped += 1


def _manager(tmp_path: Path, entry_points, registry=None, **kwargs) -> ExtensionManager:
    return ExtensionManager(
        registry,
        runtime_home=tmp_path / "runtime",
        entry_points=entry_points,
        core_version="0.2.3",
        **kwargs,
    )


def _names(registry: ToolRegistry) -> set[str]:
    return {spec.name for spec in registry.snapshot_specs()}


def test_tools_stay_absent_until_recontribution(tmp_path):
    registry = ToolRegistry()
    extension = _ScopedExtension(_manifest(), tools=(_tool("security_passive_recon"),))
    manager = _manager(tmp_path, [_EntryPoint("security", extension)], registry)

    assert manager.enable("security").state is ExtensionState.ENABLED
    assert _names(registry) == set()

    status = manager.recontribute("security")

    assert status.state is ExtensionState.ENABLED
    assert status.error is None
    assert _names(registry) == {"security_passive_recon"}
    assert extension.started == 1  # rebuilding is not a restart


def test_recontribution_withdraws_tools_and_keeps_commands(tmp_path):
    registry = ToolRegistry()
    command = CommandContribution(name="security", handler=lambda *_a, **_k: None)
    extension = _ScopedExtension(
        _manifest(), tools=(_tool("security_active_discovery"),), commands=(command,)
    )
    manager = _manager(tmp_path, [_EntryPoint("security", extension)], registry)
    manager.enable("security")
    manager.recontribute("security")
    assert _names(registry) == {"security_active_discovery"}

    # The scope is cleared, so the Extension now offers no Tools at all.
    extension.tools = ()
    status = manager.recontribute("security")

    assert status.state is ExtensionState.ENABLED
    assert _names(registry) == set()
    assert [item.name for item in manager.command_snapshot()] == ["security"]


def test_repeated_recontribution_does_not_conflict_with_itself(tmp_path):
    registry = ToolRegistry()
    extension = _ScopedExtension(_manifest(), tools=(_tool("security_passive_recon"),))
    manager = _manager(tmp_path, [_EntryPoint("security", extension)], registry)
    manager.enable("security")

    for _ in range(3):
        assert manager.recontribute("security").error is None

    assert _names(registry) == {"security_passive_recon"}
    assert len(registry.snapshot_specs()) == 1
    assert registry.owner_of("security_passive_recon") == "security"


def test_failed_rebuild_restores_the_previous_tool_set(tmp_path):
    registry = ToolRegistry()
    extension = _ScopedExtension(_manifest(), tools=(_tool("security_passive_recon"),))
    manager = _manager(tmp_path, [_EntryPoint("security", extension)], registry)
    manager.enable("security")
    manager.recontribute("security")
    assert _names(registry) == {"security_passive_recon"}

    extension.tools = (_tool("security_active_discovery"),)
    extension.contribute_error = RuntimeError("scope file unreadable")
    status = manager.recontribute("security")

    # Still enabled, still holding exactly what it held before the attempt.
    assert status.state is ExtensionState.ENABLED
    assert status.error is not None
    assert "scope file unreadable" in status.error
    assert _names(registry) == {"security_passive_recon"}


def test_invalid_rebuild_is_rejected_without_losing_current_tools(tmp_path):
    registry = ToolRegistry()
    extension = _ScopedExtension(_manifest(), tools=(_tool("security_passive_recon"),))
    manager = _manager(tmp_path, [_EntryPoint("security", extension)], registry)
    manager.enable("security")
    manager.recontribute("security")

    # Two Tools sharing one name is not a registrable set.
    duplicate = _tool("security_duplicate")
    extension.tools = (duplicate, duplicate)
    status = manager.recontribute("security")

    assert status.state is ExtensionState.ENABLED
    assert status.error is not None
    assert _names(registry) == {"security_passive_recon"}


def test_rebuild_cannot_take_a_tool_owned_by_another_extension(tmp_path):
    registry = ToolRegistry()
    other = _ScopedExtension(_manifest("other"), tools=())
    extension = _ScopedExtension(_manifest(), tools=(_tool("security_passive_recon"),))
    manager = _manager(
        tmp_path,
        [_EntryPoint("other", other), _EntryPoint("security", extension)],
        registry,
    )
    manager.enable("other")
    other.tools = (_tool("shared_tool"),)
    manager.recontribute("other")
    manager.enable("security")
    manager.recontribute("security")

    extension.tools = (_tool("shared_tool"),)
    status = manager.recontribute("security")

    assert status.error is not None
    assert registry.owner_of("shared_tool") == "other"
    assert _names(registry) == {"shared_tool", "security_passive_recon"}


def test_recontribution_is_refused_when_not_enabled(tmp_path):
    registry = ToolRegistry()
    extension = _ScopedExtension(_manifest(), tools=(_tool("security_passive_recon"),))
    manager = _manager(tmp_path, [_EntryPoint("security", extension)], registry)

    status = manager.recontribute("security")

    assert status.state is not ExtensionState.ENABLED
    assert status.error == "extension is not enabled"
    assert _names(registry) == set()
    assert extension.contribute_calls == 0


def test_recontribution_is_refused_after_disable(tmp_path):
    registry = ToolRegistry()
    extension = _ScopedExtension(_manifest(), tools=(_tool("security_passive_recon"),))
    manager = _manager(tmp_path, [_EntryPoint("security", extension)], registry)
    manager.enable("security")
    manager.recontribute("security")
    manager.disable("security")

    status = manager.recontribute("security")

    assert status.error == "extension is not enabled"
    assert _names(registry) == set()


def test_extension_without_contribute_is_reported_not_supported(tmp_path):
    registry = ToolRegistry()
    manager = _manager(
        tmp_path, [_EntryPoint("plain", _PlainExtension(_manifest("plain")))], registry
    )
    manager.enable("plain")

    status = manager.recontribute("plain")

    assert status.state is ExtensionState.ENABLED
    assert status.error == "extension does not support recontribution"
    assert _names(registry) == {"plain_tool"}


def test_unknown_extension_recontribution_is_inert(tmp_path):
    manager = _manager(tmp_path, [], ToolRegistry())

    assert manager.recontribute("absent").state is ExtensionState.UNAVAILABLE


def test_reentrant_recontribution_is_refused_not_recursed(tmp_path):
    registry = ToolRegistry()
    extension = _ScopedExtension(_manifest(), tools=(_tool("security_passive_recon"),))
    extension.reenter = True
    manager = _manager(tmp_path, [_EntryPoint("security", extension)], registry)
    manager.enable("security")

    status = manager.recontribute("security")

    assert extension.contribute_calls == 1
    assert extension.reentry_status.error == "recontribution already in progress"
    assert status.state is ExtensionState.ENABLED
    assert _names(registry) == {"security_passive_recon"}


def test_extension_can_trigger_its_own_rebuild_through_the_context(tmp_path):
    registry = ToolRegistry()
    extension = _ScopedExtension(_manifest(), tools=(_tool("security_passive_recon"),))
    manager = _manager(tmp_path, [_EntryPoint("security", extension)], registry)
    manager.enable("security")

    # This is the handle a scope command uses: the Extension asks the host to
    # re-read it, without the Extension ever touching the host registries.
    assert extension.context.recontribute is not None
    status = extension.context.recontribute()

    assert status.state is ExtensionState.ENABLED
    assert _names(registry) == {"security_passive_recon"}


def test_rebuilt_tools_are_visible_to_the_model(tmp_path):
    registry = ToolRegistry()
    extension = _ScopedExtension(_manifest(), tools=(_tool("security_passive_recon"),))
    manager = _manager(tmp_path, [_EntryPoint("security", extension)], registry)
    manager.enable("security")
    assert registry.visible_specs("*") == ()

    manager.recontribute("security")
    assert [spec.name for spec in registry.visible_specs("*")] == [
        "security_passive_recon"
    ]

    extension.tools = ()
    manager.recontribute("security")
    assert registry.visible_specs("*") == ()


def test_disable_after_recontribution_removes_everything(tmp_path):
    registry = ToolRegistry()
    command = CommandContribution(name="security", handler=lambda *_a, **_k: None)
    extension = _ScopedExtension(
        _manifest(), tools=(_tool("security_passive_recon"),), commands=(command,)
    )
    manager = _manager(tmp_path, [_EntryPoint("security", extension)], registry)
    manager.enable("security")
    manager.recontribute("security")

    manager.disable("security")

    assert _names(registry) == set()
    assert manager.command_snapshot() == ()
    assert manager.owner_snapshot()["tools"] == ()
    assert extension.stopped == 1
