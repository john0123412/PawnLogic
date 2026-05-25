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

- `/chat list [n]` — 列出最近 n 个会话（默认 20）
- `/chat view <id|n>` — 查看完整对话内容
- `/chat export <id|n> [路径]` — 导出为 Markdown 文件
- `/chat find <关键词>` — 跨所有会话全文搜索
- `/chat tag <id|n> <标签>` — 给会话打标签（逗号分隔）
- `/chat untag <id|n> <标签>` — 移除标签
- `/chat bytag <标签>` — 按标签筛选会话
- `/chat link <id1> <id2> [备注]` — 关联两个会话
- `/chat unlink <id1> <id2>` — 取消关联
- `/chat related <id|n>` — 查看关联会话

### 2. 自动命名与动态工作区

- **自动命名**：第 2 轮对话后，Agent 自动生成语义化会话名（如 `python-爬虫` / `ctf-堆溢出`）
- **动态工作区**：每个会话获得独立的 `~/.pawnlogic/workspace/session_<时间戳>_<哈希>/` 目录
- **原子切换**：加载会话时触发重命名 + 反向符号链接 + 指针更新，保证原子性
- **DB 一致性**：所有会话的 `workspace_dir` 字段均经过校验，`/chat load` 不会返回空路径

### 3. 交互体验

- **Ctrl+C 撤回**：输入模式下 Ctrl+C 回滚上一轮并重新显示提示符（Claude Code 风格）
- **Ctrl+D 退出**：通过 EOF 干净退出
- **中断生成**：Agent 生成过程中按 Ctrl+C 立即停止，保留已输出内容

### 4. GSD 工程架构

- **规格驱动规划**：Agent 在任何工具调用前必须输出包含 `<action>` 和 `<verify>` 的 `<plan>` XML
- **原子提交**：每个功能点独立提交，保持 git 历史整洁
- `/init_project [描述]` — 在当前目录生成 `.pawn_state.md`（项目大目标）
- `/state` — 查看当前目录的 `.pawn_state.md`

### 5. 上下文管理

- **滑动窗口**：自动摘要旧历史，防止长任务 API 超时
- `/compact` — 手动压缩：轻量模型总结 + 清空历史
- `/clear` — 清空上下文（保留 Pin 消息）
- `/pin [n]` — 固定最近 n 条消息（默认 2）
- `/unpin` — 解除所有 Pin
- `/context` — 查看上下文大小和 Token 估算

### 6. 知识库 RAG

- `/memorize [主题]` — AI 总结对话 → 存入知识库（每次新会话自动召回）
- `/knowledge [查询]` — 搜索/列出知识条目
- `/forget <id>` — 删除指定知识条目

---

## Provider 与模型管理

### 内置 Provider

| Provider | 环境变量 | 格式 |
|----------|---------|------|
| DeepSeek | `DEEPSEEK_API_KEY` | OpenAI |
| OpenAI | `OPENAI_API_KEY` | OpenAI |
| Anthropic | `ANTHROPIC_API_KEY` | Anthropic |

### 内置模型别名

| 别名 | 模型 ID | 说明 |
|------|---------|------|
| `ds-v4-flash` | deepseek-v4-flash | 默认主力，快速低成本 |
| `ds-v4-pro` | deepseek-v4-pro | 旗舰推理 |
| `gpt-4o` | gpt-4o | 视觉 + 多模态 |
| `gpt-4.1` | gpt-4.1 | 代码与指令跟随 |
| `o3` | o3 | 复杂推理 |
| `claude-sonnet` | claude-sonnet-4-6 | 均衡主力 |
| `claude-haiku` | claude-haiku-4-5-20251001 | 快速低成本 |

### 添加自定义 Provider

**方式一：TUI 面板（推荐）**
```
/provider
```
打开交互式面板，支持：
- 上下键导航，Enter 进入详情
- N 新增 Provider（填写名称、Base URL、格式、API Key）
- D 删除自定义 Provider
- 详情页：更新 Key、拉取模型、测试连通性、管理模型（逐个删除）

