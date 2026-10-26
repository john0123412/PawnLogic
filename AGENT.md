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
- Fetch must hide non-chat models before registration, using only metadata the
  free `/v1/models` listing already returned. **Fetch must never send a chat
  or completion request to decide whether a model exists.** Probing each
  candidate with a real `POST /chat/completions` is a billable inference:
  openrouter returns hundreds of models, so one fetch produced hundreds of
  charged requests and took minutes. Filter on
  `architecture.output_modalities`; a provider that omits the field is kept,
  because absence of evidence is not evidence of absence. The trade-off is
  accepted deliberately — a model your key cannot actually use is no longer
  hidden up front, and surfaces as a normal API error on first use.
- Test Connection must be free. It checks the same `models_url_from_base_url()`
  listing that fetch uses, so it answers "is the base URL reachable and does
  this key work" without inferring. Do not reintroduce a `max_tokens=1` chat
  POST here; it was a real billable request.
- Test Connection still requires a loaded chat model for that provider, so
  `/provider test <model>` can name the alias the user asked about. Do not
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
  internals, parser diagnostics, and low-level API errors unless the user
  explicitly enables debug output.
- Model reasoning text IS shown in user-friendly mode, as a dim
  `🧠 [thinking]` stream in the transcript. This reverses the earlier rule
  that hid reasoning behind debug mode: with it hidden, a slow
  time-to-first-token was indistinguishable from a dead connection, because
  the transcript showed nothing and the toolbar only carried a timer.
  Reasoning is a side channel — it never counts as the answer and never
  satisfies the plan guard. Raw tool-call arguments and parser diagnostics
  remain debug-only. See Known Risks for the provider-format limit.
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

Architecture budget (a separate CI step from `ruff check .`, so a clean
local lint run says nothing about it):

```bash
python tools/check_architecture_budget.py
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
- **A release needs two PRs, not one.** `tools/check_release_consistency.py`
  has two mutually exclusive states — candidate (`VERSION` bumped, no
  `.release-ready`, READMEs declare the version an unreleased candidate) and
  finalization (`.release-ready` = the version, READMEs and this file declare
  it the current public release) — so a single commit cannot satisfy both.
  The finalization commit must reach `main` first, because `publish.yml`'s
  `verify-release-source` requires the tag's target to be an ancestor of
  `origin/main`. Tagging straight from the release branch fails that gate, and
  a direct push to `main` is blocked by branch protection. Sequence: candidate
  PR → merge → finalization PR → merge → tag the `main` merge commit.
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

- Current published release: `0.4.8`. Release tag: `v0.4.8`. Artifacts must
  originate from the reviewed `main` merge commit through the GitHub Actions
  workflow using Trusted Publishing / OIDC. PyPI:
  <https://pypi.org/project/pawnlogic/0.4.8/>. GitHub Release:
  <https://github.com/john0123412/PawnLogic/releases/tag/v0.4.8>.
  After a publish, confirm each of these against PyPI, the Release page, and
  the remote tag rather than against the local one — the PyPI JSON API's
  `info.version` also lags the upload by minutes, so a per-version URL is the
  reliable check.
  Per-release narrative belongs in `CHANGELOG.md`, not here.
- Runtime version source of truth: `config/paths.py:VERSION`.
- **Do not edit this section as a release log.** Per-release narrative
  belongs in `CHANGELOG.md`; design narrative belongs in `docs/plans/` and
  `docs/adr/`. Keep only: the current version, the open owner items, and
  the invariants below. Before rewriting, verify the release state
  against PyPI, the GitHub Release, and the remote tag — never a local
  `git tag` alone.
- 0.3.7's inline-terminal rebuild is complete and shipped: merged by PR
  #124, released in `v0.3.7`, plan moved to Completed Plans in
  `docs/plans/INDEX.md`, architecture captured by
  [ADR 0010](docs/adr/0010-inline-terminal-modal.md) (**Accepted**). Its
  fixes are the live-terminal, selector, queue, and Esc-semantics
  invariants recorded under Known Risks.
- Phase 2 shipped in `0.3.9` (plan: `docs/plans/p2-steer-and-headless-frontends.md`):
  the Esc-steer handoff, the Python reference client, and the ratatui
  crate with a golden-fixture protocol freeze. Release tags now also
  attach `pawnlogic-tui-<version>-x86_64-unknown-linux-gnu.tar.gz` plus
  `ratatui-binary-sha256.txt` to the GitHub Release; the binary never
  enters the PyPI wheel. Independent `pawnlogic-security` 0.1.0 published
  from `john0123412/pawnlogic-security` on 2026-07-28.
- **Open owner item (carried since 0.3.12):** `tools/owner_acceptance_probe.py`
  automates the scriptable terminal-mode checks but deliberately reports
  four owner-terminal checks as `manual` rather than as passed — native
  scrollback, selection/copy, glyph width, and duplicate output on the
  published binary. CI coverage stays Provider-key-free by owner decision;
  the real persistent Application is exercised through isolated synthetic
  input instead. These four remain unverified.
- `main` protected by branch rule requiring PR, up-to-date branches, and four
  checks: ruff, docs guard, mypy, fast tests. Tag ruleset protects `v*.*.*`.
- Publishing uses Trusted Publishing / OIDC. GitHub Release waits on
  hash-pinned fresh-install smoke via `tools/release_install_smoke.sh`.

## Typed Island

The typed-island mypy check is intentionally selective. Grow through stable
modules and narrow fixes only. Avoid broad `# type: ignore` or global strict
mode.

**The `mypy typed island` step in `.github/workflows/main_ci.yml` is the
authoritative list.** A module is in the island only when CI passes its file
to mypy; the matching `[[tool.mypy.overrides]]` entry in `pyproject.toml` is
what actually turns on `disallow_untyped_defs` / `check_untyped_defs` for it.
Both files, plus the list below, must name the same 60 modules;
`tests/test_typed_island_sync.py` fails the build when they diverge.

To add a module: annotate it until it passes
`python -m mypy --disallow-untyped-defs <file>`, add it to **both** the CI step
and the pyproject override, and add it to the list below.

Current stable modules: `core/turn_api`, `core/turn_guards`, `core/tool_result`,
`core/tool_executor`, `core/runtime_context`, `core/provider_runtime`,
`core/provider_models`, `core/api_errors`, `core/tool_calls`,
`core/tool_registry`, `core/token_estimate`, `core/stream_repetition`, `core/context_window`, `core/workspace_cleanup`,
`core/turn_state`, `core/session_tool_loop`, `core/session_snapshot`,
`core/message_history`, `core/plan_recovery`, `core/plan_protocol`,
`core/tool_markup`, `core/synthetic_messages`,
`core/provider_streams`, `core/runtime_metrics`,
`core/mcp_client_manager`, `core/path_policy`, `core/provider_transport`,
`core/api_retry`, `core/provider_formats`, `core/provider_protocol`,
`core/provider_responses`, `core/provider_tui_rows`, `core/provider_tui_state`,
`core/turn_scheduler`,
`core/live_turn_control`, `core/turn_cancellation`, `core/queue_tui`,
`pawnlogic/live_repl`, `pawnlogic/live_terminal`, `pawnlogic/selectors`,
`pawnlogic/confirm_selector`, `pawnlogic/terminal_transcript`,
`pawnlogic/restart_recovery`, `pawnlogic/terminal_frames`, `tools/check_doc_structure`,
`tools/check_release_consistency`, `tools/merge_ctf_skills`, `tools/browser_ops`,
`tools/policy_proxy`, `tools/proxy_protocol`, `tools/text_patch`, `tools/shell_ops`,
`tools/docker_plan`, `tools/container_http_proxy`, `tools/container_http_protocol`,
`tools/container_http_relay`, `tools/docker_http`, `tools/docker_preflight`, `tools/pwn_binary`, `tools/pwn_debugger`.

`core/delegation` and `core/agent_orchestrator` are **not** in the island.
`core/agent_orchestrator` has an unannotated parameter at line 402 and would
fail; do not list a module here before CI checks it.

## Known Risks

Each entry is an invariant plus the specific mistake that reintroduces the
bug. Incident history lives in `CHANGELOG.md` and `docs/plans/`; the test
name at the end is the gate that fails if the invariant is broken.

### Provider, billing, and effort

- **Never validate a model by inferring with it.** "Check the model works" as
  a real `POST /chat/completions` is billable; per candidate it turned one
  `/provider fetch` into hundreds of charged inferences. It bit twice, in
  `provider_discovery` and again in `provider_runtime.test_connection`.
  Discovery and Test Connection now read only the free `/v1/models` listing;
  the only real inference in the product is a Turn. `core/provider_discovery.py`
  is the seam — adding a request there re-opens the hole.
- **The format registry is the only source of truth for "which protocol and
  which credential header", and an unknown value raises rather than falling
  back to OpenAI.** `api_format` was a hard binary fork with an implicit
  `else` meaning openai across 47 sites in 12 files; adding a third format
  meant adding a third `else` to all of them, and a missed branch degraded
  silently instead of failing. `core/provider_formats.py` now holds the
  registry, `core/provider_protocol.py` the per-format payload/parse/header
  seam, and `core/provider_responses.py` the Responses adapter. **A new
  format is a registry entry plus a `Protocol` row — never a new `if
  api_format == ...` anywhere else.** `protocol_for()` raises on an
  unregistered format; keep it that way. A model may override its provider's
  format with its own `api_format` (GPT-6 needs Responses for tool calling
  under the Chat Completions `openai` provider); `config/providers.py`
  `_model_endpoint` is the only place that resolves it and swaps the endpoint
  suffix. A resolver that reads `PROVIDERS[...]["api_format"]` for a model
  silently sends GPT-6 to `/chat/completions`
  (`tests/test_model_api_format_override.py`). The TUI's `/provider add` menus are
  generated from `core/provider_tui_rows.py` for the same reason: a
  hand-written menu is how the third format ended up unselectable outside the
  TUI.
