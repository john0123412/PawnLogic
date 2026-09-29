"""Provider model discovery: classify and probe a provider's chat models.

`/provider fetch` must hide models a provider cannot actually serve before the
user selects one, so every candidate id is probed against the live endpoint and
only hidden on *positive* evidence. A model that merely rate-limits or refuses
the probe payload is kept visible.

Split out of `core/provider_runtime.py` to keep the probe state machine off
that module's architecture budget. `core.provider_runtime` re-exports the
public names here, so existing `provider_runtime.<name>` call sites keep
working.
"""

from __future__ import annotations

import asyncio
from typing import Any

from core.api_errors import _retry_delay
from core.provider_models import (
    UNSUPPORTED_MODEL_MARKERS,
    normalize_base_url,
)

# Some relays reject max_tokens=1 outright ("must be greater than 2") and
# newer OpenAI models demand max_completion_tokens instead.
PROBE_MAX_TOKENS = 8
PROBE_ATTEMPTS = 2
PROBE_RETRY_CAP_SECONDS = 2.0
# Bodies complaining about the probe payload itself rather than the model id.
# Checked before UNSUPPORTED_MODEL_MARKERS because OpenAI-style parameter
# errors read like "max_tokens is not supported with this model".
PROBE_PARAM_ERROR_HINTS = (
    "max_tokens",
    "max_completion_tokens",
    "unsupported parameter",
    "invalid parameter",
)

__all__ = [
    "classify_probe_response",
    "filter_supported_chat_models",
    "probe_openai_chat_model",
]


def classify_probe_response(status_code: int, body: str) -> tuple[str, str]:
    """Classify one probe response as ("alive" | "hidden" | "unknown", reason).

    "hidden" requires positive evidence that the model id itself is unusable
    (404 or a model-identity rejection marker). Parameter rejections are
    "alive": they prove the model exists even though the payload was refused.
    Transient signals (rate limits) are "unknown" so callers can retry and,
    if unresolved, keep the model visible instead of silently dropping it.
    """
    if 200 <= status_code < 300:
        return "alive", ""
    text = (body or "").lower()
    if any(hint in text for hint in PROBE_PARAM_ERROR_HINTS):
        return "alive", "param_error"
    if any(marker in text for marker in UNSUPPORTED_MODEL_MARKERS):
        return "hidden", "model_rejected"
    if status_code == 404:
        return "hidden", "http_404"
    if status_code == 429:
        return "unknown", "rate_limited"
    return "alive", ""


async def probe_openai_chat_model(
    client: Any, endpoint: str, api_key: str, model_id: str
) -> tuple[bool, str]:
    """Return (alive, reason). A model is hidden only on positive evidence
    ("hidden" classification); rate limits and transport failures are retried
    once and otherwise reported alive with the reason attached.
    """
    payload = {
        "model": model_id,
        "max_tokens": PROBE_MAX_TOKENS,
        "messages": [{"role": "user", "content": "hi"}],
    }
    headers = {"Authorization": f"Bearer {api_key}", "content-type": "application/json"}
    reason = "probe_unreachable"
    for attempt in range(PROBE_ATTEMPTS):
        try:
            resp = await client.post(endpoint, json=payload, headers=headers)
        except Exception:
            reason = "probe_unreachable"
            if attempt < PROBE_ATTEMPTS - 1:
                await asyncio.sleep(_retry_delay(attempt))
                continue
            break
        verdict, reason = classify_probe_response(resp.status_code, resp.text)
        if verdict != "unknown":
            return verdict == "alive", reason
        if attempt < PROBE_ATTEMPTS - 1:
            resp_headers = getattr(resp, "headers", None)
            retry_after = resp_headers.get("Retry-After") if resp_headers else None
            await asyncio.sleep(
                _retry_delay(
                    attempt, retry_after, retry_after_max=PROBE_RETRY_CAP_SECONDS
                )
            )
    return True, reason


async def filter_supported_chat_models(
    base_url: str,
    api_key: str,
    candidates: list[tuple[str, dict]],
    api_format: str = "openai",
) -> tuple[list[tuple[str, dict]], int, dict]:
    """Probe candidates concurrently; returns (supported, removed, probe_stats).

    probe_stats holds "kept_unknown" (models kept despite rate limits or
    unreachable probes) and "hidden_reasons" (reason -> count for removals).
    """
    if api_format == "anthropic" or not candidates:
        return candidates, 0, {"kept_unknown": 0, "hidden_reasons": {}}

    import httpx

    endpoint = normalize_base_url(base_url, api_format)
    # Lower concurrency keeps burst probes from tripping relay rate limiters,
    # which previously got good models hidden as "unsupported".
    sem = asyncio.Semaphore(4)

    async def probe(entry: tuple[str, dict]) -> tuple[bool, str, tuple[str, dict]]:
        model_id, _cfg = entry
        async with sem:
            alive, reason = await probe_openai_chat_model(
                client, endpoint, api_key, model_id
            )
        return alive, reason, entry

    async with httpx.AsyncClient(timeout=8) as client:
        results = await asyncio.gather(*(probe(entry) for entry in candidates))

    probe_stats: dict = {"kept_unknown": 0, "hidden_reasons": {}}
    supported: list[tuple[str, dict]] = []
    for alive, reason, entry in results:
        if alive:
            if reason in ("rate_limited", "probe_unreachable"):
                probe_stats["kept_unknown"] += 1
            supported.append(entry)
        else:
            probe_stats["hidden_reasons"][reason] = (
                probe_stats["hidden_reasons"].get(reason, 0) + 1
            )
    return supported, len(candidates) - len(supported), probe_stats
