[English](README.md) | **[中文](README_zh-CN.md)**

# PawnLogic

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/pypi/v/pawnlogic.svg?label=version)](https://pypi.org/project/pawnlogic/)
[![PyPI](https://img.shields.io/pypi/v/pawnlogic.svg?cache=no)](https://pypi.org/project/pawnlogic/)
[![CI](https://github.com/john0123412/PawnLogic/actions/workflows/main_ci.yml/badge.svg)](https://github.com/john0123412/PawnLogic/actions/workflows/main_ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20WSL2-lightgrey.svg)]()

PawnLogic 是一个终端优先的自主 AI Agent，支持多 Provider 模型路由、持久化记忆、真实本地工具执行、MCP 集成和面向 CTF 的工具链。当前公开发布版本是 **0.3.1**。版本 **0.3.2** 是尚未发布的候选版本，用于有界的双 worker 委派。

## 系统要求

- Linux 或 WSL2
- Python 3.10+
- `pip`
- 只有源码 checkout、开发或 git-backed skill pack 才需要 `git`
- 使用全局 `pawn` 启动器时，`~/.local/bin` 需要在 `PATH` 中
- 可选：Docker 用于容器工具；浏览器依赖用于 Patchright / Scrapling；CTF 包用于 pwn 工作流

## 快速开始

**方式一：从 PyPI 安装**

```bash
pip install pawnlogic
pawn
```

首次运行会进入 API Key 配置流程。运行时文件会创建在 `~/.pawnlogic/` 下，不会写入项目目录。

**方式二：一行安装脚本**

```bash
curl -fsSL https://raw.githubusercontent.com/john0123412/PawnLogic/main/install.sh | bash
pawn
```

安装脚本会在 `~/.local/share/pawnlogic` 下创建独立 venv，安装官方 PyPI 包，并写入 `~/.local/bin/pawn`。

**方式三：源码 checkout 开发安装**

```bash
git clone https://github.com/john0123412/PawnLogic.git
cd PawnLogic
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
pawn
```

可选 extras：

```bash
pip install "pawnlogic[docker]"    # Docker SDK 集成
pip install "pawnlogic[browser]"   # Scrapling + Patchright 浏览器工具
pip install "pawnlogic[ctf]"       # pwntools、ROPgadget、ropper
pip install -e ".[dev,ctf]"        # 源码 checkout + 测试 + CTF 工具
```

`pawnlogic[ctf]` 只安装 CTF 工具依赖。CTF skill pack 是可选扩展资产，需要用户显式安装，
例如通过 `/skills install <repo_url>` 安装到 `~/.pawnlogic/skills`。第三方 skill pack
只有在上游许可证和 notice 已完成再分发审查后，才会随 PyPI 分发。git-backed skill
pack manifest 只是运行时发现元数据；没有匹配的 `THIRD_PARTY_NOTICES.md` 条目时，
它不授权再分发。git-backed skill pack 安装只接受 `https://`、`ssh://` 或
`git@host:owner/repo.git` remote。

源码 checkout 启动器备用方式：

```bash
./pawn.sh
```

CLI 入口：

```bash
pawn
pawn --debug
pawn --eval "summarize this repository"
pawn --eval "summarize this repository" --json
python -m pawnlogic --help
```

默认 `pawn` 使用用户友好的输出，会隐藏原始工具调用细节、解析器诊断、详细 reasoning 流和底层 API 错误。需要详细诊断时，使用 `pawn --debug` 或 `/mode`。
使用 `--json` 时，每一行都是独立的 NDJSON record。现有 `text`、`chunk` 和 `json`
record 保持稳定；带版本的 Agent lifecycle record 使用新增的
`{"type":"event","data":{...}}` envelope。

## 新特性

0.3.2 在保持现有公共 contract 不变的前提下，引入经过隔离证明的有界双 worker 委派：

- 支持的 batch caller 最多可并行运行两个委派 task，同时保留 FIFO 准入和按输入顺序返回结果；`delegate_task` 仍是单 task 兼容 Adapter，不会隐式 fan-out。
- 每个并发 child 都获得复制的 RuntimeContext、唯一的 `.tasks/` workspace、有界 output collector 与 task-local cancellation token。
- 共享 Token、Tool Call 和成本 budget 在排队、完成、取消和 deadline 到期时仍保持原子 claim 与 settle 行为。
- 并发 child 只能使用完成 task 隔离的文件 Tool。shell、network、container、extension、MCP、browser、pwn、sandbox 及其他未隔离 Tool 会在 handler 执行前 fail closed。

完整版本历史见 [CHANGELOG.md](CHANGELOG.md)。

## 核心能力

| 能力 | 描述 |
|------|------|
| 多 Provider 模型 | 内置 DeepSeek、OpenAI、Anthropic 别名，并可通过 `/provider` 添加自定义 OpenAI-compatible 或 Anthropic-style Provider。 |
| 委派 Agent | 有界 sub-agent 使用由 host 控制的动态模型路由、用户 allow/deny 策略、Token/工具/成本预算、按能力过滤的工具、task-local workspace，以及带 task lineage 的一至两个 worker 编排。 |
| 结构化上下文 | 版本化任务状态、保持 Tool Call 完整性的裁剪、`ctx_trim_to` 目标和由 host 选择的委派上下文，使长会话保持有界且不会复制原始父级历史。 |
| 持久化工作区 | 基于 SQLite 的会话、可搜索历史、memory 命令、有界且携带来源信息的知识检索、每会话 workspace 和 `~/.pawnlogic/` 下的审计日志。 |
| 真实工具执行 | Host shell、代码沙箱、文件操作、URL fetch、浏览器自动化、Docker 容器和 CTF helper。 |
| Trust-boundary UX | 用户模式会明确提示工具何时跨越本地主机、容器、浏览器、网络、delegate 或明文 HTTP 边界。 |
| 可选 Extension | 已安装的包可以声明 `pawnlogic.extensions` entry point。发现阶段不会加载其代码，必须通过 `/extension enable <name>` 显式启用。 |
| MCP 集成 | stdio MCP server 可通过 `~/.pawnlogic/mcp_configs.json` 配置，PawnLogic 会处理 roots 和 stderr 日志。 |
| CTF / pwn 工作流 | 可选 pwn 工具、Docker 容器 helper、GDB 自动化、ROP 链支持、libc leak 工作流和用户安装的本地 skill pack。 |
| 发布卫生 | CI 先运行 Ruff、typed-island mypy、docs guard 和 Python 3.11 fast PR 检查；release/manual 验证再覆盖 Python 3.10/3.11/3.12、packaging、Dynamic E2E、文档结构、语言策略、包构建和 Trusted Publishing 护栏。生产 PyPI 发布只能由版本 tag 通过 Trusted Publishing 触发；手动 workflow dispatch 仅面向 TestPyPI。 |

## 支持模型

PawnLogic 自带预配置模型别名。只有 active 且已配置 API Key 的 Provider 会显示在 `/model` 和 Tab 补全中。

| Provider | Aliases | 说明 |
|----------|---------|------|
| DeepSeek | `ds-v4-flash`, `ds-v4-pro` | 默认 Provider；快速主模型和旗舰推理模型。 |
| OpenAI | `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.4-nano`, `gpt-4o`, `gpt-4.1`, `o3` | 编程、视觉、多模态、低延迟和推理别名。 |
| Anthropic | `claude-opus`, `claude-sonnet`, `claude-haiku` | Anthropic Messages API 路径下的 Opus、Sonnet、Haiku 别名。 |

自定义 Provider 的模型描述来自 `~/.pawnlogic/custom_providers.json`。重新运行 `/provider update <name>` 会刷新已选模型；当 Provider 没有提供可用描述时，会写入英文 fallback 描述。

未指定模型请求时，委派任务会自动优先选择符合条件的快速 worker，而不会默认复用当前对话模型。`/worker` 会列出当前可通过 `/model` 看见的全部模型，包括符合条件的自定义 Provider 别名。`/agent policy` 可以 allow 或 deny 模型别名、选择默认路由模式，并限制成本或并发。显式模型请求只是偏好；Provider 可见性、用户策略、能力和预算检查始终由 host 决定。
结构化 task 和 result 携带 task/parent ID、deadline、usage 与 failure record。
共享编排预算通过原子方式预留，取消采用协作式机制。core orchestrator 最多准入两个
worker；每个并发 child 都有复制的 RuntimeContext、隔离 workspace、有界 output
collector 和 task-local cancellation token。并发 child 只允许使用已做 task 隔离的文件
工具。`delegate_task` 仍是单任务兼容 Adapter：`max-concurrency=2` 只对支持的 batch
caller 生效，绝不会隐式 fan-out。

## Provider 管理

```bash
/provider                         # 打开 Provider TUI
/provider add <name> <base_url> <ENV_KEY> [anthropic]
/provider fetch <name>            # 拉取可用模型并选择别名
/provider update <name>           # 重新拉取 Provider 模型
/provider activate <name>         # 显示已选择的 Provider 模型
/provider deactivate <name>       # 隐藏 Provider 模型
/provider list                    # 显示 Provider 和 Key 状态
/provider test <model>            # 测试某个模型别名的连通性
/setkey                           # 重新运行 Key 配置
/keys                             # 显示已配置 Key 状态
```

API Key 存储在 `~/.pawnlogic/.env`。Provider 配置、模型别名和描述存储在 `~/.pawnlogic/custom_providers.json`，不包含 secret value。Provider 配置流程不会把 Key 写入 shell 启动文件。

本地 relay 和实验环境可以使用明文 `http://` Provider endpoint，但用户友好模式会显示 trust-boundary 提示，因为请求和 API Key 没有 TLS 保护。

不稳定的自定义 Provider 可以通过 `~/.pawnlogic/.env` 中的环境变量调优：`PAWNLOGIC_API_RETRY_MAX` 控制包含首次请求在内的总尝试次数，`PAWNLOGIC_API_RETRY_AFTER_MAX` 限制 Provider `Retry-After` 延迟上限，`PAWNLOGIC_API_CONNECT_TIMEOUT`、`PAWNLOGIC_API_READ_TIMEOUT` 和 `PAWNLOGIC_API_NONSTREAM_TIMEOUT` 分别调节连接和响应等待时间。

## 快速命令参考

```bash
/model [alias]                    # 切换模型
/mode                             # 切换用户友好/debug 输出
/chat find <keyword>              # 搜索所有会话
/think <prompt>                   # 执行一次更深推理
/compact                          # 总结并压缩上下文
/undo [n]                         # 回滚最近轮次
/deep                             # full-power 模式
/init_project [desc]              # 初始化项目状态
/pwnenv                           # 检查 CTF 工具链完整性
/ctf init <name>                  # 创建 CTF workspace metadata
/ctf solved [flag]                # 将已确认的 CTF flag 标记为 solved
/ctf writeup                      # 导出 CTF writeup 草稿
/skills install <repo_url>         # 安装 git-backed skill pack
/skills                            # 交互式 TUI: 切换、同步、重新扫描
/extension list                   # 列出已安装的 Extension
/extension enable <name>          # 显式启用 Extension
/extension disable <name>         # 禁用 Extension
/worker [alias|auto]              # 查看或设置首选 worker
/agent policy show                # 查看委派 Agent 策略
/agent run <role> <objective>     # 输出安全的 delegate_task 请求模板
```

在 PawnLogic 内运行 `/help` 可查看完整命令列表。

## Trust Boundary

PawnLogic 是 agent 执行工具，不是安全沙箱。它会在你要求时，用当前用户权限执行真实工具。Pattern filter、Docker 边界和 capability profile 能减少误操作，但不能阻止有意攻击者。

Web fetch 和 browser navigation 会在使用 HTTP(S) target 前通过共享 Network Policy
进行评估。URL 会被规范化；包含 credential 的 URL、cloud metadata/internal target，
以及 loopback、link-local、multicast、unspecified 或 reserved address 都会被拒绝。
Private-network target 需要显式授权；在非交互请求本应要求确认时，系统会 fail closed。
每个 redirect destination 在跟随前都会重新规范化、解析并评估，包括重新检查
target-scoped authorization。模型生成的 Tool 参数不能授予 private-network
权限；已确认的 private target 不会发送给远程 reader service。

Docker `bridge`/`host` 网络和 legacy `uvx mcp-server-fetch` 启动在授权 gate
处没有具体 URL，因此使用 capability-only authorization。Docker 网络需要
`allow_network=true` 或 `PAWNLOGIC_DOCKER_ALLOW_NETWORK=true`；legacy MCP
网络安装需要 `allow_network_install=true` 或
`PAWNLOGIC_MCP_ALLOW_NETWORK_INSTALL=true`。这些授权只授予对应 capability，
不代表 URL target 已获授权。

用户友好模式会针对 host shell 执行、Docker container exec、browser/network-capable 工具、private network URL 访问、delegated sub-agent 和 plaintext HTTP Provider 显示明确的 trust-boundary notice。需要更底层的工具参数和诊断信息时，使用 `pawn --debug`。Docker 文件挂载默认限制在 workspace 内，包括 read-only 挂载；挂载外部只读 challenge 文件需要显式设置 `allow_host_read_mount`。

Host shell 执行现在会在启动子进程前经过 operation policy。低风险命令正常执行，中等风险命令会被分类并写入审计，高风险命令需要明确的交互确认，critical 操作默认拒绝。非交互执行，包括 `pawn --eval`，在高风险命令需要确认时会 fail closed。`DANGEROUS_PATTERNS` 只是误操作/风险分类的一部分，不是 sandbox 边界，也不能阻止恶意本地用户。

## 可选 Extension

Python distribution 可以通过 `pawnlogic.extensions` entry-point group 声明
Extension 元数据。PawnLogic 可以在不加载 Extension 代码的情况下列出已安装项。
安装 Extension 不会自动启用。

```bash
/extension list
/extension status [name]
/extension enable <name>
/extension disable <name>
```

已启用名称存储在 `~/.pawnlogic/extensions/enabled.json`。Extension 启动失败不会阻断
core 启动；贡献名称发生冲突时会拒绝注册，不会覆盖内置 Tool 或命令。
依赖较重或安全敏感的 Extension 必须独立打包和发布。Core wheel 不包含
`pawnlogic_security` package、security console script 或 security dependency；
即使安装了这类 distribution，仍需通过 `/extension enable <name>` 明确授权。

## MCP 工具集成

pip 或一行安装脚本用户，PawnLogic 启动时会在 `~/.pawnlogic/` 下创建可编辑模板：

```bash
pawn
cp ~/.pawnlogic/mcp_configs.example.json ~/.pawnlogic/mcp_configs.json
# 编辑 ~/.pawnlogic/mcp_configs.json，并通过 /setkey 或 ~/.pawnlogic/.env 添加 key
pawn
```

源码 checkout 用户也可以直接复制仓库模板：

```bash
cp mcp_configs.example.json ~/.pawnlogic/mcp_configs.json
```

示例支持的 MCP server 包括 Tavily search、Playwright browser automation 和 filesystem bridge。示例中默认禁用外部 `fetch` MCP，因为 `uvx mcp-server-fetch` 可能在启动时访问 PyPI；除非明确需要，请优先使用 PawnLogic 内置的 `fetch_url`。

MCP 子进程 stderr 默认写入 `~/.pawnlogic/logs/mcp/<server>.stderr.log`。如果需要在终端看到原始 MCP stderr，可在 `mcp_configs.json` 顶层设置 `"debug_stderr": true`。PawnLogic 会为当前工作目录和 `~/.pawnlogic/workspace` 声明 MCP roots。

## 数据目录结构

所有运行时数据和 API Key 都存储在 `~/.pawnlogic/`。

```text
~/.pawnlogic/
├── .env                    # API Key
├── custom_providers.json   # 用户 Provider 配置，不含 Key
├── mcp_configs.json        # MCP server 声明
├── pawn.db                 # 会话、消息、知识库
├── global_skills.md        # GSA 技能存档
├── skills/                 # 可选用户安装 skill pack
├── workspace/              # 每会话工作目录
└── logs/                   # 审计日志
```

项目目录不包含 secret，可以安全提交或分享。

## 使用示例

### 接入第三方 API

```
/provider add myrelay https://api.myrelay.com/v1/chat/completions MYRELAY_API_KEY
/provider fetch myrelay
/provider activate myrelay
/model <别名>
```

### 视觉分析

```
分析截图 ./screenshot.png，提取代码并修复 bug。
```

### CTF Pwn

```
/model ds-v4-pro
分析 ./challenge，用 pwn_debug 检查 main 断点处的寄存器。
```

## 常见问题

**Q: 添加了 Provider 但 `/model` 看不到新模型？**
A: 配置 Key，运行 `/provider fetch <name>`，选择模型，再 `/provider activate <name>`。

**Q: Test Connection 失败但 fetch 成功？**
A: Fetch 只读 `/v1/models`；Test Connection 发送聊天请求。先加载聊天模型。

**Q: API Key 在哪里？**
A: `~/.pawnlogic/.env`，不在项目目录，不被 git 追踪。

**Q: `pawn: command not found`？**
A: `export PATH="$HOME/.local/bin:$PATH"`

**Q: 浏览器工具缺少模块？**
A: `pip install 'pawnlogic[browser]'` 然后 `patchright install chromium`。

**Q: 支持 Ollama 本地模型？**
A: 支持。`/provider add`，Base URL 填 `http://localhost:11434`，Key 留空。

## 文档

| 文档 | 描述 |
|------|------|
| [**README.md**](README.md) | 英文 README |
| [**README_zh-CN.md**](README_zh-CN.md) | 本页 |
| [**CHANGELOG.md**](CHANGELOG.md) | 版本历史和发布说明 |
| [**CONTRIBUTING.md**](CONTRIBUTING.md) | 贡献、Provider 和测试工作流 |
| [**SECURITY.md**](SECURITY.md) | 漏洞报告策略 |
| [**THIRD_PARTY_NOTICES.md**](THIRD_PARTY_NOTICES.md) | 第三方归属和再分发说明 |

## 支持

- GitHub: [github.com/john0123412/PawnLogic](https://github.com/john0123412/PawnLogic)
- Issues: 请使用 GitHub Issues 提交 bug 或功能请求。
