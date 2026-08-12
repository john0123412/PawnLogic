# ADR 0008: Delegation Runtime Owns Model-Routed Agent Tasks

## Status

Accepted

## Context

PawnLogic already has a synchronous `delegate_task` Tool in
`tools/delegate_tool.py`. It creates a fresh `_SubAgentSession`, chooses a
worker Model Alias, builds a small system prompt, filters a Tool Registry
snapshot by capability profile, reuses the normal Provider stream consumer,
and returns a compact text result. The current implementation has useful
compatibility behavior, but its Interface is implicit and its responsibilities
are concentrated in one Tool handler:

- The public Tool schema accepts `task_description`, `capability`, and
  `verbose`; it does not expose a `model_alias` request even though the
  handler reads one from raw arguments.
- Worker routing uses `preferred_worker`, the current model's fast-tier
  status, a same-Provider fast peer, a fixed cross-Provider candidate list,
  and finally `DEFAULT_MODEL`. Key availability, Provider activity, model
  capability, user policy, cost, and wall-clock budget are not one explicit
  routing contract.
- Prompt construction is fixed in the handler. A delegated task can provide
  a description, but not a structured role, focused instructions, context
  references, or an explicit model requirement.
- The child inherits up to five high-priority persistent facts and otherwise
  receives a fresh message list. Context selection, secret handling, parent
  linkage, and result evidence are not typed.
- Execution is synchronous with a hard `MAX_ITER` limit. Token, Provider-call,
  cost, wall-clock, deadline, and cancellation budgets are not represented in
  the task or result contract.
- The child sees a capability-filtered Registry snapshot and executes real
  Tool side effects in the host process. The current `delegate_task` Tool is
  excluded from the child map, but there is no general Delegation Runtime
  boundary that prevents a future child implementation from bypassing host
  policy.

The 0.3.0 architecture plan calls for a Delegation Runtime that is shared by
the parent Agent, CLI commands, future orchestration, and UI adapters. The
runtime must allow a parent prompt to request another eligible model without
allowing the model to choose outside the user's policy. It must also preserve
the current automatic fast-worker behavior while the contract is introduced.

This ADR defines the stable Interfaces and invariants. It does not introduce
parallel execution, a task graph, a shared blackboard, or a new Provider
transport.

## Decision

Introduce a Delegation Runtime Module with five responsibility boundaries:

1. `AgentTask` is the validated input value object.
2. `AgentResult` is the structured output value object.
3. `DelegationPolicy` is the host-owned authorization and budget policy.
4. `ModelRouter` selects an eligible Model Alias and explains the decision.
5. `DelegationExecutor` composes the child Turn, executes it, and enforces the
   policy through existing host Interfaces.

The first implementation may place these Interfaces in `core/delegation.py`
and `core/model_router.py`, or in an equivalent ownership-focused package.
`tools/delegate_tool.py` remains an Adapter and must not remain the owner of
routing, prompt policy, context selection, or execution semantics.

### AgentTask

`AgentTask` is an immutable, host-validated request. Its fields are the
minimum information needed to run one delegated objective:

```python
@dataclass(frozen=True)
class AgentBudget:
    max_iterations: int = 15
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_provider_calls: int = 15
    max_wall_seconds: float = 900.0
    deadline: float | None = None
    max_cost: float | None = None

@dataclass(frozen=True)
class AgentTask:
    task_id: str
    objective: str
    role: str = "general"
    instructions: str = ""
    model_requirement: str = "auto"
    model_alias: str | None = None
    strict_model_request: bool = False
    context_mode: str = "selected"
    context_refs: tuple[str, ...] = ()
    capability_profile: str = "inherited"
    allowed_tools: tuple[str, ...] = ()
    budget: "AgentBudget" = AgentBudget()
    parent_task_id: str | None = None
    root_task_id: str | None = None
    depth: int = 0
```

The exact serialization may use a versioned mapping, but the semantic fields
are stable. The implementation must validate:

