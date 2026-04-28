"""Tests for the Plugin base class, PluginRegistry, and built-in plugins."""

from __future__ import annotations

import asyncio
import math
from typing import Any

import pytest

from pawnlogic.plugins.base import Plugin, PluginResult
from pawnlogic.plugins.registry import PluginRegistry
from pawnlogic.plugins.builtin.calculator import CalculatorPlugin
from pawnlogic.plugins.builtin.web_search import WebSearchPlugin


# ---------------------------------------------------------------------------
# Minimal concrete plugin for testing the base class
# ---------------------------------------------------------------------------

class DoublePlugin(Plugin):
    """Returns double the given number."""

    @property
    def name(self) -> str:
        return "double"

    @property
    def description(self) -> str:
        return "Returns double the input number."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"n": {"type": "number", "description": "Number to double."}}

    def execute(self, **kwargs: Any) -> PluginResult:
        n = kwargs.get("n", 0)
        return PluginResult(success=True, output=str(n * 2), data={"result": n * 2})


# ---------------------------------------------------------------------------
# Plugin base class tests
# ---------------------------------------------------------------------------

def test_plugin_to_schema():
    plugin = DoublePlugin()
    schema = plugin.to_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "double"
    assert "n" in schema["function"]["parameters"]["properties"]


def test_plugin_execute():
    plugin = DoublePlugin()
    result = plugin.execute(n=5)
    assert result.success is True
    assert result.output == "10"
    assert result.data["result"] == 10


def test_plugin_execute_async_fallback():
    plugin = DoublePlugin()
    result = asyncio.run(plugin.execute_async(n=3))
    assert result.success is True
    assert result.output == "6"


def test_plugin_result_defaults():
    r = PluginResult(success=True, output="ok")
    assert r.data == {}
    assert r.error is None


# ---------------------------------------------------------------------------
# PluginRegistry tests
# ---------------------------------------------------------------------------

def test_registry_register_and_get():
    registry = PluginRegistry()
    registry.register(DoublePlugin())
    assert "double" in registry
    plugin = registry.get("double")
    assert plugin.name == "double"


def test_registry_register_duplicate_raises():
    registry = PluginRegistry()
    registry.register(DoublePlugin())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(DoublePlugin())


def test_registry_replace():
    registry = PluginRegistry()
    registry.register(DoublePlugin())
    registry.replace(DoublePlugin())  # should not raise
    assert "double" in registry


def test_registry_unregister():
    registry = PluginRegistry()
    registry.register(DoublePlugin())
    registry.unregister("double")
    assert "double" not in registry


def test_registry_unregister_missing_raises():
    registry = PluginRegistry()
    with pytest.raises(KeyError):
        registry.unregister("nonexistent")


def test_registry_get_missing_raises():
    registry = PluginRegistry()
    with pytest.raises(KeyError):
        registry.get("nonexistent")


def test_registry_len_and_names():
    registry = PluginRegistry()
    registry.register(DoublePlugin())
    registry.register(CalculatorPlugin())
    assert len(registry) == 2
    assert "calculator" in registry.names()
    assert "double" in registry.names()


def test_registry_schemas():
    registry = PluginRegistry()
    registry.register(DoublePlugin())
    schemas = registry.schemas()
    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"


def test_registry_register_many():
    registry = PluginRegistry()
    registry.register_many([DoublePlugin(), CalculatorPlugin()])
    assert len(registry) == 2


def test_registry_iter():
    registry = PluginRegistry()
    registry.register(DoublePlugin())
    plugins = list(registry)
    assert len(plugins) == 1
    assert plugins[0].name == "double"


# ---------------------------------------------------------------------------
# CalculatorPlugin tests
# ---------------------------------------------------------------------------

def test_calculator_basic_arithmetic():
    calc = CalculatorPlugin()
    assert calc.execute(expression="2 + 2").output == "4.0"
    assert calc.execute(expression="10 - 3").output == "7.0"
    assert calc.execute(expression="6 * 7").output == "42.0"
    assert calc.execute(expression="10 / 4").output == "2.5"


def test_calculator_power():
    calc = CalculatorPlugin()
    result = calc.execute(expression="2 ** 10")
    assert result.success is True
    assert result.output == "1024.0"


def test_calculator_constants():
    calc = CalculatorPlugin()
    result = calc.execute(expression="pi")
    assert result.success is True
    assert float(result.output) == pytest.approx(math.pi)


def test_calculator_floor_div_and_mod():
    calc = CalculatorPlugin()
    assert calc.execute(expression="17 // 5").output == "3.0"
    assert calc.execute(expression="17 % 5").output == "2.0"


def test_calculator_division_by_zero():
    calc = CalculatorPlugin()
    result = calc.execute(expression="1 / 0")
    assert result.success is False
    assert "zero" in result.error.lower()


def test_calculator_invalid_expression():
    calc = CalculatorPlugin()
    result = calc.execute(expression="import os")
    assert result.success is False


def test_calculator_empty_expression():
    calc = CalculatorPlugin()
    result = calc.execute()
    assert result.success is False
    assert result.error is not None


def test_calculator_name():
    assert CalculatorPlugin().name == "calculator"


def test_calculator_schema():
    schema = CalculatorPlugin().to_schema()
    assert "expression" in schema["function"]["parameters"]["properties"]


# ---------------------------------------------------------------------------
# WebSearchPlugin tests
# ---------------------------------------------------------------------------

def test_web_search_stub_returns_result():
    plugin = WebSearchPlugin()
    result = plugin.execute(query="Python tutorial")
    assert result.success is True
    assert "Python tutorial" in result.output
    assert result.data["query"] == "Python tutorial"
    assert len(result.data["results"]) >= 1


def test_web_search_empty_query():
    plugin = WebSearchPlugin()
    result = plugin.execute()
    assert result.success is False
    assert result.error is not None


def test_web_search_name():
    assert WebSearchPlugin().name == "web_search"


def test_web_search_schema():
    schema = WebSearchPlugin().to_schema()
    props = schema["function"]["parameters"]["properties"]
    assert "query" in props
    assert "max_results" in props
