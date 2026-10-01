"""Provider model identifiers, probe-adjacent formatting, and response helpers."""

from __future__ import annotations

from typing import Any

from config.providers import custom_model_alias, is_chat_model_candidate
from core.api_errors import format_http_error, model_listing_unavailable_hint

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


def connection_result_from_listing(
    resp: Any,
    ms: int,
    *,
    api_format: str | None = None,
    auth: str | None = None,
) -> tuple[bool, str]:
    """Interpret a response from the free model-listing endpoint.

    Used by Test Connection, which must never infer. A 2xx means the base
    URL resolved and the provider accepted the key. Anything else is a
    failure, formatted by the shared error helper — which already names the
    likely cause for 401/403 rather than a generic status line.

    ``api_format``/``auth`` let the 401 hint name the credential header that
    was actually sent. Without them a relay that speaks Anthropic but
    authenticates with Bearer reports "your API key is invalid" for a key that
    works, which is what sent one user to rotate a valid credential.

    A listing response says nothing about whether a specific model can serve
    chat, so this deliberately does not take a model id.
    """
    if 200 <= resp.status_code < 300:
        return True, f"Connected ({ms}ms; free model listing, no inference sent)"
    msg = format_http_error(
        resp.status_code, resp.text, api_format=api_format, auth=auth
    )
    listing_hint = model_listing_unavailable_hint(resp.status_code)
    return False, f"{msg} {listing_hint}" if listing_hint else msg


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
    hidden_meta = int(stats.get("hidden_by_metadata", 0))
    selectable = int(stats.get("selectable", 0))
    lines = [
        (
            f"Sync summary: {returned} returned; {hidden_name} hidden by type/name; "
            f"{hidden_meta} hidden by capability metadata; "
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
