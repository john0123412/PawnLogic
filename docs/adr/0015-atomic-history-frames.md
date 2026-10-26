# ADR 0015 — Atomic History Frames for the Inline Terminal

> **Status:** Proposed — owner-verified on 2026-10-25 (no flicker in
> Windows Terminal under WSL); moves to **Accepted** once merged and
> released. Amends ADR 0010: the inline-terminal constraints stand; only
> the mechanism that moves output into the host scrollback changes.

## Context

The live terminal is an inline Prompt Toolkit application (ADR 0010):
streamed output appears in a viewport above the composer and is then moved
into the host terminal's native scrollback. That move went through Prompt
Toolkit's `run_in_terminal`, which reaches the terminal as five or six
separate writes:

1. `renderer.erase()` erases the block and flushes;
2. the TTY switches to cooked mode and the caller writes the rows;
3. `renderer.reset()` flushes again;
4. a cursor-position request (`ESC[6n`) is sent;
5. the block is redrawn and flushed;
6. the cursor-position reply changes the block height and it is redrawn
   once more.

Between write 1 and write 5 the terminal displays the erased block. The
owner reported that as the whole screen flashing every time output moved
into the scrollback, and asked that the terminal be drawn the way
mainstream open-source agents draw theirs. A 2-second debounce had been
added earlier to make the flashes rarer; it made them less frequent, not
gone. Separately, the 250 ms status ticker repainted an unchanged screen
four times a second; that is fixed independently (the ticker now repaints
only when a polled surface changed) and is not part of this decision.

Codex's TUI (`codex-rs/tui`, studied from its `insert_history.rs`,
`tui.rs` and `tui/scrollback.rs`) solves the same problem with the same
inline-viewport model:

- every draw runs inside `stdout().sync_update(...)`, i.e. DEC private
  mode 2026 (synchronized output);
- finalized history is queued and flushed at the start of the next frame,
  inside that same synchronized update, before the viewport is drawn;
- on most terminals history is inserted with a DECSTBM scroll region above
  the viewport, which leaves the viewport untouched; on Windows Terminal
  (detected through `WT_SESSION`) Codex uses a "full-screen" mode instead
  — clear the viewport, write the rows, scroll the whole screen, and
  repaint the viewport in the same frame — because partial scroll regions
  discard rows there instead of moving them into the scrollback.

## Decision

Move output into the host scrollback with one **history frame**
(`pawnlogic/terminal_frames.py`):

1. The live terminal renders through `SynchronizedVt100Output`, a
   `Vt100_Output` whose every flush is one write bracketed by
   `ESC[?2026h` … `ESC[?2026l`. Terminals that implement mode 2026
   (Windows Terminal since the 1.24 preview, reaching stable through a
   servicing release and 1.25; kitty; WezTerm; iTerm2; foot; Ghostty;
   Alacritty) present each write atomically; terminals that do not ignore
   the private mode and still receive a single write.
2. `write_history_frame` holds every flush (`output.frame()`), then runs
   the renderer's own `erase()`, writes the pre-wrapped rows, and calls
   `Application._redraw()` so the block is repainted from a fresh renderer
   state. The terminal receives one write and never displays the erased
   block. No cooked-mode switch and no cursor-position request happen per
   flush.
3. Insertion uses Codex's full-screen strategy on every terminal: the rows
   are written where the block was and scroll the whole screen once they
   reach the bottom. That is the strategy Codex itself uses on Windows
   Terminal, the owner's terminal, and it keeps native scrollback correct
   in tmux. A DECSTBM scroll-region strategy was not adopted: it is unsafe
   on Windows Terminal and would need terminal detection to be worth it.
4. The repaint keeps the block's bottom edge in place: the rows the
   history takes come off the top of the block (`_HeadroomContainer`
   floor), so the composer does not jump up after a selector or preview
   closes.
5. The delivery cursor advances before the repaint (the block must not
   show delivered rows again) and is restored if the frame cannot be
   written; the bounded retry and circuit breaker are unchanged.
6. Because a flush is now one atomic write, the live-flush interval drops
   from 2 s to 0.1 s; it only batches a fast stream. Lines move from the
   live viewport into the scrollback at the same screen rows.
7. `FramedApplication` wraps Prompt Toolkit's resize handler in one frame,
   so a resize repaint is one write as well.

## Alternatives considered

- **Keep `run_in_terminal` and debounce harder.** Rarer flashes, not no
  flashes; this is what the 2 s debounce already was.
- **Alternate screen (full-screen TUI).** Removes flicker but loses native
  scrollback, selection and copy — the constraint ADR 0010 exists to keep.
- **Rewrite the terminal UI in Rust or TypeScript.** The flicker came from
  the escape-sequence strategy, not the language; the same frames are
  expressible through Prompt Toolkit's output buffer. A different frontend
  remains possible through the headless wire-v1 protocol (ADR 0011) and the
  existing ratatui crate, but it is a parity project (selectors, provider
  and skills TUIs), not a flicker fix.

## Consequences

- `run_in_terminal` is no longer on the streaming path. It remains only
  for rare explicit notices (`pawnlogic/cli.py:_terminal_notice`), which
  still erase and redraw the block once each.
- The frame relies on two Prompt Toolkit internals: `Vt100_Output`'s
  write/flush split (subclassed) and `Application._redraw()` (with an
  `invalidate()` fallback that loses atomicity, not correctness).
  `prompt_toolkit>=3.0` is not pinned tighter; `tests/test_terminal_frames.py`
  fails if either stops behaving as assumed.
- A frame repaints the whole block, so a large mounted selector makes each
  flush larger. With mode 2026 that is invisible; without it, it is still
  one write.
- Atomicity can be verified from bytes (tests, PTY probes), but "does not
  flicker" can only be verified by eye in the owner's terminal.
