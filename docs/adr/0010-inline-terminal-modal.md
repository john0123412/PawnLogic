# ADR 0010 — Inline Terminal and Single-Application Modal

> **Status:** Proposed (implementation landed in 0.3.7; acceptance
> gates pending). The 0.3.7 rebuild on
> `rebuild/inline-terminal-0.3.7` implements every decision in this
> ADR: `full_screen=False`, `mouse_support=False`, the
> `TerminalTranscript` single owner, and the dual-path
> `controller.run_selector` dispatch for every interactive selector.
> Per the Acceptance section below, the ADR moves to **Accepted** only
> after the 0.3.7 PR is merged, the 0.3.7 release is published to
> PyPI, and the owner runs a real PTY smoke against the live composer.

## Context

The persistent composer in 0.3.6 still uses the alternate screen buffer
and owns the mouse, so the host terminal cannot scroll, select, or copy
the live transcript. The interactive selectors (`/model`, `/planguard`,
`/provider`, `/skills`) each tear down the main `Application`, restore
stdout, run a separate `Application`, and rebuild the main `Application`
on return. That exit-rebuild handoff has known races, drops the queue
preview, and breaks the recovered-draft marker on round trip.

## Decision

From this ADR forward, the live terminal and every interactive selector
inside it must follow these constraints. They are recorded here so future
PRs can be rejected on sight if they violate them.

1. The live composer must not enter the alternate screen buffer. Prompt
   Toolkit must be constructed with `full_screen=False`. Native terminal
   scrollback, mouse selection, and copy-paste must work for the user
   while the composer is running.
2. The live composer must not enable PT mouse-tracking modes (`?1000h`,
   `?1002h`, `?1003h`, `?1006h`). PT must be constructed with
   `mouse_support=False`. Wheel events must flow to the host terminal
   first; coordinate-aware terminal capabilities (iTerm2, Kitty) may
   still be honored when explicitly advertised.
3. Every interactive selector must run as a dialog inside the same
   `Application` as the live composer. The selector must open and close
   without calling `Application.exit()` and without spawning a second
   `Application.run_async()`. The main `Application` task must remain
   alive for the entire round trip.
4. The terminal layer owns the modal lifecycle: overlay placement, focus
   save and restore, key bindings while a modal is open, a bounded modal
   stack, and `Application.invalidate()` when the modal state changes.
   Command-layer code must not know about the specific `Application`,
   the controller, or the alternate screen at all.
5. The persistent transcript must be routed through a single
   `TerminalTranscript` owned by the persistent terminal. The
   `TerminalSink` and stdout/stderr proxy must both write to that
   transcript, which in turn writes to the host terminal output. The
   legacy `_output_chunks` parallel buffer in `PersistentTerminal` must
   be removed so transcript ownership is unambiguous.
6. The readline fallback must remain serial and unchanged. The in-
   `Application` modal path is gated on Prompt Toolkit being available
   and active; the readline path keeps its existing text controls.

## Consequences

- Any new interactive selector must be added to the in-`Application`
  modal host, not as a standalone `Application`. Future cycle proposals
  that want to keep the exit-rebuild pattern must first amend this ADR.
- Removing the alternate screen exposes previously hidden PT key
  sequences to the host shell. The bounded escape-sequence window from
  0.3.6 and the new transcript buffer are the mitigations; the RED
  tests in `tests/test_live_terminal_inline.py` and
  `tests/test_model_selector_modal.py` must keep them covered, and real
  PTY smoke tests must keep the host terminal scrollback / selection
  contract covered manually.
- The terminal layer now owns more state (modal stack, focus memory,
  transcript). The stable typed-island list in `AGENT.md` will grow by
  one (`pawnlogic/terminal_transcript`) only after the implementation
  lands and passes CI.

## Acceptance

This ADR is **Accepted** when all of the following are true together:

- The PR that implements the 0.3.7 inline-terminal-stability plan is
  merged into `main`.
- The 0.3.7 release is published to PyPI.
- A real PTY smoke test, run by the human owner, confirms that the host
  terminal can scroll, select, and copy the live transcript while the
  composer is running, and that selectors round-trip without rebuilding
  the main `Application`.

Until then, the ADR remains **Proposed** and any implementation work
must not be described in `CHANGELOG.md`, `SECURITY.md`, `AGENT.md`, or
the plan file as "complete", "shipped", or "released".
