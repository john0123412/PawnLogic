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
CTF-oriented toolchain. The current public release is **0.4.0**.

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
pawn --continue                    # load the newest recoverable draft
pawn resume <session>              # load a chosen session without running it
python -m pawnlogic --help
```

Default `pawn` uses user-friendly output and hides raw tool-call internals,
parser diagnostics, and low-level API errors.
Model reasoning is shown, as a dim `🧠 [thinking]` stream, because a slow
first token is otherwise indistinguishable from a dead connection. It is a
side channel: it never counts as the answer. Providers that do not stream a
`reasoning_content` field — including Anthropic-format models, whose
`thinking_delta` the stream adapter does not yet handle — show the status
words below without the reasoning text.
Tool-call recovery is best effort, not a guarantee. If a malformed tool-call
attempt cannot be parsed, it produces no tool call and is not executed;
detailed parser diagnostics remain hidden in user-friendly mode.
Use `pawn --debug` or `/mode` when you need detailed diagnostics.
With `--json`, each line is an independent NDJSON record. Existing `text`,
`chunk`, and `json` records remain stable; versioned Agent lifecycle records
use the additive `{"type":"event","data":{...}}` envelope.

## What's New

Version 0.4.0 unifies reasoning effort into a single control, and adds a third provider protocol with authentication no longer bound to it:

- **`/effort` is the one control for reasoning effort:** six rungs —
  `off`, `low`, `medium`, `high`, `xhigh`, `max` — defaulting to `medium`,
  in a modal selector reachable from `/model`. The old tier commands
  (`/low`, `/mid`, `/normal`, `/deep`, `/max`, `/ultra`) still work as
  aliases and print where the setting moved. See
  [ADR 0012](docs/adr/0012-reasoning-effort-control.md).
- **The parameter is only sent to models that declare it:** support is a
  per-rung map, so a model that takes `low`/`medium`/`high` but not
  `xhigh` never receives `xhigh`, and a model that declares nothing is
  never sent the parameter at all. That is what keeps the default safe
  against an OpenAI-compatible relay that rejects it. A whole custom
  provider can opt its models in with
  `/provider effort <name> on|off`.
- **An effort change no longer discards an explicit `/worker` lock.**
  Every tier preset pinned the worker to `auto`, so the old commands
  silently undid the lock while the worker menu kept showing the old
  value.
- **A Turn reports `Sent` the moment you press Enter,** instead of
  showing `0s` through the whole pre-request window, where a slow
  time-to-first-token was indistinguishable from a dead connection.
  Model reasoning text is shown as a dim `🧠 [thinking]` stream in
  user-friendly mode.
- **The completion menu no longer paints over the toolbar.** It is
  laid out between the output window and the composer, so the model
  field and the fuzzy candidates no longer draw on top of each other.
- **An idle Ctrl+C exits cleanly.** It used to unwind past the CLI
  teardown and leave the non-daemon Turn worker holding the interpreter
  open, where only SIGKILL worked.
- **`/provider effort` can no longer break your provider config.**
  Pointing it at a built-in provider wrote an incomplete entry into
  `custom_providers.json`, and the next start rejected the whole file —
  every custom provider, model, and activation state gone. Built-in
  providers are refused with an explanation; the opt-in applies to
  custom providers only.
- **A third provider protocol, and authentication is no longer tied to
  it.** `api_format` accepts `openai`, `anthropic`, or the new
  `responses` (OpenAI Responses, `POST {base}/responses`). The
  credential header used to be *derived* from the format, so a relay
  serving Anthropic-shaped payloads over `Authorization: Bearer` — which
  rejects `x-api-key` — had no configuration that could work. Auth is
  now its own setting (`auto`, `bearer`, `x_api_key`, `both`) in the
  provider TUI and in
  `/provider add <alias> <url> <KEY> [format] [auth]`; `auto` keeps the
  previous behaviour exactly. A 401 now names the credential header
  that was actually sent and points at the Auth setting instead of
  asserting your key is invalid. See
  [Protocols and authentication](#protocols-and-authentication).

See [CHANGELOG.md](CHANGELOG.md) for the full release history.

## Key Capabilities

| Capability | Description |
|-----------|-------------|
| Multi-provider models | Built-in DeepSeek, OpenAI, and Anthropic aliases plus custom OpenAI-compatible, Anthropic-style, or OpenAI Responses providers through `/provider`, each with an independent authentication scheme. |
| Delegated agents | Bounded sub-agents use host-controlled dynamic model routing, user allow/deny policy, token/tool/cost budgets, capability-filtered Tools, task-local workspaces, and one-or-two-worker orchestration with task lineage. |
| Structured context | Versioned task state, Tool-call-safe trimming against an estimated-token context budget (`/ctx <tokens>`; legacy character budgets migrate on load), and host-selected delegated context keep long sessions bounded without copying raw parent history. |
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

## Reasoning Effort

Thinking effort is one control, not two. A single level decides both how hard
the model thinks and how much room it gets: the `reasoning_effort` value sent
to the provider, plus the runtime limits for output tokens, tool-call
iterations, a context window denominated in estimated tokens, Tool output, and
time budget. `/model` asks for the
level right after you pick a model, so the two choices are made in one place.

| Level | Sent to the provider | Tool-call iterations | Replaces |
|-------|----------------------|----------------------|----------|
| `off` | `none` | 10 | — |
| `low` | `low` | 10 | `/low` |
| `medium` | `medium` | 30 | `/mid`, `/normal` |
| `high` | `high` | 50 | `/deep` |
| `xhigh` | `xhigh` | 100 | `/max` |
| `max` | `max` | 150 | `/ultra` |

`medium` is the default. The legacy commands still work and now map to the
matching level, so an existing muscle memory is never wrong — it just prints
where the setting moved.

The value is only sent for models that declare support for it, so a relay that
rejects the parameter can never turn an effort change into an error. Every
DeepSeek alias, the `gpt-5.x` family, and `o3` declare support. For any other
model the level still moves the local limits and the selector says so
explicitly, because a silently-ignored setting reads as a broken feature.
Custom providers can opt in with `/provider effort <name> on` when they accept
the field.

Anthropic-format models are not wired up: the Messages API expresses extended
thinking as `thinking.budget_tokens` rather than `reasoning_effort`, so for
those models the level currently moves local limits only. Effort applies to
delegated workers too, since a worker resolves the level from its own model
alias; only the worker's output budget is capped separately so a worker chosen
for speed does not inherit a 32k ceiling.

## Provider Management

```bash
/provider                         # open the provider TUI
/provider add <name> <base_url> <ENV_KEY> [format] [auth]
/provider fetch <name>            # fetch available models and select aliases
/provider update <name>           # re-fetch provider models
/provider activate <name>         # show selected provider models
/provider deactivate <name>       # hide provider models
/provider effort <name> on|off     # let a custom provider receive reasoning_effort
/provider list                    # show provider and key status
/provider test <model>            # test connectivity for a model alias
/setkey                           # run key setup again
/keys                             # show configured key status
```

API keys are stored in `~/.pawnlogic/.env`. Provider configs, model aliases,
and descriptions are stored in `~/.pawnlogic/custom_providers.json` without
secret values. Provider setup does not write keys into shell startup files.

### Protocols and authentication

`format` is one of `openai`, `anthropic`, or `responses`:

| Format | Endpoint | Payload |
|---|---|---|
| `openai` | `POST {base}/chat/completions` | OpenAI Chat Completions |
| `anthropic` | `POST {base}/messages` | Anthropic Messages |
| `responses` | `POST {base}/responses` | OpenAI Responses |

`auth` is a separate setting, because the two are independent in practice.
Relays routinely serve Anthropic-shaped payloads over `Authorization: Bearer`
and reject `x-api-key` with a 401, and the reverse also occurs. `auto` — the
default — reproduces the protocol's own historical scheme, so existing
providers keep working unchanged:

| `auth` | Header sent |
|---|---|
| `auto` | the protocol default (`x-api-key` for Anthropic, `Bearer` otherwise) |
| `bearer` | `Authorization: Bearer` |
| `x_api_key` | `x-api-key` |
| `both` | both headers |

`anthropic-version` is sent for every `anthropic` request regardless of `auth`
— it identifies the payload shape rather than the credential, and Anthropic
endpoints require it.

When a 401 happens, the error names the credential header that was actually
sent and points at the `Auth` setting, instead of telling you to replace a key
that may be working. Change `Auth` first, and only rotate the key if it is
also rejected on the header the relay expects.

The interactive TUI also edits a provider in place. Open a provider's detail
view and choose `Edit Provider` to correct its `Base URL`, `Format`, and `Auth`;
the save keeps the provider name, its API key, and its loaded models. Renaming
is not offered there, because a rename must re-point every model entry and the
key's environment variable and cannot be written atomically. Replace the key
with `Update API Key`, which asks for the full value again and never displays
the stored one.

Confirmation dialogs mark the focused button in text as well as colour, and
`←` `→` `↑` `↓` and `Tab` all move between them. `Delete Provider` opens a
dialog that starts on `Cancel`, so `Enter` never deletes by accident.

The model list behind `Fetch` and `Sync` opens with an empty search box every
time, so a query typed into an earlier list is never re-applied to the next
one. Move with `↑` `↓` `PageUp` and `PageDown`; `Space` or `Enter` ticks the
model under the cursor, `a` selects all, and `c` clears the selection. Press
`s` to load the ticked models and stay in the list, or `S` to load them and
close it — neither requires moving to the buttons first. The list is paged,
and its three actions — `Load Selected`, `Load & Close`, and `Cancel` — sit
after the last model, so press `L` to jump straight to them instead of
walking down once per model. They mark the focused one in text rather than
colour alone.

`Fetch` and `Sync` never send a chat request, so listing models costs
nothing. They read the provider's free `/v1/models` listing and hide entries
that report a non-text output modality; a provider that does not report
capability metadata keeps all of its entries. `/provider test <model>` is
also free: it checks the same listing, so it answers "is the base URL
reachable and does this key work" without ever inferring. The trade-off of
having no billable probe anywhere in the provider flow is that a model your
key cannot actually use is no longer filtered out in advance — it fails as a
normal API error the first time you use it.

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
/model <alias> <effort>           # switch model and set reasoning effort in one step
/effort                           # open the reasoning-effort selector
/effort <level>                   # set reasoning effort directly (off|low|medium|high|xhigh|max)
/limits                           # show the active effort level and whether it is sent
/mode                             # toggle user-friendly/debug output
/chat find <keyword>              # search all sessions
/think <prompt>                   # run one deeper reasoning turn
/compact                          # summarize and compact context
/undo [n]                         # roll back recent turns
/queue                            # advanced queue inspection; does not interrupt the active Turn
/queue clear                      # clear queued/recovered messages without interrupting a Turn
/queue resume                     # resume recoverable queued work
/queue remove <id>                # remove one queued message by stable ID
/queue steer <id>                 # convert a follow-up into a steer
/queue follow-up <id>             # convert a steer into a follow-up
/queue recall <id>                # prefill the editor without removing the message
/abort                            # interrupt the active Turn and clear queued/recovered work
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
/planguard [strict|advisory|status]  # no argument opens the mode selector; effort levels default to advisory, strict is opt-in
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
cloud-metadata/internal targets, the reserved `localhost` namespace (including
subdomains), and loopback, link-local, multicast, unspecified, or reserved
addresses are denied. Private-network targets require explicit authorization,
and non-interactive requests fail closed when confirmation would otherwise be
required. Redirect destinations are normalized, resolved, and evaluated again
before they are followed, including any target-scoped authorization.
Model-generated Tool arguments cannot grant private-network authorization, and
confirmed private targets bypass remote reader services.

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
critical operations are denied by default. The confirmation modal opens
pre-selected on **Deny**: press `y` to approve, `n`/`Esc`/`Ctrl+C` to reject,
and a bare `Enter` rejects. Approval is never a side effect of a keystroke
meant for the composer, and while the modal is mounted the status line shows
`⚠ awaiting confirmation — Esc to review`. Non-interactive execution, including
`pawn --eval`, fails closed when a high-risk command would require
confirmation. `DANGEROUS_PATTERNS` remains only one misuse/risk classifier; it
is not a sandbox boundary and cannot stop a malicious local user.

Host shell execution is hard-bounded: on timeout the whole process group
receives SIGTERM and then SIGKILL, and cleanup never waits forever even if a
child becomes uninterruptible (for example a WSL2 kernel stall). Registered
tools additionally run under a watchdog (`tool_watchdog_sec`, default 600
seconds): a tool call that exceeds the limit is abandoned with an ERROR result
so the session continues instead of freezing. An abandoned background thread
may keep running until the process exits. A high-risk confirmation waits
`confirmation_wait_sec` (default 300 seconds, clamped to stay below
`tool_watchdog_sec`); that deadline belongs to the terminal event loop that
mounted the modal, and an abandoned tool thread's confirmation is reclaimed when
the watchdog expires, so a timed-out prompt can never leave the modal mounted.

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
├── sessions/               # per-session scratch directories (session_<id>/)
├── workspace/              # auto-named task directories plus by-name/ aliases
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

A relay that speaks the Anthropic protocol but authenticates with a Bearer
token — or the reverse — is the same command with a different `auth`:

```
/provider add myrelay https://relay.example.com/v1 MYRELAY_API_KEY anthropic bearer
/provider test <alias>
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

