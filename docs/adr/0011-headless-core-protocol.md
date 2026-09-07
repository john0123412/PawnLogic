# ADR 0011 — Headless Core Protocol

> **Status:** Accepted (2026-09-06).
> The owner reviewed the proposal in-session and directed continued
> implementation; the contract tests and the `pawn serve` skeleton
> landed first, so acceptance rests on a working, tested wire.

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

- [x] Owner approves the protocol shape (transport, request surface,
      event vocabulary, versioning) — approved in-session on 2026-09-06.
- [x] Contract tests for the v1 event/request vocabulary merged.
- [x] `pawn serve` skeleton implemented behind those tests, sharing the
      core driver loop with `--eval` (the `--eval` pre-flight and result
      extraction now share `pawnlogic/headless.py` helpers).
- [x] Live turn events (`stream`/`tool`/turn `status`) forwarded from
      the core's typed Agent Event stream via
      `SessionEventEmitter.content_delta`; no subscriber means zero
      REPL behavior change.


## Revision (Phase 2b M3, 2026-09-06): protocol freeze discipline

Phase 2 shipped the first two frontends of this protocol (the Python
reference client, `frontends/serve_wire.py`, and the Rust ratatui
client, `frontends/ratatui`). Both must keep speaking the identical
wire, so the freeze rules are now explicit:

1. **The golden fixture is the contract.**
   `tests/fixtures/serve_events_v1.jsonl` must exercise every v1 message
   type. The Python contract suite asserts its shape; the Rust
   `wire::tests::parses_every_golden_fixture_line` test must accept the
   same file. Changing the fixture requires the corresponding parser
   change in BOTH languages in the same PR.
2. **v1 is frozen.** Within `{"v": 1}`: event fields are additive only
   (new optional fields are fine; renaming or re-typing existing fields
   is not). New request types or event types require `v: 2` and a new
   fixture (`serve_events_v2.jsonl`) side by side.
3. **Version bump flow.** Bump `PROTOCOL_VERSION` in
   `pawnlogic/headless.py` and the parser's accepted-version set in
   `frontends/ratatui/src/wire.rs` together; the old fixture stays for
   regression, and both frontends negotiate only their exact version.
4. **CI gates.** The Python suite gates the wire on every PR; the 🦀
   Rust Frontend job (cargo test --locked) gates the parser. A protocol
   change that skips one language fails the other's tests.
5. **Distribution decision (M3).** The Rust frontend ships as a
   source-checkout crate only (`frontends/ratatui`), built with
   `cargo build --release` by whoever runs it. No prebuilt binaries and
   no PyPI changes for Phase 2; revisiting that requires a separate
   owner decision because it changes the release pipeline.
