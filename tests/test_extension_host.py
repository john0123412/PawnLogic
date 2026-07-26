"""Tests for the process-level ExtensionHost Adapter."""

from __future__ import annotations

from types import SimpleNamespace

import core.extensions

from pawnlogic.extension_host import ExtensionHost


def test_mount_and_live_completion_items():
    host = ExtensionHost()
    host.manager = SimpleNamespace(
        status=lambda: (
            SimpleNamespace(
                name="demo",
                state=SimpleNamespace(value="disabled"),
                error=None,
            ),
        )
    )
    session = SimpleNamespace(runtime_context=SimpleNamespace(extension_manager=None))

    host.mount(session)

    assert session.runtime_context.extension_manager is host.manager
    assert host.completion_items() == {"demo": "Extension (disabled)"}


def test_completion_failure_is_non_fatal():
    def fail():
        raise RuntimeError("metadata unavailable")

    host = ExtensionHost()
    host.manager = SimpleNamespace(status=fail)

    assert host.completion_items() == {}


def test_start_isolates_persisted_activation_failure(monkeypatch, tmp_path):
    manager = SimpleNamespace(
        activate_persisted=lambda: (_ for _ in ()).throw(
            RuntimeError("extension start failed")
        ),
        shutdown=lambda: None,
    )
    monkeypatch.setattr(
        core.extensions,
        "ExtensionManager",
        lambda **_kwargs: manager,
    )
    host = ExtensionHost()

    result = host.start(runtime_home=tmp_path, tool_registry=object())

    assert result is manager
    assert host.manager is manager


def test_shutdown_is_idempotent():
    calls: list[str] = []
    host = ExtensionHost()
    host.manager = SimpleNamespace(shutdown=lambda: calls.append("shutdown"))

    host.shutdown()
    host.shutdown()

    assert calls == ["shutdown"]
