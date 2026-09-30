"""Provider request payload and header builders for the API client."""

from __future__ import annotations

import copy
import json

from config import DYNAMIC_CONFIG, MODELS, PROVIDERS
from config.tiers import EFFORT_WIRE_VALUES, DEFAULT_EFFORT_LEVEL
from core.state import runtime_config


_REASONING_MODEL_PATTERNS = (
    "mimo",        # Xiaomi MiMo family, including legacy aliases.
    "deepseek",    # DeepSeek family: v4-flash / v4-pro / reasoner / r1.
    "qwq",         # Alibaba QwQ reasoning series.
)

# A custom provider that opts in accepts the effort ladder, but opting in is
# not a claim that it has a ``none`` value.  Leaving ``off`` out keeps that
# rung local-only, which costs the user nothing: ``off`` already selects the
# smallest budget, it just does not ask the provider to stop reasoning.
_EFFORT_OPT_IN_LADDER = {
    level: value for level, value in EFFORT_WIRE_VALUES.items() if level != "off"
}


def model_effort_map(model_alias: str) -> dict:
    """Return the rung -> wire value map a model accepts, or an empty dict.

    A built-in model declares its own map.  A custom model inherits the
    ladder only when its provider explicitly opted in, so a relay that
    rejects ``reasoning_effort`` is never sent the field by accident.
    """
    model = MODELS.get(model_alias) or {}
    declared = model.get("effort")
    if isinstance(declared, dict) and declared:
        return {str(rung): str(value) for rung, value in declared.items()}
    provider_cfg = PROVIDERS.get(str(model.get("provider") or "")) or {}
    if provider_cfg.get("reasoning_effort"):
        return dict(_EFFORT_OPT_IN_LADDER)
    return {}


def resolve_reasoning_effort(model_alias: str) -> str | None:
    """Return the wire value for the active effort level, or None to omit it.

    Resolved per model alias at the one place every request payload is built,
    so the main turn, delegated workers, ``/think``, history summaries and
    workspace naming all resolve the same way and none of them can drift.
    """
    level = str(runtime_config().get("effort_level") or DEFAULT_EFFORT_LEVEL)
    value = model_effort_map(model_alias).get(level)
    return str(value) if value else None



def _is_reasoning_model(model_alias: str, model_id: str = "") -> bool:
    """Return whether a model supports the reasoning_content field."""
    m = MODELS.get(model_alias)
    if m is not None and "reasoning" in m:
        return bool(m["reasoning"])
    combo = f"{(model_alias or '').lower()}|{(model_id or '').lower()}"
    return any(pattern in combo for pattern in _REASONING_MODEL_PATTERNS)


def _sanitize_messages_for_model(
    messages: list,
    model_alias: str,
    model_id: str = "",
) -> list:
    """Return an OpenAI-format message copy suitable for the target model."""
    is_reasoning = _is_reasoning_model(model_alias, model_id)
    cloned_msgs = copy.deepcopy(messages)
    out: list[dict] = []
    for message in cloned_msgs:
        clean = {
            key: value for key, value in message.items()
            if not (isinstance(key, str) and key.startswith("_"))
        }
        reasoning_content = clean.get("reasoning_content")
        if not reasoning_content or not is_reasoning:
            clean.pop("reasoning_content", None)
        out.append(clean)
    return out


def _anthropic_convert_tools(tools_schema: list) -> list:
    """Convert OpenAI tool schema to Anthropic input_schema format."""
    result = []
    for tool in tools_schema or []:
        function = tool.get("function", {})
        result.append({
            "name": function.get("name", ""),
            "description": function.get("description", ""),
            "input_schema": function.get("parameters", {"type": "object", "properties": {}}),
        })
    return result


def _anthropic_convert_messages(messages: list) -> tuple[list, str | None]:
    """Convert OpenAI messages to Anthropic messages and system prompt."""
    system_prompt = None
    converted = []

    for message in messages:
        role = message.get("role")

        if role == "system":
            system_prompt = message.get("content", "")
            continue

        if role == "tool":
            converted.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": message.get("tool_call_id", ""),
                    "content": message.get("content", ""),
                }],
            })
            continue

        if role == "assistant":
            content = message.get("content") or ""
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                converted.append({"role": "assistant", "content": content or "."})
            else:
                blocks = []
                if content:
                    blocks.append({"type": "text", "text": content})
                for tool_call in tool_calls:
                    function = tool_call.get("function", {})
                    args_str = function.get("arguments", "{}")
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except json.JSONDecodeError:
                        args = {"_raw": args_str}
                    blocks.append({
                        "type": "tool_use",
                        "id": tool_call.get("id", ""),
                        "name": function.get("name", ""),
                        "input": args,
                    })
                converted.append({"role": "assistant", "content": blocks})
            continue

        if role == "user":
            content = message.get("content", "")
            if isinstance(content, str):
                converted.append({"role": "user", "content": content})
            else:
                converted.append(message)
            continue

    merged: list[dict] = []
    for message in converted:
        if merged and merged[-1]["role"] == message["role"]:
            previous = merged[-1]["content"]
            current = message["content"]
            if isinstance(previous, str) and isinstance(current, str):
                merged[-1]["content"] = previous + "\n\n" + current
            elif isinstance(previous, list) and isinstance(current, list):
                merged[-1]["content"] = previous + current
            elif isinstance(previous, str) and isinstance(current, list):
                merged[-1]["content"] = [{"type": "text", "text": previous}, *current]
            elif isinstance(previous, list) and isinstance(current, str):
                merged[-1]["content"] = [*previous, {"type": "text", "text": current}]
        else:
            merged.append(message)

    return merged, system_prompt


def _anthropic_build_payload(
    messages: list,
    model_id: str,
    max_tokens: int,
    tools_schema: list | None,
) -> dict:
    """Build a native Anthropic Messages API request body."""
    converted_messages, system_prompt = _anthropic_convert_messages(messages)
    payload: dict = {
        "model": model_id,
        "max_tokens": max_tokens or DYNAMIC_CONFIG["max_tokens"],
        "messages": converted_messages,
        "stream": True,
    }
    if system_prompt:
        payload["system"] = system_prompt
    if tools_schema:
        payload["tools"] = _anthropic_convert_tools(tools_schema)
    return payload


def _anthropic_build_headers(api_key: str, body_len: int) -> dict:
    """Build native Anthropic request headers."""
    return {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
        "Content-Length": str(body_len),
    }


def _build_openai_payload(
    messages: list,
    model_alias: str,
    model_id: str,
    max_tokens: int,
    tools_schema: list | None,
    tool_choice: str,
    response_format: dict | None,
) -> dict:
    clean = _sanitize_messages_for_model(messages, model_alias, model_id)
    payload = {
        "model": model_id,
        "messages": clean,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if tools_schema:
        payload["tools"] = tools_schema
        payload["tool_choice"] = tool_choice
    if response_format:
        payload["response_format"] = response_format
    reasoning_effort = resolve_reasoning_effort(model_alias)
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    payload["stream_options"] = {"include_usage": True}
    return payload


def _build_openai_headers(api_key: str, body_len: int) -> dict:
    """Build OpenAI-compatible streaming request headers."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
        "Content-Length": str(body_len),
    }
