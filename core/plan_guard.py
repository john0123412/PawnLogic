"""Plan guard helpers for tool-call authorization."""

import json


PLAN_EXEMPT_TOOLS = {
    "pwn_env",        # Environment probing; no side effects.
    "list_dir",       # Directory listing; no side effects.
    "search_skills",  # P6 skill-pack retrieval; read-only.
    "check_service",  # P6 environment sniffing; read-only.
    # git_op is exempt only for read-only actions; see is_plan_exempt.
}


def is_plan_exempt(tc_buf: dict) -> bool:
    """Allow skipping <plan> when all tool calls are read-only exemptions."""
    for idx in tc_buf:
        name = tc_buf[idx]["name"]
        if name not in PLAN_EXEMPT_TOOLS and name != "git_op":
            return False
        if name == "git_op":
            try:
                args = json.loads(tc_buf[idx]["args"])
                if args.get("action") not in ("status", "log", "diff", "branch"):
                    return False
            except Exception:
                return False
    return True


def tool_call_missing_plan(text_buf: str, tc_buf: dict) -> bool:
    """Return True when a non-exempt tool call was emitted without a plan."""
    if not tc_buf:
        return False
    if is_plan_exempt(tc_buf):
        return False
    return "<plan>" not in text_buf or "</plan>" not in text_buf
