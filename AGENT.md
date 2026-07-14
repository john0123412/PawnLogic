# PawnLogic - Agent Instructions

This file is the repository-level operating guide and single source of truth
for coding agents working on PawnLogic. `CLAUDE.md` is intentionally a thin
wrapper that imports this file; do not duplicate the shared instructions there.

## Project Summary

- Product: a terminal AI agent with multi-provider model routing, persistent
  SQLite memory, real tool execution, MCP integrations, and CTF-oriented tools.
- Installed CLI entry point: `pawn` -> `pawnlogic.cli:run`.
- Source checkout compatibility entry point: `python main.py` -> `pawnlogic.cli`.
- Module entry point: `python -m pawnlogic` -> `pawnlogic.cli:run`.
- Shell launcher: `pawn.sh` -> `python -m pawnlogic`.
- Curl installer: `install.sh` creates an isolated venv, installs the package
  with pip, and writes a `pawn` launcher.
- Runtime data: `~/.pawnlogic/` by default. Tests must use a temporary
  `PAWNLOGIC_HOME`.
- Version source of truth: `config/paths.py:VERSION`.
- Build backend: setuptools with dynamic version in `pyproject.toml`.
- Project memory: `PROJECT_MEMORY.md` is the compact architecture, ownership,
  active-plan, and risk map for agents. Read it after this file before broad
  planning, code changes, release work, or multi-file audits.

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
git diff --cached | grep -nE "sk-ant-[A-Za-z0-9_-]{20,}|sk-(proj-|svcacct-|live-)?[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{50,}|tp-[a-z0-9]{30,}|AIza[A-Za-z0-9_-]{35}|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|(OPENAI|ANTHROPIC|DEEPSEEK|AZURE|GOOGLE|GEMINI|MISTRAL|OPENROUTER|TOGETHER|DASHSCOPE|MOONSHOT|ZHIPU|XAI)[A-Z0-9_]*(API_)?KEY[[:space:]]*[:=][[:space:]]*['\"]?[A-Za-z0-9_./+=-]{20,}" || true
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

## Completion And Runtime Entry Points

The repository has one CLI runtime implementation.

- `pawnlogic/cli.py` owns CLI help, parser options, completer behavior,
  provider command guidance, startup behavior, `PawnCompleter`, and `run()`.
- `main.py`, `pawnlogic/__main__.py`, and `pawn.sh` are thin adapters. Do not
  duplicate CLI runtime logic into them.
- `main.py` must keep legacy `import main` compatibility by exposing the same
  implementation as `pawnlogic.cli`.
- Dynamic `/model <alias>` completions must be read live from `_visible_models`.
- Do not cache fetched provider models into a static completer `meta_dict`.
- Add or update tests for both `main.PawnCompleter` and
  `pawnlogic.cli.PawnCompleter` when changing completion behavior.
- `python main.py --help`, `python -m pawnlogic --help`, `pawn --help`, and
  `./pawn.sh --help` must work and show the same CLI parser output.
- Fresh-venv `pip install .` must expose a working `pawn` command.
- Source code, comments, runtime prompts, log messages, generated templates,
  tests, and agent-facing instructions must be written in English.
- English is the repository default. Do not add `_EN` suffixes for default
  English files; use names such as `README.md` and `GUIDE.md`.
- Chinese is allowed only in repository files whose filename stem ends with
  `_zh-CN` (for example `README_zh-CN.md` and `GUIDE_zh-CN.md`), where it must match
  the English documentation semantically.
- Do not introduce Chinese text anywhere else in the repository, including
  Python source, shell scripts, tests, fixtures, config files, commit-facing
  templates, or agent instructions.
- Default `pawn` startup is user-friendly mode. It must hide raw tool-call
  internals, parser diagnostics, detailed reasoning streams, and low-level API
  errors unless the user explicitly enables debug output.
- Default user-friendly mode must not print internal loguru WARNING diagnostics
  to the terminal. Non-fatal internal diagnostics belong in debug/file logs; use
  concise user-facing print messages for issues the user must act on.
- `pawn --debug` is the only startup flag for detailed terminal diagnostics.
  Do not reintroduce `--quiet`; use debug mode and runtime state flags instead.
- `/mode` remains the interactive switch between user-friendly output and debug
  output.

## Documentation Synchronization Policy

Documentation drift is considered a bug.

- Every completed repository change must include a README review before the
  final report. If the change affects user-facing behavior, installation,
  commands, providers/models, MCP/tool behavior, trust boundaries, security
  posture, docs navigation, packaging, CI, or release flow, update both
  `README.md` and `README_zh-CN.md` in the same change.
- If a change does not require a README edit, say so explicitly in the final
  report as `README reviewed: no change needed`, with the reason.
