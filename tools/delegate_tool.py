"""
tools/delegate_tool.py - fresh-context subtask delegation.

delegate_task(task_description):
  - Instantiates a fresh _SubAgentSession in the background.
  - Runs a full agentic loop silently while tool side effects still occur.
  - Captures tool logs and the final response, then returns a compact result.
  - Keeps the main session context from growing with subtask details.

Dual-model routing:
  - Subtasks use a fast/low-cost worker model.
  - Candidate order: ds-v4-flash -> claude-haiku -> gpt-4.1.
  - The code selects the first available worker model; the main model does not choose it.

Import cycle avoidance:
  - This module does not import core/session.py at top level.
  - TOOL_MAP and TOOLS_SCHEMA are lazily imported when the tool is called.
  - _sub_stream() uses core/api_client.stream_request directly.
"""

import io, json, contextlib, threading
from datetime import datetime
from config import (
    DYNAMIC_CONFIG, DEFAULT_MODEL, MODELS, validate_api_key, is_fast_model, find_fast_peer,
)
from core.api_client import stream_request, ensure_tool_call_id
from core.memory     import _gen_id
from tools.file_ops  import _session_cwd
from utils.ansi      import c, YELLOW, GRAY, GREEN, MAGENTA

# Recursion depth guard.
_delegate_ctx = threading.local()   # .depth tracks delegation depth per thread.
_MAX_DEPTH    = 2                   # Maximum nested sub-agent depth.

# Worker candidate priority list for dual-model routing.
_WORKER_MODEL_CANDIDATES = [
    "ds-v4-flash",
    "claude-haiku",
    "gpt-4.1",
]

def _select_worker_model(current_model: str = DEFAULT_MODEL) -> str:
    """
    Select the worker model for a delegated sub-task.

    - If current model is already fast-tier, use it directly.
    - If current model is pro-tier, find a fast peer in the same provider.
    - Fallback: first available model in _WORKER_MODEL_CANDIDATES, then DEFAULT_MODEL
    """
    preferred = DYNAMIC_CONFIG.get("preferred_worker", "auto")
    if preferred and preferred != "auto":
        if preferred in MODELS:
            ok, _ = validate_api_key(preferred)
            if ok:
                return preferred

    # Already fast; no point switching.
    if is_fast_model(current_model):
        ok, _ = validate_api_key(current_model)
        if ok:
            return current_model

    # Pro model: find fast peer in the same provider.
    peer = find_fast_peer(current_model)
    if peer:
        return peer

    # Cross-provider fallback
    for alias in _WORKER_MODEL_CANDIDATES:
        if alias not in MODELS:
            continue
        ok, _ = validate_api_key(alias)
        if ok:
            return alias
    return DEFAULT_MODEL

# ════════════════════════════════════════════════════════
# Lazy imports to avoid a cycle with session.py.
# ════════════════════════════════════════════════════════

def _tool_map():
    """Import session.TOOL_MAP only when called, after the import cycle is gone."""
    from core.session import TOOL_MAP
    return TOOL_MAP

def _tools_schema():
    from core.session import TOOLS_SCHEMA
    return TOOLS_SCHEMA

# ════════════════════════════════════════════════════════
# Sub-agent session running silently.
# ════════════════════════════════════════════════════════

