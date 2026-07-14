# PawnLogic Project Memory

This file is the compact project memory for maintainers and coding agents. Read
it after `AGENT.md` and before broad planning, code changes, release work, or
multi-file audits.

Keep this file current when a change affects architecture, module ownership,
release direction, public contracts, maintenance risks, or the next planned
tasks. Do not use it as a changelog; `CHANGELOG.md` remains the user-facing
release history.

## Current Release State

- Current public release: `0.2.2`.
- Runtime version source of truth: `config/paths.py:VERSION`.
- Latest published tag: `v0.2.2`.
- Most recent completed plan:
  `docs/plans/0.2.2-runtime-evaluation-architecture-slimming.md`.
- Active plan:
  `docs/plans/0.2.3-autonomous-runtime-reliability-deepening.md`.
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
- Third-party skill packs must not be included in wheels or sdists by default.

## Architecture Map

### CLI And Startup

- `pawnlogic/cli.py` remains the public parser/command facade and owns
  `PawnCompleter` compatibility.
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
- `core/runtime_context.py` owns session runtime state such as cwd, workspace,
  sink, debug mode, user mode, and dynamic config.
- `core/runtime_metrics.py` owns internal metrics snapshots. Metrics are local
  runtime state only.
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
- `core/provider_tui.py` owns provider TUI input, paste, focus, and confirmation
  behavior.
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
- Delegate capability profiles filter Registry capabilities and must not grow
  a second hard-coded tool-name policy.
- `core/trust.py` and `core/operation_policy.py` own trust-boundary categories,
  notices, and command-risk policy.
- `tools/file_ops.py` owns workspace-bound file operations.
- `tools/sandbox.py` owns host shell execution policy integration.
- `tools/docker_sandbox.py` owns Docker execution boundaries.
- `tools/browser_ops.py` owns browser automation operations and recovery paths.
- `tests/test_trust.py`, `tests/test_operation_policy.py`,
  `tests/test_run_shell_policy.py`, and `tests/test_docker_policy.py` protect
  trust boundary behavior.

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
- `tools/merge_ctf_skills.py` is a maintenance helper for optional CTF skills.
- `THIRD_PARTY_NOTICES.md` records redistribution decisions for third-party
  skill content.
- `tests/test_runtime_eval.py` protects the runtime evaluation artifact
  contract, redaction, deterministic fake scenarios, real API gating, spend
  guards, safe tool smoke, and timeout classification.
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

## Active Iteration: 0.2.3 Autonomous Runtime Reliability And Deepening

The active iteration closes confirmed safety and release-gate gaps before
deepening runtime Modules. It then improves custom Provider transaction/retry
behavior, makes runtime evaluation enforce real budgets and exercise real local
paths, restores bounded WSL2 Codex automation, and reduces large-file ownership
hotspots without changing public runtime contracts.

Use `docs/plans/0.2.3-autonomous-runtime-reliability-deepening.md` for PR order,
Interface definitions, targeted tests, CI monitoring, stop conditions, and the
separate release-authorization gate.

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
  shared trust and Operation Policy Interfaces.
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
