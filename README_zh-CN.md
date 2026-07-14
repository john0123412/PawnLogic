[English](README.md) | **[中文](README_zh-CN.md)**

# PawnLogic

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/pypi/v/pawnlogic.svg?label=version)](https://pypi.org/project/pawnlogic/)
[![PyPI](https://img.shields.io/pypi/v/pawnlogic.svg?cache=no)](https://pypi.org/project/pawnlogic/)
[![CI](https://github.com/john0123412/PawnLogic/actions/workflows/main_ci.yml/badge.svg)](https://github.com/john0123412/PawnLogic/actions/workflows/main_ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20WSL2-lightgrey.svg)]()

PawnLogic 是一个终端优先的自主 AI Agent，支持多 Provider 模型路由、持久化记忆、真实本地工具执行、MCP 集成和面向 CTF 的工具链。当前公开发布版本是 **0.2.3**。

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
例如通过 `/sp install <repo_url>` 安装到 `~/.pawnlogic/skills`。第三方 skill pack
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

## 新特性

0.2.3 关闭了安全缺口，让自定义 Provider 可预测地恢复，并深化了 runtime 模块，同时保持 0.2.2 的公开 contract 不变：

- Canonical path containment 通过 `core/path_policy.py` 防止 workspace 遍历、symlink 逃逸和恶意 MCP server-name 注入。
- 集中式 host-process trust enforcement 将每个 shell、Docker、web、pwn 和 delegate 路径路由到一个 Operation Policy 模块，具有显式 network 和 destructive 授权。
- Transactional provider mutation 在写入 key 之前验证 name、URL、format 和 definition metadata；写入失败时，disk 和 memory 保持不变。Format-specific header（OpenAI bearer、Anthropic x-api-key）在 test、fetch、stream 和 non-stream 路径中一致使用。
- 统一 retry 和 circuit-breaker policy 在请求开始时加载，具有 bounded validation，仅在没有 partial response 被发出时重试，并给 half-open 状态一个 single probe lease。
- Runtime evaluation 通过 child-process termination 强制执行 real deadline，产生 schema-versioned atomic JSONL artifact，并在没有网络访问的情况下运行带有 provider stream fixture 的 offline replay scenario。
- Bounded codex goal runner 为 maintainer-only unattended work 提供 locking、manifest、heartbeat、wall-clock timeout 和显式 capability gate。
- Module ownership split 将 CLI startup/REPL、provider TUI state、tool implementation、session persistence、runtime context 和 runtime metrics 隔离到经过测试的 internal interface 后面。

完整版本历史见 [CHANGELOG.md](CHANGELOG.md)。

## 核心能力

| 能力 | 描述 |
|------|------|
| 多 Provider 模型 | 内置 DeepSeek、OpenAI、Anthropic 别名，并可通过 `/provider` 添加自定义 OpenAI-compatible 或 Anthropic-style Provider。 |
| 持久化工作区 | 基于 SQLite 的会话、可搜索历史、memory 命令、知识库、每会话 workspace 和 `~/.pawnlogic/` 下的审计日志。 |
| 真实工具执行 | Host shell、代码沙箱、文件操作、URL fetch、浏览器自动化、Docker 容器和 CTF helper。 |
| Trust-boundary UX | 用户模式会明确提示工具何时跨越本地主机、容器、浏览器、网络、delegate 或明文 HTTP 边界。 |
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
/sp install <repo_url>            # 安装 git-backed skill pack
```

在 PawnLogic 内运行 `/help` 可查看完整命令列表。

## Trust Boundary

PawnLogic 是 agent 执行工具，不是安全沙箱。它会在你要求时，用当前用户权限执行真实工具。Pattern filter、Docker 边界和 capability profile 能减少误操作，但不能阻止有意攻击者。

用户友好模式会针对 host shell 执行、Docker container exec、browser/network-capable 工具、private network URL 访问、delegated sub-agent 和 plaintext HTTP Provider 显示明确的 trust-boundary notice。需要更底层的工具参数和诊断信息时，使用 `pawn --debug`。Docker 文件挂载默认限制在 workspace 内，包括 read-only 挂载；挂载外部只读 challenge 文件需要显式设置 `allow_host_read_mount`。

Host shell 执行现在会在启动子进程前经过 operation policy。低风险命令正常执行，中等风险命令会被分类并写入审计，高风险命令需要明确的交互确认，critical 操作默认拒绝。非交互执行，包括 `pawn --eval`，在高风险命令需要确认时会 fail closed。`DANGEROUS_PATTERNS` 只是误操作/风险分类的一部分，不是 sandbox 边界，也不能阻止恶意本地用户。

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

## 文档

| 文档 | 描述 |
|------|------|
| [**README.md**](README.md) | 英文 README |
| [**README_zh-CN.md**](README_zh-CN.md) | 本页 |
| [**GUIDE.md**](GUIDE.md) | 完整参考：命令、架构和 FAQ |
| [**GUIDE_zh-CN.md**](GUIDE_zh-CN.md) | 中文完整参考 |
| [**CHANGELOG.md**](CHANGELOG.md) | 版本历史和发布说明 |
| [**CONTRIBUTING.md**](CONTRIBUTING.md) | 贡献、Provider 和测试工作流 |
| [**SECURITY.md**](SECURITY.md) | 漏洞报告策略 |
| [**THIRD_PARTY_NOTICES.md**](THIRD_PARTY_NOTICES.md) | 第三方归属和再分发说明 |

## 支持

- GitHub: [github.com/john0123412/PawnLogic](https://github.com/john0123412/PawnLogic)
- Issues: 请使用 GitHub Issues 提交 bug 或功能请求。
