# PawnLogic - Claude Code Instructions

This file is the repository-level operating guide for Claude Code sessions.
Keep it in sync with `AGENT.md` whenever project workflow, provider behavior,
documentation policy, or verification requirements change.

## Project Summary

- Product: a terminal AI agent with multi-provider model routing, persistent
  SQLite memory, real tool execution, MCP integrations, and CTF-oriented tools.
- Installed CLI entry point: `pawn` -> `pawnlogic.cli:run`.
- Source checkout entry point: `python main.py`.
- Runtime data: `~/.pawnlogic/` by default. Tests must use a temporary
  `PAWNLOGIC_HOME`.
- Version source of truth: `config/paths.py:VERSION`.
- Build backend: setuptools with dynamic version in `pyproject.toml`.

## Non-Negotiable Safety Rules

Never commit local runtime data, user-specific paths, secrets, or machine
identifiers.

Do not commit:

- `.env`, `.env.*`, API keys, tokens, private keys, certificates, or secret
  config files.
- `custom_providers.json`, `pawn.db`, SQLite files, or runtime MCP configs.
- Absolute local paths such as `/home/<user>/...`, `/Users/<user>/...`, or
  `C:\Users\<user>\...`.
- Machine names, internal hostnames, VPN names, LAN domains, or internal IPs.
- Real provider keys in docs, tests, fixtures, commit messages, or logs.

Allowed runtime paths in documentation:

- `~/.pawnlogic/...`
- `${HOME}/...`
- `$PWD/...`
- relative paths
- placeholders such as `<name>`, `<path>`, and `<your-username>`

Before every commit, run staged-diff leak scans:

```bash
git diff --cached | grep -nE "/home/[^/ ]+/|/Users/[^/ ]+/|C:\\\\Users\\\\" || true
git diff --cached | grep -nE "DESKTOP-[A-Z0-9-]+|\.local\b|\.lan\b" || true
git diff --cached | grep -nE "sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{50,}|tp-[a-z0-9]{30,}" || true
```

If any match is a real leak, stop and fix it before committing.

## Provider And Model Rules

The provider and model workflow is user-facing and must remain consistent
across code, tests, and documentation.

- DeepSeek is always active by default and must not be deactivated.
- Custom providers are inactive by default.
- Multiple custom providers may be active at the same time, but activation must
  be explicit through `/provider activate <name>` or the provider TUI.
- `/model` and command completion must show only:
  - DeepSeek models with a configured key.
  - Models from providers that are both active and have a configured key.
- Adding a provider must not require a successful connection test.
- Fetching models must register only user-selected, supported chat models.
- Fetch must hide legacy, image, audio, embedding, realtime, and other non-chat
  models before registration.
- Fetch must perform provider compatibility probing when possible so unsupported
  chat models are hidden before the user selects them.
- Test Connection must use a loaded chat model for that provider. Do not
  hardcode obsolete models such as `gpt-3.5-turbo`, `ds-chat`, or `ds-r1`.
- If a provider has no loaded chat model, Test Connection should tell the user
  to fetch models first.
- The provider TUI must support paste and independent focus for Name, Base URL,
  Format, and API Key fields.
- The provider TUI must provide an explicit confirm/exit action; users should
  not be forced to rely on Escape.
- Fetch success messaging must be explicit:
  - If the provider is active, say the models are available in `/model`.
  - If inactive, tell the user to run `/provider activate <name>`.

## Completion And Entry-Point Parity

The repository has two runnable entry points. Keep them behaviorally aligned.

- `main.py` is used by source checkout workflows and legacy tests.
- `pawnlogic/cli.py` is used by the installed `pawn` command.
- Any CLI help, parser option, completer, provider command guidance, or startup
  behavior changed in one entry point must be changed in the other.
- Dynamic `/model <alias>` completions must be read live from `_visible_models`.
- Do not cache fetched provider models into a static completer `meta_dict`.
- Add or update tests for both `main.PawnCompleter` and
  `pawnlogic.cli.PawnCompleter` when changing completion behavior.
- `pawn --help` and `python main.py --help` must both work and show current
  model examples such as `ds-v4-flash`.

## Documentation Synchronization Policy

Documentation drift is considered a bug.

- `README.md` and `README_CN.md` must stay structurally and semantically
  equivalent.
- `GUIDE_EN.md` and `GUIDE_CN.md` must stay structurally and semantically
  equivalent.
- English and Chinese docs may use different natural language, but they must
  keep the same sections, command lists, examples, FAQ topics, provider rules,
  and behavior descriptions.
- Command syntax placeholders must stay identical across languages. Prefer
  English placeholders such as `<name>`, `<url>`, `<KEY>`, `[alias]`, and
  `[desc]`.
- When provider/model behavior changes, update all of these together:
  - `README.md`
  - `README_CN.md`
  - `GUIDE_EN.md`
  - `GUIDE_CN.md`
  - `CONTRIBUTING.md` if contributor workflow is affected
  - `main.py` help text
  - `pawnlogic/cli.py` help text
  - `core/commands/provider.py` user-facing messages
- Do not leave obsolete examples such as `ds-chat`, `ds-r1`, `gpt-3.5-turbo`,
  or `myrelay/gpt-4o` unless the text is specifically testing legacy filtering.
- If a scan finds old provider/model wording, either update it or document why
  it is intentionally present in a test.

Useful drift scans:

