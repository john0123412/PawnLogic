# PawnLogic Ratatui Frontend (Phase 2b)

An alternate-screen, fullscreen terminal client for the PawnLogic
headless serve protocol (ADR 0011). It renders the conversation in an
in-app scrolling history pane with a **floating top status bar** (model,
turn state, elapsed timer) and a one-row composer — the Codex /
Claude-Code-fullscreen interaction model, as opposed to the inline
Python REPL that keeps native terminal scrollback.

## Requirements

- A PawnLogic source checkout or venv with the package importable
  (`pip install -e .` or the project venv) — the client spawns
  `python -m pawnlogic serve` as its backend.
- A configured model (see the main README's provider section).

## Build

```bash
cd frontends/ratatui
cargo build --release
# binary: target/release/pawnlogic-tui
```

## Run

```bash
# Interactive fullscreen session:
target/release/pawnlogic-tui --model bai:glm-5.3-flash

# One-shot acceptance run (renders a single prompt, dumps the screen):
target/release/pawnlogic-tui --model bai:glm-5.3-flash \
    --once "Reply with exactly: ok" --dump /tmp/screen.txt

# One slash command (rendered like the live REPL's /keys):
target/release/pawnlogic-tui --model bai:glm-5.3-flash \
    --once-command "/keys" --dump /tmp/keys.txt
```

Environment: the spawned `pawn serve` inherits your environment; point
`PAWNLOGIC_HOME` at an isolated directory for testing.

## Keys

| Key | Action |
|-----|--------|
| Enter | submit — a plain prompt when idle, a steer while a Turn runs |
| Esc | interrupt the active Turn |
| Up/Down, PageUp/PageDown, mouse wheel | scroll the history pane |
| Ctrl+C | shut the server down and exit |

## Protocol freeze

The client speaks wire v1 (ADR 0011). The contract sample is
`tests/fixtures/serve_events_v1.jsonl`; the Rust parser and the Python
contract suite must both accept it (see ADR 0011's freeze-discipline
section). Unknown versions or event types abort parsing loudly.

## Distribution status

Source-checkout only for now: build locally with cargo. Prebuilt
binaries and PyPI packaging for the frontend are deliberately deferred
pending an owner decision (see ADR 0011, M3 distribution decision).
