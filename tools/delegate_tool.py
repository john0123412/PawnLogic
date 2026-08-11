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

Shared execution path:
  - Streaming uses core.turn_api.consume_model_stream (same as the main loop).
  - Tool args are resolved with core.tool_executor.resolve_tool_arguments.
  - Tools run through a core.tool_executor.ToolExecutor, so unknown-tool and
    exception handling match the main loop.
  - The capability profile (inherited / read_only / no_shell / custom) narrows
    which registry tools the non-isolated sub-agent may see and execute.

Import cycle avoidance:
  - This module does not import core/session.py at top level.
  - Tool registry snapshots are lazily imported when the tool is called.
"""

import json
import threading
from dataclasses import replace
from config import (
    DEFAULT_MODEL, MODELS, validate_api_key, is_fast_model, find_fast_peer,
)
from core.delegation import (
    AgentBudget,
    AgentResult,
    AgentTask,
    DelegationModelPolicy,
    FailureRecord,
    default_delegation_policy_store,
)
from core import delegation as delegation_events
from core.agent_orchestrator import CancellationToken, SerialAgentOrchestrator
from core.delegation_runtime import (
    CAPABILITY_PROFILES,
    DelegationTaskExecutor,
    SubAgentSession as _SubAgentSession,
    make_sub_executor as _make_sub_executor,
    _tool_map,
    _tools_schema,
    resolve_allowed_tools,
    tool_allowed,
)
from core.model_router import ModelRouter, RoutingDecision
from core.state import (
    state as _runtime_state, get_dynamic_config_value,
)
from core.runtime_context import current_runtime_context
from core.trust import subagent_notice
from utils.ansi      import c, YELLOW, GRAY, GREEN, MAGENTA

__all__ = [
    "CAPABILITY_PROFILES",
    "DELEGATE_TOOL",
    "_make_sub_executor",
    "_tool_map",
    "_tools_schema",
    "resolve_allowed_tools",
    "tool_allowed",
    "tool_delegate_task",
]

# Recursion depth guard.
_delegate_ctx = threading.local()   # .depth tracks delegation depth per thread.
_MAX_DEPTH    = 2                   # Maximum nested sub-agent depth.

# Worker candidate priority list for dual-model routing.
_WORKER_MODEL_CANDIDATES = [
    "ds-v4-flash",
    "claude-haiku",
    "gpt-4.1",
]


def _user_mode() -> bool:
    return bool(_runtime_state.user_mode)

def _select_worker_model(current_model: str = DEFAULT_MODEL) -> str:
    """
    Select the worker model for a delegated sub-task.

    - If current model is already fast-tier, use it directly.
    - If current model is pro-tier, find a fast peer in the same provider.
    - Fallback: first available model in _WORKER_MODEL_CANDIDATES, then DEFAULT_MODEL
    """
    preferred = get_dynamic_config_value("preferred_worker", "auto")
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
# Tool entry point.
# ════════════════════════════════════════════════════════

def _policy_store():
    return default_delegation_policy_store()


def _host_cancellation_token() -> CancellationToken:
    """Project the active turn interrupt into delegated execution."""
    token = CancellationToken()
    try:
        from core.interrupts import interrupted

        if interrupted():
            token.cancel("parent turn interrupted")
    except Exception:
        pass
    return token


def _agent_task_from_arguments(a: dict) -> AgentTask:
    objective = str(a.get("objective") or a.get("task_description") or "")
    capability = a.get(
        "capability_profile",
        a.get("capability", "inherited"),
    )
    allowed_tools = a.get("allowed_tools", a.get("allowlist", ())) or ()
    budget = AgentBudget(
        max_tokens=a.get("max_tokens", 8192),
        max_cost=a.get("max_cost"),
        max_tool_calls=a.get("max_tool_calls", 15),
    )
    return AgentTask(
        objective=objective,
        role=str(a.get("role", "general")),
        instructions=str(a.get("instructions", "")),
        model_requirement=str(a.get("model_requirement", "auto")),
        model_alias=a.get("model_alias"),
        context_mode=str(a.get("context_mode", "selected")),
        capability_profile=str(capability),
        allowed_tools=allowed_tools,
        budget=budget,
    )


def _route_agent_task(
    task: AgentTask,
    *,
    parent_model: str,
    policy: DelegationModelPolicy,
    legacy_arguments: dict,
) -> RoutingDecision:
    new_fields = {
        "objective",
        "role",
        "instructions",
        "model_requirement",
        "model_alias",
        "context_mode",
        "capability_profile",
        "allowed_tools",
        "max_tokens",
        "max_cost",
        "max_tool_calls",
    }
    use_legacy = (
        not new_fields.intersection(legacy_arguments)
        and policy == DelegationModelPolicy()
    )
    if use_legacy:
        selected = _select_worker_model(parent_model)
        return RoutingDecision(
            selected,
            "legacy_auto_fast",
            eligible_models=(selected,),
        )
    return ModelRouter().select(task, parent_model, policy)


def _rejected_result(decision: RoutingDecision) -> str:
    result = AgentResult(
        status="rejected",
        summary=decision.error or "Delegated model request was rejected.",
        model_alias=None,
        routing_reason=decision.reason,
        failures=(
            FailureRecord(
                code=decision.reason,
                message=decision.error or "No eligible delegated model.",
                retryable=False,
            ),
        ),
    )
    return "[Sub-agent rejected]\n" + json.dumps(
        result.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
    )


def _host_parent_context(task: AgentTask):
    """Resolve child context only through the active host RuntimeContext."""
    context = current_runtime_context()
    provider = getattr(context, "context_provider", None)
    if not callable(provider):
        return None
    try:
        return provider(task.context_mode)
    except (TypeError, ValueError):
        return None


def tool_delegate_task(a: dict) -> str:
    """Run a structured delegated task through host-owned model policy."""
    if not str(a.get("objective") or a.get("task_description") or "").strip():
        return "ERROR: task_description is required"
    try:
        task = _agent_task_from_arguments(a)
    except (TypeError, ValueError) as exc:
        return f"ERROR: {exc}"

    verbose = bool(a.get("verbose", False))
    parent_model = str(_runtime_state.current_model or DEFAULT_MODEL)
    policy = _policy_store().load()
    cancellation = _host_cancellation_token()
    decision = _route_agent_task(
        task,
        parent_model=parent_model,
        policy=policy,
        legacy_arguments=a,
    )
    delegation_events.publish_routing_event(decision)
    if decision.model_alias is None:
        delegation_events.publish_delegation_rejected(decision.reason)
        return _rejected_result(decision)
    worker_model = decision.model_alias

    if decision.reason == "preferred_model":
        print(c(MAGENTA, f"  [Delegate] preferred worker: [{worker_model}]"))
    else:
        print(c(YELLOW, f"  [Delegate] worker model: [{worker_model}]"))

    # Recursion depth guard.
    current_depth = getattr(_delegate_ctx, "depth", 0)
    if current_depth >= _MAX_DEPTH:
        delegation_events.publish_delegation_rejected("depth_limit")
        return (
            f"ERROR: maximum delegation depth {_MAX_DEPTH} reached; nested delegation denied.\n"
            f"Use tools directly for this task instead of calling delegate_task again."
        )

    print(c(MAGENTA, f"  [Sub-agent] starting delegated task..."))
    print(c(
        GRAY,
        f"  Task: {task.objective[:80]}"
        f"{'...' if len(task.objective) > 80 else ''}",
    ))
    print(c(
        GRAY,
        f"  Model: {worker_model}  Depth: {current_depth+1}/{_MAX_DEPTH}  "
        f"Limit: {_SubAgentSession.MAX_ITER} iterations  "
        f"Capability: {task.capability_profile}",
    ))
    if _user_mode():
        print(c(YELLOW, subagent_notice(task.capability_profile)))

    effective_tokens = (
        ModelRouter.effective_max_tokens(task, policy)
        or task.budget.max_tokens
    )
    effective_budget = AgentBudget(
        max_tokens=effective_tokens,
        max_cost=ModelRouter.effective_max_cost(task, policy),
        max_tool_calls=task.budget.max_tool_calls,
    )
    effective_task = replace(task, budget=effective_budget)
    parent_context = (
        None if cancellation.cancelled else _host_parent_context(effective_task)
    )

    def _started(child_agent_id: str) -> None:
        delegation_events.publish_delegation_started(
            effective_task,
            decision,
            child_agent_id=child_agent_id,
            effective_tokens=effective_tokens,
        )

    executor = DelegationTaskExecutor(
        worker_model,
        context_envelope=parent_context,
        session_factory=_SubAgentSession,
        on_started=_started,
    )

    _delegate_ctx.depth = current_depth + 1
    try:
        orchestration = SerialAgentOrchestrator(executor).run(
            (effective_task,),
            budget=effective_budget,
            cancellation=cancellation,
        )
    finally:
        _delegate_ctx.depth = current_depth
    agent_result = replace(
        orchestration.results[0],
        model_alias=orchestration.results[0].model_alias or worker_model,
        routing_reason=(
            orchestration.results[0].routing_reason or decision.reason
        ),
    )
    sub = executor.subagent
    child_agent_id = executor.child_agent_id or "delegated-agent"

    # Report tool-call summary.
    tool_log = tuple(getattr(sub, "_tool_log", ())) if sub is not None else ()
    if tool_log:
        tool_summary = "\n".join(tool_log[-10:])
        print(c(GRAY, f"\n  [Sub-agent tool-call summary]\n{tool_summary}"))

    delegation_events.publish_delegation_result(agent_result, child_agent_id)

    print(c(
        GREEN,
        f"  [Sub-agent] {agent_result.status}, result length: "
        f"{len(agent_result.summary)} chars",
    ))
    metadata = (
        f"Model: {worker_model}\n"
        f"Routing: {decision.reason}\n"
        f"Usage: prompt={agent_result.usage.prompt_tokens}, "
        f"completion={agent_result.usage.completion_tokens}, "
        f"tools={agent_result.usage.tool_calls}"
    )
    structured = json.dumps(
        agent_result.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
    )

    if verbose:
        return (
            f"[Sub-agent {agent_result.status}]\n"
            f"{metadata}\n"
            f"Structured: {structured}\n"
            f"--- Tool-call log ---\n"
            f"{chr(10).join(tool_log) or '(no tool calls)'}\n\n"
            f"--- Final result ---\n"
            f"{agent_result.summary}"
        )
    return (
        f"[Sub-agent {agent_result.status}]\n{metadata}\n"
        f"Structured: {structured}\n{agent_result.summary}"
    )

# ════════════════════════════════════════════════════════
# Schema
# ════════════════════════════════════════════════════════

DELEGATE_SCHEMA = {
    "type": "function",
    "function": {
        "name":        "delegate_task",
        "description": (
            "Delegate a complex subtask to a fresh-context sub-agent.\n"
            "The sub-agent has independent context, uses a host-authorized model "
            "and capability profile, and returns a compact structured result.\n"
            "The main agent context does not grow with subtask tool-call details.\n"
            "Use for one module of a large refactor, independent search-and-summarize work,\n"
            "multi-step test flows, reading long code files, analyzing large logs, or deep web search.\n"
            "model_alias is a request only; host visibility, user policy, and budgets remain authoritative."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_description": {
                    "type":        "string",
                    "description": "Detailed subtask description; be as specific as possible.",
                },
                "role": {
                    "type": "string",
                    "description": "Focused worker role, for example security-reviewer.",
                },
                "instructions": {
                    "type": "string",
                    "description": (
                        "Additional task instructions. These remain below host "
                        "safety policy and cannot grant authorization."
                    ),
                },
                "model_requirement": {
                    "type": "string",
                    "enum": ["auto", "fast", "reasoning", "vision", "same", "same_provider"],
                    "description": "Requested model capability or routing mode.",
                },
                "model_alias": {
                    "type": "string",
                    "description": (
                        "Optional visible Model Alias request; the host may reject "
                        "it under user policy or budget."
                    ),
                },
                "context_mode": {
                    "type": "string",
                    "enum": ["selected", "minimal", "none"],
                    "description": "Parent context selection policy.",
                },
                "capability": {
                    "type":        "string",
                    "enum":        ["inherited", "read_only", "no_shell", "custom"],
                    "description": (
                        "Tool permission profile for the non-isolated sub-agent. "
                        "'inherited' (default) grants all parent tools; 'read_only' "
                        "removes shell/code execution and filesystem writes; "
                        "'no_shell' removes only shell/code execution."
                    ),
                },
                "allowed_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional additional Tool allowlist intersected with the "
                        "capability profile."
                    ),
                },
                "max_tokens": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Per-task token ceiling, capped by user policy.",
                },
                "max_cost": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Per-task cost ceiling, capped by user policy.",
                },
                "max_tool_calls": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Per-task Tool Call ceiling.",
                },
                "verbose": {
                    "type":        "boolean",
                    "description": "Include the full tool-call log in the result when true (default false).",
                },
            },
            "required": ["task_description"],
        },
    },
}
