# PawnLogic Project Memory

This file is the compact project memory for maintainers and coding agents. Read
it after `AGENT.md` and before broad planning, code changes, release work, or
multi-file audits.

Keep this file current when a change affects architecture, module ownership,
release direction, public contracts, maintenance risks, or the next planned
tasks. Do not use it as a changelog; `CHANGELOG.md` remains the user-facing
release history.

## Current Release State

- Current public release: `0.3.0` (tag and GitHub Release: `v0.3.0`).
- Runtime version source of truth: `config/paths.py:VERSION`, currently
  `0.3.1` as an unreleased release candidate. Do not create a `v0.3.1` tag,
  publish packages, or create a GitHub Release without explicit authorization.
- Most recent completed plan:
  `docs/plans/0.3.0-extensible-agent-platform-and-security-distribution.md`.
- Active plan:
  `docs/plans/0.3.1-runtime-hardening-and-release-preparation.md`.
  The 0.3.1 candidate contains bounded streaming and file-discovery recovery,
  execution-boundary hardening, and documented release preparation. The
  independent `pawnlogic-security` 0.1.0 package release is described below.
- PR 1 contracts are recorded in commit `7ff8c27`: ADR 0007, ADR 0008, and
  focused delegation/MCP characterization tests.
- The merged 0.3.0 core delivers the Extension Runtime, Extension
  commands/startup, Network Policy, installed-layout security compatibility
  fixture, policy-driven Delegation Runtime, Structured Context Manager,
  bounded provenance-aware knowledge retrieval with SQLite as the durable
  authority, the versioned Agent Event Interface, bounded serial multi-Agent
  orchestration, and the integration/release documentation, CLI Agent help,
  live policy completions, and core distribution gates.
- Merged `main` was verified directly, not only per-branch: 1178 non-E2E tests
  and 8 E2E tests passed, ruff/mypy/docs/release/architecture/index guards
  passed, all three CLI entry points responded, and the wheel/sdist built with
  `twine check` passing and zero `skills/` entries.
- Publishing is gated on more than a successful upload. A production tag must
  point at a commit contained in `main`, the built artifacts are pinned by
  hash, and `tools/release_install_smoke.sh` reinstalls the published
  distribution from the index into a fresh environment to confirm the served
  wheel matches the built wheel, the reported version is correct, and the
  installed `pawn` console script runs. The GitHub Release waits on that smoke,
  so `skip-existing` cannot leave a stale artifact and still report success.
- CI trigger scope is a known past defect: `work/**` branches originally had
  neither a `push` nor a `pull_request` trigger, so stacked PRs reported no
  checks. Both triggers now exist, with `pull_request` alone covering branches
  that have an open PR to avoid duplicate runs.
- `main` remains protected by the classic branch protection rule requiring a
  pull request, up-to-date branches, conversation resolution, and four GitHub
  Actions checks: `🔍 Lint (ruff)`, `📖 Docs Guard`, `🔎 Type Check (mypy)`,
  and `🧪 Fast Tests (Python 3.11)`. Force pushes and deletions are denied and
  the rule applies to admins. A separate tag-target ruleset protects
  `v*.*.*` from deletion or retargeting after creation.
- The independent `pawnlogic-security` distribution now lives at
  `john0123412/pawnlogic-security`. Its MVP was merged to protected `main` at
  `534e9e0`; 192 local tests and the remote Python 3.10/3.11/3.12 oldest/newest
  PawnLogic compatibility matrix pass. It provides scope-gated passive recon,
  bounded active discovery, workflows/evidence, and an optional
  default-disabled child-process adapter. Version `0.1.0` was published from
  protected `main` commit `955da3c` on 2026-07-28: TestPyPI workflow
  `30347824976` passed upload and hash-pinned fresh-install smoke, while
  production workflow `30349110662` passed source/tag/changelog verification,
  PyPI Trusted Publishing, hash-pinned fresh-install smoke, and GitHub Release
  creation for `v0.1.0`.
