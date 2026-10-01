"""Shared provider runtime operations for CLI and TUI callers."""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

from config.paths import PAWNLOGIC_HOME
from config import providers as provider_config
from config.providers import (
    BUILTIN_PROVIDER_NAMES,
    CUSTOM_PROVIDERS_PATH,
    FETCHED_MODEL_DESC,
    MODELS,
    PROVIDERS,
    init_providers,
    models_url_from_base_url,
)
from core.api_errors import _retry_delay, format_http_error, format_transport_error
from core.api_retry import (
    RetryPolicy,
    is_retryable_http_status,
    is_retryable_transport_error,
    retry_policy_from_env,
)
from core.file_store import atomic_write_text, ensure_private_dir
from core.logger import logger
from core.provider_formats import (
    build_auth_headers,
    normalize_api_format,
    normalize_auth,
)
from core.provider_models import (
    REASONING_KEYWORDS,
    candidate_save_alias,
    connection_result_from_listing,
    first_provider_chat_model as _first_provider_chat_model,
    format_alias_preview,
    format_model_sync_notice,
    model_alias_changes,
    model_is_chat_candidate,
    model_rejection_reason,
)
from core.provider_transport import provider_headers
from core.state import state as _runtime_state
from core.trust import TrustBoundaryKind, trust_notice_for_boundary
# Model probing lives in core.provider_discovery; re-exported here so existing
# `provider_runtime.<name>` call sites keep resolving.
from core.provider_discovery import (
    filter_supported_chat_models,
)

PAWNLOGIC_DIR = PAWNLOGIC_HOME
ENV_PATH = PAWNLOGIC_DIR / ".env"
ALWAYS_ACTIVE = {"deepseek"}
_WARNED_HTTP_PROVIDER_URLS: set[str] = set()
load_custom_providers = init_providers

__all__ = [
    "candidate_save_alias",
    "connection_result_from_listing",
    "fetch_models",
    "filter_supported_chat_models",
    "first_provider_chat_model",
    "format_alias_preview",
    "format_model_sync_notice",
    "model_alias_changes",
    "model_is_chat_candidate",
    "model_rejection_reason",
]


async def _request_with_retry(
    request: Callable[[], Awaitable[Any]], *, policy: RetryPolicy
) -> Any:
    """Execute one provider request with the shared pre-response retry policy."""
    last_error: Exception | None = None
    for attempt in range(policy.max_attempts):
        try:
            response = await request()
        except Exception as exc:
            last_error = exc
            if not is_retryable_transport_error(exc) or attempt >= policy.max_attempts - 1:
                raise
            await asyncio.sleep(_retry_delay(attempt))
            continue
        if (
            is_retryable_http_status(response.status_code)
            and attempt < policy.max_attempts - 1
        ):
            retry_after = response.headers.get("Retry-After")
            await asyncio.sleep(
                _retry_delay(
                    attempt,
                    retry_after,
                    retry_after_max=policy.retry_after_cap_seconds,
                )
            )
            continue
        return response
    if last_error is not None:
        raise last_error
    raise RuntimeError("provider request exhausted without a response")


def _user_mode() -> bool:
    return bool(_runtime_state.user_mode)


def maybe_warn_insecure_provider(
    base_url: str, *, emit: Callable[[str], None] = print
) -> None:
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


def save_provider_with_rollback(
    name: str,
    prov_cfg: dict,
    models_cfg: dict,
    *,
    replace_models: bool = False,
) -> tuple[bool, str]:
    """Persist a custom provider to disk, then update live registries.

    If disk persistence fails, live PROVIDERS/MODELS remain unchanged.
    Returns (ok, error_message).
    """
    # `source_item` is the raw `/v1/models` entry that fetch carries so
    # filtering can read free capability metadata without another request. It
    # is a transient field and must never reach custom_providers.json, so it
    # is stripped here as well as at the TUI save site.
    models_cfg = {
        alias: {k: v for k, v in cfg.items() if k != "source_item"}
        for alias, cfg in models_cfg.items()
    }
    try:
        provider_config.save_custom_provider(name, prov_cfg, models_cfg, replace_models=replace_models)
    except Exception as exc:
        return False, f"Failed to save provider config: {exc}"
    # Only update live registries after successful persistence.
    provider_config.register_provider(name, prov_cfg)
    return True, ""


def update_custom_provider(
    provider_name: str,
    base_url: str,
    api_format: str,
    auth: str | None = None,
) -> tuple[bool, str]:
    """Replace a custom provider's endpoint fields, keeping its identity.

    The name, API key env var, label, active state, and loaded models all
    survive: only the base URL, the wire format, and — when given — the auth
    scheme are replaced, in a single atomic write. Renaming is deliberately out
    of scope here — it would have to re-point every model entry and rename the
    env var, which cannot be done in one write without a window where the
    provider is half-migrated.

    ``auth`` left as ``None`` keeps whatever the provider already had, so an
    Edit that does not touch the Auth row cannot silently reset it.
    """
    if provider_name not in PROVIDERS:
        return False, f"Provider not found: {provider_name}"
    if provider_name in BUILTIN_PROVIDER_NAMES:
        return False, f"Cannot edit built-in provider: {provider_name}"
    try:
        fmt = normalize_api_format(api_format)
    except ValueError as exc:
        return False, str(exc)
    cfg = dict(PROVIDERS[provider_name])
    cfg["base_url"] = str(base_url).strip()
    cfg["api_format"] = fmt
    if auth is not None:
        try:
            cfg["auth"] = normalize_auth(auth)
        except ValueError as exc:
            return False, str(exc)
    # An empty models map with replace_models left False is what keeps the
    # provider's already-loaded models on disk.
    ok, err = save_provider_with_rollback(provider_name, cfg, {})
    if not ok:
        return False, err
    init_providers(force=True)
    return True, ""


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


