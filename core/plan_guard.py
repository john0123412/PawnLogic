"""Plan guard helpers for tool-call authorization."""

import json


PLAN_EXEMPT_TOOLS = {
    "pwn_env",         # Environment probing; no side effects.
    "list_dir",        # Directory listing; no side effects.
    "read_file",       # File reading; no side effects.
    "read_file_lines", # Chunked file reading; no side effects.
    "search_skills",   # P6 skill-pack retrieval; read-only.
    "check_service",   # P6 environment sniffing; read-only.
    "web_search",      # Information retrieval; no local side effects.
    "web_fetch",       # URL fetch gated by Network Policy; read-only locally.
    # git_op is exempt only for read-only actions; see is_plan_exempt.
}

# Appended to each executed tool result of a plan-missing batch. The notice
# must never claim the call was intercepted or blocked: in soft mode the tool
# really ran, and a signal contradicted by the visible result teaches weak
# models to ignore it.
TOOL_PLAN_NOTICE = (
    "[SYSTEM: This result was produced WITHOUT a <plan> block. Your next "
    "response MUST start with <plan><intent>...</intent></plan> before any "
    "further tool call.]"
)

# Batch-level reminder appended after a plan-missing batch. Wording must not
# contradict observable reality: in soft mode the tools really executed, so
# claiming they were "intercepted" teaches weak models to ignore the signal.
PLAN_MISSING_SIGNAL = (
    "[SYSTEM: PLAN_MISSING — your previous tool calls ran WITHOUT a <plan> block]\n"
    "The executor requires a <plan> block before tool usage.\n"
    "Recovery: start your next response with "
    "<plan><intent>your original intent</intent></plan>, then continue. "
    "Do NOT apologize or repeat previous text."
)


def with_plan_notice(content: str, *, flagged: bool) -> str:
    """Append the plan reminder to one tool result when the batch lacked a plan."""
    if not flagged:
        return content
    return f"{content}\n\n{TOOL_PLAN_NOTICE}"


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
