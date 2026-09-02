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

## Planned 0.3.0 Terms

The terms below are reserved by the proposed 0.3.0 architecture plan. They
describe planned contracts and do not imply that the implementation already
exists.

### Extension

An Extension is a separately distributed capability package discovered by the
PawnLogic host. Installing an Extension makes its metadata discoverable;
explicit enablement is required before its Tools, commands, prompt fragments,
or runtime Adapters become available.

Extensions must declare compatibility, trust, capabilities, and ownership of
every contribution. A failed or disabled Extension must not leave partial
contributions in the active runtime.

### Agent Task

An Agent Task is a structured delegated objective containing focused
instructions, model requirements, selected context references, Tool
capabilities, and execution budgets. The host validates the task before a
delegated agent runs.

The parent Agent may request a Model Alias, but the host Model Router makes the
final selection under Provider visibility, user policy, capability, and budget
rules.

### Engagement Scope

An Engagement Scope is the explicit authorization envelope for
network-security work. It defines included and excluded targets, allowed action
classes, budgets, evidence location, and expiry.

Active network-security Tools must fail closed when no valid Engagement Scope
contains the resolved target and requested action.

### Knowledge Record

A Knowledge Record is durable local information with a stable identity,
content, source, provenance, and revision metadata. Retrieval indexes and
caches may project Knowledge Records, but they are not the durable source of
truth.

### Agent Event

An Agent Event is a versioned runtime observation such as text output, Tool
lifecycle, retrieval evidence, policy decision, delegated-agent lifecycle,
usage, error, or Turn completion.

Human terminal, NDJSON, and future UI renderers are Output Adapters over Agent
Events.

## 0.3.6 Terms

The terms below are reserved by the 0.3.6 live turn control plan
(docs/plans/0.3.6-live-turn-control.md) and ADR 0009. They describe the
contract the Turn Scheduler implements.

### Turn Scheduler

The Turn Scheduler is the deep module that owns turn execution state for one
session: the active Turn, the steering queue, the follow-up queue, the
recovered draft, state transitions, and persistence checkpoints. Its public
surface is `submit`, `control`, and `view`; nothing outside the scheduler
mutates session queue state directly.

### Steering Message

A Steering Message is user input submitted while a Turn is running. It takes
effect at the next safe point, enters context as a new user message, and
never merges with other submissions. If a text-only Turn reaches natural
completion without exposing a safe point, an unclaimed Steering Message rolls
forward as the next independent Turn instead of remaining stuck in the queue.

### Follow-up Message

A Follow-up Message is user input queued to run after the current Turn stops
naturally. Follow-ups are consumed one per Turn, in submission order.

### Safe Point

A Safe Point is the boundary after the current Tool Call completes where a
steering message can be applied. Tool calls from the same batch that have not
started are recorded as protocol-complete skipped results.

### Recovered Draft

A Recovered Draft is an unfinished Turn restored after an interruption or
process restart. After cooperative cancellation settles, the live terminal
automatically presents it as editable input. Submitting replaces and runs it
exactly once; it never replays side-effect Tools automatically.

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
