# PawnLogic — Full Reference Guide / 完整使用指南

> English and Chinese / 中英双语参考手册

---

## Table of Contents / 目录

1. [Feature Overview / 功能概览](#feature-overview--功能概览)
2. [Providers & Models / Provider 与模型管理](#providers--models--provider-与模型管理)
3. [Installation / 安装与部署](#installation--安装与部署)
4. [API Key Setup / API Key 配置](#api-key-setup--api-key-配置)
5. [Command Reference / 命令参考](#command-reference--命令参考)
6. [Examples / 使用示例](#examples--使用示例)
7. [Architecture / 架构说明](#architecture--架构说明)
8. [FAQ / 常见问题](#faq--常见问题)

---

## Feature Overview / 功能概览

### 1. Session Management / 会话管理

| Command | Description / 说明 |
|---------|---------------------|
| `/chat list [n]` | List recent n sessions (default 20) / 列出最近 n 个会话 |
| `/chat view <id\|n>` | View full conversation / 查看完整对话内容 |
| `/chat export <id\|n> [path]` | Export to Markdown / 导出为 Markdown |
| `/chat find <keyword>` | Full-text search across all sessions / 跨会话全文搜索 |
| `/chat tag <id\|n> <tags>` | Tag a session (comma-separated) / 打标签 |
| `/chat untag <id\|n> <tags>` | Remove tags / 移除标签 |
| `/chat bytag <tag>` | Filter by tag / 按标签筛选 |
| `/chat link <id1> <id2>` | Link two sessions / 关联两个会话 |
| `/chat related <id\|n>` | View linked sessions / 查看关联会话 |

### 2. Auto-Naming & Dynamic Workspace / 自动命名与动态工作区

- **Auto-naming** — after turn 2, the agent generates a semantic session name (e.g. `ctf-heap-exploit`)  
  **自动命名** — 第 2 轮对话后自动生成语义化会话名
- **Dynamic workspace** — each session gets `~/.pawnlogic/workspace/session_<ts>_<hash>/`  
  **动态工作区** — 每个会话拥有独立工作目录
- **Atomic swap** — workspace rename + symlink + DB update in one operation  
  **原子切换** — 重命名 + 反向符号链接 + DB 更新同步完成

### 3. UX / 交互体验

- **Ctrl+C** — cancels current input and rolls back last turn (Claude Code style) / 回滚上一轮
- **Ctrl+D** — clean exit / 干净退出
- **Interrupt generation** — Ctrl+C during agent output stops immediately / 中断生成立即停止

### 4. Spec-Driven Planning (GSD) / 规格驱动规划

- Agent must emit a `<plan>` XML block with `<action>` and `<verify>` before any tool call  
  每次工具调用前必须输出含 `<action>` 和 `<verify>` 的 `<plan>` XML
- `/init_project [desc]` — create `.pawn_state.md` in current directory / 生成项目状态文件
- `/state` — view current `.pawn_state.md` / 查看项目状态

### 5. Context Management / 上下文管理

- **Sliding window** — auto-summarizes old history to prevent API timeouts  
  **滑动窗口** — 自动摘要旧历史防止超时
- `/compact` — manually compress context / 手动压缩上下文
- `/clear` — clear context, keep pinned messages / 清空上下文，保留 Pin
- `/pin [n]` — pin last n messages (default 2) / 固定最近 n 条
- `/context` — show context size and token estimate / 查看大小和 Token 估算

### 6. Knowledge Base RAG / 知识库

- `/memorize [topic]` — AI summarizes conversation → saves to knowledge base / AI 总结→知识库
- `/knowledge [query]` — search or list knowledge entries / 搜索/列出知识条目
- `/forget <id>` — delete a knowledge entry / 删除知识条目

---

## Providers & Models / Provider 与模型管理

### Built-in Providers / 内置 Provider

| Provider | Env Var | Format |
|----------|---------|--------|
| DeepSeek | `DEEPSEEK_API_KEY` | OpenAI |
| OpenAI   | `OPENAI_API_KEY`   | OpenAI |
| Anthropic | `ANTHROPIC_API_KEY` | Anthropic |

### Built-in Model Aliases / 内置模型别名

| Alias | Model ID | Notes |
|-------|----------|-------|
| `ds-v4-flash` | deepseek-v4-flash | Default, fast & cheap / 默认主力 |
| `ds-v4-pro`   | deepseek-v4-pro   | Flagship reasoning / 旗舰推理 |
| `gpt-4o`      | gpt-4o            | Vision + multimodal / 视觉多模态 |
| `gpt-4.1`     | gpt-4.1           | Code & instruction following |
| `o3`          | o3                | Complex reasoning / 复杂推理 |
| `claude-sonnet` | claude-sonnet-4-6 | Balanced / 均衡主力 |
| `claude-haiku`  | claude-haiku-4-5-20251001 | Fast & cheap / 快速低成本 |

### Adding a Custom Provider / 添加自定义 Provider

**Option A — Interactive TUI (recommended) / TUI 面板（推荐）**
```
/provider
```
- Arrow keys to navigate, Enter for details / 上下键导航，Enter 进详情
- `N` — add new provider / 新增
- `D` — delete provider / 删除
- Detail view: update key, fetch models, test connectivity / 详情：更新 Key、拉取模型、测试连通性

**Option B — CLI / 命令行**
```bash
/provider add myrelay https://api.myrelay.com/v1/chat/completions MYRELAY_API_KEY
/provider fetch myrelay    # interactive multi-select / 交互多选
/provider update myrelay   # re-fetch model list / 重新拉取
/provider remove myrelay
```

**Base URL rules / Base URL 规则：**
- Ends with `/chat/completions` or `/messages` → used as-is / 直接使用
- Ends with `/v1` → appends endpoint suffix / 追加端点后缀
- Bare domain → appends `/v1/chat/completions` or `/v1/messages` / 补全完整路径

### Model Visibility / 模型可见性

`/model` and Tab completion only show models whose API key is configured.  
`/model` 命令和 Tab 补全只显示**已配置 API Key 的模型**。

---

## Installation / 安装与部署

### WSL2 / Ubuntu (recommended / 推荐)

```bash
git clone https://github.com/john0123412/PawnLogic.git && cd PawnLogic
python3 -m venv venv && source venv/bin/activate
pip install --upgrade pip && pip install -r requirements.txt
python main.py
```

The first run launches the configuration wizard automatically.  
首次运行自动进入配置向导，无需手动编辑配置文件。

### Global `pawn` command / 全局 `pawn` 命令

```bash
chmod +x pawn.sh
ln -sf "$(pwd)/pawn.sh" ~/.local/bin/pawn
# Then run `pawn` from any directory / 之后在任意目录输入 pawn 即可启动
```

### MCP Tools / MCP 工具接入

```bash
cp mcp_configs.example.json ~/.pawnlogic/mcp_configs.json
# Edit mcp_configs.json and add keys to ~/.pawnlogic/.env
# 编辑 mcp_configs.json，在 ~/.pawnlogic/.env 中填入对应 Key
python main.py   # MCP servers load automatically / 自动加载
```

---

## API Key Setup / API Key 配置

All keys are stored in `~/.pawnlogic/.env`. **No secrets in the project directory.**  
所有 Key 存储在 `~/.pawnlogic/.env`，**项目目录中不含任何密钥**。

```bash
# LLM providers / 大模型
DEEPSEEK_API_KEY=sk-...
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# MCP tools / MCP 工具
TAVILY_API_KEY=tvly-...

# Custom providers (written by wizard) / 自定义（向导自动写入）
MYRELAY_API_KEY=...
```

`mcp_configs.json` references keys via `${VAR_NAME}`, keeping configs and secrets decoupled.  
`mcp_configs.json` 通过 `${VAR_NAME}` 引用 `.env`，两者解耦。

Check key status at runtime: `/keys`  
运行时查看状态：`/keys`

---

## Command Reference / 命令参考

### Conversation Control / 对话控制

| Command | Description / 说明 |
|---------|---------------------|
| `/model [alias]` | Switch model (only shows configured) / 切换模型 |
| `/mode` | Toggle USER / DEV output mode / 切换输出模式 |
| `/clear` | Clear context, keep pins / 清空上下文 |
| `/context` | Context size + token estimate / 上下文大小 |
| `/pin [n]` | Pin last n messages / 固定最近 n 条 |
| `/unpin` | Unpin all / 解除所有 Pin |
| `/undo [n]` | Roll back last n turns / 撤回最近 n 轮 |
| `/compact` | Summarize + compress context / 压缩上下文 |
| `/think <prompt>` | Single deep-reasoning turn / 单次深度推理 |
| `/cd <path>` | Change working directory / 切换工作目录 |
| `/file <path>` | Load file into context / 载入文件 |
| `/history` | Message history with sequence numbers / 消息历史 |

### Provider Management / Provider 管理

| Command | Description / 说明 |
|---------|---------------------|
| `/provider` | Open interactive TUI / 打开 TUI 面板 |
| `/provider list` | List all providers / 列出所有 Provider |
| `/provider add <name> <url> <KEY>` | Register provider / 注册 Provider |
| `/provider fetch <name>` | Fetch model list / 拉取模型列表 |
| `/provider update <name>` | Re-fetch model list / 重新拉取 |
| `/provider remove <name>` | Delete custom provider / 删除 |
| `/provider test <model>` | Test connectivity / 测试连通性 |
| `/keys` | Show all key status / 查看 Key 状态 |
| `/setkey` | Re-run key wizard / 重新运行配置向导 |

### Session Persistence / 会话持久化

| Command | Description / 说明 |
|---------|---------------------|
| `/save [name]` | Save current session / 保存当前会话 |
| `/load <name\|n>` | Load session / 加载历史会话 |
| `/sessions` | List all sessions / 列出所有会话 |
| `/del <name\|n>` | Delete session / 删除会话 |
| `/rename <n> <name>` | Rename session / 重命名 |
| `/resume [n]` | Resume session with history / 恢复并显示历史 |

### Compute Tiers / 算力档位

| Command | Tokens | Ctx | Iter | Use Case |
|---------|--------|-----|------|----------|
| `/low`  | 4k | 40k | 10 | Daily / 日常 |
| `/mid`  | 8k | 150k | 30 | Dev / 开发（默认）|
| `/deep` | 32k | 400k | 50 | Full power / 全火力 |
| `/max`  | 32k | 600k | 100 | Extreme / 极限 |

### Tool Status / 工具状态

| Command | Description / 说明 |
|---------|---------------------|
| `/webstatus` | Jina / Pandoc / Lynx status |
| `/pwnenv` | CTF toolchain integrity check / CTF 工具链检查 |
| `/docker` | Docker container management / Docker 容器管理 |
| `/stats` | Session token usage / 会话 Token 用量 |

---

## Examples / 使用示例

### Add a third-party API / 接入第三方 API

```
/provider add myrelay https://api.myrelay.com/v1/chat/completions MYRELAY_API_KEY
/provider fetch myrelay
# Select models with Space, confirm with Enter / Space 选中，Enter 确认
/model myrelay/gpt-4o
```

### Vision analysis / 视觉分析

```
Analyze screenshot ./screenshot.png, extract the code and fix the bug.
分析截图 ./screenshot.png，提取其中的代码并修复 bug
```

### CTF Pwn

```
/model ds-v4-pro
Analyze ./challenge, use pwn_debug to inspect registers at main breakpoint.
分析 ./challenge，用 pwn_debug 在 main 断点查看寄存器状态
```

### GSD project workflow / 项目工程

```
/init_project Build a CLI JSON formatter
→ Agent: plan → write → verify → git commit
```

---

## Architecture / 架构说明

### Code Structure / 代码结构

```
PawnLogic/
├── main.py              # Entry point, REPL loop / 入口、交互循环
├── config/              # Config package / 配置包
│   ├── paths.py         # ★ VERSION defined here / 版本号唯一定义处
│   ├── providers.py     # Provider & model registry / Provider 与模型注册表
│   ├── tiers.py         # Compute tier presets / 算力档位
│   ├── security.py      # Safety patterns & blacklists / 安全名单
│   ├── sandbox.py       # Sandbox config / 沙箱配置
│   └── phases.py        # MoE tool routing / MoE 路由表
├── core/                # Core modules / 核心模块
│   ├── session.py       # Agentic Loop
│   ├── memory.py        # SQLite persistence / SQLite 持久化
│   ├── api_client.py    # Dual-format API client / 双格式 API 客户端
│   ├── naming.py        # Auto-naming & workspace / 自动命名
│   └── provider_tui.py  # Provider TUI
├── tools/               # Tool implementations / 工具实现
└── skills/              # Local skill packs / 本地技能包
```

### Runtime Data / 运行时数据 (`~/.pawnlogic/`)

```
~/.pawnlogic/
├── .env                    # API keys (never committed) / API 密钥
├── custom_providers.json   # Custom providers, no keys / 自定义 Provider（不含密钥）
├── pawn.db                 # SQLite database / SQLite 数据库
├── mcp_configs.json        # MCP server declarations / MCP 服务声明
├── workspace/              # Agent working directories / Agent 工作区
└── logs/                   # Audit logs / 审计日志
```

---

## FAQ / 常见问题

**Q: Added a provider but `/model` doesn't show new models?**  
**Q: 添加了 Provider 但 `/model` 看不到新模型？**  
A: Run `/provider fetch <name>` to pull the model list, then select models in the interactive prompt.  
A: 需要先运行 `/provider fetch <名称>` 拉取模型列表，然后在多选界面选择并确认。

---

**Q: Test Connection fails but fetch succeeds?**  
**Q: Test Connection 失败但 fetch 成功？**  
A: Normal. `/v1/models` is a GET request that many relay services don't authenticate. Test Connection sends a real chat request using a generic model ID that some relays don't support. As long as fetch works and the key is valid, actual usage is unaffected.  
A: 正常现象。`/v1/models` 很多中转服务不鉴权。只要 fetch 成功、Key 有效，实际使用不受影响。

---

**Q: HTTP 305 after switching to a custom model?**  
**Q: 切换到自定义模型后报 HTTP 305？**  
A: Base URL format issue. Go to `/provider` → detail view → Update API Key to re-save and trigger a fix. Or edit `~/.pawnlogic/custom_providers.json` directly.  
A: Base URL 格式问题。通过 `/provider` 详情页重新保存，或直接编辑 `custom_providers.json`。

---

**Q: How do I delete a specific custom model?**  
**Q: 如何彻底删除一个自定义模型？**  
A: `/provider` → select provider → Enter → Manage Models → arrow keys → `D` to delete.  
A: `/provider` → 选择 Provider → Enter → Manage Models → 上下键 → `D` 删除。

---

**Q: Where are my API keys stored?**  
**Q: API Key 在哪里？**  
A: `~/.pawnlogic/.env` — outside the project directory, never tracked by git.  
A: `~/.pawnlogic/.env`，不在项目目录，不会被 git 追踪。

---

**Q: Does it support local Ollama models?**  
**Q: 支持 Ollama 本地模型吗？**  
A: Yes. Use `/provider add`, set Base URL to `http://localhost:11434`, leave the key empty or use any placeholder string.  
A: 支持。通过 `/provider add` 注册，Base URL 填 `http://localhost:11434`，Key 留空或填任意字符串。
