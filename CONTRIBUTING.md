# Contributing to PawnLogic

Thank you for your interest in contributing! Please read this guide before opening a PR.

## Development Setup

```bash
git clone https://github.com/john0123412/PawnLogic.git && cd PawnLogic
python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests

```bash
PAWNLOGIC_HOME="$(mktemp -d)" venv/bin/python -m pytest tests/ -v
```

## Docker Smoke Test (optional, hits a real provider)

```bash
# One-time symlink your real env + custom providers
ln -s ~/.pawnlogic/.env .env.smoke
ln -s ~/.pawnlogic/custom_providers.json custom_providers.smoke.json

# Non-interactive (asserts the model replies "pawnlogic-smoke-ok")
docker compose -f docker-compose.test.yml run --rm smoketest

# Scripted interactive flow (/help + /keys + one prompt + /exit)
docker compose -f docker-compose.test.yml run --rm interactive-smoke

# Clean up containers (keep image cached)
docker compose -f docker-compose.test.yml down --volumes --remove-orphans
```

`.env.smoke` and `custom_providers.smoke.json` are in `.gitignore`/`.dockerignore`. Each smoke run consumes real API tokens.

## Adding an API Provider

**Option A — Runtime (recommended, no code change needed):**

```bash
/provider add my-relay https://api.example.com/v1/chat/completions MY_API_KEY
/provider fetch my-relay   # fetch available models and select interactively
/provider activate my-relay
```

Keys are written to `~/.pawnlogic/.env`. Provider configs go to `~/.pawnlogic/custom_providers.json`. Custom providers are inactive by default; activate only the providers whose fetched models should appear in `/model`. Neither file is committed.

**Option B — Built-in (for PRs):**

1. Add an entry to `PROVIDERS` in `config/providers.py`
2. Add model aliases to `MODELS` in the same file
3. Add `XXX_API_KEY=` placeholder to `.env.example`
4. PR title: `feat(providers): add <name>`

## Adding an MCP Tool

1. Add the server declaration to `mcp_configs.example.json`
2. Add any required key placeholder to `.env.example`
3. PR title: `feat(mcp): add <name>`

## Module Boundaries

| Module | Rule |
|--------|------|
| `core/session.py` | Agentic loop core — changes require tests |
| `tools/` | Add new files; do not modify existing tool signatures |
| `config/` | Config declarations only, no business logic |
| `config/paths.py` | **Only place to change the version number** |

## Commit Convention

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(scope): short description
fix(scope): short description
refactor / docs / chore / test
```

## Pull Request Checklist

- [ ] `python -m py_compile` passes on all modified files
- [ ] `PAWNLOGIC_HOME="$(mktemp -d)" venv/bin/python -m pytest tests/` passes
- [ ] No secrets or API keys committed
- [ ] PR description filled in (use the template)
