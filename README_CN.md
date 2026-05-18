# 🤖 PawnLogic 1.1

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20WSL2-lightgrey.svg)]()

> **全自主终端 AI 智能体** — 多模型路由、持久记忆、工具执行、会话管理。专为开发者和安全研究者打造。

## PawnLogic 是什么？

PawnLogic 是一个终端原生 AI 智能体，**真正能做事**：运行代码、浏览网页、编辑文件、调试二进制、跨会话记住一切——全在你的终端里完成。

```bash
# 安装
git clone https://github.com/john0123412/PawnLogic.git && cd PawnLogic
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 填入你的 API Key
python main.py
```

**核心能力一览：**
- 🔀 **12 家 LLM 厂商** — DeepSeek、Claude、GPT-4o、Qwen、GLM、Groq、MiMo、Ollama 等，`/model` 热切换
- 🧠 **持久记忆** — SQLite 会话历史、RAG 知识库、跨会话全文搜索
- 🛠️ **真实工具执行** — Shell、代码沙箱（8 种语言）、网页抓取、文件操作、Docker 容器
- 👁️ **视觉能力** — 截图直接喂给 `glm-4v` 或 `gpt-4o` 分析
- 📋 **规格驱动规划** — Agent 每次行动前输出 `<plan>` XML，无盲目执行
- 💬 **会话管理** — 标签、搜索、关联、导出对话，`/chat` 命令系列
- 🗜️ **滑动窗口上下文** — 自动摘要旧历史，防止长任务 API 超时

> ✅ 完美支持 **WSL2** 及其环境下的本地工具链调用

---

<details>
<summary>🔐 CTF / 安全研究工具链（点击展开）</summary>

PawnLogic 内置完整的 Pwn/CTF 流水线：

- **二进制分析**：`inspect_binary` → 自动将 checksec/file 结果写入 `.pawn_state.md`
- **偏移计算**：`pwn_cyclic` 生成 de Bruijn 序列 → `pwn_debug` 读取崩溃偏移
- **ROP 链构建**：`pwn_rop`（ROPgadget 封装）+ `pwn_libc`（libc 泄露解析）+ `pwn_one_gadget`
- **GDB 自动化**：批处理 GDB 脚本，SIGSEGV/SIGABRT/SIGBUS 时自动追加 `bt full`
- **Docker 隔离**：`pwn_container` 提供持久化 CTF 环境，支持指定 libc 版本
- **倒计时调试**：`pwn_timed_debug` 具备时间感知的模式切换
- **技能包**：`./skills/ctf_pwn/`、`./skills/ctf_web/` 等，检测到相关关键词时自动注入

**CTF 场景推荐模型组合：**
| 任务 | 推荐模型 |
|------|---------|
| Pwn 漏洞开发 | `ds-r1` 或 `ds-v4-pro`（深度推理） |
| Web 代码审计 | `ds-chat` 或 `glm-5.1` |
| 截图 / 隐写分析 | `glm-4v` 或 `gpt-4o` |
| 极速脚本生成 | `groq-llama3` |
| 离线 / 断网环境 | `qwen-local`（Ollama） |

</details>

---

## 文档

| 文档 | 说明 |
|------|------|
| [README.md](README.md) | 英文简介（当前页为中文版） |
| [GUIDE.md](GUIDE.md) | 完整英文使用指南（功能、命令、架构、FAQ） |

---

## 快速开始

### 系统要求

- **推荐**：WSL2 / Ubuntu（满血体验）
- **可选**：Windows（基础体验，不支持 Pwn 工具链）

### 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/john0123412/PawnLogic.git && cd PawnLogic

# 2. 创建虚拟环境
python3 -m venv venv && source venv/bin/activate

# 3. 安装依赖
pip install --upgrade pip && pip install -r requirements.txt

# 4. 配置 API Key
cp .env.example .env
# 编辑 .env，填入你的 Key（不用的厂商留空即可）

# 5. 启动
python main.py
```

### 全局 `pawn` 命令（推荐）

```bash
chmod +x /path/to/PawnLogic/pawn.sh
ln -sf /path/to/PawnLogic/pawn.sh ~/.local/bin/pawn
# 之后在任意目录输入 pawn 即可启动
```

---

## 核心命令速查

```bash
/model ds-r1          # 切换模型
/mode                 # 切换 USER/DEV 输出模式
/chat find <关键词>   # 跨会话全文搜索
/chat tag 3 pwn       # 给第3个会话打标签
/think <问题>         # 单次深度推理
/compact              # 压缩上下文
/undo                 # 撤回上一轮
/deep                 # 切换深度模式（32k tokens, 50轮）
/init_project         # 初始化 GSD 工程流水线
/pwnenv               # 检查 CTF 工具链完整性
```

完整命令手册见 [GUIDE.md](GUIDE.md)。

---

## 支持与贡献

- **GitHub**: [github.com/john0123412/PawnLogic](https://github.com/john0123412/PawnLogic)
- **问题反馈**: 请通过 GitHub Issues 提交

**祝您使用愉快！** 🚀
