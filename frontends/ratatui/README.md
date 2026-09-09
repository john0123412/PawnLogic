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
command defaults to `python3 -m pawnlogic serve` resolved from `PATH`.
Set `PAWNLOGIC_TUI_SERVER="$PWD/venv/bin/python -m pawnlogic serve"`
when an older installed pawnlogic shadows the repository code. The
override is the complete backend command; the client only appends
`--model <alias>`.

## Keys

| Key | Action |
|-----|--------|
| Enter | submit — a plain prompt when idle, a steer while a Turn runs |
| Esc | interrupt the active Turn |
| Left/Right, Home/End | move the composer cursor |
| Backspace/Delete | edit at the composer cursor |
| Ctrl+A/Ctrl+E/Ctrl+U | move to start/end or clear the composer |
| Bracketed paste | insert pasted text at the composer cursor |
| Up/Down, PageUp/PageDown, mouse wheel | scroll the history pane |
| Ctrl+C or `/q`/`/quit`/`/exit` | shut the server down and exit |

Wire v1 has no modal-selector protocol. Use text forms such as
`/model <alias>` and `/provider list`. Bare `/model`, `/provider`,
`/skills`, and `/setkey` fail immediately with guidance instead of
opening a hidden Prompt Toolkit application.

## Protocol freeze

The client speaks wire v1 (ADR 0011). The contract sample is
`tests/fixtures/serve_events_v1.jsonl`; the Rust parser and the Python
contract suite must both accept it (see ADR 0011's freeze-discipline
section). Unknown protocol versions and malformed events abort parsing
loudly; unknown event types are ignored as required by ADR 0011 so v1
can grow additively.

## Distribution status

Source-checkout build (above). Release tags additionally publish a
prebuilt Linux binary — `pawnlogic-tui-<version>-x86_64-unknown-linux-gnu.tar.gz`
with its sha256 — attached to the GitHub Release by the publish
workflow (see ADR 0011, M3 distribution decision, owner-revised
2026-09-06). PyPI packaging of the frontend remains out of scope.
