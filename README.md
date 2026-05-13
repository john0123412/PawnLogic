# 🤖 PawnLogic 1.1

> **GSD 工程外骨骼 · 多模态视觉 · 会话管理 · SQLite 记忆 · 动态沙箱 · CTF 逆向工具链 · 双模输出 · 技能引擎 · P6 自动化利用链 · API 鲁棒性 · 逻辑刷新 · 双格式 API 原生支持 · 自定义 Provider**

PawnLogic 是一个专为极客和开发者打造的全能终端 AI 智能体。强大的会话管理系统，让您能够轻松浏览、搜索、标签化和关联历史对话，同时保留了所有强大功能。

> ✅ 完美支持 **WSL2** 及其环境下的本地工具链调用

---

## ✨ 核心特性一览

### 🧠 1. 强大的会话管理系统 (1.1 新增)

- `/chat list [n]` — 列出最近 n 个会话（默认20）
- `/chat view <id|n>` — 查看完整对话内容
- `/chat export <id|n> [文件路径]` — 导出为 Markdown 文件
- `/chat find <关键词>` — 跨会话全文搜索
- `/chat tag <id|n> <标签>` — 给会话打标签（逗号分隔）
- `/chat untag <id|n> <标签>` — 移除会话标签
- `/chat bytag <标签>` — 按标签筛选会话
- `/chat link <id1> <id2> [备注]` — 关联两个会话
- `/chat unlink <id1> <id2>` — 取消关联
- `/chat related <id|n>` — 查看关联会话

### 🏷️ 2. 会话自动命名与动态工作区 (1.1 新增)

- **自动命名**：新会话在第 2 轮对话时自动触发命名流程，Agent 根据对话内容生成语义化名称（如 `Python爬虫项目` / `CTF堆溢出分析`）
- **动态工作区**：每个会话拥有独立的 `~/.pawnlogic/workspace/session_<timestamp>_<hash>/` 工作目录，自动隔离文件和状态
- **原子化切换**：会话加载时自动 rename + 反向 symlink + 指针更新，确保工作目录切换的原子性和可回滚性
- **DB 一致性**：所有 76 条会话的 workspace_dir 均已验证有效，`/chat load` 永不返回空路径

### ✂️ CC 风格交互体验 (1.1 新增)

- **Ctrl+C 回退编辑**：输入状态下按 Ctrl+C 不退出程序，自动撤回最后一轮对话并重新显示提示符（对齐 Claude Code 交互体验）
- **Ctrl+D 退出**：使用 Ctrl+D（EOF）正常退出程序
- **Agent 生成中断**：在 Agent 生成过程中按 Ctrl+C 立即停止，保留已产出内容

### 🏗️ 3. GSD 企业级工程架构

- **规格驱动规划 (Spec-Driven)**：Agent 写代码前必须输出包含 `<action>` 和 `<verify>` 的 XML 计划
- **无污染子任务委派 (Fresh Context)**：内置 `delegate_task` 工具，解决"上下文腐化"问题
- **原子化自动提交**：每次修改代码并通过测试后自动调用 `git commit`
- **全局状态管理**：使用 `/init_project` 生成 `.pawn_state.md`

### 👁️ 4. 多模态视觉支持

- 终端 AI "看图"能力，支持 `glm-4v`、`gpt-4o` 等视觉模型
- **适用场景**：识别报错截图、分析网页 UI、读取 CTF 隐写图片、解析系统架构图

### 🛠️ 5. 极客专属能力

- **多语言隔离沙箱**：Python / C / C++ / JS / Bash / Rust / Go / Java
- **Docker 容器化执行**：`run_code_docker`（一次性容器）+ `pwn_container`（持久化容器），默认断网隔离
- **智能 Web 爬虫**：Jina Reader → Pandoc → 正则兜底（三级降级策略）
- **Pwn/CTF 工具链**：GDB 批处理动态调试、ROPgadget、de Bruijn 溢出偏移计算、倒计时感知调试
- **Pwn 自动分析流**：`inspect_binary` 执行后自动将 checksec/file 结果写入 `.pawn_state.md`，Agent 始终拥有最新二进制快照
- **GDB 崩溃自动回溯**：检测到 SIGSEGV/SIGABRT/SIGBUS 时自动追加 `bt full`，获取含局部变量的完整堆栈回溯
- **GSA 防御性审计**：工具调用失败自动记录，同类失败 ≥3 次自动沉淀到技能库
- **时间感知调度**：`/time` 设置倒计时，剩余 30s 自动切换极速模式

### 💰 成本微操工具集 (1.1 新增)

- `/undo [n]` — 撤回最近 n 轮对话（默认 1），不影响已 Pin 的消息
- `/compact` — 轻量模型总结当前进度 → 清空历史（保留 Pin）→ 以摘要作为新会话首条消息
- `/think <prompt>` — 单次推理模式，自动切换至推理 Worker（ds-r1/qwq），用完恢复原模型
- `/ping` — 极简保活请求，刷新 API 缓存 TTL

### 🧠 6. 结构化持久记忆

- **SQLite 驱动**：`~/.pawnlogic/pawn.db`，支持多会话保存与无缝加载
- **原生 RAG**：`/memorize` 将高价值对话沉淀进本地知识库，跨会话自动注入
- **精准锁定**：`/pin msg <n>` 防止关键消息被遗忘

### 🔀 7. 多厂商大模型路由 (2026 全生态)

- 支持 **12 大厂商**：Nous / OpenAI / DeepSeek / Qwen / ZhipuAI / SiliconFlow / OpenRouter / Moonshot / MiniMax / Groq / Xiaomi MiMo / Ollama
- 使用 `/model` 命令无缝热切换，`/setkey` 重新配置 API Key
- 动态加载机制：未配置的 Key 不影响其他模型正常运行

### 🎭 8. 双模输出系统 (P6 新增)

- `/mode` 一键切换 **USER 模式**与 **DEV 模式**
- **USER 模式**：极致简洁，所有原始 Traceback、Tool Call JSON、底层异常自动转为友好中文提示（如 `❌ 系统忙，请稍后重试`）
- **DEV 模式**：极致透明，显示所有 Tool Call 详情、异步线程状态和原始响应
- 错误映射覆盖 10+ 种常见异常类型（ConnectionError / TimeoutError / PermissionError / FileNotFoundError 等）

### 📚 9. 本地技能引擎 (P6 新增)