- **Plan-only recovery must change the request, not repeat it.** After a
  plan-only reply the next request carries `tool_choice="required"`, after the
  second `"none"` with a message asking for an answer or one clarifying
  question, after the third the turn stops, and any other reply restores
  `"auto"` (`core/plan_recovery.RECOVERY_STEPS`; `MAX_PLAN_ONLY_RECOVERIES`
  must equal its length). Re-sending the identical request plus a sterner user
  message looks cheaper and is the retry that failed: recovery worked once in
  nine tries in the session that motivated this. `auto` is never passed to
  `stream_request`, so an ordinary request is byte-identical to the one sent
  before recovery existed. `tool_choice` is serialized at the protocol seam
  only: Chat Completions and Responses send the string, Anthropic maps
  `required` to `{"type": "any"}` and `none` to `{"type": "none"}` and omits
  `auto` (`_anthropic_stream_payload`); an `if api_format == ...` in session
  code is the mistake. A provider that refuses a value with HTTP 400/422 gets
  exactly one retry as `auto`, and the value is remembered unsupported for
  that model alias for the session (`ToolChoiceMemory`) -- but only once the
  retry is flowing: a 400 for another reason (an oversized request) fails the
  `auto` retry too, and blaming `tool_choice` would switch the escalation off
  for the session. The fallback sits
  between `stream_request` and `consume_model_stream`: after the error delta
  has reached the consumer the user already saw an API error for a request
  that was silently retried, and once content has streamed a retry would
  repeat output, so it is skipped then. The refused request carries no usage,
  which is why nothing is counted twice; the retry is a new `stream_request`
  call with its own transport retry budget. A provider that *accepts* a value
  and ignores it cannot be detected: a Responses-format custom provider
  answered HTTP 200 and echoed `tool_choice` for `auto`/`required`/`none`,
  yet `required` produced a tool call in 1 of 3 requests (the others were
  reasoning-only, i.e. empty) and `none` made the model print its own
  text-dialect tool call as the answer. So an empty reply to a recovery
  request is retried as `auto` — resending the identical request is the retry
  that fails again — and the 3-strike bound still ends the turn.
  `test_recovery_changes_the_request_instead_of_repeating_it`,
  `test_a_refused_tool_choice_is_retried_once_as_auto_and_never_sent_again`,
  `test_an_empty_reply_to_a_required_request_is_retried_as_auto`, and
  `tests/test_plan_recovery.py` (serialization per format, fallback edges).
- **A reply whose text is a tool call nothing parsed is not a final answer.**
  A model that writes its call as text in a dialect the extractor does not know
  (DeepSeek DSML tokens, Qwen `<function=...>`, a provider's `<x_tool_call>`
  tags, a bare or fenced JSON call) used to end the turn: no parsed tool call
  meant "final answer", so nothing ran and the markup was printed as the
  answer (a `tool_choice="none"` recovery request made the stuck provider print
  `<iquestcoder_tool_call>list_dir<arg_key>...` as its reply). Such a reply now
  takes the plan-only ladder: same `RECOVERY_STEPS` bound and the same counter
  (a plan-only reply followed by a text call is the second strike;
  `unusable_reply_kind` in `core/plan_recovery.py` decides), with a nudge that
  says the call was written as text and must go through the provider's tool
  interface (`TOOL_MARKUP_RECOVERY_STEPS`; both nudges start with `[SYSTEM:`,
  so they are not turns). The reply and the nudge are turn artifacts, so a
  failed turn discards them. Detection (`core/tool_markup.py`) is shape only
  and deliberately conservative, because a false positive costs a round trip on
  an honest answer: fenced code and inline code are blanked first; a tag pair
  named `*tool_call(s)`, a line-start `<function=...>` block, or a JSON call
  counts only when it *ends* the reply (a model stops after a call, an
  explanation of the format keeps talking) and names a tool the request offered
  (a call is useless without its tool, an explanation shows `tool_name`
  placeholders -- the product's own `<tool_call>{"name":"tool_name",...}`
  format quoted at the end of an answer is the case this is for); JSON is
  additionally only the whole reply (plan blocks removed) or a whole fenced
  block at the end; reserved special tokens match anywhere outside code. A
  quoted example that uses a real tool name is indistinguishable from a call
  and does match (a known limit, pinned). No dialect parser was added, so a
  recognised call is never executed from reply text, and a call cut off before
  its closing tag is not recognised. With no tool offered (a vision model)
  nothing is recovered. The recogniser runs on every reply that has no tool
  call, so it stays linear on degenerate output and `json.loads` is guarded
  against `RecursionError` (deep nesting raises that, not `ValueError`); a
  next saved plan covers the following native batch only if the saved reply
  contained one (`</plan>`). A new dialect is a pattern plus a positive and a
  negative test; widening the match to bare words such as `tool_call`, or adding
  a parser, is the mistake.
  `tests/test_tool_markup.py` (a positive per dialect, negatives for prose,
  quoted examples and code, degenerate input),
  `test_a_tool_call_written_as_text_is_recovered_instead_of_shown_as_the_answer`,
  and its negative control
  `test_an_answer_that_only_talks_about_tool_calls_is_still_an_answer` (both
  directions are needed to know the wiring is live).
- **The plan protocol is one setting per custom provider, resolved in one
  place; the prompt, the guard and every injected plan demand follow it.**
  `"plan_protocol": false` on a custom provider entry in
  `custom_providers.json` (`/provider plan <name> on|off`) removes the
  Execution Protocol section from the system prompt; absent or `true` is
  today's prompt byte for byte, because the section is the module constant
  `prompt_builder._EXECUTION_PROTOCOL` and `plan_protocol=False` can only omit
  that text. It exists because a Responses-format custom provider's model
  treats writing the plan as the action: in a paid A/B the same first request
  was plan-only 2 of 2 times as built and 0 of 2 times with only that section
  removed (one reply was a native tool call). The section also carries the
  text-fallback `<tool_call>` format and the long-output rules, and they go
  with it: a provider that depends on the text fallback should keep the
  protocol on. `core/plan_protocol.plan_protocol_enabled` is the only
  model -> provider -> setting resolver, the way `model_effort_map` is the only
  effort resolver: built-in providers, a missing key, and any value that is not
  the literal `false` are on (a hand-edited `"off"` must not switch it off, and
  a stray key on a built-in entry changes nothing); a consumer that reads
  `PROVIDERS[...]["plan_protocol"]` itself will drift. Persistence shares
  `/provider effort`'s boundary (`config.providers._set_custom_provider_flag`):
  it refuses `BUILTIN_PROVIDER_NAMES` and requires an existing entry that
  already carries `base_url` and `api_key_env`, and it never creates an entry,
  because one incomplete entry makes the loader discard the whole file. The
  validator copies unknown keys (`**prov`, unchanged since 0.3.9), so a release
  that predates the key still loads the file and simply keeps the protocol on.
  `test_set_provider_plan_protocol_refuses_builtins_without_the_command_layer`,
  `test_set_provider_plan_protocol_never_mints_a_partial_entry` and
  `test_set_provider_plan_protocol_refuses_a_complete_shadow_entry` pin the
  guards separately, as for effort. The setting is the prompt's third rebuild
  key (`_prompt_plan_protocol`, beside phase and urgent mode): a model switch or
  a toggle on the current provider rebuilds it once, and nothing else does
  (`test_toggling_the_current_provider_rebuilds_the_prompt_once`,
  `test_prepare_turn_keeps_system_prompt_byte_identical_across_turns`).
  Precedence: the provider setting outranks `plan_guard_mode`. With the
  protocol off the guard flags, annotates (`TOOL_PLAN_NOTICE`), signals
  (`PLAN_MISSING`) and counts nothing in any mode, because enforcing an
  instruction the model never received contradicts the prompt; `/planguard`
  says so instead of silently doing nothing. The guard, the loop notices and
  the turn-context block read the setting the *prompt* was built with
  (`prompt_plan_protocol`), not the live one: an urgent-mode model swap in the
  middle of a turn must not start enforcing a protocol the prompt does not carry
  (`test_the_guard_follows_the_prompt_not_a_mid_turn_model_swap`,
  `test_plan_less_tool_batches_are_not_flagged_when_the_protocol_is_off`, with
  `test_plan_less_tool_batches_are_still_flagged_when_the_protocol_is_on` as
  its positive control). Plan-only recovery stays on, because a model may still
  write a plan of its own accord and a bare plan is still not an answer
  (`test_plan_only_recovery_stays_on_when_the_protocol_is_off`). Two other
  texts asked for a `<plan>` and follow the switch -- the GSA conflict warning
  and the anti-loop notices
  (`test_the_gsa_conflict_warning_does_not_ask_for_a_plan_with_the_protocol_off`,
  `test_loop_notices_are_unchanged_with_the_protocol_on_and_plan_free_when_off`)
  -- so a new injected sentence that says "in your `<plan>`" is the mistake. The
  language rule's "your internal `<plan>` tags MAY use English" is deliberately
  left (it requires nothing). `/provider plan` arrives as `arg="plan"`,
  `arg2="<name> [on|off]"` and is dispatched beside `effort`
  (`test_provider_plan_off_reaches_the_handler_with_name_and_state_split`,
  `test_provider_completion_covers_every_dispatched_subcommand`).
- **A `<plan>` in the stream opens a plan block only outside code, at the
  start of a line or directly followed by a plan sub-tag.** `_PlanRenderer`
  prints plan text dim gray and keeps it out of the answer, so treating a
  *quoted* tag as a plan swallowed the rest of an answer that explained the
  plan protocol: a "[plan start]" line mid-answer, then everything dim gray,
  indistinguishable from the thinking stream, because no `</plan>` ever came.
  The rule classifies all 421 stored replies containing the tag (419 real
  plans unchanged; the two quotes, one in a code fence and one in inline code,
  are now answer text). The renderer tracks only the answer's current-line
  head, its backtick parity and the fence state (`_note`), resets them on
  `flush()` and after `</plan>`, and waits (`_opens_plan` returns `None`)
  while the stream has not yet said whether a sub-tag follows; a stream that
  ends undecided returns the tag as text. Reintroducing an unconditional
  `<plan>` match, or tracking the whole line instead of its head (quadratic on
  a long line fed in small chunks), is the mistake. `tests/test_plan_renderer.py`
  feeds every case in 1-, 2-, 3- and 7-character chunks.