- `README.md` claiming an unreleased version as public is a fixed past defect.
  `tools/check_release_consistency.py` used to compare the README claim against
  `config/paths.py:VERSION`, so bumping VERSION on a candidate branch made the
  false claim pass. It now compares against the newest `vX.Y.Z` git tag and
  additionally requires both READMEs to name a VERSION ahead of that tag as an
  unreleased release candidate. A reviewed pre-tag finalization may use the
  exact-version `.release-ready` marker; stale markers fail closed and the
  marker is removed after publishing. Untagged trees fall back to VERSION and
  say so.
- Local release artifacts such as `dist/`, `build/`, and `*.egg-info/` should
  not remain after release validation unless a maintainer explicitly asks to
  keep them.

## Product Shape

PawnLogic is a terminal AI agent with:

- multi-provider model routing
- provider and model management through CLI commands and a TUI
- persistent SQLite-backed sessions and memory
- real tool execution with trust boundaries
- MCP integration
- browser automation helpers
- CTF-oriented tooling and optional external skill packs

The installed CLI entry point is `pawn`, implemented by `pawnlogic.cli:run`.
Source checkout compatibility entry points are thin wrappers:

- `python main.py`
- `python -m pawnlogic`
- `./pawn.sh`

Do not duplicate runtime CLI logic into wrappers.

## High-Value Contracts

These contracts are more important than local refactoring convenience:

- DeepSeek is active by default and must not be deactivated.
- Custom providers are inactive by default and become visible only when active
  and configured.
- `/model` and completions show only visible, configured chat models.
- Provider fetch registers only user-selected supported chat models.
- Connection tests use a loaded chat model, not legacy hardcoded defaults.
- Default startup is user-friendly mode and hides raw tool-call internals,
  parser diagnostics, detailed reasoning streams, and low-level API errors.
- `pawn --debug` is the explicit path for detailed terminal diagnostics.
- Public stream delta dicts must remain stable.
- Tool result message shape, assistant message shape, and `reasoning_content`
  persistence rules must remain stable.
- Runtime metrics must not introduce telemetry, network calls, secrets, or
  default terminal noise.
- Web and browser HTTP(S) targets pass through the shared Network Policy:
  credentials, metadata, and special address ranges are denied; private targets
  require explicit authorization; redirects are re-evaluated; non-interactive
  confirmation fails closed.
- Model-provided Tool arguments are untrusted and cannot self-authorize a
  private-network target. Confirmed private targets bypass remote reader
  services.
- Docker bridge/host networking and legacy `uvx mcp-server-fetch` startup use
  capability-only authorization gates. Capability approval is not target
  approval.
- Third-party skill packs must not be included in wheels or sdists by default.
- The repository language scan enforces English outside `_zh-CN` documentation
  while excluding optional source-checkout `skills/` assets. Those assets remain
  governed by attribution and export-ignore rules; first-party source, tests,
  and product documentation do not inherit that exception.
- Proposed Extensions must remain disabled until explicitly enabled; installing
  a distribution is not authorization to load or execute it.
- An enabled Extension may rebuild its contributions through
  `ExtensionManager.recontribute(name)`, which is how a scope-gated Extension
  publishes and withdraws Tools without a disable/enable cycle. `contribute`
  must return the complete current set, never a delta. The swap is atomic: own
  registrations are withdrawn before validation so a rebuild cannot conflict
  with itself, and a rejected rebuild restores the previous set and stays
  ENABLED. Extensions reach it only through `ExtensionContext.recontribute`.
- Proposed network-security Tools require a valid Engagement Scope and shared
  Operation/Network Policy authorization before active work.
- Proposed delegated-model requests are preferences routed by the host; user
  allowlists, Provider visibility, capability checks, and effective budgets
  remain authoritative.
- Delegation policy is persisted atomically under
  `~/.pawnlogic/delegation/policy.json`. Legacy `delegate_task` calls retain
  automatic fast-worker routing; explicit aliases and prompt requests never
  bypass host visibility, policy, Tool capability, or budget checks.