- Every completed repository change must also include a `PROJECT_MEMORY.md`
  review before the final report. Update it in the same commit when the change
  affects architecture boundaries, module ownership, public contracts, active
  release plans, typed-island scope, release state, or known recurring risks.
  If no update is needed, say so explicitly in the final report as
  `PROJECT_MEMORY reviewed: no change needed`, with the reason.
- README updates must be completed before release PR merge, release tag
  creation, package build, or PyPI upload. Do not treat a post-release README
  cleanup as fixing the already published PyPI project page.
- `README.md` and `README_zh-CN.md` must stay structurally and semantically
  equivalent.
- `GUIDE.md` and `GUIDE_zh-CN.md` must stay structurally and semantically
  equivalent.
- `tools/check_doc_structure.py` and the Docs workflow must enforce matching
  heading level/order for the English and Chinese documentation pairs.
- English and Chinese docs may use different natural language, but they must
  keep the same sections, command lists, examples, FAQ topics, provider rules,
  and behavior descriptions.
- Command syntax placeholders must stay identical across languages. Prefer
  English placeholders such as `<name>`, `<url>`, `<KEY>`, `[alias]`, and
  `[desc]`.
- When provider/model behavior changes, update all of these together:
  - `README.md`
  - `README_zh-CN.md`
  - `GUIDE.md`
  - `GUIDE_zh-CN.md`
  - `CONTRIBUTING.md` if contributor workflow is affected
  - `pawnlogic/cli.py` help text
  - `core/commands/provider.py` user-facing messages
- Do not leave obsolete examples such as `ds-chat`, `ds-r1`, `gpt-3.5-turbo`,
  or `myrelay/gpt-4o` unless the text is specifically testing legacy filtering.
- If a scan finds old provider/model wording, either update it or document why
  it is intentionally present in a test.

Useful drift scans:

```bash
rg -n "appear automatically|only shows configured|ds-chat|ds-r1|gpt-3\.5-turbo|myrelay/gpt-4o" \
  README.md README_zh-CN.md GUIDE.md GUIDE_zh-CN.md CONTRIBUTING.md pawnlogic/cli.py core tests

rg -n "<name>|/provider activate|/provider deactivate|active provider" \
  README.md README_zh-CN.md GUIDE.md GUIDE_zh-CN.md pawnlogic/cli.py core/commands/provider.py
```

## Third-Party Skill Pack Policy

Third-party skill packs are optional extension assets, not mandatory runtime
package contents.

- `pawnlogic[ctf]` installs CTF tooling dependencies only. Do not describe it
  as installing third-party skill Markdown, support files, or an original
  PawnLogic CTF knowledge base.
- PyPI extras cannot conditionally add or remove files from the same built
  wheel. If a file is in the wheel, every installation receives it regardless
  of which extra the user selected.
- Keep third-party CTF skill packs external by default. Users may install them
  explicitly into `~/.pawnlogic/skills` with `/sp install <repo_url>` or copy a
  local skill-pack directory.
- Do not redistribute third-party skill content in PyPI artifacts, generated
  release source archives, Docker images, or generated bundled-skill
  directories until `THIRD_PARTY_NOTICES.md` records the upstream URL, commit
  or release, license, copyright notice, copied/adapted files, and
  redistribution decision.
- Use `.gitattributes export-ignore` for tracked source-checkout skill assets
  that must stay out of generated release archives while license review is
  incomplete.
- If upstream license status is unclear, treat the content as install-guidance
  only. Do not package it.
- Public docs may say PawnLogic integrates with or adapts curated upstream CTF
  resources after attribution is recorded. Do not claim third-party CTF skill
  content is fully self-developed or original to PawnLogic.
- When changing skill-pack packaging or installation behavior, update
  `README.md`, `README_zh-CN.md`, `GUIDE.md`, `GUIDE_zh-CN.md`,
  `THIRD_PARTY_NOTICES.md`, `CHANGELOG.md`, and the packaging tests together.

## Configuration And Database Cleanliness

The repository must remain clean of local runtime state.

- Runtime provider config belongs in `~/.pawnlogic/custom_providers.json`.
- Runtime secrets belong in `~/.pawnlogic/.env`.
- Runtime sessions belong in `~/.pawnlogic/pawn.db`.
- Tests must isolate runtime data with a temporary `PAWNLOGIC_HOME`.
- Prefer pytest `tmp_path` fixtures for tests. In shell commands, create the
  directory with `mktemp -d` and install a cleanup trap before running pytest.
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
Commands below assume the intended virtual environment or CI Python is already
active. Use `python -m ...`; do not hardcode `venv/bin/python`.

Developer code index:

