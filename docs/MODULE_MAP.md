# PawnLogic Module Map

> **For agentic workers:** Use this map to identify ownership before editing.
> Each module lists its Interface, Implementation, Seam, Adapter, owning tests,
> and invariants. When in doubt, read the module's docstring and the linked ADR.

## Core Runtime

| Module | Role | Interface | Tests | Invariants |
|--------|------|-----------|-------|------------|
| `core/session.py` | State Adapter | `AgentSession` class | `test_session_utils.py`, `test_turn_guards.py` | Session owns message history, tool map, and model selection. One session per REPL. |
| `core/runtime_context.py` | Authoritative context | `RuntimeContext` dataclass | `test_runtime_context.py` | Owns cwd, workspace, sink, mode flags. Legacy globals are one-way mirrors. |
| `core/session_tool_loop.py` | Turn tool loop | `TurnToolLoop.execute_batch()` | `test_tool_executor.py`, `test_turn_guards.py` | Batch execution, Plan guard, audit, metrics. Single Interface for all tool dispatch. |
| `core/session_snapshot.py` | Persistence Interface | `save_snapshot()` / `load_snapshot()` | `test_memory_reliability.py` | Manual and autosave share one snapshot shape. Atomic writes. |
| `core/message_history.py` | Message ordering | `MessageHistory` class | `test_session_utils.py` | Preserves assistant/tool message order, `reasoning_content`, pinned messages. |
| `core/context_manager.py` | Structured context Interface | `ContextManager`, `ContextState`, `ContextEnvelope` | `test_context_manager.py`, `test_context_window.py` | Counts content/reasoning/Tool data, preserves atomic Tool groups and protected state, persists versioned state through an existing pinned message carrier, and reports protected over-budget context without corruption. |
| `core/context_window.py` | Context compatibility Adapter | `_ctx_chars()`, `_trim_and_compact_context()` | `test_context_window.py`, `test_session_utils.py` | Legacy exports remain stable; compaction targets `ctx_trim_to` when retained protected content permits it. |
| `core/runtime_metrics.py` | Counter owner | `RuntimeMetrics` class | `test_runtime_metrics.py` | Sole owner of turn, tool, and API call counters. Snapshots are immutable. |
| `core/delegation.py` | Delegation contracts | `AgentTask`, `AgentResult`, `DelegationPolicyStore` | `test_delegation_contracts.py` | Immutable bounded task/result values. Policy writes are atomic and secret fields are rejected. |
| `core/model_router.py` | Delegated model policy | `ModelRouter.route()` | `test_model_router.py` | Only visible, configured, allowed, capability-matching, budget-eligible models can be selected. |
| `core/delegation_runtime.py` | Delegated execution | `SubAgentSession` | `test_delegate_tool.py`, `test_delegation_baseline.py` | Host safety instructions precede task instructions; Tool capabilities and call/token budgets are enforced. |
| `core/tool_registry.py` | Capability Interface | `ToolRegistry.register()` / `visible_specs()` | `test_tool_registry.py` | Handler, schema, phase, trust, capabilities registered atomically. No tool without handler. |
| `core/extension_contracts.py` | Extension Interface | Frozen Extension values and lifecycle Protocols | `test_extensions.py` | Contracts import no discovery/startup logic. Contributions are typed and owner-attributed. |
| `core/extensions.py` | Extension Runtime | `ExtensionManager` | `test_extensions.py` | Discovery never loads entry points. Enablement is explicit, transactional, persisted, and failure-isolated. |
| `core/mcp_client_manager.py` | MCP process Adapter | `MCPClientManager`, `init_external_mcp()` | `test_mcp_client_manager.py`, `test_mcp_config.py`, `test_network_adapter_baseline.py` | Startup is failure-isolated. Legacy `uvx mcp-server-fetch` requires capability-only network-install authorization. |
| `core/tool_executor.py` | Tool dispatch | `ToolExecutor` class | `test_tool_executor.py` | Dispatches to handler, records outcome, respects trust boundary. |
| `core/tool_result.py` | Outcome shape | `ToolResult` dataclass | `test_tool_result.py` | Explicit status, content, error_type, side_effect flag. |

## Provider Stack