class _SubAgentSession:
    """
    Lightweight sub-agent with only system + task messages.
    It does not share state with the main session. Tool side effects are real,
    but stdout is captured.
    """

    MAX_ITER = 15   # Hard cap to prevent infinite loops.

    def __init__(self, task: str, model_alias: str = DEFAULT_MODEL):
        self.session_id  = "sub_" + _gen_id()
        self.model_alias = model_alias

        # Inherit important facts from the parent agent.
        inherited_ctx = ""
        try:
            from core.memory import search_facts, format_facts_for_prompt
            # Take up to 5 high-priority facts (priority >= 2).
            rows = search_facts(query="", priority_min=2, limit=5)
            if rows:
                inherited_ctx = (
                    "\n[Inherited Context from Parent Agent]\n"
                    + format_facts_for_prompt(rows, max_chars=400)
                    + "\n"
                )
        except Exception:
            inherited_ctx = ""

        self.messages: list = [
            {
                "role":    "system",
                "content": (
                    "You are a focused sub-agent executing ONE specific delegated task.\n"
                    "Complete the task thoroughly using available tools.\n"
                    f"Working directory: {_session_cwd[0]}\n"
                    f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                    f"{inherited_ctx}\n"
                    "Rules:\n"
                    "- Use tools as needed. Be thorough.\n"
                    "- When done, return a concise summary of what was accomplished.\n"
                    "- Do NOT explain your plan, just act.\n"
                    "- Do NOT call delegate_task again (no nested delegation allowed).\n"
                ),
            },
            {"role": "user", "content": task},
        ]
        self._tool_log: list[str] = []

    def run(self) -> str:
        """
        Run the agentic loop silently.
        stdout is redirected while tool calls still execute normally.
        Returns the final text response from the sub-agent.
        """
        tool_map    = _tool_map()
        # Prevent nested delegation by removing delegate_task from the schema.
        tools_sch   = [s for s in _tools_schema()
                       if s.get("function", {}).get("name") != "delegate_task"]
        cap         = io.StringIO()

        for iteration in range(self.MAX_ITER):
            text_buf = ""; tc_buf: dict = {}

            # Redirect stdout to hide tool-call prints.
            with contextlib.redirect_stdout(cap):
                for delta in stream_request(
                    self.messages, self.model_alias,
                    tools_schema=tools_sch,
                    max_tokens=min(DYNAMIC_CONFIG["max_tokens"], 8192),
                ):
                    if "_error" in delta:
                        return f"[Sub-agent error] {delta['_error']}"
                    choices = delta.get("choices", [])
                    if not choices:
                        continue
                    d     = choices[0].get("delta", {})
                    chunk = d.get("content") or ""
                    text_buf += chunk
                    for tcd in d.get("tool_calls", []):
                        idx = tcd.get("index", 0)
                        if idx not in tc_buf:
                            tc_buf[idx] = {
                                "id":   ensure_tool_call_id(tcd, iteration, idx),
                                "name": "",
                                "args": "",
                            }
                        fn = tcd.get("function", {})
                        tc_buf[idx]["name"] += fn.get("name", "")
                        tc_buf[idx]["args"] += fn.get("arguments", "")

            # No tool call means the subtask is done.
            if not tc_buf:
                return text_buf.strip() or "(sub-agent returned no output)"

            # Append assistant message.
            self.messages.append({
                "role":    "assistant",
                "content": text_buf or None,
                "tool_calls": [
                    {
                        "id":       tc_buf[i]["id"],
                        "type":     "function",
                        "function": {
                            "name":      tc_buf[i]["name"],
                            "arguments": tc_buf[i]["args"],
                        },
                    }
                    for i in sorted(tc_buf)
                ],
            })

            # Execute tools.
            for i in sorted(tc_buf):
                tc   = tc_buf[i]; name = tc["name"]
                try:    fn_args = json.loads(tc["args"]) if tc["args"].strip() else {}
                except Exception: fn_args = {}

                self._tool_log.append(f"  [{iteration+1}] {name}({list(fn_args.keys())})")

                if name in tool_map:
                    result = tool_map[name](fn_args)
                else:
                    result = f"ERROR: unknown tool '{name}'"

                limit = min(DYNAMIC_CONFIG["tool_max_chars"], 6000)
                if len(result) > limit:
                    result = result[:limit//2] + "\n...[truncated]...\n" + result[-500:]

                self.messages.append({
                    "role":         "tool",
                    "tool_call_id": tc["id"],
                    "content":      result,
                })

        return f"[Sub-agent hit max_iter={self.MAX_ITER}]"

# ════════════════════════════════════════════════════════
# Tool entry point.
# ════════════════════════════════════════════════════════

def tool_delegate_task(a: dict) -> str:
    """
    Entry point for delegated subtasks.
    Called from the main session, executes a full subtask, then returns a compact result.

    Dual-model routing ignores caller-provided model_alias and selects the first
    available fast worker model from the candidate list.
    """
    task        = a.get("task_description", "").strip()
    caller_model = a.get("model_alias", DEFAULT_MODEL)
    verbose     = bool(a.get("verbose", False))

    if not task:
        return "ERROR: task_description is required"

    # Dual-model routing: pro -> fast peer, fast -> itself.
    worker_model = _select_worker_model(caller_model)
    _preferred = DYNAMIC_CONFIG.get("preferred_worker", "auto")
    if _preferred and _preferred != "auto":
        print(c(MAGENTA,
            f"  [Delegate] preferred worker forced: [{worker_model}]"
        ))
    else:
        print(c(YELLOW,
            f"  [Delegate] worker model: [{worker_model}]"
        ))

    # Recursion depth guard.
    current_depth = getattr(_delegate_ctx, "depth", 0)
    if current_depth >= _MAX_DEPTH:
        return (
            f"ERROR: maximum delegation depth {_MAX_DEPTH} reached; nested delegation denied.\n"
            f"Use tools directly for this task instead of calling delegate_task again."
        )

    print(c(MAGENTA, f"  [Sub-agent] starting delegated task..."))
    print(c(GRAY,    f"  Task: {task[:80]}{'...' if len(task)>80 else ''}"))
    print(c(GRAY,    f"  Model: {worker_model}  Depth: {current_depth+1}/{_MAX_DEPTH}  Limit: {_SubAgentSession.MAX_ITER} iterations"))

    sub    = _SubAgentSession(task, worker_model)

    _delegate_ctx.depth = current_depth + 1
    try:
        result = sub.run()
    finally:
        _delegate_ctx.depth = current_depth

    # Report tool-call summary.
    if sub._tool_log:
        tool_summary = "\n".join(sub._tool_log[-10:])
        print(c(GRAY, f"\n  [Sub-agent tool-call summary]\n{tool_summary}"))

    print(c(GREEN, f"  [Sub-agent] complete, result length: {len(result)} chars"))

    if verbose:
        return (
            f"[Sub-agent complete]\n"
            f"--- Tool-call log ---\n"
            f"{chr(10).join(sub._tool_log) or '(no tool calls)'}\n\n"
            f"--- Final result ---\n"
            f"{result}"
        )
    else:
        return f"[Sub-agent complete]\n{result}"

# ════════════════════════════════════════════════════════
# Schema
# ════════════════════════════════════════════════════════

DELEGATE_SCHEMA = {
    "type": "function",
    "function": {
        "name":        "delegate_task",
        "description": (
            "Delegate a complex subtask to a fresh-context sub-agent.\n"
            "The sub-agent has independent context, can use all tools, and returns only a compact result.\n"
            "The main agent context does not grow with subtask tool-call details.\n"
            "Use for one module of a large refactor, independent search-and-summarize work,\n"
            "multi-step test flows, reading long code files, analyzing large logs, or deep web search.\n"
            "The worker model is selected automatically for cost control; do not specify it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_description": {
                    "type":        "string",
                    "description": "Detailed subtask description; be as specific as possible.",
                },
                # model_alias was removed; worker selection is controlled by code.
                "verbose": {
                    "type":        "boolean",
                    "description": "Include the full tool-call log in the result when true (default false).",
                },
            },
            "required": ["task_description"],
        },
    },
}