- non-empty objective and bounded role/instruction lengths;
- canonical task, parent, and root identifiers;
- a supported `context_mode` and capability profile;
- tool names against the host Registry snapshot;
- a non-negative depth within the host maximum;
- budgets within host maximums before any Provider request or Tool execution.

`instructions` are task guidance, not a replacement for the host system
prompt. They may request another Model Alias or a role-specific strategy, but
they cannot grant capabilities, alter policy, expose secrets, or authorize
network or destructive operations.

`model_requirement` expresses a capability or routing preference such as
`auto`, `fast`, `reasoning`, `vision`, or `same_provider`. `model_alias` is a
request, not an authority. A strict caller may request that rejection of an
explicit alias fail the task; the default compatibility path is predictable
fallback with an observable reason.

`context_refs` names bounded, host-resolved references. They are not arbitrary
file paths or a copy of the parent message list. The Context Manager and
RuntimeContext own resolution and redaction when those Interfaces are
introduced.

`AgentBudget` is a frozen value object containing the limits relevant to one
task, at minimum:

- maximum iterations;
- maximum output/input tokens when the Provider reports them;
- maximum Provider calls;
- maximum wall-clock seconds and an absolute deadline;
- maximum estimated or recorded cost;
- cancellation state or a cancellation token reference.

The host may tighten any requested budget. A child cannot increase the
effective budget by editing task instructions or by returning a new task.

### AgentResult

`AgentResult` is the only result boundary between a child and its parent. It
must be immutable after completion and serializable without raw Provider
objects or unredacted credentials:

```python
@dataclass(frozen=True)
class AgentResult:
    task_id: str
    parent_task_id: str | None
    root_task_id: str
    status: str
    summary: str
    model_alias: str | None
    selected_by: str | None
    routing_reason: str | None
    artifacts: tuple["ArtifactRef", ...]
    evidence: tuple["EvidenceRef", ...]
    failures: tuple["FailureRecord", ...]
    usage: "AgentUsage"
```

`status` is one of a documented finite set, including at least `completed`,
`failed`, `cancelled`, `timed_out`, `budget_exhausted`, and `rejected`.
`summary` is bounded and redacted. Artifacts and evidence are references with
ownership, relative location, media/type metadata, and provenance; they are
not an unbounded transcript dump. `AgentUsage` records available token,
Provider-call, duration, and cost counters without requiring a Provider to
support every counter.

Routing metadata is part of the result even when the selected model is the
current model. `selected_by` identifies the routing rule, for example
`explicit_alias`, `requirement`, `same_provider_peer`, `user_preferred_worker`,
`automatic_fast_worker`, `current_model_fallback`, or `default_fallback`.
`routing_reason` is a stable machine-readable reason code plus safe human
detail. Rejected candidates and the policy that rejected them are recorded in
the result's failure or routing evidence, without recording API keys or full
prompts.

### DelegationPolicy

`DelegationPolicy` is created and owned by the host. It is not supplied by the
child model and cannot be weakened by `AgentTask.instructions`:

```python
@dataclass(frozen=True)
class DelegationPolicy:
    allowed_model_aliases: frozenset[str] = frozenset()
    denied_model_aliases: frozenset[str] = frozenset()
    default_mode: str = "auto"
    max_depth: int = 2
    max_concurrency: int = 1
    max_iterations: int = 15
    max_provider_calls: int = 15
    max_wall_seconds: float = 900.0
    max_tokens: int | None = None
    max_cost: float | None = None
    allow_nested_delegation: bool = False
    allow_network: bool = False
    allow_destructive: bool = False
```

The concrete persistence format is a Runtime Home configuration contract and
must be updated atomically. Empty `allowed_model_aliases` means the host's
normal visible-model policy, not an unrestricted provider catalogue. An
explicit allowlist narrows that visible set. Deny rules always win. The
effective model set is the intersection of:

1. the live `/model` visibility rules (active Provider and configured key);
2. user allow/deny policy;
3. requested model capability and `model_requirement`;
4. task and parent remaining budgets; and
5. any host trust or execution policy.