**方式二：命令行**
```bash
# 注册 Provider（不注册模型）
/provider add siliconflow https://api.siliconflow.cn/v1/chat/completions SILICON_API_KEY

# 拉取模型列表（交互多选）
/provider fetch siliconflow

# 更新模型列表
/provider update siliconflow

# 删除
/provider remove siliconflow
```

**Base URL 规则**：存储原始 URL，系统在请求时自动补全路径：
- 以 `/chat/completions` 或 `/messages` 结尾 → 直接使用
- 以 `/v1` 结尾 → 追加 `/chat/completions` 或 `/messages`
- 裸域名（如 `https://api.example.com`）→ 追加 `/v1/chat/completions` 或 `/v1/messages`

### 模型过滤机制

`/model` 命令和 Tab 补全只显示**已配置 API Key 的模型**。未配置 Key 的 Provider 下的所有模型自动隐藏。

---

## 安装与部署

### WSL2 / Ubuntu（推荐）

```bash
git clone https://github.com/john0123412/PawnLogic.git && cd PawnLogic
python3 -m venv venv && source venv/bin/activate
pip install --upgrade pip && pip install -r requirements.txt
python main.py
```

首次运行自动进入配置向导，无需手动编辑配置文件。

### 全局 `pawn` 命令

```bash
chmod +x pawn.sh
ln -sf "$(pwd)/pawn.sh" ~/.local/bin/pawn
# 之后在任意目录输入 pawn 即可启动
```

### MCP 工具接入

```bash
cp mcp_configs.example.json ~/.pawnlogic/mcp_configs.json
# 编辑 mcp_configs.json，按需启用服务
# 在 ~/.pawnlogic/.env 中填入对应 Key
python main.py   # MCP 服务自动加载
```

---

## API Key 配置

所有 Key 存储在 `~/.pawnlogic/.env`，**项目目录中不含任何密钥**。

这个文件同时存放：
- **大模型 API Key**（DeepSeek、OpenAI、Anthropic 及所有自定义 Provider）
- **MCP 工具 Key**（Tavily 搜索、Browserbase 等）

格式示例：

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

`mcp_configs.json` 中通过 `${VAR_NAME}` 引用 `.env` 里的 Key，两者解耦。

运行时查看 Key 状态：
```
/keys
```

---

## 命令参考

### 对话控制

| 命令 | 说明 |
|------|------|
| `/model [别名]` | 切换模型（只显示已配置 Key 的模型） |
| `/mode` | 切换 USER / DEV 输出模式 |
| `/clear` | 清空上下文（保留 Pin 消息） |
| `/context` | 上下文大小 / Token 估算 |
| `/pin [n]` | 固定最近 n 条消息（默认 2） |
| `/unpin` | 解除所有 Pin |
| `/undo [n]` | 撤回最近 n 轮（默认 1） |
| `/compact` | 压缩上下文 |
| `/think <问题>` | 单次深度推理 |
| `/cd <路径>` | 切换工作目录 |
| `/file <路径>` | 载入文件到上下文 |
| `/history` | 消息历史（含序号） |

### Provider 管理

| 命令 | 说明 |
|------|------|
| `/provider` | 打开交互式 TUI 面板 |
| `/provider list` | 列出所有 Provider 状态 |
| `/provider add <名称> <url> [anthropic]` | 注册 Provider |
| `/provider fetch <名称>` | 拉取模型列表（交互多选） |
| `/provider update <名称>` | 重新拉取模型列表 |
| `/provider remove <名称>` | 删除自定义 Provider |
| `/provider test <模型>` | 测试连通性 |
| `/keys` | 查看所有 Key 状态 |
| `/setkey` | 重新运行 Key 配置向导 |

### 会话持久化

| 命令 | 说明 |
|------|------|
| `/save [名称]` | 保存当前会话 |
| `/load <名称\|n>` | 加载历史会话 |
| `/sessions` | 列出所有会话 |
| `/del <名称\|n>` | 删除指定会话 |
| `/rename <n> <名称>` | 重命名会话 |
| `/resume [n]` | 恢复会话并显示历史 |

