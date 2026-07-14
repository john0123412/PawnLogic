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
| `core/runtime_metrics.py` | Counter owner | `RuntimeMetrics` class | `test_runtime_metrics.py` | Sole owner of turn, tool, and API call counters. Snapshots are immutable. |
| `core/tool_registry.py` | Capability Interface | `ToolRegistry.register()` / `visible_specs()` | `test_tool_registry.py` | Handler, schema, phase, trust, capabilities registered atomically. No tool without handler. |
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
| `core/provider_tui.py` | Provider TUI | Rendering + key bindings | `test_provider_commands.py` | Thin rendering over `ProviderTUIState`. All mutations through `ProviderRuntime`. |
| `core/provider_tui_state.py` | TUI state | `ProviderTUIState` class | `test_provider_tui_state.py` | Pure state transitions, no IO. Typed, deterministic methods. |

## Security And Trust

| Module | Role | Interface | Tests | Invariants |
|--------|------|-----------|-------|------------|
| `core/trust.py` | Trust boundaries | `TrustBoundaryKind` enum | `test_trust.py` | Every named boundary has a standard notice and legacy level. |
| `core/operation_policy.py` | Operation gating | `OperationPolicy` class | `test_operation_policy.py`, `test_run_shell_policy.py` | Network, destructive, and interactive operations require explicit authorization. |
| `core/path_policy.py` | Path containment | `resolve_within()`, `safe_filename_fragment()` | `test_security.py` | Canonical resolution + `relative_to()` containment. No symlink escapes. |
| `core/host_process.py` | Process runner | `HostProcessRunner.run()` | `test_host_process.py` | Environment scrubbing, timeout, process-group cleanup. |

## Tools

| Module | Role | Interface | Tests | Invariants |
|--------|------|-----------|-------|------------|
| `tools/file_ops.py` | File operations | Tool handlers | `test_security.py` | Workspace-relative writes. Path containment enforced. |
| `tools/shell_ops.py` | Shell orchestration | `run_shell()` | `test_run_shell_policy.py` | Delegates to shared `HostProcessRunner`. |
| `tools/text_patch.py` | Text patching | `apply_text_patch()` | `test_security.py` | Fuzzy SEARCH/REPLACE matching. |
| `tools/docker_sandbox.py` | Docker operations | Tool handlers | `test_docker_policy.py` | Network=none by default. Labelled resources. No unscoped prune. |
| `tools/docker_plan.py` | Docker plans | `build_docker_plan()` | `test_docker_policy.py` | Plan validation separated from SDK calls. |
| `tools/pwn_chain.py` | CTF chain | Tool handlers | `test_ctf_workflow.py` | Binary paths quoted. GDB init filtered. |
| `tools/pwn_binary.py` | Binary analysis | `ElfAnalysisCache` | `test_ctf_workflow.py` | Pure binary/ROP/cyclic helpers. |
| `tools/pwn_debugger.py` | Debugger ops | Tool handlers | `test_ctf_workflow.py` | GDB/interactive process logic. |
| `tools/browser_ops.py` | Browser operations | Tool handlers | `test_browser_ops.py` | Loopback-only fixtures. Path containment for screenshots. |
| `tools/delegate_tool.py` | Delegate tool | `delegate_tool_handler()` | `test_tool_executor.py` | Capability-based filtering. No bypass of host/network/destructive gates. |

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
| `pawnlogic/cli.py` | CLI facade | `run()`, `PawnCompleter` | `test_cli_startup.py`, `test_cli_transcripts.py` | Public entry point. Live model completions. |
| `pawnlogic/startup.py` | Bootstrap | `setup_environment()` | `test_cli_startup.py` | First-run, env, debug mode. |
| `pawnlogic/repl.py` | REPL loop | `run_repl()` | `test_cli_startup.py` | Signal handling, input restoration. |
