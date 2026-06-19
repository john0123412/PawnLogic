# PawnLogic — 完整使用指南

> 功能、命令、模型、架构、常见问题的完整中文参考手册。

---

## 目录

1. [功能概览](#功能概览)
2. [Provider 与模型管理](#provider-与模型管理)
3. [安装与部署](#安装与部署)
4. [API Key 配置](#api-key-配置)
5. [命令参考](#命令参考)
6. [使用示例](#使用示例)
7. [架构说明](#架构说明)
8. [常见问题](#常见问题)

---

## 功能概览

### 1. 会话管理

| 命令 | 说明 |
|------|------|
| `/chat list [n]` | 列出最近 n 个会话（默认 20） |
| `/chat view <id\|n>` | 查看完整对话内容 |
| `/chat export <id\|n> [path]` | 导出为 Markdown 文件 |
| `/chat find <keyword>` | 跨所有会话全文搜索 |
| `/chat tag <id\|n> <tags>` | 给会话打标签（逗号分隔） |
| `/chat untag <id\|n> <tags>` | 移除标签 |
| `/chat bytag <tag>` | 按标签筛选会话 |
| `/chat link <id1> <id2>` | 关联两个会话 |
| `/chat related <id\|n>` | 查看关联会话 |

### 2. 自动命名与动态工作区

- **自动命名**：第 2 轮对话后，Agent 自动生成语义化会话名（如 `ctf-heap-exploit`）
- **动态工作区**：每个会话获得独立的 `~/.pawnlogic/workspace/session_<时间戳>_<哈希>/` 目录
- **原子切换**：加载会话时触发重命名 + 反向符号链接 + DB 更新，保证原子性

### 3. 交互体验

- **Ctrl+C 撤回**：输入模式下 Ctrl+C 回滚上一轮并重新显示提示符（Claude Code 风格）
- **Ctrl+D 退出**：通过 EOF 干净退出
- **中断生成**：Agent 生成过程中按 Ctrl+C 立即停止，保留已输出内容

### 4. GSD 工程架构

- **规格驱动规划**：Agent 在任何工具调用前必须输出包含 `<action>` 和 `<verify>` 的 `<plan>` XML
- `/init_project [desc]` — 在当前目录生成 `.pawn_state.md`
- `/state` — 查看当前目录的 `.pawn_state.md`

### 5. 上下文管理

- **滑动窗口**：自动摘要旧历史，防止长任务 API 超时
- `/compact` — 手动压缩上下文
- `/clear` — 清空上下文（保留 Pin 消息）
- `/pin [n]` — 固定最近 n 条消息（默认 2）
- `/context` — 查看上下文大小和 Token 估算

### 6. 知识库 RAG

- `/memorize [topic]` — AI 总结对话 → 存入知识库
- `/knowledge [query]` — 搜索或列出知识条目
- `/forget <id>` — 删除指定知识条目

---

## Provider 与模型管理

### 内置 Provider

| Provider  | 环境变量               | 格式      |
|-----------|----------------------|-----------|
| DeepSeek  | `DEEPSEEK_API_KEY`   | OpenAI    |
| OpenAI    | `OPENAI_API_KEY`     | OpenAI    |
| Anthropic | `ANTHROPIC_API_KEY`  | Anthropic |

### 内置模型别名

| 别名            | 模型 ID                     | 说明               |
|-----------------|----------------------------|--------------------|
| `ds-v4-flash`   | deepseek-v4-flash          | 默认主力，快速低成本 |
| `ds-v4-pro`     | deepseek-v4-pro            | 旗舰推理           |
| `gpt-5.5`       | gpt-5.5                    | OpenAI 最新旗舰    |
| `gpt-5.4`       | gpt-5.4                    | 编程与专业工作     |
| `gpt-5.4-mini`  | gpt-5.4-mini               | 轻量高效           |
| `gpt-5.4-nano`  | gpt-5.4-nano               | OpenAI 最低成本模型 |
| `gpt-4o`        | gpt-4o                     | 视觉 + 多模态      |
| `gpt-4.1`       | gpt-4.1                    | 代码与指令跟随     |
| `o3`            | o3                         | 复杂推理           |
| `claude-opus`   | claude-opus-4-6            | 前沿推理旗舰       |
| `claude-sonnet` | claude-sonnet-4-6          | 均衡主力           |
| `claude-haiku`  | claude-haiku-4-5-20251001  | 快速低成本         |

### 添加自定义 Provider

**方式一：TUI 面板（推荐）**
```
/provider
```
- 上下键导航，Enter 进入详情
- `N` 新增 Provider
- `D` 删除自定义 Provider
- 详情页：更新 Key、active/deactivate、拉取模型、测试连通性、管理模型

**方式二：命令行**
```bash
/provider add myrelay https://api.myrelay.com/v1/chat/completions MYRELAY_API_KEY
/provider fetch myrelay    # 交互多选
/provider activate myrelay # 让选中的模型显示在 /model
/provider update myrelay   # 重新拉取
/provider remove myrelay
```

**Base URL 规则：**
- 以 `/chat/completions` 或 `/messages` 结尾 → 直接使用
- 以 `/v1` 结尾 → 追加端点后缀
- 裸域名 → 追加 `/v1/chat/completions` 或 `/v1/messages`

### 模型过滤机制

`/model` 命令和 Tab 补全只显示 DeepSeek，以及 active 且已配置 API Key 的 Provider。自定义 Provider 默认 inactive，拉取并选择模型后需要运行 `/provider activate <name>`。

---

## 安装与部署

### 系统要求

- Linux 或 WSL2
- Python 3.10+
- `pip`
- 只有源码 checkout 或开发时才需要 `git`
- 如需全局 `pawn` 命令，`~/.local/bin` 需要在 `PATH` 中

### WSL2 / Ubuntu（推荐）

包安装：

```bash
pip install pawnlogic
pawn
```

一行安装脚本：

```bash
curl -fsSL https://raw.githubusercontent.com/john0123412/PawnLogic/main/install.sh | bash
pawn
```

安装脚本会创建 `~/.local/share/pawnlogic/venv`，通过 pip 安装正式包，并写入
`~/.local/bin/pawn`。

源码 checkout 开发安装：

```bash
git clone https://github.com/john0123412/PawnLogic.git && cd PawnLogic
python3 -m venv venv && source venv/bin/activate
pip install --upgrade pip && pip install -e ".[dev]"
pawn
```

首次运行自动进入配置向导。

### 运行时输出模式

```bash
pawn                              # 用户友好的交互模式
pawn --debug                      # 显示详细诊断信息的交互模式
pawn --eval "your prompt"         # 单次执行后退出
pawn --eval "prompt" --json       # 机器可读 JSON 输出
```

默认 `pawn` 会隐藏原始工具参数、解析器诊断、详细 API 错误和 reasoning 流，只显示
`Thinking...` 或简短工具进度等状态。排查 Provider 连通性、解析器行为、工具参数
或底层 API 失败时，使用 `pawn --debug`。`--json` 用于配合 `--eval` 输出脚本可读
结果，不是 debug 显示模式。交互会话中，`/mode` 会在用户友好输出和 debug 输出之间切换。

### 源码 checkout 启动器备用方式

```bash
./pawn.sh
```

如果提示 `pawn: command not found`，运行：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### 可选 CTF Skill Pack

安装 CTF 工具依赖：

```bash
pip install "pawnlogic[ctf]"
```

这个 extra 会安装 `pwntools`、`ROPgadget`、`ropper` 等工具依赖；它不会把第三方
skill-pack Markdown 安装进 PyPI 包。CTF skill pack 是可选扩展资产，需要显式安装到
`~/.pawnlogic/skills`，例如：

```bash
/sp install <repo_url>
```

git-backed skill pack 安装只接受 `https://`、`ssh://` 或
`git@host:owner/repo.git` remote。

只有在 `THIRD_PARTY_NOTICES.md` 中记录了上游许可证、来源 URL、commit 和必要 notice
之后，才可以从本仓库再分发第三方 CTF skill 内容。

### MCP 工具接入

pip 或一行安装脚本用户，PawnLogic 启动时会在 `~/.pawnlogic/` 下生成可编辑模板：

```bash
pawn   # 生成 ~/.pawnlogic/env.example 和 ~/.pawnlogic/mcp_configs.example.json
cp ~/.pawnlogic/mcp_configs.example.json ~/.pawnlogic/mcp_configs.json
# 编辑 ~/.pawnlogic/mcp_configs.json，并通过 /setkey 或 ~/.pawnlogic/.env 填入对应 Key
pawn   # mcp_configs.json 存在时，MCP 服务会自动加载
```

源码 checkout 用户也可以直接复制仓库模板：

```bash
cp mcp_configs.example.json ~/.pawnlogic/mcp_configs.json
```

示例配置默认禁用外部 `fetch` MCP，因为 `uvx mcp-server-fetch` 可能在启动时访问 PyPI。
请优先使用 PawnLogic 内置的 `fetch_url`；只有明确需要时，再手动启用该 MCP 并允许网络安装。

---

## API Key 配置

所有 Key 存储在 `~/.pawnlogic/.env`，**项目目录中不含任何密钥**。
pip 或一行安装脚本用户，`pawn` 会生成 `~/.pawnlogic/env.example` 作为可编辑模板。
你可以使用首次启动向导、运行 `/setkey`，或手动复制模板。Provider 配置流程不会把 Key
写入 shell 启动文件：

```bash
cp ~/.pawnlogic/env.example ~/.pawnlogic/.env
chmod 600 ~/.pawnlogic/.env
```

```bash
# 大模型
DEEPSEEK_API_KEY=sk-...
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# MCP 工具
TAVILY_API_KEY=tvly-...

# 自定义 Provider（由向导自动写入）
MYRELAY_API_KEY=...
```

`mcp_configs.json` 通过 `${VAR_NAME}` 引用 `.env` 里的 Key，两者解耦。

运行时查看 Key 状态：`/keys`

---

## 命令参考

### 对话控制

| 命令 | 说明 |
|------|------|
| `/model [alias]` | 切换模型（只显示 active 且已配置 Key 的 Provider） |
| `/mode` | 切换用户友好 / debug 输出 |
| `/clear` | 清空上下文（保留 Pin 消息） |
| `/context` | 上下文大小 / Token 估算 |
| `/pin [n]` | 固定最近 n 条消息（默认 2） |
| `/unpin` | 解除所有 Pin |
| `/undo [n]` | 撤回最近 n 轮（默认 1） |
| `/compact` | 压缩上下文 |
| `/think <prompt>` | 单次深度推理 |
| `/cd <path>` | 切换工作目录 |
| `/file <path>` | 载入文件到上下文 |
| `/history` | 消息历史（含序号） |

### Provider 管理

| 命令 | 说明 |
|------|------|
| `/provider` | 打开交互式 TUI 面板 |
| `/provider list` | 列出所有 Provider 状态 |
| `/provider add <name> <url> <KEY>` | 注册 Provider |
| `/provider fetch <name>` | 拉取模型列表（交互多选） |
| `/provider update <name>` | 重新拉取模型列表 |
| `/provider activate <name>` | 让该 Provider 的已选模型显示在 `/model` |
| `/provider deactivate <name>` | 从 `/model` 隐藏该 Provider 的模型 |
| `/provider remove <name>` | 删除自定义 Provider |
| `/provider test <model>` | 测试连通性 |
| `/keys` | 查看所有 Key 状态 |
| `/setkey` | 重新运行 Key 配置向导 |

### 会话持久化

| 命令 | 说明 |
|------|------|
| `/save [name]` | 保存当前会话 |
| `/load <name\|n>` | 加载历史会话 |
| `/sessions` | 列出所有会话 |
| `/del <name\|n>` | 删除指定会话 |
| `/rename <n> <name>` | 重命名会话 |
| `/resume [n]` | 恢复会话并显示历史 |

### 算力档位

| 命令 | Token | Ctx | Iter | 场景 |
|------|-------|-----|------|------|
| `/low` | 4k | 40k | 10 | 日常 |
| `/mid` | 8k | 150k | 30 | 开发（默认） |
| `/deep` | 32k | 400k | 50 | 全火力 |
| `/max` | 32k | 600k | 100 | 极限 |

### 工具状态

| 命令 | 说明 |
|------|------|
| `/webstatus` | Jina / Pandoc / Lynx 状态 |
| `/pwnenv` | CTF 工具链完整性检查 |
| `/docker` | Docker 容器管理 |
| `/stats` | 本次会话 Token 用量统计 |

Docker 文件挂载默认限制在 workspace 内，包括 read-only 挂载。挂载外部只读 challenge
文件需要显式设置 `allow_host_read_mount`。

### CTF 工作流

| 命令 | 说明 |
|------|------|
| `/ctf init <name>` | 在当前 workspace 初始化 CTF metadata |
| `/ctf status` | 查看当前 CTF metadata |
| `/ctf artifact <path-or-note>` | 记录 challenge artifact |
| `/ctf remote <host:port-or-url>` | 记录远程目标 |
| `/ctf flag <candidate>` | 记录 flag candidate |
| `/ctf solved [confirmed-flag]` | 确认 flag 后将题目标记为 solved |
| `/ctf writeup` | 导出 Markdown writeup 草稿 |

---

## 使用示例

### 接入第三方 API

```
/provider add myrelay https://api.myrelay.com/v1/chat/completions MYRELAY_API_KEY
/provider fetch myrelay
# Space 选中，Enter 确认
/provider activate myrelay
/model <alias shown by /provider fetch>
```

### 视觉分析

```
分析截图 ./screenshot.png，提取其中的代码并修复 bug
```

### CTF Pwn

```
/model ds-v4-pro
分析 ./challenge，用 pwn_debug 在 main 断点查看寄存器状态
```

### 项目工程（GSD）

```
/init_project Build a CLI JSON formatter
→ Agent: plan → write → verify → git commit
```

---

## 架构说明

### 代码结构

```
PawnLogic/
├── main.py              # 源码 checkout 兼容薄包装
├── pawnlogic/cli.py     # pawn 与 python -m pawnlogic 共用的唯一 CLI 运行实现
├── config/
│   ├── paths.py         # ★ 版本号唯一定义处
│   ├── providers.py     # Provider 与模型注册表
│   ├── tiers.py         # 算力档位预设
│   ├── security.py      # 安全名单
│   ├── sandbox.py       # 沙箱配置
│   └── phases.py        # MoE 路由表
├── core/
│   ├── session.py       # Agentic Loop
│   ├── memory.py        # SQLite 持久化
│   ├── api_client.py    # 双格式 API 客户端
│   ├── naming.py        # 自动命名与工作区
│   └── provider_tui.py  # Provider 管理 TUI
├── tools/               # 工具实现
└── skills/              # 源码 checkout 技能包（不随 PyPI wheel 发布）
```

### 运行时数据（`~/.pawnlogic/`）

```
~/.pawnlogic/
├── .env                    # API 密钥（不提交）
├── custom_providers.json   # 自定义 Provider（不含密钥）
├── pawn.db                 # SQLite 数据库
├── mcp_configs.json        # MCP 服务声明
├── skills/                 # 可选用户安装技能包
├── workspace/              # Agent 工作区
└── logs/                   # 审计日志
```

---

## 常见问题

**Q: 添加了 Provider 但 `/model` 看不到新模型？**  
A: 需要先配置 Key，运行 `/provider fetch <name>` 拉取并选择模型，再运行 `/provider activate <name>`。`/model` 会隐藏 inactive Provider。

**Q: Test Connection 失败但 fetch 成功？**  
A: Fetch 只读取 `/v1/models`；Test Connection 会用已加载的聊天模型发送一次最小请求。如果还没加载聊天模型，请先 fetch。若仍失败，说明该 Provider 不接受当前模型、Key 或 Base URL。

**Q: 切换到自定义模型后报 HTTP 305？**  
A: Base URL 格式问题。通过 `/provider` 详情页重新保存，或直接编辑 `~/.pawnlogic/custom_providers.json`。

**Q: 如何彻底删除一个自定义模型？**  
A: `/provider` → 选择 Provider → Enter → Manage Models → 上下键 → `D` 删除。

**Q: API Key 在哪里？**  
A: `~/.pawnlogic/.env`，不在项目目录，不会被 git 追踪。

**Q: 安装后提示 `pawn: command not found`？**  
A: 把用户命令目录加入 PATH：`export PATH="$HOME/.local/bin:$PATH"`。

**Q: 启动提示需要 Python 3.10+？**  
A: 安装更新版本的 Python，并用该版本重新创建虚拟环境。

**Q: 浏览器工具提示缺少模块？**  
A: 安装可选浏览器依赖：`pip install 'pawnlogic[browser]'`，然后运行 `patchright install chromium`。

**Q: WSL2 下 PATH 或工具检测异常？**  
A: 尽量从 Linux 文件系统启动，不要在 `/mnt/c/...` 下运行，并让 Linux 工具路径排在 Windows 路径前面。

**Q: 支持 Ollama 本地模型吗？**  
A: 支持。通过 `/provider add` 注册，Base URL 填 `http://localhost:11434`，Key 留空或填任意字符串。
