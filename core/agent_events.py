"""Versioned, immutable Agent Event contracts and synchronous publication."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from enum import Enum
import json
import math
import re
import threading
from types import MappingProxyType
from typing import Protocol, TypeAlias, cast


AGENT_EVENT_SCHEMA_VERSION = 1
REDACTED_SECRET = "[REDACTED_SECRET]"

# Metadata is intentionally narrower than payload data. These fields support
# ordering, correlation, and renderer hints without becoming a second payload.
ALLOWED_METADATA_KEYS = frozenset(
    {
        "correlation_id",
        "created_at",
        "duration_ms",
        "finish_reason",
        "model",
        "provider",
        "request_id",
        "sequence",
        "source",
        "span_id",
        "task_id",
        "timestamp",
        "trace_id",
    }
)
AGENT_EVENT_METADATA_KEYS = ALLOWED_METADATA_KEYS

_EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "event_type",
        "session_id",
        "turn_id",
        "agent_id",
        "parent_agent_id",
        "payload",
        "metadata",
    }
)
_SENSITIVE_KEYS = frozenset(
    {
        "access_key",
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "auth_token",
        "authorization",
        "bearer_token",
        "client_secret",
        "cookie",
        "credential",
        "credentials",
        "password",
        "passwd",
        "private_key",
        "refresh_token",
        "secret",
        "session_token",
        "token",
    }
)
_SENSITIVE_KEY_SUFFIXES = (
    "_access_key",
    "_access_token",
    "_api_key",
    "_auth_token",
    "_client_secret",
    "_password",
    "_private_key",
    "_refresh_token",
    "_session_token",
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b("
    r"api[_-]?key|access[_-]?key|access[_-]?token|auth(?:orization)?|"
    r"bearer[_-]?token|client[_-]?secret|cookie|credentials?|password|passwd|"
    r"private[_-]?key|refresh[_-]?token|secret|session[_-]?token|token|"
    r"(?:OPENAI|ANTHROPIC|DEEPSEEK|AZURE|GOOGLE|GEMINI|MISTRAL|OPENROUTER|"
    r"TOGETHER|DASHSCOPE|MOONSHOT|ZHIPU|XAI)[A-Z0-9_]*(?:API_)?KEY"
    r")(\s*[:=]\s*)['\"]?([^\s,;'\"&]+)"
)
_AUTHORIZATION_RE = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+")
_KNOWN_SECRET_RE = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{20,}|"
    r"sk-(?:proj-|svcacct-|live-)?[A-Za-z0-9_-]{12,}|"
    r"ghp_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{30,}|"
    r"tp-[a-z0-9]{30,}|"
    r"AIza[A-Za-z0-9_-]{35}|"
    r"AKIA[0-9A-Z]{16}|"
    r"ASIA[0-9A-Z]{16}"
)
_URL_CREDENTIAL_RE = re.compile(
    r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@]+@"
)
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
    r"-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)


class AgentEventKind(str, Enum):
    """Stable event kinds in schema version 1."""

    TURN_STARTED = "turn.started"
    TURN_COMPLETED = "turn.completed"
    TURN_FAILED = "turn.failed"
    TURN_CANCELLED = "turn.cancelled"
    TEXT_DELTA = "text.delta"
    REASONING_VISIBILITY = "reasoning.visibility"
    TOOL_STARTED = "tool.started"
    TOOL_RESULT = "tool.result"
    RETRIEVAL_EVIDENCE = "retrieval.evidence"
    DELEGATION_STARTED = "delegation.started"
    DELEGATION_RESULT = "delegation.result"
    POLICY_DECISION = "policy.decision"
    USAGE = "usage"
    ERROR = "error"


EventKind = AgentEventKind


def _normalized_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalized_key(key)
    return normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_KEY_SUFFIXES)


def _redact_text(value: str) -> str:
    value = _PRIVATE_KEY_RE.sub(REDACTED_SECRET, value)
    value = _SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED_SECRET}",
        value,
    )
    value = _AUTHORIZATION_RE.sub(
        lambda match: f"{match.group(1)} {REDACTED_SECRET}",
        value,
    )
    value = _KNOWN_SECRET_RE.sub(REDACTED_SECRET, value)
    return _URL_CREDENTIAL_RE.sub(
        lambda match: f"{match.group(1)}{REDACTED_SECRET}@",
        value,
    )


def redact_secrets(value: object) -> object:
    """Return a recursively redacted JSON-like copy of ``value``."""
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, Mapping):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("event mappings must use string keys")
            redacted[key] = (
                REDACTED_SECRET if _is_sensitive_key(key) else redact_secrets(item)
            )
        return redacted
    if isinstance(value, (list, tuple)):
        return [redact_secrets(item) for item in value]
    return value


def _freeze_json(value: object, field_name: str) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_name} must not contain non-finite numbers")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key in sorted(value):
            if not isinstance(key, str):
                raise TypeError(f"{field_name} mappings must use string keys")
            frozen[key] = _freeze_json(value[key], field_name)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, field_name) for item in value)
    raise TypeError(f"{field_name} must contain only JSON-compatible values")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return _redact_text(normalized)


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


@dataclass(frozen=True, slots=True)
class AgentEvent:
    """One immutable, redacted event crossing the Agent Event boundary."""

    event_type: AgentEventKind | str
    session_id: str
    turn_id: str
    agent_id: str
    parent_agent_id: str | None = None
    payload: Mapping[str, object] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)
    schema_version: int = AGENT_EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or not isinstance(
            self.schema_version, int
        ):
            raise TypeError("schema_version must be an integer")
        if self.schema_version != AGENT_EVENT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported Agent Event schema version: {self.schema_version}"
            )
        try:
            event_type = AgentEventKind(self.event_type)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"unsupported Agent Event type: {self.event_type}") from exc
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a mapping")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")

        safe_payload = redact_secrets(self.payload)
        safe_metadata: Mapping[str, object] = {
            key: value
            for key, value in self.metadata.items()
            if isinstance(key, str) and key in ALLOWED_METADATA_KEYS
        }
        safe_metadata = cast(Mapping[str, object], redact_secrets(safe_metadata))

        object.__setattr__(self, "event_type", event_type)
        object.__setattr__(self, "session_id", _required_text(self.session_id, "session_id"))
        object.__setattr__(self, "turn_id", _required_text(self.turn_id, "turn_id"))
        object.__setattr__(self, "agent_id", _required_text(self.agent_id, "agent_id"))
        object.__setattr__(
            self,
            "parent_agent_id",
            _optional_text(self.parent_agent_id, "parent_agent_id"),
        )
        object.__setattr__(self, "payload", _freeze_json(safe_payload, "payload"))
        object.__setattr__(
            self,
            "metadata",
            _freeze_json(safe_metadata, "metadata"),
        )

    @property
    def kind(self) -> AgentEventKind:
        """Return the typed event kind."""
        return AgentEventKind(self.event_type)

    def to_dict(self) -> dict[str, object]:
        """Return a detached, redacted dictionary in schema-version shape."""
        event = {
            "schema_version": self.schema_version,
            "event_type": cast(AgentEventKind, self.event_type).value,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "agent_id": self.agent_id,
            "parent_agent_id": self.parent_agent_id,
            "payload": _thaw_json(self.payload),
            "metadata": _thaw_json(self.metadata),
        }
        return dict(cast(Mapping[str, object], redact_secrets(event)))

    def to_json(self) -> str:
        """Serialize with canonical key ordering and no insignificant spaces."""
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> AgentEvent:
        """Validate and construct one event from its public dictionary shape."""
        if not isinstance(data, Mapping):
            raise TypeError("Agent Event data must be a mapping")
        unknown = set(data) - _EVENT_FIELDS
        if unknown:
            names = ", ".join(sorted(str(name) for name in unknown))
            raise ValueError(f"unknown Agent Event fields: {names}")
        try:
            return cls(
                schema_version=cast(int, data["schema_version"]),
                event_type=cast(AgentEventKind | str, data["event_type"]),
                session_id=cast(str, data["session_id"]),
                turn_id=cast(str, data["turn_id"]),
                agent_id=cast(str, data["agent_id"]),
                parent_agent_id=cast(str | None, data.get("parent_agent_id")),
                payload=cast(Mapping[str, object], data.get("payload", {})),
                metadata=cast(Mapping[str, object], data.get("metadata", {})),
            )
        except KeyError as exc:
            raise ValueError(f"missing Agent Event field: {exc.args[0]}") from exc

    @classmethod
    def from_json(cls, value: str) -> AgentEvent:
        """Parse one JSON object through the versioned event contract."""
        if not isinstance(value, str):
            raise TypeError("Agent Event JSON must be a string")
        data = json.loads(value)
        if not isinstance(data, Mapping):
            raise ValueError("Agent Event JSON must contain an object")
        return cls.from_dict(data)


AgentEventSubscriber: TypeAlias = Callable[[AgentEvent], None]


class AgentEventSink(Protocol):
    """Synchronous destination for immutable Agent Events."""

    def publish(self, event: AgentEvent) -> None: ...


class AgentEventStream(Protocol):
    """Subscription surface exposed to synchronous event consumers."""

    def subscribe(
        self,
        subscriber: AgentEventSubscriber,
    ) -> Callable[[], None]: ...


class AgentEventPublisher:
    """Small ordered, synchronous publisher with snapshot dispatch semantics."""

    def __init__(
        self,
        subscribers: Iterable[AgentEventSubscriber] = (),
    ) -> None:
        self._subscribers = list(subscribers)
        self._lock = threading.RLock()
        if any(not callable(subscriber) for subscriber in self._subscribers):
            raise TypeError("Agent Event subscribers must be callable")

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def subscribe(
        self,
        subscriber: AgentEventSubscriber,
    ) -> Callable[[], None]:
        if not callable(subscriber):
            raise TypeError("Agent Event subscriber must be callable")
        with self._lock:
            self._subscribers.append(subscriber)
        active = True

        def unsubscribe() -> None:
            nonlocal active
            if active:
                self.unsubscribe(subscriber)
                active = False

        return unsubscribe

    def unsubscribe(self, subscriber: AgentEventSubscriber) -> None:
        with self._lock, suppress(ValueError):
            self._subscribers.remove(subscriber)

    def publish(self, event: AgentEvent) -> None:
        if not isinstance(event, AgentEvent):
            raise TypeError("event must be an AgentEvent")
        # Subscribers may write to stdout/JSON sinks, so keep dispatch ordered
        # even when concurrent child workers publish at the same time.
        with self._lock:
            for subscriber in tuple(self._subscribers):
                with suppress(Exception):
                    subscriber(event)

    def emit(self, event: AgentEvent) -> None:
        """Compatibility spelling for callers that expose an ``emit`` sink."""
        self.publish(event)


SynchronousAgentEventPublisher = AgentEventPublisher


__all__ = [
    "AGENT_EVENT_METADATA_KEYS",
    "AGENT_EVENT_SCHEMA_VERSION",
    "ALLOWED_METADATA_KEYS",
    "REDACTED_SECRET",
    "AgentEvent",
    "AgentEventKind",
    "AgentEventPublisher",
    "AgentEventSink",
    "AgentEventStream",
    "AgentEventSubscriber",
    "EventKind",
    "SynchronousAgentEventPublisher",
    "redact_secrets",
]