### 知识库

| 命令 | 说明 |
|------|------|
| `/memorize [主题]` | AI 总结 → 存入知识库 |
| `/knowledge [查询]` | 搜索/列出知识条目 |
| `/forget <id>` | 删除知识条目 |

### 算力档位

| 命令 | 说明 |
|------|------|
| `/low` | 日常模式：tokens=4k, ctx=40k, iter=10 |
| `/mid` | 开发模式：tokens=8k, ctx=150k, iter=30（默认） |
| `/deep` | 深度模式：tokens=32k, ctx=400k, iter=50 |
| `/max` | 极限模式：tokens=32k, ctx=600k, iter=100 |
| `/normal` | 重置到 /mid |

### 工具状态

| 命令 | 说明 |
|------|------|
| `/webstatus` | Jina / Pandoc / Lynx 状态 |
| `/pwnenv` | CTF 工具链完整性检查 |
| `/docker` | Docker 容器管理 |
| `/stats` | 本次会话 Token 用量统计 |

---

## 使用示例

### 接入第三方 API

```
/provider add myrelay https://api.myrelay.com/v1/chat/completions MYRELAY_API_KEY
/provider fetch myrelay
# 在弹出的多选界面中选择需要的模型，Enter 确认
/model gpt-4o   # 切换到刚注册的模型
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
/init_project 实现一个命令行 JSON 美化工具
→ Agent 自动 plan → write → verify → git commit
```

---

## 架构说明

### 项目代码结构

```
PawnLogic/
├── main.py              # 入口、命令解析、交互循环
├── config/              # 配置包
│   ├── providers.py     # Provider 与模型注册表
│   ├── tiers.py         # 算力档位预设
│   ├── security.py      # 安全名单
│   ├── sandbox.py       # 沙箱配置
│   └── phases.py        # MoE 路由表
├── core/                # 核心模块
│   ├── session.py       # Agentic Loop
│   ├── memory.py        # SQLite 持久化
│   ├── state.py         # 运行时状态
│   ├── api_client.py    # 双格式 API 客户端
│   ├── provider_tui.py  # Provider 管理 TUI
│   └── mcp_client_manager.py  # MCP 客户端
├── tools/               # 工具实现
└── skills/              # 本地技能包
```

### 运行时数据（`~/.pawnlogic/`）

```
~/.pawnlogic/
├── .env                    # API 密钥
├── custom_providers.json   # 自定义 Provider（不含密钥）
├── pawn.db                 # SQLite 数据库
├── mcp_configs.json        # MCP 服务声明
├── workspace/              # Agent 工作区
└── logs/                   # 审计日志
```

---

## 常见问题

**Q: 添加了 Provider 但 `/model` 看不到新模型？**
A: 需要先运行 `/provider fetch <名称>` 拉取模型列表，然后在多选界面选择并确认。

**Q: Test Connection 失败但 fetch 成功？**
A: 正常现象。`/v1/models` 是 GET 请求，很多中转服务对它不鉴权。Test Connection 发送真实 chat 请求，用的是通用测试模型 ID，部分中转不支持该 ID。只要 fetch 成功、Key 有效，实际使用不受影响。

**Q: 切换到自定义模型后报 HTTP 305？**
A: Base URL 格式问题。系统会自动补全路径，但如果已有旧数据，可通过 `/provider` → 详情页 → Update API Key 重新保存触发修复，或直接编辑 `~/.pawnlogic/custom_providers.json`。

**Q: 如何彻底删除一个自定义模型？**
A: `/provider` → 选择对应 Provider → Enter → Manage Models → 上下键选择 → D 删除。

**Q: API Key 在哪里？**
A: `~/.pawnlogic/.env`，不在项目目录，不会被 git 追踪。

**Q: 支持 Ollama 本地模型吗？**
A: 支持。通过 `/provider add` 注册，Base URL 填 `http://localhost:11434`，Key 留空或填任意字符串。
