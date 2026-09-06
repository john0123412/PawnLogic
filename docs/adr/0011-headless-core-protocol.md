# ADR 0011 — Headless Core Protocol

> **Status:** Proposed.
> Phase 1 of the post-0.3.7 roadmap. This ADR proposes the process
> boundary that lets a future native frontend (Rust/ratatui candidate,
> Phase 2) or any script drive the existing Python core. It moves to
> **Accepted** only after the owner approves the protocol shape and the
> first contract tests land.

## Context

The interactive surface and the agent core currently share one Python
process: `pawnlogic/cli.py` owns the REPL, Prompt Toolkit composer, and
command dispatch, while `core/` owns sessions, the tool registry,
security policies, providers, and MCP. The 0.3.7 cycle showed that this
coupling makes the terminal layer the most fragile part of the codebase:
every UI experiment re-risks PTY handling, repaint races, and the
single-Application modal contract (ADR 0010).

Two user goals drive the next iteration: faster startup (addressed in
0.3.7+ by lazy-loading; `--help` is ~0.24 s) and a better interface. A
native TUI cannot be evaluated safely while the core is only reachable
through the Python REPL process. At the same time, the project already
has a headless seam — `pawn --eval --json` emits NDJSON events
(`result`, `error` with `stage`) and non-zero exit codes for
API failure (exit 1) and missing keys (exit 2) — but it is one-shot,
unversioned, and undocumented as a contract.

## Decision

From this ADR forward, a headless core protocol may be built under the
following constraints. They are recorded so future PRs can be rejected
on sight if they violate them.

1. **The Python core stays authoritative.** Sessions, the tool
   registry, Operation/Network/Trust policies, provider routing, and
   MCP live in the core process. A frontend never re-implements,
   bypasses, or second-guesses them.
2. **Transport is NDJSON over stdio.** One JSON object per line, both
   directions. No sockets, no remote transport, no multi-client fan-out
   in this ADR's scope. Every message carries a version envelope:
   `{"v": 1, "type": "...", ...}`. Unknown `type` values must be
   ignored by both sides, so fields can evolve without a handshake.
3. **The request surface is minimal.** `prompt` (text for one turn),
   `interrupt` (user interrupt of the running turn), `command` (one
   slash-command line, resolved by the core's command dispatcher), and
   `shutdown` (graceful exit). Everything else is out of scope until a
   follow-up ADR extends it.
4. **The event vocabulary extends the existing `--eval --json` wire.**
   `result`, `error` (with `stage`), `stream` (content deltas), `tool`
   (call start/result), and `status` (phase/model/timer) are the
   starting set. Event fields are additive only within a major version.
5. **One process, one session.** A headless process serves exactly one
   AgentSession. Parallel sessions mean parallel processes; the core
   never multiplexes sessions over one stdio pair.
6. **The Prompt Toolkit REPL is unaffected.** The live terminal keeps
   its ADR 0010 contract. The headless mode is a separate entry point
   (planned as `pawn serve`), not a flag bolted onto the REPL loop.
7. **Contract tests pin the wire.** Every event/request type in the
   vocabulary has a schema-level test asserting field names, types, and
   the version envelope, so a frontend can rely on them across patch
   releases.

## Consequences

- Phase 2 frontends become evaluable without touching the Python
  terminal layer, and the historical `--eval --json` contract becomes
  the v1 subset of a versioned protocol instead of a private format.
- The core must expose a programmatic driver loop (submit prompt,
  await events, deliver interrupts) that the synchronous `--eval` path
  and the new entry point share, so behavior cannot drift between them.
- stdio framing means large tool results (screenshots) are paths, not
  payloads — this already holds (MCP assets are returned as file paths).
- A native frontend still needs the owner's real-PTY acceptance per the
  0.3.7 process; this ADR does not change that acceptance bar.

## Acceptance

- [ ] Owner approves the protocol shape (transport, request surface,
      event vocabulary, versioning).
- [x] Contract tests for the v1 event/request vocabulary merged.
- [x] `pawn serve` skeleton implemented behind those tests, sharing the
      core driver loop with `--eval` (the `--eval` pre-flight and result
      extraction now share `pawnlogic/headless.py` helpers).
