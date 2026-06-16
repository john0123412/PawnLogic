# Changelog

All notable changes to PawnLogic are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.1.1] - 2026-06-15

### Changed
- Rebuilt release documentation and package metadata so the next PyPI long
  description, documentation URL, changelog, README, and supported versions are
  aligned before publishing.
- Provider and model runtime state now uses a re-entrant store lock around
  mutation helpers and snapshot reads, while preserving the legacy
  `PROVIDERS` and `MODELS` compatibility dictionaries.
- Provider commands now read provider/model tables through detached snapshots,
  and the provider TUI uses local stable snapshots for repeated model/provider
  rendering paths.

### Fixed
- Updated the generated runtime environment template to use the current default
  model alias, `ds-v4-flash`, instead of the obsolete `ds-chat` example.
- Updated the security support table so the current public release line is
  visible before publishing.
- Replaced direct runtime config writes with same-directory temporary writes,
  flush/fsync, and `os.replace()` for `custom_providers.json`, sync metadata,
  provider TUI model deletion, and `.env` key persistence.
- Preserved private `0o600` permissions for persisted `.env` keys.
- Quoted first-run shell `export` lines with shell-safe quoting while keeping
  the exact key value in the current process environment.
- Made startup session resume failures, malformed provider JSON, provider TUI
  model deletion failures, and unexpected provider completer refresh failures
  visible through warnings or concise user-facing status messages.

### Tests
- Added coverage for atomic runtime writes, `.env` permissions, shell export
  quoting, malformed provider JSON handling, startup resume failure handling,
  provider TUI model deletion errors, completer refresh warnings, and provider
  store lock re-entrancy.

## [0.1.0] - 2026-06-15

### Added
- Added `core/tool_result.py` with stateless tool-result helpers and a
  per-turn `ToolResultProcessor` for truncation, audit logging, directory
  search hints, repeat-error detection, and anti-loop injections.
- Added `core/turn_guards.py` to concentrate urgent-mode handling,
  empty-response retries, chain-of-thought guard decisions, and concurrent
  truncation cleanup outside the main turn loop.
- Added `core/tool_registry.py` as the canonical ToolRegistry module, with
  snapshot APIs and compatibility refresh paths for legacy `TOOL_MAP` and
  `TOOLS_SCHEMA` callers.
- Added centralized trust-boundary notice helpers in `core/trust.py` so shell,
  browser, fetch, Docker, delegate, and insecure-provider warnings share the
  same permission taxonomy and wording.
- Added static release-workflow guardrails that prevent reintroducing
  long-lived PyPI tokens or `twine upload` publishing paths.

### Changed
- Reduced `AgentSession.run_turn` by moving tool-result processing and guard
  decisions behind dedicated modules while preserving public session behavior.
- Delegate sub-agents now share the main ToolExecutor path and registry
  snapshots, reducing drift between parent and delegated tool execution.
- Dynamic runtime configuration reads and writes now flow through a unified
  runtime interface, reducing split state between command handlers, sessions,
  and configuration globals.
- Provider and model mutation paths now go through a store interface with
  detached snapshots, making provider listing and model visibility more
  deterministic.
- GitHub Actions dependencies now use Node 24 runtime-compatible versions.
- PyPI/TestPyPI publishing now uses PyPI Trusted Publishing / GitHub OIDC with
  split build, publish, and GitHub Release jobs.

### Fixed
- Fixed sandbox timeout cleanup to kill POSIX process groups before falling
  back to the parent process.
- Fixed provider command test isolation around lazy provider initialization.
- Fixed TestPyPI/PyPI release flow so production GitHub Releases are created
  only after a successful PyPI publish.
- Kept trust-boundary warnings visible in user mode while avoiding duplicated
  inline message text across tool modules.

### Tests
- 526 tests passing.
- Added focused coverage for tool-result processing, turn guards,
  ToolRegistry snapshots, delegate execution parity, runtime config access,
  provider store mutation APIs, trust-boundary notices, and publish workflow
  invariants.
