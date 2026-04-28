"""Message and Role types for conversation history."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(str, Enum):
    """Conversation participant roles."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class Message:
    """A single message in a conversation thread.

    Attributes:
        role: Who authored this message.
        content: Text content of the message.
        name: Optional sender name (e.g. tool name for ``Role.TOOL`` messages).
        metadata: Arbitrary extra data attached to the message.
    """

    role: Role
    content: str
    name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise the message to a plain dictionary."""
        data: dict[str, Any] = {"role": self.role.value, "content": self.content}
        if self.name is not None:
            data["name"] = self.name
        return data

    @classmethod
    def system(cls, content: str) -> "Message":
        """Convenience constructor for a system message."""
        return cls(role=Role.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> "Message":
        """Convenience constructor for a user message."""
        return cls(role=Role.USER, content=content)

    @classmethod
    def assistant(cls, content: str) -> "Message":
        """Convenience constructor for an assistant message."""
        return cls(role=Role.ASSISTANT, content=content)

    @classmethod
    def tool(cls, content: str, name: str) -> "Message":
        """Convenience constructor for a tool-result message."""
        return cls(role=Role.TOOL, content=content, name=name)
