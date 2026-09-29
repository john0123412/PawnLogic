"""Provider model discovery: filter a provider's chat models for free.

`/provider fetch` lists models from the free `/v1/models` endpoint and then
hides the ones that cannot serve chat. That filtering used to send a real
`POST /chat/completions` per candidate -- a billable inference. openrouter
returns hundreds of models, so one fetch produced hundreds of charged
requests and took minutes.

Filtering now reads `architecture.output_modalities` from the listing
response the fetch already has. Nothing is inferred, nothing is billed, and
the whole fetch costs one listing call. A provider that omits the field is
kept: absence of evidence is not evidence of absence.

Split out of `core/provider_runtime.py` to keep this off that module's
architecture budget. `core.provider_runtime` re-exports the public names
here, so existing `provider_runtime.<name>` call sites keep working.
"""

from __future__ import annotations

__all__ = [
    "filter_supported_chat_models",
    "metadata_hidden_reason",
]


def metadata_hidden_reason(item: dict) -> str:
    """Classify one `/v1/models` entry from its free metadata alone.

    Returns "" to keep, or a reason to hide. A provider that reports
    ``output_modalities`` is telling us what the model emits; anything that
    cannot emit text cannot be a chat model, and hiding it costs nothing.
    Absence of the field is not evidence of absence — providers are not
    required to send it — so an entry without it is always kept.
    """
    architecture = item.get("architecture")
    modalities = (
        architecture.get("output_modalities")
        if isinstance(architecture, dict)
        else None
    )
    if not isinstance(modalities, list) or not modalities:
        return ""
    normalized = {str(m).strip().lower() for m in modalities}
    if "text" in normalized:
        return ""
    return "non_chat_output"


async def filter_supported_chat_models(
    base_url: str,
    api_key: str,
    candidates: list[tuple[str, dict]],
    api_format: str = "openai",
) -> tuple[list[tuple[str, dict]], int, dict]:
    """Filter candidates using the metadata `/v1/models` already returned.

    This used to probe every candidate with a real
    ``POST /chat/completions``. That is a billable inference: openrouter
    returns hundreds of models, so a single ``/provider fetch`` produced
    hundreds of charged requests and took minutes. Filtering is now derived
    from the free ``architecture.output_modalities`` field in the listing
    response, so no chat request is ever made and the whole fetch costs one
    listing call.

    ``base_url``, ``api_key`` and ``api_format`` are kept so existing call
    sites keep working; they are deliberately unused.
    """
    del base_url, api_key, api_format
    if not candidates:
        return candidates, 0, {"kept_unknown": 0, "hidden_reasons": {}}

    stats: dict = {"kept_unknown": 0, "hidden_reasons": {}}
    supported: list[tuple[str, dict]] = []
    for model_id, cfg in candidates:
        reason = metadata_hidden_reason(cfg.get("source_item") or {})
        if reason:
            stats["hidden_reasons"][reason] = (
                stats["hidden_reasons"].get(reason, 0) + 1
            )
            continue
        supported.append((model_id, cfg))
    return supported, len(candidates) - len(supported), stats