- `./skills/` 目录存放领域专属技能文件夹（零配置：放一个 `.md` 即可）
- Agent 执行任务前自动扫描技能目录，按文件名 + 内容关键词匹配评分
- **智能阈值过滤**：`min_score=3` 确保仅在检测到相关意图时才注入技能（如提到 "Heap Overflow" 才加载堆利用指南），普通聊天零注入，保持 System Prompt 精简
- 匹配到的技能全文注入系统提示词，Agent 按技能指令执行任务
- 与 GSA 全局技能存档互补：GSA 管理跨会话经验，本地技能管理项目级模板

### 🔍 10. 环境嗅探工具 (P6 新增)

- `check_service(port)` — 通过 lsof 或 `/proc` 文件系统快速提取端口进程详情
- 返回：PID、进程名、可执行文件路径、命令行、工作目录、关键环境变量、引用的动态库
- 用于侦察阶段确认目标服务运行环境，替代盲目执行 `ps aux`

### 🌐 11. 全球技能包同步 (P6 新增)

- `/sp sync` — 遍历 `./skills/` 下所有带 `.git` 的技能包，批量 `git pull` 同步更新
- `/sp install <repo_url>` — 从远程仓库一键安装新技能包（自动 clone + 权限修正 + 缓存刷新）
- USER 模式下显示简洁进度，DEV 模式显示详细结果

### ⚡ 12. Scrapling 反爬引擎优化 (P6 新增)

- `StealthyFetcher.configure()` 全局预热：消除首次 fetch 的冷启动超时
- 超时自动重试：间隔 2s → 5s → 10s，最多 3 次尝试
- 穿透 Cloudflare 5 秒盾、JS 渲染防护

---

## 📡 核心引擎与多模型接入

PawnLogic 1.1 完整适配 2026 主流 API 生态，支持多模型动态热切换，覆盖从深度推理到毫秒级响应的全场景。原生支持 **OpenAI Chat Completions** 和 **Anthropic Messages** 两种 API 格式，通过 `/provider` 命令可添加自定义中转接口。

### 🗺️ 全球模型支持列表

| 厂商 | 别名 | 推荐模型 ID | 格式 | 优势场景 |
|------|------|------------|------|---------|
| **PawnLogic Engine** | `hermes` / `hermes405` | `NousResearch/Hermes-4-70B` | OpenAI | 框架原生优化，指令遵循极强 |
| **OpenAI** | `gpt-4o` / `gpt-4o-mini` | `gpt-4o` | OpenAI | 视觉+推理，需代理 |
| **Anthropic** | `claude-opus` / `claude-sonnet` / `claude-haiku` | `claude-opus-4-7` | Anthropic | 旗舰推理 / 均衡性能 / 极速响应 |
| **DeepSeek** | `ds-chat` / `ds-r1` | `deepseek-chat` / `deepseek-reasoner` | OpenAI | V3 性价比之王；R1 深度推理首选 |
| **DeepSeek V4** | `ds-v4-pro` / `ds-v4-flash` | `deepseek-v4-pro` | OpenAI | Pwn 漏洞逻辑建模 / 毫秒级响应 |
| **智谱 AI** | `glm-5.1` / `glm-4.7` / `glm-4.5-air` | `glm-5.1` | OpenAI | 国内直连，国产推理旗舰 |
| **智谱 AI (视觉)** | `glm-4v` | `glm-4v-plus` | OpenAI | Web 截图 / 隐写图片分析 |
| **通义千问** | `qwen-max` / `qwen-3.0` | `qwen-3.0-max` | OpenAI | 强大长文本处理与代码纠错 |
| **硅基流动** | `sf-ds-v3` / `sf-qwen72b` | `deepseek-ai/DeepSeek-V3` | OpenAI | 开源模型低成本推理池 |
| **Moonshot** | `kimi` | `moonshot-v1-128k` | OpenAI | 超长上下文日志分析 |
| **Groq** | `groq-llama3` | `llama-3.3-70b-versatile` | OpenAI | **极速**：秒级生成 Exploit 脚本 |
| **小米 MiMo** | `mimo-v2.5-pro` / `mimo-v2.5` | `mimo-v2.5-pro` | OpenAI | 小米自研推理模型，国内直连 |
| **本地 Ollama** | `qwen-local` | `qwen2.5-7b-instruct` | OpenAI | 离线靶机环境，零泄密风险 |
| **自定义 Provider** | 任意别名 | 任意模型 ID | OpenAI/Anthropic | 自建中转接口，通过 `/provider add` 添加 |

> **CTF 场景推荐组合**
> - Pwn 漏洞开发 → `ds-r1` 或 `ds-v4-pro`（深度推理）
> - Web 代码审计 → `ds-chat` 或 `glm-5.1`（高性价比，长上下文）
> - 截图 / 隐写分析 → `glm-4v` 或 `gpt-4o`（多模态视觉）
> - 极速脚本生成 → `groq-llama3`（毫秒级响应）
> - 离线靶机环境 → `qwen-local`（零网络依赖）
> - 旗舰推理 → `claude-opus`（Anthropic 原生格式）

### 🧠 推理模型与 Thinking 支持 (1.1 新增)

PawnLogic 1.1 完美支持包含 `reasoning_content` 的推理模型，自动保留 Agent 的完整思考过程：

- **推理模型列表**：`ds-r1`（DeepSeek R1）、`mimo-v2.5-pro`（小米 MiMo）、`qwq`（阿里 QwQ）等
- **思考过程保留**：所有推理步骤自动存入 SQLite `messages.reasoning_content` 列，支持后续查阅和分析
- **使用方式**：`/think <prompt>` 单次推理模式，或 `/model ds-r1` 切换为推理模型进行多轮对话
- **成本优化**：推理模型通常 Token 消耗更高，建议用于复杂逻辑问题（Pwn 漏洞分析、数学推导、代码审计）

---

## 🚀 部署指南

### 系统要求

- **推荐**：WSL2 / Ubuntu（满血体验）
- **可选**：Windows（基础体验，不支持 Pwn 工具链）



### 🐧 WSL2/Ubuntu 部署（推荐）

由于现代 Linux 发行版（如 Ubuntu 24.04+）引入了 PEP 668 环境隔离机制，**强烈建议使用虚拟环境 (venv) 进行部署**，以避免破坏系统全局 Python 环境。