- Structured context uses versioned `ContextState` and `ContextEnvelope`
  contracts. The current state round-trips through the existing pinned
  assistant-message persistence shape; provider payloads receive a rendered
  block, not the JSON carrier. Tool Call groups remain atomic during trimming.
- `ctx_max_chars` triggers selection and `ctx_trim_to` is the target. Protected
  anchors, pins, Tool groups, or structured state are never silently corrupted
  to satisfy the target; an over-budget envelope is explicit.
- Delegated context is resolved through the active host RuntimeContext.
  `none`, `minimal`, and `selected` cannot be forged by Tool arguments, and raw
  parent system messages/full history are not copied to child Providers.
- Delegated tasks and results carry generated task IDs, optional parent task
  IDs, deadlines, and structured token, Tool Call, and cost usage. The serial
  orchestrator admits each task through an atomic shared budget claim and
  supports cooperative cancellation without exposing executor exceptions.
- Multi-Agent execution remains deterministic and serial. Requests for
  concurrency above one fail closed until Workspace and RuntimeContext
  isolation tests pass. A task graph remains deferred until two concrete
  callers require it; `delegate_task` remains the compatibility Adapter.
- Knowledge retrieval uses immutable `KnowledgeRecord`, `KnowledgeQuery`, and
  `RetrievalHit` contracts. `core/knowledge_sqlite.py` owns bounded FTS5 and
  keyword fallback over the authoritative SQLite corpus. Optional vector
  projections can affect ranking only after record ID and revision hydration
  from SQLite; absence, stale metadata, or outage remains non-fatal.
- Knowledge indexing uses revision-aware durable outbox events. Rebuild
  enqueueing runs inside SQLite with `INSERT ... SELECT`, so the process and an
  optional Redis projection never need the complete corpus in memory.
- Agent Events use a versioned immutable `AgentEvent` contract and a
  synchronous process-local publisher. RuntimeContext owns the stream;
  main-session and delegated execution publish structural Turn, retrieval,
  Tool, policy, usage, and delegation events without changing persisted
  messages. Event payloads are recursively redacted before subscribers receive
  them, and subscriber failures do not stop Agent execution.
- Human output keeps its existing transcript. `JsonSink` keeps the existing
  `text`, `chunk`, and `json` NDJSON records and adds a typed `event` record;
  event transport does not require parsing ANSI output.
- The Extension Runtime uses `pawnlogic.extensions` package entry points.
  Discovery reads metadata without loading Extension code; explicit enablement
  owns validation, contribution registration, rollback, persisted state, and
  shutdown. `recontribute` reuses that same validation and ownership path, so
  there is one definition of a valid contribution set.
- `core/extensions.py` owns discovery and lifecycle; `core/extension_contracts.py`
  owns the frozen value/protocol surface shared with external distributions.
  `ExtensionRecontributing` is optional, so Extensions written before it keep
  working and are reported as not supporting rebuilds.
- `tests/test_extension_recontribution.py` protects atomic contribution swaps,
  rollback on a rejected rebuild, re-entrancy refusal, and model visibility.
- `/extension list|status|enable|disable` is the lifecycle command Interface.
  Startup reactivates only persisted enabled names before MCP attachment,
  isolates individual failures, and mounts the manager on RuntimeContext.

## Architecture Map

### CLI And Startup

- `pawnlogic/cli.py` remains the public parser/command facade and owns
  `PawnCompleter` compatibility.
- Live model completions also feed `/agent policy model allow|deny <alias>`;
  static completion inputs must not cache Provider visibility.
- `pawnlogic/startup.py` owns runtime-home, env, proxy, key-readiness, and
  writable-runtime primitives.
- `pawnlogic/repl.py` owns prompt-loop signal state, input restoration, and
  small input/history caches.
- `main.py`, `pawnlogic/__main__.py`, and `pawn.sh` stay thin adapters.
- `tools/cli_transcript_runner.py` owns deterministic maintainer transcript
  checks for slash-command output without starting the full REPL.
- `tests/test_deployment_friendly.py` protects source checkout, installed
  package, entry point, and runtime-data isolation behavior.
