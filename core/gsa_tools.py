"""Tool handlers for GSA skill feedback and pre-flight payload auditing.

Handlers and schemas live here; ``core.session`` registers them into the
shared tool registry at import time, so registration order is preserved by
importing this module at the handler block's original position.
"""

from __future__ import annotations

from core.gsa import bump_skill
from core.memory import check_failure, format_failures_for_prompt


def tool_bump_skill(args: dict) -> str:
    """
    Increase a GSA skill's hit count and refresh its timestamp after using it
    successfully. Call this proactively after <verify> passes.
    """
    skill_name = args.get("skill_name", "").strip()
    if not skill_name:
        return "ERROR: skill_name cannot be empty"
    try:
        _ok, msg = bump_skill(skill_name)
        return msg
    except Exception as e:
        return f"ERROR: bump_skill failed: {e}"


BUMP_SKILL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "bump_skill",
        "description": (
            "GSA feedback-loop tool. When you successfully use a skill from "
            "global_skills.md to solve a problem, call this to increment hits, "
            "refresh last_used, and improve confidence. Frequently validated "
            "skills receive higher priority in future retrieval.\n"
            "Call it after <verify> passes and before GSA archiving."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type":        "string",
                    "description": "Exact skill name: the ## heading text without the '## ' prefix.",
                },
            },
            "required": ["skill_name"],
        },
    },
}


def tool_audit_payload(args: dict) -> str:
    """
    Pre-flight payload audit tool.
    Query historical failures for a tool and return warnings and suggestions.
    """
    tool_name   = args.get("tool_name", "").strip()
    payload_hint = args.get("payload_preview", "").strip()

    if not tool_name:
        return "ERROR: tool_name cannot be empty"

    rows = check_failure(tool_name, args_keywords=payload_hint, limit=3)
    if not rows:
        return f"✓ Audit passed: no historical failures for {tool_name}."

    warning = format_failures_for_prompt(rows)
    return (
        f"⚠ Audit warning: {tool_name} has {len(rows)} historical failure records\n\n"
        f"{warning}\n\n"
        "Suggestion: modify the payload or try a different approach before retrying."
    )


AUDIT_PAYLOAD_SCHEMA = {
    "type": "function",
    "function": {
        "name": "audit_payload",
        "description": (
            "Pre-flight payload audit tool. Before dangerous run_code / run_shell / "
            "run_interactive operations, call this to check similar historical failures. "
            "If matches exist, the system returns failure reasons and modification advice.\n"
            "Use before exploit scripts, shellcode execution, or GDB debugging."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Target tool name: run_code / run_shell / run_interactive.",
                },
                "payload_preview": {
                    "type": "string",
                    "description": "Payload or argument summary for fuzzy matching historical failures.",
                },
            },
            "required": ["tool_name"],
        },
    },
}


__all__ = [
    "AUDIT_PAYLOAD_SCHEMA",
    "BUMP_SKILL_SCHEMA",
    "tool_audit_payload",
    "tool_bump_skill",
]