```bash
# 1. 克隆仓库
git clone [https://github.com/john0123412/PawnLogic.git](https://github.com/john0123412/PawnLogic.git)
cd pawnlogic

# 2. 创建并激活虚拟环境 (解决 pip externally-managed-environment 报错)
python3 -m venv venv
source venv/bin/activate

# 3. 安装核心依赖
pip install --upgrade pip
pip install -r requirements.txt

# 4. (可选) 安装 CTF/Pwn 实战工具链系统依赖
# sudo apt update && sudo apt install gcc g++ python3-dev libssl-dev libffi-dev build-essential

# 5. 配置 API Key（见下方说明）
cp .env.example .env
# 编辑 .env，填入你的 Key

# 6. 启动
python main.py
```

### 🌐 全局 `pawn` 命令部署（推荐）

通过 `pawn.sh` 启动器 + 符号链接，可在任意目录下直接输入 `pawn` 启动 PawnLogic，无需 `cd` 到项目目录。

#### `pawn.sh` 工作原理

`pawn.sh` 是一个智能启动器，每次执行时：

1. **追踪真实路径**：通过 `readlink -f` 解析自身真实位置（即使通过符号链接调用），定位到项目根目录
2. **激活虚拟环境**：自动查找并激活 `venv/` 或 `.venv/`（优先 `venv/`），确保所有 Python 依赖可用
3. **环境检查**：若无 venv 且系统缺少 `nest_asyncio`，给出明确安装指引
4. **启动主程序**：使用 `exec python3 main.py "$@"` 替换当前进程，透传所有命令行参数

由于每次运行都重新解析路径和读取源文件，**在项目目录中修改代码后立即生效**，无需重新部署。

#### 部署步骤

```bash
# 1. 确保 pawn.sh 有执行权限
chmod +x /home/johnny/scripts/agent/pawnlogic_1.0/pawn.sh

# 2. 创建全局符号链接（~/.local/bin 需已在 PATH 中）
ln -sf /home/johnny/scripts/agent/pawnlogic_1.0/pawn.sh ~/.local/bin/pawn

# 3. 验证：在任意目录下执行
cd /tmp && pawn --help
```

#### 调用链

```
任意目录输入 pawn
  → ~/.local/bin/pawn（符号链接）
    → /home/johnny/scripts/agent/pawnlogic_1.0/pawn.sh
      → readlink -f 定位项目根目录
      → source venv/bin/activate
      → exec python3 main.py "$@"
```

#### 注意事项

- 修改 `scripts/agent/pawnlogic_1.0/` 下的任何文件（`main.py`、`config.py`、`core/*` 等）后，下次运行 `pawn` 即使用最新代码
- 符号链接只需创建一次，之后无需重复操作
- 若 `~/.local/bin` 不在 PATH 中，需先添加：`export PATH="$HOME/.local/bin:$PATH"`（加入 `~/.bashrc` 持久化）

### 🪟 Windows 部署（基础体验）

*注意：Windows 缺乏原生 Linux 命令，仅支持 Python 沙箱、网页搜索、文件修改和对话。不建议用于 Pwn 题或编译 C 语言。*