```bash
rg -n "appear automatically|only shows configured|ds-chat|ds-r1|gpt-3\.5-turbo|myrelay/gpt-4o" \
  README.md README_CN.md GUIDE_EN.md GUIDE_CN.md CONTRIBUTING.md main.py pawnlogic/cli.py core tests

rg -n "<name>|/provider activate|/provider deactivate|active provider" \
  README.md README_CN.md GUIDE_EN.md GUIDE_CN.md main.py pawnlogic/cli.py core/commands/provider.py
```

## Configuration And Database Cleanliness

The repository must remain clean of local runtime state.

- Runtime provider config belongs in `~/.pawnlogic/custom_providers.json`.
- Runtime secrets belong in `~/.pawnlogic/.env`.
- Runtime sessions belong in `~/.pawnlogic/pawn.db`.
- Tests must isolate runtime data with `PAWNLOGIC_HOME="$(mktemp -d)"`.
- Ignored local cache files such as `.aider.tags.cache.v4/cache.db` may exist
  locally, but they must not be staged or committed.
- Smoke-test symlinks such as `.env.smoke` and `custom_providers.smoke.json`
  must remain ignored and must not be dereferenced into committed secrets.

Cleanliness checks:

```bash
git ls-files | rg '(^|/)(custom_providers\.json|\.env|.*\.(db|sqlite|sqlite3))$' || true
find . -maxdepth 2 -type f \( -name 'custom_providers.json' -o -name '.env' -o -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' \) -print | sort
git status --short --untracked-files=all
```

## Required Verification

Use the narrowest fast test first, then full verification before commit.

Provider/model changes:

```bash
PAWNLOGIC_HOME="$(mktemp -d)" PAWNLOGIC_TEST_MODE=true \
  venv/bin/python -m pytest tests/test_provider_commands.py -q --timeout=60
```

Full test suite:

```bash
PAWNLOGIC_HOME="$(mktemp -d)" PAWNLOGIC_TEST_MODE=true \
  venv/bin/python -m pytest tests/ -q --timeout=60
```

Lint:

```bash
venv/bin/python -m ruff check .
```

CLI smoke checks:

```bash
PAWNLOGIC_HOME="$(mktemp -d)" PAWNLOGIC_TEST_MODE=true pawn --help
PAWNLOGIC_HOME="$(mktemp -d)" PAWNLOGIC_TEST_MODE=true venv/bin/python main.py --help
```

Diff integrity:

```bash
git diff --check
```

Run all relevant checks again after staging if the commit touches Python code,
provider behavior, CLI help, or tests.

## Commit And Push Workflow

- Keep commits focused and reviewable.
- Do not include unrelated generated files, caches, build output, local runtime
  config, or database files.
- Use staged leak scans before committing.
- Confirm `git status --short --branch --untracked-files=all` after commit.
- If the task requires remote delivery, push `main` and confirm the new remote
  HEAD in the final report.

## Architecture Notes

- `config/` should remain declarative: paths, providers, model registry, tiers,
  phases, and security policy.
- `core/commands/provider.py` owns provider commands, `/model`, provider
  visibility, and provider-facing command messages.
- `core/provider_tui.py` owns the provider TUI. Paste/focus behavior belongs
  there, not in ad hoc input handling.
- `config.providers.load_custom_providers()` has import-time side effects and
  merges custom providers into `PROVIDERS`.
- The first-run gate must rely on `_has_any_api_key()` and must not require
  `~/.pawnlogic/.env` to exist when keys are injected through the process
  environment.
- `tests/test_provider_commands.py` is the main regression suite for provider
  visibility, active state, fetch filtering, TUI input behavior, and completer
  behavior.
- `tests/test_deployment_friendly.py` protects startup, first-run, packaging,
  and deployment behavior.

## Version Bump Fixed Locations

All agents must treat version updates as a fixed-location operation. Do not add
or edit scattered version literals.

Allowed version-bump edits:

1. `config/paths.py`
   - Change only `VERSION`.
   - This is the only runtime source of truth.
2. `README.md` and `README_CN.md`
   - Update only the version badge when the badge contains a literal version.
   - Keep both language files aligned.
3. `SECURITY.md`
   - Update only the Supported Versions table.
4. `CHANGELOG.md`
   - Add exactly one new release section for the new version.
   - Keep existing historical sections unchanged unless correcting a proven
     factual error.

Forbidden version-bump edits:

- Do not hardcode a version in `pyproject.toml`; it must continue to read
  `config.paths.VERSION` dynamically.
- Do not update version strings in comments, docstrings, help text, command
  output, tests, package metadata, or generated files unless a failing test
  proves that location is an intentional release artifact.
- Do not edit build output in `dist/`, `build/`, or `*.egg-info/`.
- Do not create a second version source of truth.

Version-bump validation:

```bash
rg -n "0\.[0-9]+\.[0-9]+|[1-9][0-9]*\.[0-9]+\.[0-9]+" \
  --glob '!dist/**' --glob '!build/**' --glob '!*.egg-info/**'
git diff --stat
```

The diff should be limited to the fixed locations above unless the task
explicitly includes additional release work.

Build verification:

```bash
rm -rf dist/ build/
venv/bin/python -m build
venv/bin/python -m twine check dist/*
venv/bin/python -m zipfile -l dist/*.whl | grep -ic skills/ctf
```

The wheel should not include optional `skills/ctf_*` packs by default.
