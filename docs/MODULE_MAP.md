# PawnLogic Module Map

> **For agentic workers:** Use this map to identify ownership before editing.
> Each module lists its Interface, Implementation, Seam, Adapter, owning tests,
> and invariants. When in doubt, read the module's docstring and the linked ADR.

## Core Runtime

| Module | Role | Interface | Tests | Invariants |
|--------|------|-----------|-------|------------|
| `core/session.py` | State Adapter | `AgentSession` class | `test_session_utils.py`, `test_turn_guards.py` | Session owns message history, tool map, and model selection. One session per REPL. Re-exports `_PlanRenderer` from `core/plan_renderer.py`. |
| `core/plan_renderer.py` | Plan tag renderer | `_PlanRenderer.feed()` / `.flush()` | `test_session_utils.py`, `test_flush_tail_on_wire.py` | Strips the XML `<plan>` block from the stream. Any content outside `<plan>` is returned to the caller; a fragment left mid-tag must ride the content-delta seam, not stdout. |
| `core/runtime_context.py` | Authoritative context | `RuntimeContext` dataclass | `test_runtime_context.py` | Owns cwd, workspace, sink, mode flags. Legacy globals are one-way mirrors. |
| `core/session_tool_loop.py` | Turn tool loop | `TurnToolLoop.execute_batch()` | `test_tool_executor.py`, `test_turn_guards.py` | Batch execution, Plan guard, audit, metrics. Single Interface for all tool dispatch. |
| `core/session_snapshot.py` | Persistence snapshot contract | `SessionSnapshot`, `SESSION_SNAPSHOT_SCHEMA` | `test_session_snapshot.py`, `test_core_coverage.py` | Manual, autosave, and scheduler checkpoints share one versioned immutable snapshot shape. |
| `core/persistence.py` | Durable session recovery Adapter | `checkpoint_scheduler_view()`, `session_continue()` | `test_core_coverage.py`, `test_cli_startup.py` | Scheduler transitions persist without turn metrics/autonaming side effects; recoverable sessions load as editable drafts and never auto-run. |
| `core/message_history.py` | Message ordering | `MessageHistory` class | `test_session_utils.py` | Preserves assistant/tool message order, `reasoning_content`, pinned messages. |
| `core/turn_scheduler.py` | Turn admission and lifecycle | `TurnScheduler.submit()` / `control()` / `view()` | `test_turn_scheduler.py` | Stable IDs, FIFO within each lane, explicit capacity errors, recoverable drafts, ordered checkpoint state, and an optional per-session non-daemon worker; mixed-lane steer precedence applies at P3 safe points and unclaimed steer drains after natural completion. |
| `core/queue_tui.py` | Queue presentation and menu Adapter | `queue_rows()`, `render_queue_tui()`, `open_queue_tui()` | `test_queue_tui.py`, `test_commands_dispatch.py` | Reads immutable scheduler views only; stable sequence/short-ID rows, explicit cancellation, and no stdin ownership while a Turn is active. |
| `core/turn_cancellation.py` | Per-Turn cancellation | `TurnCancellationToken`, `execute_session_tool_batch()` | `test_turn_scheduler.py`, `test_session_tool_loop.py` | Cancellation is scoped to one Turn ContextVar; tool batches close interrupted/skipped protocol pairs without replaying side effects. |
| `core/live_turn_control.py` | Session turn-control Adapter | `build_session_scheduler()` plus submit/resume/claim/shutdown helpers | `test_session_utils.py`, `test_turn_scheduler.py` | Keeps `AgentSession` thin while preserving the scheduler's three-entry Interface, typed lifecycle controls, and isolated background context seam. |
| `core/context_manager.py` | Structured context Interface | `ContextManager`, `ContextState`, `ContextEnvelope` | `test_context_manager.py`, `test_context_window.py` | Counts content/reasoning/Tool data, preserves atomic Tool groups and protected state, persists versioned state through an existing pinned message carrier, and reports protected over-budget context without corruption. |
| `core/context_window.py` | Context compatibility Adapter | `_ctx_chars()`, `_trim_and_compact_context()` | `test_context_window.py`, `test_session_utils.py` | Legacy exports remain stable; compaction targets `ctx_trim_to` when retained protected content permits it. |
| `core/runtime_metrics.py` | Counter owner | `RuntimeMetrics` class | `test_runtime_metrics.py` | Sole owner of turn, tool, and API call counters. Snapshots are immutable. |
| `core/delegation.py` | Delegation contracts | `AgentTask`, `AgentResult`, `DelegationPolicyStore` | `test_delegation_contracts.py` | Immutable bounded task/result values. Policy writes are atomic and secret fields are rejected. |
| `core/agent_orchestrator.py` | Bounded orchestration Interface | `SerialAgentOrchestrator`, `CancellationToken`, `BudgetLedger` | `test_agent_orchestrator.py`, `test_concurrent_delegation.py`, `test_delegation_tree_budget.py` | Tasks retain input-order results through an injected Delegation Runtime executor. Atomic claims are single-settlement; one or two workers only, with task-local cancellation and deadlines. A two-worker executor must be concurrency-safe. `run()` accepts an optional shared `BudgetLedger` so a delegation tree draws from one budget ceiling. |
| `core/model_router.py` | Delegated model policy | `ModelRouter.route()` | `test_model_router.py` | Only visible, configured, allowed, capability-matching, budget-eligible models can be selected. |
| `core/delegation_runtime.py` | Delegated execution | `SubAgentSession`, `DelegationTaskExecutor` | `test_delegate_tool.py`, `test_delegation_baseline.py`, `test_concurrent_delegation.py` | Host safety instructions precede task instructions; each child receives a copied RuntimeContext, unique workspace, bounded output collector, and task-local cancellation. Two-worker mode permits only task-isolated file Tools. |
| `core/knowledge.py` | Retrieval contracts and orchestration | `KnowledgeRecord`, `RetrievalHit`, `KnowledgeRetriever` | `test_knowledge.py` | SQLite content is authoritative; optional projections provide ranking only; stale or unavailable projections fall back without startup failure. |
| `core/knowledge_sqlite.py` | Durable knowledge Adapter | `SQLiteKnowledgeAdapter` | `test_knowledge_memory_adapter.py` | Bounded FTS/keyword reads, revision-aware outbox events, and database-side rebuild enqueueing never materialize the full corpus. |
| `core/gsa_tools.py` | GSA tool handlers | `tool_bump_skill`, `tool_audit_payload` | `test_session_utils.py`, `test_tool_routing.py` | Handlers and schemas live here; `core.session` registers them into the shared registry at import time. |
| `core/agent_events.py` | Versioned Agent Event Interface | `AgentEvent`, `AgentEventPublisher` | `test_agent_events.py`, `test_agent_event_integration.py` | Events are immutable, recursively redacted, canonically serialized, and synchronously published outside persisted chat-message shapes. |
| `core/session_events.py` | Main-session event Adapter | `SessionEventEmitter` | `test_agent_event_integration.py`, `test_session_utils.py` | Correlates Turn, retrieval, usage, Tool, and policy events; subscriber failures never stop Agent execution. |
| `core/tool_registry.py` | Capability Interface | `ToolRegistry.register()` / `visible_specs()` | `test_tool_registry.py` | Handler, schema, phase, trust, capabilities registered atomically. No tool without handler. |
| `core/extension_contracts.py` | Extension Interface | Frozen Extension values and lifecycle Protocols | `test_extensions.py` | Contracts import no discovery/startup logic. Contributions are typed and owner-attributed. |
| `core/extensions.py` | Extension Runtime | `ExtensionManager` | `test_extensions.py` | Discovery never loads entry points. Enablement is explicit, transactional, persisted, and failure-isolated. |
| `core/mcp_client_manager.py` | MCP process Adapter | `MCPClientManager`, `init_external_mcp()` | `test_mcp_client_manager.py`, `test_mcp_config.py`, `test_mcp_provenance.py`, `test_network_adapter_baseline.py` | Startup is failure-isolated. Legacy `uvx mcp-server-fetch` requires capability-only network-install authorization. Tool results carry provenance (server/transport/call id/content hash). |
| `core/tool_executor.py` | Tool dispatch | `ToolExecutor` class | `test_tool_executor.py` | Dispatches to handler, records outcome, respects trust boundary. |
| `core/tool_result.py` | Outcome shape | `ToolResult` dataclass | `test_tool_result.py` | Explicit status, content, error_type, side_effect flag. |