| Module | Role | Interface | Tests | Invariants |
|--------|------|-----------|-------|------------|
| `core/provider_transport.py` | Format-specific headers | `provider_headers()` | `test_providers.py` | OpenAI and Anthropic header shapes are format-specific. Never share bearer tokens across formats. |
| `core/provider_runtime.py` | Mutation Interface | `ProviderRuntime` class | `test_provider_runtime.py` | Persist config before mutating live registries. Rollback on write failure. |
| `core/provider_streams.py` | SSE readers | `read_openai_sse_lines()`, `read_anthropic_sse_lines()` | `test_api_stream_helpers.py` | Provider-specific SSE parsing. Contract-tested delta shapes. |
| `core/api_retry.py` | Retry policy | `RetryPolicy` dataclass | `test_api_retry.py`, `test_api_errors.py` | Policy loaded at request time, not import time. Classification shared across paths. |
| `core/api_client.py` | HTTP transport | `APIWrapper` class | `test_api_stream_helpers.py` | Stream and non-stream share classification. Timeout cap enforced. |
| `core/api_errors.py` | Error formatting | `format_http_error()` | `test_api_errors.py` | User-friendly messages without tracebacks. Retryable status is explicit. |
| `core/commands/provider.py` | Provider commands | `cmd_provider()`, `cmd_model()` | `test_provider_commands.py` | `_visible_models()` is the single eligibility helper. Active + configured key = visible. |
| `core/commands/extensions.py` | Extension commands | `cmd_extension()` | `test_extension_commands.py`, `test_cli_transcripts.py` | Reads the manager from RuntimeContext. Commands never construct or bypass the Extension Runtime. |
| `core/provider_tui.py` | Provider TUI | Rendering + key bindings | `test_provider_commands.py` | Thin rendering over `ProviderTUIState`. All mutations through `ProviderRuntime`. |
| `core/provider_tui_state.py` | TUI state | `ProviderTUIState` class | `test_provider_tui_state.py` | Pure state transitions, no IO. Typed, deterministic methods. |

## Security And Trust

| Module | Role | Interface | Tests | Invariants |
|--------|------|-----------|-------|------------|
| `core/trust.py` | Trust boundaries | `TrustBoundaryKind` enum | `test_trust.py` | Every named boundary has a standard notice and legacy level. |
| `core/operation_policy.py` | Operation gating | `OperationPolicy` class | `test_operation_policy.py`, `test_run_shell_policy.py` | Host-shell destructive and interactive operations require explicit authorization. |
| `core/network_policy.py` | Network authorization Interface | `NetworkPolicy.evaluate()`, `normalize_url()` | `test_network_policy.py`, `test_network_policy_baseline.py`, `test_network_adapter_baseline.py` | Normalize HTTP(S) targets; deny credentials, metadata, and special address ranges; private targets require explicit authorization; every redirect is re-evaluated; non-interactive confirmation fails closed. |
| `core/path_policy.py` | Path containment | `resolve_within()`, `safe_filename_fragment()` | `test_security.py` | Canonical resolution + `relative_to()` containment. No symlink escapes. |
| `core/host_process.py` | Process runner | `HostProcessRunner.run()` | `test_host_process.py` | Environment scrubbing, timeout, process-group cleanup. |

## Tools

| Module | Role | Interface | Tests | Invariants |
|--------|------|-----------|-------|------------|
| `tools/file_ops.py` | File operations | Tool handlers | `test_security.py` | Workspace-relative writes. Path containment enforced. |
| `tools/shell_ops.py` | Shell orchestration | `run_shell()` | `test_run_shell_policy.py` | Delegates to shared `HostProcessRunner`. |
| `tools/network_adapter.py` | Network host Adapter | `evaluate_network_url()`, `open_url_with_policy()`, `navigate_with_policy()` | `test_network_policy_baseline.py` | DNS and redirect checks enter the pure Network Policy; model arguments cannot self-authorize private targets. |
| `tools/web_ops.py` | HTTP fetch Adapter | `tool_fetch_url()` | `test_network_policy_baseline.py`, `test_network_adapter_baseline.py` | Initial and redirect targets pass through `NetworkPolicy`; confirmed private targets bypass remote readers. |
| `tools/text_patch.py` | Text patching | `apply_text_patch()` | `test_security.py` | Fuzzy SEARCH/REPLACE matching. |
| `tools/docker_sandbox.py` | Docker operations | Tool handlers | `test_docker_policy.py`, `test_network_adapter_baseline.py` | Network=none by default. Bridge/host require capability-only authorization. Labelled resources. No unscoped prune. |
| `tools/docker_plan.py` | Docker plans | `build_docker_plan()` | `test_docker_policy.py` | Plan validation separated from SDK calls. |
| `tools/pwn_chain.py` | CTF chain | Tool handlers | `test_ctf_workflow.py` | Binary paths quoted. GDB init filtered. |
| `tools/pwn_binary.py` | Binary analysis | `ElfAnalysisCache` | `test_ctf_workflow.py` | Pure binary/ROP/cyclic helpers. |
| `tools/pwn_debugger.py` | Debugger ops | Tool handlers | `test_ctf_workflow.py` | GDB/interactive process logic. |
| `tools/browser_ops.py` | Browser Network Policy Adapter | Tool handlers | `test_browser_ops.py`, `test_network_policy_baseline.py` | Navigation requests and final destinations are policy-checked. Path containment for screenshots. |
| `tools/delegate_tool.py` | Delegation Adapter | `tool_delegate_task()` | `test_delegate_tool.py`, `test_delegation_baseline.py` | Preserves legacy automatic routing while adapting structured tasks/results to the Delegation Runtime. |