- `ruff check .` passing.
- `python -m compileall -q config core pawnlogic tests tools` passing.
- Package build and `twine check` passing.

## [0.0.10] - 2026-06-14

### Added
- Added a repository language policy test that fails when tracked non-`*_CN`
  files contain Chinese text, keeping source, workflows, config, prompts, and
  agent instructions English-only by default.
- Added MCP Roots support for the stdio filesystem server and a configurable
  MCP stderr debug path so startup diagnostics stay controlled.
- Added ToolRegistry snapshot access and a `ToolExecutor` extraction path for
  tool-call parsing, phase routing, handler execution, audited failure
  prechecks, semantic failure recording, and argument normalization.
- Added focused tests for tool routing, tool-call parsing, ToolExecutor data
  contracts, phase switching, audit failure handling, prompt building, context
  window trimming, and run-turn regression behavior.
- Added a local code index tool for source-checkout development workflows.

### Fixed
- Hardened execution-surface defaults: Docker `install_deps` now validates
  package names, URL fetch/browser tools reject unsafe schemes and blocked local
  addresses, browser startup no longer hardcodes `--no-sandbox`, and recursive
  file enumeration filters sensitive paths.
- Fixed streamed-interrupt cleanup so CLI interrupts cancel in-flight streaming
  I/O without leaking interrupt state into later turns.
- Fixed provider runtime initialization by making custom providers load lazily
  through runtime access paths, stabilizing provider/model listing and custom
  provider visibility.
- Fixed sandbox timeout cleanup by starting POSIX subprocesses in a new session
  and killing the process group before falling back to parent-process kill.
- Fixed MCP/provider startup presentation issues by normalizing default custom
  model descriptions and avoiding filesystem server roots warnings.

### Changed
- `AgentSession` now delegates system prompt construction to
  `core/prompt_builder.py`, context-window trimming to
  `core/context_window.py`, tool-call parsing to `core/tool_calls.py`, and
  tool execution helpers to `core/tool_executor.py`.
- Runtime mode and dynamic configuration writes now converge through
  `core.state`, reducing split-brain state between `config` globals and runtime
  session state.
- Tool registration now uses registry snapshots while preserving legacy
  `TOOL_MAP` and `TOOLS_SCHEMA` compatibility for existing callers.
- Delegate sub-agents now read tool schemas and handlers through registry
  snapshots, preserving compatibility while making tool visibility less
  dependent on mutable globals.
- Release automation and project guidance now require changelog-backed GitHub
  release notes and stricter release cleanup checks.

### Tests
- 432 tests passing.
- `ruff check .` passing.
- `python -m compileall -q config core pawnlogic tests` passing.
- Package build, `twine check`, and wheel skill-pack exclusion checks passing.

## [0.0.9] - 2026-06-12

### Added
- Centralized provider/API error formatting in `core/api_errors.py`, covering
  HTTP 401/403/429/500/502/503/504 and transport failures with consistent CLI
  and provider TUI messages.
- Added `RuntimeContext` as the session-owned runtime state object for current
  working directory, workspace path, output sink, mode flags, and dynamic
  configuration.
- Added architecture context documentation in `CONTEXT.md` and ADRs for
  RuntimeContext and shared ProviderRuntime decisions.
- Added SQLite write-contention tests for message autosave, session naming
  updates, and failure-pattern writes.

### Fixed
- Provider API failures now return explicit user-visible errors instead of
  appearing to hang when an API key is rejected, a gateway fails, or a provider
  cannot be reached.
- Stream retry notices are surfaced before final output, and HTTP 403/502 style
  terminal errors now stop the turn cleanly without waiting for more chunks.
- SQLite write paths now share a busy timeout, retry count, and backoff policy
  for locked/busy database errors.

### Changed
- `AgentSession.run_turn` now delegates stream consumption to
  `core/turn_api.py`, keeping turn orchestration separate from model-stream
  parsing.
