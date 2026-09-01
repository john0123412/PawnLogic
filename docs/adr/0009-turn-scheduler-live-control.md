# ADR 0009: Turn Scheduler and Live Turn Control

## Status

Accepted after the 0.3.6 contract review and the P0-P6 implementation gates.
The release remains an unreleased 0.3.6 candidate until packaging, remote CI,
and the release approval gate complete.

## Context

The 0.3.5 recovery work made interrupted Turns retryable and edit-safe, but
the interaction model is still stop-and-resume: the REPL reads no input while
a Turn runs, Ctrl+C is the only mid-Turn input path, and
`core/message_queue.py` mixes future work, in-flight pending work, and retry
state in one deque that silently drops the lowest-priority message when full.
Mainstream agent CLIs expose live control instead: submit a steering message
while running, queue follow-ups, and interrupt one Turn without losing
queued work.

Blocking this change are four structural facts:

1. `core/interrupts.py` holds one module-level `threading.Event`; it is not
   session- or Turn-scoped, and Python signal handlers only run on the main
   thread, so a worker-thread execution model cannot rely on signals.
2. `AgentSession` mixes turn execution, queue policy, and persistence; its
   architecture budget (2100 lines) has almost no headroom.
3. Module-level globals (`_user_mode`, `_debug_mode`, `_dynamic_config`) and
   RuntimeContext legacy mirrors are read and written across the call stack;
   a second thread makes unsynchronized access observable.
4. Crash recovery can re-enqueue pending work, so a side-effect tool could
   auto-replay.

## Decision

### TurnScheduler as the deep module

A new `core/turn_scheduler.py` replaces `core/message_queue.py`. Its public
surface is three calls: `submit(submission) -> SubmissionReceipt`,
`control(action) -> ControlReceipt`, and `view() -> SchedulerView`. Internals
own the active Turn, the steering queue, the follow-up queue, the recovered
draft, state transitions, and atomic persistence checkpoints. Submissions
carry stable IDs and FIFO within each lane; mixed lanes follow the safe-point
policy, with steer taking precedence over follow-up. A full queue is an
explicit error, never a silent drop. The unused `priority` ordering and the
module-level singleton are removed. One worker serializes execution per session
so message history is never mutated concurrently.

The production executor Adapter wraps `AgentSession._run_turn_active()`;
tests inject an in-memory Adapter. FIFO is guaranteed within each lane; mixed
lanes are resolved by safe-point policy, with steer taking precedence over
follow-up at P3. CLI, remote control, and tests depend on the scheduler
Interface, never on session internals such as `_message_queue` or
`_autosave()`.

### Steering and safe points

A steer submitted while running is consumed at the next safe point: the
boundary after the current Tool Call completes. Tool calls in the same batch
that have not started are recorded as protocol-complete `skipped` results.
Plan-guard interaction is fixed here: a skipped batch still counts as one
observed batch for the escalation counter, so steering cannot be used to
reset or evade the two-strike escalation rule. The steer is appended as a new
user message and the model is requested again. Streaming text-only responses
are not torn apart; Esc stays the immediate-interrupt path.

Follow-ups are consumed only after the agent stops naturally, one per Turn,
so distinct user intents never merge.

### Cancellation

Each Turn owns a cancellation token following the delegation runtime pattern
(`core/agent_orchestrator.py`). Esc and Ctrl+C are key bindings that call
`control()`; the worker observes the token cooperatively. Signal handlers are
never used to stop the worker thread. An interrupt fully closes unfinished
Tool Call protocol pairs before the Turn is marked interrupted.

### Threading migration

Execution moves to a worker thread in two independently accepted stages:
P2a keeps the Prompt Toolkit composer permanently live on the main thread
with output through the Output Sink, then P2b moves turn execution into the
worker after an audit lands for every module-level global and RuntimeContext
legacy mirror, classifying each as encapsulated or thread-confined. The
readline fallback stays serial with an explicit capability notice.

### Persistence

Scheduler snapshots carry a schema version and are written atomically on
every transition. Old queue state migrates deterministically (queued to
follow-up, pending to recovered draft). Restart restores queues and turns an
unfinished Turn into an editable draft; side-effect Tools are never replayed
automatically.

### Queue presentation

Queue presentation is an Adapter over the immutable `SchedulerView`. The
Prompt Toolkit menu is available only while the UI thread is idle; an active
worker is never asked to share stdin. Stable-ID remove, recall, and
steer/follow-up conversion are routed back through typed scheduler controls,
so every mutation retains checkpointing and active/recovered safety rules.

### P0 verification contract

The P0 terminal baseline exercises the Prompt Toolkit path and a real native
blocking Tool Call. It submits a steering line while the Tool Call is blocked,
asserts that no second model request starts before the Tool Call completes, and
then verifies that the next request contains the steer. A text-only stream must
finish intact before any submitted follow-up is requested. The readline
fallback remains serial and buffers input until the active Turn finishes.

The baseline may use imperative `pytest.xfail` only for the known
pre-scheduler mismatch after all startup, input-mode, Tool Call, and trace
preconditions have passed. Function-level or module-level xfail markers are
not permitted because they can hide harness and setup failures.

### Version policy note

This work ships as 0.3.6. Per the AGENT.md Version Numbering Policy the
minor digit does not move without an explicit owner decision, and the 0.3.6
version PR stays unmerged until the previous release completes.

### Verification evidence

- P0-P5 scheduler, live-composer, cancellation, runtime-context, and
  persistence regression suites were previously green; the maintained
  targeted set records 112 passing tests.
- P6 queue controls, conversion, immutable rendering, recall, toolbar, and
  active-stdin isolation add 171 passing targeted tests.
- Dynamic terminal E2E is green: 23 tests passed. Fast non-E2E validation is
  green: 1,432 tests passed with 7 deselected and 5 Python tarfile warnings.
- Ruff, CI-equivalent typed-island mypy (including the six live-control
  modules), documentation structure, release consistency, repository
  language policy, architecture budget, code-index freshness, and diff checks
  are green. Packaging/fresh-install validation is intentionally not claimed
  by this ADR and remains a release-stage gate.

## Consequences

- `core/session.py` must shrink: execution extraction moves code out, keeping
  the file under its architecture budget with real headroom.
- The MessageQueue public API is removed; its callers migrate to the
  scheduler in the same cycle, and the 0.3.5 recovery E2Es become regression
  baselines for the new contract.
- `/abort` changes meaning; documentation in both languages migrates in the
  same commit series so no mixed semantics remain.
- Cross-process control stays out of scope until a socket/app-server layer
  exists.
