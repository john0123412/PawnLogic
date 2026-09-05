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
- Project memory: The release state, typed-island scope, known risks, and
  agent workflow are in the sections at the end of this file.

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
- Top-level command completion candidates must come from `core.commands.COMMANDS`;
  do not maintain a second manual command list. Every newly registered command
  must be reachable through Prompt Toolkit and readline fuzzy completion as
  well as direct command dispatch.
- Fuzzy direct dispatch must execute only a unique registered-command match.
  Ambiguous input must list its candidates and execute no command.
- Add or update tests for both `main.PawnCompleter` and
  `pawnlogic.cli.PawnCompleter` when changing completion behavior.
- `python main.py --help`, `python -m pawnlogic --help`, `pawn --help`, and
  `./pawn.sh --help` must work and show the same CLI parser output.
- Fresh-venv `pip install .` must expose a working `pawn` command.
- Source code, comments, runtime prompts, log messages, generated templates,
  tests, and agent-facing instructions must be written in English.
- English is the repository default. Do not add `_EN` suffixes for default
  English files; use names such as `README.md`.
- Chinese is allowed only in repository files whose filename stem ends with
  `_zh-CN` (for example `README_zh-CN.md`), where it must match
  the English documentation semantically.
- Checked-in `skills/` assets are optional source-checkout material governed by
  the Third-Party Skill Pack Policy. They may retain their upstream language,
  but must remain export-ignored and must not be used to add first-party Chinese
  source, tests, or product documentation.
- Outside translated `_zh-CN` documentation and the approved `skills/`
  exception, do not introduce Chinese text in Python source, shell scripts,
  tests, fixtures, config files, commit-facing templates, or agent
  instructions.
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
- Every completed repository change must also review the "Current Release State",
  "Typed Island", and "Known Risks" sections of this file. Update them in the
  same commit when the change affects architecture, contracts, release state,
  typed-island scope, or known risks. If no update is needed, say so explicitly
  in the final report as `AGENT.md sections reviewed: no change needed`.
- README updates must be completed before release PR merge, release tag
  creation, package build, or PyPI upload. Do not treat a post-release README
  cleanup as fixing the already published PyPI project page.
- `README.md` and `README_zh-CN.md` must stay structurally and semantically
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
  (GUIDE merged into README)
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
  README.md README_zh-CN.md CONTRIBUTING.md pawnlogic/cli.py core tests

rg -n "<name>|/provider activate|/provider deactivate|active provider" \
  README.md README_zh-CN.md pawnlogic/cli.py core/commands/provider.py
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
  explicitly into `~/.pawnlogic/skills` with `/skills install <repo_url>` or copy a
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
  `README.md`, `README_zh-CN.md`,
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

## Merging A Stacked PR Chain

GitHub does not reliably retarget a child pull request when its base branch is
deleted. Merging a parent with `--delete-branch` first can close the child as
`DIRTY` instead, and a closed pull request cannot be reopened while its base is
missing and cannot have its base changed while it is closed. Recovering means
pushing the deleted base back from a saved ref.

Merge a stack in this order, one link at a time:

1. Record a rollback ref for `main` and for every branch in the stack before
   touching anything:

   ```bash
   git update-ref refs/backup/pre-merge-<name> "$(git rev-parse origin/<branch>)"
   ```

2. Retarget the child pull request onto `main` first:

   ```bash
   gh pr edit <child> --base main
   ```

3. Only then merge the parent and delete its branch:

   ```bash
   gh pr merge <parent> --merge --delete-branch
   ```

4. Confirm the child is still `OPEN` with `base=main` before moving to the next
   link.

Retargeting before merging means no pull request depends on a branch at the
moment it is deleted. If a child is closed anyway, push its base branch back
from `refs/backup/pre-merge-<name>`, reopen the pull request, retarget it, and
delete the temporary branch again.

Merging a stack does not validate the merged result. Run the full local suite
and the guards against the merged branch itself, because each branch passing
individually is not evidence for their combination.

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
  `README_zh-CN.md`, `CHANGELOG.md`, `SECURITY.md`,
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

## Version Numbering Policy

This policy is set by the repository owner and binds every agent and release.

