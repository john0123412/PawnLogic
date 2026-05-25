# 🤖 PawnLogic

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20WSL2-lightgrey.svg)]()

> **完全自主的终端 AI Agent** — 多模型路由、持久化记忆、真实工具执行、会话管理。专为开发者与安全研究者打造。

## ⚡ 快速开始

```bash
git clone https://github.com/john0123412/PawnLogic.git && cd PawnLogic
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py   # 首次运行自动进入 API 配置向导
```

全局 `pawn` 命令：
```bash
chmod +x pawn.sh && ln -sf "$(pwd)/pawn.sh" ~/.local/bin/pawn
```

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
| OpenAI | `gpt-4o` `gpt-4.1` `o3` | 视觉、代码、复杂推理 |
| Anthropic | `claude-sonnet` `claude-haiku` | 均衡性能、快速低成本 |

通过 `/provider fetch` 添加的自定义 Provider 会自动出现在 `/model` 和 Tab 补全中。

## Provider 管理

```bash
/provider              # 打开交互式 TUI 面板
/provider add <name> <base_url> <ENV_KEY> [anthropic]
/provider fetch <name> # 自动发现模型并交互多选
/provider list         # 显示所有 Provider 及 Key 状态
/provider test <model> # 测试连通性
```

所有 Key 存储在 `~/.pawnlogic/.env`，Provider 配置（不含 Key）存储在 `~/.pawnlogic/custom_providers.json`。

## 快速命令参考

```bash
/model [alias]          # 切换模型
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
python main.py   # MCP 服务器自动加载
```

支持的 MCP 服务器：**Tavily**（搜索）、**Playwright**（浏览器自动化）、**Filesystem**（文件系统桥接）。

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
| **README.md** | English version |
| **README_CN.md** | 本页 |
| **GUIDE.md** | 完整参考手册 — 命令、架构、常见问题 |

## 支持

- **GitHub**: [github.com/john0123412/PawnLogic](https://github.com/john0123412/PawnLogic)
- **Issues**: GitHub Issues 提交 Bug 或功能请求
