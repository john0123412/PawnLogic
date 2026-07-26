"""Merge live model and Extension completion sources."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


def merge_completion_sources(
    base_words: list[str],
    base_meta: Mapping[str, str],
    *,
    model_provider: Callable[[], Mapping[str, Mapping[str, Any]]] | None = None,
    extension_provider: Callable[[], Mapping[str, str]] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Return fresh completion words without mutating the static inputs."""
    words = list(base_words)
    meta = dict(base_meta)

    if model_provider is not None:
        try:
            models = model_provider()
        except Exception:
            models = {}
        for alias, model_info in models.items():
            description = str(model_info.get("desc", ""))
            for word in (
                f"/model {alias}",
                f"/agent policy model allow {alias}",
                f"/agent policy model deny {alias}",
            ):
                if word not in meta:
                    words.append(word)
                meta[word] = description

    if extension_provider is not None:
        try:
            extensions = extension_provider() or {}
        except Exception:
            extensions = {}
        for name, description in extensions.items():
            for subcommand in ("enable", "disable", "status"):
                word = f"/extension {subcommand} {name}"
                if word not in meta:
                    words.append(word)
                meta[word] = str(description or "")

    return words, meta


__all__ = ["merge_completion_sources"]
