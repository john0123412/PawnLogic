# PawnLogic 1.1 — Complete User Guide

> Full English reference for all features, commands, models, deployment, and architecture.

---

## Table of Contents

1. [Features Overview](#features-overview)
2. [Model Routing](#model-routing)
3. [Deployment](#deployment)
4. [API Key Configuration](#api-key-configuration)
5. [Command Reference](#command-reference)
6. [Usage Examples](#usage-examples)
7. [Architecture](#architecture)
8. [Changelog](#changelog)
9. [FAQ](#faq)

---

## Features Overview

### 1. Session Management

- `/chat list [n]` — List recent n sessions (default 20)
- `/chat view <id|n>` — View full conversation content
- `/chat export <id|n> [path]` — Export as Markdown file
- `/chat find <keyword>` — Full-text search across all sessions
- `/chat tag <id|n> <tags>` — Tag a session (comma-separated)
- `/chat untag <id|n> <tags>` — Remove tags
- `/chat bytag <tag>` — Filter sessions by tag
- `/chat link <id1> <id2> [note]` — Link two related sessions
- `/chat unlink <id1> <id2>` — Remove link
- `/chat related <id|n>` — View linked sessions

### 2. Auto-Naming & Dynamic Workspace

- **Auto-naming**: After the 2nd conversation turn, the agent generates a semantic session name (e.g. `python-crawler` / `ctf-heap-overflow`)
- **Dynamic workspace**: Each session gets an isolated `~/.pawnlogic/workspace/session_<timestamp>_<hash>/` directory
- **Atomic switching**: Session load triggers rename + reverse symlink + pointer update atomically
- **DB consistency**: All session `workspace_dir` fields are validated; `/chat load` never returns an empty path

### 3. CC-Style Interaction

- **Ctrl+C to undo**: In input mode, Ctrl+C rolls back the last turn and re-displays the prompt (Claude Code style)
- **Ctrl+D to exit**: Clean exit via EOF
- **Interrupt generation**: Ctrl+C during agent generation stops immediately, preserving partial output

### 4. GSD Engineering Architecture

- **Spec-driven planning**: Agent must output `<plan>` XML with `<action>` and `<verify>` before any tool call
- **Fresh-context delegation**: Built-in `delegate_task` tool spawns clean sub-agents to avoid context corruption
- **Atomic commits**: After each verified file change, `git commit` is called automatically
- **Global state**: `/init_project` generates `.pawn_state.md` as the project memory anchor

### 5. Vision (Multimodal)

- Terminal AI vision via `glm-4v` or `gpt-4o`
- Use cases: error screenshot analysis, web UI inspection, CTF steganography, architecture diagrams

### 6. Execution Capabilities

- **Multi-language sandbox**: Python / C / C++ / JS / Bash / Rust / Go / Java
- **Docker execution**: `run_code_docker` (ephemeral) + `pwn_container` (persistent), network-isolated by default
- **Smart web crawler**: Jina Reader → Pandoc → regex fallback (3-tier degradation)
- **GDB crash backtracing**: Auto-appends `bt full` on SIGSEGV/SIGABRT/SIGBUS
- **Defensive auditing**: Tool failures auto-recorded; 3+ same-type failures sink to `global_skills.md`
- **Time-aware scheduling**: `/time` sets countdown; <30s remaining triggers URGENT_MODE

### 7. Cost Control

- `/undo [n]` — Roll back last n turns (default 1), preserves pinned messages
- `/compact` — Lightweight model summarizes progress → clears history → summary becomes first message
- `/think <prompt>` — Single reasoning turn, auto-switches to reasoning worker (ds-r1/qwq), then restores
- `/ping` — Minimal keepalive request to refresh API cache TTL

### 8. Persistent Memory

- **SQLite-backed**: `~/.pawnlogic/pawn.db` with multi-session save/load
- **Native RAG**: `/memorize` distills conversations into local knowledge base, auto-injected across sessions
- **Pin messages**: `/pin msg <n>` prevents critical messages from being pruned

### 9. Dual Output Modes

- `/mode` toggles **USER mode** and **DEV mode**
- **USER mode**: All raw tracebacks, tool call JSON, and exceptions converted to friendly messages (e.g. `❌ Please try again`)
- **DEV mode**: Full transparency — tool call details, async thread state, raw responses

### 10. Local Skill Engine

- `./skills/` directory holds skill pack folders (zero config: just drop a `.md` file)
- Agent auto-scans and scores skills by filename + content keywords before each task
- `min_score=3` threshold: skills only injected when relevant intent detected; zero injection for casual chat
- Complements GSA (Global Skills Archive): GSA manages cross-session experience, local skills manage project templates

### 11. Environment Recon

- `check_service(port)` — Extracts process details for a port via lsof or `/proc`
- Returns: PID, process name, executable path, command line, working dir, env vars, linked libraries
- Read-only operation, exempt from `<plan>` requirement

### 12. Skill Pack Sync

- `/sp sync` — `git pull` all skill packs with `.git` directories
- `/sp install <url>` — Clone + install a new skill pack from remote
- `/sp rescan` — Clear cache and re-scan `skills/` directory

### 13. Scrapling Anti-Bot Engine

- `StealthyFetcher.configure()` pre-warmed globally: eliminates cold-start timeout
- Auto-retry on timeout: 2s → 5s → 10s, up to 3 attempts
- Bypasses Cloudflare 5-second shield and JS-rendered pages

### 14. Sliding-Window Context (v1.1)

- Automatically summarizes old history when iteration count exceeds threshold
- Preserves: system prompt + first 2 turns (task anchor) + history summary + last N turns (sliding window)
- Summary retains security primitives: offsets, addresses, gadgets, ruled-out paths
- Prevents Read Timeout on long agentic tasks (e.g. mimo-v2.5 120s limit)

---

## Model Routing

PawnLogic supports 12 providers with hot-switching via `/model`. Both OpenAI Chat Completions and Anthropic Messages API formats are natively supported.

| Provider | Alias | Model ID | Format | Best For |
|----------|-------|----------|--------|----------|
| PawnLogic Engine | `hermes` / `hermes405` | `NousResearch/Hermes-4-70B` | OpenAI | High instruction-following |
| OpenAI | `gpt-4o` / `gpt-4o-mini` | `gpt-4o` | OpenAI | Vision + reasoning |
| Anthropic | `claude-opus` / `claude-sonnet` / `claude-haiku` | `claude-opus-4-7` | Anthropic | Flagship / balanced / fast |
| DeepSeek | `ds-chat` / `ds-r1` | `deepseek-chat` / `deepseek-reasoner` | OpenAI | Cost-efficient / deep reasoning |
| DeepSeek V4 | `ds-v4-pro` / `ds-v4-flash` | `deepseek-v4-pro` | OpenAI | Pwn logic / ultra-fast |
| ZhipuAI | `glm-5.1` / `glm-4.7` / `glm-4.5-air` | `glm-5.1` | OpenAI | China-direct, strong reasoning |
| ZhipuAI Vision | `glm-4v` | `glm-4v-plus` | OpenAI | Screenshot / stego analysis |
| Qwen | `qwen-max` / `qwen-3.0` | `qwen-3.0-max` | OpenAI | Long context, code correction |
| SiliconFlow | `sf-ds-v3` / `sf-qwen72b` | `deepseek-ai/DeepSeek-V3` | OpenAI | Low-cost open-source inference |
| Moonshot | `kimi` | `moonshot-v1-128k` | OpenAI | Ultra-long context log analysis |
| Groq | `groq-llama3` | `llama-3.3-70b-versatile` | OpenAI | **Ultra-fast** script generation |
| Xiaomi MiMo | `mimo-v2.5-pro` / `mimo-v2.5` | `mimo-v2.5-pro` | OpenAI | China-direct reasoning model |
| Local Ollama | `qwen-local` | `qwen2.5-7b-instruct` | OpenAI | Offline / air-gapped |

### Reasoning Models

Models returning `reasoning_content` (DeepSeek R1, MiMo, QwQ) are fully supported:
- Reasoning steps auto-saved to SQLite `messages.reasoning_content` column
- `/think <prompt>` for single reasoning turn; restores original model after
- Use for: Pwn exploit analysis, math proofs, code auditing

### Custom Providers

```bash
/provider add        # Interactive guided setup
/provider list       # List all providers with format tags ([A] = Anthropic)
/provider test <model>  # Test connectivity
/provider remove <n>    # Remove custom provider
```

---

## Deployment

### Requirements

- **Recommended**: WSL2 / Ubuntu (full experience)
- **Optional**: Windows (basic only — no Pwn toolchain)

### WSL2 / Ubuntu (Recommended)

```bash
git clone https://github.com/john0123412/PawnLogic.git && cd PawnLogic
python3 -m venv venv && source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env   # fill in your API keys
python main.py
```

Optional CTF/Pwn system dependencies:
```bash
sudo apt update && sudo apt install gcc g++ python3-dev libssl-dev libffi-dev build-essential
```

### Global `pawn` Command

```bash
chmod +x /path/to/PawnLogic/pawn.sh
ln -sf /path/to/PawnLogic/pawn.sh ~/.local/bin/pawn
# Then from any directory:
pawn
```

`pawn.sh` resolves its own real path via `readlink -f`, activates the venv, and runs `main.py`. Code changes take effect immediately on next run.

### Docker Deployment

```bash
# Install Docker
sudo apt install -y docker.io
sudo usermod -aG docker $USER

# Install Python Docker SDK
pip install docker

# Check status inside PawnLogic
/docker status
```

Pre-configured image aliases:

| Alias | Image | Use Case |
|-------|-------|----------|
| `pwndocker` | `skysider/pwndocker` | Full Pwn env (GDB/pwntools/ROPgadget) |
| `ubuntu18` | `ubuntu:18.04` | glibc 2.27 — older CTF challenges |
| `ubuntu22` | `ubuntu:22.04` | glibc 2.35 — newer challenges |
| `kali` | `kalilinux/kali-rolling` | Penetration testing |
| `python` | `python:3.12-slim` | Pure Python execution |
| `gcc` | `gcc:latest` | C/C++ compilation |

---

## API Key Configuration

```bash
cp .env.example .env
# Edit .env and fill in keys for the providers you use
python main.py
```

Check key status at runtime:
```
/keys
```

All keys are read from environment variables. No hardcoded credentials anywhere in the codebase. Keys are stored only in `.env` (gitignored). Custom provider configs (without keys) are stored in `~/.pawnlogic/custom_providers.json`.

---

## Command Reference

### Environment & Model Control

| Command | Description |
|---------|-------------|
| `/mode` | Toggle USER / DEV output mode |
| `/model [alias]` | Switch LLM (e.g. `/model ds-r1`) |
| `/setkey` | Re-run API key configuration wizard |
| `/keys` | Show key status for all providers |
| `/clear` | Clear history, free tokens (keeps pinned + state) |
| `/cd <path>` | Change agent working directory |
| `/file <path>` | Load a file into conversation context |
| `/undo [n]` | Roll back last n turns (default 1) |
| `/compact` | Summarize + clear history (keeps pins) |
| `/think <prompt>` | Single reasoning turn |
| `/ping` | Keepalive request |

### Project Management

| Command | Description |
|---------|-------------|
| `/init_project [desc]` | Initialize `.pawn_state.md` for GSD workflow |
| `/state` | View current project plan |
| `/memorize [topic]` | Distill conversation into knowledge base |
| `/knowledge [query]` | Search / list knowledge entries |
| `/forget <id>` | Delete a knowledge entry |

### Session Management

| Command | Description |
|---------|-------------|
| `/history` | View numbered message history |
| `/pin msg <n>` | Pin message n (prevents pruning) |
| `/save [name]` | Save current session to DB |
| `/sessions` | List all sessions |
| `/load <name\|n>` | Load a session by name or index |
| `/resume [n]` | Resume session with history display |
| `/rename <n> <name>` | Rename a saved session |
| `/del <name\|n>` | Delete a session |

### Compute Tiers

| Command | Tokens | Context | Max Iter | Time Budget |
|---------|--------|---------|----------|-------------|
| `/low` | 4k | 40k | 10 | 5 min |
| `/mid` | 8k | 150k | 30 | 10 min ← default |
| `/deep` | 32k | 400k | 50 | 30 min |
| `/max` | 32k | 600k | 100 | 60 min |
| `/normal` | — | — | — | Reset to /mid |

Fine-grained: `/tokens`, `/ctx`, `/iter`, `/toolsize`, `/fetchsize <n>` · `/limits` to view current values.

### Time-Aware Scheduling

| Command | Description |
|---------|-------------|
| `/time` | View budget / elapsed / remaining |
| `/time <seconds>` | Set time budget |
| `/time 0` | Disable time limit |

When <30s remain, URGENT_MODE activates: skips `<plan>`, switches to fastest available model, compresses output.

### Docker Management

| Command | Description |
|---------|-------------|
| `/docker status` | Check Docker connection |
| `/docker images` | List local images |
| `/docker ps` | List PawnLogic-managed containers |
| `/docker pull <image>` | Pull image (supports aliases) |

### Workspace Maintenance

| Command | Description |
|---------|-------------|
| `/workspace status` | Overview: size / file count / DB consistency |
| `/workspace cleanup` | Read-only scan + auto-backup |
| `/workspace cleanup plan` | Phase 0+1: backup + generate cleanup list |
| `/workspace cleanup execute` | Phase 2+3: archive to `~/.pawnlogic/archive/` + fix DB |
| `/workspace cleanup restore` | Roll back from latest tar backup (atomic) |

### Defensive Auditing

| Command | Description |
|---------|-------------|
| `/failures` | View last 20 tool call failure records |
| `/failures <N>` | View last N failures |
| `/failures clear` | Clear all failure records |

### Global Skills Archive (GSA)

| Command | Description |
|---------|-------------|
| `/memo [content]` | Archive a skill: AI classifies and writes to `global_skills.md` |
| `/memo` | Archive last AI response from current session |
| `/skills` | View category index of `global_skills.md` |
| `/skills view` | View full content (paginated) |
| `/skills path` | Show file path |

### Local Skill Packs

| Command | Description |
|---------|-------------|
| `/sp` or `/skillpack` | List all local skill packs |
| `/sp rescan` | Clear cache, re-scan `skills/` |
| `/sp sync` | `git pull` all skill packs with `.git` |
| `/sp install <url>` | Install skill pack from remote repo |
| `/sp <name>` | View skill pack details |

### Worker Model Selection

| Command | Description |
|---------|-------------|
| `/worker` | Show sub-task worker candidate menu |
| `/worker <alias>` | Lock sub-task model |
| `/worker auto` | Restore auto-routing |

---

## Usage Examples

### Example 1: Large-Scale Engineering (GSD)

```
You > /init_project Build a FastAPI user management system with RBAC
```

Agent reads project state, outputs a strict `<plan>` with `<action>` and `<verify>` blocks, scaffolds `models.py`, `auth.py`, etc. Each file that passes `<verify>` triggers a silent `git commit`. Come back to a complete, version-controlled repository.

### Example 2: Multimodal Analysis (Vision)

```
You > Analyze ./error_log.png, use delegate_task to search for the fix, then write a patch script
```

Agent calls `analyze_local_image` → extracts error text → spawns a clean sub-agent for web search → returns the solution to the main window.

### Example 3: CTF Binary Exploitation

```
You > Analyze ./vuln_pwn. Find the stack overflow offset and set a breakpoint at main with pwn_debug
```

Agent runs checksec, generates de Bruijn pattern via `pwn_cyclic`, writes a GDB batch script, runs `pwn_debug`, and returns register state with the confirmed offset.

### Example 4: USER vs DEV Mode

```
You > /mode          # switch to USER mode
You > run ./broken_script.py
# Output: ❌ Please try again  (no traceback, no JSON)

You > /mode          # switch back to DEV mode
You > run ./broken_script.py
# Output: full traceback + tool call JSON + thread state
```

### Example 5: Web Penetration (P6 Auto-Exploit Chain)

```
You > Scan http://target.com:8080, find and exploit the vulnerability
```

Agent executes the full P6 pipeline:
1. **Recon**: `web_fetch` extracts Server/X-Powered-By/Cookie fingerprints
2. **Env confirm**: `check_service(port=8080)` gets PID/path/env vars
3. **Weapon search**: `search_skills(query='Shiro')` matches local skill packs
4. **Sync**: `/sp sync` or `/sp install` for latest exploit scripts
5. **Execute**: Runs pre-built exploit from skill pack
6. **Verify**: Confirms flag/shell, calls `bump_skill` to boost skill weight

### Example 6: Session Management

```bash
/chat find python crawler        # full-text search across all sessions
/chat tag 3 crawler,learning     # tag session #3
/chat bytag crawler              # filter by tag
/chat link 3 5 "same project, different phases"
```

---

## Architecture

### Code Layout

```
main.py                  — Entry point, slash command parser
config.py                — API routing, model registry, tier presets, security lists
core/
  session.py             — Agentic loop, streaming parser, tool executor, context management
  memory.py              — SQLite DB manager, RAG retrieval, FTS5 search
  persistence.py         — Session persistence
  naming.py              — Auto session naming, workspace alias management
  gsa.py                 — Global Skills Archive manager
  skill_manager.py       — SkillScanner: scan, match, sync, install
  logger.py              — loguru dual-sink logging
tools/
  file_ops.py            — File read/write/patch/shell
  web_ops.py             — Web search and fetch
  browser_ops.py         — Scrapling anti-bot browser (StealthyFetcher + Patchright)
  recon_ops.py           — Environment recon (check_service)
  sandbox.py             — Multi-language code sandbox
  docker_sandbox.py      — Docker container execution
  pwn_chain.py           — CTF/Pwn toolchain (GDB/ROP/libc/one_gadget)
  vision.py              — Multimodal vision analysis
  delegate_tool.py       — Fresh-context sub-agent delegation
skills/                  — Local skill pack directory
```

### Data Storage (`~/.pawnlogic/`)

```
pawn.db                  — Core SQLite DB (sessions, messages, knowledge, facts, failures)
global_skills.md         — Global Skills Archive
workspace/               — Per-session isolated working directories
logs/                    — Audit logs (audit_*.jsonl)
custom_providers.json    — Custom provider configs (no keys)
```

### Security Constraints

1. **Read protection**: `~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.kube` are blacklisted
2. **Write protection**: `/etc`, `/bin`, `/boot`, `/lib`, `/sys` etc. are blacklisted
3. **Dangerous command interception**: `rm -rf /`, fork bombs, reverse shells, `curl|sh`, `sudo` — 14+ patterns blocked
4. **Sandbox env isolation**: All API keys stripped from sandbox environment variables
5. **Docker network isolation**: `network=none` by default; resource limits: 512MB RAM, 0.5 CPU, 256 PIDs

---

## Changelog

### v1.1 (Current)

**Context Management**
- ✅ Sliding-window context pruning: `_build_api_messages()` sends only anchor + summary + recent N turns to LLM
- ✅ History summarization: lightweight model distills old turns, preserving security primitives (offsets, addresses, gadgets)
- ✅ Fixes Read Timeout on long agentic tasks (e.g. mimo-v2.5 120s limit at iteration 15)

**Auto-Naming Reliability**
- ✅ Fixed retry blocking: cooldown gate moved inside `_do()` lock — API failures no longer block retries
- ✅ Fixed Markdown code block parsing in `_extract_json`
- ✅ Fixed snippet collection: prioritizes user/assistant text over tool call names
- ✅ Fixed `response_format` parameter: only passed to OpenAI official models

**Dynamic Workspace**
- ✅ Per-session isolated workspace directories with atomic rename + reverse symlink
- ✅ `/workspace cleanup` suite: status / plan / execute / restore

**Reasoning Model Support**
- ✅ Full support for `reasoning_content` field (DeepSeek R1, MiMo, QwQ)
- ✅ Reasoning steps persisted to SQLite for later review
- ✅ `/think <prompt>` single reasoning mode

**Custom Provider & Dual API Format**
- ✅ Native OpenAI Chat Completions + Anthropic Messages support
- ✅ `/provider` interactive panel: add / remove / test
- ✅ Configs persisted to `~/.pawnlogic/custom_providers.json` (no keys)

**Security & Robustness (P0–P8)**
- ✅ Command injection fix in `git_op` (subprocess list form)
- ✅ Semantic failure detection (20+ signals: Traceback, Segfault, exit codes)
- ✅ Anti-loop detection: 3 identical command+error pairs → inject bypass hints
- ✅ Logic Refresh: every 20 iterations, summarize recent observations
- ✅ API empty response retry: exponential backoff 2s→4s→8s, up to 3 attempts
- ✅ URGENT_MODE: <30s remaining → skip plan, switch to fastest model, compress output
- ✅ `/max` tier: iter=100, ctx=600k, 60min budget

**UX (P2)**
- ✅ `prompt_toolkit` FuzzyCompleter + Fish-style inline suggestions
- ✅ `rich` Markdown rendering with syntax highlighting
- ✅ Bottom status bar: model / tier / token usage / Ctx% / directory / phase
- ✅ Ctx% color thresholds: green (<70%) / yellow (70–90%) / red (≥90%)
- ✅ Fuzzy command correction: `/modle` → `/model` (similarity ≥0.7)

### v1.0

- ✅ `/chat` session management command suite
- ✅ SQLite with tags, links, FTS5 full-text search
- ✅ 2026 model ecosystem: DeepSeek V4, GLM-5.1, Qwen 3.0, Groq, Moonshot
- ✅ GSD engineering architecture · multimodal vision · RAG knowledge base · multi-language sandbox · CTF/Pwn toolchain

---

## FAQ

**Q: How do I switch models?**
Use `/model <alias>`, e.g. `/model ds-v4-pro` for DeepSeek V4 Pro.

**Q: How do I back up my sessions?**
`/chat export <id> ./backup.md` exports as Markdown.

**Q: How do I find a past project?**
`/chat find <keyword>` for full-text search, or `/chat bytag <tag>` to filter by tag.

**Q: Agent is slow — what can I do?**
Use `/low` for low-compute mode, `/model groq-llama3` for ultra-fast responses, or `/clear` to free context tokens.

**Q: Docker won't connect on WSL2?**
Run `sudo dockerd &` manually, or enable systemd in `/etc/wsl.conf`:
```ini
[boot]
systemd=true
```
Then run `/docker status` to diagnose.

**Q: Can I use PawnLogic without Docker?**
Yes. Docker is optional. `run_code` local sandbox is unaffected. `run_code_docker` and `pwn_container` will return installation instructions if Docker is unavailable.

**Q: What's the difference between USER and DEV mode?**
`/mode` toggles. USER mode hides all raw errors and shows friendly messages — good for demos. DEV mode shows full tracebacks, tool call JSON, and thread state — good for debugging.

**Q: How do I undo the last turn?**
`/undo` rolls back 1 turn; `/undo 3` rolls back 3. Ctrl+C in input mode also triggers undo.

**Q: Context is nearly full — what should I do?**
`/compact` summarizes progress and clears history (keeps pins). `/clear` clears everything. Watch the Ctx% indicator in the status bar.

**Q: How do I add a custom skill?**
Create a folder under `./skills/`, add `skill.md` (or `guide.md`). Keywords are auto-extracted from filename and headings. Optionally add `manifest.json` for metadata. See `skills/README.md`.

**Q: Is `check_service` safe to run?**
Yes. It is read-only — uses `/proc` or `lsof` only, modifies nothing. It is exempt from the `<plan>` requirement.

---

## Support

- **GitHub**: [github.com/john0123412/PawnLogic](https://github.com/john0123412/PawnLogic)
- **Issues**: Please use GitHub Issues for bug reports and feature requests
