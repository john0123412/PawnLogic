"""Provider model identifiers, probe-adjacent formatting, and response helpers."""

from __future__ import annotations

from typing import Any

from config.providers import custom_model_alias, is_chat_model_candidate
from core.api_errors import format_http_error

UNSUPPORTED_MODEL_MARKERS = (
    "not supported",
    "unsupported",
    "model_not_found",
    "model not found",
    "does not exist",
    "unknown model",
    "invalid model",
    "not available",
)
REASONING_KEYWORDS = ("mimo", "deepseek", "qwq")


def normalize_base_url(raw: str, api_format: str = "openai") -> str:
    """Build the actual chat endpoint from a stored provider URL."""
    raw = raw.rstrip("/")
    if raw.endswith("/chat/completions") or raw.endswith("/messages"):
        return raw
    suffix = "/messages" if api_format == "anthropic" else "/chat/completions"
    if raw.endswith("/v1"):
        return raw + suffix
    return raw + "/v1" + suffix


def connection_result_from_response(resp: Any, ms: int) -> tuple[bool, str, int]:
    if 200 <= resp.status_code < 300:
        try:
            resp.json()
        except ValueError:
            return True, f"Connected ({ms}ms; non-standard response)", ms
        return True, f"Connected ({ms}ms)", ms

    if resp.status_code == 400:
        if model_rejection_reason(resp.text):
            return False, format_http_error(400, resp.text), ms
        try:
            body = resp.json()
        except ValueError:
            return False, format_http_error(400, resp.text), ms
        if isinstance(body, dict) and "error" in body:
            return True, f"Connected ({ms}ms; API returned validation error)", ms

    return False, format_http_error(resp.status_code, resp.text), ms


def model_is_chat_candidate(model_id: str) -> bool:
    return is_chat_model_candidate(model_id)


def candidate_save_alias(provider_name: str, model_id: str, cfg: dict) -> str:
    return custom_model_alias(provider_name, str(cfg.get("id") or model_id), model_id)


def model_alias_changes(
    provider_name: str, entries: list[tuple[str, dict]]
) -> list[tuple[str, str]]:
    changes = []
    for model_id, cfg in entries:
        alias = candidate_save_alias(provider_name, model_id, cfg)
        if alias != model_id:
            changes.append((model_id, alias))
    return changes


def format_alias_preview(changes: list[tuple[str, str]], limit: int = 3) -> str:
    preview = ", ".join(f"{model_id} -> {alias}" for model_id, alias in changes[:limit])
    if len(changes) > limit:
        preview += f", ... +{len(changes) - limit} more"
    return preview


def format_model_sync_notice(
    stats: dict, alias_changes: list[tuple[str, str]]
) -> list[str]:
    returned = int(stats.get("returned", 0))
    hidden_name = int(stats.get("hidden_by_name", 0))
    hidden_probe = int(stats.get("hidden_by_probe", 0))
    kept_unknown = int(stats.get("probe_kept_unknown", 0) or 0)
    selectable = int(stats.get("selectable", 0))
    kept_part = (
        f"{kept_unknown} kept despite probe issues (rate limit/unreachable); "
        if kept_unknown
        else ""
    )
    lines = [
        (
            f"Sync summary: {returned} returned; {hidden_name} hidden by type/name; "
            f"{hidden_probe} hidden by chat probe; {kept_part}"
            f"{selectable} selectable."
        )
    ]
    if alias_changes:
        lines.append(
            f"Alias note: {len(alias_changes)} model IDs will be saved with provider prefix: "
            f"{format_alias_preview(alias_changes)}."
        )
    return lines


def first_provider_chat_model(provider_name: str, models: dict[str, dict]) -> str:
    for alias, cfg in models.items():
        if cfg.get("provider") != provider_name:
            continue
        model_id = str(cfg.get("id") or alias)
        if model_is_chat_candidate(model_id):
            return model_id
    return ""


def model_rejection_reason(response_text: str) -> str:
    text = response_text.lower()
    if any(marker in text for marker in UNSUPPORTED_MODEL_MARKERS):
        return "unsupported"
    return ""
