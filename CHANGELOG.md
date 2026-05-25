# Changelog

All notable changes to PawnLogic are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.1] - 2026-05-25

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

## [1.0] - 2026-05-18

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