- **Auth is an axis orthogonal to the payload format, and `anthropic-version`
  is a protocol constant, not a credential.** The reported 401 was a relay
  serving Anthropic-shaped payloads over `Authorization: Bearer`, which
  rejects `x-api-key` — no configuration could work, because the credential
  header was *derived from* the format. `auth` is now its own setting and
  `protocol_headers()` owns the non-credential headers, keyed to the format.
  Keying `anthropic-version` off the auth scheme instead — the first cut —
  dropped it under `auth: bearer`, trading the reported 401 for a 400 on the
  exact combination the feature exists to support, and wrongly added it to
  `openai` payloads, where some gateways reject unknown headers.
  `test_anthropic_version_rides_along_under_every_auth_scheme` and
  `test_anthropic_version_never_leaks_onto_an_openai_payload` gate both
  halves; mutate them separately, because one subsumes the other in a test
  that only checks the positive.
- **A 401 hint must not tell a user to rotate a key that works.** The old
  wording was unconditional, and it fired on exactly the reported case: a
  valid key rejected because of the header it was sent in. `auth_failure_hint`
  now names the credential header actually sent and points at the `Auth`
  setting, keeping the "your key is invalid" wording only where the protocol
  already sends Bearer by default — there is nothing for the user to change.
  `test_no_hint_ever_suggests_setkey_while_naming_a_credential_header` sweeps
  every format x scheme pair.
- **`reasoning_effort` goes only where the model declares it, and the
  declaration is a per-rung map, not a flag.** `MODELS[alias]["effort"]` is
  `{rung: wire_value}`, so a model accepting `low`/`medium`/`high` but not
  `xhigh` simply lacks that key. Collapsing it to a boolean is what would get
  a partly-supporting model sent a value it rejects. An undeclared model gets
  an empty map and the field is never written — that is what makes the default
  safe against a relay that 400s on the parameter. A provider may opt its
  models in wholesale via `reasoning_effort` in `custom_providers.json`
  (`/provider effort <name> on|off`), which grants the ladder *minus* `off`.
  `core/api_payloads.model_effort_map` is the only resolver;
  `resolve_reasoning_effort` is called from the single `_build_openai_payload`
  and deliberately not threaded through call sites, because a missed call site
  fails silently as "the setting does nothing".
- **DeepSeek 400s when a `tool_calls` turn replays without that assistant
  message's `reasoning_content`.** A whole-chain invariant: `core/turn_api.py:90`
  buffers it, **both** branches of `AgentSession._append_assistant_or_tool_call_message`
  store it (the `tool_calls` branch is what every real turn takes; the other is
  the easy one to check), and `_sanitize_messages_for_model` preserves it for
  reasoning models. `TestReasoningContentReadBack` in
  `tests/test_reasoning_effort.py`.
- **Effort is one knob, so a delegated worker inherits the level** — a worker
  resolves from its *own* alias, so "set `high` once" means `high` everywhere.
  The one exception is `SubAgentSession.MAX_TOKENS`: a worker chosen for speed
  inheriting a 32k output ceiling contradicts the reason it was chosen (it
  mirrors the existing `tool_max_chars` clamp). Do not start suppressing
  effort per call site (`/think`, history summaries, workspace naming,
  delegation) — four private switches drift, and the user asked for one
  control.
- **An opt-in that persists into `custom_providers.json` can invalidate the
  whole file, so it must never create an entry.** `_validated_custom_provider_data`
  requires *every* entry to carry a valid `base_url` and an `api_key_env`, and
  `load_custom_providers` abandons the entire file on the first failure — so one
  bad entry costs the user every custom provider, every custom model, and all
  persisted activation state on the next start, with no error beyond a warning.
  `/provider effort` shipped with `setdefault`, which minted exactly such a bare
  `{"reasoning_effort": true}` for a built-in name and reported success. Two
  independent guards now hold at the persistence boundary, and both are pinned
  separately because one subsumes the other for the ordinary case: refuse
  `BUILTIN_PROVIDER_NAMES` (needed only for a *complete* shadow entry, which
  `load_custom_providers` skips anyway, so writing to it would report success
  and change nothing), and require an existing entry that already carries both
  required fields. The command-layer guard in `_effort_flow.py` is UX; it
  returns first and would mask a regression in the store, which is why the
  direct tests exist. `test_provider_effort_on_builtin_is_refused_and_preserves_the_config_file`.
- **`/provider` subcommand completion is a second hand-maintained list.** The
  dispatcher in `core/commands/provider.py` and the completion entries in
  `pawnlogic/cli.py` are separate; `/provider effort` shipped with a handler and
  README docs but no completion entry, so it was typeable only in full.
  `test_provider_completion_covers_every_dispatched_subcommand` compares the two
  by scanning both sources, so a new subcommand cannot merge without one.
- **An effort change must preserve `preferred_worker`.** Every tier preset
  pins it to `"auto"`, so the old `/deep`-style writes silently undid an
  explicit `/worker <alias>` lock; because the worker menu reads the on-disk
  policy *first* (`core/commands/tools.py`), the menu then showed the old value
  while delegation actually used `auto`. `apply_effort` is the single write path and carries it across —
  a new writer doing a blanket `update_dynamic_config(preset)` reintroduces
  this. `TestWorkerLockPreserved`.
- **Two-token commands arrive as `arg` *and* `arg2`, not one remainder
  string.** `handle_slash` splits as `split(None, 2)`, so `/model <alias>
  <effort>` gives the alias in `arg` and the level in `arg2`. A parser that
  only splits `ctx.arg` makes the documented form unreachable *while its unit
  test — which passes the whole string as `arg` — still passes*. Same split
  for `/provider <sub> <rest>`. Test two-token forms through the real split.
  A command taking free text or a path (`/think`, `/cd`, `/file`) must read
  `CommandContext.text`, not `arg`; reading `arg` silently keeps only the
  first word (`test_think_sends_the_whole_prompt_through_handle_slash`).
- Provider visibility must agree across CLI, TUI, completions, and runtime fetch.
- Trust/Operation/Network Policy drift across host, Docker, browser, MCP, and
  CTF paths; URL adapters must re-evaluate DNS and redirects.
