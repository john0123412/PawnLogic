"""Shared provider runtime operations for CLI and TUI callers."""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import time
from typing import Any

from config.paths import PAWNLOGIC_HOME
from config import providers as provider_config
from config.providers import (
    CUSTOM_PROVIDERS_PATH,
    FETCHED_MODEL_DESC,
    MODELS,
    PROVIDERS,
    custom_model_alias,
    init_providers,
    is_chat_model_candidate,
    models_url_from_base_url,
)
from core.api_errors import format_http_error, format_transport_error
from core.file_store import atomic_write_text, ensure_private_dir
from core.logger import logger
from core.state import state as _runtime_state
from core.trust import TrustBoundaryKind, trust_notice_for_boundary

PAWNLOGIC_DIR = PAWNLOGIC_HOME
ENV_PATH = PAWNLOGIC_DIR / ".env"
ALWAYS_ACTIVE = {"deepseek"}
UNSUPPORTED_MODEL_MARKERS = (
    "not supported", "unsupported", "model_not_found", "model not found",
    "does not exist", "unknown model", "invalid model", "not available",
)
REASONING_KEYWORDS = ("mimo", "deepseek", "qwq")
_WARNED_HTTP_PROVIDER_URLS: set[str] = set()
load_custom_providers = init_providers


def _user_mode() -> bool:
    return bool(_runtime_state.user_mode)


def maybe_warn_insecure_provider(base_url: str, *, emit=print) -> None:
    url = str(base_url or "").strip()
    if not url.startswith("http://") or url in _WARNED_HTTP_PROVIDER_URLS:
        return
    _WARNED_HTTP_PROVIDER_URLS.add(url)
    if _user_mode():
        emit(trust_notice_for_boundary(TrustBoundaryKind.PLAIN_HTTP))


def save_key(env_var: str, key: str) -> None:
    """Persist a provider API key to the runtime .env and current process."""
    ensure_private_dir(PAWNLOGIC_DIR)
    existing = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    lines = [line for line in existing.splitlines() if not line.startswith(f"{env_var}=")]
    lines.append(f"{env_var}={key}")
    atomic_write_text(ENV_PATH, "\n".join(lines) + "\n", mode=0o600)
    os.environ[env_var] = key


def record_sync_time(provider_name: str) -> None:
    ensure_private_dir(PAWNLOGIC_DIR)
    data: dict[str, Any] = {"providers": {}, "models": {}, "sync_times": {}}
    if CUSTOM_PROVIDERS_PATH.exists():
        try:
            data = json.loads(CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(
                "Failed to update provider sync time in custom_providers.json ({}): {!r}",
                CUSTOM_PROVIDERS_PATH, exc,
            )
            return
    data.setdefault("sync_times", {})[provider_name] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    atomic_write_text(CUSTOM_PROVIDERS_PATH, json.dumps(data, ensure_ascii=False, indent=2))


def sync_models_to_runtime() -> None:
    """Merge custom_providers.json into in-memory provider/model config."""
    init_providers(force=True)


def set_active(provider_name: str, active: bool) -> tuple[bool, str]:
    """Set provider visibility for model selection."""
    if provider_name not in PROVIDERS:
        return False, f"Provider not found: {provider_name}"
    if provider_name in ALWAYS_ACTIVE and not active:
        return False, "DeepSeek is always active."
    if not provider_config.set_provider_active(provider_name, active):
        return False, f"Failed to update provider active state: {provider_name}"
    init_providers(force=True)
    state = "active" if active else "inactive"
    return True, f"Provider is now {state}."


def normalize_base_url(raw: str, api_format: str = "openai") -> str:
    """Build the actual chat endpoint from a stored provider URL."""
    raw = raw.rstrip("/")
    if raw.endswith("/chat/completions") or raw.endswith("/messages"):
        return raw
    suffix = "/messages" if api_format == "anthropic" else "/chat/completions"
    if raw.endswith("/v1"):
        return raw + suffix
    return raw + "/v1" + suffix


def connection_result_from_response(resp, ms: int) -> tuple[bool, str, int]:
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


def model_alias_changes(provider_name: str, entries: list[tuple[str, dict]]) -> list[tuple[str, str]]:
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


def format_model_sync_notice(stats: dict, alias_changes: list[tuple[str, str]]) -> list[str]:
    returned = int(stats.get("returned", 0))
    hidden_name = int(stats.get("hidden_by_name", 0))
    hidden_probe = int(stats.get("hidden_by_probe", 0))
    selectable = int(stats.get("selectable", 0))
    lines = [
        (
            f"Sync summary: {returned} returned; {hidden_name} hidden by type/name; "
            f"{hidden_probe} hidden by chat probe; {selectable} selectable."
        )
    ]
    if alias_changes:
        lines.append(
            f"Alias note: {len(alias_changes)} model IDs will be saved with provider prefix: "
            f"{format_alias_preview(alias_changes)}."
        )
    return lines


def first_provider_chat_model(provider_name: str) -> str:
    for alias, cfg in MODELS.items():
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


async def probe_openai_chat_model(client, endpoint: str, api_key: str, model_id: str) -> tuple[bool, str]:
    payload = {
        "model": model_id,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "hi"}],
    }
    headers = {"Authorization": f"Bearer {api_key}", "content-type": "application/json"}
    try:
        resp = await client.post(endpoint, json=payload, headers=headers)
    except Exception as exc:
        return False, str(exc)[:80]
    if 200 <= resp.status_code < 300:
        return True, ""
    reason = model_rejection_reason(resp.text)
    if reason:
        return False, reason
    if resp.status_code in (400, 401, 403):
        return True, ""
    return False, f"HTTP {resp.status_code}"


