# Changelog

All notable changes to PawnLogic are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.0.5] - 2026-06-06

### Added
- `PAWNLOGIC_HOME` runtime directory override for isolating config, logs,
  workspace files, MCP assets, custom providers, and tests.
- `MCP_ENABLED=false` startup switch to skip external MCP loading in test and
  constrained environments.
- Regression tests for runtime path isolation and MCP startup disabling.
- Focused unit coverage for memory, persistence, API client parsing/circuit
  breaker logic, and file patch helpers.

### Fixed
- E2E tests no longer rename or depend on the user's real
  `~/.pawnlogic/mcp_configs.json`.
- Replace remaining bare `except:` handlers in `core/` and `tools/` so
  `KeyboardInterrupt` and `SystemExit` are not swallowed.
- Document the isolated test command in `CONTRIBUTING.md`.

### Tests
- Full suite: 202 tests passing.
- `ruff check .` passing with the configured lint rules.

---

## [0.0.4] - 2026-05-26

### Added
- `--eval <prompt>` single-shot execution mode (non-interactive)
- `--json` machine-readable output (NDJSON) and `--session <id>` flags
- `HumanSink` / `JsonSink` output abstraction (`core/output.py`)
- JSON output for `/sessions`, `/provider list`, `/keys`

### Fixed
- Force loguru stderr level to WARNING in `--json` mode so INFO/DEBUG
  log lines never pollute the NDJSON consumer

### Tests
- 7 new tests for `--eval` flow and JSON command output

---

## [0.0.3] - 2026-05-26

### Refactor
- Extract all 56 slash commands from `main.py` into `core/commands/`
  (system / session / provider / workspace / tools)
- `main.py` reduced from 3192 → 1102 lines (−65.5%)

### Tests
- Add dispatch registry and routing tests for `core/commands/`
  (179 tests total)

---

## [0.0.2] - 2026-05-25

### Fixed
- `mcp` missing from dependencies causing crash on startup
- `mcp_client_manager.py` bare import now guarded with try/except
- Add `docker` optional dependency declaration

---

## [0.0.1] - 2026-05-25

### Fixed
- `NameError: CYAN` in `docker_sandbox.py` — `tool_pwn_container list` action crashed at runtime due to missing import
- `ValueError('empty naming response')` for reasoning models (DeepSeek V4 Flash) — naming requests now use `max_tokens=512` and suppress the reasoning chain via system prompt

### Changed
- **Single source of truth for version** — `VERSION` is defined only in `config/paths.py`; `pyproject.toml` reads it dynamically; all runtime references auto-follow
- **Project directory renamed** from `pawnlogic` to `pawnlogic`
- Removed all hardcoded version strings from comments and docstrings throughout the codebase
- Removed 49 unused imports and dead local variables across `core/` and `tools/` (ruff F401/F811/F841)

### Added
- `CHANGELOG.md`, `SECURITY.md` — standard open-source project files
- `skills/heap_exploit/manifest.json` — `SkillScanner` was silently skipping this skill pack
- `.aiderignore` added to `.gitignore`
- Version badge in README pointing to `config/paths.py` as the canonical version source
- Issue and PR templates under `.github/`

### Documentation
- Rewrote `README.md` and `README_CN.md` with accurate model list, provider table, and project structure

---

## [0.0.0] - 2026-05-18

### Added
- Initial public release
- Multi-provider routing (DeepSeek / OpenAI / Anthropic + custom OpenAI-compatible)
- SQLite session persistence with full-text search, tagging, linking
- RAG knowledge base (`/memorize`, `/knowledge`)
- GSA (Global Skills Archive) with FSRS spaced-repetition scoring
- MCP tool integration (Tavily, Playwright, Filesystem, Fetch)
- Docker sandbox (`run_code_docker`, `pwn_container`, Airlock)
- CTF/Pwn toolchain (GDB automation, ROP chain, libc leak resolution)
- Spec-driven planning with `<plan>` XML gate (CoT Guard)
- Workspace management with auto-naming and cleanup
- `prompt_toolkit` TUI with fuzzy completion and bottom toolbar
- `rich` Markdown rendering for agent output
