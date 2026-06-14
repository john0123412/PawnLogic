"""Tool schema selection helpers for phase-aware routing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


ALWAYS_AVAILABLE_TOOLS = ("switch_phase", "bump_skill")


def select_phase_tools(
    schemas: Sequence[dict],
    agent_phases: Mapping[str, Sequence[str]],
    current_phase: str,
    *,
    always_available: Sequence[str] = ALWAYS_AVAILABLE_TOOLS,
) -> list[dict]:
    """Return tool schemas available for the current phase."""
    phase_whitelist = set(agent_phases.get(current_phase, []))
    always = set(always_available)
    selected: list[dict] = []
    for schema in schemas:
        name = schema.get("function", {}).get("name")
        if name in phase_whitelist or name in always:
            selected.append(schema)
    return selected


def phase_tool_names(agent_phases: Mapping[str, Sequence[str]], current_phase: str) -> set[str]:
    """Return the configured tool names for a phase."""
    return set(agent_phases.get(current_phase, []))