The policy also owns maximum depth, cancellation, deadlines, and Tool
capabilities. `allow_network` and `allow_destructive` are not sufficient by
themselves to authorize an operation: the shared `OperationPolicy`, trust
boundary, path policy, Engagement Scope where applicable, and Tool Registry
phase checks still apply.

### ModelRouter

`ModelRouter` is a pure or side-effect-free host Interface over provider/model
snapshots and `DelegationPolicy`:

```python
class ModelRouter(Protocol):
    def select(
        self,
        task: AgentTask,
        parent_model_alias: str,
        policy: DelegationPolicy,
    ) -> "ModelSelection": ...
```

`ModelSelection` contains the selected alias, Provider, selected-by value,
reason code, rejected candidates, and a safe display reason. It does not make
an API call and does not trust a model-generated request as authorization.

Candidate selection is deterministic and follows this order:

1. If `model_alias` is explicit, validate it against visible models, user
   allow/deny policy, Provider key/activity, capability, and remaining budget.
   Select it when valid. If invalid, fail with `strict_model_request` or
   continue through the documented fallback path with a rejection reason.
2. Match `model_requirement` to eligible model capabilities. A requirement such
   as `reasoning`, `vision`, or `fast` must not silently select an incompatible
   model.
3. If the effective mode requests provider affinity, prefer an eligible fast
   peer from the parent model's Provider.
4. Apply the user-configured preferred worker and explicit model allowlist,
   preserving stable configuration order.
5. Remove candidates that exceed token, Provider-call, cost, depth, deadline,
   or wall-clock limits.
6. Use the current parent model only when it remains eligible under all of the
   same checks.
7. Use the configured default fallback only when it is eligible. Otherwise
   return a rejected selection; never manufacture a model or bypass visibility
   to force execution.

The compatibility Adapter must preserve the current automatic order when a
legacy request has no new model fields: `preferred_worker`, current fast model,
same-Provider fast peer, `_WORKER_MODEL_CANDIDATES`, then `DEFAULT_MODEL`.
The new router may express the same outcome with richer reasons, but it must
not change the default selected Model Alias until a deliberate compatibility
change is documented and tested.

### DelegationExecutor

`DelegationExecutor` owns one delegated Turn after routing:

```python
class DelegationExecutor(Protocol):
    def run(
        self,
        task: AgentTask,
        parent: "RuntimeContext",
        policy: DelegationPolicy,
    ) -> AgentResult: ...
```

The executor performs these steps in order:

1. Validate task identity, depth, cancellation, and effective budgets.
2. Ask `ModelRouter` for a `ModelSelection`.
3. Resolve a bounded `ContextEnvelope` from selected `context_refs` and
   parent RuntimeContext state. Include only the minimum objective context,
   relevant facts, necessary Tool results, and explicit evidence references.
4. Construct child messages with immutable host system instructions and safety
   policy first, then bounded role guidance, task instructions, selected
   context, and the objective. Parent instructions cannot replace or reorder
   the host policy.
5. Derive Tool visibility as the intersection of Registry phase, enabled
   Extension ownership, capability profile, explicit task allowlist, and
   OperationPolicy/trust decisions. Build the child `ToolExecutor` from this
   snapshot; do not hand a child raw handler maps or provider credentials.
6. Execute one child agent loop through the existing Provider stream and Tool
   execution Interfaces, recording usage, failures, Tool results, and
   cancellation checks against the effective deadline and budget.
7. Redact and normalize the final response into `AgentResult`, preserving
   parent/root linkage and artifacts/evidence references.

The first implementation is strictly serial: one `run()` call owns one child
loop and blocks until it completes, fails, is cancelled, or reaches a limit.
It must not create implicit threads, async tasks, background workers, or a
shared task graph. `max_concurrency` is fixed to one in the initial runtime;
values greater than one are rejected or clamped by host policy with an
observable reason. Parallel execution is a later decision requiring isolated
RuntimeContext and Output Sink state, explicit Workspace ownership,
serialized or conflict-checked side effects, atomic budgets, and proven child
process cleanup.