- Never increment the minor (second) version digit without an explicit user
  instruction given for that specific bump. Only the patch (third) digit may
  be incremented autonomously.
- Releases publish strictly in sequence. Never tag, publish, merge, or declare
  a version that skips or precedes an earlier declared-but-unpublished
  version; a cycle's version PR must not merge until the previous version's
  tag and publish have completed.
- A minor-version bump requires the user's written decision recorded in the
  active plan before any version file changes.

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

## Current Release State

- Current published release: `0.3.6`. PyPI, GitHub Release, and latest tag
  are `v0.3.6`, published 2026-09-02 through Trusted Publishing after the
  full test gate, Dynamic E2E, distribution build, and PyPI fresh-install
  smoke. The `0.3.5` release remains complete.
- Release finalization: `v0.3.6` was published on 2026-09-02 through Trusted
  Publishing. The release workflow completed its full test gate, Dynamic E2E,
  distribution build, PyPI fresh-install smoke, and GitHub Release creation.
  PR #122 carried the README version-pointer alignment required by
  `tools/check_release_consistency.py`; the v0.3.6 tag was force-updated
  to point at that commit because the tag ruleset blocks deletion.
- Runtime version source of truth: `config/paths.py:VERSION`.
- Active plan: `0.3.7-inline-terminal-stability.md` is the active plan
  currently being repaired locally on `test/release-0.3.7`. It restores native terminal
  scrollback / mouse selection / copy by removing the alternate-screen
  application mode and unifies interactive selectors under a single
  Prompt Toolkit Application dialog state. The 0.3.6 plan is
  **complete** and moved to Completed Plans in `docs/plans/INDEX.md`;
  the architecture is captured by
  [ADR 0010](docs/adr/0010-inline-terminal-modal.md) in **Proposed**
  state (local implementation repaired; acceptance gates pending).
  The earlier rebuild history remains available for diff and
  forensics. Independent
  `pawnlogic-security` 0.1.0 published from
  `john0123412/pawnlogic-security` on 2026-07-28.
