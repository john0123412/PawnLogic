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

- Current published release: `0.3.13`. Published 2026-09-29 through
  Trusted Publishing from the `Publish to PyPI` workflow run
  [`36574462310`](https://github.com/john0123412/PawnLogic/actions/runs/36574462310),
  triggered by pushing the annotated `v0.3.13` tag (tag object `dbf92f6`)
  onto the PR #161 merge commit `bcd23fd` (peeled target verified on
  `origin/main`). The full publish gate passed on the first attempt with
  no re-run: verify-release-source, Test before publish, Dynamic E2E,
  Build distributions, Build ratatui binary, Publish to PyPI, PyPI
  install smoke, and GitHub Release creation. The two TestPyPI jobs are
  skipped by design on a production release. PyPI project page:
  <https://pypi.org/project/pawnlogic/0.3.13/>. GitHub Release:
  <https://github.com/john0123412/PawnLogic/releases/tag/v0.3.13>
  (wheel + sdist + Linux ratatui binary tarball with sha256, non-draft,
  notes sourced from the `CHANGELOG.md` `[0.3.13]` section).
  The published wheel's sha256 (`964fbdb0…`) matches the release asset,
  so the installed artifact is the artifact this repository built. The
  PyPI long description is the current 0.3.13 README, including the
  free-listing wording for `Fetch`/`Sync` and `/provider test`. PyPI's
  `docs_url` field is unset and the `Documentation` project URL points at
  the GitHub `README.md`, the same as every prior release. The tag had to
  be cut from a `main` commit because `publish.yml`'s
  `verify-release-source` requires the tag's target to be an ancestor of
  `origin/main`; that is why the release needed a candidate PR (#160) and
  a separate finalization PR (#161). The four owner terminal acceptance
  checks on the published binary are still owner-gated and are not
  claimed as passed anywhere.
  This was a billing-fix release: `Fetch`/`Sync` and `/provider test`
  both charged real inferences and now read the free `/v1/models`
  listing only. It also carried the live SIGINT teardown fix (PR #158).
  `0.3.12` remains complete; it was published 2026-09-28 from run
  [`36439179697`](https://github.com/john0123412/PawnLogic/actions/runs/36439179697)
  onto merge commit `613096a`.
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
Both files, plus the list below, must name the same 43 modules;
`tests/test_typed_island_sync.py` fails the build when they diverge.

To add a module: annotate it until it passes
`python -m mypy --disallow-untyped-defs <file>`, add it to **both** the CI step
and the pyproject override, and add it to the list below.

Current stable modules: `core/turn_api`, `core/turn_guards`, `core/tool_result`,
`core/tool_executor`, `core/runtime_context`, `core/provider_runtime`,
`core/provider_models`, `core/api_errors`, `core/tool_calls`,
`core/tool_registry`, `core/context_window`, `core/workspace_cleanup`,
`core/turn_state`, `core/session_tool_loop`, `core/session_snapshot`,
`core/message_history`, `core/provider_streams`, `core/runtime_metrics`,
`core/mcp_client_manager`, `core/path_policy`, `core/provider_transport`,
`core/api_retry`, `core/provider_tui_state`, `core/turn_scheduler`,
`core/live_turn_control`, `core/turn_cancellation`, `core/queue_tui`,
`pawnlogic/live_repl`, `pawnlogic/live_terminal`, `pawnlogic/selectors`,
`pawnlogic/confirm_selector`, `pawnlogic/terminal_transcript`,
`pawnlogic/restart_recovery`, `tools/check_doc_structure`,
`tools/check_release_consistency`, `tools/merge_ctf_skills`, `tools/browser_ops`,
`tools/lsp_lite`, `tools/text_patch`, `tools/shell_ops`, `tools/docker_plan`,
`tools/pwn_binary`, `tools/pwn_debugger`.

`core/delegation` and `core/agent_orchestrator` are **not** in the island.
`core/agent_orchestrator` has an unannotated parameter at line 402 and would
fail; do not list a module here before CI checks it.

## Known Risks

- Trust/Operation/Network Policy drift across host, Docker, browser, MCP, CTF
  execution paths. URL adapters must re-evaluate DNS and redirects.
- Provider visibility drift between CLI, TUI, completions, and runtime fetch.
- **Never validate a model by inferring with it.** "Check the model works"
  implemented as a real `POST /chat/completions` is a billable request, and
  doing it per candidate turned one `/provider fetch` into hundreds of charged
  inferences. This bit twice: first in `provider_discovery`, then again in
  `provider_runtime.test_connection`, which is the more dangerous of the two
  because it fires on a plain user command and reported only "Connected". The
  rule now binds in "Provider And Model Rules": discovery reads only the free
  `/v1/models` metadata, and Test Connection reads the same listing. There is
  no billable path left in the provider flow — the only real inference in the
  product is a Turn. `core/provider_discovery.py` is the seam; adding a
  request to it re-opens the billing hole.
- User-friendly mode accidentally leaking debug internals.
- Stream adapters changing public delta dict keys or ordering.
- Extension discovery importing or enabling third-party code during startup.
- Security Tools bypassing shared Tool Registry, Operation Policy, or
  Network Policy checks. A tool that wants a policy decision must call the
  pure `classify_host_process()` (or `classify_shell_command()`), as
  `tools/shell_ops.authorize_shell_operation` does; `HostProcessRunner.run()`
  classifies *and* spawns, so it is only for the single real execution.
  `run_code` additionally classifies the payload's own tractable literal
  shell surface (bash lines; Python `os.system`/`os.popen`/
  `subprocess(..., shell=True)`) with the same policy, failing closed on
  anything but `ALLOW`. Still invisible to it: a script's temp-file
  contents, dynamic command construction, `from os import system` aliases,
  and javascript/go/compiled payloads. The boundary is defence-in-depth
  and consistency, not an OS sandbox.
- Delegated-agent requests bypassing Provider visibility, allowlists, budgets,
  or capability filtering.
- Tool watchdog abandons wedged tool threads instead of blocking the session;
  abandoned threads keep running until process exit and their results are lost.
- Prompt Toolkit live composition, worker-thread execution, persistent-screen
  repainting, modal pause/resume, and TTY-owning interactive Tools can race;
  live-input tests must exercise the fixed-bottom application, stdout/stderr
  restoration, and serial readline fallback.
- The ratatui frontend is a separate wire-v1 client, not a replacement UI
  embedded into the Python REPL. Its terminal guard must restore raw mode,
  alternate screen, mouse capture, bracketed paste, and cursor visibility on
  every error path. The frontend must treat streamed answer text as the
  authoritative rendered response and use `result` only as a non-streaming
  fallback; rendering both duplicates every answer. Wire v1 cannot host the
  Python Prompt Toolkit selectors, so modal-only commands must fail fast with
  explicit text alternatives.
- Prompt Toolkit key bindings classify intent before main-loop dispatch; the
  session Adapter must reconcile stale START/STEER/FOLLOW_UP hints against the
  latest scheduler view. Text-only completion must drain unclaimed steer input
  and keep queued content visibly previewed above the composer. Cancellation
  settlement must stay off the UI thread and mark the automatically prefilled  recovered draft as a one-shot replacement rather than a follow-up.
- The 0.3.6 Queue TUI is deliberately main-thread-only and must not claim
  worker stdin. The persistent terminal renders bare `/queue` inline instead
  of pausing for a nested selector; non-TTY and readline paths use text
  controls. Escape shares a prefix with Alt shortcuts, so real-input tests
  must keep its bounded sequence-resolution latency covered. Mouse-wheel and
  coordinate-free ScrollUp/ScrollDown events must remain owned by the output
  viewport so composer history cannot consume them.
- A failed Turn parks the session and mints a recovered draft. That draft is
  a retry offer, not a queue entry: counting it as queued work classified a
  newly typed prompt as `FOLLOW_UP`, whose implicit RESUME the anti-cascade
  gate refuses, so the prompt was queued while the UI still reported `Idle`
  (the post-429 "typing does nothing" freeze). Admission must resolve a
  recovered draft to `START` and resume explicitly, on both the live and the
  serial readline paths.
- Only one Prompt Toolkit `Application` may own the PTY. Every interactive
  selector, including the `/provider fetch` model multi-select, must run
  inside the persistent Application through the controller's `run_selector`;
  a second `Application.run_async()` corrupts cursor/escape state (ADR 0010).
- A tool thread must never leave a selector mounted. Abandoning a worker
  does not unwind it, and a thread-side `future.result(timeout=...)` that
  expires does not cancel the coroutine it was waiting on, so the
  `finally` in `run_selector` never ran and `has_state` pinned the eager
  selector key bindings on: the composer went read-only and ordinary
  typing was consumed as selector input for the rest of the session.
  Every deadline for a modal that a tool thread is waiting on must be
  owned by the loop that mounted it (`asyncio.wait_for` in
  `run_confirmation_modal`), and the tool watchdog's abandon path must
  additionally reclaim a pending confirmation through
  `cancel_pending_confirmation()`. The thread-side wait is a backstop
  and must outlast the loop-side deadline. Pinned by
  `TestConfirmationModalLifecycle`.
- A mounted selector owns the keyboard through `eager=True` bindings, so
  a trust-boundary modal must not resolve on an incidental keystroke.
  The high-risk confirmation defaults to **Deny** and requires an
  explicit `y`; a bare `Enter` denies. It also swallows every key until
  the host has read `formatted_text` at least once, because until the
  Float has painted, the user has not seen the prompt. Do not widen
  `ConfirmOperationSelector.handle_key` to fall through, and keep the
  selector's `escape` binding eager while the Turn-interrupt `escape` in
  `live_repl` stays non-eager so the modal wins the key.
- An Application task that ends without `close()` must both wake the parked
  CLI submission waiter and resolve any pending selector future. A silent
  exit there previously left the only recovery a force-quit.
- An idle Ctrl+C must never become a `BaseException` in the Application
  task. Two sources used to produce one: the `c-c` binding's
  `event.app.exit(exception=KeyboardInterrupt())` and
  `install_live_interrupt_handler`'s idle raise. `run_async` does not catch
  it, so it unwound through `asyncio.run` and skipped the CLI teardown —
  and `session.shutdown()` is the only thing that releases the non-daemon
  `pawnlogic-turn-*` worker, so the interpreter then blocked in
  `threading._shutdown()`. Because `_observe_terminal_task` had already
  disarmed SIGINT to `SIG_IGN`, Ctrl+C could not break that hang either:
  the tty echoes `^C` because ECHO is independent of delivery, so the
  reported symptom was "cannot exit" with only SIGKILL working. Both
  sources now route to `on_idle_interrupt`, which runs the same
  double-press confirm the readline path uses and closes the terminal on
  the second press, so the loop reaches teardown normally. The bare
  `raise KeyboardInterrupt` survives only as the fallback for a caller
  that installs no idle handler. The teardown is a `finally` on purpose —
  it is the second half of the fix and is what makes the fallback safe, so
  a `BaseException` unwinding through `asyncio.run` can no longer strand
  the Turn worker. Do not move `session.shutdown()` back out of that
  `finally`, and do not give the `c-c` binding its own exit path again.
- The teardown releases the Turn worker on a bounded deadline, so a wedged
  worker can still wedge exit — this is the one idle-Ctrl+C path with no
  recovery. `core/turn_scheduler.py:967` sets `daemon=False`, the only
  non-daemon thread in the repo, so `threading._shutdown()` waits for it
  indefinitely and ignores any deadline the thread applied to itself. The
  release is `join_worker.join(timeout=self._shutdown_timeout)` (`:702`),
  default **5.0 s** (`:448`); a worker still alive at the deadline is
  abandoned and recorded as `"worker did not stop before shutdown timeout"`,
  and the interpreter then blocks on it anyway. The `finally` converts the
  *common* case (teardown skipped entirely, worker never released) into
  this *rare* one (worker genuinely refuses to stop). It does not eliminate
  the hang class; do not write or repeat that it does.
- The idle-Ctrl+C e2e proves the teardown runs, not that the hang is gone.
  `test_idle_ctrl_c_exits_cleanly_and_runs_the_teardown` never starts a
  Turn, so there is no live `pawnlogic-turn-*` worker during the test — the
  reported scenario (worker alive + idle Ctrl+C) has no end-to-end
  coverage. A pexpect `\x03` also reaches the `c-c` *binding* rather than
  the Python signal handler, so that e2e gates only the binding path; the
  SIGINT path is gated separately by `tests/test_live_sigint_teardown.py`.
  Mutation-testing each source independently is what established the
  split — reverting only the signal handler leaves that e2e green.
- A live-side notice must go through `run_in_terminal`; a direct `print`
  from the Application's event loop is swallowed, because the renderer owns
  stdout. `_terminal_notice` is the only correct route. The two idle
  sources are also independent schedulers (one closure variable each in
  `build_prompt_toolkit_bindings` and in `install_live_interrupt_handler`),
  so a new source needs its own guard. The live SIGINT handler is disarmed
  to `SIG_IGN` from `_observe_terminal_task`; do not restore that guard to
  depend on `restore()` — the shutdown block is exactly the code the
  exception skips, so `closing` never became true.
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
- The provider Add form and the provider Edit form are one renderer
  (`core/provider_tui_form.render_wizard`) with two persistence paths, so
  the invariants that separate them live in different places. Edit locks
  the Name and API Key rows by **excluding them from the arrow-key focus
  cycle**, not by validating the field on save: any new row added to the
  form, or any new binding that sets `_wiz_focus` directly, can make a
  locked row reachable or writable. Edit also depends on saving with an
  empty models map and `replace_models=False` to leave loaded models on
  disk; passing the models map with replacement would silently drop every
  model the provider had fetched. Both are pinned by tests, and the
  name/key/delete identity rules belong in `provider_runtime`, not the
  TUI.
- `ProviderTUI` mirrors widget state onto `ProviderTUIState` through
  `_STATE_ATTRS`, but the mirroring is **one-way at render time**: a render
  that calls a `_sync_*_from_input()` helper copies the widget's text back
  over the state field. A state-only reset is therefore not a reset — the
  next paint undoes it. The model search `TextArea` outlives a selection
  session, so `begin_model_selection` clearing `model_search` left the
  selector reopening pre-filtered by the previous query, down to an empty
  list with nothing to tick. Session teardown must go through
  `ProviderTUI._begin_model_selection`, which clears widget and state
  together; the state method cannot reach the widget.
- The model selector shares one cursor between the model rows and the three
  action buttons, which live at indices `total`, `total + 1`, `total + 2`.
  Any list longer than a handful of models therefore buries its own actions:
  a real openrouter sync returned hundreds of models, so loading a ticked one
  cost one `↓` per model. This is invisible in tests that use a 3-model list
  and invisible in the panel's own rendering, because the buttons are always
  painted at the bottom. Two shortcuts must therefore stay: `L` reaches the
  action row, and `s`/`S` load from the current position without going there
  at all. They share `_ms_load_selected()` with the action row, so the
  "select at least one model" guard has a single home — a shortcut added
  beside `_do_save_models()` instead of through that helper would bypass it.
  Keep at least one test at realistic list length.
- Live host scrollback must use Prompt Toolkit's `run_in_terminal`
  handoff. Worker threads must never write directly to the TTY; complete
  lines stream live, partial lines flush once at close, and a failed host
  write must not advance the transcript flush cursor. Live flushes are
  debounced (at most one per `_HOST_FLUSH_MIN_INTERVAL_SECONDS`) and
  payloads are pre-wrapped with the host's real column count via
  `_wrap_host_payload` (`pawnlogic/live_terminal.py`): an erase cycle
  that assumes one row per logical line leaves residue on rows the host
  wrapped itself (wcwidth mismatch on CJK/emoji), which previously
  stacked into duplicated, interleaved scrollback. Tests pin the
  debounce interval behavior and the wide-glyph pre-wrap folding.
- Session scratch directories live under `~/.pawnlogic/sessions/`
  (`core/naming.py:stable_workspace_dir`); `~/.pawnlogic/workspace/`
  holds only auto-named task directories and `by-name/` aliases. The
  auto-naming swap (`core/session.py:_swap_workspace_dir`) promotes a
  session across roots with a relative reverse symlink so pre-swap
  absolute paths keep resolving. Do not reintroduce `session_<id>/`
  creation under `workspace/`.
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
- Steer semantics changed in P2-0 (ADR 0009 revision): Esc with queued
  work now discards the interrupted prompt's parked-draft path entirely
  (the queue takes over; empty-queue Esc still parks as a recovered
  draft). Client scripts or UI tests that relied on the interrupted
  prompt reappearing as an editable draft while a steer was queued will
  see the queued turn run instead — this is the intended contract, not a
  regression.
- The Dynamic E2E case
  `test_live_bare_escape_interrupts_one_turn_without_another_keypress`
  has shown a transient environment-sensitive flake in CI: the `pexpect`
  expectations for `Status: interrupted` (the 1.5 s
  `⏸ interrupted by user` post-Esc banner) and for the queued
  `Queued: 1 message(s)` row both use a 10 s window that sometimes
  times out on GitHub-hosted runners while passing locally and on the
  owner PTY. The publish workflow for `v0.3.7` saw this on
  `33973977545`; a re-run (`33974631898`) cleared it, and the same
  signature recurred on the `test/release-0.3.12` push run. The
  underlying PTY esc behavior is intact — this is a flake, not a
  product regression. Re-check before the next PyPI publish; the fix
  is to widen the window or split the test into "Esc → banner shows"
  vs "Esc → worker settles within N s" to isolate the signature.
- The typed-island module list is stated in three places (the CI mypy
  step, the pyproject overrides, and the Typed Island section).
  `tests/test_typed_island_sync.py` fails the build when they diverge;
  treat that failure as the gate, not as a test to relax.
- `pexpect.expect` compiles its pattern as a regex, so a literal string
  containing a metacharacter can never match. `"Press Ctrl+C again"` does
  not match that notice: `+` binds to the preceding `l`, so the pattern
  demands `Ctrl` + `l+` + `C` while the stream carries a literal `+`. The
  result is a timeout on a feature that is working perfectly, with the
  notice visible in `child.before`. Wrap any literal in `re.escape`. Two
  traps in the same helper: with `encoding="utf-8"`, assigning a **binary**
  file to `child.logfile_read` raises `TypeError` on the first read, so
  every later "the child printed nothing" reading is an artifact of the
  probe rather than of the product; and pexpect only reads the pty inside
  `expect`/`read`, so a `send` + `sleep` diagnostic captures nothing
  unless something is driving reads.
- A test that provokes `KeyboardInterrupt` or `SystemExit` in-process can
  abort the whole pytest session instead of failing. The exception unwinds
  out of the test, pytest stops doing further work, and the run exits **2**
  — but the summary line still reports only what already passed, so it
  reads like success. Measured on a full fast-suite run: **679 of 1727
  tests executed**, and the output said "679 passed". A regression touching
  a signal handler can therefore hide most of the suite behind one line of
  `!!! KeyboardInterrupt !!!`. Contain the provoked exception in the test
  (`_run_expecting_routed_interrupt` in `tests/test_live_sigint_teardown.py`
  does this via `pytest.fail`) so the regression becomes a normal, named
  failure. A fixture that only restores the previous handler is not enough
  — it runs *after* the yield, by which time the exception has escaped.
- Mutation-test each independent fix source; a suite that covers one does
  not cover the other. See the idle-Ctrl+C entries above: reverting only
  the `install_live_interrupt_handler` route left the headline e2e test
  green, because the pexpect PTY delivers `\x03` to the `c-c` binding
  instead. The suite as a whole was correct; only running the mutations
  separately showed which gate covers which source.

## Agent Workflow

For broad code changes:

1. Read `AGENT.md` (this file).
2. Read the active plan under `docs/plans/`.
3. Refresh the code index: `python tools/code_index.py build`
4. Use the index: `python tools/code_index.py symbol <name>` / `refs <name>`
5. Run narrow tests first, then wider validation before committing.
6. Update this file if the work changes architecture, contracts, or risks.
