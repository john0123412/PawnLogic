# 🤖 PawnLogic 1.1

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-WSL2%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)]()

> **A fully autonomous terminal AI agent** — multi-model routing, persistent memory, real tool execution, and session management. Built for developers and security researchers.

## ⚡ Quick Start

```bash
git clone https://github.com/john0123412/PawnLogic.git && cd PawnLogic
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py   # first run launches the API configuration wizard
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

## Provider Management

Add any third-party OpenAI-compatible API in seconds:

```bash
/provider              # open interactive TUI panel
/provider add <name> <base_url> [anthropic]   # register a provider
/provider fetch <name>   # auto-discover models with interactive multi-select
/provider update <name>  # re-fetch model list
/provider list           # show all providers and key status
/provider test <model>   # test connectivity
```

All keys are stored in `~/.pawnlogic/.env`. Provider configs (no keys) go to `~/.pawnlogic/custom_providers.json`.

## Supported Built-in Models

| Provider | Aliases | Best For |
|----------|---------|----------|
| DeepSeek | `ds-v4-flash` `ds-v4-pro` | Fast default, flagship reasoning |
| OpenAI | `gpt-4o` `gpt-4.1` `o3` | Vision, code, complex reasoning |
| Anthropic | `claude-sonnet` `claude-haiku` | Balanced, fast low-cost |

Custom providers added via `/provider fetch` appear automatically in `/model` and Tab completion.

## Quick Command Reference

```bash
/model [alias]          # switch model (only shows models with configured keys)
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

## Data Layout

```
~/.pawnlogic/
├── .env                    # API keys (never committed)
├── custom_providers.json   # user-added providers and models
├── pawn.db                 # sessions, messages, knowledge base
├── mcp_configs.json        # MCP server declarations
└── logs/                   # audit logs
```

## Installation

```bash
git clone https://github.com/john0123412/PawnLogic.git && cd PawnLogic
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Global `pawn` command:
```bash
chmod +x pawn.sh && ln -sf "$(pwd)/pawn.sh" ~/.local/bin/pawn
```

## Documentation

| Document | Description |
|----------|-------------|
| **README.md** | This page |
| **[README_CN.md](README_CN.md)** | 中文版 |
| **[GUIDE.md](GUIDE.md)** | Full reference — commands, architecture, FAQ |

## Support

- **GitHub**: [github.com/john0123412/PawnLogic](https://github.com/john0123412/PawnLogic)
- **Issues**: GitHub Issues for bugs and feature requests
