# 🤖 PawnLogic 1.1

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-WSL2%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)]()

> **全自主终端 AI 智能体** — 多模型路由、持久记忆、真实工具执行、会话管理。专为开发者和安全研究者打造。

## ⚡ 快速开始

```bash
git clone https://github.com/john0123412/PawnLogic.git && cd PawnLogic
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py   # 首次运行自动进入 API 配置向导
```

## 核心能力

| 能力 | 说明 |
|------|------|
| 🔀 **动态 Provider 系统** | 内置 DeepSeek / OpenAI / Anthropic，通过 `/provider` 添加任意兼容 API |
| 🧠 **持久记忆** | SQLite 会话历史、RAG 知识库、跨会话全文搜索 |
| 🛠️ **真实工具执行** | Shell、代码沙箱（8 种语言）、网页抓取、文件操作、Docker 容器 |
| 👁️ **视觉能力** | 截图直接喂给 `gpt-4o` 或 `claude-sonnet` 分析 |
| 📋 **规格驱动规划** | Agent 每次行动前输出 `<plan>` XML，无盲目执行 |
| 💬 **会话管理** | 标签、搜索、关联、导出对话，`/chat` 命令系列 |
| 🔐 **CTF / Pwn 工具链** | GDB 自动化、ROP 链构建、libc 泄露解析、Docker 隔离 |

## Provider 管理

几秒内接入任意第三方 OpenAI 兼容 API：

```bash
/provider              # 打开交互式 TUI 面板
/provider add <名称> <base_url> [anthropic]   # 注册 Provider
/provider fetch <名称>   # 自动嗅探模型列表，交互多选注册
/provider update <名称>  # 重新拉取模型列表
/provider list           # 查看所有 Provider 和 Key 状态
/provider test <模型>    # 测试连通性
```

所有 Key 存储在 `~/.pawnlogic/.env`，Provider 配置（不含 Key）存储在 `~/.pawnlogic/custom_providers.json`。

## 内置模型

| Provider | 别名 | 适用场景 |
|----------|------|---------|
| DeepSeek | `ds-v4-flash` `ds-v4-pro` | 默认主力，旗舰推理 |
| OpenAI | `gpt-4o` `gpt-4.1` `o3` | 视觉、代码、复杂推理 |
| Anthropic | `claude-sonnet` `claude-haiku` | 均衡主力，快速低成本 |

通过 `/provider fetch` 添加的自定义模型会自动出现在 `/model` 菜单和 Tab 补全中。

## 常用命令速查

```bash
/model [别名]           # 切换模型（只显示已配置 Key 的模型）
/mode                   # 切换 USER / DEV 输出模式
/chat find <关键词>     # 跨会话全文搜索
/think <问题>           # 单次深度推理
/compact                # 压缩上下文
/undo [n]               # 撤回最近 n 轮
/deep                   # 切换深度模式（32k tokens，50 轮）
/init_project           # 初始化 GSD 工程流水线
/pwnenv                 # 检查 CTF 工具链完整性
/keys                   # 查看所有 Provider 的 Key 状态
```

## MCP 工具接入

```bash
cp mcp_configs.example.json ~/.pawnlogic/mcp_configs.json
# 编辑 mcp_configs.json，在 ~/.pawnlogic/.env 中填入对应 Key（如 TAVILY_API_KEY=...）
python main.py   # MCP 服务自动加载
```

## 数据目录

```
~/.pawnlogic/
├── .env                    # API 密钥（已 gitignore，勿提交）
├── custom_providers.json   # 用户自定义 Provider（不含密钥）
├── pawn.db                 # 会话、消息、知识库
├── mcp_configs.json        # MCP 服务声明
└── logs/                   # 审计日志
```

## 安装

```bash
git clone https://github.com/john0123412/PawnLogic.git && cd PawnLogic
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```

全局 `pawn` 命令：
```bash
chmod +x pawn.sh && ln -sf "$(pwd)/pawn.sh" ~/.local/bin/pawn
```

## 文档

| 文档 | 说明 |
|------|------|
| **README_CN.md** | 本页（中文版） |
| **[README.md](README.md)** | English version |
| **[GUIDE.md](GUIDE.md)** | 完整使用指南 |

## 支持

- **GitHub**: [github.com/john0123412/PawnLogic](https://github.com/john0123412/PawnLogic)
- **问题反馈**: GitHub Issues
