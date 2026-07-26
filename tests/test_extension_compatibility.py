"""Compatibility tests using a real installed-layout Extension distribution."""

from __future__ import annotations

import sys
from importlib import metadata
from pathlib import Path

import pytest

from core.extension_contracts import ExtensionState
from core.extensions import ExtensionManager
from core.tool_registry import ToolRegistry


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "extensions" / "site-packages"
FIXTURE_MODULE = "pawnlogic_compat_fixture"
EXTENSION_NAME = "compat-fixture"


@pytest.fixture
def installed_fixture(monkeypatch, tmp_path):
    for name in tuple(sys.modules):
        if name == FIXTURE_MODULE or name.startswith(f"{FIXTURE_MODULE}."):
            sys.modules.pop(name)
    events = tmp_path / "events.txt"
    monkeypatch.syspath_prepend(str(FIXTURE_ROOT))
    monkeypatch.setenv("PAWNLOGIC_EXTENSION_FIXTURE_MARKER", str(events))
    monkeypatch.delenv("PAWNLOGIC_EXTENSION_FIXTURE_MODE", raising=False)
    yield events
    for name in tuple(sys.modules):
        if name == FIXTURE_MODULE or name.startswith(f"{FIXTURE_MODULE}."):
            sys.modules.pop(name)


def _fixture_entry_point():
    try:
        points = metadata.entry_points(group="pawnlogic.extensions")
    except TypeError:
        points = metadata.entry_points().select(group="pawnlogic.extensions")
    return next(point for point in points if point.name == EXTENSION_NAME)


def _manager(tmp_path: Path) -> tuple[ExtensionManager, ToolRegistry]:
    registry = ToolRegistry()
    manager = ExtensionManager(
        registry,
        runtime_home=tmp_path / "runtime",
        core_version="0.2.3",
        entry_points=(_fixture_entry_point(),),
    )
    return manager, registry


def _events(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def test_installed_but_disabled_entry_point_is_discovered_without_import(
    installed_fixture,
    tmp_path,
):
    point = _fixture_entry_point()
    assert point.value == "pawnlogic_compat_fixture.extension:extension"
    manager, registry = _manager(tmp_path)

    descriptors = manager.discover()

    assert [item.name for item in descriptors] == [EXTENSION_NAME]
    assert manager.status(EXTENSION_NAME)[0].state is ExtensionState.DISCOVERED
    assert registry.snapshot_specs() == ()
    assert _events(installed_fixture) == []
    assert "pawnlogic_compat_fixture.extension" not in sys.modules


def test_real_entry_point_enable_exposes_all_contributions_after_success(
    installed_fixture,
    tmp_path,
):
    manager, registry = _manager(tmp_path)
    assert manager.command_snapshot() == ()
    assert manager.phase_snapshot() == ()
    assert manager.prompt_snapshot() == ()

    status = manager.enable(EXTENSION_NAME)

    assert status.state is ExtensionState.ENABLED
    assert registry.get_spec("compat_fixture_tool") is not None
    assert registry.owner_of("compat_fixture_tool") == EXTENSION_NAME
    assert [item.name for item in manager.command_snapshot()] == ["/compat-fixture"]
    assert [item.name for item in manager.phase_snapshot()] == ["COMPAT_FIXTURE"]
    assert [item.name for item in manager.prompt_snapshot()] == [
        "compat-fixture-prompt"
    ]
    assert manager.owner_snapshot() == {
        "tools": (EXTENSION_NAME,),
        "commands": (EXTENSION_NAME,),
        "phases": (EXTENSION_NAME,),
        "prompts": (EXTENSION_NAME,),
    }
    assert _events(installed_fixture) == ["import", "start"]
    manager.shutdown()
    assert _events(installed_fixture) == ["import", "start", "stop"]


@pytest.mark.parametrize("mode", ["incompatible", "start-fails"])
def test_real_entry_point_failure_is_isolated_and_rolls_back(
    installed_fixture,
    tmp_path,
    monkeypatch,
    mode,
):
    monkeypatch.setenv("PAWNLOGIC_EXTENSION_FIXTURE_MODE", mode)
    manager, registry = _manager(tmp_path)

    status = manager.enable(EXTENSION_NAME)

    assert status.state is ExtensionState.FAILED
    assert status.enabled is False
    assert registry.snapshot_specs() == ()
    assert manager.command_snapshot() == ()
    assert manager.phase_snapshot() == ()
    assert manager.prompt_snapshot() == ()
    assert manager.owner_snapshot() == {
        "tools": (),
        "commands": (),
        "phases": (),
        "prompts": (),
    }
    events = _events(installed_fixture)
    assert events[0] == "import"
    if mode == "incompatible":
        assert "start" not in events
    else:
        assert "start" in events
    assert events[-1] == "stop"