- `tests/test_cli_startup.py` protects startup output and mode behavior.
- `tests/test_cli_transcripts.py` protects user-visible transcript output for
  core slash-command flows.

### Session Runtime

- `core/session.py` owns the main turn loop and session orchestration.
- `core/turn_state.py` is an internal per-turn state snapshot, not a public API.
- `core/session_tool_loop.py` owns deterministic tool-batch ordering, guard
  decisions, PLAN correction timing, and explicit internal tool outcomes.
- `core/tool_executor.py` owns single-call execution and failure envelopes;
  public tool message dictionaries remain compatibility contracts.
- `core/session_snapshot.py` is the immutable save/load contract used by both
  manual save and autosave; `core/message_history.py` owns dangling Tool Call
  repair without importing session runtime code.
- `core/persistence.py` is the SQLite adapter for `SessionSnapshot`.
- `core/runtime_metrics.py` is the sole owner of completed, interrupted,
  failed, autosaved, usage, retry, tool, and failure-class counters.
- `core/runtime_context.py` is the authoritative session runtime-state owner for
  cwd, workspace, sink, debug mode, user mode, and dynamic config. A
  `contextvars` activation scope isolates sessions and async tasks; turn and
  command execution activate their owning context.
- `core.state`, `config` output flags, `tools.file_ops` path pointers, and the
  command active sink are compatibility mirrors or fallbacks only. New runtime
  writes go through `RuntimeContext`.
- `core/runtime_metrics.py` owns internal metrics snapshots. Metrics are local
  runtime state only.
- `core/context_manager.py` owns structured state, prompt-budget counting,
  atomic Tool-group selection, versioned state carriers, and bounded host
  projections. `core/context_window.py` retains the old helper exports as
  compatibility Adapters.
- `core/delegation.py` owns immutable delegated task/result/usage/failure and
  model-policy contracts plus atomic policy persistence.
- `core/agent_orchestrator.py` owns cooperative cancellation, atomic shared
  budget claims, structured orchestration results, and the serial Delegation
  Runtime executor seam.
- `core/model_router.py` owns dynamic delegated-model eligibility and routing
  reasons. `core/delegation_runtime.py` owns the bounded child execution loop
  and Tool filtering. `tools/delegate_tool.py` remains the public compatibility
  Adapter.
- `tests/test_session_utils.py` and `tests/test_turn_guards.py` protect turn
  behavior, guard behavior, message ordering, and persistence shape.

### Providers And Models

- `config/providers.py` defines provider metadata and model registry defaults.
- `core/provider_runtime.py` owns shared provider operations such as connection
  testing, fetching models, saving keys, and activation.
- `core/provider_transport.py` owns format-specific HTTP headers, provider
  definition validation, and the `ProviderDefinition` dataclass used before any
  disk or registry mutation.
- `core/commands/provider.py` owns `/provider` and `/model` command semantics.
- `core/provider_tui.py` adapts prompt-toolkit rendering and key bindings.
- `core/provider_tui_state.py` owns deterministic panel, cursor, dialog,
  wizard, search, selection, and status transitions without IO.
- `core/provider_runtime.py` is the shared mutation boundary for CLI and TUI
  provider changes.
- `tests/test_provider_commands.py` is the main provider visibility and command
  regression suite.
- `tests/test_provider_runtime.py` protects shared provider operation behavior.

### API And Streaming

- `core/api_client.py` owns API request orchestration and compatibility entry
  points.
- `core/api_payloads.py` owns provider request payload/header builders and
  reasoning-message sanitization used by `core/api_client.py`.
- `core/provider_streams.py` owns provider-specific stream adapter details while
  preserving the existing public delta dict schema.
- `core/api_errors.py` owns user-facing API error classification and formatting.
- API retry behavior is globally tunable through `PAWNLOGIC_API_RETRY_MAX` and
  `PAWNLOGIC_API_RETRY_AFTER_MAX`; default behavior remains three attempts and
  a ten-second `Retry-After` cap.
