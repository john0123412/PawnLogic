# PawnLogic — Claude Code Instructions

Project-level guidance for Claude Code sessions working on this repo.

## Project at a Glance

- **What**: A fully autonomous terminal AI agent — multi-model routing, persistent memory, real tool execution.
- **Entry point**: `pawn` CLI command (`pawnlogic.cli:run` in `pyproject.toml`).
- **Runtime data**: lives in `~/.pawnlogic/` (sessions, db, env, custom providers). **Never** in the repo dir.
- **Build backend**: setuptools (PEP 517). `VERSION` defined only in `config/paths.py`.

## 🔒 Privacy Rules (Hard, Non-negotiable)

These exist because we shipped, then had to rewrite history and run a force-push to clean a leaked Linux username path. Don't make it happen again.

### Never commit any of the following:

1. **Absolute local filesystem paths** containing real usernames:
   - ❌ `/home/<username>/...`, `/Users/<username>/...`, `C:\Users\<username>\...`
   - ❌ `\\wsl.localhost\<distro>\home\<username>\...`
   - ✅ Use `${HOME}`, `~`, `$PWD`, or relative paths in all configs, scripts, and docker-compose files.
   - ✅ For docs/READMEs use placeholders like `<your-username>` or `~/.pawnlogic/...`.

2. **Anything matching the secrets section of `.gitignore`** (`.env*`, `*.key`, `*.pem`, `*.token`, etc.). The `.gitignore` is opt-out by design — if you add a new secrets-bearing file type, add it to `.gitignore` *first*, then create the file.

3. **Hostnames, machine names, network internals**:
   - ❌ `DESKTOP-XXXXX`, internal IPs, internal DNS names, VPN endpoints
   - ✅ `localhost`, `127.0.0.1`, public DNS only

4. **Commit messages containing leaked data**. `git-filter-repo --replace-message` is needed if a message itself leaks. Better: don't write the leaky message in the first place.

### Before every commit:

Run these grep checks against the staged diff (`git diff --cached`):

```bash
git diff --cached | grep -nE "/home/[^/ ]+/|/Users/[^/ ]+/|C:\\\\Users\\\\" && echo "❌ local path leak"
git diff --cached | grep -nE "DESKTOP-[A-Z0-9-]+|\.local\b|\.lan\b"          && echo "❌ hostname leak"
git diff --cached | grep -nE "sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{50,}|tp-[a-z0-9]{30,}" && echo "❌ token leak"
```

If any of these matches, **stop and fix** before committing — even if `--no-verify` would let it through.

### When configuring docker-compose / scripts:

- Default values should never be a real path. Prefer:
  - `env_file: .env.smoke` (relative, plus `.gitignore`-protected via `.env.*`)
  - `volumes: ./custom_providers.smoke.json:/app/...` (relative)
  - Document setup as `ln -s ~/.pawnlogic/.env .env.smoke` in CONTRIBUTING.md.
- For CI: write secrets to relative paths at runtime, never commit them.

## Standard Workflow

### Running tests

```bash
PAWNLOGIC_HOME="$(mktemp -d)" PAWNLOGIC_TEST_MODE=true \
  venv/bin/python -m pytest tests/ -v --timeout=60
```

`PAWNLOGIC_TEST_MODE=true` skips the first-run wizard.
`PAWNLOGIC_HOME` to a fresh tmpdir keeps tests from polluting `~/.pawnlogic/`.

### Building / publishing

```bash
rm -rf dist/ build/
venv/bin/python -m build
venv/bin/python -m twine check dist/*
```

Tag push `v[0-9]+.[0-9]+.[0-9]*` triggers `.github/workflows/publish.yml` → real PyPI.
`workflow_dispatch` on publish.yml supports `target=testpypi` for dry-run.

### Docker smoke (hits a real provider API)

```bash
ln -s ~/.pawnlogic/.env .env.smoke
ln -s ~/.pawnlogic/custom_providers.json custom_providers.smoke.json
docker compose -f docker-compose.test.yml run --rm smoketest
docker compose -f docker-compose.test.yml run --rm interactive-smoke
docker compose -f docker-compose.test.yml down --volumes --remove-orphans
```

`.env.smoke` and `custom_providers.smoke.json` are gitignored. Each run consumes real tokens.

### Version bump

The **only** place version lives: `config/paths.py:VERSION`. Then update:
- `README.md` + `README_CN.md` version badge
- `SECURITY.md` Supported Versions table
- New `[X.Y.Z]` section in `CHANGELOG.md`

`pyproject.toml` reads `VERSION` dynamically via `[tool.setuptools.dynamic]` — don't hardcode there.

## Known Architectural Pitfalls

1. **Source-tree `main.py` compatibility wrapper**: installed wheels no longer expose a top-level `main` module; `pawn` targets `pawnlogic.cli:run`. The repository still keeps root `main.py` so `python main.py`, `pawn.sh`, and older tests keep working in a checkout.

2. **`first_run` gate must use `_has_any_api_key()` alone** (not `_ENV_PATH.exists()`). Custom providers from `custom_providers.json` are merged into `PROVIDERS` at module-import time, so the gate treats them on equal footing — no provider name is or should be hardcoded. See regression tests in `tests/test_deployment_friendly.py::test_first_run_gate_*`.

3. **`config.providers` import has side effects**: `load_custom_providers()` runs at module load time (`config/providers.py:312`). Any code that needs custom providers visible just needs to `import config.providers` before the check.

4. **`conftest.py` force-caches `config` package**: there's `sys.modules` black magic at the top to prevent tests that mock `sys.modules["config"]` from poisoning other tests. Don't simplify it unless you've audited every test.

5. **Workflow trigger scope**: `main_ci.yml` triggers on `main`, `chore/**`, `test/**`, and `workflow_dispatch`. `publish.yml` triggers on tag push matching `v[0-9]+.[0-9]+.[0-9]*` or `workflow_dispatch`. If you add a new branch convention, add it to the trigger list.

## Useful Repo Map

- `main.py` — top-level entry. Contains `main()` async loop + `run()` sync wrapper + first-run gate + arg parsing.
- `config/` — declarative only (paths, providers, security policies, model registry). No business logic.
- `core/` — agentic loop, persistence, memory, MCP, commands. Most behavior changes here.
- `tools/` — pluggable agent tools (shell, file ops, sandbox, vision, recon, pwn). Add new files; don't break existing signatures.
- `utils/` — small shared helpers (ANSI, key masking).
- `skills/` — markdown skill packs. `skills/ctf_*/` excluded from default wheel; install via `pip install pawnlogic[ctf]`.
- `tests/` — pytest suite. Subprocess-based deployment tests in `test_deployment_friendly.py`.
- `.github/workflows/main_ci.yml` and `publish.yml` — CI / release.
- `docker-compose.test.yml` + `Dockerfile.test` + `.dockerignore` — smoke harness, see CONTRIBUTING.md.

## Quick Sanity Commands

```bash
# Lint
venv/bin/python -m ruff check .

# Test
PAWNLOGIC_HOME=$(mktemp -d) PAWNLOGIC_TEST_MODE=true venv/bin/python -m pytest tests/ -q --timeout=60

# Build + metadata check
rm -rf dist/ build/ && venv/bin/python -m build && venv/bin/python -m twine check dist/*

# Verify wheel excludes ctf skills
venv/bin/python -m zipfile -l dist/*.whl | grep -ic skills/ctf  # should print 0
```
