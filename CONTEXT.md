# PawnLogic Context

This file defines project vocabulary for architecture reviews, tests, and
future agent work. Use these terms consistently in code comments, docs, issues,
and ADRs.

## Domain Terms

### Turn

A Turn is one user prompt processed by an `AgentSession`. It starts when the
prompt is appended to session messages and ends when the model stream finishes,
an error terminates the attempt, or the turn is interrupted.

Turn responsibilities include context trimming, provider request execution,
tool-call handling, visible output, token counters, failure recording, and
session persistence.

### Provider

A Provider is a model backend configuration: name, base URL, API format, API key
environment variable, active state, and loaded model list.

Built-in providers and custom providers share the same runtime behavior. Adding
a Provider records configuration; activating it makes its configured chat models
eligible for `/model` and completions.

### Model Alias

A Model Alias is the stable local name used by PawnLogic to select a concrete
model. It maps to provider metadata in `MODELS`, including provider name, model
ID, display color, and capability flags such as vision or reasoning.

User-facing commands should prefer Model Alias names over provider-specific
model IDs unless they are displaying fetched provider results.

### Runtime Home

Runtime Home is the user data root for mutable local state. By default it is
`~/.pawnlogic`, and tests must isolate it with `PAWNLOGIC_HOME`.

Runtime Home contains provider configuration, secrets, logs, SQLite memory, MCP
configuration, and workspaces. It must not be committed to the repository.

### Workspace

A Workspace is the per-session directory under Runtime Home where relative file
writes are redirected. It is distinct from the process current working
directory, which controls shell and read-oriented operations.

Session auto-naming may rename a Workspace and leave compatibility links so old
absolute paths continue to resolve.

### Tool Call

A Tool Call is a model-requested action executed by PawnLogic. It has a tool
name, JSON arguments, a call ID, and a tool result message returned to the model.

Tool Calls are subject to execution protocol checks, security policy, output
truncation, failure recording, and user-mode/debug-mode rendering.

### Skill Pack

A Skill Pack is a local instruction bundle that can be matched into a Turn to
improve domain-specific behavior. Skill Packs live outside normal conversation
messages until selected, then their formatted guidance is injected into the
session prompt context.

Skill Packs are runtime assets, not package data in PyPI distributions.

## Runtime State Terms

### RuntimeContext

RuntimeContext is the active session runtime object containing current working
directory, Workspace path, output sink, mode flags, and dynamic configuration.
It concentrates runtime state that was previously spread across module globals.

Legacy modules may still expose compatibility pointers, but they should be
synchronized from RuntimeContext instead of being independently mutated.

### Output Sink

An Output Sink is the active object that renders user-visible output. HumanSink
prints terminal text; JsonSink emits NDJSON for automation. Slash commands
should write through the active Output Sink rather than calling `print()`
directly.