def delete_custom_provider(provider_name: str) -> tuple[bool, str]:
    """Remove a custom provider from persistence and live registries."""
    if provider_name in ALWAYS_ACTIVE or provider_name not in PROVIDERS:
        return False, f"Provider cannot be removed: {provider_name}"
    try:
        if not provider_config.remove_custom_provider(provider_name):
            return False, f"Failed to remove provider config: {provider_name}"
        provider_config.remove_provider(provider_name)
        provider_config.remove_models_for_provider(provider_name)
    except Exception as exc:
        init_providers(force=True)
        return False, f"Failed to remove provider: {exc}"
    return True, ""


def first_provider_chat_model(provider_name: str) -> str:
    return _first_provider_chat_model(provider_name, MODELS)


async def test_connection(
    base_url: str,
    api_key: str,
    api_format: str,
    model_id: str,
    auth: str = "auto",
) -> tuple[bool, str, int]:
    """Check reachability and credentials for free.

    This used to POST ``max_tokens=1`` to the chat endpoint, which is a real
    billable inference. It now checks the same two things a user actually
    needs answered — is the configured base URL reachable, and does the
    provider accept this API key — against the free model-listing endpoint
    derived from that base URL. No chat request is made, so this command
    never costs anything.

    The trade-off: it no longer proves that ``model_id`` can serve chat. A
    model the key cannot use is reported by the provider on first real use.

    ``auth`` is sent as configured, so a relay that authenticates differently
    from the protocol it speaks can still be tested here rather than only at
    the first real request.
    """
    import httpx

    t0 = time.monotonic()
    policy = retry_policy_from_env()
    if not api_key:
        return False, "API key is not configured.", 0
    listing = models_url_from_base_url(base_url)
    maybe_warn_insecure_provider(listing)
    try:
        headers = build_auth_headers(api_format, auth, api_key)
    except ValueError as exc:
        return False, str(exc), 0
    try:
        async with httpx.AsyncClient(timeout=policy.nonstream_timeout_seconds) as client:
            resp = await _request_with_retry(
                lambda: client.get(listing, headers=headers),
                policy=policy,
            )
        ms = int((time.monotonic() - t0) * 1000)
        ok, msg = connection_result_from_listing(resp, ms, api_format=api_format, auth=auth)
        return ok, msg, ms
    except httpx.TimeoutException:
        return (
            False,
            f"Connection timeout: provider did not respond within {policy.nonstream_timeout_seconds:g}s.",
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
    auth: str = "auto",
) -> tuple[list[tuple[str, dict]], str, dict]:
    import httpx

    policy = retry_policy_from_env()
    models_url = models_url_from_base_url(base_url)
    maybe_warn_insecure_provider(models_url)
    all_data: list = []
    stats: dict[str, Any] = {
        "returned": 0,
        "hidden_by_name": 0,
        "hidden_by_metadata": 0,
        "selectable": 0,
    }
    headers = provider_headers(api_format, api_key, auth)
    url: str | None = f"{models_url}?limit=200"
    try:
        async with httpx.AsyncClient(timeout=policy.nonstream_timeout_seconds) as client:
            while url:
                request_url = url

                async def fetch_page(request_url: str = request_url) -> Any:
                    return await client.get(request_url, headers=headers)

                resp = await _request_with_retry(
                    fetch_page,
                    policy=policy,
                )
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    return [], format_http_error(
                        exc.response.status_code,
                        exc.response.text,
                        api_format=api_format,
                        auth=auth,
                    ), stats
                try:
                    body = resp.json()
                except ValueError:
                    return [], f"Provider returned invalid JSON from {models_url}.", stats
                if not isinstance(body, dict):
                    return [], f"Provider returned non-object JSON from {models_url}.", stats
                data = body.get("data", [])
                if not isinstance(data, list):
                    return [], f"Provider returned non-list 'data' field from {models_url}.", stats
                all_data.extend(data)
                if not body.get("has_more"):
                    break
                cursor = body.get("next_cursor") or body.get("next_page")
                url = f"{models_url}?limit=200&after={quote(str(cursor), safe='')}" if cursor else None
    except httpx.TimeoutException:
        return [], (
            "Connection timeout: provider did not return /v1/models within "
            f"{policy.nonstream_timeout_seconds:g}s."
        ), stats
    except httpx.HTTPError as exc:
        return [], format_transport_error(exc), stats
    except Exception as exc:
        return [], format_transport_error(exc), stats

    stats["returned"] = len(all_data)
    candidates = []
    for item in all_data:
        if not isinstance(item, dict):
            stats["hidden_by_name"] += 1
            continue
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
                # Raw listing entry, kept so filtering can read the free
                # capability metadata without another request. It is dropped
                # before anything is persisted.
                "source_item": item,
            },
        ))

    filtered, removed, filter_stats = await filter_supported_chat_models(base_url, api_key, candidates, api_format)
    stats["hidden_by_metadata"] = removed
    stats["hidden_reasons"] = dict(filter_stats.get("hidden_reasons", {}))
    stats["selectable"] = len(filtered)
    if removed:
        for _model_id, cfg in filtered:
            cfg["desc"] = f"{FETCHED_MODEL_DESC}; {removed} unsupported hidden"
    return filtered, "", stats
