"""Contract tests for the non-importing Extension Runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.extension_contracts import (
    CommandContribution,
    ExtensionContributions,
    ExtensionManifest,
    ExtensionState,
    PhaseContribution,
    PromptContribution,
)
from core.extensions import ExtensionManager
from core.tool_registry import ToolRegistry, ToolSpec


def _schema(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}


def _tool(name: str) -> ToolSpec:
    return ToolSpec(name=name, handler=lambda _args: name, schema=_schema(name))


class _Distribution:
    def __init__(self, name: str, version: str) -> None:
        self.name = name
        self.version = version


class _EntryPoint:
    def __init__(self, name: str, export: object, *, distribution: str | None = None, version: str = "1.0.0") -> None:
        self.name = name
        self.value = f"{name}.extension:extension"
        self.dist = _Distribution(distribution or name, version)
        self.export = export
        self.load_count = 0

    def load(self) -> object:
        self.load_count += 1
        if isinstance(self.export, BaseException):
            raise self.export
        return self.export


@dataclass
class _Extension:
    manifest: ExtensionManifest
    contributions: ExtensionContributions = field(default_factory=ExtensionContributions)
    start_error: BaseException | None = None
    stop_error: BaseException | None = None
    use_context: bool = False
    started: int = 0
    stopped: int = 0

    def start(self, context):
        self.started += 1
        if self.start_error is not None:
            if self.use_context:
                context.tools.register_many(self.contributions.tools)
            raise self.start_error
        if self.use_context:
            context.tools.register_many(self.contributions.tools)
            context.commands.register_many(self.contributions.commands)
            context.phases.register_many(self.contributions.phases)
            context.prompts.register_many(self.contributions.prompts)
            return None
        return self.contributions

    def stop(self) -> None:
        self.stopped += 1
        if self.stop_error is not None:
            raise self.stop_error


def _manifest(name: str = "demo", *, core: str = ">=0.2,<0.3", schema: dict | None = None) -> ExtensionManifest:
    return ExtensionManifest(
        name=name,
        version="1.0.0",
        core_version_spec=core,
        api_version=1,
        description="test Extension",
        capabilities=frozenset({"tools.read_only"}),
        config_schema=schema or {"type": "object", "additionalProperties": False},
    )


def _manager(tmp_path: Path, entry_points, registry=None, **kwargs) -> ExtensionManager:
    return ExtensionManager(
        registry,
        runtime_home=tmp_path / "runtime",
        entry_points=entry_points,
        core_version="0.2.3",
        **kwargs,
    )


def test_no_extensions_is_a_successful_empty_runtime(tmp_path):
    manager = _manager(tmp_path, [])

    assert manager.discover() == ()
    assert manager.status() == ()
    manager.shutdown()


def test_discovery_lists_disabled_extension_without_loading_it(tmp_path):
    extension = _Extension(_manifest())
    entry_point = _EntryPoint("demo", extension)
    manager = _manager(tmp_path, [entry_point])

    descriptors = manager.discover()

    assert descriptors[0].name == "demo"
    assert descriptors[0].enabled is False
    assert manager.status("demo")[0].state is ExtensionState.DISCOVERED
    assert entry_point.load_count == 0
    assert extension.started == 0


def test_enable_registers_all_contributions_and_persists_atomically(tmp_path):
    extension = _Extension(
        _manifest(),
        ExtensionContributions(
            tools=(_tool("demo_tool"),),
            commands=(CommandContribution("demo-command"),),
            phases=(PhaseContribution("DEMO"),),
            prompts=(PromptContribution("demo-prompt", "Use the demo tool."),),
        ),
    )
    entry_point = _EntryPoint("demo", extension)
    registry = ToolRegistry()
    manager = _manager(tmp_path, [entry_point], registry)

    status = manager.enable("DEMO")

    assert status.state is ExtensionState.ENABLED
    assert status.enabled is True
    assert entry_point.load_count == 1
    assert registry.get_spec("demo_tool") is not None
    assert manager.command_snapshot()[0].name == "demo-command"
    assert manager.phase_snapshot()[0].name == "DEMO"
    assert manager.prompt_snapshot()[0].name == "demo-prompt"
    assert json_names(manager.enabled_state_path) == ["demo"]


def test_enable_failure_during_persistence_rolls_back_tools_and_calls_stop(tmp_path, monkeypatch):
    extension = _Extension(_manifest(), ExtensionContributions(tools=(_tool("demo_tool"),)))
    registry = ToolRegistry()
    manager = _manager(tmp_path, [_EntryPoint("demo", extension)], registry)
    monkeypatch.setattr(manager, "_write_enabled_names", lambda _names: (_ for _ in ()).throw(OSError("disk full")))

    status = manager.enable("demo")

    assert status.state is ExtensionState.FAILED
    assert status.enabled is False
    assert registry.get_spec("demo_tool") is None
    assert extension.stopped == 1
    assert "disk full" in (status.error or "")


def test_persisted_enablement_is_visible_without_auto_loading(tmp_path):
    extension = _Extension(_manifest())
    entry_point = _EntryPoint("demo", extension)
    first_manager = _manager(tmp_path, [entry_point])
    assert first_manager.enable("demo").state is ExtensionState.ENABLED

    replacement_entry_point = _EntryPoint("demo", _Extension(_manifest()))
    second_manager = _manager(tmp_path, [replacement_entry_point])

    descriptor = second_manager.discover()[0]

    assert descriptor.enabled is True
    assert replacement_entry_point.load_count == 0


def test_incompatible_extension_is_rejected_after_load_without_start(tmp_path):
    extension = _Extension(_manifest(core=">=9.0"))
    entry_point = _EntryPoint("demo", extension)
    manager = _manager(tmp_path, [entry_point])

    status = manager.enable("demo")

    assert status.state is ExtensionState.FAILED
    assert status.compatible is False
    assert extension.started == 0
    assert entry_point.load_count == 1
    assert "incompatible" in (status.error or "").lower()


def test_invalid_config_is_rejected_before_start(tmp_path):
    extension = _Extension(
        _manifest(
            schema={
                "type": "object",
                "properties": {"mode": {"type": "string"}},
                "required": ["mode"],
                "additionalProperties": False,
            }
        )
    )
    manager = _manager(tmp_path, [_EntryPoint("demo", extension)], configs={"demo": {}})

    status = manager.enable("demo")

    assert status.state is ExtensionState.FAILED
    assert extension.started == 0
    assert "required" in (status.error or "")


def test_load_and_start_failures_are_isolated_and_redacted(tmp_path):
    load_entry_point = _EntryPoint("load-fails", RuntimeError("token=load-secret"))
    load_manager = _manager(tmp_path / "load", [load_entry_point])
    load_status = load_manager.enable("load-fails")

    start_extension = _Extension(_manifest("start-fails"), start_error=RuntimeError("api_key=start-secret"))
    start_entry_point = _EntryPoint("start-fails", start_extension)
    start_manager = _manager(tmp_path / "start", [start_entry_point], ToolRegistry())
    start_status = start_manager.enable("start-fails")

    assert load_status.state is ExtensionState.FAILED
    assert "load-secret" not in (load_status.error or "")
    assert start_status.state is ExtensionState.FAILED
    assert "start-secret" not in (start_status.error or "")
    assert start_extension.stopped == 1


def test_context_registrars_are_manager_owned_and_rollback_together(tmp_path):
    contributions = ExtensionContributions(
        tools=(_tool("ctx-tool"),),
        commands=(CommandContribution("ctx-command"),),
        phases=(PhaseContribution("CTX"),),
        prompts=(PromptContribution("ctx-prompt", "context"),),
    )
    extension = _Extension(_manifest(), contributions, use_context=True)
    registry = ToolRegistry()
    manager = _manager(tmp_path, [_EntryPoint("demo", extension)], registry)

    assert manager.enable("demo").state is ExtensionState.ENABLED
    manager.disable("demo")

    assert registry.get_spec("ctx-tool") is None
    assert manager.command_snapshot() == ()
    assert manager.phase_snapshot() == ()
    assert manager.prompt_snapshot() == ()


def test_duplicate_extension_names_are_rejected_without_loading(tmp_path):
    first = _EntryPoint("demo", _Extension(_manifest()), distribution="demo-a")
    second = _EntryPoint("demo", _Extension(_manifest()), distribution="demo-b")
    manager = _manager(tmp_path, [first, second])

    descriptors = manager.discover()
    status = manager.enable("demo")

    assert len(descriptors) == 2
    assert all(descriptor.error == "duplicate extension name" for descriptor in descriptors)
    assert status.state is ExtensionState.FAILED
    assert first.load_count == 0
    assert second.load_count == 0


def test_duplicate_tool_and_command_names_fail_without_partial_state(tmp_path):
    extension = _Extension(
        _manifest(),
        ExtensionContributions(
            tools=(_tool("same"), _tool("same")),
            commands=(CommandContribution("same-command"), CommandContribution("same-command")),
        ),
    )
    registry = ToolRegistry()
    manager = _manager(tmp_path, [_EntryPoint("demo", extension)], registry)

    status = manager.enable("demo")

    assert status.state is ExtensionState.FAILED
    assert registry.get_spec("same") is None
    assert manager.command_snapshot() == ()


def test_disable_removes_only_owned_tools_and_persisted_enablement(tmp_path):
    first = _Extension(_manifest("first"), ExtensionContributions(tools=(_tool("first-tool"),)))
    second = _Extension(_manifest("second"), ExtensionContributions(tools=(_tool("second-tool"),)))
    registry = ToolRegistry()
    manager = _manager(
        tmp_path,
        [_EntryPoint("first", first), _EntryPoint("second", second)],
        registry,
    )
    manager.enable("first")
    manager.enable("second")

    status = manager.disable("first")

    assert status.state is ExtensionState.DISABLED
    assert registry.get_spec("first-tool") is None
    assert registry.get_spec("second-tool") is not None
    assert json_names(manager.enabled_state_path) == ["second"]


def test_shutdown_stops_and_removes_runtime_state_but_retains_persisted_names(tmp_path):
    extension = _Extension(_manifest(), ExtensionContributions(tools=(_tool("shutdown-tool"),)))
    registry = ToolRegistry()
    manager = _manager(tmp_path, [_EntryPoint("demo", extension)], registry)
    manager.enable("demo")

    manager.shutdown()

    assert extension.stopped == 1
    assert registry.get_spec("shutdown-tool") is None
    assert json_names(manager.enabled_state_path) == ["demo"]
    assert manager.status("demo")[0].state is ExtensionState.DISABLED


def json_names(path: Path) -> list[str]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def test_pep_440_compatible_and_wildcard_core_specs(tmp_path):
    accepted_specs = ("~=0.2", "~=0.2.3", "==0.2.*")
    for index, spec in enumerate(accepted_specs):
        extension = _Extension(_manifest(core=spec))
        manager = _manager(
            tmp_path / f"accepted-{index}",
            [_EntryPoint("demo", extension)],
        )
        assert manager.enable("demo").state is ExtensionState.ENABLED

    rejected = _Extension(_manifest(core="~=0.2.4"))
    manager = _manager(tmp_path / "rejected", [_EntryPoint("demo", rejected)])
    assert manager.enable("demo").state is ExtensionState.FAILED
    assert rejected.started == 0