- `tests/test_api_stream_helpers.py` and `tests/test_api_errors.py` protect
  stream shape, retry behavior, partial stream recovery, and error formatting.

### Tools, Trust, And Sandboxing

- `core/tool_registry.py` owns complete `ToolSpec` metadata (handler, schema,
  phases, trust, and capabilities). Built-in and MCP tools enter through this
  registry; `TOOL_MAP` and `TOOLS_SCHEMA` are compatibility views only.
- `core/extension_contracts.py` is the stable Extension Interface.
  `core/extensions.py` owns entry-point discovery and Extension lifecycle.
  Tool and command registries record contribution owners and reject Extension
  collisions before mutation.
- `core/commands/extensions.py` is a thin command Adapter over the manager.
  `pawnlogic/cli.py` owns startup/shutdown integration and live Extension
  completion; it reaches Tools through `extension_tool_registry()`, not private
  session Registry state.
- Delegate capability profiles filter Registry capabilities and must not grow
  a second hard-coded tool-name policy.
- `core/trust.py` and `core/operation_policy.py` own trust-boundary categories,
  notices, and command-risk policy.
- `core/network_policy.py` owns normalized HTTP(S) target decisions, injected
  DNS-answer evaluation, redirect re-evaluation, private-target authorization,
  special-address denial, and capability-only network gates.
- `tools/file_ops.py` owns workspace-bound file operations.
- `tools/text_patch.py` owns SEARCH/REPLACE matching and diagnostics;
  `tools/file_ops.py` keeps the public `patch_file` adapter.
- `tools/shell_ops.py` owns host-shell authorization orchestration.
- `tools/sandbox.py` owns host shell execution policy integration.
- `tools/network_adapter.py` owns DNS, redirect, browser-navigation, and host
  confirmation adapters for the pure Network Policy.
- `tools/web_ops.py` and `tools/browser_ops.py` adapt URL fetch and browser
  operations without treating model-provided arguments as authorization.
- `tools/docker_sandbox.py` owns Docker execution boundaries; bridge/host
  networking enters Network Policy as an explicitly authorized capability.
- `tools/docker_plan.py` validates pure Docker execution plans before SDK use.
- `tools/pwn_binary.py` owns pure/cached binary helpers, while
  `tools/pwn_debugger.py` owns GDB script planning; `tools/pwn_chain.py` keeps
  public tool adapters.
- `core/mcp_client_manager.py` owns MCP lifecycle and applies the
  capability-only network-install gate to legacy `uvx mcp-server-fetch`
  startup.
- `tests/test_trust.py`, `tests/test_operation_policy.py`,
  `tests/test_run_shell_policy.py`, `tests/test_docker_policy.py`,
  `tests/test_network_policy.py`, `tests/test_network_policy_baseline.py`, and
  `tests/test_network_adapter_baseline.py` protect trust and network-policy
  behavior.

### Workspace, Skills, And Maintenance

- `core/workspace_cleanup.py` owns workspace backup, restore, staging, cleanup,
  and rollback behavior.
- `core/skill_manager.py` owns skill-pack metadata and indexing behavior.
- `tools/runtime_eval.py` owns the local runtime evaluation harness and writes
  redacted JSONL artifacts under ignored `.pawnlogic_eval/`. Real API smoke
  remains opt-in through `PAWNLOGIC_REAL_API_SMOKE=true` and guarded by local
  call and duration budgets. The `tools` suite covers safe local file/shell
  flows and fail-closed policy checks without network targets. Optional
  `docker`, `browser`, and `ctf` suites skip cleanly when local dependencies
  are unavailable; when available, they stay local by using no-network Docker
  execution with workspace-bound mounts, a local static HTML server, and local
  binary tooling only. CI runs only the offline runtime evaluation suite.
- `tools/eval/scenarios/` owns production-parser replay, Registry-backed safe
  tool smoke, and deterministic resource-growth soak workloads. Provider replay
  fixtures cover text, usage, tool calls, retry notices, malformed events, and
  partial-stream interruption without network access.