## Evaluation

| Module | Role | Interface | Tests | Invariants |
|--------|------|-----------|-------|------------|
| `tools/eval/contracts.py` | Eval shapes | `EvalBudget`, `RuntimeEvalRecord` | `test_runtime_eval.py` | Frozen dataclasses. Schema version tracked. |
| `tools/eval/runner.py` | Eval runner | `run_suite()` | `test_runtime_eval.py` | Deadline enforcement. Child process cleanup. |
| `tools/eval/artifacts.py` | Artifact I/O | `write_artifact()` | `test_runtime_eval_artifacts.py` | Atomic replacement. Allowlisted fields only. |
| `tools/eval/redaction.py` | Redaction | `redact_summary()` | `test_runtime_eval.py` | Never stores raw Provider output. |
| `tools/runtime_eval.py` | CLI facade | `--suite`, `--max-api-calls` | `test_runtime_eval.py` | Delegates to `tools/eval/`. CLI args compatible. |

## Configuration

| Module | Role | Interface | Tests | Invariants |
|--------|------|-----------|-------|------------|
| `config/paths.py` | Paths and version | `VERSION`, `PAWNLOGIC_HOME` | `test_deployment_friendly.py` | Sole version source of truth. |
| `config/providers.py` | Provider registry | `PROVIDERS` dict | `test_providers.py` | DeepSeek always active. Custom providers inactive by default. |
| `config/security.py` | Security policy | Constants | `test_security.py` | Blocked paths, allowed extensions. |

## CLI

| Module | Role | Interface | Tests | Invariants |
|--------|------|-----------|-------|------------|
| `pawnlogic/cli.py` | CLI facade | `run()`, `PawnCompleter` | `test_cli_startup.py`, `test_cli_transcripts.py` | Public entry point. Live model and Extension completions; Extension startup failures remain non-fatal. |
| `pawnlogic/extension_host.py` | Extension startup Adapter | `ExtensionHost` | `test_extension_host.py` | One process-level manager; persisted activation and shutdown failures are isolated. |
| `pawnlogic/completion_sources.py` | Live completion merge | `merge_completion_sources()` | `test_completion_sources.py`, `test_provider_commands.py` | Static completion inputs are immutable; model and Extension sources are read live. |
| `pawnlogic/startup.py` | Bootstrap | `setup_environment()` | `test_cli_startup.py` | First-run, env, debug mode. |
| `pawnlogic/repl.py` | REPL loop | `run_repl()` | `test_cli_startup.py` | Signal handling, input restoration. |

## Planned 0.3.0 Seams

These Modules are approved design targets in the proposed 0.3.0 plan. They are
listed here to reserve ownership boundaries, not to imply that the
implementations already exist.

| Module | Intended Interface | Seam / Adapter | Status |
|--------|--------------------|----------------|--------|
| Extension Runtime | `ExtensionManager` over stable extension contracts | Python entry-point discovery Adapter; explicit enablement; transactional contribution registration | Core Module and CLI/command Adapters implemented |
| Delegation Runtime | `AgentTask`, `AgentResult`, `DelegationModelPolicy`, `ModelRouter`, `SubAgentSession` | Legacy `delegate_task` compatibility Adapter; Provider-backed execution Adapter | Core Module and command/Tool Adapters implemented |
| Structured Context | `ContextManager`, `ContextState`, `ContextEnvelope` | Main-session provider view; host-owned delegated projection; legacy context-window Adapters | Core Module and main/delegation Adapters implemented |
| Network Policy | `NetworkPolicy.evaluate()` over normalized `NetworkOperation` values | DNS resolver plus web, browser, MCP, and Docker caller Adapters | Core Module and caller Adapters implemented |
| Knowledge Retrieval | Durable knowledge-record and retrieval Interface | SQLite source-of-truth Adapter; optional Redis cache/vector Adapter | Planned |
| Agent Event | Typed event stream for conversations, tools, delegation, budgets, and evidence | CLI, NDJSON, and optional Streamlit rendering Adapters | Planned |

The planned Interfaces must preserve these boundaries:

- Extensions contribute capabilities through the host Interface; they do not
  mutate private session globals.
- Delegated agents request Models and Tools through host policy; prompts cannot
  bypass user allowlists, budgets, trust boundaries, or Engagement Scope.
- Redis remains an optional acceleration Adapter, never the only durable store.
- Streamlit remains a separate UI Adapter and does not parse terminal output.
