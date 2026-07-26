"""Validated delegation contracts and persistent model policy."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any

from core.file_store import atomic_write_text
from core.agent_events import AgentEvent, AgentEventKind
from core.runtime_context import current_runtime_context


_MODEL_REQUIREMENTS = frozenset(
    {"auto", "fast", "reasoning", "vision", "same", "same_provider"}
)
_CONTEXT_MODES = frozenset({"selected", "minimal", "none"})
_CAPABILITY_PROFILES = frozenset({"inherited", "read_only", "no_shell", "custom"})
_RESULT_STATUSES = frozenset(
    {"completed", "failed", "cancelled", "timed_out", "budget_exhausted", "rejected"}
)
_POLICY_MODES = frozenset({"auto", "same", "fast", "reasoning"})
_POLICY_FIELDS = frozenset(
    {
        "default_mode",
        "preferred_model",
        "allowed_models",
        "denied_models",
        "max_cost",
        "max_tokens",
        "max_concurrency",
    }
)
_MAX_TEXT_LENGTH = 32_768
_MAX_NAME_LENGTH = 256
_MAX_CONCURRENCY = 2


def publish_delegation_event(
    event_type: AgentEventKind,
    payload: dict[str, object],
    *,
    child_agent_id: str | None = None,
) -> None:
    """Publish structural delegation evidence without exposing task text."""
    context = current_runtime_context()
    if context is None or not context.session_id or not context.agent_id:
        return
    try:
        context.publish_event(
            AgentEvent(
                event_type=event_type,
                session_id=context.session_id,
                turn_id=context.active_turn_id,
                agent_id=child_agent_id or context.agent_id,
                parent_agent_id=(
                    context.agent_id if child_agent_id is not None else None
                ),
                payload=payload,
                metadata={"source": "delegation"},
            )
        )
    except Exception:
        return


def publish_routing_event(decision: Any) -> None:
    publish_delegation_event(
        AgentEventKind.POLICY_DECISION,
        {
            "policy": "delegated_model_routing",
            "decision": str(decision.reason),
            "approved": decision.model_alias is not None,
            "model_alias": decision.model_alias,
        },
    )


def publish_delegation_rejected(reason: str) -> None:
    publish_delegation_event(
        AgentEventKind.DELEGATION_RESULT,
        {"status": "rejected", "routing_reason": reason},
    )


def publish_delegation_started(
    task: Any,
    decision: Any,
    *,
    child_agent_id: str,
    effective_tokens: int,
) -> None:
    publish_delegation_event(
        AgentEventKind.DELEGATION_STARTED,
        {
            "status": "started",
            "model_alias": decision.model_alias,
            "routing_reason": decision.reason,
            "role": task.role,
            "capability_profile": task.capability_profile,
            "max_tokens": effective_tokens,
            "max_tool_calls": task.budget.max_tool_calls,
        },
        child_agent_id=child_agent_id,
    )


def publish_delegation_result(result: Any, child_agent_id: str) -> None:
    publish_delegation_event(
        AgentEventKind.DELEGATION_RESULT,
        {
            "status": result.status,
            "model_alias": result.model_alias,
            "routing_reason": result.routing_reason,
            "failure_codes": [failure.code for failure in result.failures],
            "usage": result.usage.to_dict(),
        },
        child_agent_id=child_agent_id,
    )


def default_delegation_policy_store() -> DelegationPolicyStore:
    """Resolve the policy store from the active Runtime Home."""
    import config.paths as path_config

    runtime_home = Path(
        os.environ.get("PAWNLOGIC_HOME") or path_config.PAWNLOGIC_HOME
    )
    return DelegationPolicyStore(runtime_home)


def _text(
    value: object,
    field_name: str,
    *,
    allow_empty: bool = False,
    max_length: int = _MAX_TEXT_LENGTH,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} exceeds {max_length} characters")
    return normalized


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _text(value, field_name, max_length=_MAX_NAME_LENGTH)


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _positive_int(value: object, field_name: str) -> int:
    result = _non_negative_int(value, field_name)
    if result == 0:
        raise ValueError(f"{field_name} must be positive")
    return result


def _optional_cost(value: object, field_name: str = "max_cost") -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number or None")
    result = float(value)
    if result < 0 or not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite and non-negative")
    return result


def _string_tuple(
    value: object,
    field_name: str,
    *,
    max_length: int = _MAX_NAME_LENGTH,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (tuple, list)):
        raise TypeError(f"{field_name} must be a tuple or list of strings")
    normalized = tuple(
        _text(item, field_name, max_length=max_length) for item in value
    )
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must not contain duplicates")
    return normalized


@dataclass(frozen=True)
class AgentBudget:
    max_tokens: int = 8192
    max_cost: float | None = None
    max_tool_calls: int = 15

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_tokens", _positive_int(self.max_tokens, "max_tokens"))
        object.__setattr__(self, "max_cost", _optional_cost(self.max_cost))
        object.__setattr__(
            self,
            "max_tool_calls",
            _non_negative_int(self.max_tool_calls, "max_tool_calls"),
        )

    def to_dict(self) -> dict[str, int | float | None]:
        return {
            "max_tokens": self.max_tokens,
            "max_cost": self.max_cost,
            "max_tool_calls": self.max_tool_calls,
        }


@dataclass(frozen=True)
class AgentTask:
    objective: str
    role: str = "general"
    instructions: str = ""
    model_requirement: str = "auto"
    model_alias: str | None = None
    context_mode: str = "selected"
    capability_profile: str = "inherited"
    allowed_tools: tuple[str, ...] = ()
    budget: AgentBudget = field(default_factory=AgentBudget)

    def __post_init__(self) -> None:
        object.__setattr__(self, "objective", _text(self.objective, "objective"))
        object.__setattr__(
            self,
            "role",
            _text(self.role, "role", max_length=_MAX_NAME_LENGTH),
        )
        object.__setattr__(
            self,
            "instructions",
            _text(self.instructions, "instructions", allow_empty=True),
        )
        requirement = _text(
            self.model_requirement,
            "model_requirement",
            max_length=_MAX_NAME_LENGTH,
        )
        if requirement not in _MODEL_REQUIREMENTS:
            raise ValueError(f"unsupported model_requirement: {requirement}")
        object.__setattr__(self, "model_requirement", requirement)
        object.__setattr__(
            self, "model_alias", _optional_text(self.model_alias, "model_alias")
        )
        context_mode = _text(
            self.context_mode, "context_mode", max_length=_MAX_NAME_LENGTH
        )
        if context_mode not in _CONTEXT_MODES:
            raise ValueError(f"unsupported context_mode: {context_mode}")
        object.__setattr__(self, "context_mode", context_mode)
        capability_profile = _text(
            self.capability_profile,
            "capability_profile",
            max_length=_MAX_NAME_LENGTH,
        )
        if capability_profile not in _CAPABILITY_PROFILES:
            raise ValueError(f"unsupported capability_profile: {capability_profile}")
        object.__setattr__(self, "capability_profile", capability_profile)
        object.__setattr__(
            self,
            "allowed_tools",
            _string_tuple(self.allowed_tools, "allowed_tools"),
        )
        if not isinstance(self.budget, AgentBudget):
            raise TypeError("budget must be an AgentBudget")

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "role": self.role,
            "instructions": self.instructions,
            "model_requirement": self.model_requirement,
            "model_alias": self.model_alias,
            "context_mode": self.context_mode,
            "capability_profile": self.capability_profile,
            "allowed_tools": list(self.allowed_tools),
            "budget": self.budget.to_dict(),
        }


@dataclass(frozen=True)
class AgentUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "prompt_tokens",
            _non_negative_int(self.prompt_tokens, "prompt_tokens"),
        )
        object.__setattr__(
            self,
            "completion_tokens",
            _non_negative_int(self.completion_tokens, "completion_tokens"),
        )
        object.__setattr__(
            self, "tool_calls", _non_negative_int(self.tool_calls, "tool_calls")
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "tool_calls": self.tool_calls,
        }


@dataclass(frozen=True)
class ArtifactRef:
    name: str
    path: str
    media_type: str = "application/octet-stream"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "name", _text(self.name, "name", max_length=_MAX_NAME_LENGTH)
        )
        path = _text(self.path, "path", max_length=4096).replace("\\", "/")
        parsed = PurePosixPath(path)
        if parsed.is_absolute() or ".." in parsed.parts:
            raise ValueError("path must be a relative artifact path")
        object.__setattr__(self, "path", str(parsed))
        object.__setattr__(
            self,
            "media_type",
            _text(self.media_type, "media_type", max_length=_MAX_NAME_LENGTH),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "path": self.path,
            "media_type": self.media_type,
        }


@dataclass(frozen=True)
class EvidenceRef:
    source: str
    reference: str
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source",
            _text(self.source, "source", max_length=_MAX_NAME_LENGTH),
        )
        object.__setattr__(
            self,
            "reference",
            _text(self.reference, "reference", max_length=4096),
        )
        object.__setattr__(
            self,
            "description",
            _text(self.description, "description", allow_empty=True),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "reference": self.reference,
            "description": self.description,
        }


@dataclass(frozen=True)
class FailureRecord:
    code: str
    message: str
    retryable: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "code", _text(self.code, "code", max_length=_MAX_NAME_LENGTH)
        )
        object.__setattr__(self, "message", _text(self.message, "message"))
        if not isinstance(self.retryable, bool):
            raise TypeError("retryable must be a boolean")

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


@dataclass(frozen=True)
class AgentResult:
    status: str
    summary: str
    model_alias: str | None = None
    routing_reason: str | None = None
    artifacts: tuple[ArtifactRef, ...] = ()
    evidence: tuple[EvidenceRef, ...] = ()
    failures: tuple[FailureRecord, ...] = ()
    usage: AgentUsage = field(default_factory=AgentUsage)

    def __post_init__(self) -> None:
        status = _text(self.status, "status", max_length=_MAX_NAME_LENGTH)
        if status not in _RESULT_STATUSES:
            raise ValueError(f"unsupported status: {status}")
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self, "summary", _text(self.summary, "summary", allow_empty=True)
        )
        object.__setattr__(
            self, "model_alias", _optional_text(self.model_alias, "model_alias")
        )
        object.__setattr__(
            self,
            "routing_reason",
            _optional_text(self.routing_reason, "routing_reason"),
        )
        object.__setattr__(
            self,
            "artifacts",
            self._typed_tuple(self.artifacts, ArtifactRef, "artifacts"),
        )
        object.__setattr__(
            self,
            "evidence",
            self._typed_tuple(self.evidence, EvidenceRef, "evidence"),
        )
        object.__setattr__(
            self,
            "failures",
            self._typed_tuple(self.failures, FailureRecord, "failures"),
        )
        if not isinstance(self.usage, AgentUsage):
            raise TypeError("usage must be an AgentUsage")

    @staticmethod
    def _typed_tuple(value: object, item_type: type, field_name: str) -> tuple:
        if isinstance(value, (str, bytes)) or not isinstance(value, (tuple, list)):
            raise TypeError(f"{field_name} must be a tuple or list")
        normalized = tuple(value)
        if not all(isinstance(item, item_type) for item in normalized):
            raise TypeError(f"{field_name} must contain only {item_type.__name__}")
        return normalized

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "model_alias": self.model_alias,
            "routing_reason": self.routing_reason,
            "artifacts": [item.to_dict() for item in self.artifacts],
            "evidence": [item.to_dict() for item in self.evidence],
            "failures": [item.to_dict() for item in self.failures],
            "usage": self.usage.to_dict(),
        }


@dataclass(frozen=True)
class DelegationModelPolicy:
    default_mode: str = "auto"
    preferred_model: str | None = None
    allowed_models: tuple[str, ...] = ()
    denied_models: tuple[str, ...] = ()
    max_cost: float | None = None
    max_tokens: int = 8192
    max_concurrency: int = 1

    def __post_init__(self) -> None:
        mode = _text(self.default_mode, "default_mode", max_length=_MAX_NAME_LENGTH)
        if mode not in _POLICY_MODES:
            raise ValueError(f"unsupported default_mode: {mode}")
        object.__setattr__(self, "default_mode", mode)
        object.__setattr__(
            self,
            "preferred_model",
            _optional_text(self.preferred_model, "preferred_model"),
        )
        object.__setattr__(
            self,
            "allowed_models",
            _string_tuple(self.allowed_models, "allowed_models"),
        )
        object.__setattr__(
            self,
            "denied_models",
            _string_tuple(self.denied_models, "denied_models"),
        )
        object.__setattr__(self, "max_cost", _optional_cost(self.max_cost))
        object.__setattr__(self, "max_tokens", _positive_int(self.max_tokens, "max_tokens"))
        concurrency = _positive_int(self.max_concurrency, "max_concurrency")
        if concurrency > _MAX_CONCURRENCY:
            raise ValueError(
                f"max_concurrency must not exceed {_MAX_CONCURRENCY}"
            )
        object.__setattr__(self, "max_concurrency", concurrency)

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_mode": self.default_mode,
            "preferred_model": self.preferred_model,
            "allowed_models": list(self.allowed_models),
            "denied_models": list(self.denied_models),
            "max_cost": self.max_cost,
            "max_tokens": self.max_tokens,
            "max_concurrency": self.max_concurrency,
        }


class DelegationPolicyStore:
    """Persist delegation model policy below one Runtime Home."""

    def __init__(self, runtime_home: str | Path) -> None:
        self.runtime_home = Path(runtime_home).expanduser()
        self.path = self.runtime_home / "delegation" / "policy.json"

    def load(self) -> DelegationModelPolicy:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("policy payload must be an object")
            values = {name: payload[name] for name in _POLICY_FIELDS if name in payload}
            return DelegationModelPolicy(**values)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            return DelegationModelPolicy()

    def save(self, policy: DelegationModelPolicy) -> DelegationModelPolicy:
        if not isinstance(policy, DelegationModelPolicy):
            raise TypeError("policy must be a DelegationModelPolicy")
        text = json.dumps(policy.to_dict(), indent=2, sort_keys=True) + "\n"
        atomic_write_text(self.path, text, mode=0o600)
        return policy

    def update(self, **changes: Any) -> DelegationModelPolicy:
        unknown = set(changes) - _POLICY_FIELDS
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"unknown policy field: {names}")
        updated = replace(self.load(), **changes)
        return self.save(updated)


__all__ = [
    "AgentBudget",
    "AgentResult",
    "AgentTask",
    "AgentUsage",
    "ArtifactRef",
    "DelegationModelPolicy",
    "DelegationPolicyStore",
    "EvidenceRef",
    "FailureRecord",
    "default_delegation_policy_store",
    "publish_delegation_event",
    "publish_delegation_rejected",
    "publish_delegation_result",
    "publish_delegation_started",
    "publish_routing_event",
]