- `tools/merge_ctf_skills.py` is a maintenance helper for optional CTF skills.
- `tools/codex_goal_run.sh` is the bounded unattended-maintenance entry point.
  It requires a clean feature branch, confines artifacts to ignored local
  roots, stores a redacted manifest and heartbeat, and keeps real API,
  dependency installation, and remote Git capabilities independently gated.
- `THIRD_PARTY_NOTICES.md` records redistribution decisions for third-party
  skill content.
- `tests/test_runtime_eval.py` protects the runtime evaluation artifact
  contract, redaction, deterministic fake scenarios, real API gating, spend
  guards, safe tool smoke, and timeout classification.
- `tests/test_codex_goal_run.py` uses fake executables and temporary Git
  repositories; it must never launch a real Codex process during pytest.
- `tests/test_workspace_cleanup.py`,
  `tests/test_merge_ctf_skills.py`, and packaging tests protect these flows.

### Documentation And Release Guards

- `README.md` and `README_zh-CN.md` must stay structurally and semantically
  aligned.
- `GUIDE.md` and `GUIDE_zh-CN.md` must stay structurally and semantically
  aligned.
- `tools/check_doc_structure.py` enforces translated heading structure and thin
  agent wrappers.
- `tools/check_release_consistency.py` enforces release version consistency.
- `tests/test_repository_language_policy.py` enforces that Chinese text appears
  only in tracked files whose stem ends with `_zh-CN`.
- `tools/check_architecture_budget.py` records per-file line and complexity
  regression ceilings for the largest runtime modules. CI fails when a budgeted
  file exceeds its ceiling.
- `tools/code_index.py check` validates that the local code index is fresh
  against current source file hashes.
- `docs/MODULE_MAP.md` maps each major module to its Interface, Implementation,
  Seam, Adapter, owning tests, and invariants.
- `docs/agents/` contains progressive-disclosure agent docs for issue tracking,
  triage labels, and domain context pointers.
- `docs/adr/` contains accepted Architecture Decision Records for RuntimeContext,
  ProviderRuntime, Provider streams, Tool trust, runtime evaluation artifacts,
  and Skill Pack packaging.
- `docs/plans/INDEX.md` identifies exactly one active release plan and lists
  completed plans.

## Completed Iteration: 0.2.2 Runtime Evaluation And Architecture Slimming

The 0.2.2 iteration added durable local runtime evaluation and reduced code
bloat through behavior-preserving splits. Use
`docs/plans/0.2.2-runtime-evaluation-architecture-slimming.md` as the release
record for completed task order and validation.

Completed workstreams:

1. Plan the 0.2.2 iteration without changing `config/paths.py`.
2. Add a runtime evaluation harness with deterministic fake/offline scenarios
   before adding provider-specific or dependency-heavy suites.
3. Add bounded real API smoke only behind explicit spend guards and redaction.
4. Add CLI transcript and safe tool dynamic smoke coverage.
5. Add optional Docker, browser, CTF, and soak suites that skip cleanly when
   dependencies are unavailable.
6. Add a fast CI-safe offline runtime evaluation job.
7. Split large modules by ownership boundary while preserving public contracts.
8. Prepare and publish 0.2.2 only after local validation and remote CI pass.

The iteration preserved public CLI syntax, provider visibility rules, public
stream delta dict schema, tool result message shape, assistant message shape,
and `reasoning_content` persistence.

## Completed Iteration: 0.2.3 Autonomous Runtime Reliability And Deepening

The 0.2.3 iteration closed confirmed safety and release-gate gaps, deepened
runtime modules, improved custom Provider transaction/retry behavior, made
runtime evaluation enforce real budgets and exercise real local paths, restored
bounded WSL2 Codex automation, and reduced large-file ownership hotspots without
changing public runtime contracts.

The release was published as `v0.2.3` on 2026-07-14. Use
`docs/plans/0.2.3-autonomous-runtime-reliability-deepening.md` for PR order,
Interface definitions, targeted tests, CI monitoring, stop conditions, and the
complete release evidence.

## Typed Island

