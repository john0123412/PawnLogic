"""Plugin system package."""

from pawnlogic.plugins.base import Plugin, PluginResult
from pawnlogic.plugins.registry import PluginRegistry

__all__ = ["Plugin", "PluginResult", "PluginRegistry"]
