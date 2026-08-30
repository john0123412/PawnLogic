"""Merge live command, model, and Extension completion sources."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any


def merge_completion_sources(
    base_words: list[str],
    base_meta: Mapping[str, str],
    *,
    command_provider: Callable[[], Iterable[str]] | None = None,
    model_provider: Callable[[], Mapping[str, Mapping[str, Any]]] | None = None,
    extension_provider: Callable[[], Mapping[str, str]] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Return fresh completion words without mutating the static inputs."""
    words = list(base_words)
    meta = dict(base_meta)

    if command_provider is not None:
        try:
            commands = command_provider()
        except Exception:
            commands = ()
        for word in commands:
            if word not in words:
                words.append(word)
            meta.setdefault(word, "")

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


def pawn_fuzzy_match(query: str, candidate: str) -> tuple[bool, list[int]]:
    """
    Case-insensitive subsequence fuzzy match.
    Return ``(True, indices)`` if ``query`` is a subsequence of ``candidate``
    (case-insensitive), where ``indices`` is the list of matched character
    positions in ``candidate``.  Return ``(False, [])`` otherwise.
    Used for fuzzy verb matching in command dispatch, allowing partial type-ahead
    such as ``/plang`` → ``/planguard``.
    """
    q, c = query.lower(), candidate.lower()
    ci = 0
    indices: list[int] = []
    for qc in q:
        while ci < len(c) and c[ci] != qc:
            ci += 1
        if ci >= len(c):
            return False, []
        indices.append(ci)
        ci += 1
    return True, indices


def builtin_command_completion_words() -> list[str]:
    """Return every registered top-level command for CLI completion."""
    from core.commands import COMMANDS

    return sorted(COMMANDS)


def matching_command_words(query: str, candidates: list[str]) -> list[str]:
    """Return exact-prefix command matches before subsequence matches."""
    query_lower = query.lower()
    exact_matches: list[str] = []
    fuzzy_matches: list[str] = []
    for candidate in sorted(set(candidates)):
        matched, _ = pawn_fuzzy_match(query, candidate)
        if not matched:
            continue
        if candidate.lower().startswith(query_lower):
            exact_matches.append(candidate)
        else:
            fuzzy_matches.append(candidate)
    return exact_matches + fuzzy_matches


def readline_command_candidates(static_words: list[str]) -> list[str]:
    """Return live top-level commands plus static readline subcommands."""
    return [
        *builtin_command_completion_words(),
        *(word for word in static_words if " " in word),
    ]


__all__ = [
    "builtin_command_completion_words",
    "matching_command_words",
    "merge_completion_sources",
    "pawn_fuzzy_match",
    "readline_command_candidates",
]