- 0.3.7 release prep is paused for local repair on
  `test/release-0.3.7`; no repair commit, push, merge, tag, or publish
  may happen before the owner PTY gate. Phase A (the persistent
  terminal itself) and Phase B (the four interactive selectors —
  `/model`, `/planguard`, `/provider`, `/skills`) now have local
  implementation and regression evidence.
  `/model` and `/planguard` use the state-machine selector path that
  installs the selector in the live `Application`'s
  `SelectorRegistry`; `/provider` and `/skills` expose rich
  `ModalSpec` containers and dynamic key bindings that are mounted in
  that same Application. Their standalone Applications are used only
  by the serial/readline fallback. `controller.run_selector` rejects
  awaitable live factories so a nested `Application.run_async()`
  cannot silently return. Completed transcript lines reach the host
  stdout through Prompt Toolkit's `run_in_terminal` handoff while the
  Application remains alive; partial lines flush once at close, worker
  bursts are serialized, and transient host-write failures retry
  without advancing the flush cursor. The bare-Escape binding now routes the
  queue-first-item conversion through
  `ControlAction(kind=CLAIM_STEER)` plus `session.queue_control` so
  the scheduler correctly marks the queued entry as a steer instead
  of creating a fresh turn. The persistent composer's `TextArea`
  height is now `Dimension(min=1, max=5)` so long wrapped input
  grows up to five rows instead of being clipped to a single fixed
  row. A follow-up audit cycle (350abfa) reverted the
  ``@bindings.add('enter', eager=True)`` flag and removed the
  ``@bindings.add('c-j')`` binding from ``pawnlogic/live_repl.py``:
  both were added by the b88cea3 multiline-composer commit but
  empirically they break the live composer's normal text-insert
  path.  The PTY e2e suite sends text + LF (``\n``) via
  ``pexpect.sendline`` and ``\n`` maps to ``Keys.ControlJ`` in
  Prompt Toolkit; the custom c-j binding ate that press as a
  literal-newline insertion and the model never got called, while
  the ``eager=True`` flag on the enter binding dropped the first
  typed character on its own.  Leaving ``c-j`` to PT's default
  ``_newline2`` handler (which re-feeds ``\n`` as ``ControlM``)
  and relying on the ``_CombinedRegistry`` to resolve ``enter`` to
  the LAST matching handler in the merged list restores the e2e
  flow.  The multiline composer's ``Dimension(min=1, max=5)`` and
  ``wrap_lines=True`` stay in place; only the literal-newline
  insertion path is removed (no ``c-j`` binding) until a
  /draft-style command is added to drive ``buffer.insert_text``
  explicitly.  A follow-up cycle (6317195) added a persistent
  1-line status indicator above the composer so the user always
  sees what the worker thread is doing: `[model]  Idle`,
  `[model]  ⏱ Ns · Esc to interrupt` while a Turn is in flight,
  `[model]  ⏸ interrupted by user` for 1.5 s after a user-initiated
  Esc / Ctrl+C interrupt, and `[model]  Idle — edit the draft and
  press Enter` for 1.5 s after a recovery prefill. A 250 ms
  `loop.call_later` ticker keeps the seconds counter honest while
  the model runs, so the event loop stays free for key dispatch and
  mid-turn typing echoes into the composer instead of being
  swallowed. The same cycle hides the queue counters from the
  user surface: the toolbar's `Queue:` segment is dropped,
  `core/queue_tui.toolbar_queue_status` returns a label-only
  string, and `/queue` is gone from the help block, the cmdhelp
  dictionary, the top-of-file command summary, and the live
  composer's "controls allowed while running" notice. `/queue
  resume` and `/queue clear` survive as internal aliases
  reachable through `ControlAction(kind=RESUME, explicit=True)`
  and the existing command registration, so scripts that type
  them keep working. The `/abort` command is merged: the previous
  `--all` form is removed and plain `/abort` interrupts the active
  Turn and clears the queue in one call. Failure is silent on the
  user UI — a failed Turn parks the queue internally but the
  persistent status line simply returns to `Idle` with no `Failed
  · +N parked` label — so the only outward sign of a failure is
  a 1.5 s `interrupted by user` banner when the user pressed
  Esc. The internal anti-cascade gate
  (`ControlAction(explicit=True)`) is preserved exactly as it
  was. Release-prep edits in this cycle:
  `config/paths.py:VERSION` `0.3.6` → `0.3.7`, the `0.3.7` section
  added to `CHANGELOG.md`, `0.3.7` row added to `SECURITY.md`, and
  [ADR 0010](docs/adr/0010-inline-terminal-modal.md) header updated
  to record that the implementation has landed while keeping the
  acceptance gates (`main` merge, PyPI publish, owner PTY smoke) as
  the conditions for moving the ADR to **Accepted**. The two real-path
  TUI tests for `/provider` and `/skills` are green, and the 12 E2E
  tests that were failing on 3be257b's HEAD because of the c-j binding
  all pass after 350abfa's revert of the eager / c-j additions. Ruff,
  typed-island mypy
  for `pawnlogic/terminal_transcript.py`,
  `pawnlogic/live_terminal.py`, `pawnlogic/selectors.py`, and
  `pawnlogic/restart_recovery.py`, `git diff --check`, leak scans,
  `check_doc_structure.py`, and `check_release_consistency.py` are
  all clean. The current local repair has combined evidence of 1,521
  non-E2E tests and 29/29 Dynamic E2E tests; remote CI and owner PTY
  acceptance have not run against it. The release PR (#124) is open against `main` from
  `rebuild/inline-terminal-0.3.7`; `main` must not be force-pushed
  and `v0.3.7` must not be tagged or pushed to PyPI until the remote
  Actions on the release PR are green and the owner has run the
  manual PTY smoke.
- 0.3.6 release gates all closed: 1,470 non-E2E tests, 26 Dynamic E2E,
  Ruff, typed-island mypy (42 modules), documentation and language guards,
  release consistency, architecture budget, package build, twine metadata,
  isolated fresh-install smoke, Python 3.10/3.11/3.12 matrix, and remote
  Dynamic E2E all green. PR #120 (release prep), PR #121 (post-merge docs),
  and PR #122 (README version-pointer alignment) all merged into `main`.
- `main` protected by branch rule requiring PR, up-to-date branches, and four
  checks: ruff, docs guard, mypy, fast tests. Tag ruleset protects `v*.*.*`.
- Publishing uses Trusted Publishing / OIDC. GitHub Release waits on
  hash-pinned fresh-install smoke via `tools/release_install_smoke.sh`.

## Typed Island

The typed-island mypy check is intentionally selective. Grow through stable
modules and narrow fixes only. Avoid broad `# type: ignore` or global strict
mode.

