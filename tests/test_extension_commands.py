"""Tests for the optional Extension slash command UX."""

from __future__ import annotations

import asyncio
import importlib
import sys
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from core.commands import CommandContext
from core.extension_contracts import ExtensionState


class CaptureSink:
    def __init__(self) -> None:
        self.output: list[str] = []

    def print(self, text: str) -> None:
        self.output.append(text)

    def write(self, text: str) -> None:
        self.output.append(text)


@dataclass
class FakeStatus:
    name: str
    state: ExtensionState
    error: str | None = None


class FakeManager:
    def __init__(self, statuses: list[FakeStatus] | None = None) -> None:
        self.statuses = statuses or []
        self.calls: list[tuple[str, str | None]] = []

    def status(self, name: str | None = None) -> tuple[FakeStatus, ...]:
        self.calls.append(("status", name))
        if name is None:
            return tuple(self.statuses)
        return tuple(status for status in self.statuses if status.name == name)

    def enable(self, name: str) -> FakeStatus:
        self.calls.append(("enable", name))
        return next(status for status in self.statuses if status.name == name)

    def disable(self, name: str) -> FakeStatus:
        self.calls.append(("disable", name))
        return next(status for status in self.statuses if status.name == name)


@pytest.fixture(scope="module")
def extension_command():
    """Import the command with a local decorator so COMMANDS stays untouched."""
    commands = importlib.import_module("core.commands")
    captured: dict[str, object] = {}

    def fake_register(*verbs: str):
        def decorator(handler):
            for verb in verbs:
                captured[verb] = handler
            return handler

        return decorator

    original_register = commands.register
    commands.register = fake_register
    sys.modules.pop("core.commands.extensions", None)
    try:
        importlib.import_module("core.commands.extensions")
    finally:
        commands.register = original_register
    return captured["/extension"]


def make_context(sink: CaptureSink, manager: object | None, arg: str = "", arg2: str = ""):
    runtime_context = SimpleNamespace(extension_manager=manager)
    session = SimpleNamespace(runtime_context=runtime_context)
    return CommandContext("/extension", arg, arg2, session, sink)


def run_command(extension_command, context: CommandContext) -> None:
    asyncio.run(extension_command(context))


def test_list_renders_extension_states(extension_command):
    sink = CaptureSink()
    manager = FakeManager([
        FakeStatus("demo", ExtensionState.ENABLED),
        FakeStatus("disabled", ExtensionState.DISABLED),
    ])

    run_command(extension_command, make_context(sink, manager))

    assert sink.output[0] == "Extensions:"
    assert any("demo" in line and "enabled" in line for line in sink.output)
    assert manager.calls == [("status", None)]


def test_list_action_and_enable_success(extension_command):
    sink = CaptureSink()
    status = FakeStatus("demo", ExtensionState.ENABLED)
    manager = FakeManager([status])

    run_command(extension_command, make_context(sink, manager, "list"))
    run_command(extension_command, make_context(sink, manager, "enable", "demo"))

    assert "✓ Extension 'demo' — state: enabled" in sink.output
    assert manager.calls[-1] == ("enable", "demo")


def test_disable_failure_shows_state_and_redacts_error(extension_command):
    sink = CaptureSink()
    manager = FakeManager([
        FakeStatus(
            "demo",
            ExtensionState.FAILED,
            "token=super-secret-value; cleanup failed",
        ),
    ])

    run_command(extension_command, make_context(sink, manager, "disable", "demo"))

    assert sink.output == [
        "✗ Unable to disable 'demo' — state: failed; error: token=<redacted>; cleanup failed",
    ]
    assert "super-secret-value" not in sink.output[0]


def test_missing_manager_is_reported_as_unavailable(extension_command):
    sink = CaptureSink()

    run_command(extension_command, make_context(sink, None))

    assert sink.output == [
        "Extension manager is unavailable. Extensions cannot be managed.",
    ]


def test_missing_named_extension_is_reported_as_unavailable(extension_command):
    sink = CaptureSink()
    manager = FakeManager()

    run_command(extension_command, make_context(sink, manager, "status", "missing"))

    assert sink.output == [
        "✗ Unable to inspect 'missing' — state: unavailable",
    ]


@pytest.mark.parametrize(
    ("arg", "arg2"),
    [("unknown", ""), ("enable", ""), ("list", "extra"), ("status", "a b")],
)
def test_unknown_or_invalid_syntax_shows_usage(extension_command, arg, arg2):
    sink = CaptureSink()
    manager = FakeManager()

    run_command(extension_command, make_context(sink, manager, arg, arg2))

    assert sink.output == [
        "Usage: /extension [list|status [name]|enable <name>|disable <name>]",
    ]
    assert manager.calls == []
