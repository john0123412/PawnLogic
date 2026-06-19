**[English](README.md)** | [Chinese](README_CN.md)

# PawnLogic

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/pypi/v/pawnlogic.svg?label=version)](https://pypi.org/project/pawnlogic/)
[![PyPI](https://img.shields.io/pypi/v/pawnlogic.svg?cache=no)](https://pypi.org/project/pawnlogic/)
[![CI](https://github.com/john0123412/PawnLogic/actions/workflows/main_ci.yml/badge.svg)](https://github.com/john0123412/PawnLogic/actions/workflows/main_ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20WSL2-lightgrey.svg)]()

PawnLogic is a terminal-first autonomous AI agent with multi-provider model
routing, persistent memory, real local tool execution, MCP integration, and a
CTF-oriented toolchain. The current source release is **0.1.3**; publication
to PyPI and GitHub Releases should happen only after release approval.

## System Requirements

- Linux or WSL2
- Python 3.10+
- `pip`
- `git` only for source checkouts, development, or git-backed skill packs
- `~/.local/bin` in `PATH` when using the global `pawn` launcher
- Optional: Docker for container tools, browser dependencies for Patchright /
  Scrapling, and CTF packages for pwn workflows

## Quick Start

**Option A: install from PyPI**

```bash
pip install pawnlogic
pawn
```

The first run opens the API key configuration flow. Runtime files are created
under `~/.pawnlogic/`, not inside the project directory.

**Option B: one-line installer**

```bash
curl -fsSL https://raw.githubusercontent.com/john0123412/PawnLogic/main/install.sh | bash
pawn
```

The installer creates an isolated venv under `~/.local/share/pawnlogic`,
installs the official PyPI package, and writes `~/.local/bin/pawn`.

**Option C: source checkout for development**

```bash
git clone https://github.com/john0123412/PawnLogic.git
cd PawnLogic
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
pawn
```

Optional extras:

```bash
pip install "pawnlogic[docker]"    # Docker SDK integration
pip install "pawnlogic[browser]"   # Scrapling + Patchright browser tools
pip install "pawnlogic[ctf]"       # pwntools, ROPgadget, ropper
pip install -e ".[dev,ctf]"        # source checkout with tests and CTF tools
```

`pawnlogic[ctf]` installs CTF tooling dependencies only. CTF skill packs are
optional extension assets that users install explicitly, for example with
`/sp install <repo_url>` into `~/.pawnlogic/skills`. Third-party skill packs are
not bundled into PyPI distributions unless their upstream license and notices
have been reviewed for redistribution.
Git-backed skill-pack installs accept only `https://`, `ssh://`, or
`git@host:owner/repo.git` remotes.

Source-checkout launcher fallback:

```bash
./pawn.sh
```

CLI entry points:

```bash
pawn
pawn --debug
pawn --eval "summarize this repository"
pawn --eval "summarize this repository" --json
python -m pawnlogic --help
```

Default `pawn` uses user-friendly output and hides raw tool-call internals,
parser diagnostics, detailed reasoning streams, and low-level API errors.
Use `pawn --debug` or `/mode` when you need detailed diagnostics.

## What's New

Version 0.1.3 hardens the existing runtime and release surface:

- Git-backed skill-pack installs and `git_op clone` accept only `https://`,
  `ssh://`, or `git@host:owner/repo.git` remotes, with dangerous git
  transports disabled explicitly.
- Docker file mounts are workspace-bound by default, including read-only
  mounts. External read-only challenge files require explicit opt-in.
- Provider setup stores API keys only in PawnLogic's private `.env` path and no
  longer writes keys into shell startup files.
- Provider auto-routing respects inactive providers, and runtime database/log
  files use restrictive local permissions where supported.
- User-facing internal/parser failure messages now point to debug/log
  diagnostics instead of reporting a generic busy state.

See [CHANGELOG.md](CHANGELOG.md) for the full release history.

## Key Capabilities

| Capability | Description |
|-----------|-------------|
| Multi-provider models | Built-in DeepSeek, OpenAI, and Anthropic aliases plus custom OpenAI-compatible or Anthropic-style providers through `/provider`. |
| Persistent workspace | SQLite-backed sessions, searchable history, memory commands, knowledge base, per-session workspaces, and audit logs under `~/.pawnlogic/`. |
| Real tool execution | Host shell, code sandbox, file operations, URL fetch, browser automation, Docker containers, and CTF helpers. |
| Trust-boundary UX | User-mode warnings make it explicit when a tool crosses local host, container, browser, network, delegate, or plaintext HTTP boundaries. |
| MCP integration | Stdio MCP servers can be configured from `~/.pawnlogic/mcp_configs.json`, with roots and stderr logging handled by PawnLogic. |
| CTF / pwn workflows | Optional pwn tooling, Docker container helpers, GDB automation, ROP chain support, libc leak workflows, and user-installed local skill packs. |
| Release hygiene | CI runs fast Python 3.11 PR checks first, then release/manual validation covers Python 3.10/3.11/3.12, packaging, dynamic E2E, docs structure, language policy, package build, and Trusted Publishing guardrails. |

## Supported Models

PawnLogic ships with preconfigured model aliases. Only active providers with a
configured API key are shown in `/model` and Tab completion.

| Provider | Aliases | Notes |
|----------|---------|-------|
| DeepSeek | `ds-v4-flash`, `ds-v4-pro` | Default provider; fast primary model plus flagship reasoning model. |
| OpenAI | `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.4-nano`, `gpt-4o`, `gpt-4.1`, `o3` | Coding, vision, multimodal, low-latency, and reasoning aliases. |
| Anthropic | `claude-opus`, `claude-sonnet`, `claude-haiku` | Opus, Sonnet, and Haiku aliases for Anthropic's Messages API path. |

Custom provider model descriptions come from
`~/.pawnlogic/custom_providers.json`. Re-running `/provider update <name>`
refreshes selected models and writes English fallback descriptions for fetched
models when the provider does not supply a useful description.

## Provider Management

```bash
/provider                         # open the provider TUI
/provider add <name> <base_url> <ENV_KEY> [anthropic]
/provider fetch <name>            # fetch available models and select aliases
/provider update <name>           # re-fetch provider models
/provider activate <name>         # show selected provider models
/provider deactivate <name>       # hide provider models
/provider list                    # show provider and key status
/provider test <model>            # test connectivity for a model alias
/setkey                           # run key setup again
/keys                             # show configured key status
```

API keys are stored in `~/.pawnlogic/.env`. Provider configs, model aliases,
and descriptions are stored in `~/.pawnlogic/custom_providers.json` without
secret values. Provider setup does not write keys into shell startup files.

Plain `http://` provider endpoints are allowed for local relays and lab
setups, but user-friendly mode prints a trust-boundary warning because requests
and API keys are not protected by TLS.

## Quick Command Reference

```bash
/model [alias]                    # switch model
/mode                             # toggle user-friendly/debug output
/chat find <keyword>              # search all sessions
/think <prompt>                   # run one deeper reasoning turn
/compact                          # summarize and compact context
/undo [n]                         # roll back recent turns
/deep                             # full-power mode
/init_project [desc]              # initialize project state
/pwnenv                           # check CTF toolchain integrity
/ctf init <name>                  # start CTF workspace metadata
/ctf solved [flag]                # mark a confirmed CTF flag as solved
/ctf writeup                      # export a CTF writeup draft
/sp install <repo_url>            # install a git-backed skill pack
```

Run `/help` inside PawnLogic for the full command list.

## Trust Boundary

PawnLogic is an agent execution tool, not a security sandbox. It intentionally
executes real tools with the current user's permissions when you ask it to do
so. Pattern filters, Docker boundaries, and capability profiles reduce
accidents; they do not contain a determined attacker.

User-friendly mode prints explicit trust-boundary notices for host shell
execution, Docker container exec, browser/network-capable tools, private
network URL access, delegated sub-agents, and plaintext HTTP providers. Use
`pawn --debug` when you need lower-level tool arguments and diagnostics.
Docker file mounts are workspace-bound by default, including read-only mounts;
outside read-only challenge files require explicit `allow_host_read_mount`.

## MCP Tool Integration

For pip or one-line installer users, PawnLogic creates editable templates in
`~/.pawnlogic/` on startup:

```bash
pawn
cp ~/.pawnlogic/mcp_configs.example.json ~/.pawnlogic/mcp_configs.json
# edit ~/.pawnlogic/mcp_configs.json and add keys with /setkey or ~/.pawnlogic/.env
pawn
```

For source checkout users, the repository template can also be copied directly:

```bash
cp mcp_configs.example.json ~/.pawnlogic/mcp_configs.json
```

Supported example MCP servers include Tavily search, Playwright browser
automation, and a filesystem bridge. External `fetch` MCP is disabled in the
example because `uvx mcp-server-fetch` may contact PyPI during startup; use
PawnLogic's built-in `fetch_url` unless you explicitly enable that MCP server.

MCP subprocess stderr is written to
`~/.pawnlogic/logs/mcp/<server>.stderr.log` by default. Set top-level
`"debug_stderr": true` in `mcp_configs.json` when you want raw MCP stderr on
the console. PawnLogic advertises MCP roots for the current working directory
and `~/.pawnlogic/workspace`.

## Data Layout

All runtime data and API keys are stored in `~/.pawnlogic/`.

```text
~/.pawnlogic/
├── .env                    # API keys
├── custom_providers.json   # user provider configs, no keys
├── mcp_configs.json        # MCP server declarations
├── pawn.db                 # sessions, messages, knowledge base
├── global_skills.md        # GSA skill archive
├── skills/                 # optional user-installed skill packs
├── workspace/              # per-session working directories
└── logs/                   # audit logs
```

The project directory contains no secrets and is safe to commit or share.

## Documentation

| Document | Description |
|----------|-------------|
| [**README.md**](README.md) | This page |
| [**README_CN.md**](README_CN.md) | Chinese README |
| [**GUIDE.md**](GUIDE.md) | Full reference: commands, architecture, and FAQ |
| [**GUIDE_CN.md**](GUIDE_CN.md) | Chinese full reference |
| [**CHANGELOG.md**](CHANGELOG.md) | Version history and release notes |
| [**CONTRIBUTING.md**](CONTRIBUTING.md) | Contribution, provider, and test workflow |
| [**SECURITY.md**](SECURITY.md) | Vulnerability reporting policy |
| [**THIRD_PARTY_NOTICES.md**](THIRD_PARTY_NOTICES.md) | Third-party attribution and redistribution notes |

## Support

- GitHub: [github.com/john0123412/PawnLogic](https://github.com/john0123412/PawnLogic)
- Issues: use GitHub Issues for bugs and feature requests.
