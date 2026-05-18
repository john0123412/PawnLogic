# 🤖 PawnLogic 1.1

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20WSL2-lightgrey.svg)]()

> **A fully autonomous terminal AI agent** — multi-model routing, persistent memory, real tool execution, and session management. Built for developers and security researchers.

## What is PawnLogic?

PawnLogic is a terminal-native AI agent that **actually does things**: runs code, browses the web, edits files, debugs binaries, and remembers everything across sessions — all from your terminal.

```bash
git clone https://github.com/john0123412/PawnLogic.git && cd PawnLogic
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # add your API key
python main.py
```

> ✅ Full **WSL2** support with native Linux toolchain integration

---

## Key Capabilities

| Capability | Description |
|-----------|-------------|
| 🔀 **12 LLM Providers** | DeepSeek, Claude, GPT-4o, Qwen, GLM, Groq, MiMo, Ollama — hot-switch with `/model` |
| 🧠 **Persistent Memory** | SQLite session history, RAG knowledge base, cross-session full-text search |
| 🛠️ **Real Tool Execution** | Shell, code sandbox (8 languages), web fetch, file ops, Docker containers |
| 👁️ **Vision** | Feed screenshots to `glm-4v` or `gpt-4o` for analysis |
| 📋 **Spec-Driven Planning** | Agent outputs `<plan>` XML before every action — no blind execution |
| 💬 **Session Management** | Tag, search, link, and export conversations with `/chat` commands |
| 🗜️ **Sliding-Window Context** | Auto-summarizes old history to prevent API timeouts on long tasks |
| 🔐 **CTF / Pwn Toolchain** | GDB automation, ROP chain building, libc leak resolution, Docker isolation |

---

## 30-Second Demo

```
You > /init_project Build a FastAPI app with JWT auth

[HERMES] 📡 [Phase:RECON] loading 8 tools...
  💭 [Plan] Scaffold project structure → write models.py → auth.py → main.py → verify
  🔧 write_file(path='models.py', ...) [1/30]
  🔧 write_file(path='auth.py', ...) [2/30]
  🔧 run_shell(command='pytest tests/') [3/30]
  ✓ All tests passed. Committing...
  🔧 git_op(action='commit', message='feat: FastAPI JWT auth scaffold') [4/30]
Done. Full project with tests and git history.
```

```
You > /model ds-r1
You > Analyze ./vuln — find the stack overflow offset

[DS-R1] 🧠 [thinking] Checking binary protections first...
  🔧 inspect_binary(path='./vuln') [1/50]
  🔧 pwn_cyclic(action='gen', length=200) [2/50]
  🔧 pwn_debug(binary='./vuln', gdb_script='run < pattern.txt\ninfo registers') [3/50]
  ✓ Offset confirmed: 72 bytes. NX enabled — switching to ROP chain strategy.
```

---

## Documentation

| Document | Description |
|----------|-------------|
| **README.md** | This page — English quick start |
| **[README_CN.md](README_CN.md)** | 中文简介 — Chinese overview |
| **[GUIDE.md](GUIDE.md)** | Full English reference — all features, commands, models, architecture, FAQ |

---

## Supported Models

| Provider | Aliases | Best For |
|----------|---------|----------|
| DeepSeek | `ds-chat` `ds-r1` `ds-v4-pro` `ds-v4-flash` | Reasoning, cost-efficient, ultra-fast |
| Anthropic | `claude-opus` `claude-sonnet` `claude-haiku` | Flagship reasoning, balanced, fast |
| OpenAI | `gpt-4o` `gpt-4o-mini` | Vision + reasoning |
| ZhipuAI | `glm-5.1` `glm-4.7` `glm-4v` | China-direct, vision |
| Groq | `groq-llama3` | Ultra-fast script generation |
| Xiaomi MiMo | `mimo-v2.5-pro` `mimo-v2.5` | China-direct reasoning |
| Qwen | `qwen-max` `qwen-3.0` | Long context, code |
| Local Ollama | `qwen-local` | Offline / air-gapped |

Full model table with IDs and use cases: [GUIDE.md → Model Routing](GUIDE.md#model-routing)

---

## Quick Command Reference

```bash
/model <alias>        # switch LLM
/mode                 # toggle USER / DEV output mode
/chat find <keyword>  # full-text search across all sessions
/think <prompt>       # single deep-reasoning turn
/compact              # summarize + clear context
/undo [n]             # roll back last n turns
/deep                 # switch to deep mode (32k tokens, 50 iter)
/init_project         # initialize GSD engineering pipeline
/pwnenv               # check CTF toolchain integrity
```

Full command reference: [GUIDE.md → Command Reference](GUIDE.md#command-reference)

---

<details>
<summary>🔐 CTF / Security Research Toolchain (click to expand)</summary>

PawnLogic includes a dedicated Pwn/CTF pipeline:

- **Binary analysis**: `inspect_binary` → auto-writes checksec/file results to `.pawn_state.md`
- **Offset finding**: `pwn_cyclic` generates de Bruijn patterns → `pwn_debug` reads crash offset
- **ROP chain building**: `pwn_rop` (ROPgadget wrapper) + `pwn_libc` (libc leak resolver) + `pwn_one_gadget`
- **GDB automation**: batch-mode GDB scripts, auto `bt full` on SIGSEGV/SIGABRT/SIGBUS
- **Docker isolation**: `pwn_container` for persistent CTF environments with specific libc versions
- **Timed debugging**: `pwn_timed_debug` with countdown-aware mode switching
- **Skill packs**: `./skills/ctf_pwn/`, `./skills/ctf_web/`, etc. — auto-injected when relevant keywords detected

**Recommended model combos for CTF:**
| Task | Model |
|------|-------|
| Pwn exploit dev | `ds-r1` or `ds-v4-pro` (deep reasoning) |
| Web code audit | `ds-chat` or `glm-5.1` |
| Screenshot / stego | `glm-4v` or `gpt-4o` |
| Fast script gen | `groq-llama3` |
| Offline / air-gapped | `qwen-local` (Ollama) |

</details>

---

## Installation

### WSL2 / Ubuntu (Recommended)

```bash
git clone https://github.com/john0123412/PawnLogic.git && cd PawnLogic
python3 -m venv venv && source venv/bin/activate
pip install --upgrade pip && pip install -r requirements.txt
cp .env.example .env   # fill in your API keys — unused providers can be left blank
python main.py
```

### Global `pawn` Command

```bash
chmod +x /path/to/PawnLogic/pawn.sh
ln -sf /path/to/PawnLogic/pawn.sh ~/.local/bin/pawn
# Now run `pawn` from any directory
```

### API Keys

Edit `.env` and add keys for the providers you use. Check status at runtime with `/keys`. Full setup guide: [GUIDE.md → API Key Configuration](GUIDE.md#api-key-configuration)

---

## Support

- **GitHub**: [github.com/john0123412/PawnLogic](https://github.com/john0123412/PawnLogic)
- **Issues**: GitHub Issues for bugs and feature requests
- **Full docs**: [GUIDE.md](GUIDE.md)