- Provider CLI commands and the provider TUI now share `core/provider_runtime`
  for connection tests, model fetching, API key saving, and activation state.
- Slash command output is routed through output sinks, preserving human output
  while keeping JSON/eval paths cleaner.
- Ruff checks now include bugbear, simplification, pyupgrade, and Ruff-specific
  hygiene rules, with legacy debt isolated through per-file ignores.
- Run-turn tests now share reusable session and fake-stream helpers instead of
  open-coded stream iterators.

### Tests
- 333 tests passing.
- `ruff check .` passing.
- Documentation heading structure checks passing.

## [0.0.8] - 2026-06-09

### Added
- Fresh installs now generate runtime config templates for environment keys and
  MCP setup, so pip/curl users start with documented local config files.
- Documentation structure checks now guard the English/Chinese README and guide
  heading layout, with `CLAUDE.md` kept as a thin `AGENT.md` wrapper.

### Fixed
- Stabilized interactive `Ctrl+C` handling: in-flight interrupts now show
  immediate feedback, roll back only the current turn, and no longer leak the
  interrupt flag into background auto-naming threads.
- Fixed user-mode streamed output being erased by the thinking spinner during
  multi-chunk responses.
- Fixed restored-history and `Ctrl+Z` prompts that could submit successfully
  but show only token usage when providers returned usage-only, reasoning-only,
  or `choices[].message.content` stream payloads.

### Changed
- Normal interactive mode is now user-friendly by default. Raw tool-call
  arguments, parser diagnostics, reasoning streams, and nonfatal diagnostics are
  shown only in `--debug` mode or after toggling `/mode`.
- Source prompts and user-facing provider/session/workspace command copy were
  normalized to English while keeping Chinese documentation aligned.
- Example MCP configuration now disables the external `fetch` server by default
  because `uvx mcp-server-fetch` can contact PyPI during startup; users can opt
  in explicitly when they need it.
- PyPI wheels and sdists no longer include `skills/`. Local skill packs are now
  source-checkout or user-installed assets; installed users use
  `~/.pawnlogic/skills` when they add packs explicitly.
- Documentation now distinguishes source-checkout skill packs from pip/curl
  runtime data.

### Tests
- 305 tests passing.
- `ruff check .`, source compile checks, package build, `twine check`, and
  wheel/sdist skill-exclusion checks passing.

## [0.0.7] - 2026-06-08

### Added
- `install.sh` one-line installer that creates an isolated venv under
  `~/.local/share/pawnlogic`, installs the official package with pip, and
  writes a permission-safe `~/.local/bin/pawn` launcher.
- Deployment tests for `python main.py --help`, `python -m pawnlogic --help`,
  fresh-venv `pip install .`, and the generated `pawn` command.

### Changed
- `main.py` is now a thin source-checkout compatibility wrapper. The single
  CLI runtime implementation lives in `pawnlogic/cli.py`, and `pawn.sh` now
  launches `python -m pawnlogic`.
- README, README_CN, GUIDE, GUIDE_CN, AGENT, CLAUDE, and CONTRIBUTING now
  document pip as the official install path and `install.sh` as a pip-based
  installer wrapper.

### Tests
- 279 tests passing.
- `ruff check .` passing.

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
  in `[project.urls]` pointing at `GUIDE.md`.
- `docker-compose.test.yml` + `Dockerfile.test` + `.dockerignore` for
  isolated smoke testing (`docker compose -f docker-compose.test.yml run
  --rm smoketest`); the smoke harness hits a real provider API and asserts a
  recognisable response.

### Changed
- **Default wheel is now ~254 KB** (was ~1.7 MB) — `skills/ctf_*/` are
  excluded from the default wheel via `[tool.setuptools.packages.find]
  exclude`; install with `pip install pawnlogic[ctf]` to opt in.
- `requirements.txt` removed; `pip install -e .` is the single source of
  truth. README, README_CN, GUIDE, GUIDE_CN, and `pawn.sh` all updated.
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
