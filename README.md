**[English](README.md)** | [Chinese](README_zh-CN.md)

# PawnLogic

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/pypi/v/pawnlogic.svg?label=version&cacheSeconds=0)](https://pypi.org/project/pawnlogic/)
[![CI](https://github.com/john0123412/PawnLogic/actions/workflows/main_ci.yml/badge.svg)](https://github.com/john0123412/PawnLogic/actions/workflows/main_ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20WSL2-lightgrey.svg)]()

PawnLogic is a terminal-first autonomous AI agent with multi-provider model
routing, persistent memory, real local tool execution, MCP integration, and a
CTF-oriented toolchain. The current public release is **0.4.3**.


## Quick Start

Requirements: Linux or WSL2, Python 3.10+, `pip`. `git` is only needed for
source checkouts and git-backed skill packs. Put `~/.local/bin` on `PATH`
for the global launcher.

**Install from PyPI:**

```bash
pip install pawnlogic
pawn
```

**One-line installer** (isolated venv, writes `~/.local/bin/pawn`):

```bash
curl -fsSL https://raw.githubusercontent.com/john0123412/PawnLogic/main/install.sh | bash
pawn
```

**Source checkout** (development):

```bash
git clone https://github.com/john0123412/PawnLogic.git
cd PawnLogic
python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
pawn
```

Optional extras: `pawnlogic[docker]`, `pawnlogic[browser]`, `pawnlogic[ctf]`.
The `[ctf]` extra installs tooling only (pwntools, ROPgadget, ropper); skill
packs stay separate and are installed explicitly with
`/skills install <repo_url>`.

The first run opens the API key setup. Runtime data lives under
`~/.pawnlogic/`, never inside the project directory.

```bash
pawn                                     # interactive TUI
pawn --eval "summarize this repository"   # one-shot, non-interactive
pawn --eval "..." --json                 # NDJSON output
pawn --continue                          # resume the newest recoverable session
pawn resume <session>                    # load a session without running it
pawn --debug                             # full diagnostics
```

Optional extras: `pawnlogic[docker]`, `pawnlogic[browser]`, `pawnlogic[ctf]`.
The `[ctf]` extra installs tooling only (pwntools, ROPgadget, ropper); skill
packs stay separate and are installed explicitly with
`/skills install <repo_url>` into `~/.pawnlogic/skills` (or the checkout's own
`skills/` directory when running from a source checkout that contains one).

## Models and Providers

Built-in aliases (only providers with a configured key appear in `/model`).
Each alias points at a real model ID; aliases move when providers ship new
models, so run `/provider fetch <name>` after adding a key to pick up the
current list.

| Alias | Model | Provider |
|-------|-------|----------|
| `ds-v4-flash` | `deepseek-v4-flash` | DeepSeek |
| `ds-v4-pro` | `deepseek-v4-pro` | DeepSeek |
| `gpt-5.5` | `gpt-5.5` | OpenAI |
| `gpt-5.4` | `gpt-5.4` | OpenAI |
| `gpt-5.4-mini` | `gpt-5.4-mini` | OpenAI |
| `gpt-5.4-nano` | `gpt-5.4-nano` | OpenAI |
| `gpt-4o` | `gpt-4o` | OpenAI |
| `gpt-4.1` | `gpt-4.1` | OpenAI |
| `o3` | `o3` | OpenAI |
| `claude-opus` | `claude-opus-4-6` | Anthropic |
| `claude-sonnet` | `claude-sonnet-4-6` | Anthropic |
| `claude-haiku` | `claude-haiku-4-5-20251001` | Anthropic |

```bash
/provider                              # provider TUI
/provider add <name> <base_url> <ENV_KEY> [format] [auth]
/provider fetch <name>                 # list models, pick aliases
/provider update <name>                # re-fetch models
/provider activate|deactivate <name>    # show or hide a provider's models
/provider list                         # provider and key status
/provider test <model>                 # free connectivity check, no inference
/setkey                                # re-run key setup
/keys                                  # key status
```

Keys live in `~/.pawnlogic/.env`; provider configs in
`~/.pawnlogic/custom_providers.json` (no secrets). Setup never touches shell
startup files.

### Protocols and authentication

| Format | Endpoint |
|---|---|
| `openai` | `POST {base}/chat/completions` |
| `anthropic` | `POST {base}/messages` |
| `responses` | `POST {base}/responses` |

Auth is independent from format: `auto`, `bearer`, `x_api_key`, or `both`.
The default `auto` keeps each protocol's historical scheme, so existing
providers keep working unchanged. A 401 names the credential header that was
actually sent — change `Auth` before rotating the key.

## Reasoning Effort

One control sets both how hard the model thinks and the runtime limits
(output tokens, tool-call iterations, context budget, time budget):

| Level | Sent to provider | Tool-call iterations | Replaces |
|-------|------------------|----------------------|----------|
| `off` | `none` | 10 | — |
| `low` | `low` | 10 | `/low` |
| `medium` | `medium` | 30 | `/mid`, `/normal` |
| `high` | `high` | 50 | `/deep` |
| `xhigh` | `xhigh` | 100 | `/max` |
| `max` | `max` | 150 | `/ultra` |

Default is `medium`; the old tier commands still work as aliases. The value
is only sent to models that declare support for it. Custom providers opt in
with `/provider effort <name> on`.

## Commands

```bash
/model <alias> [effort]        # switch model, optionally set effort
/effort [level]                # off|low|medium|high|xhigh|max
/mode                          # toggle user-friendly/debug output
/chat find <keyword>           # search all sessions
/think <prompt>                # one deeper reasoning turn
/compact                       # summarize and compact context
/undo [n]                      # roll back recent turns
/queue                         # inspect queued and steered work
/abort                         # interrupt the active turn
/init_project [desc]           # initialize project state
/pwnenv                        # check CTF toolchain integrity
/ctf init <name>               # start CTF workspace metadata
/ctf solved [flag]             # mark a confirmed flag as solved
/ctf writeup                   # export a CTF writeup draft
/skills install <repo_url>     # install a git-backed skill pack
/worker [alias|auto]           # inspect or set the preferred worker
/planguard [strict|advisory|status]
/agent policy show             # delegated-agent policy
```

`/help` lists everything, including `/extension` management.

## Trust Boundary

PawnLogic executes real tools with your user permissions. It is an agent
execution tool, not a security sandbox. High-risk shell commands need
explicit confirmation (the dialog defaults to **Deny**); non-interactive
runs fail closed instead. Plaintext `http://` providers and cross-boundary
tool use print explicit warnings. Pattern filters and Docker boundaries
reduce accidents but do not contain a determined attacker.

The 0.4.3 release hardens outbound boundaries: Docker network modes
are restricted to `none`, `bridge`, and `host`. Container-sharing modes such as
`container:<id>` and unknown modes are rejected before the Docker SDK is called,
even with `allow_network=true`. Bridge and host still require explicit network
authorization. Browser tools (Patchright and Scrapling) enforce HTTP/HTTPS
connections through a mandatory loopback proxy that dials policy-time pinned
addresses. Both Chromium paths disable HTTP/2 and QUIC, force loopback through
that proxy, request Service Worker blocking, and restrict non-proxied WebRTC UDP. Context
route guards provide a second check where interception is available; failed
installation closes the context. Confirmed private targets retain their exact
pins only for the current operation, whose sockets are closed on exit.
Plain HTTP accepts one request per connection and rejects chunked uploads,
upgrades, `Expect`, and bodies over 8 MiB. HTTPS remains end-to-end opaque;
this destination boundary is not an OS sandbox. Service Worker blocking is
requested from the SDK; the proxy enforces their egress even if registration
is not blocked. Scrapling versions without
the required setup contract are denied before fetching.

Plaintext HTTP is allowed for authorized CTF labs. Run HTTP client code with
`run_code_docker`, `network="bridge"`, and `allow_network=true` after explicit
network authorization; use the local `python` image and omit host file mounts
and dependency installation when the standard library is sufficient. The
disposable container retains its 512 MiB memory, 0.5 CPU, and 256 PID limits.
Its HTTP client is not subject to the browser proxy's upload/framing limits.
One-shot `run_code_docker` containers now drop all Linux capabilities, use
tmpfs for `/tmp` and `/run`, and have a read-only root filesystem. Python
`install_deps` uses a writable root filesystem and the image's default user
unless `container_user` is supplied. Otherwise the default user matches the
host UID:GID; this is non-root only when the host UID is nonzero. On platforms
without host IDs the image default is used. `container_user="root"` explicitly
selects root. Persistent `pwn_container` workloads retain their image defaults.
Additional workspace mounts remain subject to the mount policy.

The scoped transport below is an Unreleased source change; it is not included
in the published 0.4.3 package.

The optional operator setting `PAWNLOGIC_DOCKER_EGRESS_ALLOW` accepts explicit
hostnames, IPs, and CIDRs. With this setting, an authorized `network="bridge"`
request uses an offline (`network=none`) disposable container and a mounted
Unix-socket relay to a trusted host HTTP/CONNECT proxy. Every proxy destination
must match the scope; declared hostnames resolve once before startup and the
proxy dials only those numeric addresses. CIDRs authorize literal IP targets;
an unlisted hostname is denied without a DNS lookup. Special addresses denied
by Network Policy remain denied. Direct network sockets have no external route,
including requests that ignore proxy variables. Redirects to an unapproved
host/IP fail at the next proxy request. The container cannot authorize itself.

Scoped networking currently requires a Unix Docker host, the built-in Python
image, a non-root numeric UID:GID, no additional host mounts or `install_deps`,
and a 1–300 second timeout. Use `urllib.request`, which honors the configured
proxy environment; `http.client` requires explicit proxy/CONNECT handling.
The relay supports streamed fixed-length and chunked uploads up to 64 MiB per
request, bounded headers/trailers, and one request per HTTP connection; `Expect`
and protocol upgrades are rejected. CONNECT is an opaque TCP tunnel to an
approved target/port, not TLS inspection or transparent TCP/UDP networking.
Operation expiry/cleanup revokes active sockets before container removal.
The UID must be nonzero; the numeric GID may be zero.

When a scope is set, host networking, persistent exec, connected persistent
create, Airlock installs, and extra host mounts are denied. Offline runs and
unmounted offline persistent creation remain available; persistent list/destroy
remain available. Without this setting, authorized bridge/host access retains
its capability-only behavior and has no destination allowlist. Airlock then
preserves existing bridge attachments and disconnects only its temporary
attachment; failed disconnects revoke access and kill/remove the container,
reporting unresolved daemon cleanup as a possible live-container risk.
This setting does not quarantine previously running bridge/host containers;
stop/destroy them before relying on the scope. Change the operator declaration
only between operations. Transparent arbitrary TCP/UDP filtering remains a
separate host-managed phase.

The [boundary follow-up plan](docs/plans/container-boundary-followups.md)
tracks the remaining container boundary work. Implemented so far: the offline
attach compatibility guard (Airlock rejects offline (none/unattached)
containers and unverifiable network state before any attach or install), the
Airlock operation deadline (hard `timeout_seconds`, watchdog-enforced; expiry
revokes the tool handle and terminates the container) and the read-only
legacy-container preflight (`pwn_container action=preflight` reports running
PawnLogic-labelled containers that still have network access; a scope never
quarantines them). Host-managed transparent TCP/UDP filtering is prepared as
a review package only (ADR 0014: helper interface, traffic-path-to-hook
matrix, rollback; simulated tests); it stays uninstalled and requires
separate host authorization before anything is applied. Offline restoration
topology remains proposed.
Review-package checks fail closed on query errors, inspect complete rule
snapshots without short-circuit pipelines, and reject link-local and cloud
metadata destinations, including IPv4-mapped spellings.
Airlock installer admission is atomic against expiry. An already-admitted
Docker request can race with termination; an unconfirmed cleanup is reported
as a live-container risk requiring manual action.

## Data Layout

```text
~/.pawnlogic/
├── .env                    # API keys
├── custom_providers.json   # provider configs, no keys
├── mcp_configs.json        # MCP server declarations
├── pawn.db                 # sessions, messages, knowledge base
├── skills/                 # user-installed skill packs
├── sessions/               # per-session scratch directories
├── workspace/              # task workspaces
└── logs/                   # audit logs
```

The project directory contains no secrets and is safe to share.

## FAQ

**`/model` doesn't show new models after adding a provider?**
Configure its key, then `/provider fetch <name>`, select models, and
`/provider activate <name>`.

**Where are API keys stored?**
`~/.pawnlogic/.env` — outside the project, never tracked by git.

**`pawn: command not found`?**
`export PATH="$HOME/.local/bin:$PATH"`.

**How do I add an MCP server?**

```bash
cp ~/.pawnlogic/mcp_configs.example.json ~/.pawnlogic/mcp_configs.json
# then edit mcp_configs.json
```

**Browser tools report a missing module?**
`pip install 'pawnlogic[browser]'`, then `patchright install chromium`.

**Local Ollama models?**
`/provider add` with base URL `http://localhost:11434` and an empty key.

## Documentation

| Document | Description |
|----------|-------------|
| [CHANGELOG.md](CHANGELOG.md) | Version history and release notes |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribution, provider, and test workflow |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting policy |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | Third-party attribution |

## Support

- GitHub: [github.com/john0123412/PawnLogic](https://github.com/john0123412/PawnLogic)
- Issues: GitHub Issues for bugs and feature requests.
