"""Tests for core message types and Role enum."""

import pytest
from pawnlogic.core.message import Message, Role


def test_role_values():
    assert Role.SYSTEM == "system"
    assert Role.USER == "user"
    assert Role.ASSISTANT == "assistant"
    assert Role.TOOL == "tool"


def test_message_convenience_constructors():
    sys_msg = Message.system("Be concise.")
    assert sys_msg.role == Role.SYSTEM
    assert sys_msg.content == "Be concise."
    assert sys_msg.name is None

    user_msg = Message.user("Hello!")
    assert user_msg.role == Role.USER
    assert user_msg.content == "Hello!"

    asst_msg = Message.assistant("Hi there.")
    assert asst_msg.role == Role.ASSISTANT
    assert asst_msg.content == "Hi there."

    tool_msg = Message.tool("42", name="calculator")
    assert tool_msg.role == Role.TOOL
    assert tool_msg.content == "42"
    assert tool_msg.name == "calculator"


def test_message_to_dict_basic():
    msg = Message.user("Ping")
    d = msg.to_dict()
    assert d == {"role": "user", "content": "Ping"}


def test_message_to_dict_with_name():
    msg = Message.tool("result", name="my_tool")
    d = msg.to_dict()
    assert d["role"] == "tool"
    assert d["name"] == "my_tool"
    assert d["content"] == "result"


def test_message_metadata_default_empty():
    msg = Message.user("hi")
    assert msg.metadata == {}


def test_message_metadata_custom():
    msg = Message(role=Role.USER, content="test", metadata={"key": "value"})
    assert msg.metadata["key"] == "value"