## Provider Stack

| Module | Role | Interface | Tests | Invariants |
|--------|------|-----------|-------|------------|
| `core/provider_transport.py` | Format-specific headers | `provider_headers()` | `test_providers.py` | OpenAI and Anthropic header shapes are format-specific. Never share bearer tokens across formats. |
| `core/provider_runtime.py` | Mutation Interface | `ProviderRuntime` class | `test_provider_runtime.py` | Persist config before mutating live registries. Rollback on write failure. Re-exports the probe API from `core/provider_discovery.py` so existing call sites keep resolving. |
| `core/provider_discovery.py` | Model probe policy | `classify_probe_response()`, `probe_openai_chat_model()`, `filter_supported_chat_models()` | `test_provider_runtime.py` | Hide a model only on positive evidence. Rate limits and transport failures are `unknown`, retried once, then kept visible. |
| `core/provider_models.py` | Model Policy | Provider model helpers | `test_provider_runtime.py` | Keep model classification, aliases, and response formatting independent from provider persistence. |
| `core/provider_streams.py` | SSE readers | `read_openai_sse_lines()`, `read_anthropic_sse_lines()` | `test_api_stream_helpers.py` | Provider-specific SSE parsing. Contract-tested delta shapes. |
| `core/api_retry.py` | Retry policy | `RetryPolicy` dataclass | `test_api_retry.py`, `test_api_errors.py` | Policy loaded at request time, not import time. Classification shared across paths. |
| `core/api_client.py` | HTTP transport | `APIWrapper` class | `test_api_stream_helpers.py` | Stream and non-stream share classification. Timeout cap enforced. |
| `core/api_errors.py` | Error formatting | `format_http_error()` | `test_api_errors.py` | User-friendly messages without tracebacks. Retryable status is explicit. |
| `core/commands/provider.py` | Provider commands | `cmd_provider()`, `cmd_model()` | `test_provider_commands.py` | `_visible_models()` is the single eligibility helper. Active + configured key = visible. |
| `core/commands/__init__.py` | Command registry and dispatch | `COMMANDS`, `dispatch()`, `matching_command_words()` | `test_commands_dispatch.py`, `test_provider_commands.py` | Registered verbs are authoritative; fuzzy direct dispatch executes only a unique match and reports ambiguity without executing. |
| `core/commands/extensions.py` | Extension commands | `cmd_extension()` | `test_extension_commands.py`, `test_cli_transcripts.py` | Reads the manager from RuntimeContext. Commands never construct or bypass the Extension Runtime. |
| `core/provider_tui.py` | Provider TUI | Layout + key bindings + actions | `test_provider_commands.py` | Layout, key bindings, and actions over `ProviderTUIState`. Form and dialog drawing live in `core/provider_tui_form.py`. All mutations through `ProviderRuntime`. |
| `core/provider_tui_form.py` | Form + dialog drawing | `render_wizard()`, `render_dialog()`, `detail_actions()`, `wiz_focus_cycle()`, `focus_buttons()` | `test_provider_commands.py` | Pure rendering for the shared Add/Edit form and the confirmation dialogs. `focus_buttons()` is shared with the model selector so both mark the focused button in text, not colour alone. |
| `core/provider_tui_state.py` | TUI state | `ProviderTUIState` class | `test_provider_tui_state.py` | Pure state transitions, no IO. Typed, deterministic methods. |