Current stable modules: `core/turn_api`, `core/turn_guards`, `core/tool_result`,
`core/tool_executor`, `core/runtime_context`, `core/provider_runtime`,
`core/provider_models`,
`core/api_errors`, `core/tool_calls`, `core/tool_registry`, `core/context_window`,
`core/workspace_cleanup`, `core/turn_state`, `core/session_tool_loop`,
`core/session_snapshot`, `core/delegation`, `core/agent_orchestrator`,
`core/message_history`, `core/provider_streams`, `core/runtime_metrics`,
`core/mcp_client_manager`, `core/path_policy`, `core/provider_transport`,
`core/api_retry`, `core/provider_tui_state`, `core/turn_scheduler`,
`core/live_turn_control`, `core/turn_cancellation`, `core/queue_tui`,
`pawnlogic/live_repl`, `pawnlogic/live_terminal`, `pawnlogic/terminal_transcript`, `pawnlogic/restart_recovery`,
`tools/check_doc_structure`,
`tools/check_release_consistency`, `tools/merge_ctf_skills`, `tools/browser_ops`,
`tools/lsp_lite`, `tools/text_patch`, `tools/shell_ops`, `tools/docker_plan`,
`tools/pwn_binary`, `tools/pwn_debugger`.

## Known Risks

- Trust/Operation/Network Policy drift across host, Docker, browser, MCP, CTF
  execution paths. URL adapters must re-evaluate DNS and redirects.
- Provider visibility drift between CLI, TUI, completions, and runtime fetch.
- User-friendly mode accidentally leaking debug internals.
- Stream adapters changing public delta dict keys or ordering.
- Extension discovery importing or enabling third-party code during startup.
- Security Tools bypassing shared Tool Registry, Operation Policy, or
  Network Policy checks.
- Delegated-agent requests bypassing Provider visibility, allowlists, budgets,
  or capability filtering.
- Tool watchdog abandons wedged tool threads instead of blocking the session;
  abandoned threads keep running until process exit and their results are lost.
- Prompt Toolkit live composition, worker-thread execution, persistent-screen
  repainting, modal pause/resume, and TTY-owning interactive Tools can race;
  live-input tests must exercise the fixed-bottom application, stdout/stderr
  restoration, and serial readline fallback.
- Prompt Toolkit key bindings classify intent before main-loop dispatch; the
  session Adapter must reconcile stale START/STEER/FOLLOW_UP hints against the
  latest scheduler view. Text-only completion must drain unclaimed steer input
  and keep queued content visibly previewed above the composer. Cancellation
  settlement must stay off the UI thread and mark the automatically prefilled
  recovered draft as a one-shot replacement rather than a follow-up.
- The 0.3.6 Queue TUI is deliberately main-thread-only and must not claim
  worker stdin. The persistent terminal renders bare `/queue` inline instead
  of pausing for a nested selector; non-TTY and readline paths use text
  controls. Escape shares a prefix with Alt shortcuts, so real-input tests
  must keep its bounded sequence-resolution latency covered. Mouse-wheel and
  coordinate-free ScrollUp/ScrollDown events must remain owned by the output
  viewport so composer history cannot consume them.
- Safe-point steering can alter Tool Call batch protocol; skipped results,
  ordering, and plan-guard accounting must remain complete.
- Tier presets use advisory plan-guard mode (`plan_guard_mode`) so weak models
  can run side-effect tools without plan blocks; `/planguard strict` remains
  explicit opt-in. Operation Policy remains the actual safety gate, not the
  CoT Guard.
- `/abort` clears queued input but cannot cancel a provider request already
  handed to a synchronous stream; Ctrl+C remains the in-flight interruption
  path.