1. 安装 [Python 3.10+](https://www.python.org/downloads/)
2. 打开 PowerShell，设置 API Key 环境变量：

   ```powershell
   [System.Environment]::SetEnvironmentVariable('DEEPSEEK_API_KEY', 'sk-填写你的Key', 'User')
   ```

3. 进入目录并运行：

   ```powershell
   cd D:\pawnlogic
   python main.py
   ```

### 🐳 Docker 容器化部署（P3 新增）

Docker 容器化让 Agent 能在**完全隔离的容器环境**中执行代码，适用于 CTF 靶机 exploit 测试、多版本 libc 环境验证等场景。

#### 第一步：安装 Docker CE

```bash
# Ubuntu / WSL2
sudo apt update
sudo apt install -y docker.io
sudo systemctl start docker
sudo systemctl enable docker

# 将当前用户加入 docker 组（免 sudo）
sudo usermod -aG docker $USER
# 重新登录终端生效
```

> **WSL2 用户注意**：WSL2 默认没有 systemd，需要手动启动 dockerd：
> ```bash
> sudo dockerd &
> # 或在 /etc/wsl.conf 中添加:
> # [boot]
> # systemd=true
> # 然后在 PowerShell 中运行: wsl --shutdown && wsl
> ```

#### 第二步：安装 Python Docker SDK

```bash
# 在 PawnLogic venv 中安装
pip install docker
```

#### 第三步：验证 Docker 连接

启动 PawnLogic 后，运行 `/docker status`：

```
▶ You > /docker status

  Docker 状态：
  ✓ Docker 连接正常
  版本: 24.0.7
  容器: 0 个  |  镜像: 5 个
  存储: /var/lib/docker
```

#### 第四步：拉取常用镜像

```bash
# 方法 1：在 PawnLogic 终端内拉取
▶ You > /docker pull pwndocker
▶ You > /docker pull ubuntu18

# 方法 2：在系统终端拉取
docker pull skysider/pwndocker
docker pull ubuntu:18.04
```

#### 预设镜像说明

| 别名 | 镜像 | 用途 |
|------|------|------|
| `pwndocker` | `skysider/pwndocker` | Pwn 全能靶机（含 GDB/pwntools/ROPgadget/checksec） |
| `ubuntu18` | `ubuntu:18.04` | glibc 2.27，老题常用 |
| `ubuntu22` | `ubuntu:22.04` | glibc 2.35，新题常用 |
| `kali` | `kalilinux/kali-rolling` | Kali 渗透测试环境 |
| `python` | `python:3.12-slim` | 纯 Python 执行环境 |
| `gcc` | `gcc:latest` | C/C++ 编译环境 |

#### 使用方式

**方式 1：一次性容器（`run_code_docker`）**

Agent 自动调用，代码执行完毕后容器自动销毁：

```
▶ You > 用 run_code_docker 在 pwndocker 容器中运行 exploit.py，断网模式
```

Agent 会自动：
1. 拉取镜像（如果本地不存在）
2. 将代码写入临时目录并挂载到容器
3. 在容器内执行（默认断网 `network=none`）
4. 读取输出并销毁容器

**方式 2：持久化容器（`pwn_container`）**

适合需要多次交互的 Pwn 调试：

```
▶ You > 创建一个名为 heap-lab 的 pwndocker 容器，然后在里面运行 checksec
```

Agent 会自动：
1. `pwn_container(action="create", name="heap-lab", image="pwndocker")`
2. `pwn_container(action="exec", name="heap-lab", command="checksec /target/vuln")`
3. 多次 exec 后：`pwn_container(action="destroy", name="heap-lab")`

**方式 3：手动管理（`/docker` 命令）**

```bash
▶ You > /docker status       # 查看 Docker 连接状态
▶ You > /docker images       # 列出本地镜像
▶ You > /docker ps           # 列出 PawnLogic 容器
▶ You > /docker pull pwndocker  # 拉取指定镜像
```

#### 安全特性

- **默认断网**：`network=none`，防止 CTF flag 泄露
- **资源限制**：内存 512MB、CPU 0.5 核、PID 256
- **自动销毁**：一次性容器执行后自动清理
- **危险命令拦截**：Docker 内外共享同一套 `DANGEROUS_PATTERNS` 黑名单

#### 不安装 Docker 会怎样？

PawnLogic 对 Docker 采用**优雅降级**策略：
- 本地沙箱 `run_code` 完全不受影响
- `run_code_docker` / `pwn_container` 会返回明确的安装指引
- `/docker status` 会显示 `✗ Docker 不可用: 未安装 docker-py`

---

## 🔑 API Key 配置指南

### 三步到位

**第一步：复制模板**

```bash
cp .env.example .env
```

**第二步：填入你的 Key**

用任意编辑器打开 `.env`，按需填写。不用的厂商直接留空，不影响其他模型运行。

**第三步：启动**

```bash
python main.py
# 或指定起始模型
python main.py --model ds-r1
```

### 📄 .env.example

```dotenv
# ════════════════════════════════════════════════════════
# PawnLogic 1.1 — API Key 配置
# 复制本文件为 .env，填入对应 Key，不使用的厂商留空即可。
# 警告：.env 含敏感凭证，已加入 .gitignore，切勿提交至版本库。
# ════════════════════════════════════════════════════════

# ── PawnLogic 默认引擎（Nous Research）──────────────────
PAWN_API_KEY=your_nous_api_key_here

# ── OpenAI ──────────────────────────────────────────────
OPENAI_API_KEY=sk-...

# ── DeepSeek（V3 日常 / R1 深度推理 / V4 前沿）──────────
DEEPSEEK_API_KEY=sk-...

# ── 通义千问 Qwen（阿里云百炼）─────────────────────────
QWEN_API_KEY=sk-...

# ── 智谱 GLM（含视觉模型 glm-4v-plus）──────────────────
ZHIPU_API_KEY=your_zhipu_api_key_here

# ── 硅基流动 SiliconFlow ───────────────────────────────
SILICON_API_KEY=sk-...

# ── OpenRouter（多模型聚合网关，可选）──────────────────
OPENROUTER_API_KEY=sk-...

# ── Moonshot (Kimi) ─────────────────────────────────────
MOONSHOT_API_KEY=sk-...

# ── MiniMax (海螺) ───────────────────────────────────────
MINIMAX_API_KEY=your_minimax_api_key_here

# ── Groq（极速推理）────────────────────────────────────
GROQ_API_KEY=gsk_...

# ── 小米 MiMo ──────────────────────────────────────────
XIAOMI_API_KEY=your_xiaomi_api_key_here

# ── 本地 Ollama（无需 Key，自定义端口时修改 URL）────────
# LOCAL_API_URL=http://localhost:11434/v1/chat/completions
# LOCAL_API_KEY=

# ── Anthropic (Claude) ──────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...
```

### 🔍 运行时验证 Key 状态

启动后使用 `/keys` 命令即时检查各厂商的 Key 配置状态：

```
You > /keys

Provider         Env Var             Status
────────────────────────────────────────────
PawnLogic Engine PAWN_API_KEY        ✅ 已配置
OpenAI           OPENAI_API_KEY      ❌ 未配置
DeepSeek         DEEPSEEK_API_KEY    ✅ 已配置
Qwen             QWEN_API_KEY        ✅ 已配置
ZhipuAI          ZHIPU_API_KEY       ✅ 已配置（视觉可用）
SiliconFlow      SILICON_API_KEY     ❌ 未配置
Moonshot         MOONSHOT_API_KEY    ✅ 已配置
Groq             GROQ_API_KEY        ✅ 已配置
Xiaomi MiMo      XIAOMI_API_KEY      ✅ 已配置
Local Ollama     LOCAL_API_KEY       ⬜ 无需 Key
```

使用 `/model <别名>` 切换，例如：

```bash
/model ds-r1          # 切换至 DeepSeek R1 深度推理
/model claude-sonnet  # 切换至 Claude Sonnet（Anthropic 原生格式）
/model glm-4v         # 切换至智谱视觉模型，可传入截图分析
/model groq-llama3    # 切换至 Groq 极速模式
/model qwen-local     # 切换至本地 Ollama，断网也能用
```

### 🔌 自定义 API Provider（OpenAI / Anthropic 双格式原生支持）

PawnLogic 原生支持 OpenAI Chat Completions 和 Anthropic Messages 两种 API 格式，可通过 `/provider` 命令添加自建中转接口或其他第三方 API。

```bash
/provider              # 打开交互式 Provider 管理面板
/provider list         # 列出所有 Provider 状态（含格式标记）
/provider add          # 添加自定义 Provider（引导式配置）
/provider remove <n>   # 删除自定义 Provider
/provider test <model> # 测试 Provider 连通性
```

**添加自定义 Provider 示例：**

```
You > /provider add

  Provider 名称: my_relay
  API 格式: [1] OpenAI / [2] Anthropic → 1
  Base URL: https://my-relay.com/v1/chat/completions
  API Key: ****
  模型 ID: gpt-4o
  模型别名: my-gpt

  ✓ Provider 'my_relay' 已添加
  使用: /model my-gpt
```

**安全说明：**
- API Key 仅存入 `.env` 文件（已加入 `.gitignore`，不会被提交）
- 结构化配置存入 `~/.pawnlogic/custom_providers.json`（项目目录外，不含 Key）
- 所有 Key 通过环境变量读取，代码中零硬编码

---

## 📖 核心命令手册

启动终端后，你会看到 `You >` 提示符。可以像使用 ChatGPT 一样直接对话，也可以使用 `/` 开头的快捷命令。

### ⚙️ 环境与模型控制

- `/mode` — 切换 USER / DEV 输出模式（USER 屏蔽底层错误，DEV 显示所有细节）
- `/model [alias]` — 切换大模型（如 `/model glm-5.1`）
- `/setkey` — 重新运行 API Key 配置向导
- `/keys` — 显示各 Provider Key 配置状态
- `/clear` — 清空历史对话释放 Token（保留已 Pin 消息和项目 State）
- `/cd <path>` — 切换 Agent 的工作目录
- `/file ./test.py` — 将某个文件一次性载入到对话上下文
- `/undo [n]` — 撤回最近 n 轮对话（默认 1）
- `/compact` — 压缩上下文（轻量模型总结 + 清空历史）
- `/think <prompt>` — 单次推理模式（自动切换推理 Worker）
- `/ping` — 保活请求，刷新缓存 TTL

### 🧠 项目管理与 GSD 工作流

- `/init_project [目标描述]` — 初始化当前目录的 `.nous_state.md`，开启自动化工程流水线
- `/state` — 查看当前项目的总体规划
- `/memorize [主题]` — AI 总结当前对话并永久存入 SQLite 知识库
- `/knowledge [query]` — 搜索/列出知识条目
- `/forget <id>` — 删除指定知识条目

### 💾 会话存档与精度控制

- `/history` — 查看带序号的历史记录
- `/pin msg <n>` — 精准固定第 n 条消息，防止被遗忘
- `/save [项目名]` — 保存当前对话进度到数据库
- `/sessions` — 列出所有会话
- `/load <name|n>` — 加载历史会话（名称子串/序号）
- `/resume [n]` — 恢复会话并显示对话历史（最近消息完整展示，更早消息折叠）
- `/rename <n> <name>` — 重命名已保存会话
- `/del <name|n>` — 删除指定会话

### 🔍 会话浏览器 (1.1)

- `/chat list [n]` — 列出最近 n 个会话（默认20）
- `/chat view <id|n>` — 查看某个会话的完整对话内容
- `/chat export <id|n> [文件路径]` — 导出对话为 Markdown 文件
- `/chat find <关键词>` — 跨所有会话全文搜索内容
- `/chat tag <id|n> <标签>` — 给会话打标签（逗号分隔）
- `/chat untag <id|n> <标签>` — 移除会话标签
- `/chat bytag <标签>` — 按标签筛选会话
- `/chat link <id1> <id2> [备注]` — 关联两个会话
- `/chat unlink <id1> <id2>` — 取消关联
- `/chat related <id|n>` — 查看与指定会话相关联的所有会话

### 🧮 四档预设（算力调节）

- `/low` — 日常闲聊/简单问答（tokens=4k, ctx=40k, iter=10）
- `/mid` — 开发编程/脚本编写（tokens=8k, ctx=150k, iter=30）← 默认
- `/deep` — 论文阅读/大型项目重构/复杂漏洞挖掘（tokens=32k, ctx=400k, iter=50）
- `/max` — 极限火力：大规模自动化利用链/超长会话（tokens=32k, ctx=600k, iter=100, 60min）
- `/normal` — 重置到 /mid

### 🔧 细粒度调节

- `/tokens /ctx /iter /toolsize /fetchsize <n>` — 调整具体参数
- `/limits` — 查看所有当前限制

### 🛠️ 工具状态

- `/webstatus` — Jina / Pandoc / Lynx 状态
- `/browserstatus` — Scrapling 浏览器工具状态
- `/pwnenv` — CTF 工具链完整性检查

### 🐳 Docker 容器管理（1.1 新增）

- `/docker status` — 查看 Docker 连接状态
- `/docker images` — 列出本地镜像
- `/docker ps` — 列出 PawnLogic 管理的容器
- `/docker pull <镜像>` — 拉取指定镜像（支持别名如 `pwndocker`）

### 🧹 Workspace 维护（1.1 新增）

- `/workspace status` — 查看 workspace 概览（大小/文件数/DB 一致性）
- `/workspace cleanup` — 生成清理清单（只读扫描 + 自动备份，不修改文件）
- `/workspace cleanup plan` — Phase 0+1：备份 workspace + 扫描生成清单
- `/workspace cleanup execute` — Phase 2+3：按清单归档到 `~/.pawnlogic/archive/` + DB workspace_dir 补写
- `/workspace cleanup restore` — 从最近 tar 备份回滚整个 workspace（原子化操作）

**使用场景**：
- 定期清理散落的临时文件、孤儿会话目录、过期脚本
- 保留核心目录（skills/、screenshots/、writeups/ 等）
- 自动修复 DB 中 workspace_dir 为空的会话
- 完整备份 + 原子化回滚，零数据丢失风险

### ⏱️ 时间感知调度（1.1 新增）

- `/time` — 查看当前时间预算、已用时间、剩余时间
- `/time <秒数>` — 设置时间预算（如 `/time 300` = 5 分钟）
- `/time 0` — 关闭时间限制
- 剩余 <30s 时自动触发 URGENT_MODE（跳过 Plan、切极速模型、压缩输出）

### 🎯 Worker 模型选择（1.1 新增）

- `/worker` — 显示子任务 Worker 候选模型菜单（带 Key 状态）
- `/worker <alias>` — 手动锁定子任务使用的模型
- `/worker auto` — 恢复自动路由（按优先级选取首个可用小模型）

### 🛡️ 防御性审计（1.1 新增）

- `/failures` — 查看最近 20 条工具调用失败记录
- `/failures <N>` — 查看最近 N 条
- `/failures clear` — 清空所有失败记录
- Agent 执行 `run_code` / `run_shell` / `run_interactive` 前自动检查历史失败

### 📚 全局技能存档 (GSA)

- `/memo [内容]` — 手动存档技能：AI 自动分类并写入 `~/.pawnlogic/global_skills.md`
- `/memo` — 不带参数：对当前对话最后一轮 AI 回复进行存档
- `/skills` — 查看 `global_skills.md` 的分类目录
- `/skills view` — 查看 `global_skills.md` 全部内容（分页）
- `/skills path` — 显示技能文件路径

### 🗂️ 本地技能引擎 (P6 新增)

- `./skills/` 目录存放技能包文件夹（零配置：放一个 `.md` 即可，可选 `manifest.json`）
- Agent 根据任务关键词自动匹配并注入相关技能
- `/sp` 或 `/skillpack` — 列出所有本地技能包
- `/sp rescan` — 清除缓存，重新扫描 skills/ 目录
- `/sp sync` — 同步所有带 `.git` 的技能包（批量 git pull）
- `/sp install <url>` — 从远程仓库安装新技能包
- `/sp <名称>` — 查看指定技能包详情（关键词、触发词、脚本）

### 🔍 环境嗅探 (P6 新增)

- `check_service(port)` — 检查指定端口上运行的服务进程详情
- 返回：PID、进程名、可执行文件路径、命令行、工作目录、环境变量、动态库
- 侦察阶段自动调用，替代盲目执行 `ps aux`

---

## 💡 终极使用场景演示

### 场景一：大型工程重构（GSD 威力展示）

> **You >** `/init_project` 写一个带权限控制的 FastAPI 用户管理系统。

Agent 会先读取项目状态，输出严格的 `<plan>`，规划好 `models.py`、`auth.py` 等模块，并写好 `<verify>` 验证脚本。每写完并验证通过一个文件，就会在后台静默执行 `git commit`。你去喝杯咖啡，回来就是一个功能完整且自带版本记录的完美仓库。

### 场景二：多模态解题分析（Vision 威力展示）

> **You >** 看看这张截图 `./error_log.png`，帮我用 `delegate_task` 委派子 Agent 搜索报错解决方案，然后写个修复脚本。

Agent 调用 `analyze_local_image` 读取图片转 Base64 喂给视觉模型提取报错文本，启动纯净子会话独立执行全网搜索与代码编写，最后把完美的解决方案返回给主聊天窗口。

### 场景三：极客 CTF 逆向

> **You >** 分析 `./vuln_pwn`。找到栈溢出偏移量，并使用 `pwn_debug` 在 `main` 函数下断点观察。

Agent 自动检测环境，调用 checksec、使用 de Bruijn 生成特征序列、自动编写 GDB 批处理脚本进行动态调试并返回寄存器状态。

### 场景四：双模输出 — 面试演示 vs 深度调试 (P6)

> **You >** `/mode`（切换到 USER 模式）
>
> **You >** 运行 `./broken_script.py`

Agent 执行失败，终端只显示：`❌ 系统忙，请稍后重试`（无 Traceback、无 JSON 轰炸）。

> **You >** `/mode`（切回 DEV 模式）
>
> **You >** 再次运行 `./broken_script.py`

终端完整展示 Traceback、工具调用 JSON、异步线程状态——开发者可精准定位问题。

### 场景五：P6 自动化利用链 (Web 渗透)

> **You >** 扫描 http://target.com:8080，找到漏洞并利用

Agent 自动执行完整 P6 流程：
1. **侦察**：`web_fetch` 获取页面指纹，识别框架（如 Shiro）
2. **环境确认**：`check_service(port=8080)` 提取进程信息（Java/Tomcat）
3. **武器检索**：`search_skills(query='Shiro')` 匹配本地技能包
4. **同步更新**：提醒 `/sp sync` 或 `/sp install` 获取最新利用脚本
5. **执行**：运行技能包内的预置 exploit 脚本
6. **验证**：确认回显/Flag，调用 `bump_skill` 提升技能权重

全程 USER 模式只显示简洁进度，DEV 模式显示每个工具调用细节。

### 场景六：会话管理与项目追踪 (1.1)

```bash
/chat find Python 爬虫          # 搜索所有包含关键词的会话
/chat tag 3 爬虫项目,学习笔记   # 给第3个会话打标签
/chat bytag 爬虫项目            # 筛选所有该标签的会话
/chat link 3 5 "同一项目的不同阶段"  # 关联两个相关会话
```

---

## 📂 系统架构与数据分布

### 📁 代码目录：`~/.local/share/pawnlogic/`

- `main.py` — 入口与 Slash 命令解析
- `config.py` — API、预设参数、MoE 阶段路由、黑白名单配置
- `core/session.py` — 核心调度环（Agentic Loop）、流式解析、工具注册
- `core/memory.py` — SQLite 数据库管理与 RAG 检索
- `core/persistence.py` — 会话持久化管理
- `core/gsa.py` — 全局技能存档管理
- `core/skill_manager.py` — SkillScanner 技能包扫描、匹配、同步、安装引擎
- `core/logger.py` — loguru 双端日志系统
- `tools/` — 工具库
  - `file_ops.py` — 文件操作（读/写/补丁/Shell）
  - `web_ops.py` — 网页搜索与抓取
  - `browser_ops.py` — Scrapling 反爬浏览器武器库（StealthyFetcher + Patchright）
  - `recon_ops.py` — 环境嗅探（check_service：端口→进程详情）
  - `sandbox.py` — 多语言代码沙箱
  - `docker_sandbox.py` — Docker 容器化执行
  - `pwn_chain.py` — CTF/Pwn 工具链（GDB/ROP/libc/one_gadget）
  - `vision.py` — 多模态视觉分析
  - `delegate_tool.py` — 无污染子任务委派
- `skills/` — 本地技能包目录（文件夹模式，含 skill.md + 可选 manifest.json + 脚本）

### 📁 数据存储：`~/.pawnlogic/`

- `pawn.db` — 核心 SQLite 数据库（含 `sessions`、`messages`、`knowledge` 表）
- `global_skills.md` — 全局技能存档文件
- `sessions/` — 会话文件存储目录

### 🔒 安全限制说明

Agent 内置严格的软隔离保护：

1. **读保护**：禁止读取 `~/.ssh`、`~/.gnupg`、`/etc` 等敏感凭证目录
2. **写保护**：禁止向 `/bin`、`/boot`、`/lib`、`/sys` 等系统关键路径写入文件
3. **高危命令拦截**：内置正则拦截 `rm -rf /`、`mkfs`、`dd if=` 等毁号操作
   *(如有需求，请在 `config.py` 的 `WRITE_BLACKLIST` 中自行放开)*

---

## 🔄 版本更新日志

### v1.1（当前版本）

**会话自动命名与动态工作区 (Dynamic Workspace)**
- ✅ 自动命名：新会话在第 2 轮对话时自动触发命名流程，Agent 根据对话内容生成语义化名称
- ✅ 动态工作区：每个会话拥有独立的 `~/.pawnlogic/workspace/session_<timestamp>_<hash>/` 工作目录
- ✅ 原子化切换：会话加载时自动 rename + 反向 symlink + 指针更新，确保切换的原子性和可回滚性
- ✅ DB 一致性修复：所有 76 条会话的 workspace_dir 均已验证有效，`/chat load` 永不返回空路径
- ✅ Workspace 维护工具：新增 `/workspace cleanup` 系列命令（status/plan/execute/restore）

**推理模型与 Thinking 支持**
- ✅ 完美支持 `reasoning_content` 推理模型：DeepSeek R1、小米 MiMo、阿里 QwQ 等
- ✅ 思考过程保留：所有推理步骤自动存入 SQLite `messages.reasoning_content` 列
- ✅ `/think <prompt>` 单次推理模式，自动切换至推理 Worker，用完恢复原模型
- ✅ 成本优化：推理模型用于复杂逻辑问题（Pwn 漏洞分析、数学推导、代码审计）

**自定义 Provider 与双格式 API 原生支持**
- ✅ 原生支持 OpenAI Chat Completions 和 Anthropic Messages 两种 API 格式
- ✅ Anthropic 原生接入：`claude-opus-4-7`、`claude-sonnet-4-6`、`claude-haiku-4-5`
- ✅ `/provider` 命令面板：交互式添加/删除/测试自定义 Provider
- ✅ 自定义 Provider 配置持久化至 `~/.pawnlogic/custom_providers.json`（不含 Key）
- ✅ API Key 安全存储：仅存 `.env`（已 gitignore），通过环境变量注入
- ✅ `/model` 显示格式标记：`[A]` = Anthropic 格式

**会话管理增强**
- ✅ `/rename <序号> <新名称>` — 重命名已保存会话
- ✅ `/resume` 恢复会话时自动显示对话历史
- ✅ 对话历史智能展示：最近 6 条完整显示，更早消息折叠为摘要

**P0 — 安全加固与防御性审计**
- ✅ 修复 git commit 命令注入（web_ops.py 改用 subprocess 列表形式）
- ✅ 沙箱环境变量隔离（剔除所有 API Key）
- ✅ 危险模式扩展（fork bomb / reverse shell / curl|sh 等 14 种）
- ✅ 语义级失败判定（检测 Traceback / Segfault / exit code 等 20+ 信号）
- ✅ 投前审计：`run_code` / `run_shell` / `run_interactive` 执行前自动检查历史失败
- ✅ 失败自动记录 + 同类失败 ≥3 次自动沉淀到 `global_skills.md`
- ✅ `audit_payload` 工具 + `/failures` 命令

**P1 — 时间感知调度**
- ✅ 三档预设新增 `time_budget_sec`（LOW=5min / MID=10min / DEEP=30min）
- ✅ URGENT_MODE：剩余 <30s 自动触发极速模式（跳过 Plan、切模型、压缩输出）
- ✅ `/time` 命令：查看/设置时间预算
- ✅ `pwn_timed_debug` 工具：倒计时感知的 CTF 交互式调试

**P2 — CLI UX 终端体验升级**
- ✅ `prompt_toolkit` 集成：FuzzyCompleter 模糊匹配 + Fish-style 灰色内联提示
- ✅ CC 风格内联模型选择器（上下键 + Enter 确认 + Esc 取消 + 数字键跳转）
- ✅ `rich` Markdown 渲染（代码块高亮 + 表格对齐）
- ✅ 底部状态栏（模型 / 档位 / Token 消耗 / Ctx% 上下文占比 / 目录 / Phase 实时显示）
- ✅ Ctx% 三色阈值：绿色(<70%) / 黄色(70-90%) / 红色(≥90%)，提醒及时 `/save` 或 `/compact`
- ✅ 模糊命令修正（`/modle` → `/model`，相似度 ≥0.7 自动修正）
- ✅ Windows 兼容（readline / prompt_toolkit 安全导入）

**P3 — Docker 动态容器化**
- ✅ `run_code_docker` 工具：一次性容器执行（创建 → 执行 → 销毁）
- ✅ `pwn_container` 工具：持久化容器管理（create / exec / destroy / list）
- ✅ 6 个预设镜像别名（pwndocker / ubuntu18 / ubuntu22 / kali / python / gcc）
- ✅ 默认断网 + 资源限制（512MB / 0.5 核 / PID 256）
- ✅ `/docker` 命令（status / images / ps / pull）
- ✅ Docker 不可用时优雅降级，不影响本地沙箱

**P6 — 双模输出与技能引擎**
- ✅ `/mode` 命令：一键切换 USER / DEV 输出模式
- ✅ USER_MODE 错误屏蔽：10+ 种常见异常自动转为友好中文提示
- ✅ `user_friendly_error()` 统一错误映射函数
- ✅ `./skills/` 本地技能目录：Agent 按关键词自动检索匹配的领域技能
- ✅ `_scan_local_skills()` 技能扫描引擎（文件名 + 内容评分排序）
- ✅ 技能全文动态注入系统提示词

**P6 — 自动化利用链架构升级**
- ✅ Scrapling 启动优化：`StealthyFetcher.configure()` 全局预热，消除冷启动超时
- ✅ `web_fetch` 超时自动重试：间隔 2s → 5s → 10s，最多 3 次
- ✅ `check_service(port)` 环境嗅探工具：lsof/proc 提取端口进程详情（PID/路径/环境变量/动态库）
- ✅ `/sp sync` 全球技能包同步：批量 git pull 所有带 .git 的技能包
- ✅ `/sp install <url>` 远程技能包安装：git clone + 权限修正 + 缓存刷新
- ✅ P6 流程闭环：侦察 → check_service → search_skills → install/sync → 执行
- ✅ `check_service` 注册到 RECON/GENERAL/WEB_PEN 阶段，只读操作跳过 plan 检查

**P6 — CC 风格交互 & 成本微操**
- ✅ Ctrl+C 回退编辑：输入状态下 Ctrl+C 撤回最后一轮对话，将用户文本作为 default 重新编辑（对齐 Claude Code 体验）
- ✅ `/undo [n]` 物理删除尾部消息对，不影响 Pin
- ✅ `/compact` 轻量模型总结 → 清空历史 → 摘要作首条消息
- ✅ `/think <prompt>` 单次推理模式，自动切换推理 Worker（ds-r1/qwq）
- ✅ `/ping` 极简保活请求，刷新 API 缓存 TTL
- ✅ `utils/ansi.py` 新增 `Spinner` 类：USER_MODE 下 Loading 动画（braille 点阵旋转）
- ✅ System Prompt 精简：P6 协议改为祈使句风格，技能注入格式压缩

**P7 — API 鲁棒性与逻辑刷新**
- ✅ API 空响应重试：自定义 `APIEmptyResponseError` + 指数退避（2s→4s→8s，最多 3 次），空响应不再静默退出
- ✅ Logic Refresh 模块：每 20 轮自动触发阶段性总结，提炼关键发现与排除路径
- ✅ 冗余数据清理：自动压缩重复的短报错信息（No such file / Permission denied 等）
- ✅ Anti-Loop 检测：连续 3 次相同命令+相同错误 → 注入绕过提示（软链接/open_basedir/路径编码）
- ✅ Shell 环境持久化：自动探测 HOST_IP、缓存代理变量，所有 shell 调用继承
- ✅ 路径自动建议：文件未找到时提示 `find / -name`、`/proc/self/cwd`、`readlink -f`
- ✅ 超时信号捕获：Popen + 进程组 → SIGTERM → 等待 → SIGKILL，收集部分输出
- ✅ `/max` 极限档位：iter=100, ctx=600k, 60min 时间预算，适配大规模自动化利用链

**P8 — 状态栏增强 + Pwn 工具链深化 + 技能引擎优化**
- ✅ 底部状态栏新增 Token 累计消耗 + Ctx% 上下文占比实时显示
- ✅ Ctx% 三色阈值：绿色(<70%) / 黄色(70-90%) / 红色(≥90%)
- ✅ `inspect_binary` 自动写入 `.pawn_state.md`：Agent 始终拥有最新二进制快照
- ✅ GDB 崩溃自动 `bt full`：检测 SIGSEGV/SIGABRT/SIGBUS 后自动追加完整回溯（含局部变量）
- ✅ 技能包 `min_score=3` 阈值过滤：普通聊天零注入，仅相关意图触发技能加载
- ✅ 推理模型 deepcopy 隔离：跨模型切换时 `session.messages` 零污染
- ✅ Rich Markup 转义：shell 输出含 `[/path]` / `[^]` 等字符不再触发 MarkupError

**基础改进**
- ✅ 新增小米 MiMo 厂商接入（4 个模型）
- ✅ `/worker` 子任务模型选择命令
- ✅ FTS5 全文搜索引擎
- ✅ 审计日志系统（`~/.pawnlogic/logs/audit_*.jsonl`）
- ✅ 版本号统一为 1.1
- ✅ `requirements.txt` 依赖声明

### v1.0

- ✅ **新增 `/chat` 会话管理命令系列**：浏览、搜索、标签、关联历史对话
- ✅ **增强 SQLite 数据库**：新增会话标签、关联、全文搜索功能
- ✅ **2026 全生态模型接入**：DeepSeek V4、GLM-5.1、Qwen 3.0、Groq、Moonshot 等
- ✅ **优化配置向导**：支持 12 大厂商 API Key 配置
- ✅ **新增智谱 AI 视觉模型支持**：`glm-4v-plus` 国内直连
- ✅ GSD 企业级工程架构 · 多模态视觉 · SQLite 持久化 · RAG 知识库 · 多语言沙箱 · CTF/Pwn 工具链

---

## 🆘 常见问题

**Q: 如何切换模型？**
A: 使用 `/model` 命令，如 `/model ds-v4-pro` 切换到 DeepSeek V4 Pro。

**Q: 如何查看所有可用的模型？**
A: 启动时会显示模型列表，或使用 `/help` 查看。

**Q: 如何备份我的会话？**
A: 使用 `/chat export <id> ./backup.md` 导出为 Markdown 文件。

**Q: 如何找到之前的某个项目？**
A: 使用 `/chat find <关键词>` 全文搜索，或 `/chat bytag <标签>` 按标签筛选。

**Q: Agent 运行缓慢怎么办？**
A: 使用 `/low` 切换低算力模式，或 `/model groq-llama3` 切换至 Groq 极速引擎，或 `/clear` 清空上下文释放 Token。

**Q: 如何查看系统状态？**
A: 使用 `/limits` 查看当前配置，`/pwnenv` 检查工具链完整性。

**Q: Docker 连不上怎么办？**
A: WSL2 用户需要手动启动 Docker：`sudo dockerd &`，或在 `/etc/wsl.conf` 中启用 systemd。运行 `/docker status` 查看具体错误。

**Q: Docker 镜像拉取太慢怎么办？**
A: 配置 Docker 镜像加速器（如阿里云）。在 `/etc/docker/daemon.json` 中添加 `{"registry-mirrors": ["https://xxx.mirror.aliyuncs.com"]}`，然后 `sudo systemctl restart docker`。

**Q: 不装 Docker 能用 PawnLogic 吗？**
A: 完全可以。Docker 是可选功能，本地沙箱 `run_code` 不受影响。`run_code_docker` 和 `pwn_container` 会返回安装指引。

**Q: 如何用 Docker 跑不同版本 libc 的 Pwn 题？**
A: 使用 `ubuntu18`（glibc 2.27）或 `ubuntu22`（glibc 2.35）镜像：`/docker pull ubuntu18`，然后让 Agent 用 `run_code_docker(image="ubuntu18", ...)` 执行。

**Q: USER 模式和 DEV 模式有什么区别？**
A: `/mode` 切换。USER 模式屏蔽所有原始报错，只显示友好中文提示（如 `❌ 系统忙，请稍后重试`），适合演示和日常使用。DEV 模式显示完整 Traceback、Tool Call JSON 和底层日志，适合开发调试。

**Q: 如何撤回上一轮对话？**
A: 使用 `/undo` 撤回最近 1 轮，或 `/undo 3` 撤回最近 3 轮。在输入状态下按 Ctrl+C 也可快速撤回。

**Q: 上下文快满了怎么办？**
A: 使用 `/compact` 让轻量模型总结当前进度并清空历史，或 `/clear` 直接清空。`/compact` 会保留 Pin 消息和总结摘要。

**Q: 如何让 Agent 深度推理？**
A: 使用 `/think <你的问题>`，自动切换至推理模型（ds-r1/qwq），用完恢复原模型。

**Q: 如何添加自定义技能？**
A: 在 `./skills/` 目录下创建文件夹，放入 `skill.md`（或 `guide.md`），系统自动从文件名和标题提取关键词。也可添加 `manifest.json` 补充元数据。详见 `skills/README.md`。

**Q: 如何同步社区最新的利用脚本？**
A: 使用 `/sp install <repo_url>` 从 GitHub 安装技能包，或 `/sp sync` 批量更新已有的 `.git` 技能包。

**Q: check_service 工具安全吗？**
A: 完全安全。它是只读操作，仅通过 `/proc` 或 lsof 读取进程信息，不修改任何系统状态。已加入 `_PLAN_EXEMPT_TOOLS`，跳过 plan 检查。

**Q: 时间预算用完了会怎样？**
A: Agent 自动终止当前任务，输出已收集的结果。建议根据任务复杂度设置合理预算：`/time 300`（5 分钟）适合简单任务，`/time 1800`（30 分钟）适合复杂项目。

---

## 📞 支持与贡献

- **GitHub**: [PawnLogic 项目仓库](https://github.com/john0123412/PawnLogic)
- **文档**: 查看本 README 和代码内注释
- **问题反馈**: 请通过 GitHub Issues 提交

---

**祝您使用愉快！** 🚀
