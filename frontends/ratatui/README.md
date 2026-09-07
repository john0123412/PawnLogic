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
`PAWNLOGIC_HOME` at an isolated directory for testing. The backend
command defaults to `python -m pawnlogic` resolved from `PATH` — set
`PAWNLOGIC_TUI_SERVER="python -m pawnlogic"` (or a venv's absolute
python) when an older installed pawnlogic shadows the repository code.

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

Source-checkout build (above). Release tags additionally publish a
prebuilt Linux binary — `pawnlogic-tui-<version>-x86_64-unknown-linux-gnu.tar.gz`
with its sha256 — attached to the GitHub Release by the publish
workflow (see ADR 0011, M3 distribution decision, owner-revised
2026-09-06). PyPI packaging of the frontend remains out of scope.