- The 0.3.7 multiline composer cannot accept a literal ``\n`` from the
  composer key path: the ``c-j`` binding was removed because it intercepted
  bare ``\n`` (which the PTY e2e suite relies on for submit) and the
  ``eager=True`` flag on the ``enter`` binding made the first typed key
  disappear.  Authoring a multi-line draft now requires a future
  ``/draft``-style command that drives ``buffer.insert_text`` directly;
  until then, the only way to send a multi-line message is to type it
  pre-formatted in a single ``send`` (no in-composer literal newlines).
- The multiline composer must keep ``dont_extend_height=True`` with
  ``Dimension(min=1, max=5)`` and must NOT use ``weight=0``:
  multiline content raising the preferred height while zero weight
  excludes the child from the growth rotation sends PT 3.0.52's
  ``take_using_weights`` into an infinite layout loop (frozen page,
  dead keys on wrapped input). The narrow live-terminal suite and the
  e2e live-composer flows pin the working combination.
- Rich in-Application TUIs (`/provider`, `/skills`) contribute dynamic
  containers, key bindings, and focus targets to the persistent
  Application. Their live command factories must never return an
  awaitable or start a nested `Application`; tests must execute the real
  command path and preserve the host Application/task identity.
- Live host scrollback must use Prompt Toolkit's `run_in_terminal`
  handoff. Worker threads must never write directly to the TTY; complete
  lines stream live, partial lines flush once at close, and a failed host
  write must not advance the transcript flush cursor.
- A failed or aborted Turn parks the queue: implicit RESUME drains are
  rejected until the user explicitly resumes (``/queue resume`` or
  Enter on the recovered draft, carried by ``ControlAction.explicit``).
  New user input still queues normally; only the automatic drain is
  gated. Tests pin the parked cascade and the explicit pass-through.
  The 0.3.7 live terminal keeps failure silent in the toolbar
  (label-only ``Failed``); the internal anti-cascade gate is
  preserved.
- The queue preview above the composer is a CONDITIONAL surface: it
  renders nothing while the queue is empty (the 0.3.7 clean-composer
  goal) and shows the muted ``↳ queued [kind]`` rows the moment a
  steer or follow-up is queued. Removing it again would make
  Enter-while-running and the Esc→CLAIM_STEER handoff invisible
  (the owner's real-usage regression report after the initial
  hidden-queue re-scope); tests pin the empty/queued/failed
  render states.
- An interrupt with queued work is a STEER, not a recovery: the
  scheduler must not mint a recovered draft while the queue is
  non-empty, and the worker must re-drive the queue after the
  interrupt settles (the ``_recover_active_unlocked`` queue guard
  and the INTERRUPTED ``should_return`` computation in ``_drive``).
  The recovered-draft edit flow applies ONLY to empty-queue
  interrupts. Tests pin both halves; the preview never renders
  recovered rows (status line + prefilled composer carry them).
- ``/q`` is a registered alias of ``/exit`` and must stay in
  ``LIVE_SLASH_COMMANDS`` so the running-Turn whitelist keeps
  accepting it.
- Queued messages are reworkable through gestures, not commands:
  ``ControlKind.POP_ALL`` atomically drains the queued lanes and
  the recovered slot into one editable draft, driven by bare Esc /
  Up / Alt+Up on an empty, idle composer (the claude-code
  gesture). Esc while a Turn runs keeps the interrupt + CLAIM_STEER
  meaning. ``pop_all_session_queue`` is the session seam;
  ``/queue`` stays hidden from the command surface with its
  resume/clear aliases intact.
- The bottom toolbar renders fields within a width budget (see
  ``_TOOLBAR_HARD_MAX`` / ``_TOOLBAR_WIDE_MIN`` in
  ``pawnlogic/live_repl.py``); adding a toolbar field must keep the
  80-column rendering free of mid-field clipping.
- English and zh-CN docs drifting in structure or command examples.
- Release prep editing version literals outside fixed locations.
- Packaging accidentally including `skills/` content.

## Agent Workflow

For broad code changes:

1. Read `AGENT.md` (this file).
2. Read the active plan under `docs/plans/`.
3. Refresh the code index: `python tools/code_index.py build`
4. Use the index: `python tools/code_index.py symbol <name>` / `refs <name>`
5. Run narrow tests first, then wider validation before committing.
6. Update this file if the work changes architecture, contracts, or risks.
