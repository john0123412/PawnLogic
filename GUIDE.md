# PawnLogic — Full Reference Guide

> Complete reference for commands, models, architecture, and FAQ.

---

## Table of Contents

1. [Feature Overview](#feature-overview)
2. [Providers & Models](#providers--models)
3. [Installation](#installation)
4. [API Key Setup](#api-key-setup)
5. [Command Reference](#command-reference)
6. [Examples](#examples)
7. [Architecture](#architecture)
8. [FAQ](#faq)

---

## Feature Overview

### 1. Session Management

| Command | Description |
|---------|-------------|
| `/chat list [n]` | List recent n sessions (default 20) |
| `/chat view <id\|n>` | View full conversation |
| `/chat export <id\|n> [path]` | Export to Markdown |
| `/chat find <keyword>` | Full-text search across all sessions |
| `/chat tag <id\|n> <tags>` | Tag a session (comma-separated) |
| `/chat untag <id\|n> <tags>` | Remove tags |
| `/chat bytag <tag>` | Filter sessions by tag |
| `/chat link <id1> <id2>` | Link two sessions |
| `/chat related <id\|n>` | View linked sessions |

### 2. Auto-Naming & Dynamic Workspace

- **Auto-naming** — after turn 2, the agent generates a semantic session name (e.g. `ctf-heap-exploit`)
- **Dynamic workspace** — each session gets `~/.pawnlogic/workspace/session_<ts>_<hash>/`
- **Atomic swap** — workspace rename + symlink + DB update in one operation

### 3. UX

- **Ctrl+C** — cancels current input and rolls back the last turn (Claude Code style)
- **Ctrl+D** — clean exit
- **Interrupt generation** — Ctrl+C during agent output stops immediately

### 4. Spec-Driven Planning (GSD)

- Agent must emit a `<plan>` XML block with `<action>` and `<verify>` before any tool call
- `/init_project [desc]` — create `.pawn_state.md` in current directory
- `/state` — view current `.pawn_state.md`

### 5. Context Management

- **Sliding window** — auto-summarizes old history to prevent API timeouts
- `/compact` — manually compress context
- `/clear` — clear context, keep pinned messages
- `/pin [n]` — pin last n messages (default 2)
- `/context` — show context size and token estimate

### 6. Knowledge Base RAG

- `/memorize [topic]` — AI summarizes conversation → saves to knowledge base
- `/knowledge [query]` — search or list knowledge entries
- `/forget <id>` — delete a knowledge entry

---

## Providers & Models

### Built-in Providers

| Provider  | Env Var              | Format    |
|-----------|----------------------|-----------|
| DeepSeek  | `DEEPSEEK_API_KEY`   | OpenAI    |
| OpenAI    | `OPENAI_API_KEY`     | OpenAI    |
| Anthropic | `ANTHROPIC_API_KEY`  | Anthropic |

### Built-in Model Aliases

| Alias           | Model ID                    | Notes                      |
|-----------------|-----------------------------|----------------------------|
| `ds-v4-flash`   | deepseek-v4-flash           | Default, fast & cheap      |
| `ds-v4-pro`     | deepseek-v4-pro             | Flagship reasoning         |
| `gpt-5.5`       | gpt-5.5                     | OpenAI latest flagship     |
| `gpt-5.4`       | gpt-5.4                     | Coding & professional      |
| `gpt-5.4-mini`  | gpt-5.4-mini                | Lightweight & efficient    |
| `gpt-5.4-nano`  | gpt-5.4-nano                | Lowest-cost OpenAI model   |
| `gpt-4o`        | gpt-4o                      | Vision + multimodal        |
| `gpt-4.1`       | gpt-4.1                     | Code & instruction         |
| `o3`            | o3                          | Complex reasoning          |
| `claude-opus`   | claude-opus-4-6             | Frontier reasoning         |
| `claude-sonnet` | claude-sonnet-4-6           | Balanced                   |
| `claude-haiku`  | claude-haiku-4-5-20251001   | Fast & cheap               |

### Adding a Custom Provider

**Option A — Interactive TUI (recommended)**
```
/provider
```
- Arrow keys to navigate, Enter for details
- `N` — add new provider
- `D` — delete provider
- Detail view: update key, activate/deactivate, fetch models, test connectivity, manage models

**Option B — CLI**
```bash
/provider add myrelay https://api.myrelay.com/v1/chat/completions MYRELAY_API_KEY
/provider fetch myrelay    # interactive multi-select
/provider activate myrelay # make selected models visible in /model
/provider update myrelay   # re-fetch model list
/provider remove myrelay
```

**Base URL rules:**
- Ends with `/chat/completions` or `/messages` → used as-is
- Ends with `/v1` → appends endpoint suffix
- Bare domain → appends `/v1/chat/completions` or `/v1/messages`

### Model Visibility

`/model` and Tab completion only show DeepSeek plus providers that are active and have a configured API key. Custom providers are inactive by default; run `/provider activate <name>` after fetching the models you want. Custom model descriptions are loaded from `~/.pawnlogic/custom_providers.json`; fetched models receive an English fallback description when the provider does not supply one.

---

## Installation

### Requirements

- Linux or WSL2
- Python 3.10+
- `pip`
- `git` only for source checkout or development
- `~/.local/bin` in `PATH` for the global `pawn` command

### WSL2 / Ubuntu (recommended)

Package install:

```bash
pip install pawnlogic
pawn
```

One-line installer:

```bash
curl -fsSL https://raw.githubusercontent.com/john0123412/PawnLogic/main/install.sh | bash
pawn
```

The installer creates `~/.local/share/pawnlogic/venv`, installs the official
package with pip, and writes `~/.local/bin/pawn`.

Source checkout for development:

```bash
git clone https://github.com/john0123412/PawnLogic.git && cd PawnLogic
python3 -m venv venv && source venv/bin/activate
pip install --upgrade pip && pip install -e ".[dev]"
pawn
```

The first run launches the configuration wizard automatically.

### Runtime Output Modes

```bash
pawn                              # interactive user-friendly mode
pawn --debug                      # interactive mode with detailed diagnostics
pawn --eval "your prompt"         # single execution then exit
pawn --eval "prompt" --json       # machine-readable JSON output
```

Default `pawn` hides raw tool-call arguments, parser diagnostics, detailed API
errors, and reasoning streams. It may show concise status such as `Thinking...`
or a short tool progress line. Use `pawn --debug` when troubleshooting provider
connectivity, parser behavior, tool-call arguments, or low-level API failures.
`--json` is for scripting output with `--eval`; it is not the debug display
mode. During an interactive session, `/mode` toggles between user-friendly and
debug output.

### Host Shell Operation Policy

PawnLogic is not a sandbox. Host shell commands still execute with the current
user's permissions, but `run_shell` now evaluates an operation policy before
starting a subprocess. Low-risk commands are allowed, medium-risk commands are
allowed with audit classification, high-risk commands require explicit
interactive confirmation, and critical commands are denied by default.
Non-interactive execution, including `pawn --eval`, fails closed when a
high-risk command would require confirmation.

The policy covers high-risk shell redirection outside the workspace, `tee`,
`dd of=...`, in-place `sed`/`perl`, `find -delete`, `xargs rm`, `rm -rf`,
recursive `chmod`/`chown`, download-pipe-shell commands, and obvious reverse
or bind shell patterns. Critical denials include credential paths such as
`~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.kube`, `~/.pawnlogic/.env`, Docker sockets,
and protected system write paths. `DANGEROUS_PATTERNS` is retained only as a
misuse/risk classifier and is not a security boundary.

### Source-checkout launcher fallback

```bash
./pawn.sh
```

If `pawn` is not found, run:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Optional CTF Skill Packs

Install CTF tool dependencies with:

```bash
pip install "pawnlogic[ctf]"
```

This extra installs tooling dependencies such as `pwntools`, `ROPgadget`, and
`ropper`; it does not install third-party skill-pack Markdown into the PyPI
package. CTF skill packs are optional extension assets. Install them explicitly
into `~/.pawnlogic/skills`, for example:

```bash
/sp install <repo_url>
```

Git-backed skill-pack installs accept only `https://`, `ssh://`, or
`git@host:owner/repo.git` remotes.

Only redistribute third-party CTF skill content from this repository after the
upstream license, source URL, commit, and required notices have been recorded in
`THIRD_PARTY_NOTICES.md`.
Skill-pack manifests are runtime discovery metadata only; they do not authorize
redistribution by themselves.

### MCP Tools

For pip or one-line installer users, PawnLogic creates editable templates in
`~/.pawnlogic/` on startup:

```bash
pawn   # creates ~/.pawnlogic/env.example and ~/.pawnlogic/mcp_configs.example.json
cp ~/.pawnlogic/mcp_configs.example.json ~/.pawnlogic/mcp_configs.json
# Edit ~/.pawnlogic/mcp_configs.json and add keys with /setkey or ~/.pawnlogic/.env
pawn   # MCP servers load automatically when mcp_configs.json exists
```

For source checkout users, the repository template can also be copied directly:

```bash
cp mcp_configs.example.json ~/.pawnlogic/mcp_configs.json
```

The example keeps the external `fetch` MCP disabled by default because
`uvx mcp-server-fetch` may contact PyPI during startup. Use PawnLogic's built-in
`fetch_url` unless you explicitly enable that MCP server and allow network installation.

MCP subprocess stderr is written to `~/.pawnlogic/logs/mcp/<server>.stderr.log`
by default so server startup banners do not appear in the main terminal. Set
top-level `"debug_stderr": true` in `mcp_configs.json` to show raw MCP stderr
while troubleshooting. PawnLogic advertises MCP roots for the current working
directory and `~/.pawnlogic/workspace`.

---

## API Key Setup

All keys are stored in `~/.pawnlogic/.env`. **No secrets in the project directory.**
For pip or one-line installer users, `pawn` creates `~/.pawnlogic/env.example`
as an editable template. You can either run the first-run wizard, run `/setkey`,
or copy the template manually. Provider setup does not write keys into shell
startup files:

```bash
cp ~/.pawnlogic/env.example ~/.pawnlogic/.env
chmod 600 ~/.pawnlogic/.env
```

```bash
# LLM providers
DEEPSEEK_API_KEY=sk-...
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# MCP tools
TAVILY_API_KEY=tvly-...

# Custom providers (written by wizard)
MYRELAY_API_KEY=...
```

`mcp_configs.json` references keys via `${VAR_NAME}`, keeping configs and secrets decoupled.

Check key status at runtime: `/keys`

---

## Command Reference

### Conversation Control

| Command | Description |
|---------|-------------|
| `/model [alias]` | Switch model (only shows active providers with configured keys) |
| `/mode` | Toggle user-friendly/debug output |
| `/clear` | Clear context, keep pins |
| `/context` | Context size + token estimate |
| `/pin [n]` | Pin last n messages |
| `/unpin` | Unpin all |
| `/undo [n]` | Roll back last n turns |
| `/compact` | Summarize + compress context |
| `/think <prompt>` | Single deep-reasoning turn |
| `/cd <path>` | Change working directory |
| `/file <path>` | Load file into context |
| `/history` | Message history with sequence numbers |

### Provider Management

| Command | Description |
|---------|-------------|
| `/provider` | Open interactive TUI |
| `/provider list` | List all providers |
| `/provider add <name> <url> <KEY>` | Register provider |
| `/provider fetch <name>` | Fetch model list |
| `/provider update <name>` | Re-fetch model list |
| `/provider activate <name>` | Show this provider's selected models in `/model` |
| `/provider deactivate <name>` | Hide this provider's models from `/model` |
| `/provider remove <name>` | Delete custom provider |
| `/provider test <model>` | Test connectivity |
| `/keys` | Show all key status |
| `/setkey` | Re-run key wizard |

### Session Persistence

| Command | Description |
|---------|-------------|
| `/save [name]` | Save current session |
| `/load <name\|n>` | Load session |
| `/sessions` | List all sessions |
| `/del <name\|n>` | Delete session |
| `/rename <n> <name>` | Rename session |
| `/resume [n]` | Resume session with history |

### Compute Tiers

| Command | Tokens | Ctx  | Iter | Use Case     |
|---------|--------|------|------|--------------|
| `/low`  | 4k     | 40k  | 10   | Daily        |
| `/mid`  | 8k     | 150k | 30   | Dev (default)|
| `/deep` | 32k    | 400k | 50   | Full power   |
| `/max`  | 32k    | 600k | 100  | Extreme      |

### Tool Status

| Command | Description |
|---------|-------------|
| `/webstatus` | Jina / Pandoc / Lynx status |
| `/pwnenv` | CTF toolchain integrity check |
| `/docker` | Docker container management |
| `/stats` | Session token usage |

Docker file mounts are workspace-bound by default, including read-only mounts.
Outside read-only challenge files require explicit `allow_host_read_mount`.

### CTF Workflow

| Command | Description |
|---------|-------------|
| `/ctf init <name>` | Initialize CTF metadata in the active workspace |
| `/ctf status` | Show active CTF metadata |
| `/ctf artifact <path-or-note>` | Record a challenge artifact |
| `/ctf remote <host:port-or-url>` | Record a remote target |
| `/ctf flag <candidate>` | Record a flag candidate |
| `/ctf solved [confirmed-flag]` | Mark the challenge solved after confirming a flag |
| `/ctf writeup` | Export a Markdown writeup draft |

---

## Examples

### Add a third-party API

```
/provider add myrelay https://api.myrelay.com/v1/chat/completions MYRELAY_API_KEY
/provider fetch myrelay
# Select models with Space, confirm with Enter
/provider activate myrelay
/model <alias shown by /provider fetch>
```

### Vision analysis

```
Analyze screenshot ./screenshot.png, extract the code and fix the bug.
```

### CTF Pwn

```
/model ds-v4-pro
Analyze ./challenge, use pwn_debug to inspect registers at main breakpoint.
```

### GSD project workflow

```
/init_project Build a CLI JSON formatter
→ Agent: plan → write → verify → git commit
```

---

## Architecture

### Code Structure

```
PawnLogic/
├── main.py              # Thin source-checkout compatibility wrapper
├── pawnlogic/cli.py     # Single CLI runtime used by pawn and python -m pawnlogic
├── config/
│   ├── paths.py         # ★ VERSION defined here
│   ├── providers.py     # Provider & model registry
│   ├── tiers.py         # Compute tier presets
│   ├── security.py      # Safety patterns & blacklists
│   ├── sandbox.py       # Sandbox config
│   └── phases.py        # MoE tool routing
├── core/
│   ├── session.py       # Agentic Loop
│   ├── memory.py        # SQLite persistence
│   ├── api_client.py    # Dual-format API client
│   ├── naming.py        # Auto-naming & workspace
│   └── provider_tui.py  # Provider TUI
├── tools/               # Tool implementations
└── skills/              # Source-checkout skill packs (not shipped in PyPI wheels)
```

### Runtime Data (`~/.pawnlogic/`)

```
~/.pawnlogic/
├── .env                    # API keys (never committed)
├── custom_providers.json   # Custom providers, no keys
├── pawn.db                 # SQLite database
├── mcp_configs.json        # MCP server declarations
├── skills/                 # Optional user-installed skill packs
├── workspace/              # Agent working directories
└── logs/                   # Audit logs
```

---

## FAQ

**Q: Added a provider but `/model` doesn't show new models?**  
A: Configure its key, run `/provider fetch <name>`, select models in the prompt, then run `/provider activate <name>`. `/model` hides inactive providers.

**Q: Test Connection fails but fetch succeeds?**  
A: Fetch only reads `/v1/models`; Test Connection sends a minimal chat request using a loaded chat model. If no chat model is loaded yet, fetch first. If it still fails, the selected model, key, or base URL is not accepted by that provider.

**Q: HTTP 305 after switching to a custom model?**  
A: Base URL format issue. Go to `/provider` → detail view → Update API Key to re-save. Or edit `~/.pawnlogic/custom_providers.json` directly.

**Q: How do I delete a specific custom model?**  
A: `/provider` → select provider → Enter → Manage Models → arrow keys → `D` to delete.

**Q: Where are my API keys stored?**  
A: `~/.pawnlogic/.env` — outside the project directory, never tracked by git.

**Q: `pawn` says command not found after install?**  
A: Add the user bin directory to PATH: `export PATH="$HOME/.local/bin:$PATH"`.

**Q: Startup says Python 3.10+ is required?**  
A: Install a newer Python and recreate the virtual environment with that interpreter.

**Q: Browser tools say a module is missing?**  
A: Install the optional browser extra: `pip install 'pawnlogic[browser]'`, then run `patchright install chromium`.

**Q: WSL2 has strange PATH/tool detection issues?**  
A: Start PawnLogic from the Linux filesystem, not `/mnt/c/...`, and keep Linux tool paths before Windows paths.

**Q: Does it support local Ollama models?**  
A: Yes. Use `/provider add`, set Base URL to `http://localhost:11434`, leave the key empty or use any placeholder string.