async def filter_supported_chat_models(
    base_url: str,
    api_key: str,
    candidates: list[tuple[str, dict]],
    api_format: str = "openai",
) -> tuple[list[tuple[str, dict]], int]:
    if api_format == "anthropic" or not candidates:
        return candidates, 0

    import httpx

    endpoint = normalize_base_url(base_url, api_format)
    sem = asyncio.Semaphore(8)

    async def probe(entry: tuple[str, dict]) -> tuple[bool, tuple[str, dict]]:
        model_id, _cfg = entry
        async with sem:
            ok, _reason = await probe_openai_chat_model(client, endpoint, api_key, model_id)
        return ok, entry

    async with httpx.AsyncClient(timeout=8) as client:
        results = await asyncio.gather(*(probe(entry) for entry in candidates))

    supported = [entry for ok, entry in results if ok]
    return supported, len(candidates) - len(supported)


async def test_connection(
    base_url: str,
    api_key: str,
    api_format: str,
    model_id: str,
) -> tuple[bool, str, int]:
    import httpx

    t0 = time.monotonic()
    if not api_key:
        return False, "API key is not configured.", 0
    if not model_id:
        return False, "No chat models loaded. Use Fetch / Sync Models first.", 0
    endpoint = normalize_base_url(base_url, api_format)
    maybe_warn_insecure_provider(endpoint)
    payload = {
        "model": model_id,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "hi"}],
    }
    if api_format == "anthropic":
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
    else:
        headers = {"Authorization": f"Bearer {api_key}", "content-type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(endpoint, json=payload, headers=headers)
        ms = int((time.monotonic() - t0) * 1000)
        return connection_result_from_response(resp, ms)
    except httpx.TimeoutException:
        return (
            False,
            "Connection timeout: provider did not respond within 10s.",
            int((time.monotonic() - t0) * 1000),
        )
    except httpx.HTTPError as exc:
        return False, format_transport_error(exc), int((time.monotonic() - t0) * 1000)
    except Exception as exc:
        return False, format_transport_error(exc), int((time.monotonic() - t0) * 1000)


async def fetch_models(
    base_url: str,
    api_key: str,
    api_format: str = "openai",
) -> tuple[list[tuple[str, dict]], str, dict]:
    import httpx

    models_url = models_url_from_base_url(base_url)
    maybe_warn_insecure_provider(models_url)
    all_data: list = []
    stats = {"returned": 0, "hidden_by_name": 0, "hidden_by_probe": 0, "selectable": 0}
    url: str | None = f"{models_url}?limit=200"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            while url:
                resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    return [], format_http_error(exc.response.status_code, exc.response.text), stats
                body = resp.json()
                all_data.extend(body.get("data", []))
                if not body.get("has_more"):
                    break
                cursor = body.get("next_cursor") or body.get("next_page")
                url = f"{models_url}?limit=200&after={cursor}" if cursor else None
    except httpx.TimeoutException:
        return [], "Connection timeout: provider did not return /v1/models within 15s.", stats
    except httpx.HTTPError as exc:
        return [], format_transport_error(exc), stats
    except Exception as exc:
        return [], format_transport_error(exc), stats

    stats["returned"] = len(all_data)
    candidates = []
    for item in all_data:
        model_id = item.get("id", "")
        if not model_id or not model_is_chat_candidate(model_id):
            stats["hidden_by_name"] += 1
            continue
        lower_model = model_id.lower()
        vision = any(key in lower_model for key in ("vision", "vl", "visual"))
        reasoning = any(key in lower_model for key in REASONING_KEYWORDS)
        candidates.append((
            model_id,
            {
                "id": model_id,
                "provider": "",
                "desc": FETCHED_MODEL_DESC,
                "color": "\033[37m",
                "vision": vision,
                "reasoning": reasoning,
            },
        ))

    filtered, removed = await filter_supported_chat_models(base_url, api_key, candidates, api_format)
    stats["hidden_by_probe"] = removed
    stats["selectable"] = len(filtered)
    if removed:
        for _model_id, cfg in filtered:
            cfg["desc"] = f"{FETCHED_MODEL_DESC}; {removed} unsupported hidden"
    return filtered, "", stats
