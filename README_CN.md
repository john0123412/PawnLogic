[English](README.md) | **[中文](README_CN.md)**

# 🤖 PawnLogic

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.0.7-blue.svg)](config/paths.py)
[![PyPI](https://img.shields.io/pypi/v/pawnlogic.svg?cache=no)](https://pypi.org/project/pawnlogic/)
[![CI](https://github.com/john0123412/PawnLogic/actions/workflows/main_ci.yml/badge.svg)](https://github.com/john0123412/PawnLogic/actions/workflows/main_ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20WSL2-lightgrey.svg)]()

> **完全自主的终端 AI Agent** — 多模型路由、持久化记忆、真实工具执行、会话管理。专为开发者与安全研究者打造。

## 系统要求

- Linux 或 WSL2
- Python 3.10+
- `pip` 和 `git`
- 如需全局 `pawn` 命令，`~/.local/bin` 需要在 `PATH` 中

## ⚡ 快速开始

**方式一 — pip 安装（推荐）**
```bash
pip install pawnlogic
pawn   # 首次运行自动进入 API 配置向导
```

**方式二 — 一行安装脚本**
```bash
curl -fsSL https://raw.githubusercontent.com/john0123412/PawnLogic/main/install.sh | bash
pawn
```

安装脚本会在 `~/.local/share/pawnlogic` 下创建独立 venv，通过 pip 安装正式
`pawnlogic` 包，并写入 `~/.local/bin/pawn` 启动器。它不会复制源码目录，也不会把运行时数据存到项目目录。

**方式三 — 从源码开发安装**
```bash
git clone https://github.com/john0123412/PawnLogic.git && cd PawnLogic
python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
pawn             # 首次运行自动进入 API 配置向导
```

**可选 CTF skill 包**（pwntools / ROPgadget / ropper + `skills/ctf_*` 文档）：
```bash
pip install -e ".[ctf]"
```

源码 checkout 启动器备用方式：
```bash
./pawn.sh
```
如果包安装或安装脚本执行后仍提示 `pawn: command not found`，运行
`export PATH="$HOME/.local/bin:$PATH"`，并把这行加入你的 shell 配置文件。

**CLI 用法：**
```bash
pawn                              # 交互模式
pawn --eval "your prompt"         # 单次执行后退出
pawn --eval "prompt" --json       # JSON 输出（供脚本调用）
```

## 新特性

完整版本历史见 [CHANGELOG.md](CHANGELOG.md)。

## 核心能力

| 能力 | 描述 |
|------|------|
| 🔀 **动态 Provider 系统** | 内置 DeepSeek / OpenAI / Anthropic + 通过 `/provider` 添加任意 OpenAI 兼容 API |
| 🧠 **持久化记忆** | SQLite 会话历史、RAG 知识库、跨会话全文搜索 |
| 🛠️ **真实工具执行** | Shell、代码沙箱（8 种语言）、网页抓取、文件操作、Docker 容器 |
| 👁️ **视觉多模态** | 将截图传给 `gpt-4o` 或 `claude-sonnet` 进行分析 |
| 📋 **规格驱动规划** | Agent 在每次工具调用前必须输出 `<plan>` XML — 无盲目执行 |
| 💬 **会话管理** | 通过 `/chat` 命令标签、搜索、关联、导出对话 |
| 🔐 **CTF / Pwn 工具链** | GDB 自动化、ROP 链构建、libc 泄漏解析、Docker 隔离 |

## 支持模型

| 服务商 | 别名 | 适用场景 |
|--------|------|----------|
| DeepSeek | `ds-v4-flash` `ds-v4-pro` | 快速默认、旗舰推理 |
| OpenAI | `gpt-5.5` `gpt-5.4` `gpt-5.4-mini` `gpt-5.4-nano` `gpt-4o` `gpt-4.1` `o3` | 旗舰、编程、视觉、推理 |
| Anthropic | `claude-opus` `claude-sonnet` `claude-haiku` | 前沿推理、均衡、快速 |

DeepSeek 默认 active。自定义 Provider 只有在 Key 已配置、模型已拉取并手动 active 后，才会出现在 `/model` 和 Tab 补全中。

## Provider 管理

```bash
/provider              # 打开交互式 TUI 面板
/provider add <name> <base_url> <ENV_KEY> [anthropic]
/provider fetch <name> # 拉取可用模型并交互选择
/provider update <name>
/provider activate <name>
/provider deactivate <name>
/provider list         # 显示所有 Provider 及 Key 状态
/provider test <model> # 测试连通性
```

所有 Key 存储在 `~/.pawnlogic/.env`，Provider 配置（不含 Key）存储在 `~/.pawnlogic/custom_providers.json`。

## 快速命令参考

```bash
/model [alias]          # 切换模型，只显示 active 且已配置 Key 的 Provider
/mode                   # 切换 USER / DEV 输出模式
/chat find <keyword>    # 跨所有会话全文搜索
/think <prompt>         # 单次深度推理
/compact                # 压缩上下文
/undo [n]               # 撤回最近 n 轮
/deep                   # 切换深度模式（32k tokens, 50 iter）
/init_project           # 初始化 GSD 工程流水线
/pwnenv                 # 检查 CTF 工具链完整性
/keys                   # 显示所有 Provider 的 Key 配置状态
```

## MCP 工具集成

```bash
cp mcp_configs.example.json ~/.pawnlogic/mcp_configs.json
# 编辑 mcp_configs.json，在 ~/.pawnlogic/.env 中添加 TAVILY_API_KEY= 等
pawn   # MCP 服务器自动加载
```

支持的 MCP 服务器：**Tavily**（搜索）、**Playwright**（浏览器自动化）、**Filesystem**（文件系统桥接）。
示例配置默认禁用外部 `fetch` MCP，因为 `uvx mcp-server-fetch` 可能在启动时访问 PyPI。
请优先使用 PawnLogic 内置的 `fetch_url`；只有明确需要时，再手动启用该 MCP 并允许网络安装。

## 数据目录结构

所有运行时数据和 API Key 存储在 `~/.pawnlogic/` — **永远不在项目目录中**。

```
~/.pawnlogic/
├── .env                    # 所有 API Key（LLM Provider + MCP 工具）
├── custom_providers.json   # 用户添加的 Provider 配置（不含 Key）
├── mcp_configs.json        # MCP 服务器声明
├── pawn.db                 # 会话、消息、知识库
├── global_skills.md        # GSA 技能存档
├── workspace/              # 每个会话的独立工作目录
└── logs/                   # 审计日志
```

项目目录不包含任何密钥，可以安全提交或分享。

## 文档

| 文档 | 描述 |
|------|------|
| [**README.md**](README.md) | 英文版 |
| [**README_CN.md**](README_CN.md) | 本页 |
| [**GUIDE_EN.md**](GUIDE_EN.md) | 完整参考手册 — 命令、架构、常见问题 |
| [**GUIDE_CN.md**](GUIDE_CN.md) | 完整参考手册 — 命令、架构、常见问题 |
| [**CHANGELOG.md**](CHANGELOG.md) | 版本历史和发布说明 |
| [**CONTRIBUTING.md**](CONTRIBUTING.md) | 如何贡献、添加 Provider、运行测试 |
| [**SECURITY.md**](SECURITY.md) | 漏洞报告策略 |

## 支持

- **GitHub**: [github.com/john0123412/PawnLogic](https://github.com/john0123412/PawnLogic)
- **Issues**: GitHub Issues 提交 Bug 或功能请求
