**[English](README.md)** | [Chinese](README_zh-CN.md)

# PawnLogic

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/pypi/v/pawnlogic.svg?label=version&cacheSeconds=0)](https://pypi.org/project/pawnlogic/)
[![PyPI](https://img.shields.io/pypi/v/pawnlogic.svg?cache=no)](https://pypi.org/project/pawnlogic/)
[![CI](https://github.com/john0123412/PawnLogic/actions/workflows/main_ci.yml/badge.svg)](https://github.com/john0123412/PawnLogic/actions/workflows/main_ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20WSL2-lightgrey.svg)]()

PawnLogic is a terminal-first autonomous AI agent with multi-provider model
routing, persistent memory, real local tool execution, MCP integration, and a
CTF-oriented toolchain. The current public release is **0.3.2**.

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
`/skills install <repo_url>` into `~/.pawnlogic/skills`. Third-party skill packs are
not bundled into PyPI distributions unless their upstream license and notices
have been reviewed for redistribution.
Skill-pack manifests are runtime discovery metadata only; they do not authorize
redistribution without a matching `THIRD_PARTY_NOTICES.md` entry.
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
With `--json`, each line is an independent NDJSON record. Existing `text`,
`chunk`, and `json` records remain stable; versioned Agent lifecycle records
use the additive `{"type":"event","data":{...}}` envelope.

## What's New

Version 0.3.2 introduces bounded, isolation-proven two-worker delegation and
unified skill pack management while preserving existing public contracts:

- A supported batch caller can run at most two delegated tasks while preserving
  FIFO admission and input-order results; `delegate_task` remains a one-task
  compatibility adapter and never creates implicit fan-out.
- Each concurrent child receives a copied RuntimeContext, unique `.tasks/`
  workspace, bounded output collector, and task-local cancellation token.
- Shared token, Tool-call, and cost budgets retain atomic claim and settlement
  behavior across queued, completed, cancelled, and deadline-expired tasks.
- Concurrent children may use only task-isolated file Tools. Shell, network,
  container, extension, MCP, browser, pwn, sandbox, and other non-isolated
  Tool paths fail closed before handler execution.
- Unified skill pack management under `/skills`: interactive TUI with
  arrow-key navigation, space-to-toggle, search, and bulk operations.
  `/sp` and `/skillpack` commands are removed; `/skills` is the single entry
  point for install, sync, rescan, and enable/disable.

See [CHANGELOG.md](CHANGELOG.md) for the full release history.

## Key Capabilities

| Capability | Description |
|-----------|-------------|
| Multi-provider models | Built-in DeepSeek, OpenAI, and Anthropic aliases plus custom OpenAI-compatible or Anthropic-style providers through `/provider`. |
| Delegated agents | Bounded sub-agents use host-controlled dynamic model routing, user allow/deny policy, token/tool/cost budgets, capability-filtered Tools, task-local workspaces, and one-or-two-worker orchestration with task lineage. |
| Structured context | Versioned task state, Tool-call-safe trimming, `ctx_trim_to` targeting, and host-selected delegated context keep long sessions bounded without copying raw parent history. |
| Persistent workspace | SQLite-backed sessions, searchable history, memory commands, bounded provenance-aware knowledge retrieval, per-session workspaces, and audit logs under `~/.pawnlogic/`. |
| Real tool execution | Host shell, code sandbox, file operations, URL fetch, browser automation, Docker containers, and CTF helpers. |
| Trust-boundary UX | User-mode warnings make it explicit when a tool crosses local host, container, browser, network, delegate, or plaintext HTTP boundaries. |
| Optional Extensions | Installed packages can advertise `pawnlogic.extensions` entry points. Discovery does not load their code, and `/extension enable <name>` is always explicit. |
| MCP integration | Stdio MCP servers can be configured from `~/.pawnlogic/mcp_configs.json`, with roots and stderr logging handled by PawnLogic. |
| CTF / pwn workflows | Optional pwn tooling, Docker container helpers, GDB automation, ROP chain support, libc leak workflows, and user-installed local skill packs. |
| Release hygiene | CI runs Ruff, typed-island mypy, docs guard, and fast Python 3.11 PR checks first, then release/manual validation covers Python 3.10/3.11/3.12, packaging, dynamic E2E, docs structure, language policy, package build, and Trusted Publishing guardrails. Production PyPI publishing is tag-only through Trusted Publishing; manual workflow dispatch targets TestPyPI only. |

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

Delegated tasks automatically prefer an eligible fast worker when no model
request is supplied; they do not automatically reuse the current conversation
model. `/worker` lists every model currently visible through `/model`, including
eligible custom-provider aliases. `/agent policy` can allow or deny aliases,
select the default routing mode, and cap cost or concurrency. Explicit model
requests are preferences: provider visibility, user policy, capability, and
budget checks remain authoritative.
Structured tasks and results carry task/parent IDs, deadlines, usage, and
failure records. Shared orchestration budgets are reserved atomically, and
cancellation is cooperative. The core orchestrator admits at most two workers;
each concurrent child has a copied RuntimeContext, an isolated workspace, a
bounded output collector, and a task-local cancellation token. Concurrent
children may use only task-isolated file Tools. `delegate_task` remains a
single-task compatibility Adapter: a policy value of `max-concurrency=2` takes
effect only for a supported batch caller and never causes implicit fan-out.

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

Unstable custom providers can be tuned through environment variables in
`~/.pawnlogic/.env`: `PAWNLOGIC_API_RETRY_MAX` controls total request attempts
including the first attempt, `PAWNLOGIC_API_RETRY_AFTER_MAX` caps provider
`Retry-After` delays, and `PAWNLOGIC_API_CONNECT_TIMEOUT`,
`PAWNLOGIC_API_READ_TIMEOUT`, and `PAWNLOGIC_API_NONSTREAM_TIMEOUT` tune
connection and response wait times.

## Quick Command Reference

```bash
/model <alias>                    # switch model
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
/skills install <repo_url>         # install a git-backed skill pack
/skills                            # interactive TUI: toggle, sync, rescan
/extension list                   # list installed Extensions
/extension enable <name>          # explicitly enable an Extension
/extension disable <name>         # disable an Extension
/worker [alias|auto]              # inspect or set the preferred worker
/planguard [strict|advisory|status]  # CoT plan-guard mode; no arg means advisory
/agent policy show                # inspect delegated-agent policy
/agent run <role> <objective>     # print a safe delegate_task request template
```

Run `/help` inside PawnLogic for the full command list.

## Trust Boundary

PawnLogic is an agent execution tool, not a security sandbox. It intentionally
executes real tools with the current user's permissions when you ask it to do
so. Pattern filters, Docker boundaries, and capability profiles reduce
accidents; they do not contain a determined attacker.

Web fetches and browser navigation evaluate HTTP(S) targets through the shared
Network Policy before use. URLs are normalized; embedded credentials,
cloud-metadata/internal targets, and loopback, link-local, multicast,
unspecified, or reserved addresses are denied. Private-network targets require
explicit authorization, and non-interactive requests fail closed when
confirmation would otherwise be required. Redirect destinations are normalized,
resolved, and evaluated again before they are followed, including any
target-scoped authorization. Model-generated Tool arguments cannot grant
private-network authorization, and confirmed private targets bypass remote
reader services.

Docker `bridge`/`host` networking and legacy `uvx mcp-server-fetch` startup use
capability-only authorization because no concrete URL is available at the gate.
Authorize Docker networking with `allow_network=true` or
`PAWNLOGIC_DOCKER_ALLOW_NETWORK=true`; authorize the legacy MCP network install
with `allow_network_install=true` or
`PAWNLOGIC_MCP_ALLOW_NETWORK_INSTALL=true`. These approvals grant only the
named capability; they are not URL-target approvals.

User-friendly mode prints explicit trust-boundary notices for host shell
execution, Docker container exec, browser/network-capable tools, private
network URL access, delegated sub-agents, and plaintext HTTP providers. Use
`pawn --debug` when you need lower-level tool arguments and diagnostics.
Docker file mounts are workspace-bound by default, including read-only mounts;
outside read-only challenge files require explicit `allow_host_read_mount`.

Host shell execution now passes through an operation policy before subprocess
startup. Low-risk commands run normally, medium-risk commands are classified
for audit, high-risk commands require explicit interactive confirmation, and
critical operations are denied by default. Non-interactive execution, including
`pawn --eval`, fails closed when a high-risk command would require
confirmation. `DANGEROUS_PATTERNS` remains only one misuse/risk classifier; it
is not a sandbox boundary and cannot stop a malicious local user.

Host shell execution is hard-bounded: on timeout the whole process group
receives SIGTERM and then SIGKILL, and cleanup never waits forever even if a
child becomes uninterruptible (for example a WSL2 kernel stall). Registered
tools additionally run under a watchdog (`tool_watchdog_sec`, default 600
seconds): a tool call that exceeds the limit is abandoned with an ERROR result
so the session continues instead of freezing. An abandoned background thread
may keep running until the process exits.

## Optional Extensions

Python distributions may advertise Extension metadata through the
`pawnlogic.extensions` entry-point group. PawnLogic can list installed
Extensions without loading their code. Installation never enables an
Extension automatically.

```bash
/extension list
/extension status [name]
/extension enable <name>
/extension disable <name>
```

Enabled names are stored under `~/.pawnlogic/extensions/enabled.json`.
Extension startup failures are isolated from core startup, and contribution
name conflicts are rejected instead of overwriting built-in Tools or commands.
Dependency-heavy or security-sensitive Extensions must remain independently
packaged and published. The core wheel contains no `pawnlogic_security` package,
security console script, or security dependency; installing such a distribution
would still require explicit `/extension enable <name>` authorization.

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

## Examples

### Add a third-party API

```
/provider add myrelay https://api.myrelay.com/v1/chat/completions MYRELAY_API_KEY
/provider fetch myrelay
/provider activate myrelay
/model <alias>
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

## FAQ

**Q: `/model` doesn't show new models after adding a provider?**
A: Configure its key, run `/provider fetch <name>`, select models, then `/provider activate <name>`.

**Q: Test Connection fails but fetch succeeds?**
A: Fetch reads `/v1/models`; Test Connection sends a chat request. Load a chat model first.

**Q: Where are API keys stored?**
A: `~/.pawnlogic/.env` — outside the project, never tracked by git.

**Q: `pawn` says command not found?**
A: `export PATH="$HOME/.local/bin:$PATH"`

**Q: Browser tools say a module is missing?**
A: `pip install 'pawnlogic[browser]'` then `patchright install chromium`.

**Q: Does it support local Ollama models?**
A: Yes. `/provider add`, Base URL `http://localhost:11434`, leave key empty.

## Documentation

| Document | Description |
|----------|-------------|
| [**README.md**](README.md) | This page |
| [**README_zh-CN.md**](README_zh-CN.md) | Chinese README |
| [**CHANGELOG.md**](CHANGELOG.md) | Version history and release notes |
| [**CONTRIBUTING.md**](CONTRIBUTING.md) | Contribution, provider, and test workflow |
| [**SECURITY.md**](SECURITY.md) | Vulnerability reporting policy |
| [**THIRD_PARTY_NOTICES.md**](THIRD_PARTY_NOTICES.md) | Third-party attribution and redistribution notes |

## Support

- GitHub: [github.com/john0123412/PawnLogic](https://github.com/john0123412/PawnLogic)
- Issues: use GitHub Issues for bugs and feature requests.