- **DNS is resolved once per URL after syntax and unconditional target denials,
  and the connection layer must never re-resolve.** In
  `tools/network_adapter.py`, `_pinned_addresses_for_url` only pins literal
  IPs; the `NetworkPolicy` resolver closure performs the single hostname
  lookup and captures its result, while direct urllib handlers only dial those
  pins (`_PinnedHTTP(S)Connection`). Each direct redirect hop is pinned
  independently. A missing pin record or failed lookup fails closed instead of
  falling back to a fresh lookup, which is what closes the DNS-rebinding TOCTOU
  gap (issue #177). Proxy-routed hops deliberately use the stdlib proxy path;
  when a redirect changes proxy routing, every direct hop still uses its own
  policy-time pins. A new fetch path that opens sockets must go through
  `open_url_with_policy` (or carry the same pin table). `tests/test_network_dns_pinning.py`
  gates the invariant, including the single-resolution assertion.
- **PawnLogic containers must never be privileged or gain Linux
  capabilities.** `tools/docker_sandbox.py` rejects `privileged`,
  `cap_add`, `cap_drop` and `security_opt` in tool arguments with a
  SECURITY BLOCK, and `spawn_container()` in `tools/docker_spawn.py` is the
  single choke point that raises `PermissionError` whenever a forbidden kwarg
  is present, so these kwargs never reach the Docker SDK, even under
  `python -O`. The same funnel merges the one-shot hardening defaults
  (`cap_drop=ALL`, read-only rootfs, tmpfs) after the deny check, so tool
  arguments cannot supply raw hardening kwargs. Trusted Python callers may
  override read-only/tmpfs defaults; dependency installation uses this exception.
  The docker policy helpers
  live in `tools/docker_spawn.py` (funnel + hardening + container user),
  `tools/docker_egress.py` (operator-declared bridge egress scope),
  `tools/docker_mounts.py` (mount safety), and `tools/docker_schemas.py`
  (tool schemas). A new container tool that calls
  `client.containers.run` directly instead of going through
  `spawn_container` silently drops this guarantee — keep the funnel.
- **Any tool path that grants a container network access must go through
  `_check_network_policy`.** The airlock (`tool_install_package`) used to
  attach bridge egress without the `allow_network` authorization the other
  container tools require — that bypass is now closed. A new tool that
  connects a container to a network must call the same gate. Airlock rejects
  installs while an operator scope is configured; without a scope its legacy
  capability gate remains mandatory. Before any attach, a compatibility guard
  refreshes the container and rejects offline (none/unattached) membership and
  unknown network state without connecting or installing — the daemon cannot
  attach none-created containers to bridge afterward; the container is
  preserved and the rejection never suggests host networking. Every install
  also runs under a hard deadline (`timeout_seconds`, integer 1–300, default
  120) enforced by an independent watchdog thread: the installer call and the
  owned-network disconnect are bounded waits, the per-container lease is
  acquired before the bridge-membership ownership decision and held until
  cleanup completes, so the deadline and serialization span the whole
  lifecycle. Expiry revokes the tool
  handle and attempts container termination and owned-attachment removal;
  failed or unconfirmed daemon cleanup is explicitly reported. Per-container operations are
  serialized with generation-bound timers that reject stale callbacks before
  expiry is claimed; unresolved cleanup is a containment failure, never success.
  A hung attach that completes after the deadline never reaches the
  installer, and the disconnect-failure containment is itself a bounded
  wait. Installer admission uses one generation-bound, atomic state claim
  inside its worker; expiry winning that claim prevents the daemon exec call.
  Already-admitted work can race with remote termination: Docker requests
  cannot be physically cancelled atomically. No state lock spans a daemon
  call. Metadata/attach calls have the finite SDK timeout and may return
  after the operation deadline while the watchdog attempts containment.
  If expiry containment outlives its bounded join window the operator is told
  containment was unresolved; a late containment pass may still land on the
  same condemned container (fail-closed over-kill) but skips the
  owned-attachment disconnect once a successor operation has begun.
  If its temporary disconnect
  fails, revoke tool access and kill the container, falling back to forced
  removal; if both fail, report the live-container risk and manual cleanup.
  An attachment error must still trigger cleanup: a daemon can attach before
  its response is lost. If refreshed daemon state confirms no attachment,
  preserve the offline container; unknown state still requires cleanup. Never
  return success after failed network cleanup.
- **Docker network modes are a closed set: `none`, `bridge`, `host`.**
  `_check_network_policy` and the pure `build_docker_execution_plan`
  validator reject `container:<id>` sharing and unknown modes before the
  Docker SDK is called, regardless of `allow_network` — a shared-namespace
  mode must not inherit another container's network without an authorization
  gate of its own. The tool schemas carry the matching `enum`, so keep the
  schema, plan validator, and gate in agreement when touching network modes.
- **Legacy containers are identified, never auto-quarantined.**
  `pwn_container action=preflight` is a read-only report over
  PawnLogic-labelled (`pawn=true`) containers: running bridge/host/
  user-defined/unknown-network membership is flagged as needing attention,
  offline (`none`) containers are listed as offline, and missing or
  ambiguous daemon state is reported as unknown — never as safe. Enabling
  `PAWNLOGIC_DOCKER_EGRESS_ALLOW` does not quarantine these containers;
  stop/destroy stays an explicit owner action, and the report never mutates
  a container. The classification lives in `tools/docker_preflight.py`.
- **Authorized CTF plaintext HTTP remains supported in disposable containers.**
  Use `run_code_docker` with explicitly authorized bridge networking, existing
  memory/CPU/PID limits, and no credential mounts. Container HTTP clients do
  not inherit browser proxy framing limits. Bridge authorization carries an
  operator scope when `PAWNLOGIC_DOCKER_EGRESS_ALLOW` is set: an authorized
  bridge request runs with `network=none` and a read-only-mounted Unix relay
  to the host HTTP/CONNECT proxy. `tools/docker_http.py` owns setup/cleanup;
  `tools/container_http_proxy.py` enforces the explicit host/IP/CIDR scope,
  and `tools/container_http_protocol.py` owns bounded streaming/framing.
  Hostnames resolve once into a frozen all-address snapshot. CIDRs match
  literal IPs only; unknown hostnames fail without DNS. Network Policy hard
  denials still apply. The container can open the relay socket directly, so
  every host proxy request must enforce scope before forwarding; environment
  variables and Unix permissions are not the enforcement boundary.
  Numeric sockets never re-resolve. Operation expiry/cleanup closes pending
  dials and active sockets before container removal; setup/cleanup failures
  are SECURITY BLOCK. Scoped runs require built-in Python, a non-root numeric
  UID:GID, no extra mounts or dependencies, and timeout 1–300 seconds.
  Fixed/chunked uploads stream up to 64 MiB per request with bounded headers,
  trailers and concurrency; Expect/Upgrade are rejected. CONNECT is opaque
  TCP to approved target/port, not TLS-only or arbitrary transparent TCP/UDP.
  Under scope, host networking, connected persistent create, all persistent
  exec, extra mounts and Airlock are denied. Offline runs and unmounted
  offline persistent creation are allowed; list/destroy remain available.
  Nonzero UID is mandatory; numeric GID may be zero. Scope does not quarantine
  previously running connected containers: destroy/stop them first, and change
  declarations only between operations.
  The creation funnel rejects alternate network kwargs and non-none mode.
  Without a scope, bridge/host authorization remains capability-only.
  Never suggest host networking or disabling browser enforcement as a workaround.
  Outside scoped bridge runs, one-shot hardening retains the host UID:GID
  (possibly root) and permits dependency installs with writable rootfs;
  persistent containers keep image defaults. Transparent arbitrary TCP/UDP
  enforcement is a separate host-managed phase; no sudo/firewall changes are
  made by tool code. `tests/test_docker_http_integration.py`,
  `tests/test_container_http_proxy.py`, `tests/test_container_http_protocol.py`
  and `tests/test_container_http_relay.py` gate these boundaries.
- **IPv4-mapped IPv6 must retain IPv4 hard denials.** Network Policy classifies
  the effective IPv4 before metadata, special-address and private-network checks;
  original address forms remain available for scope matching. Explicit scope
  authorization must never admit mapped metadata. Literal and hostname-snapshot
  regressions in `tests/test_network_policy.py` and
  `tests/test_container_http_proxy.py` fail before any dial.
- **The host egress helper is an uninstalled review package.** Its policies
  must reject metadata including `100.100.100.200` and mapped forms. Cleanup
  verification must use successful complete snapshots; failed queries and
  short-circuit pipeline SIGPIPE must never masquerade as absent rules.
  Real backend coverage and owner authorization are still required before
  installing any host filter. `tests/test_host_egress_helper.py` gates the
  artifact behavior, not kernel enforcement.
  Blanket established-state acceptance is REPLY-only; original-direction
  connections must still match pinned destinations, including pre-activation
  connections. Artifact deletion alone cannot quarantine a live container.
  `tools/host_egress_preflight.py` is a read-only prerequisite CLI, never a
  privileged entry point or activation gate. It records all kernel matrix
  paths as `not_run`; no simulated result can substitute for backend evidence.
  Every nftables packet rule binds the approved bridge interface. Conntrack
  deletion and verification require an explicit original-direction zone and
  original source, without an allowlist destination restriction. Before running
  these artifacts, an executor must prove exclusive zone/source ownership,
  validate actual zone assignment and quarantine the owned container. A numeric
  zone alone neither creates isolation nor proves ownership, including zone 0.
- **Browser transports require the loopback policy proxy.** Chromium skips
  redirect route callbacks, so context guards alone cannot enforce destinations.
  Both Patchright paths (including Scrapling >= 0.4.15) disable HTTP/2/QUIC,
  explicitly proxy loopback, request Service Worker blocking, and restrict non-proxied
  WebRTC UDP. Each CONNECT authority or single plain-HTTP request is evaluated
  non-interactively and dials only policy-time pins. Only a host-confirmed
  private decision can mint a grant: retain its exact pins and operation token,
  never override hard denials, and never grant background requests. Scope exit
  and stop close existing client/upstream sockets, including dial races; reject
  overlapping scopes and bound handlers. Plain HTTP cannot raw-splice later
  requests: validate Host/body framing, strip proxy/hop headers, force close,
  and reject unsupported streaming/upgrades. Preserve CONNECT pre-read bytes.
  A missing proxy fails navigation; lazy guard/proxy providers are resolved
  after bootstrap and exceptions must not return stale success. Failed setup
  closes the context, and Scrapling verifies the hook on every retry.
  `tests/test_policy_proxy.py`, `tests/test_proxy_protocol.py`, and the optional
  real Chromium `tests/test_browser_proxy_integration.py` gate these boundaries.
  Patchright 1.63 implements Service Worker blocking with a JavaScript shim;
  the native prototype method bypasses it. The mandatory proxy
  must enforce real Service Worker egress even with registration allowed.
  CONNECT enforces destinations, not TLS contents or an OS process sandbox.
- **MCP tool results must stay attributable to their server.** Results go
  out as `_ProvenancedStr` carrying `MCPToolProvenance` (server,
  transport, call id, content/config/command hashes); the executor
  preserves it into `ToolExecutionResult.metadata["mcp_provenance"]` and
  the attestation header stays in the model-visible text. A new result
  path that stringifies MCP output must not drop the provenance.
- Extension discovery must not import or enable third-party code during startup.
- User-friendly mode must not leak debug internals; `/mode` remains the switch.
- Stream adapters must not change public delta dict keys or ordering.

### Terminal: selectors, modals, and the single Application

- **Only one Prompt Toolkit `Application` may own the PTY.** Every interactive
  selector, including the `/provider fetch` multi-select, runs inside the
  persistent Application via `controller.run_selector`; a second
  `run_async()` corrupts cursor/escape state (ADR 0010).
- **`/model` has two front ends, and the selector name resolves in one
  module's globals.** With a controller it renders a `ModelSelector` through
  `run_selector`; without one it calls `cc_style_model_selector`, a standalone
  `Application` that may only run where no controller owns the PTY. That
  function lives in `core/commands/_model_picker.py` and is **re-exported**
  into `core/commands/provider.py` — the call site resolves it there, which is
  what keeps both the real picker and the tests that replace
  `provider_commands.cc_style_model_selector` working. Do not "clean up" the
  re-export into a lazy call-site import: it silently disconnects those tests.
  **Both branches need a positive test** — the original only asserted the
  standalone picker is *not* called with a controller, so a dead call site
  stayed green.
  `test_model_dispatch_reaches_standalone_picker_when_no_controller`.
- **A `Float` never participates in layout; it paints over existing rows.** The
  live terminal is inline (`full_screen=False`), so its block is only as tall as
  the rows below the cursor — about three — and `FloatContainer` anchors a
  cursor-float *below* whenever space below ≥ space above, then clips it. The
  completion menu was mounted that way, so "below the cursor" was the toolbar:
  model field and fuzzy candidates drew on top of each other. It is now an
  `HSplit` child between output window and composer, so it reserves its own
  rows. **Any new menu or overlay a user types into must be real layout.**
  Two traps make this easy to reintroduce unnoticed:
  `DummyOutput.get_rows_below_cursor_position()` returns a hardcoded `40`, so
  tests using a bare `DummyOutput` get a block where the float happens to flip
  above and looks correct — use a double reporting production geometry
  (`_InlineSizedOutput`); and `FloatContainer` did nothing else here, so the
  root is a bare `DynamicContainer` — reintroducing it reintroduces the
  clipping. `test_completion_menu_gets_its_own_rows_instead_of_covering_the_toolbar`.
- **The toolbar renders fields within a width budget** (`_TOOLBAR_HARD_MAX` /
  `_TOOLBAR_COL_MARGIN` in `pawnlogic/live_repl.py`; there is no
  `_TOOLBAR_WIDE_MIN` — an earlier version of this entry named a constant that
  never existed). The row is `fields + "  ·  " + status` and is clipped as a
  whole, so **the status is reserved FIRST**: it is the only per-render-changing
  part, and it used to be the first thing a narrow terminal threw away. Two
  invariants follow (`tests/test_status_line.py`): fields are cut only on the
  double-space boundary `build_bottom_toolbar` joins them with, so no row shows
  a half-label like `Model: bai:`; and when not even one whole field fits,
  fields are dropped and status takes the row. Keep status short — a model
  prefix duplicated the never-dropped `Model:` field and forced mid-value
  clipping at 80 columns. `build_bottom_toolbar` deliberately over-counts the
  `ctx` segment (~21 columns) and `tests/test_live_repl.py` pins the
  resulting 80-column set.
- **A tool thread must never leave a selector mounted.** Abandoning a worker
  does not unwind it, and a thread-side `future.result(timeout=...)` that
  expires does not cancel the coroutine, so `run_selector`'s `finally` never
  ran and `has_state` pinned the eager bindings on: the composer went read-only
  for the rest of the session. Every deadline for a modal a tool thread waits
  on must be owned by the loop that mounted it (`asyncio.wait_for` in
  `run_confirmation_modal`), and the watchdog's abandon path must additionally
  reclaim a pending confirmation via `cancel_pending_confirmation()`. The
  thread-side wait is a backstop and must outlast the loop-side deadline.
  `TestConfirmationModalLifecycle`.
- **A mounted selector owns the keyboard through `eager=True` bindings**, so a
  trust-boundary modal must not resolve on an incidental keystroke. The
  high-risk confirmation defaults to **Deny** and needs an explicit `y`; bare
  `Enter` denies. It also swallows every key until the host has read
  `formatted_text` once — until the Float paints, the user has not seen the
  prompt. Do not widen `ConfirmOperationSelector.handle_key` to fall through,
  and keep the selector's `escape` eager while the Turn-interrupt `escape` in
  `live_repl` stays non-eager so the modal wins the key.
- **An Application task that ends without `close()` must both wake the parked
  CLI submission waiter and resolve any pending selector future.** A silent
  exit there previously left a force-quit as the only recovery.
- **An idle Ctrl+C must never become a `BaseException` in the Application
  task.** Two sources used to produce one: the `c-c` binding's
  `event.app.exit(exception=KeyboardInterrupt())` and
  `install_live_interrupt_handler`'s idle raise. `run_async` does not catch it,
  so it unwound through `asyncio.run` and skipped the CLI teardown — and
  `session.shutdown()` is the only thing that releases the non-daemon
  `pawnlogic-turn-*` worker, so the interpreter then blocked in
  `threading._shutdown()`. Because `_observe_terminal_task` had already
  disarmed SIGINT to `SIG_IGN`, Ctrl+C could not break that hang either: the
  tty echoes `^C` because ECHO is independent of delivery, so the reported
  symptom was "cannot exit" with only SIGKILL working. Both sources now route
  to `on_idle_interrupt`, which runs the same double-press confirm the readline
  path uses and closes the terminal on the second press. The bare
  `raise KeyboardInterrupt` survives only as the fallback for a caller that
  installs no idle handler. The teardown is a `finally` on purpose — it is the
  second half of the fix and is what makes the fallback safe. Do not move
  `session.shutdown()` back out of that `finally`, and do not give the `c-c`
  binding its own exit path again.
- **The teardown releases the Turn worker on a bounded deadline, so a wedged
  worker can still wedge exit — the one idle-Ctrl+C path with no recovery.**
  `core/turn_scheduler.py:967` sets `daemon=False`, the only non-daemon thread
  in the repo, so `threading._shutdown()` waits for it indefinitely and
  ignores any deadline the thread applied to itself. The release is
  `join_worker.join(timeout=self._shutdown_timeout)` (`:702`), default **5.0 s**
  (`:448`); a worker still alive at the deadline is abandoned and recorded as
  `"worker did not stop before shutdown timeout"`, and the interpreter then
  blocks on it anyway. The `finally` converts the *common* case (teardown
  skipped entirely, worker never released) into this *rare* one. **It does not
  eliminate the hang class; do not write or repeat that it does.**
- **The idle-Ctrl+C e2e proves the teardown runs, not that the hang is gone.**
  `test_idle_ctrl_c_exits_cleanly_and_runs_the_teardown` never starts a Turn,
  so there is no live `pawnlogic-turn-*` worker during it — the reported
  scenario has no end-to-end coverage. A pexpect `\x03` also reaches the `c-c`
  *binding* rather than the Python signal handler, so that e2e gates only the
  binding path; the SIGINT path is gated separately by
  `tests/test_live_sigint_teardown.py`. Mutation-testing each source
  independently is what established the split: reverting only the signal
  handler leaves that e2e green.
- **A live-side notice must go through `run_in_terminal`; a direct `print`
  from the Application's event loop is swallowed,** because the renderer owns
  stdout. `_terminal_notice` is the only correct route, and it is now the only
  remaining `run_in_terminal` user: each notice still erases and redraws the
  block in several writes, so it must stay a rare, explicit event and never
  carry streamed output (see the history-frame entry below). The two idle sources
  are also independent schedulers (one closure variable each in
  `build_prompt_toolkit_bindings` and in `install_live_interrupt_handler`), so
  a new source needs its own guard. The live SIGINT handler is disarmed to
  `SIG_IGN` from `_observe_terminal_task`; do not restore that guard to depend
  on `restore()` — the shutdown block is exactly the code the exception skips,
  so `closing` never became true.
- **Prompt Toolkit live composition, worker threads, persistent repainting,
  modal pause/resume, and TTY-owning tools can race.** Live-input tests must
  exercise the fixed-bottom application, stdout/stderr restoration, and the
  serial readline fallback.
- **The multiline composer must keep `dont_extend_height=True` with
  `Dimension(min=1, max=5)` and must NOT use `weight=0`.** Multiline content
  raising preferred height while zero weight excludes the child from the growth
  rotation, sending PT 3.0.52's `take_using_weights` into an infinite layout
  loop (frozen page, dead keys on wrapped input). Pinned by the narrow
  live-terminal suite and the e2e live-composer flows.
- **The composer cannot accept a literal `\n` from the key path.** The `c-j`
  binding was removed because it intercepted bare `\n` (which the PTY e2e
  suite relies on for submit) and `eager=True` on `enter` made the first typed
  key disappear. Multi-line drafts need a future `/draft`-style command driving
  `buffer.insert_text`; until then the only way is one pre-formatted `send`.
- **The inline block must never be as tall as the host terminal.** Prompt
  Toolkit caps an inline block at `rows`, and a block that tall starts at
  screen row 0, so the history-frame erase (`ESC[<n>A` to the block's
  first row, then `ESC[J`) runs from the home position. tmux's default
  `scroll-on-clear` treats that as a full-screen clear and keeps the old rows
  in the scrollback: the transient viewport survived there and the flush
  wrote the same answer below it. The viewport reaches full height whenever
  more undelivered output arrives than fits on screen inside one
  `_HOST_FLUSH_MIN_INTERVAL_SECONDS` window — a fast stream or one large
  tool result. `_HeadroomContainer` (the Application root in
  `pawnlogic/live_terminal.py`) clamps the preferred height to
  `rows - _INLINE_HEADROOM_ROWS`; replacing the root with a bare
  `DynamicContainer` reintroduces the duplicate. The clamp cannot cover a
  cursor already at row 0, where Prompt Toolkit's cursor-position report
  alone makes the block full height. Prompt Toolkit's default `c-l`
  (`clear-screen`) is the one path that puts the block there: the next
  history frame then erases from home once, and tmux keeps one stale copy of
  the block. Do not add another clear without revisiting this.
  `test_inline_block_never_claims_the_terminal_top_row`.
- **Rich in-Application TUIs (`/provider`, `/skills`)** contribute containers,
  key bindings, and focus targets to the persistent Application. Their live
  command factories must never return an awaitable or start a nested
  `Application`; tests must execute the real command path and preserve host
  Application/task identity.
- **The 0.3.6 Queue TUI is deliberately main-thread-only** and must not claim
  worker stdin. The persistent terminal renders bare `/queue` inline rather
  than pausing for a nested selector; non-TTY and readline paths use text
  controls. Escape shares a prefix with Alt shortcuts, so real-input tests must
  keep its bounded sequence-resolution latency covered. Mouse-wheel and
  coordinate-free ScrollUp/ScrollDown stay owned by the output viewport so
  composer history cannot consume them.
- **The status ticker must not repaint an unchanged screen.** Prompt
  Toolkit's renderer hides and re-shows the cursor on *every* render, even
  one with an empty screen diff, so the 250 ms ticker's unconditional
  `invalidate()` sent four cursor hide/show cycles a second to an idle host —
  the post-answer flicker. `_invalidate_if_polled_surface_changed` compares
  the toolbar and queue-preview text against what was last *painted*
  (`_painted_toolbar`, recorded in `_render_toolbar`; `_painted_queue_preview`,
  recorded in the preview's visibility filter), not against the previous tick,
  so a state that flips and flips back between ticks cannot strand a stale
  row. A new time-polled surface must join that comparison, or it stops
  updating; an unconditional repaint anywhere on a timer reintroduces the
  flicker. `test_idle_status_ticker_does_not_repaint_an_unchanged_screen`,
  `test_status_ticker_repaints_when_the_polled_status_changes`.
- **Live host scrollback is one atomic history frame; worker threads must
  never write to the TTY and streamed output must never go through
  `run_in_terminal`.** `run_in_terminal` reached the terminal as five or six
  writes (erase+flush, cooked mode, the rows, reset+flush, a `ESC[6n`
  cursor query, redraw), and the terminal displayed the erased block between
  them — the full-screen flash the owner saw on every flush, which a 2 s
  debounce only made rarer. `write_history_frame` (`pawnlogic/terminal_frames.py`,
  ADR 0015) holds every flush, runs the renderer's own `erase()`, writes the
  rows, and calls `Application._redraw()`, so erase, rows and repaint leave as
  ONE write, bracketed by DEC 2026 synchronized update via
  `SynchronizedVt100Output`, which `pawnlogic/cli.py` must keep creating
  (`create_live_output`). Three ways to reintroduce the flash: a flush path
  that writes rows outside `output_frame`, `invalidate()` in place of
  `_redraw()` inside the frame (the repaint then lands in a later write), or
  a Prompt Toolkit upgrade that flushes from somewhere the frame does not
  hold. The delivery cursor advances *before* the repaint, or the repainted
  block shows the delivered rows a second time, and is restored if the frame
  cannot be written; complete lines stream live, partial lines flush once at
  close, and the bounded retry/breaker is unchanged. The repaint keeps the
  block's bottom edge (`_history_floor` via `_HeadroomContainer`), or the
  composer jumps up after a preview or selector closes. Insertion scrolls the
  whole screen (Codex's Windows Terminal strategy) rather than a DECSTBM
  region, which discards rows on Windows Terminal. Live flushes stay spaced
  by `_HOST_FLUSH_MIN_INTERVAL_SECONDS` (0.1 s; batching only) and payloads
  are pre-wrapped to the host's real column count via `_wrap_host_payload`.
  The payload keeps SGR and drops every other escape
  (`_host_scrollback_text`): stripping SGR too made each flush repaint dim
  thinking text in the default color, which the owner saw as flicker. Color
  state crosses flush boundaries from the delivered prefix, so a new flush
  path must pass `prefix` to `_host_payload_text`; without it a span split by
  a flush loses its color on the far side. The live viewport re-opens the
  same span (`_delivered_sgr`), or the undelivered half of a span renders in
  the default color until it is delivered. `_wrap_host_payload` must keep
  giving SGR zero width, or colored CJK rows fold early.
  `tests/test_terminal_frames.py` (one write per flush, no erase without its
  repaint, no CPR or cooked mode, rollback, floor, live-viewport color),
  `test_live_host_flush_carries_color_across_flushes`.
- **The ratatui frontend is a separate wire-v1 client**, not a UI embedded in
  the Python REPL. Its terminal guard must restore raw mode, alternate screen,
  mouse capture, bracketed paste, and cursor visibility on every error path. It
  must treat streamed answer text as authoritative and use `result` only as a
  non-streaming fallback — rendering both duplicates every answer. Wire v1
  cannot host the Python selectors, so modal-only commands must fail fast with
  explicit text alternatives.
- **Prompt Toolkit key bindings classify intent before main-loop dispatch**;
  the session Adapter must reconcile stale START/STEER/FOLLOW_UP hints against
  the latest scheduler view. Text-only completion must drain unclaimed steer
  input and keep queued content visibly previewed above the composer.
  Cancellation settlement must stay off the UI thread and mark the prefilled
  recovered draft a one-shot replacement, not a follow-up.

### Provider TUI

- **Add and Edit are one renderer** (`core/provider_tui_form.render_wizard`)
  with two persistence paths, so their invariants live in different places.
  Edit locks Name and API Key by **excluding them from the arrow-key focus
  cycle**, not by validating on save — any new row, or any binding that sets
  `_wiz_focus` directly, makes a locked row reachable or writable. Edit also
  saves with an empty models map and `replace_models=False` to leave loaded
  models on disk; passing the map with replacement silently drops every fetched
  model. Both are test-pinned; name/key/delete identity rules belong in
  `provider_runtime`, not the TUI.
- **`ProviderTUI` mirrors widget state onto `ProviderTUIState` through
  `_STATE_ATTRS`, one-way, at render time.** A render calling `_sync_*_from_input()` copies widget text back
  over the state field, so a state-only reset is undone by the next paint. The
  model search `TextArea` outlives a selection session, so `begin_model_selection`
  clearing `model_search` left the selector reopening pre-filtered, down to an
  empty list with nothing to tick. Teardown must go through
  `ProviderTUI._begin_model_selection`, which clears widget and state together;
  the state method cannot reach the widget.
- **The model selector shares one cursor between rows and the three action
  buttons** at indices `total`, `total + 1`, `total + 2`. Any list longer than
  a handful buries its own actions — a real openrouter sync returned hundreds,
  so loading a ticked one cost one `↓` per model. Invisible in a 3-model test
  and invisible in the panel itself, since buttons are always painted at the
  bottom. Two shortcuts must stay: `L` reaches the action row, `s`/`S` load
  from the current position. They share `_ms_load_selected()` with the action
  row, so the "select at least one model" guard has a single home — a shortcut
  added beside `_do_save_models()` bypasses it. Keep one test at realistic
  list length.

### Queue, steering, and turn lifecycle

- **A failed or aborted Turn parks the session and mints a recovered draft.**
  That draft is a *retry offer, not a queue entry*: counting it as queued work
  classified a newly typed prompt as `FOLLOW_UP`, whose implicit RESUME the
  anti-cascade gate refuses — the prompt was queued while the UI still showed
  `Idle` (the post-429 "typing does nothing" freeze). Admission must resolve a
  recovered draft to `START` and resume explicitly, on both live and serial
  readline paths.
- **The parked state gates only the automatic drain.** Implicit RESUME is
  rejected until the user explicitly resumes (``/queue resume`` or Enter on the
  draft, via `ControlAction.explicit`); new input still queues normally. The
  live terminal keeps failure silent in the toolbar (label-only `Failed`); the
  internal anti-cascade gate is preserved.
- **An interrupt with queued work is a STEER, not a recovery.** The scheduler
  must not mint a recovered draft while the queue is non-empty, and the worker
  must re-drive the queue after the interrupt settles
  (`_recover_active_unlocked` queue guard; INTERRUPTED `should_return` in
  `_drive`). The recovered-draft flow applies ONLY to empty-queue interrupts.
  Tests pin both halves; the preview never renders recovered rows (status line
  plus prefilled composer carry them).
- **Steer semantics changed in P2-0 (ADR 0009 revision).** Esc with queued work
  now discards the interrupted prompt's parked-draft path entirely; empty-queue
  Esc still parks. Scripts relying on the interrupted prompt reappearing as an
  editable draft while a steer was queued will see the queued turn run instead —
  intended contract, not a regression.
- **The queue preview above the composer is a CONDITIONAL surface.** It renders
  nothing while the queue is empty (the 0.3.7 clean-composer goal) and shows
  the muted `↳ queued [kind]` rows the moment a steer or follow-up is queued.
  Removing it makes Enter-while-running and the Esc→CLAIM_STEER handoff
  invisible (the owner's regression report after the initial hidden-queue
  re-scope). Tests pin empty/queued/failed.
- **Queued messages are reworkable through gestures, not commands.**
  `ControlKind.POP_ALL` atomically drains queued lanes and the recovered slot
  into one editable draft, driven by bare Esc / Up / Alt+Up on an empty idle
  composer. Esc while a Turn runs keeps the interrupt + CLAIM_STEER meaning.
  `pop_all_session_queue` is the seam; `/queue` stays hidden from the command
  surface with its resume/clear aliases intact.
- **`/q` is a registered alias of `/exit`** and must stay in
  `LIVE_SLASH_COMMANDS` so the running-Turn whitelist keeps accepting it.
- **Safe-point steering can alter the Tool Call batch protocol**; skipped
  results, ordering, and plan-guard accounting must remain complete.
- **`_build_status` must return `""` for idle**, not a string the toolbar
  filters. It used to return `"[model]  Idle"` and `_render_toolbar` suppressed
  it with `"Idle" not in status` — a substring test that also swallowed the
  recovered-draft state, whose text contains "Idle", so that state had never
  been displayed despite three docs claiming it was. Do not reintroduce
  substring matching on status text.
- **The `Sent` state exists because nothing else is true between admission and
  first delta**, and its clock is stamped at admission
  (`_turn_submitted_at` in `core/live_turn_control.py`), not at
  `session._turn_start_time` — `_prepare_turn` reaches that only after
  system-prompt resets and a possible blocking summary call, leaving the
  counter pinned at `0s` through the whole pre-request window.
  `_turn_first_delta` resets at admission, or the row shows the previous
  Turn's `Thinking` during the window `Sent` exists to cover. Reasoning is
  **not** a universal first-delta signal: `core/provider_streams.py` has no
  `thinking_delta` branch, so Anthropic-format thinking is dropped at the
  adapter and never reaches `core/turn_api.py` — the status words still appear,
  the text does not. A `Sent`/`Thinking` state must not start a `\r`-framed
  spinner, for the same reason `_ThinkingSpinner` is disabled in live mode.
- **`/abort` clears queued input but cannot cancel a provider request already
  handed to a synchronous stream**; Ctrl+C remains the in-flight path.
- **The system prompt is a cache prefix, not a scratchpad.** It is rebuilt
  only when its inputs change (`_prompt_phase` / `_prompt_urgent` / the
  plan-protocol setting `_prompt_plan_protocol`), and it
  must stay byte-stable across turns: rewriting it invalidates the provider
  prompt cache from position zero, so every request pays full prefill again.
  Per-turn retrieval (knowledge hits, GSA skills, local packs) is injected
  at the conversation TAIL as an assistant message marked `_turn_context`,
  immediately before its user message — and every user-message rollback
  path (`undo`, API-error pop, hard plan-guard stop) must remove that block
  together with its user message, or history stops round-tripping to its
  pre-turn shape.
  `test_prepare_turn_keeps_system_prompt_byte_identical_across_turns`
  and `test_run_turn_api_error_terminates_turn_without_hanging` gate the two
  halves. Moving retrieval back into `build_session_prompt`'s query path, or
  adding a wall-clock line to the prompt, silently reintroduces the cache
  bust; deleting the `_turn_context` flag from `_prepare_turn` without
  extending every rollback site strands the block in history. The flag
  persists through SQLite (`messages.is_turn_context`, with an ALTER TABLE
  migration for old DBs), so save/load keeps undo exact —
  `test_undo_after_reload_removes_retrieval_block_with_its_turn` gates the
  roundtrip. Budget trimming groups history from `_turn_context` markers as
  well as user messages, and a block's group ABSORBS the user message that
  immediately follows it — treating the user as a second group start splits
  the turn in two, and the budget boundary then evicts the retrieval block
  while keeping the question
  (`test_overflow_budget_boundary_evicts_block_and_question_together`,
  `test_count_turns_groups_retrieval_block_with_its_user`). Legacy
  character budgets (`ctx_max_chars`/`ctx_trim_to`) convert to token keys at
  snapshot load (`migrate_legacy_context_budget`) per key and never overwrite
  an explicit (non-None) token value — a None token key counts as absent, the
  same convention the resolver applies — because the runtime preset already seeds token
  defaults that would otherwise mask the saved budget —
  `test_load_snapshot_converts_legacy_character_budget` and
  `test_load_snapshot_keeps_explicit_token_budget_over_stale_legacy_keys`
  gate both snapshots.

- **A turn that fails after recovery began must not leave its recovery in the
  history.** The plan-only replies and `[SYSTEM: PLAN_ONLY_*]` nudges a turn
  appends are tracked by identity (`TurnState.plan_only_artifacts`, exposed as
  `session._turn_plan_artifacts`) and removed by `purge_messages`. Left in
  place they are the worst few-shot examples available: the next request shows
  the model its own plan-only replies as the established pattern of the
  conversation (14 requests, one tool call, in the session that motivated
  this). `_run_scheduled_turn` is the one place every unsuccessful turn passes
  -- plan-only limit, plan-guard hard stop, iteration or time limit, interrupt,
  stream cancellation, exception -- and it discards *before* the autosave so the
  checkpoint is clean; a new failure exit needs no cleanup of its own. The one
  exception is a provider error: its rollback pops "the last message" on the
  assumption that it is the user's prompt, and with a nudge on top it popped
  the nudge and stranded the prompt and the plan, so that purge runs inline,
  before the pop. The ledger is reset at the start of every turn: a turn that
  fails before it has one (a missing API key) must not discard the previous
  turn's plan. `undo` had the same blind spot -- it returned the nudge's text
  as the prompt to re-edit. Executed tool batches are never removed (their side
  effects happened), a turn that *recovered* keeps its plan and nudge (history
  that worked), and no limit marker is written. Do not clean by index or
  content: the history is rewritten mid-turn by the summary refresh, and two
  turns can carry byte-identical plans. The cleaned history can hold two
  consecutive user messages, which all three payload builders accept (the
  Anthropic converter merges them), and the failed-turn autosave that follows
  shrinks the list, which is what makes the incremental SQLite writer rewrite
  instead of leaving stale rows.
  `test_failed_turn_does_not_poison_the_next_request`,
  `test_provider_error_after_recovery_rolls_back_like_a_first_request_error`,
  `test_interrupt_during_recovery_leaves_only_the_prompt`,
  `test_cancelled_stream_during_recovery_leaves_only_the_prompt`,
  `test_a_turn_that_fails_before_it_starts_keeps_the_previous_recovered_turn`,
  `test_two_consecutive_user_messages_are_valid_on_every_format`, and
  `tests/test_failed_turn_persistence.py`.
- **Framework-injected user messages are not turns.** The loop appends
  user-role messages nobody typed (plan corrections, recovery nudges, the
  empty-response notice, anti-loop hints, logic refresh, urgent mode).
  `core/synthetic_messages.py` owns the marker list (`[SYSTEM:`, `[System]`,
  `[Logic Refresh`) and `_count_turns`, `context_manager._turn_groups` and the
  history-summary filter share it. Counting every `role == "user"` message made
  three real prompts count as ten turns and fired the history summary
  (threshold 8) early, and let the budget trimmer's protected "last turn" be a
  nudge instead of the question. A new producer of injected user messages must
  start with one of the markers; `test_every_framework_injected_user_message_is_recognised_as_synthetic`
  drives each real producer. `core/naming.py` keeps a private prefix check for
  snippet selection; it is not a turn counter.
  `test_three_prompts_with_recovery_signals_do_not_trigger_the_history_summary`,
  `test_recovery_nudges_do_not_split_a_turn_into_budget_groups`.
- **Retrieval injects only what overlaps the query, and an empty retrieval
  adds no block.** GSA ranking returns `[]` when no skill clears the floor and
  when the query has no ASCII word tokens; the forced top-1 fallback injected
  the archive's first skill into every Chinese-language prompt, every turn,
  and the ASCII-only tokenizer makes that invisible in English tests. The
  archive is split on `^# ` and `^## ` outside code fences, keeping only `##`
  blocks: splitting on `## ` alone glued the next category's header to the
  skill above it, and splitting on `# ` without fence awareness cuts a skill at
  every shell comment (the real archive has them). `prune_zombie_skills` writes
  the archive back, so it uses the same boundaries
  (`gsa._archive_segments`, whose segments reassemble the file exactly) and
  removes skill blocks only: it used to split on `## ` alone, so pruning the
  last skill of a category also deleted the next category's `# ` header and
  its note from the owner's file (`tests/test_gsa_prune.py`; never remove a
  `# ` line that is outside a skill). `search_legacy` returns
  nothing for a query with no keyword (it used to list the newest rows, and
  fed the retrieval fallback and the directory auto-intuition hint). Local
  skill packs have a minimum score instead of a forced fallback, and the
  SQLite knowledge adapter drops zero-overlap rows;
  `tests/test_gsa_retrieval.py` and `tests/test_knowledge_memory_adapter.py`
  pin both. A block that is empty appends no `_turn_context` message;
  placement, flag, rollback and persistence above are unchanged. Open, not
  fixed: a single shared common word still clears the 0.025 GSA floor (no
  stop-word filter), and pack matching is permissive -- a two-letter query
  keyword matches any pack keyword that contains it, so with packs enabled
  `hi` or a Chinese greeting still selects packs.
  `test_unrelated_query_injects_nothing`,
  `test_query_without_overlap_injects_nothing`,
  `test_category_header_is_not_glued_to_the_skill_above_it`,
  `test_prepare_turn_adds_no_context_block_when_retrieval_finds_nothing`.

### Execution and policy boundaries

- **Security Tools must not bypass the shared Tool Registry, Operation Policy,
  or Network Policy.** A tool wanting a policy decision calls the pure
  `classify_host_process()` / `classify_shell_command()`, as
  `tools/shell_ops.authorize_shell_operation` does; `HostProcessRunner.run()`
  classifies *and* spawns, so it is only for the single real execution.
  `run_code` additionally classifies the payload's own tractable literal shell
  surface (bash lines; Python `os.system`/`os.popen`/`subprocess(shell=True)`)
  and AST-scans Python payloads for filesystem access whose literal (or
  expanduser/expandvars-wrapped literal) path resolves under READ_BLACKLIST
  (`open()`/`pathlib` reads, `os`/`shutil` mutators), failing closed on
  anything but `ALLOW`. Still invisible: temp-file contents, dynamically
  constructed paths, `from os import system` aliases, and
  javascript/go/compiled payloads. Defence-in-depth and consistency, not an OS
  sandbox.
- **Delegated-agent requests must not bypass Provider visibility, allowlists,
  budgets, or capability filtering.**
- **A delegation tree shares one budget ceiling.** The outermost
  `delegate_task` in a context creates the tree `BudgetLedger` from its own
  budget and nested delegations reuse it; a new `BudgetLedger(budget)` per
  `run()` call would let every tree level mint a fresh full budget.
  `tests/test_delegation_tree_budget.py::test_shared_ledger_rejects_second_branch_when_exhausted`
  is the gate. Depth and tree state are ContextVars (not threading.local)
  so they propagate into the orchestrator's pool workers.
- **A repeating stream is cut inside `consume_model_stream`, not by any
  per-turn counter.** The anti-loop logic in `core/tool_result.py` counts
  repeated *tool* iterations; a model that loops on one sentence inside a
  single reply (the incident: 37 KB, one line x52, the whole 8192-token cap)
  is caught by `core/stream_repetition.StreamRepetitionGuard`, which
  `consume_model_stream` feeds per content and per reasoning chunk. On a trip
  it appends `REPETITION_NOTICE`, sets `TurnApiResult.repetition_stopped`,
  breaks, and closes the delta generator so the provider stops streaming
  (and billing). The truncated text flows through as the final answer -- no
  session.py wiring and no recovery ladder, because re-asking a looping model
  loops again. The guard is deliberately conservative (lines under
  `MIN_LINE_CHARS` ignored; a line must recur `MAX_LINE_REPEATS` times in the
  window, or the full window fall below `MAX_DUP_RATIO` distinct), because
  cutting a real answer is worse than some waste; `PAWNLOGIC_STREAM_LOOP_GUARD=0`
  is the escape hatch. A guard that buffered to hide the few leaked repeats
  would add latency to every live stream. `tests/test_stream_repetition.py`
  and the `consume_model_stream` repetition tests in `tests/test_turn_api.py`.
- **The tool watchdog abandons wedged tool threads instead of blocking the
  session**; abandoned threads keep running until process exit and their
  results are lost.
- **Tool visibility is not an execution gate.** `AGENT_PHASES` only shapes the
  prompt; a registered tool the model names still runs.
- **What the model is shown of a tool result must not depend on the UI mode,
  and must not carry terminal escapes.** `truncate_tool_output` and
  `ToolResultProcessor.process` take no `user_mode` and cannot grow one
  quietly (`test_truncate_has_no_display_mode_parameter`). They used to, and in
  the default user-friendly mode every result was head/tail-trimmed to 30+30
  lines, so a 90-entry home directory reached the model with all sixteen
  ordinary directories cut from the middle and the model concluded there was no
  project. Only `DEFAULT_VERBOSE_TOOLS` (file reads, program and shell output,
  web content) keep head/tail trimming; everything else is cut by
  `tool_max_chars`. `list_dir` sorts hidden entries last, so any cut removes
  dot-entries first. ANSI/OSC sequences are stripped before truncation (also
  for delegated workers) because they cost tokens and character budget;
  tool-result events carry no body, so no on-screen colour is lost -- except
  for `run_shell` (`core.tool_result.ANSI_PRESERVING_TOOLS`, applied by
  `model_facing_text` in both the main loop and delegated workers): CTF
  challenges hide data in escape sequences (concealed text, cursor moves that
  overwrite what a terminal shows, OSC titles), and a model that never sees the
  bytes cannot find it. `run_code` is deliberately still stripped (open
  question for the owner), and the stored bytes are raw again for `run_shell`,
  so a display path must strip at the sink: `/resume` does, and the
  `/chat view` tool preview does (`format_session_messages_pretty`;
  `test_tool_preview_strips_escape_sequences_before_a_terminal_prints_it`). A
  new path that prints stored tool content to the terminal must call
  `utils.ansi.strip_ansi` first. Still
  mode-dependent (open): in user mode `ToolExecutor` rewrites a tool
  *exception* with `user_friendly_error` and the model receives the rewrite.
  `test_what_the_model_sees_of_a_tool_result_does_not_depend_on_the_ui_mode`,
  `test_run_shell_keeps_its_escape_sequences_byte_for_byte`,
  `test_only_run_shell_is_exempt_from_stripping`,
  `tests/test_model_facing_tool_results.py`.
- **Tier presets use advisory plan-guard mode (`plan_guard_mode`)** so weak
  models can run side-effect tools without plan blocks; `/planguard strict` is
  explicit opt-in. Operation Policy is the safety gate, not the CoT Guard. A
  custom provider's `plan_protocol` setting outranks the mode: with it off no
  mode flags anything (see the plan-protocol entry above).

### Testing traps

- **A test binding `from config import DYNAMIC_CONFIG` (or `MODELS`,
  `PROVIDERS`) at import time passes alone and fails in the full suite.**
  Several test modules — `test_security.py`, `test_config.py`,
  `test_providers.py`, `test_naming.py` — evict `config` from `sys.modules` at
  import to defeat a stale mock, re-importing the package and minting a *new*
  `DYNAMIC_CONFIG`. Earlier-imported modules hold the old object, so the write
  lands where the product never reads and the test fails with a value that
  looks like the feature is broken. It is not ordinary order-dependence: the
  culprit is simply the alphabetically-later file, so a targeted two-file run
  does not reproduce it. Go through `core.state.runtime_config()` /
  `update_dynamic_config()`, and patch `core.api_payloads.MODELS` /
  `.PROVIDERS` — the maps the resolver actually reads, themselves import-time
  bindings.
- **The trap above has a second form: the *module object* can differ, not just
  the attribute value.** When the product resolves the module inside the call
  (`import config.providers as provider_config` inside a function, as
  `set_provider_reasoning_effort` and `_effort_flow` do), a test file's
  top-level `from config import providers` is a different object from the one
  the product reads, if an earlier module evicted `config` from `sys.modules`.
  Then `monkeypatch.setattr` succeeds, changes nothing, and the test reports
  `✗ Unknown provider '<name>'` — a message that reads like a product bug.
  There is no `core.state` indirection to route around here: resolve the live
  object at test time with `sys.modules["config.providers"]`.
  `test_provider_effort_on_custom_provider_still_persists` (the failure was
  the positive path; the negative ones passed vacuously for the same reason).
- **A test that only asserts the negative does not prove the wiring is live.**
  See the `/model` entry above: the original picker test would stay green with
  the call deleted outright.
- **A test that provokes `KeyboardInterrupt` or `SystemExit` in-process can
  abort the whole pytest session instead of failing.** The exception unwinds
  out of the test, pytest stops doing further work, and the run exits **2** —
  but the summary line still reports only what already passed, so it reads like
  success. Measured on a full fast-suite run: **679 of 1727 tests executed**,
  and the output said "679 passed". A regression touching a signal handler can
  hide most of the suite behind one line of `!!! KeyboardInterrupt !!!`.
  Contain the provoked exception in the test (`_run_expecting_routed_interrupt`
  in `tests/test_live_sigint_teardown.py` does this via `pytest.fail`) so the
  regression becomes a normal, named failure. A fixture that only restores the
  previous handler is not enough — it runs *after* the yield, by which time the
  exception has escaped.
- **`pexpect.expect` compiles its pattern as a regex, so a literal containing
  a metacharacter can never match.** `"Press Ctrl+C again"` does not match that
  notice: `+` binds to the preceding `l`, so the pattern demands `Ctrl` + `l+` +
  `C` while the stream carries a literal `+`. The result is a timeout on a
  feature that is working perfectly, with the notice visible in `child.before`.
  Wrap any literal in `re.escape`. Two traps in the same helper: with
  `encoding="utf-8"`, assigning a **binary** file to `child.logfile_read`
  raises `TypeError` on the first read, so every later "the child printed
  nothing" reading is an artifact of the probe rather than of the product; and
  pexpect only reads the pty inside `expect`/`read`, so a `send` + `sleep`
  diagnostic captures nothing unless something is driving reads.
- **Mutation-test each independent fix source; a suite that covers one does
  not cover the other.** See the idle-Ctrl+C entries above: reverting only the
  `install_live_interrupt_handler` route left the headline e2e test green,
  because the pexpect PTY delivers `\x03` to the `c-c` binding instead. The
  suite as a whole was correct; only running the mutations separately showed
  which gate covers which source.
- **The typed-island module list is stated in three places** (CI mypy step,
  pyproject overrides, Typed Island section). `tests/test_typed_island_sync.py`
  fails the build when they diverge — treat that failure as the gate, not as a
  test to relax. All three name the same **60 library modules**; the CI step
  passes no `tests/` file to mypy, and `tests/test_e2e.py` appears only on the
  pytest command line.
- **Esc cancellation and recovery prefill are separate test milestones.**
  `test_live_bare_escape_interrupts_one_turn_without_another_keypress` previously
  had intermittent `Status: interrupted` / `Queued: 1 message(s)` timeouts
  (including runs `33973977545` and `33974631898`). A blocking tool's
  cancellation marker precedes the scheduler's recovery-prefill callback:
  clearing the composer at that marker can race a later draft restoration.
  The PTY harness now observes the original callback returning before sending
  Ctrl-U, while retaining the cancellation deadline and queue assertions.
  This fixes test synchronization; it is not a production terminal change or
  evidence for the four owner visual checks. Do not replace the milestone
  with sleeps, automatic retries, or wider cancellation limits.
  `test_live_escape_prefills_recovered_draft_for_edit_and_replace` hit the
  same race in the first v0.4.6 publish attempt (issue #221) through a
  different door: it waited on `child.expect("original escape prompt")`, and
  that text is already in the PTY stream from the original submission, so the
  match returned before the prefill ran. **Never synchronize on text the PTY
  has already carried; wait on `recovery_settled`.** The callback runs on the
  Application loop and sets the buffer synchronously, so keys sent after the
  marker land on the prefilled draft. The test appends to the draft rather
  than clearing it, so it also fails when the prefill stops landing at all —
  the Ctrl-U form passed with the prefill stubbed out.
- **`tests/test_session_utils.py` depends on module state the full suite
  establishes.** Run in the same process right after
  `test_provider_commands.py` (or `test_model_facing_tool_results.py`) its
  `test_run_turn_*` tests fail with `sqlite3.OperationalError: no such table:
  knowledge` — 25 of them on `main` at 0.4.7, so this predates the plan-only
  recovery work; alone, or in the full suite's order, it passes. A
  verification script, a mutation harness or a CI shard that combines test
  files must give `test_session_utils.py` its own process, or it reports
  failures that no code change caused.
- **The language-policy test scans tracked files only.** Re-run it after
  staging; a green pre-commit run misses new untracked files.
- **A project-local pytest basetemp under `.agent-work/` must set
  `GIT_CEILING_DIRECTORIES` to the scratch boundary.** Otherwise Git-based
  fixtures inherit the main repository's tags and root, producing misleading
  failures. The
  packaging `_worktree_build_copy` helper does not exclude `.agent-work`, so
  never put basetemp inside a checkout that will be copied; validate from a
  clean worktree with the temporary directory as its sibling.

### Repository hygiene

- English and zh-CN docs must not drift in structure or command examples.
- Release prep must not edit version literals outside the fixed locations.
- Packaging must not accidentally include `skills/` content.
- Session scratch directories live under `~/.pawnlogic/sessions/`
  (`core/naming.py:stable_workspace_dir`); `~/.pawnlogic/workspace/` holds only
  auto-named task directories and `by-name/` aliases. The auto-naming swap
  (`core/session.py:_swap_workspace_dir`) promotes a session across roots with
  a relative reverse symlink so pre-swap absolute paths keep resolving. Do not
  reintroduce `session_<id>/` under `workspace/`.

## Agent Workflow

For broad code changes:

1. Read `AGENT.md` (this file).
2. Read the active plan under `docs/plans/`.
3. Refresh the code index: `python tools/code_index.py build`
4. Use the index: `python tools/code_index.py symbol <name>` / `refs <name>`
5. Run narrow tests first, then wider validation before committing.
6. Update this file if the work changes architecture, contracts, or risks.
