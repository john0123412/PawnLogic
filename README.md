# 🤖 PawnLogic 1.0

> **GSD 工程外骨骼 · 多模态视觉 · 会话管理 · SQLite 记忆 · 动态沙箱 · CTF 逆向工具链**

PawnLogic 是一个专为极客和开发者打造的全能终端 AI 智能体。强大的会话管理系统，让您能够轻松浏览、搜索、标签化和关联历史对话，同时保留了所有强大功能。

> ✅ 完美支持 **WSL2** 及其环境下的本地工具链调用

---

## ✨ 核心特性一览

### 🧠 1. 强大的会话管理系统 (1.0 新增)

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

### 🏗️ 2. GSD 企业级工程架构

- **规格驱动规划 (Spec-Driven)**：Agent 写代码前必须输出包含 `<action>` 和 `<verify>` 的 XML 计划
- **无污染子任务委派 (Fresh Context)**：内置 `delegate_task` 工具，解决"上下文腐化"问题
- **原子化自动提交**：每次修改代码并通过测试后自动调用 `git commit`
- **全局状态管理**：使用 `/init_project` 生成 `.pawn_state.md`

### 👁️ 3. 多模态视觉支持

- 终端 AI "看图"能力，支持 `glm-4v`、`gpt-4o` 等视觉模型
- **适用场景**：识别报错截图、分析网页 UI、读取 CTF 隐写图片、解析系统架构图

### 🛠️ 4. 极客专属能力

- **多语言隔离沙箱**：Python / C / C++ / JS / Bash / Rust / Go / Java
- **智能 Web 爬虫**：Jina Reader → Pandoc → 正则兜底（三级降级策略）
- **Pwn/CTF 工具链**：GDB 批处理动态调试、ROPgadget、de Bruijn 溢出偏移计算

### 🧠 5. 结构化持久记忆

- **SQLite 驱动**：`~/.pawnlogic/pawn.db`，支持多会话保存与无缝加载
- **原生 RAG**：`/memorize` 将高价值对话沉淀进本地知识库，跨会话自动注入
- **精准锁定**：`/pin msg <n>` 防止关键消息被遗忘

### 🔀 6. 多厂商大模型路由 (2026 全生态)

- 支持 **11 大厂商**：Nous / OpenAI / DeepSeek / Qwen / ZhipuAI / SiliconFlow / OpenRouter / Moonshot / MiniMax / Groq / Ollama
- 使用 `/model` 命令无缝热切换，`/setkey` 重新配置 API Key
- 动态加载机制：未配置的 Key 不影响其他模型正常运行

---

## 📡 核心引擎与多模型接入

PawnLogic 1.0 完整适配 2026 主流 API 生态，支持多模型动态热切换，覆盖从深度推理到毫秒级响应的全场景。所有厂商均兼容 **OpenAI Chat Completions 格式**，可无缝切换。

### 🗺️ 全球模型支持列表

| 厂商 | 别名 | 推荐模型 ID | 优势场景 |
|------|------|------------|---------|
| **PawnLogic Engine** | `hermes` / `hermes405` | `NousResearch/Hermes-4-70B` | 框架原生优化，指令遵循极强 |
| **OpenAI** | `gpt-4o` / `gpt-4o-mini` | `gpt-4o` | 视觉+推理，需代理 |
| **DeepSeek** | `ds-chat` / `ds-r1` | `deepseek-chat` / `deepseek-reasoner` | V3 性价比之王；R1 深度推理首选 |
| **DeepSeek V4** | `ds-v4-pro` / `ds-v4-flash` | `deepseek-v4-pro` | Pwn 漏洞逻辑建模 / 毫秒级响应 |
| **智谱 AI** | `glm-5.1` / `glm-4.7` / `glm-4.5-air` | `glm-5.1` | 国内直连，国产推理旗舰 |
| **智谱 AI (视觉)** | `glm-4v` | `glm-4v-plus` | Web 截图 / 隐写图片分析 |
| **通义千问** | `qwen-max` / `qwen-3.0` | `qwen-3.0-max` | 强大长文本处理与代码纠错 |
| **硅基流动** | `sf-ds-v3` / `sf-qwen72b` | `deepseek-ai/DeepSeek-V3` | 开源模型低成本推理池 |
| **Moonshot** | `kimi` | `moonshot-v1-128k` | 超长上下文日志分析 |
| **Groq** | `groq-llama3` | `llama-3.3-70b-versatile` | **极速**：秒级生成 Exploit 脚本 |
| **本地 Ollama** | `qwen-local` | `qwen2.5-7b-instruct` | 离线靶机环境，零泄密风险 |

