"""CLI Adapter for Extension startup, session mounting, and shutdown."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class ExtensionHost:
    """Own one process-level ExtensionManager behind a small CLI Interface."""

    def __init__(self) -> None:
        self.manager: Any = None

    def start(self, *, runtime_home: Path, tool_registry: Any) -> Any:
        """Create the manager and isolate persisted activation failures."""
        from core.commands import register_owned_commands, unregister_owned_commands
        from core.extensions import ExtensionManager
        from core.logger import logger

        manager = ExtensionManager(
            tool_registry=tool_registry,
            runtime_home=runtime_home,
            command_register=register_owned_commands,
            command_unregister=unregister_owned_commands,
        )
        self.manager = manager
        try:
            statuses = manager.activate_persisted()
        except Exception as exc:
            logger.warning("Extension persisted activation failed: {}", exc)
            return manager

        for status in statuses:
            if getattr(getattr(status, "state", None), "value", None) == "failed":
                logger.warning(
                    "Extension '{}' failed to activate: {}",
                    status.name,
                    status.error or "unknown error",
                )
        return manager

    def mount(self, session: Any) -> None:
        """Expose the manager through the owning session RuntimeContext."""
        if self.manager is not None:
            session.runtime_context.extension_manager = self.manager

    def completion_items(self) -> dict[str, str]:
        """Read discoverable Extension names live for command completion."""
        if self.manager is None:
            return {}
        try:
            statuses = self.manager.status()
        except Exception:
            return {}
        items: dict[str, str] = {}
        for status in statuses:
            name = getattr(status, "name", "")
            if not name:
                continue
            state = getattr(getattr(status, "state", None), "value", None)
            state = state or str(getattr(status, "state", ""))
            description = getattr(status, "error", None) or f"Extension ({state})"
            items[str(name)] = str(description)
        return items

    def shutdown(self) -> None:
        """Release Extension resources once and tolerate cleanup failures."""
        from core.logger import logger

        manager = self.manager
        self.manager = None
        if manager is None:
            return
        try:
            manager.shutdown()
        except Exception as exc:
            logger.warning("Extension shutdown failed: {}", exc)


__all__ = ["ExtensionHost"]
