"""Structured context contracts and deterministic bounded selection."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from core.message_history import repair_dangling_tool_calls


CONTEXT_STATE_VERSION = 1
SUMMARY_VERSION = 1
CONTEXT_ENVELOPE_VERSION = 1
CONTEXT_STATE_MESSAGE_PREFIX = "[PawnLogic Context State v1]\n"
_CONTEXT_MODES = frozenset({"selected", "minimal", "none"})


def _version(value: object, field_name: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    minimum = 0 if allow_zero else 1
    if value < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    return value


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    return value.strip()


def _text_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (tuple, list)):
        raise TypeError(f"{field_name} must be a tuple or list of strings")
    normalized = tuple(_text(item, field_name) for item in value)
    if any(not item for item in normalized):
        raise ValueError(f"{field_name} must not contain empty values")
    return normalized


def _positive_chars(value: object, field_name: str) -> int:
    result = _version(value, field_name)
    return result


def _value_chars(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    if isinstance(value, (dict, list, tuple)):
        try:
            return len(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        except (TypeError, ValueError):
            pass
    return len(str(value))


def _message_chars(message: Mapping[str, Any]) -> int:
    total = _value_chars(message.get("content"))
    total += _value_chars(message.get("reasoning_content"))
    calls = message.get("tool_calls") or ()
    if isinstance(calls, Sequence) and not isinstance(calls, (str, bytes)):
        for call in calls:
            if not isinstance(call, Mapping):
                continue
            function = call.get("function")
            if isinstance(function, Mapping):
                total += _value_chars(function.get("arguments"))
    return total


def _turn_groups(messages: Sequence[Mapping[str, Any]]) -> list[tuple[int, ...]]:
    starts = [
        index for index, message in enumerate(messages) if message.get("role") == "user"
    ]
    groups: list[tuple[int, ...]] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(messages)
        groups.append(tuple(range(start, end)))
    return groups


def _tool_group(
    messages: Sequence[Mapping[str, Any]],
    index: int,
) -> tuple[int, ...]:
    """Return the complete assistant/Tool result group containing ``index``."""
    for assistant_index in range(index, -1, -1):
        assistant = messages[assistant_index]
        calls = assistant.get("tool_calls") or ()
        if not calls:
            if assistant_index < index and assistant.get("role") != "tool":
                break
            continue
        call_ids = {
            str(call.get("id"))
            for call in calls
            if isinstance(call, Mapping) and call.get("id")
        }
        indexes = [assistant_index]
        result_ids: set[str] = set()
        for result_index in range(assistant_index + 1, len(messages)):
            result = messages[result_index]
            if result.get("role") != "tool":
                break
            indexes.append(result_index)
            if result.get("tool_call_id"):
                result_ids.add(str(result["tool_call_id"]))
        if call_ids and call_ids.issubset(result_ids) and index in indexes:
            return tuple(indexes)
    return (index,)


def _without_orphan_tools(
    messages: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    repaired = repair_dangling_tool_calls(list(messages))
    expected: set[str] = set()
    result: list[dict[str, Any]] = []
    for message in repaired:
        if message.get("role") == "assistant":
            expected = {
                str(call.get("id"))
                for call in (message.get("tool_calls") or ())
                if isinstance(call, Mapping) and call.get("id")
            }
            result.append(message)
            continue
        if message.get("role") == "tool":
            tool_call_id = str(message.get("tool_call_id") or "")
            if tool_call_id in expected:
                result.append(message)
                expected.discard(tool_call_id)
            continue
        expected.clear()
        result.append(message)
    return tuple(result)


def _bounded_messages(
    messages: tuple[dict[str, Any], ...],
    *,
    budget: int,
    state_chars: int,
    include_system: bool = True,
    require_protected: bool = True,
    context_refs: tuple[str, ...] = (),
) -> tuple[dict[str, Any], ...]:
    selected: set[int] = set()
    selected_chars = state_chars

    def add(indexes: Sequence[int], *, required: bool) -> None:
        nonlocal selected_chars
        new_indexes = tuple(index for index in indexes if index not in selected)
        added_chars = sum(_message_chars(messages[index]) for index in new_indexes)
        if required or selected_chars + added_chars <= budget:
            selected.update(new_indexes)
            selected_chars += added_chars

    system_indexes = tuple(
        index
        for index, message in enumerate(messages)
        if include_system and message.get("role") == "system"
    )
    add(system_indexes, required=require_protected)

    turns = _turn_groups(messages)
    if turns:
        add(turns[0], required=require_protected)

    requested_refs = frozenset(context_refs)
    for index, message in enumerate(messages):
        message_refs: tuple[str, ...] = ()
        context_ref = message.get("_context_ref")
        if isinstance(context_ref, str):
            message_refs = (context_ref,)
        context_ref_list = message.get("_context_refs")
        if isinstance(context_ref_list, (tuple, list)):
            message_refs += tuple(
                item for item in context_ref_list if isinstance(item, str)
            )
        if requested_refs.intersection(message_refs):
            add(_tool_group(messages, index), required=require_protected)

    for index, message in enumerate(messages):
        if message.get("_pinned") is True:
            add(_tool_group(messages, index), required=require_protected)

    for turn in reversed(turns[1:]):
        add(turn, required=False)

    selected_messages = [messages[index] for index in sorted(selected)]
    return _without_orphan_tools(selected_messages)


@dataclass(frozen=True)
class ContextState:
    """Versioned task state retained independently from prose summaries."""

    goal: str = ""
    constraints: tuple[str, ...] = ()
    facts: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    failed_attempts: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    current_phase: str = ""
    next_actions: tuple[str, ...] = ()
    version: int = CONTEXT_STATE_VERSION
    summary_version: int = SUMMARY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "goal", _text(self.goal, "goal"))
        object.__setattr__(
            self, "constraints", _text_tuple(self.constraints, "constraints")
        )
        object.__setattr__(self, "facts", _text_tuple(self.facts, "facts"))
        object.__setattr__(
            self, "decisions", _text_tuple(self.decisions, "decisions")
        )
        object.__setattr__(
            self, "artifacts", _text_tuple(self.artifacts, "artifacts")
        )
        object.__setattr__(
            self,
            "failed_attempts",
            _text_tuple(self.failed_attempts, "failed_attempts"),
        )
        object.__setattr__(
            self,
            "open_questions",
            _text_tuple(self.open_questions, "open_questions"),
        )
        object.__setattr__(
            self, "current_phase", _text(self.current_phase, "current_phase")
        )
        object.__setattr__(
            self, "next_actions", _text_tuple(self.next_actions, "next_actions")
        )
        version = _version(self.version, "version")
        if version != CONTEXT_STATE_VERSION:
            raise ValueError(f"unsupported context state version: {version}")
        object.__setattr__(self, "version", version)
        object.__setattr__(
            self,
            "summary_version",
            _version(self.summary_version, "summary_version", allow_zero=True),
        )

    @property
    def needs_summary_regeneration(self) -> bool:
        return self.summary_version != SUMMARY_VERSION

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.goal,
                self.constraints,
                self.facts,
                self.decisions,
                self.artifacts,
                self.failed_attempts,
                self.open_questions,
                self.current_phase,
                self.next_actions,
            )
        )

    def prompt_block(self) -> str:
        """Render state in a deterministic, versioned prompt representation."""
        if self.is_empty:
            return ""
        lines = [
            f"[Structured Context v{self.version}; summary v{self.summary_version}]",
        ]
        fields: tuple[tuple[str, str | tuple[str, ...]], ...] = (
            ("Goal", self.goal),
            ("Constraints", self.constraints),
            ("Facts", self.facts),
            ("Decisions", self.decisions),
            ("Artifacts", self.artifacts),
            ("Failed attempts", self.failed_attempts),
            ("Open questions", self.open_questions),
            ("Current phase", self.current_phase),
            ("Next actions", self.next_actions),
        )
        for label, value in fields:
            if isinstance(value, tuple):
                if value:
                    lines.append(f"{label}:")
                    lines.extend(f"- {item}" for item in value)
            elif value:
                lines.append(f"{label}: {value}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "summary_version": self.summary_version,
            "goal": self.goal,
            "constraints": list(self.constraints),
            "facts": list(self.facts),
            "decisions": list(self.decisions),
            "artifacts": list(self.artifacts),
            "failed_attempts": list(self.failed_attempts),
            "open_questions": list(self.open_questions),
            "current_phase": self.current_phase,
            "next_actions": list(self.next_actions),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ContextState:
        if not isinstance(data, Mapping):
            raise TypeError("context state must be a mapping")
        return cls(
            goal=cast(str, data.get("goal", "")),
            constraints=cast(tuple[str, ...], data.get("constraints", ())),
            facts=cast(tuple[str, ...], data.get("facts", ())),
            decisions=cast(tuple[str, ...], data.get("decisions", ())),
            artifacts=cast(tuple[str, ...], data.get("artifacts", ())),
            failed_attempts=cast(
                tuple[str, ...],
                data.get("failed_attempts", ()),
            ),
            open_questions=cast(
                tuple[str, ...],
                data.get("open_questions", ()),
            ),
            current_phase=cast(str, data.get("current_phase", "")),
            next_actions=cast(
                tuple[str, ...],
                data.get("next_actions", ()),
            ),
            version=cast(int, data.get("version", CONTEXT_STATE_VERSION)),
            summary_version=cast(int, data.get("summary_version", 0)),
        )


def is_context_state_message(message: Mapping[str, Any]) -> bool:
    return (
        message.get("role") == "assistant"
        and str(message.get("content") or "").startswith(
            CONTEXT_STATE_MESSAGE_PREFIX
        )
    )


def context_state_message(state: ContextState) -> dict[str, Any]:
    """Build the versioned pinned carrier supported by existing persistence."""
    if not isinstance(state, ContextState):
        raise TypeError("state must be a ContextState")
    payload = json.dumps(
        state.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "role": "assistant",
        "content": CONTEXT_STATE_MESSAGE_PREFIX + payload,
        "_pinned": True,
    }


def context_state_from_messages(
    messages: Sequence[Mapping[str, Any]],
) -> ContextState | None:
    """Read the newest valid structured-state carrier from persisted messages."""
    for message in reversed(messages):
        if not is_context_state_message(message):
            continue
        content = str(message.get("content") or "")
        try:
            payload = json.loads(content[len(CONTEXT_STATE_MESSAGE_PREFIX) :])
            return ContextState.from_dict(payload)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return None


def without_context_state_messages(
    messages: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        dict(message)
        for message in messages
        if not is_context_state_message(message)
    ]


def replace_context_state_message(
    messages: Sequence[Mapping[str, Any]],
    state: ContextState,
) -> list[dict[str, Any]]:
    """Replace old carriers and keep the newest state after the first task Turn."""
    result = without_context_state_messages(messages)
    turns = _turn_groups(result)
    insert_at = turns[0][-1] + 1 if turns and turns[0] else min(1, len(result))
    result.insert(insert_at, context_state_message(state))
    return result


def replace_context_state_from_history(
    messages: Sequence[Mapping[str, Any]],
    *,
    summary: str,
    current_phase: str,
) -> list[dict[str, Any]]:
    return replace_context_state_message(
        messages,
        context_state_from_history(
            messages,
            summary=summary,
            current_phase=current_phase,
        ),
    )


@dataclass(frozen=True)
class ContextEnvelope:
    """A bounded, versioned projection of parent messages and task state."""

    state: ContextState
    messages: tuple[dict[str, Any], ...]
    char_count: int
    trimmed: bool = False
    over_budget: bool = False
    dropped_messages: int = 0
    context_refs: tuple[str, ...] = ()
    version: int = CONTEXT_ENVELOPE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "state": self.state.to_dict(),
            "messages": copy.deepcopy(list(self.messages)),
            "char_count": self.char_count,
            "trimmed": self.trimmed,
            "over_budget": self.over_budget,
            "dropped_messages": self.dropped_messages,
            "context_refs": list(self.context_refs),
        }


class ContextManager:
    """Build bounded context through one side-effect-free Interface."""

    def __init__(self, *, max_chars: int, trim_to: int) -> None:
        self._max_chars = _positive_chars(max_chars, "max_chars")
        self._trim_to = _positive_chars(trim_to, "trim_to")
        if self._trim_to > self._max_chars:
            raise ValueError("trim_to must not exceed max_chars")

    def build(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        state: ContextState | None = None,
        context_refs: Sequence[str] = (),
    ) -> ContextEnvelope:
        normalized_state = state if state is not None else ContextState()
        if not isinstance(normalized_state, ContextState):
            raise TypeError("state must be a ContextState")
        normalized_refs = _text_tuple(context_refs, "context_refs")
        original_count = len(messages)
        copied_messages = _without_orphan_tools(
            [copy.deepcopy(dict(message)) for message in messages]
        )
        state_chars = len(normalized_state.prompt_block())
        char_count = state_chars + sum(
            _message_chars(message) for message in copied_messages
        )
        if char_count > self._max_chars:
            copied_messages = _bounded_messages(
                copied_messages,
                budget=self._trim_to,
                state_chars=state_chars,
            )
            trimmed_char_count = state_chars + sum(
                _message_chars(message) for message in copied_messages
            )
            return ContextEnvelope(
                state=normalized_state,
                messages=copied_messages,
                char_count=trimmed_char_count,
                trimmed=True,
                over_budget=trimmed_char_count > self._trim_to,
                dropped_messages=original_count - len(copied_messages),
                context_refs=normalized_refs,
            )
        return ContextEnvelope(
            state=normalized_state,
            messages=copied_messages,
            char_count=char_count,
            trimmed=len(copied_messages) < original_count,
            dropped_messages=original_count - len(copied_messages),
            context_refs=normalized_refs,
        )

    def select_parent_context(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        state: ContextState | None = None,
        context_mode: str = "selected",
        context_refs: Sequence[str] = (),
    ) -> ContextEnvelope:
        """Select a child-safe parent projection within ``trim_to``."""
        normalized_mode = _text(context_mode, "context_mode")
        if normalized_mode not in _CONTEXT_MODES:
            raise ValueError(f"unsupported context_mode: {normalized_mode}")
        normalized_state = state if state is not None else ContextState()
        if not isinstance(normalized_state, ContextState):
            raise TypeError("state must be a ContextState")
        normalized_refs = _text_tuple(context_refs, "context_refs")
        copied_messages = tuple(copy.deepcopy(dict(message)) for message in messages)
        if normalized_mode == "none":
            return ContextEnvelope(
                state=ContextState(),
                messages=(),
                char_count=0,
                trimmed=bool(copied_messages) or normalized_state != ContextState(),
                dropped_messages=len(copied_messages),
            )
        state_chars = len(normalized_state.prompt_block())
        if normalized_mode == "minimal":
            normalized_state = ContextState(
                goal=normalized_state.goal,
                constraints=normalized_state.constraints,
                current_phase=normalized_state.current_phase,
                next_actions=normalized_state.next_actions,
                summary_version=normalized_state.summary_version,
            )
            state_chars = len(normalized_state.prompt_block())
            return ContextEnvelope(
                state=normalized_state,
                messages=(),
                char_count=state_chars,
                trimmed=bool(copied_messages),
                over_budget=state_chars > self._trim_to,
                dropped_messages=len(copied_messages),
                context_refs=normalized_refs,
            )
        selected_messages = _bounded_messages(
            copied_messages,
            budget=self._trim_to,
            state_chars=state_chars,
            include_system=False,
            require_protected=False,
            context_refs=normalized_refs,
        )
        char_count = state_chars + sum(
            _message_chars(message) for message in selected_messages
        )
        return ContextEnvelope(
            state=normalized_state,
            messages=selected_messages,
            char_count=char_count,
            trimmed=len(selected_messages) < len(copied_messages),
            over_budget=char_count > self._trim_to,
            dropped_messages=len(copied_messages) - len(selected_messages),
            context_refs=normalized_refs,
        )


def context_state_from_history(
    messages: Sequence[Mapping[str, Any]],
    *,
    summary: str,
    current_phase: str,
) -> ContextState:
    """Derive bounded structured state from the current session summary."""
    normalized_summary = _text(summary, "summary")
    if not normalized_summary:
        return ContextState()
    goal = ""
    for message in messages:
        content = str(message.get("content") or "").strip()
        if message.get("role") == "user" and content:
            goal = content[:400]
            break
    return ContextState(
        goal=goal,
        facts=(normalized_summary[:1600],),
        current_phase=str(current_phase),
        summary_version=SUMMARY_VERSION,
    )


def select_host_parent_context(
    *,
    state: ContextState,
    context_mode: str,
    max_chars: int,
    trim_to: int,
) -> ContextEnvelope:
    """Build a host-owned child projection without copying raw parent history."""
    bounded_max = max(1, min(int(max_chars), 4000))
    bounded_trim = max(1, min(int(trim_to), 2400, bounded_max))
    return ContextManager(
        max_chars=bounded_max,
        trim_to=bounded_trim,
    ).select_parent_context(
        (),
        state=state,
        context_mode=context_mode,
    )


__all__ = [
    "CONTEXT_ENVELOPE_VERSION",
    "CONTEXT_STATE_MESSAGE_PREFIX",
    "CONTEXT_STATE_VERSION",
    "SUMMARY_VERSION",
    "ContextEnvelope",
    "ContextManager",
    "ContextState",
    "context_state_from_history",
    "context_state_from_messages",
    "context_state_message",
    "is_context_state_message",
    "replace_context_state_from_history",
    "replace_context_state_message",
    "select_host_parent_context",
    "without_context_state_messages",
]
