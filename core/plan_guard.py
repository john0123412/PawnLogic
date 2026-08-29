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

# A model that answers a correction signal with only a complete plan has not
# produced a usable turn result. Recover a small, fixed number of times before
# stopping rather than silently treating the plan as the final answer.
MAX_PLAN_ONLY_RECOVERIES = 2

# Appended to each executed tool result of a plan-missing batch. The notice
# must never claim the call was intercepted or blocked: in soft mode the tool
# really ran, and a signal contradicted by the visible result teaches weak
# models to ignore it.
TOOL_PLAN_NOTICE = (
    "[SYSTEM: This result was produced WITHOUT a <plan> block. Your next "
    "response MUST start with <plan><intent>...</intent></plan> before any "
    "further tool call, then immediately use the current provider's tool "
    "interface. Do NOT output only a plan.]"
)

# Batch-level reminder appended after a plan-missing batch. Wording must not
# contradict observable reality: in soft mode the tools really executed, so
# claiming they were "intercepted" teaches weak models to ignore the signal.
PLAN_MISSING_SIGNAL = (
    "[SYSTEM: PLAN_MISSING — your previous tool calls ran WITHOUT a <plan> block]\n"
    "The executor requires a <plan> block before tool usage.\n"
    "Recovery: start your next response with "
    "<plan><intent>your original intent</intent></plan>, then immediately "
    "continue through the current provider's tool interface. Do NOT output "
    "only a plan, apologize, or repeat previous text."
)

PLAN_ONLY_RECOVERY_SIGNAL = (
    "[SYSTEM: PLAN_ONLY_RECOVERY]\n"
    "You supplied a complete <plan> but did not invoke a tool or provide a "
    "final answer. The plan is saved in the conversation history.\n"
    "In your next response, immediately continue the pending action through "
    "the current provider's tool interface. Do NOT output another plan by "
    "itself. If no tool is needed, provide a normal final answer."
)

PLAN_ONLY_RECOVERY_LIMIT_SIGNAL = (
    "[SYSTEM: PLAN_ONLY_RECOVERY_LIMIT]\n"
    "Automatic execution stopped because the model repeatedly returned a plan "
    "without an action or final answer."
)


def build_plan_only_assistant_message(
    text_buf: str,
    reasoning_buf: str,
) -> dict[str, str]:
    """Build the non-terminal history entry for a complete plan response."""
    message = {"role": "assistant", "content": text_buf}
    if reasoning_buf:
        message["reasoning_content"] = reasoning_buf
    return message


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


def is_plan_only_response(text_buf: str, tc_buf: dict) -> bool:
    """Return whether a response consists only of one or more complete plan blocks.

    A plan followed by visible natural language is a normal final response, and
    a plan paired with either native or text-fallback tool calls is actionable.
    Only a trimmed response that starts with ``<plan>`` and ends with
    ``</plan>`` requires recovery.
    """
    if tc_buf:
        return False
    remaining = text_buf.strip()
    while remaining:
        if not remaining.startswith("<plan>"):
            return False
        closing_tag = remaining.find("</plan>")
        if closing_tag < 0:
            return False
        remaining = remaining[closing_tag + len("</plan>"):].strip()
    return bool(text_buf.strip())