**Q: How do I set how hard the model thinks?**
A: Run `/model` and pick a level right after the model, or use `/effort` on its own. `/effort` with no argument opens the selector, `/effort high` sets it directly, and `/model <alias> <effort>` does both in one step. The level moves the provider's `reasoning_effort` and the runtime limits together. It is sent only for models that declare support — every DeepSeek alias, the `gpt-5.x` family, and `o3` do; for a model that does not, the level still changes local limits and both the selector and `/limits` say it is local-only, so nothing looks silently broken. Custom providers can opt in with `/provider effort <name> on`. The old `/deep`, `/max`, and `/ultra` commands still work and map to `high`, `xhigh`, and `max`.

**Q: Can I abbreviate a slash command?**
A: Yes. Type a unique prefix or subsequence such as `/plg`; Tab completion lists `/planguard`, and pressing Enter normalizes the command. Only a unique match is dispatched; ambiguous input lists its candidates and runs nothing. All registered built-in commands participate in both Prompt Toolkit and readline completion.

**Q: How do I choose a plan-guard mode?**
A: Run `/planguard` (or `/plg`) in an interactive terminal, then use Up/Down or 1/2 and press Enter. Use `/planguard advisory`, `/planguard strict`, or `/planguard status` for explicit or non-interactive use. Advisory is the default; in strict mode the first two tool-call batches without a plan block still run with a correction, and the third such attempt is stopped before its tools execute.