### Prompt and host-policy boundary

The delegated model may produce a request such as “use model X for the next
subtask” or may receive parent-provided instructions naming another model.
That request is data consumed by the host `ModelRouter`. It is never a direct
Provider call and never changes `DelegationPolicy`.

The child agent must not:

- call a Provider client directly or read Provider API keys;
- mutate the live Provider/model registry or user model policy;
- register, enable, or replace Tools or Extensions;
- bypass `ToolExecutor`, `OperationPolicy`, `PathPolicy`, trust boundaries,
  phase checks, or Engagement Scope validation;
- call `delegate_task` recursively unless a future policy explicitly enables
  nested delegation after separate isolation and budget review;
- expand its context, Tool allowlist, deadline, or budget from inside the child
  prompt.

Host system instructions, safety policy, and the effective Tool/policy
snapshot are always prepended and enforced by the executor. A child can be
denied even when its instructions appear to authorize the operation. Network
security work additionally requires a valid Engagement Scope and the shared
network/operation policy; a delegated prompt alone is never scope.

### Failure, fallback, and cancellation

Routing failures are explicit. A missing key, inactive Provider, denied alias,
unsupported capability, exhausted budget, invalid depth, or expired deadline
produces a rejection or a fallback record with a stable reason code. The
runtime must never silently substitute an ineligible model.

Execution failures are normalized into `AgentResult` and classified as
`failed`, `timed_out`, `cancelled`, or `budget_exhausted`. Partial text may be
retained in the bounded summary, but raw Provider errors, credentials, and
unbounded child transcripts are not returned to the parent. Tool failures use
the existing ToolResult and host error envelopes. A failed child must not
commit partial Extension/Tool registration or mutate parent message history.

Fallback is allowed only before irreversible child side effects begin. The
host may retry a Provider request or select the next eligible model when the
retry policy and remaining budget allow it; it must record the attempted model,
reason, and usage. Once a child has executed a mutating Tool, the executor
must not transparently replay the task on another model unless the Tool
operation declares replay safety and the host policy permits it.

Cancellation is host-owned. The executor checks cancellation before routing,
before each Provider call, before each Tool call, and at iteration boundaries.
It propagates cancellation to the stream/child process, stops new Tool calls,
cleans up owned processes, and returns `cancelled` with partial usage and
evidence. A timeout returns `timed_out`; exhausting a budget returns
`budget_exhausted`. Both are terminal for that task and cannot be extended by
the child.

## Compatibility migration

`tools/delegate_tool.py` remains a thin compatibility Adapter during the
migration:

1. A legacy argument containing only `task_description`, `capability`,
   `allowlist` when supplied, and `verbose` is translated into an `AgentTask`
   with `model_requirement="auto"`, selected context mode, the equivalent
   capability profile, and the host default budget.
2. The Adapter calls `DelegationExecutor.run()` and converts `AgentResult` to
   the current text envelope: `[Sub-agent complete]` plus the bounded summary;
   `verbose` controls legacy tool-log presentation only.
3. The current automatic worker selection remains the default for requests
   that provide no new model or policy fields. Existing depth, capability, and
   no-nested-delegation behavior remains fail-closed.
4. New structured callers may use `AgentTask` directly. Additive Tool/CLI
   fields for model requirements, explicit Model Alias requests, context
   references, and budgets must be versioned and validated before becoming
   visible in the public schema.
5. The Adapter must not retain a second routing implementation. Once the
   Delegation Runtime is available, `_select_worker_model`, prompt assembly,
   child Tool filtering, and result normalization are delegated to it; any
   temporary compatibility helper is covered by characterization tests.

This preserves the current `delegate_task` behavior while moving the stable
semantics behind a reusable Interface. Deprecation or removal of legacy
arguments requires at least one documented core minor release and updated
contract tests.

## Consequences