> **CTF 场景推荐组合**
> - Pwn 漏洞开发 → `ds-r1` 或 `ds-v4-pro`（深度推理）
> - Web 代码审计 → `ds-chat` 或 `glm-5.1`（高性价比，长上下文）
> - 截图 / 隐写分析 → `glm-4v` 或 `gpt-4o`（多模态视觉）
> - 极速脚本生成 → `groq-llama3`（毫秒级响应）
> - 离线靶机环境 → `qwen-local`（零网络依赖）

---

## 🚀 部署指南

### 系统要求

- **推荐**：WSL2 / Ubuntu（满血体验）
- **可选**：Windows（基础体验，不支持 Pwn 工具链）

### 🐧 WSL2/Ubuntu 部署（推荐）

```bash
# 克隆仓库
git clone https://github.com/your-repo/pawnlogic.git
cd pawnlogic

# 安装依赖
pip install -r requirements.txt

# 配置 API Key（见下方说明）
cp .env.example .env
# 编辑 .env，填入你的 Key

# 启动
python main.py
```

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
# PawnLogic 1.0 — API Key 配置
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

# ── 本地 Ollama（无需 Key，自定义端口时修改 URL）────────
# LOCAL_API_URL=http://localhost:11434/v1/chat/completions
# LOCAL_API_KEY=
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
Local Ollama     LOCAL_API_KEY       ⬜ 无需 Key
```

使用 `/model <别名>` 切换，例如：

```bash
/model ds-r1          # 切换至 DeepSeek R1 深度推理
/model glm-4v         # 切换至智谱视觉模型，可传入截图分析
/model groq-llama3    # 切换至 Groq 极速模式
/model qwen-local     # 切换至本地 Ollama，断网也能用
```

---

## 📖 核心命令手册

启动终端后，你会看到 `You >` 提示符。可以像使用 ChatGPT 一样直接对话，也可以使用 `/` 开头的快捷命令。

### ⚙️ 环境与模型控制

- `/model [alias]` — 切换大模型（如 `/model glm-5.1`）
- `/setkey` — 重新运行 API Key 配置向导
- `/keys` — 显示各 Provider Key 配置状态
- `/clear` — 清空历史对话释放 Token（保留已 Pin 消息和项目 State）
- `/cd <path>` — 切换 Agent 的工作目录
- `/file ./test.py` — 将某个文件一次性载入到对话上下文

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
- `/del <name|n>` — 删除指定会话

### 🔍 会话浏览器 (1.0)

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

### 🧮 三档预设（算力调节）

- `/low` — 日常闲聊/简单问答（tokens=4k, ctx=40k, iter=10）
- `/mid` — 开发编程/脚本编写（tokens=8k, ctx=150k, iter=30）← 默认
- `/deep` — 论文阅读/大型项目重构/复杂漏洞挖掘（tokens=32k, ctx=400k, iter=50）
- `/normal` — 重置到 /mid

### 🔧 细粒度调节

- `/tokens /ctx /iter /toolsize /fetchsize <n>` — 调整具体参数
- `/limits` — 查看所有当前限制

### 🛠️ 工具状态

- `/webstatus` — Jina / Pandoc / Lynx 状态
- `/pwnenv` — CTF 工具链完整性检查

### 📚 全局技能存档 (GSA)

- `/memo [内容]` — 手动存档技能：AI 自动分类并写入 `~/.pawnlogic/global_skills.md`
- `/memo` — 不带参数：对当前对话最后一轮 AI 回复进行存档
- `/skills` — 查看 `global_skills.md` 的分类目录
- `/skills view` — 查看 `global_skills.md` 全部内容（分页）
- `/skills path` — 显示技能文件路径

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

### 场景四：会话管理与项目追踪 (1.0)

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
- `config.py` — API、预设参数、黑白名单配置
- `core/session.py` — 核心调度环（Agentic Loop）、流式解析
- `core/memory.py` — SQLite 数据库管理与 RAG 检索
- `core/persistence.py` — 会话持久化管理
- `core/gsa.py` — 全局技能存档管理
- `tools/` — 工具库（文件、网页、沙箱、Pwn 链）

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

### v1.0（当前版本）

- ✅ **新增 `/chat` 会话管理命令系列**：浏览、搜索、标签、关联历史对话
- ✅ **增强 SQLite 数据库**：新增会话标签、关联、全文搜索功能
- ✅ **2026 全生态模型接入**：DeepSeek V4、GLM-5.1、Qwen 3.0、Groq、Moonshot 等
- ✅ **优化配置向导**：支持 11 大厂商 API Key 配置
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

---

## 📞 支持与贡献

- **GitHub**: [PawnLogic 项目仓库](https://github.com/john0123412/PawnLogic)
- **文档**: 查看本 README 和代码内注释
- **问题反馈**: 请通过 GitHub Issues 提交

---

**祝您使用愉快！** 🚀