**Q: How does the live composer handle input while a Turn runs?**
A: In Prompt Toolkit mode, one persistent terminal keeps model and Tool output above a fixed bottom composer and status toolbar. The toolbar answers "is it working?" without any guesswork: it reads `Sent · ⏱ 0s` from the moment you press Enter, switches to `Thinking` when the first token arrives, and then shows the running tool as `⏱ 12s · list_dir [2/30]`; all three end with `Esc to interrupt`. The status is reserved its width first, so it stays readable on a narrow terminal instead of being the first thing clipped away. Completed output lines are handed to the host terminal through Prompt Toolkit's safe terminal handoff, so native scrollback, mouse selection, and copy remain available while the Application is running. Consecutive submissions appear as muted queue rows immediately above the composer. The command and model completion list takes its own rows directly above the composer, so it never covers the toolbar or the model field. Enter submits a steer for the next Tool safe point; if a text-only response finishes first, each unclaimed steer runs as a separate subsequent Turn. Alt+Enter queues one follow-up for natural completion. Esc interrupts the active Turn and immediately hands control to queued work when one exists; with no queued work, the interrupted prompt becomes an editable recovered draft. On an idle empty composer, Esc, Up, or Alt+Up joins queued/recovered work into an editable draft. `/queue` remains an advanced diagnostic and management command and never pauses the active Turn. Readline remains explicitly serial and buffers input until the Turn completes.

**Q: What happens when I interrupt a running turn?**
A: Pawn waits for cooperative cancellation to settle. If queued work exists, Esc treats it as the new steer and continues with that direction without creating a duplicate recovered row. If the queue is empty, the interrupted prompt is prefilled as an editable recovered draft without rerunning it; press Enter to retry it once, or edit it then press Enter to replace it exactly once (including an edit beginning with `/`). `/queue remove <id>`, `/queue clear`, `/queue steer <id>`, `/queue follow-up <id>`, and `/queue recall <id>` remain available for advanced queue management. `/abort` interrupts the active Turn and clears all queued/recovered work; there is no separate `--all` form. After a restart, `pawn --continue` loads the newest interrupted, running, or failed session, and `pawn resume <session>` loads a chosen session. Both commands show the history and prefill the draft without running it automatically.

**Q: Test Connection fails but fetch succeeds?**
A: They now read the same free `/v1/models` listing. Fetch walks every page and can fail on a page error or a bad listing body; Test Connection checks one request. A failure from one and not the other usually means a retryable error — run it again.

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
