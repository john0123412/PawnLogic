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


class _CommandAdapter:
    def __init__(self) -> None:
        self.registered: dict[str, dict[str, object]] = {}
        self.register_calls: list[tuple[str, tuple[tuple[str, object], ...]]] = []
        self.unregister_calls: list[str] = []
        self.fail_for: set[str] = set()

    def register(self, owner: str, handlers) -> None:
        batch = tuple(handlers)
        self.register_calls.append((owner, batch))
        if owner in self.fail_for:
            raise RuntimeError("command registry unavailable")
        verbs = {verb for verb, _handler in batch}
        if verbs.intersection(self.registered.get("builtin", {})):
            raise ValueError("command verb already registered")
        for existing in self.registered.values():
            if verbs.intersection(existing):
                raise ValueError("command verb already registered")
        self.registered[owner] = dict(batch)

    def unregister(self, owner: str) -> None:
        self.unregister_calls.append(owner)
        self.registered.pop(owner, None)


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


def test_command_adapter_registers_callable_handlers_and_unregisters_on_disable(tmp_path):
    handler = lambda _ctx: "ok"
    adapter = _CommandAdapter()
    extension = _Extension(
        _manifest(),
        ExtensionContributions(commands=(CommandContribution("/demo", handler),)),
    )
    manager = _manager(
        tmp_path,
        [_EntryPoint("demo", extension)],
        command_register=adapter.register,
        command_unregister=adapter.unregister,
    )

    assert manager.enable("demo").state is ExtensionState.ENABLED
    assert adapter.registered["demo"]["/demo"] is handler

    assert manager.disable("demo").state is ExtensionState.DISABLED
    assert "demo" not in adapter.registered
    assert adapter.unregister_calls == ["demo"]


def test_command_contribution_without_handler_fails_when_adapter_is_configured(tmp_path):
    adapter = _CommandAdapter()
    extension = _Extension(
        _manifest(),
        ExtensionContributions(commands=(CommandContribution("/missing"),)),
    )
    manager = _manager(
        tmp_path,
        [_EntryPoint("demo", extension)],
        command_register=adapter.register,
        command_unregister=adapter.unregister,
    )

    status = manager.enable("demo")

    assert status.state is ExtensionState.FAILED
    assert "handler is required" in (status.error or "")
    assert adapter.register_calls == []
    assert manager.command_snapshot() == ()


def test_command_conflict_is_rejected_without_removing_existing_owner(tmp_path):
    adapter = _CommandAdapter()
    first = _Extension(
        _manifest("first"),
        ExtensionContributions(commands=(CommandContribution("/shared", lambda _ctx: "first"),)),
    )
    second = _Extension(
        _manifest("second"),
        ExtensionContributions(commands=(CommandContribution("/shared", lambda _ctx: "second"),)),
    )
    manager = _manager(
        tmp_path,
        [_EntryPoint("second", second), _EntryPoint("first", first)],
        command_register=adapter.register,
        command_unregister=adapter.unregister,
    )

    assert manager.enable("first").state is ExtensionState.ENABLED
    status = manager.enable("second")

    assert status.state is ExtensionState.FAILED
    assert adapter.registered["first"]["/shared"] is not None
    assert "second" not in adapter.registered
    assert manager.command_snapshot()[0].name == "/shared"


def test_command_registration_rolls_back_when_persistence_fails(tmp_path, monkeypatch):
    adapter = _CommandAdapter()
    extension = _Extension(
        _manifest(),
        ExtensionContributions(commands=(CommandContribution("/demo", lambda _ctx: "ok"),)),
    )
    manager = _manager(
        tmp_path,
        [_EntryPoint("demo", extension)],
        command_register=adapter.register,
        command_unregister=adapter.unregister,
    )
    monkeypatch.setattr(
        manager,
        "_write_enabled_names",
        lambda _names: (_ for _ in ()).throw(OSError("disk full")),
    )

    status = manager.enable("demo")

    assert status.state is ExtensionState.FAILED
    assert "demo" not in adapter.registered
    assert adapter.unregister_calls == ["demo"]
    assert manager.command_snapshot() == ()


def test_shutdown_unregisters_command_contributions(tmp_path):
    adapter = _CommandAdapter()
    extension = _Extension(
        _manifest(),
        ExtensionContributions(commands=(CommandContribution("/demo", lambda _ctx: "ok"),)),
    )
    manager = _manager(
        tmp_path,
        [_EntryPoint("demo", extension)],
        command_register=adapter.register,
        command_unregister=adapter.unregister,
    )

    assert manager.enable("demo").state is ExtensionState.ENABLED
    manager.shutdown()

    assert "demo" not in adapter.registered
    assert adapter.unregister_calls == ["demo"]
    assert manager.command_snapshot() == ()


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


def test_activate_persisted_uses_canonical_order_and_isolates_failures(tmp_path):
    first_manager = _manager(
        tmp_path,
        [
            _EntryPoint("zeta", _Extension(_manifest("zeta"))),
            _EntryPoint("alpha", _Extension(_manifest("alpha"))),
        ],
    )
    assert first_manager.enable("zeta").state is ExtensionState.ENABLED
    assert first_manager.enable("alpha").state is ExtensionState.ENABLED

    load_order: list[str] = []

    class _OrderedEntryPoint(_EntryPoint):
        def load(self):
            load_order.append(self.name)
            return super().load()

    replacement = _manager(
        tmp_path,
        [
            _OrderedEntryPoint("zeta", _Extension(_manifest("zeta"))),
            _OrderedEntryPoint("alpha", RuntimeError("alpha failed")),
        ],
    )

    statuses = replacement.activate_persisted()

    assert [status.name for status in statuses] == ["alpha", "zeta"]
    assert [status.state for status in statuses] == [ExtensionState.FAILED, ExtensionState.ENABLED]
    assert load_order == ["alpha", "zeta"]


def test_refresh_discovery_reloads_metadata_without_loading_entry_points(tmp_path):
    first = _EntryPoint("first", _Extension(_manifest("first")))
    second = _EntryPoint("second", _Extension(_manifest("second")))
    available = [first]
    manager = _manager(tmp_path, lambda: available)

    assert [item.name for item in manager.discover()] == ["first"]
    available.append(second)

    descriptors = manager.refresh_discovery()

    assert [item.name for item in descriptors] == ["first", "second"]
    assert first.load_count == 0
    assert second.load_count == 0


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