The typed-island mypy check is intentionally selective. It should grow through
stable modules and narrow fixes only. Avoid broad `# type: ignore`, global
strict mode, or behavior changes disguised as type cleanup.

Current stable candidates and covered modules include:

- `core/turn_api.py`
- `core/turn_guards.py`
- `core/tool_result.py`
- `core/tool_executor.py`
- `core/runtime_context.py`
- `core/provider_runtime.py`
- `core/api_errors.py`
- `core/tool_calls.py`
- `core/tool_registry.py`
- `core/context_window.py`
- `core/workspace_cleanup.py`
- `core/turn_state.py`
- `core/session_tool_loop.py`
- `core/session_snapshot.py`
- `core/delegation.py`
- `core/agent_orchestrator.py`
- `core/message_history.py`
- `core/provider_streams.py`
- `core/runtime_metrics.py`
- `core/mcp_client_manager.py`
- `core/path_policy.py`
- `tools/check_doc_structure.py`
- `tools/check_release_consistency.py`
- `tools/merge_ctf_skills.py`
- `tools/browser_ops.py`
- `tools/lsp_lite.py`

## Agent Workflow Shortcut

For broad code changes:

1. Read `AGENT.md`.
2. Read this file.
3. Read the active plan under `docs/plans/`.
4. Refresh the code index before audit or multi-file edits:

   ```bash
   python tools/code_index.py build
   ```

5. Use the index before broad text searches for known symbols:

   ```bash
   python tools/code_index.py symbol <name>
   python tools/code_index.py refs <name>
   ```

6. Run narrow tests first, then wider validation before committing.
7. Update this file if the work changes module ownership, public contracts,
   active plans, release state, or known risks.

## Known Risks To Recheck Often

- Host, Docker, browser, MCP, and CTF execution paths can drift around the
  shared trust, Operation Policy, and Network Policy Interfaces. URL adapters
  must re-evaluate DNS answers and redirects; capability-only approval must not
  be treated as target approval.
- Provider mutation ordering, format-specific fetch headers, and stream versus
  non-stream retry classification can diverge. PRs #54, #57 completed PR 5:
  fetch headers, transactional persistence, malformed-response handling, legacy
  wizard routing, eligibility centralization, and doc sync all addressed.
- Runtime evaluation must enforce real deadlines and measured budgets; a fake
  pass scenario is not evidence for the path named by a suite.
- Provider visibility drift between CLI, TUI, completions, and runtime fetch.
- User-friendly mode accidentally leaking debug internals.
- Stream adapters changing public delta dict keys or ordering.
- Workspace restore paths moving current work before validation succeeds.
- Tool trust notices drifting from operation policy behavior.
- Runtime metrics accidentally persisting secrets or changing message shape.
- Packaging accidentally including `skills/` content.
- Extension discovery importing or enabling third-party code during ordinary
  core startup.
- Separately distributed security Tools bypassing shared Tool Registry,
  Operation Policy, Network Policy, or Engagement Scope checks.
- Delegated-agent prompt/model requests bypassing Provider visibility, user
  allowlists, budgets, capability filtering, or host safety instructions.
- Targeted pytest commands that combine `test_session_utils.py` with delegation
  tests can inherit its collection-time `tools.delegate_tool` stub; run those
  focused groups in separate pytest processes. Normal full-suite collection is
  verified to pass.
- Redis becoming a required or sole durable knowledge store instead of an
  optional retrieval/index Adapter.
- English and zh-CN docs drifting in structure or command examples.
- Release prep editing version literals outside fixed locations.

## Update Rules For This File

Update `PROJECT_MEMORY.md` in the same commit when a change:

- changes module ownership or architecture boundaries
- adds, removes, or renames a major subsystem
- changes public CLI, provider, model, stream, tool, MCP, workspace, packaging,
  security, or release behavior
- changes the active release plan or current public release state
- changes typed-island scope
- adds a new recurring risk or retires an old one

Do not update this file for a purely local test assertion, typo, formatting
change, or narrow bug fix that does not affect future agent orientation.
