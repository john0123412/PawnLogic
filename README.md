# 🤖 PawnLogic

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.1-blue.svg)](config/paths.py)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20WSL2-lightgrey.svg)]()

> **A fully autonomous terminal AI agent** — multi-model routing, persistent memory, real tool execution, and session management. Built for developers and security researchers.

## ⚡ Quick Start

```bash
git clone https://github.com/john0123412/PawnLogic.git && cd PawnLogic
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py   # first run launches the API configuration wizard
```

Global `pawn` command:
```bash
chmod +x pawn.sh && ln -sf "$(pwd)/pawn.sh" ~/.local/bin/pawn
```

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
| OpenAI | `gpt-4o` `gpt-4.1` `o3` | Vision, code, complex reasoning |
| Anthropic | `claude-sonnet` `claude-haiku` | Balanced, fast low-cost |

Custom providers added via `/provider fetch` appear automatically in `/model` and Tab completion.

## Provider Management

```bash
/provider              # open interactive TUI panel
/provider add <name> <base_url> <ENV_KEY> [anthropic]
/provider fetch <name> # auto-discover models with interactive multi-select
/provider list         # show all providers and key status
/provider test <model> # test connectivity
```

All keys are stored in `~/.pawnlogic/.env`. Provider configs (no keys) go to `~/.pawnlogic/custom_providers.json`.

## Quick Command Reference

```bash
/model [alias]          # switch model
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

```bash
cp mcp_configs.example.json ~/.pawnlogic/mcp_configs.json
# edit mcp_configs.json, add TAVILY_API_KEY= etc. to ~/.pawnlogic/.env
python main.py   # MCP servers load automatically
```

Supported MCP servers: **Tavily** (search), **Playwright** (browser automation), **Filesystem** (file bridge).

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
| **README.md** | This page |
| **README_CN.md** | 中文版 |
| **GUIDE_EN.md** | Full reference — commands, architecture, FAQ |
| **GUIDE_CN.md** | 完整参考手册 — 命令、架构、常见问题 |

## Support

- **GitHub**: [github.com/john0123412/PawnLogic](https://github.com/john0123412/PawnLogic)
- **Issues**: GitHub Issues for bugs and feature requests
