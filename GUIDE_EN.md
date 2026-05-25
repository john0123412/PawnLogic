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
| `gpt-4o`        | gpt-4o                      | Vision + multimodal        |
| `gpt-4.1`       | gpt-4.1                     | Code & instruction         |
| `o3`            | o3                          | Complex reasoning          |
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
- Detail view: update key, fetch models, test connectivity

**Option B — CLI**
```bash
/provider add myrelay https://api.myrelay.com/v1/chat/completions MYRELAY_API_KEY
/provider fetch myrelay    # interactive multi-select
/provider update myrelay   # re-fetch model list
/provider remove myrelay
```

**Base URL rules:**
- Ends with `/chat/completions` or `/messages` → used as-is
- Ends with `/v1` → appends endpoint suffix
- Bare domain → appends `/v1/chat/completions` or `/v1/messages`

### Model Visibility

`/model` and Tab completion only show models whose API key is configured.

---

## Installation

### WSL2 / Ubuntu (recommended)

```bash
git clone https://github.com/john0123412/PawnLogic.git && cd PawnLogic
python3 -m venv venv && source venv/bin/activate
pip install --upgrade pip && pip install -r requirements.txt
python main.py
```

The first run launches the configuration wizard automatically.

### Global `pawn` command

```bash
chmod +x pawn.sh
ln -sf "$(pwd)/pawn.sh" ~/.local/bin/pawn
```

### MCP Tools

```bash
cp mcp_configs.example.json ~/.pawnlogic/mcp_configs.json
# Edit mcp_configs.json and add keys to ~/.pawnlogic/.env
python main.py   # MCP servers load automatically
```

---

## API Key Setup

All keys are stored in `~/.pawnlogic/.env`. **No secrets in the project directory.**

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
| `/model [alias]` | Switch model (only shows configured) |
| `/mode` | Toggle USER / DEV output mode |
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

---

## Examples

### Add a third-party API

```
/provider add myrelay https://api.myrelay.com/v1/chat/completions MYRELAY_API_KEY
/provider fetch myrelay
# Select models with Space, confirm with Enter
/model myrelay/gpt-4o
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
├── main.py              # Entry point, REPL loop
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
└── skills/              # Local skill packs
```

### Runtime Data (`~/.pawnlogic/`)

```
~/.pawnlogic/
├── .env                    # API keys (never committed)
├── custom_providers.json   # Custom providers, no keys
├── pawn.db                 # SQLite database
├── mcp_configs.json        # MCP server declarations
├── workspace/              # Agent working directories
└── logs/                   # Audit logs
```

---

## FAQ

**Q: Added a provider but `/model` doesn't show new models?**  
A: Run `/provider fetch <name>` to pull the model list, then select models in the interactive prompt.

**Q: Test Connection fails but fetch succeeds?**  
A: Normal. `/v1/models` is a GET request that many relay services don't authenticate. As long as fetch works and the key is valid, actual usage is unaffected.

**Q: HTTP 305 after switching to a custom model?**  
A: Base URL format issue. Go to `/provider` → detail view → Update API Key to re-save. Or edit `~/.pawnlogic/custom_providers.json` directly.

**Q: How do I delete a specific custom model?**  
A: `/provider` → select provider → Enter → Manage Models → arrow keys → `D` to delete.

**Q: Where are my API keys stored?**  
A: `~/.pawnlogic/.env` — outside the project directory, never tracked by git.

**Q: Does it support local Ollama models?**  
A: Yes. Use `/provider add`, set Base URL to `http://localhost:11434`, leave the key empty or use any placeholder string.