## Security And Trust

| Module | Role | Interface | Tests | Invariants |
|--------|------|-----------|-------|------------|
| `core/trust.py` | Trust boundaries | `TrustBoundaryKind` enum | `test_trust.py` | Every named boundary has a standard notice and legacy level. |
| `core/operation_policy.py` | Operation gating | `OperationPolicy` class | `test_operation_policy.py`, `test_run_shell_policy.py` | Host-shell destructive and interactive operations require explicit authorization. |
| `core/network_policy.py` | Network authorization Interface | `NetworkPolicy.evaluate()`, `normalize_url()` | `test_network_policy.py`, `test_network_policy_baseline.py`, `test_network_adapter_baseline.py` | Normalize HTTP(S) targets; deny credentials, metadata, the reserved localhost namespace, and special address ranges; private targets require explicit authorization; every redirect is re-evaluated; non-interactive confirmation fails closed. |
| `core/path_policy.py` | Path containment | `resolve_within()`, `safe_filename_fragment()` | `test_security.py` | Canonical resolution + `relative_to()` containment. No symlink escapes. |
| `core/host_process.py` | Process runner | `HostProcessRunner.run()` | `test_host_process.py` | Environment scrubbing, timeout, process-group cleanup. |

## Tools

| Module | Role | Interface | Tests | Invariants |
|--------|------|-----------|-------|------------|
| `tools/file_ops.py` | File operations | Tool handlers | `test_security.py` | Workspace-relative writes. Path containment enforced. |
| `tools/shell_ops.py` | Shell orchestration | `run_shell()` | `test_run_shell_policy.py` | Delegates to shared `HostProcessRunner`. |
| `tools/network_adapter.py` | Network host and browser policy Adapter | `evaluate_network_url()`, `evaluate_network_url_pinned()`, `open_url_with_policy()`, `navigate_with_policy()`, `BrowserRequestGuard` | `test_network_policy_baseline.py`, `test_network_dns_pinning.py`, `test_browser_ops.py` | The direct `urllib` path pins DNS answers at policy-check time and dials only those addresses; missing pins fail closed, while a configured upstream proxy owns its hop's DNS and socket. Browser guards re-check engine-issued requests where interception surfaces them, authorize confirmed targets with the enforcement proxy, and refuse page-level-only interception. |
| `tools/web_ops.py` | HTTP fetch Adapter | `tool_fetch_url()` | `test_network_policy_baseline.py`, `test_network_adapter_baseline.py` | Initial and redirect targets pass through `NetworkPolicy`; confirmed private targets bypass remote readers. |
| `tools/text_patch.py` | Text patching | `apply_text_patch()` | `test_security.py` | Fuzzy SEARCH/REPLACE matching. |
| `tools/docker_sandbox.py` | Docker operations | Tool handlers | `test_docker_policy.py`, `test_network_adapter_baseline.py` | Network=none by default. Only none/bridge/host are accepted; bridge/host require explicit authorization. Scoped disposable Python runs use network=none HTTP/CONNECT; scoped host/persistent exec/Airlock are denied. Failed temporary Airlock disconnects revoke tool access and kill/remove the container; daemon cleanup failure is reported explicitly. Unknown modes and container:<id> sharing are rejected before the SDK. Labelled resources. No unscoped prune. Delegates to the docker_spawn / docker_egress / docker_mounts / docker_schemas modules. |
| `tools/docker_spawn.py` | Container creation choke point | `spawn_container()`, `check_privilege_flags()`, `resolve_container_user()`, `HARDENING_TMPFS` | `test_docker_policy.py`, `test_tool_ownership_splits.py` | Denies privileged/cap_add/cap_drop/security_opt kwargs (SDK and CLI spellings) before the SDK call, then merges one-shot hardening defaults (cap_drop=ALL, read-only rootfs, tmpfs) after the deny check so tool arguments cannot supply raw hardening kwargs. Trusted Python callers can override read-only/tmpfs defaults. |
| `tools/docker_egress.py` | Operator scope snapshot | `parse_egress_scope()`, `resolve_egress_addresses()` | `test_docker_policy.py`, `test_docker_http_integration.py` | Freeze explicit hostname A/AAAA answers once; IP/CIDR need no DNS. Scope enforcement belongs to the host proxy, never hosts-file hints. |
| `tools/docker_http.py` | Scoped Docker transport lifecycle | `scoped_mode_error()`, `prepare_transport()`, `finish_transport()` | `test_docker_http_integration.py` | Validate supported offline transport, separate code/RO relay mounts, revoke sockets before removal; setup/cleanup fail closed. |
| `tools/container_http_proxy.py` | Unix egress enforcement | `ContainerHTTPProxy` | `test_container_http_proxy.py` | Explicit scope plus Network Policy, numeric-only pinned dial, bounded handlers, operation expiry/revocation. |
| `tools/container_http_protocol.py` | Streaming HTTP/CONNECT protocol | Scope, request/body framing and dial helpers | `test_container_http_protocol.py` | Bounded framing and streamed fixed/chunked bodies up to 64 MiB, one HTTP request per connection; CONNECT remains opaque TCP to approved targets. |
| `tools/container_http_relay.py` | Container stdlib relay | `ContainerRelay`, `proxy_environment()`, `main()` | `test_container_http_relay.py` | Loopback-to-Unix transport in network=none; readiness before user code, proxy environment override, no host credentials. |
| `tools/docker_mounts.py` | Docker mount safety | `check_path_safety()`, `is_sensitive_host_path()`, `SAFE_WORKSPACE` | `test_docker_policy.py`, `test_tool_ownership_splits.py` | RW mounts are workspace-bound; RO outside the workspace requires explicit allow and never covers credentials, docker.sock, or sensitive system locations, in both directions. |
| `tools/docker_schemas.py` | Docker tool schemas | `DOCKER_SCHEMAS` | `test_docker_policy.py` | Declarative schema block; keep the network enum in agreement with `docker_plan.SUPPORTED_NETWORK_MODES` and the network gate. |
| `tools/docker_plan.py` | Docker execution plans | `SUPPORTED_NETWORK_MODES`, `validate_network_mode()`, `build_docker_execution_plan()` | `test_docker_policy.py` | Pure plan validation owns the closed network-mode set and rejects unknown/container-sharing modes before SDK calls; runtime authorization remains in the Docker caller. |
| `tools/pwn_chain.py` | CTF chain | Tool handlers | `test_ctf_workflow.py` | Binary paths quoted. GDB init filtered. |
| `tools/pwn_binary.py` | Binary analysis | `ElfAnalysisCache` | `test_ctf_workflow.py` | Pure binary/ROP/cyclic helpers. |
| `tools/pwn_debugger.py` | Debugger ops | Tool handlers | `test_ctf_workflow.py` | GDB/interactive process logic. |
| `tools/browser_ops.py` | Browser Network Policy Adapter | Tool handlers | `test_browser_ops.py`, `test_network_policy_baseline.py` | Patchright launches through the loopback enforcement proxy with a context-lifetime guard and requested Service Worker blocking; Scrapling fetches bind to the proxy, register the guard during page setup, close the context when installation fails, and re-verify the guard after every retry. Navigation requests and final destinations are policy-checked. Path containment for screenshots. |
| `tools/policy_proxy.py` | Browser enforcement proxy | `PolicyProxy`, `retry_fetch_with_enforcement()`, `install_fetch_page_guard()`, `scrapling_version_gate()` | `test_policy_proxy.py`, `test_browser_ops.py`, `test_browser_proxy_integration.py` | Checks CONNECT authorities and single HTTP requests, preserves confirmed pins and operation tokens, revokes sockets on scope exit/stop, and bounds handlers. Chromium disables HTTP/2/QUIC and loopback bypass; failed proxy/setup fails closed. |
| `tools/proxy_protocol.py` | Strict proxy wire protocol | `read_request()`, `connect_url()`, `forward_http()`, `splice()`, `dial_pinned()` | `test_proxy_protocol.py`, `test_policy_proxy.py` | Canonical Host/body framing, single HTTP request per socket, stripped proxy/hop headers, bounded body and I/O, preserved pre-read CONNECT bytes. No TLS inspection. |
| `tools/delegate_tool.py` | Delegation Adapter | `tool_delegate_task()` | `test_delegate_tool.py`, `test_delegation_baseline.py`, `test_delegation_tree_budget.py` | Preserves legacy automatic routing while adapting structured tasks/results to the Delegation Runtime. Depth and the tree-wide budget ledger are ContextVars so they propagate into pool workers; the outermost delegation creates the shared ledger and nested calls reuse it (one budget ceiling per tree). |

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
| `pawnlogic/completion_sources.py` | Live completion merge and command-matching Adapter | `FallbackCompletion`, `merge_completion_sources()`, `pawn_fuzzy_match()`, `matching_command_words()` | `test_completion_sources.py`, `test_provider_commands.py` | Static completion inputs are immutable; the disabled-UI fallback preserves the completer value contract; command matching delegates to the registry owner while dynamic sources are read live. |
| `pawnlogic/live_repl.py` | Prompt Toolkit live-composer Adapter | `build_prompt_toolkit_bindings()`, `build_bottom_toolbar()`, `build_queue_preview()`, `dispatch_live_input()`, `dispatch_live_slash()` | `test_e2e.py`, `test_live_repl.py`, `test_cli_startup.py` | Typed Enter/Alt+Enter and Alt+Up recall submissions, immutable queue previews/toolbars, modal command handoff, and safe live slash-command gating stay separate from the CLI startup facade; readline remains serial. |
| `pawnlogic/live_terminal.py` | Persistent terminal owner | `PersistentTerminal`, `PersistentTerminalController`, `TerminalSink` | `test_live_terminal.py`, `test_live_terminal_inline.py`, `test_model_selector_modal.py`, `test_e2e.py` | One Prompt Toolkit application renders streamed output above conditional queue rows, a composer, and a toolbar; worker stdout/stderr reach host scrollback only through a serialized, bounded `run_in_terminal` handoff. Embedded selectors retain stable Application identity, and stale close/refresh callbacks cannot affect a replacement selector. The 0.3.7 cycle drops `full_screen` / `mouse_support` and routes all output through a single `TerminalTranscript`. |
| `pawnlogic/selectors.py` | In-Application selector state and lifecycle seam | `ModalSpec`, `EmbeddedSelector`, `SelectorRegistry`, `SelectorState` | `test_model_selector_modal.py` | Exactly one active selector/future pair belongs to the persistent Application; identity guards prevent stale callbacks from closing or refreshing a newer modal, and replacement/shutdown resolves the displaced future. |
| `pawnlogic/terminal_transcript.py` | Single-owner transcript buffer for the persistent terminal | `TerminalTranscript`, `TextSink`, `normalize_sink`, `pending_host_flush()`, `mark_host_flushed()` | `test_live_terminal_inline.py`, `test_model_selector_modal.py` | Thread-safe bounded in-memory buffer with a pluggable host sink and recovery-draft marker. Host flush cursors advance only after a successful handoff, so transient failures can retry without dropping transcript content. Replaces the legacy parallel `_output_chunks` deque so every writer routes through the same transcript. |
| `pawnlogic/restart_recovery.py` | Restart CLI Adapter | `parse_cli_arguments()`, `load_cli_recovery()` | `test_cli_startup.py` | `--continue` and `resume <session>` load history and prefill a draft without automatically executing a Turn. |
| `pawnlogic/startup.py` | Bootstrap | `setup_environment()` | `test_cli_startup.py` | First-run, env, debug mode. |
| `pawnlogic/repl.py` | REPL loop | `run_repl()` | `test_cli_startup.py` | Signal handling, input restoration. |
| `pawnlogic/headless.py` | Headless serve protocol server (ADR 0011) | `HeadlessServer.serve()`, `run_serve()`, `make_event()`, `missing_key_detail()`, `_run_eval_mode()` | `test_headless_contract.py` | Versioned NDJSON over stdio; one session per process; unknown request types ignored; reader thread dispatches interrupt and steer immediately; the golden fixture (tests/fixtures/serve_events_v1.jsonl) is the cross-language contract. |
| `frontends/serve_wire.py` | Python reference wire client (Phase 2a) | `ServeWire`, `LatencyRecorder`, `build_request()` | `test_serve_client.py` | UI-free protocol client: spawns `pawn serve`, daemon reader thread, v1 envelope helpers; latency stats are additive observations only. |
| `frontends/ratatui/src/wire.rs` | Rust wire parser (Phase 2b) | `parse_line()`, `build_request()` | cargo test (golden fixture alignment) | Accepts v1 fixture events, rejects unknown versions and malformed envelopes, and ignores unknown event types for additive v1 compatibility. |
| `frontends/ratatui/src/composer.rs` + `ui.rs` + `main.rs` | Rust fullscreen UI (Phase 2b) | `Composer`, `apply_event()`, `handle_event()`, `drive_loop()` | cargo test (composer/ui/main modules) | Alternate-screen fullscreen with in-app scrolling, Unicode-safe cursor editing, paste, mouse capture, single-render stream ownership, backend failure monitoring, and RAII terminal restoration. Enter=prompt/steer, Esc=interrupt, Ctrl+C or exit aliases=shutdown. |

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
| Knowledge Retrieval | Durable knowledge-record and retrieval Interface | SQLite source-of-truth Adapter; optional Redis cache/vector Adapter | Core Interface and SQLite Adapter implemented |
| Agent Event | Typed event stream for conversations, tools, delegation, budgets, and evidence | CLI and NDJSON Adapters; optional Streamlit remains external | Core Interface and runtime Adapters implemented |

The planned Interfaces must preserve these boundaries:

- Extensions contribute capabilities through the host Interface; they do not
  mutate private session globals.
- Delegated agents request Models and Tools through host policy; prompts cannot
  bypass user allowlists, budgets, trust boundaries, or Engagement Scope.
- Redis remains an optional acceleration Adapter, never the only durable store.
- Streamlit remains a separate UI Adapter and does not parse terminal output.
