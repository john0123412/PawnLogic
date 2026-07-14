# ADR 0001: RuntimeContext Owns Session Runtime State

## Status

Accepted

## Context

PawnLogic historically stored active runtime state in several module-level
pointers, especially current working directory and Workspace path in
`tools.file_ops`. `AgentSession`, slash commands, persistence loading, and file
tools all had to know which globals to mutate.

That made changes hard to localize:

- `/cd`, session creation, and session loading could drift out of sync.
- Tests had to patch `sys.modules` or replace file-tool globals.
- Adding JSON output and runtime mode state created more cross-module coupling.

## Decision

Introduce `RuntimeContext` as the session-owned runtime state object. It holds:

- `cwd`
- `workspace_dir`
- `sink`
- `debug_mode`
- `user_mode`
- `dynamic_config`

`AgentSession` creates and owns RuntimeContext. File tools keep their legacy
`_session_cwd` and `_session_workspace_dir` pointers for compatibility, but the
only write path for those pointers is `sync_runtime_context(ctx)`.

Slash command directory changes, Workspace swaps, and session loading update the
session RuntimeContext first, then synchronize compatibility pointers.

The active context is scoped with `contextvars`, so concurrent tests and future
async tasks can select independent mode, config, paths, and output sinks without
mutating each other's authoritative state. Turn execution and command dispatch
activate the owning session context. Output and dynamic-config helpers consult
that context first.

## Consequences

Runtime state now has a named interface that tests can construct with
`RuntimeContext.for_test(...)`.

Older call sites remain compatible because file tools still expose the legacy
pointers. New code should avoid direct mutation of those pointers and update the
session RuntimeContext instead.

The remaining process globals are one-way compatibility mirrors:

- `core.state.state` mirrors the active mode and dynamic config for legacy
  imports.
- `config.USER_MODE` and `config.QUIET_MODE` mirror output-mode compatibility
  flags.
- `tools.file_ops._session_cwd` and `_session_workspace_dir` mirror active paths.
- `core.commands._common._active_sink` remains a startup fallback when no
  RuntimeContext is active.

New runtime code must not write independent state to these mirrors. It updates
the owning RuntimeContext, then uses the documented synchronization boundary.
