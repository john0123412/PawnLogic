# Phase 2 — Steer Handoff and Headless Frontends

> **Status:** Complete and published — P2-0 shipped in 0.3.8, 2a/2b and
> closure in 0.3.9 (both on PyPI and GitHub Releases).
> Owner-directed across five milestones, each merged through its own PR
> with the full gate set and real-API (glm-5.3-flash via the bai route)
> acceptance.

## Scope

Replace the 0.3.7 Esc steering semantics, and stand up the headless
frontend layer that the live terminal's PTK architecture could not host
(fullscreen alternate-screen UI with a floating top status bar and
in-app scrolling).

## Milestones and evidence

1. **P2-0 — steer handoff** (PR #129, in 0.3.8): Esc is a pure interrupt;
   the scheduler hands the queue the baton. Two message-loss defects
   fixed: the live-REPL CLAIM_STEER probe (popped the steer head and
   dropped the receipt) and the drive-loop unwind on the interrupted
   turn's KeyboardInterrupt. ADR 0009 revision; real-PTY accepted.
2. **Phase 2a — reference client** (PR #131): `frontends/serve_wire.py`
   (UI-free wire layer) + `frontends/ptk_client.py` (Prompt Toolkit
   shell) + LatencyRecorder. Real-API report: prompt->turn_started
   median ~4ms, interrupt->turn_cancelled ~2.4ms, chunk gaps <100ms.
   Steer semantics over the wire resolved to abort-and-requeue.
3. **2b M1 — ratatui wire + UI shell** (PR #132): golden fixture
   `tests/fixtures/serve_events_v1.jsonl` pinned by BOTH the Python
   contract suite and the Rust parser; alternate-screen fullscreen UI
   with a floating TOP status bar and in-app scrolling; `--once`
   acceptance mode. cargo test 6/6; real-API accepted.
4. **2b M2 — command passthrough** (PR #133): slash commands ride the
   `command` request; `command_result` renders in the history pane;
   steer acceptance surfaces in the status bar; cargo CI gate added.
   Real-API /keys passthrough accepted.
5. **2b M3 — freeze discipline + distribution** (PR #135): ADR 0011
   freeze rules (golden fixture = contract, v1 additive-only, version
   bump flow, CI gates); publish workflow builds and attaches
   `pawnlogic-tui-<version>-x86_64-unknown-linux-gnu.tar.gz` (with
   sha256) to the GitHub Release on tag pushes; the ratatui render loop
   rebuilt as a synchronous poll loop after a real-PTY defect (server
   state changes never rendered without a keypress). Real-API accepted
   (turn round trip + steer handoff).

## Non-goals observed

- PyPI packaging of the Rust frontend (source-checkout + Release
  tarball distribution only, per the ADR 0011 M3 decision).
- Rust CI beyond `cargo test --locked` (clippy/fmt gates are a follow-up
  decision).

## Known follow-ups

- The 🦀 cargo gate runs only the Fast-Tests class of checks; the Full
  Matrix and Dynamic E2E remain Python-only by design.
- zhipu direct-route verification still blocked on account balance;
  all Phase 2 acceptance ran through the bai route's glm-5.3-flash.