The parent Agent, `/worker` compatibility command, future `/agent run` command,
Streamlit Adapter, and later multi-agent orchestration can share one
delegation Interface. Model requests become user-policy-controlled instead of
being implicitly decided by a Tool handler, and routing decisions become
auditable without exposing secrets.

The first implementation adds typed contracts and policy plumbing before it
adds parallelism. This increases the amount of explicit validation and result
metadata, but it prevents child agents from becoming an alternate authority
over Providers, Tools, network scope, or budgets.

The initial executor remains process-local and synchronous. A future isolated
child process or stdio MCP Adapter may implement the same executor boundary
for dependency-heavy or high-risk Extensions, but it must receive only the
validated task/context/policy projection and must return the same structured
result contract.

The durable source of truth for user model policy remains Runtime Home
configuration, written atomically. Provider availability continues to come
from the existing Provider registry and visible-model rules rather than a
second delegation-specific catalogue.

## Verification requirements

The Delegation Runtime implementation must add contract tests for:

- explicit eligible, denied, inactive, missing-key, and incompatible Model
  Alias requests;
- each routing order and its `selected_by`/reason output, including the legacy
  automatic fallback order;
- user allowlist and deny precedence over prompt requests;
- Provider, token, call, cost, depth, deadline, timeout, and cancellation
  limits;
- host instructions remaining ahead of task instructions and task instructions
  being unable to expand Tool visibility;
- minimal selected context, parent/root linkage, bounded structured results,
  redacted artifacts/evidence, and partial failure reporting;
- Tool visibility intersection and refusal to bypass host Tool/operation policy;
- bounded one-or-two-worker execution, no implicit concurrency, no nested
  delegation, and cleanup after cancellation;
- legacy `delegate_task` arguments and text result compatibility.

The ADR itself is documentation-only. Its acceptance does not change the
current version or current public behavior until the planned implementation
and tests are delivered.

## Implementation status

Implemented on the 0.3.0 stacked development branches. `core.delegation` owns
task/result/usage/policy values, `core.model_router` owns model eligibility,
`core.delegation_runtime` owns the bounded child loop, and
`core.agent_orchestrator` owns serial scheduling, cooperative cancellation, and
atomic shared budget claims. `tools.delegate_tool` remains the compatibility
Adapter and keeps its human text envelope while adding task lineage to its
structured result and Agent Events.

The initial implementation deliberately remained serial. The bounded
concurrency-two amendment below supersedes that execution restriction while
retaining the public single-task `delegate_task` Adapter. No task graph is
introduced because there is not yet a public batch caller.

## Amendment: bounded concurrency two

After the initial serial runtime, the implementation may admit at most two
synchronous child tasks when all of these conditions hold:

1. The Delegation Runtime has a forkable parent `RuntimeContext`; each child
   receives a copied context, independent dynamic configuration, unique child
   workspace, task-local output collector, and child cancellation token.
2. Isolated child activation never mirrors legacy process globals. Relative
   child file work and shell defaults resolve to the child workspace; sibling
   task workspaces are denied.
3. A two-worker child may execute only Tool paths proven task-isolated. The
   current allowlist is the file Tool family; shell, container, network, MCP,
   extension, browser, pwn, and sandbox paths fail closed before their handler
   runs.
4. Shared `BudgetLedger` claims remain atomic and are settled after every
   completed, cancelled, timed-out, failed, or invalid result. A task-local
   cancellation never reaches a sibling; host cancellation fans out through
   the parent token.
5. Direct stdout is captured into a bounded task collector. Child events are
   collected locally and forwarded through a thread-safe parent publisher, so
   NDJSON/human sinks cannot be interleaved by worker writes.

`SerialAgentOrchestrator` keeps its legacy name for compatibility but accepts
only `max_concurrency` values one and two. An executor that has not been
configured for two workers must reject accidental parallel calls. The public
`delegate_task` Adapter still submits exactly one task; a persisted policy
value of two never creates implicit work and affects only a supported batch
caller.
