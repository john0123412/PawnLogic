# Changelog

All notable changes to PawnLogic are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.0.6] - 2026-06-07

### Fixed
- **`first_run` gate no longer requires `~/.pawnlogic/.env` to exist** when
  API keys are injected via process environment variables (Docker, CI, K8s
  deployments). The pre-fix check short-circuited on `not _ENV_PATH.exists()`,
  blocking users who never wrote a key file even though their keys were in
  the process env. Custom providers from `custom_providers.json` are now
  recognised on the same footing as built-in providers — `_has_any_api_key()`
  uses no hardcoded provider names.
- **Top-level `main` module name conflict resolved** for installed wheels:
  the `pawn` console script now targets `pawnlogic.cli:run`, and the wheel no
  longer ships `main.py` as an importable top-level module. The source checkout
  keeps a small root `main.py` compatibility wrapper for `python main.py` and
  legacy tests.

### Added
- Two regression tests in `tests/test_deployment_friendly.py` for the
  `first_run` gate (process-env-only key; custom-provider-only key). The
  tests fail when reverted against the pre-0.0.6 code.
- `pawnlogic[ctf]` optional extra (`pwntools`, `ROPgadget`, `ropper`) for
  users who want the CTF skill markdown and tooling.
- `Development Status :: 4 - Beta` classifier on PyPI; `Documentation` URL
  in `[project.urls]` pointing at `GUIDE_EN.md`.
- `docker-compose.test.yml` + `Dockerfile.test` + `.dockerignore` for
  isolated smoke testing (`docker compose -f docker-compose.test.yml run
  --rm smoketest`); the smoke harness hits a real provider API and asserts a
  recognisable response.

### Changed
- **Default wheel is now ~254 KB** (was ~1.7 MB) — `skills/ctf_*/` are
  excluded from the default wheel via `[tool.setuptools.packages.find]
  exclude`; install with `pip install pawnlogic[ctf]` to opt in.
- `requirements.txt` removed; `pip install -e .` is the single source of
  truth. README, README_CN, GUIDE_EN, GUIDE_CN, and `pawn.sh` all updated.
- README "What's New" sections now link to `CHANGELOG.md` instead of being
  re-edited each release.
- `.env.example` clarifies that `XIAOMI_API_KEY` is for a custom provider
  registered in `~/.pawnlogic/custom_providers.json`, not a built-in.
- Workflow header comments no longer pin a specific version number.

### Tests
- 217 tests passing (was 215; +2 regression tests).
- `ruff check .` passing.

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
- Deployment-friendly startup regression tests for `.venv` discovery, missing
  HOME fallback, first-run JSON behavior, wizard model selection, and `.env`
  permissions.
- Latest built-in model aliases for OpenAI GPT-5.5 / GPT-5.4, Claude Opus 4.6,
  and DeepSeek V4.

### Fixed
- **Code audit — 5 bugs fixed:**
  - `core/api_client.py`: bare `except:` in `parse_sse_delta` → `except Exception:`
    (previously swallowed `SystemExit`/`KeyboardInterrupt`)
  - `core/persistence.py`: `session.model["id"]` crash in `memorize()` →
    `MODELS.get(session.model_alias, ...)` (session has `model_alias` string, not dict)
  - `tools/file_ops.py`: `_apply_patch_blocks` and `tool_patch_file` mode B bypassed
    workspace redirection — added `_resolve_write_path()` calls
  - `core/memory.py`: `search_knowledge` did full table scan in Python →
    SQL `LIKE` filtering at DB level
  - `main.py`: `first_run_wizard()` called `input()` in CI despite API keys set —
    added `PAWNLOGIC_TEST_MODE` guard to skip wizard/key prompts
- E2E tests no longer rename or depend on the user's real
  `~/.pawnlogic/mcp_configs.json`.
- Replace remaining bare `except:` handlers in `core/` and `tools/` so
  `KeyboardInterrupt` and `SystemExit` are not swallowed.
- Make first-run setup friendlier for non-technical users: preserve real
  `SystemExit` exit codes, return clean JSON errors before interactive setup,
  secure generated `.env` files with `0600`, and automatically start with the
  model selected in the wizard.
- Improve startup portability with `.venv` launcher support, `readlink -f`
  fallback, Python 3.10+ checks, missing-HOME fallback, and writable runtime
  directory checks before SQLite initialization.
- Hide CTF tool status on normal startup unless relevant tools are installed,
  and make browser optional dependency errors point to `pawnlogic[browser]`.
- Document the isolated test command in `CONTRIBUTING.md`.

### Tests
- Full suite: 208 tests passing.
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