- `tools/code_index.py` is a source-checkout development aid for agents and
  maintainers. It is not a runtime feature of the installed `pawn` command.
- Before code audit, impact analysis, or multi-file edits, build or refresh the
  local index:

```bash
python tools/code_index.py build
```

- Use the index before broad text searches when locating known functions,
  classes, methods, or call sites:

```bash
python tools/code_index.py symbol <name>
python tools/code_index.py refs <name>
```

- After editing an indexed Python file, update that file's index entry:

```bash
python tools/code_index.py update <path/to/file.py>
```

- Generated index files live under `.pawnlogic_index/`, are ignored by git, and
  must never be staged or committed.

Provider/model changes:

```bash
tmp_home="$(mktemp -d)"
trap 'rm -rf "$tmp_home"' EXIT
PAWNLOGIC_HOME="$tmp_home" PAWNLOGIC_TEST_MODE=true \
  python -m pytest tests/test_provider_commands.py -q --timeout=60
```

Full test suite:

```bash
tmp_home="$(mktemp -d)"
trap 'rm -rf "$tmp_home"' EXIT
PAWNLOGIC_HOME="$tmp_home" PAWNLOGIC_TEST_MODE=true \
  python -m pytest tests/ -q --timeout=60
```

Fast CI equivalent for normal PRs:

```bash
tmp_home="$(mktemp -d)"
trap 'rm -rf "$tmp_home"' EXIT
PAWNLOGIC_HOME="$tmp_home" PAWNLOGIC_TEST_MODE=true MCP_ENABLED=false \
  python -m pytest tests/ -v --tb=short --timeout=60 \
  --ignore=tests/test_e2e.py -m "not slow and not e2e and not packaging"
```

Release validation split:

```bash
tmp_home="$(mktemp -d)"
trap 'rm -rf "$tmp_home"' EXIT
PAWNLOGIC_HOME="$tmp_home" PAWNLOGIC_TEST_MODE=true MCP_ENABLED=false \
  python -m pytest tests/ -v --tb=short --timeout=60 --ignore=tests/test_e2e.py
PAWNLOGIC_HOME="$tmp_home" PAWNLOGIC_TEST_MODE=true MCP_ENABLED=false \
  python -m pytest tests/test_e2e.py -v --tb=short --timeout=30
```

Lint:

```bash
python -m ruff check .
```

CLI smoke checks:

```bash
tmp_home="$(mktemp -d)"
trap 'rm -rf "$tmp_home"' EXIT
PAWNLOGIC_HOME="$tmp_home" PAWNLOGIC_TEST_MODE=true MCP_ENABLED=false \
  PROMPT_TOOLKIT_ENABLED=0 python main.py --help
PAWNLOGIC_HOME="$tmp_home" PAWNLOGIC_TEST_MODE=true MCP_ENABLED=false \
  PROMPT_TOOLKIT_ENABLED=0 python -m pawnlogic --help
PAWNLOGIC_HOME="$tmp_home" PAWNLOGIC_TEST_MODE=true MCP_ENABLED=false \
  PROMPT_TOOLKIT_ENABLED=0 ./pawn.sh --help
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
- If the user asks to preserve completed edits or says changes may be deleted,
  first create a local commit for only the relevant files before cleanup,
  branch changes, or other risky follow-up work:

```bash
git add <files>
git commit -m "<type>: <summary>"
```

- Use staged leak scans before committing.
- Confirm `git status --short --branch --untracked-files=all` after commit.
- Do not push local commits to any remote branch until the user has manually
  verified the local build/run result and explicitly instructed the push.
  Passing local tests is necessary but not sufficient for remote delivery.
- For fixes, release preparation, and any change that affects packaging or CI,
  create and push a remote test branch first. Do not push directly to `main`
  until the remote branch Actions are green or the user explicitly instructs a
  main-branch hotfix.
- Normal PR CI should stay fast: ruff first, then Python 3.11 tests excluding
  only tests marked `slow`, `e2e`, or `packaging`. Release/manual CI must keep
  the Python 3.10/3.11/3.12 matrix and dynamic E2E coverage.
- If the task requires remote delivery after branch validation, push the target
  branch and confirm the new remote HEAD in the final report.

## Bounded Codex Goal Runner

`tools/codex_goal_run.sh` is the maintainer-only entry point for unattended
`codex exec` work. It requires a clean feature branch, stores artifacts only
under ignored `.codex_goals/` or `.agent-work/`, and enforces one-run locking
and a wall-clock timeout. Paid API smoke, dependency installation, and remote
Git operations require separate explicit flags. See
`docs/codex-wsl2-automation.md` for recovery and cleanup.

## Release And PyPI Publishing Rules

- Version release work must start on a new remote test branch such as
  `test/release-<version>` or `fix/<issue>-<version>`.
- Before tagging or publishing a version, verify that `README.md`,
  `README_zh-CN.md`, `GUIDE.md`, `GUIDE_zh-CN.md`, `CHANGELOG.md`, `SECURITY.md`,
  and package metadata all describe the release consistently.
- PyPI renders the long description embedded in the built distribution at
  upload time. PyPI does not update an existing version's project description
  when `README.md` changes later on GitHub. If README or guide links are fixed
  after a version has already been uploaded, record that the PyPI page will only
  be corrected by the next release.
- The remote test branch Actions must pass before publishing a new PyPI
  version.
- Publish to PyPI only after the package has passed local verification and
  remote Actions on the test branch.
- Production PyPI publishing must use Trusted Publishing / OIDC from the
  GitHub Actions release workflow. Do not reintroduce long-lived production
  PyPI API tokens unless the user explicitly approves a temporary incident
  workaround.
- Publishing jobs must use GitHub environments (`pypi` and `testpypi`) that
  match the Trusted Publisher configuration on PyPI/TestPyPI. Keep
  `id-token: write` scoped to the smallest publish jobs; build, test, and
  release-note jobs must not request it.
- Create or update the GitHub Release only after the PyPI upload succeeds.
  Release notes must not be treated as complete before the package exists on
  PyPI.
- The GitHub Release body must be sourced from the matching `CHANGELOG.md`
  release section, for example `## [0.0.9] - YYYY-MM-DD`. Do not publish a
  release whose visible release page contains only the tag/version name.
  Automated release workflows must fail if the matching changelog section is
  missing or empty.
