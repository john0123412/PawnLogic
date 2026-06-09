**[English](README.md)** | [中文](README_CN.md)

# 🤖 PawnLogic

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/pypi/v/pawnlogic.svg?label=version)](https://pypi.org/project/pawnlogic/)
[![PyPI](https://img.shields.io/pypi/v/pawnlogic.svg?cache=no)](https://pypi.org/project/pawnlogic/)
[![CI](https://github.com/john0123412/PawnLogic/actions/workflows/main_ci.yml/badge.svg)](https://github.com/john0123412/PawnLogic/actions/workflows/main_ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20WSL2-lightgrey.svg)]()

> **A fully autonomous terminal AI agent** — multi-model routing, persistent memory, real tool execution, and session management. Built for developers and security researchers.

## System Requirements

- Linux or WSL2
- Python 3.10+
- `pip`
- `git` only for source checkout or development
- `~/.local/bin` in `PATH` if you want the global `pawn` command

## ⚡ Quick Start

**Option A — pip install (recommended)**
```bash
pip install pawnlogic
pawn   # first run launches the API configuration wizard
```

**Option B — one-line installer**
```bash
curl -fsSL https://raw.githubusercontent.com/john0123412/PawnLogic/main/install.sh | bash
pawn
```

The installer creates an isolated venv under `~/.local/share/pawnlogic`, installs
the official `pawnlogic` package with pip, and writes a `~/.local/bin/pawn`
launcher. It does not copy the source tree or store runtime data in the project.

**Option C — from source for development**
```bash
git clone https://github.com/john0123412/PawnLogic.git && cd PawnLogic
python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
pawn             # first run launches the API configuration wizard
```

**Optional CTF skill pack** (pwntools / ROPgadget / ropper + the `skills/ctf_*` markdown):
```bash
pip install "pawnlogic[ctf]"       # package install
pip install -e ".[ctf]"            # source checkout
```

Source-checkout launcher fallback:
```bash
./pawn.sh
```
If `pawn` is not found after package or installer setup, run
`export PATH="$HOME/.local/bin:$PATH"` and add that line to your shell profile.

**CLI usage:**
```bash
pawn                              # interactive mode
pawn --eval "your prompt"         # single execution then exit
pawn --eval "prompt" --json       # JSON output (for scripting)
```

## What's New

See [CHANGELOG.md](CHANGELOG.md) for the full version history.

## Key Capabilities

| Capability | Description |
|-----------|-------------|
| 🔀 **Dynamic Provider System** | Built-in DeepSeek / OpenAI / Anthropic + add any OpenAI-compatible API via `/provider` |
| 🧠 **Persistent Memory** | SQLite session history, RAG knowledge base, cross-session full-text search |
| 🛠️ **Real Tool Execution** | Shell, code sandbox (8 languages), web fetch, file ops, Docker containers |
| 👁️ **Vision** | Feed screenshots to `gpt-4o` or `claude-sonnet` for analysis |
| 📋 **Spec-Driven Planning** | Agent outputs `<plan>` XML before every action — no blind execution |
| 💬 **Session Management** | Tag, search, link, and export conversations with `/chat` commands |
| 🔐 **CTF / Pwn Toolchain** | GDB automation, ROP chain building, libc leak resolution, Docker isolation |

## Supported Models

| Provider | Aliases | Best For |
|----------|---------|----------|
| DeepSeek | `ds-v4-flash` `ds-v4-pro` | Fast default, flagship reasoning |
| OpenAI | `gpt-5.5` `gpt-5.4` `gpt-5.4-mini` `gpt-5.4-nano` `gpt-4o` `gpt-4.1` `o3` | Flagship, coding, vision, reasoning |
| Anthropic | `claude-opus` `claude-sonnet` `claude-haiku` | Frontier reasoning, balanced, fast |

DeepSeek is active by default. Custom providers appear in `/model` and Tab completion only after their key is configured, models are fetched, and the provider is activated.

## Provider Management

```bash
/provider              # open interactive TUI panel
/provider add <name> <base_url> <ENV_KEY> [anthropic]
/provider fetch <name> # fetch available models and select interactively
/provider update <name>
/provider activate <name>
/provider deactivate <name>
/provider list         # show all providers and key status
/provider test <model> # test connectivity
```

All keys are stored in `~/.pawnlogic/.env`. Provider configs (no keys) go to `~/.pawnlogic/custom_providers.json`.

## Quick Command Reference

```bash
/model [alias]          # switch model, showing active configured providers
/mode                   # toggle USER / DEV output mode
/chat find <keyword>    # full-text search across all sessions
/think <prompt>         # single deep-reasoning turn
/compact                # summarize + clear context
/undo [n]               # roll back last n turns
/deep                   # switch to deep mode (32k tokens, 50 iter)
/init_project           # initialize GSD engineering pipeline
/pwnenv                 # check CTF toolchain integrity
/keys                   # show API key status for all providers
```

## MCP Tool Integration

For pip or one-line installer users, PawnLogic creates editable templates in
`~/.pawnlogic/` on startup:

```bash
pawn   # creates ~/.pawnlogic/env.example and ~/.pawnlogic/mcp_configs.example.json
cp ~/.pawnlogic/mcp_configs.example.json ~/.pawnlogic/mcp_configs.json
# edit ~/.pawnlogic/mcp_configs.json, add TAVILY_API_KEY= etc. with /setkey or ~/.pawnlogic/.env
pawn   # MCP servers load automatically when mcp_configs.json exists
```

For source checkout users, the repository template can also be copied directly:

```bash
cp mcp_configs.example.json ~/.pawnlogic/mcp_configs.json
```

Supported MCP servers: **Tavily** (search), **Playwright** (browser automation), **Filesystem** (file bridge).
The example keeps the external `fetch` MCP disabled by default because `uvx mcp-server-fetch`
may contact PyPI during startup. Use PawnLogic's built-in `fetch_url` unless you explicitly
enable that MCP server and allow network installation.

## Data Layout

All runtime data and API keys are stored in `~/.pawnlogic/` — **never in the project directory**.

```
~/.pawnlogic/
├── .env                    # ALL API keys (LLM providers + MCP tools)
├── custom_providers.json   # user-added provider configs (no keys)
├── mcp_configs.json        # MCP server declarations
├── pawn.db                 # sessions, messages, knowledge base
├── global_skills.md        # GSA skill archive
├── workspace/              # per-session working directories
└── logs/                   # audit logs
```

The project directory contains no secrets and is safe to commit or share.

## Documentation

| Document | Description |
|----------|-------------|
| [**README.md**](README.md) | This page |
| [**README_CN.md**](README_CN.md) | 中文版 |
| [**GUIDE_EN.md**](GUIDE_EN.md) | Full reference — commands, architecture, FAQ |
| [**GUIDE_CN.md**](GUIDE_CN.md) | 完整参考手册 — 命令、架构、常见问题 |
| [**CHANGELOG.md**](CHANGELOG.md) | Version history and release notes |
| [**CONTRIBUTING.md**](CONTRIBUTING.md) | How to contribute, add providers, run tests |
| [**SECURITY.md**](SECURITY.md) | Vulnerability reporting policy |

## Support

- **GitHub**: [github.com/john0123412/PawnLogic](https://github.com/john0123412/PawnLogic)
- **Issues**: GitHub Issues for bugs and feature requests
