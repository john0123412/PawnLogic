"""Tests for the Agent and Orchestrator."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from pawnlogic.core.agent import Agent
from pawnlogic.core.message import Message, Role
from pawnlogic.core.orchestrator import Orchestrator
from pawnlogic.plugins.base import Plugin, PluginResult
from pawnlogic.plugins.registry import PluginRegistry
from pawnlogic.providers.base import LLMProvider, LLMResponse


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class FixedProvider(LLMProvider):
    """Provider that always returns a fixed reply."""

    def __init__(self, reply: str = "fixed reply") -> None:
        self._reply = reply

    @property
    def name(self) -> str:
        return "fixed"

    def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        return LLMResponse(content=self._reply, model=model)


class UpperCasePlugin(Plugin):
    """Plugin that upper-cases input text."""

    @property
    def name(self) -> str:
        return "uppercase"

    @property
    def description(self) -> str:
        return "Converts text to upper-case."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"text": {"type": "string", "description": "Text to upper-case."}}

    def execute(self, **kwargs: Any) -> PluginResult:
        text = kwargs.get("text", "")
        return PluginResult(success=True, output=text.upper())


# ---------------------------------------------------------------------------
# Agent tests
# ---------------------------------------------------------------------------

def make_agent(**kwargs) -> Agent:
    defaults = dict(provider=FixedProvider(), model="test-model")
    defaults.update(kwargs)
    return Agent(**defaults)


def test_agent_provider_and_model():
    agent = make_agent()
    assert agent.provider.name == "fixed"
    assert agent.model == "test-model"


def test_agent_chat_returns_response():
    agent = make_agent()
    response = agent.chat("Hello")
    assert isinstance(response, LLMResponse)
    assert response.content == "fixed reply"


def test_agent_chat_appends_to_history():
    agent = make_agent()
    agent.chat("Hi")
    history = agent.history
    roles = [m.role for m in history]
    assert Role.USER in roles
    assert Role.ASSISTANT in roles


def test_agent_system_prompt_prepended():
    agent = make_agent(system_prompt="You are a bot.")
    history = agent.history
    assert history[0].role == Role.SYSTEM
    assert history[0].content == "You are a bot."


def test_agent_reset_clears_history_keeps_system():
    agent = make_agent(system_prompt="sys")
    agent.chat("hi")
    agent.reset()
    assert len(agent.history) == 1
    assert agent.history[0].role == Role.SYSTEM


def test_agent_reset_without_system_empties_history():
    agent = make_agent()
    agent.chat("hi")
    agent.reset()
    assert agent.history == []


def test_agent_use_plugin():
    registry = PluginRegistry()
    registry.register(UpperCasePlugin())
    agent = make_agent(plugin_registry=registry)
    result = agent.use_plugin("uppercase", text="hello world")
    assert result.success is True
    assert result.output == "HELLO WORLD"


def test_agent_use_plugin_adds_tool_message():
    registry = PluginRegistry()
    registry.register(UpperCasePlugin())
    agent = make_agent(plugin_registry=registry)
    agent.use_plugin("uppercase", text="test")
    tool_msgs = [m for m in agent.history if m.role == Role.TOOL]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].name == "uppercase"


def test_agent_use_plugin_unknown_raises():
    agent = make_agent()
    with pytest.raises(KeyError):
        agent.use_plugin("nonexistent")


def test_agent_chat_async():
    agent = make_agent()
    response = asyncio.run(agent.chat_async("async hi"))
    assert response.content == "fixed reply"


def test_agent_plugin_registry_empty_by_default():
    agent = make_agent()
    assert len(agent.plugin_registry) == 0


# ---------------------------------------------------------------------------
# Orchestrator tests
# ---------------------------------------------------------------------------

def make_orchestrator_with_agents() -> Orchestrator:
    orc = Orchestrator()
    orc.register("alpha", make_agent(provider=FixedProvider("from alpha")))
    orc.register("beta", make_agent(provider=FixedProvider("from beta")))
    return orc


def test_orchestrator_register_and_get():
    orc = Orchestrator()
    agent = make_agent()
    orc.register("myagent", agent)
    assert "myagent" in orc
    assert orc.get("myagent") is agent


def test_orchestrator_register_duplicate_raises():
    orc = Orchestrator()
    orc.register("a", make_agent())
    with pytest.raises(ValueError, match="already registered"):
        orc.register("a", make_agent())


def test_orchestrator_replace():
    orc = Orchestrator()
    orc.register("a", make_agent())
    orc.replace("a", make_agent())  # should not raise


def test_orchestrator_unregister():
    orc = Orchestrator()
    orc.register("a", make_agent())
    orc.unregister("a")
    assert "a" not in orc


def test_orchestrator_unregister_missing_raises():
    orc = Orchestrator()
    with pytest.raises(KeyError):
        orc.unregister("nope")


def test_orchestrator_get_missing_raises():
    orc = Orchestrator()
    with pytest.raises(KeyError):
        orc.get("nope")


def test_orchestrator_names():
    orc = make_orchestrator_with_agents()
    assert orc.names() == ["alpha", "beta"]


def test_orchestrator_len():
    orc = make_orchestrator_with_agents()
    assert len(orc) == 2


def test_orchestrator_chat_routes_to_correct_agent():
    orc = make_orchestrator_with_agents()
    response = orc.chat("alpha", "hi")
    assert response.content == "from alpha"

    response = orc.chat("beta", "hi")
    assert response.content == "from beta"


def test_orchestrator_broadcast():
    orc = make_orchestrator_with_agents()
    responses = orc.broadcast("hello everyone")
    assert set(responses.keys()) == {"alpha", "beta"}
    assert responses["alpha"].content == "from alpha"
    assert responses["beta"].content == "from beta"


def test_orchestrator_chat_async():
    orc = make_orchestrator_with_agents()
    response = asyncio.run(orc.chat_async("alpha", "async msg"))
    assert response.content == "from alpha"