- Do not create a release tag or trigger production publishing from an untested
  `main` commit.
- After a release completes, clean local build artifacts and release scratch
  files before reporting completion: remove `dist/`, `build/`, and
  `*.egg-info/` unless the user explicitly asks to keep them.
- When a remote test branch created for release validation has passed and the
  release changes have been merged or pushed to the target branch, delete the
  remote test branch during cleanup, for example
  `git push origin --delete test/release-<version>`, unless the branch is being
  kept intentionally for incident investigation.
- After every release workflow change or published release, re-check that
  `CLAUDE.md` remains a thin wrapper that imports `AGENT.md`.
- After every published release, verify and report:
  - GitHub raw `README.md` from `main`.
  - The PyPI latest version and PyPI long description metadata.
  - The package docs URL in PyPI metadata.
  - The public version badge rendered by the README.
  - The GitHub Release URL and visible release notes.
- Record the PyPI publish result and release URL in the final report for any
  release task.

## Release Failure Handling

- If PyPI upload fails before any artifact is accepted, fix the issue and retry
  the same version only after confirming PyPI does not already contain it.
- PyPI does not allow replacing files for an existing version. If any artifact
  was accepted and the release has a serious defect, publish a new patch version
  instead of trying to overwrite the same version.
- Yank a broken PyPI release when users should avoid installing it but the
  release should remain visible for dependency resolution and audit history.
- If the GitHub Release is created but PyPI upload failed, mark the GitHub
  Release as draft or delete it, then recreate/update it only after PyPI
  publishing succeeds.
- Record the failed version, PyPI project state, and chosen recovery action in
  `CHANGELOG.md` or the release task notes when the failure affects users.

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
2. `README.md` and `README_zh-CN.md`
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
rg -n '^VERSION = "[0-9]+\.[0-9]+\.[0-9]+"' config/paths.py
rg -n 'pypi/v/pawnlogic|^## \[[0-9]+\.[0-9]+\.[0-9]+\]|^[|] [0-9]+\.[0-9]+\.[0-9]+' \
  README.md README_zh-CN.md CHANGELOG.md SECURITY.md
git diff --stat -- config/paths.py README.md README_zh-CN.md CHANGELOG.md SECURITY.md
git diff --name-only | rg -v '^(config/paths\.py|README(_zh-CN)?\.md|CHANGELOG\.md|SECURITY\.md)$' || true
```

The diff should be limited to the fixed locations above unless the task
explicitly includes additional release work.

Build verification:

```bash
rm -rf dist/ build/
python -m build
python -m twine check dist/*
python - <<'PY'
from pathlib import Path
from zipfile import ZipFile
wheel = next(Path("dist").glob("*.whl"))
with ZipFile(wheel) as zf:
    count = sum(name.startswith("skills/") for name in zf.namelist())
print(count)
raise SystemExit(0 if count == 0 else 1)
PY
```

The wheel should not include any `skills/` packs by default. Local skill packs
are source-checkout or user-installed assets; pip/curl installations should use
`~/.pawnlogic/skills` only when the user installs packs explicitly.
