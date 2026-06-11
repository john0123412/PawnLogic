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

## Consequences

Runtime state now has a named interface that tests can construct with
`RuntimeContext.for_test(...)`.

Older call sites remain compatible because file tools still expose the legacy
pointers. New code should avoid direct mutation of those pointers and update the
session RuntimeContext instead.

The remaining module-level compatibility pointers are transitional. They should
not gain new independent state.
