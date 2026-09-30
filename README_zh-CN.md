[English](README.md) | **[中文](README_zh-CN.md)**

# PawnLogic

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/pypi/v/pawnlogic.svg?label=version&cacheSeconds=0)](https://pypi.org/project/pawnlogic/)
[![PyPI](https://img.shields.io/pypi/v/pawnlogic.svg?cache=no)](https://pypi.org/project/pawnlogic/)
[![CI](https://github.com/john0123412/PawnLogic/actions/workflows/main_ci.yml/badge.svg)](https://github.com/john0123412/PawnLogic/actions/workflows/main_ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20WSL2-lightgrey.svg)]()

PawnLogic 是一个终端优先的自主 AI Agent，支持多 Provider 模型路由、持久化记忆、真实本地工具执行、MCP 集成和面向 CTF 的工具链。当前公开发布版本是 **0.4.0**。

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
pawn --continue                    # 加载最近的可恢复草稿
pawn resume <session>              # 加载指定会话但不自动执行
python -m pawnlogic --help
```

默认 `pawn` 使用用户友好的输出，会隐藏原始工具调用细节、解析器诊断和底层 API 错误。
模型 reasoning 会以暗色 `🧠 [thinking]` 流显示：否则首个 token 来得很慢时，界面和「连接已断」
无法区分。它只是旁路展示，不计入答案。不流式返回 `reasoning_content` 的 Provider 不会显示
reasoning 文本 —— 包括 Anthropic 格式的模型，其 `thinking_delta` 目前尚未被流适配器处理 ——
但底栏状态词照常显示。
工具调用恢复仅为尽力而为，不作保证。若格式错误的工具调用尝试无法解析，则不会产生或执行工具调用；用户友好模式仍会隐藏详细的解析器诊断信息。
需要详细诊断时，使用 `pawn --debug` 或 `/mode`。
使用 `--json` 时，每一行都是独立的 NDJSON record。现有 `text`、`chunk` 和 `json`
record 保持稳定；带版本的 Agent lifecycle record 使用新增的
`{"type":"event","data":{...}}` envelope。

## 新特性

0.4.0 把推理强度统一为一个控制入口：

- **推理强度只有 `/effort` 一个控制入口：** 六档 —— `off`、`low`、`medium`、
  `high`、`xhigh`、`max` —— 默认 `medium`，以弹窗选择器的形式挂在 `/model`
  之后。旧的档位命令（`/low`、`/mid`、`/normal`、`/deep`、`/max`、`/ultra`）
  仍然可用，并会提示设置已迁移到何处。参见
  [ADR 0012](docs/adr/0012-reasoning-effort-control.md)。
- **参数只发给明确声明支持的模型：** 支持情况按档位记录，因此只接受
  `low`/`medium`/`high` 而不接受 `xhigh` 的模型永远收不到 `xhigh`；完全没有
  声明的模型则完全不会收到该参数。这正是默认值对拒绝该参数的
  OpenAI-compatible 中转站保持安全的原因。也可以用
  `/provider effort <name> on|off` 为整个自定义 Provider 的模型统一开启。
- **修改强度不再清除显式设置的 `/worker` 锁定。** 此前每个档位预设都会把
  worker 固定为 `auto`，旧命令会静默解除锁定，而 worker 菜单仍显示旧值。
- **按下 Enter 后 Turn 立刻显示 `Sent`**，不再在整个请求前窗口里停在 `0s`
  —— 那时首字延迟慢和连接已死看起来完全一样。模型推理文本在用户友好模式下
  以暗色 `🧠 [thinking]` 流展示。
- **补全菜单不再覆盖工具栏。** 它现在布局在输出窗口与编辑框之间，模型字段
  和模糊候选不再互相叠画。
- **空闲状态下的 Ctrl+C 可以正常退出。** 此前它会绕过 CLI 的清理流程，非
  daemon 的 Turn 线程继续持有解释器，只有 SIGKILL 才能结束。
- **`/provider effort` 不再会破坏 Provider 配置。** 此前把它指向内置 Provider
  会向 `custom_providers.json` 写入一条不完整的记录，下次启动时整份文件被拒绝
  —— 所有自定义 Provider、模型和激活状态全部丢失。现在内置 Provider 会被
  拒绝并给出说明；该开关只作用于自定义 Provider。

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

## 思考强度

思考强度是一个旋钮，不是两个。同一个档位同时决定模型思考多少、以及它有多少可用空间：
发给 Provider 的 `reasoning_effort`，以及输出 token、工具调用迭代次数、上下文窗口、
工具输出上限和时间预算这一整套运行时限制。`/model` 在你选完模型后会接着询问档位，
两个选择在同一个交互里完成。

| 档位 | 发给 Provider | 工具调用迭代 | 替代 |
|------|---------------|--------------|------|
| `off` | `none` | 10 | — |
| `low` | `low` | 10 | `/low` |
| `medium` | `medium` | 30 | `/mid`、`/normal` |
| `high` | `high` | 50 | `/deep` |
| `xhigh` | `xhigh` | 100 | `/max` |
| `max` | `max` | 150 | `/ultra` |

默认是 `medium`。旧命令仍然可用，并映射到对应档位——既有的肌肉记忆不会出错，
只是会提示设置搬到了哪里。

只有声明支持该参数的模型才会收到这个字段，因此不识别该参数的中转服务绝不会因为
你调整强度而报错。全部 DeepSeek 别名、`gpt-5.x` 系列和 `o3` 都声明了支持。
其他模型上该档位依然会改变本地限制，并且选择器会明确说明——一个被静默忽略的
设置看起来就像功能坏了。自定义 Provider 接受该字段时，可执行
`/provider effort <name> on` 显式启用。

Anthropic 格式的模型暂未接入：Messages API 用 `thinking.budget_tokens` 表达扩展
思考，而不是 `reasoning_effort`，所以这些模型目前只改变本地限制。委派 worker 同样
继承思考强度，因为 worker 按自己的模型别名解析档位；只有 worker 的输出预算会单独
封顶，这样为速度挑选的 worker 不会继承 32k 的上限。

## Provider 管理

```bash
/provider                         # 打开 Provider TUI
/provider add <name> <base_url> <ENV_KEY> [anthropic]
/provider fetch <name>            # 拉取可用模型并选择别名
/provider update <name>           # 重新拉取 Provider 模型
/provider activate <name>         # 显示已选择的 Provider 模型
/provider deactivate <name>       # 隐藏 Provider 模型
/provider effort <name> on|off     # 让自定义 Provider 接收 reasoning_effort
/provider list                    # 显示 Provider 和 Key 状态
/provider test <model>            # 测试某个模型别名的连通性
/setkey                           # 重新运行 Key 配置
/keys                             # 显示已配置 Key 状态
```

API Key 存储在 `~/.pawnlogic/.env`。Provider 配置、模型别名和描述存储在 `~/.pawnlogic/custom_providers.json`，不包含 secret value。Provider 配置流程不会把 Key 写入 shell 启动文件。

交互式 TUI 也支持原地修改 Provider。进入某个 Provider 的详情页并选择 `Edit Provider`，即可修正它的 `Base URL` 和 `Format`；保存会保留 Provider 名称、API Key 以及已加载的模型。这里不提供重命名：重命名必须同时改写每一个模型条目的 provider 字段和 Key 的环境变量，无法原子完成。需要更换 Key 请使用 `Update API Key`，它会要求重新粘贴完整值，且始终不显示已保存的值。

确认弹窗除颜色外还用文字标记当前按钮，`←` `→` `↑` `↓` 和 `Tab` 都可以在按钮之间移动。`Delete Provider` 打开的弹窗默认停在 `Cancel` 上，因此直接按 `Enter` 不会误删。

`Fetch` 和 `Sync` 打开的模型列表每次都从空搜索框开始，上一次列表里输入的查询不会被套用到这一次。用 `↑` `↓` `PageUp` 和 `PageDown` 移动；`Space` 或 `Enter` 勾选光标所在的模型，`a` 全选，`c` 清空选择。按 `s` 保存已勾选的模型并留在列表里，按 `S` 保存并关闭列表——两者都不需要先把光标移到操作行。列表是分页显示的，`Load Selected`、`Load & Close` 和 `Cancel` 三个操作排在最后一个模型之后，按 `L` 可直接跳到它们，不必逐行往下走；这三个操作同样除颜色外还用文字标记当前项。

`Fetch` 和 `Sync` 不会发送任何 chat 请求，因此列出模型不产生费用。它们只读取 Provider 免费返回的 `/v1/models` 列表，并隐藏声明了非文本输出模态的条目；不返回能力元数据的 Provider 会保留全部条目。`/provider test <model>` 同样是免费的：它检查同一份列表，因此可以在不发起任何推理的前提下回答「base URL 通不通、Key 认不认」。不再有任何计费探测所带来的代价是，你的 Key 实际无权使用的模型不再被提前过滤掉，它会在你第一次使用时以普通 API 错误的形式出现。

本地 relay 和实验环境可以使用明文 `http://` Provider endpoint，但用户友好模式会显示 trust-boundary 提示，因为请求和 API Key 没有 TLS 保护。

不稳定的自定义 Provider 可以通过 `~/.pawnlogic/.env` 中的环境变量调优：`PAWNLOGIC_API_RETRY_MAX` 控制包含首次请求在内的总尝试次数，`PAWNLOGIC_API_RETRY_AFTER_MAX` 限制 Provider `Retry-After` 延迟上限，`PAWNLOGIC_API_CONNECT_TIMEOUT`、`PAWNLOGIC_API_READ_TIMEOUT` 和 `PAWNLOGIC_API_NONSTREAM_TIMEOUT` 分别调节连接和响应等待时间。

## 快速命令参考

```bash
/model <alias>                    # 切换模型
/model <alias> <effort>           # 一步切换模型并设置思考强度
/effort                           # 打开思考强度选择器
/effort <level>                   # 直接设置思考强度（off|low|medium|high|xhigh|max）
/limits                           # 查看当前档位以及是否会发送给 Provider
/mode                             # 切换用户友好/debug 输出
/chat find <keyword>              # 搜索所有会话
/think <prompt>                   # 执行一次更深推理
/compact                          # 总结并压缩上下文
/undo [n]                         # 回滚最近轮次
/queue                            # 高级队列检查，不中断当前 Turn
/queue clear                      # 清除排队/恢复消息，但不中断当前 Turn
/queue resume                     # 继续处理可恢复的排队工作
/queue remove <id>                # 按稳定 ID 移除一条排队消息
/queue steer <id>                 # 将 follow-up 转换为 steer
/queue follow-up <id>             # 将 steer 转换为 follow-up
/queue recall <id>                # 预填编辑器但不移除消息
/abort                            # 中断当前 Turn，并清除排队/恢复工作
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
/planguard [strict|advisory|status]  # 无参数打开模式选择器；各思考强度档默认 advisory，strict 需显式启用
/agent policy show                # 查看委派 Agent 策略
/agent run <role> <objective>     # 输出安全的 delegate_task 请求模板
```

在 PawnLogic 内运行 `/help` 可查看完整命令列表。

## Trust Boundary

PawnLogic 是 agent 执行工具，不是安全沙箱。它会在你要求时，用当前用户权限执行真实工具。Pattern filter、Docker 边界和 capability profile 能减少误操作，但不能阻止有意攻击者。

Web fetch 和 browser navigation 会在使用 HTTP(S) target 前通过共享 Network Policy
进行评估。URL 会被规范化；包含 credential 的 URL、cloud metadata/internal target，
保留的 `localhost` 命名空间（包括其子域），以及 loopback、link-local、multicast、
unspecified 或 reserved address 都会被拒绝。Private-network target 需要显式授权；
在非交互请求本应要求确认时，系统会 fail closed。每个 redirect destination
在跟随前都会重新规范化、解析并评估，包括重新检查 target-scoped authorization。
模型生成的 Tool 参数不能授予 private-network 权限；已确认的 private target
不会发送给远程 reader service。

Docker `bridge`/`host` 网络和 legacy `uvx mcp-server-fetch` 启动在授权 gate
处没有具体 URL，因此使用 capability-only authorization。Docker 网络需要
`allow_network=true` 或 `PAWNLOGIC_DOCKER_ALLOW_NETWORK=true`；legacy MCP
网络安装需要 `allow_network_install=true` 或
`PAWNLOGIC_MCP_ALLOW_NETWORK_INSTALL=true`。这些授权只授予对应 capability，
不代表 URL target 已获授权。

用户友好模式会针对 host shell 执行、Docker container exec、browser/network-capable 工具、private network URL 访问、delegated sub-agent 和 plaintext HTTP Provider 显示明确的 trust-boundary notice。需要更底层的工具参数和诊断信息时，使用 `pawn --debug`。Docker 文件挂载默认限制在 workspace 内，包括 read-only 挂载；挂载外部只读 challenge 文件需要显式设置 `allow_host_read_mount`。

Host shell 执行现在会在启动子进程前经过 operation policy。低风险命令正常执行，中等风险命令会被分类并写入审计，高风险命令需要明确的交互确认，critical 操作默认拒绝。确认弹窗打开时默认选中**拒绝**：按 `y` 批准，按 `n`/`Esc`/`Ctrl+C` 拒绝，直接回车也视为拒绝。批准永远不会由本想输入到编辑框的按键误触发；弹窗挂载期间状态行显示 `⚠ awaiting confirmation — Esc to review`。非交互执行，包括 `pawn --eval`，在高风险命令需要确认时会 fail closed。`DANGEROUS_PATTERNS` 只是误操作/风险分类的一部分，不是 sandbox 边界，也不能阻止恶意本地用户。

Host shell 执行是硬性限时的：超时后会先向整个进程组发送 SIGTERM，再发送 SIGKILL；即使子进程进入不可中断状态（例如 WSL2 内核卡死），清理流程也永远不会无限等待。注册工具还受看门狗约束（`tool_watchdog_sec`，默认 600 秒）：超过上限的工具调用会被放弃并返回 ERROR 结果，会话将继续运行而不是永久卡住。被放弃的后台线程可能持续运行到进程退出为止。高风险确认的等待时长为 `confirmation_wait_sec`（默认 300 秒，并被限制在 `tool_watchdog_sec` 之下）；该超时由挂载弹窗的终端事件循环持有，看门狗超时时还会回收被放弃线程遗留的确认，因此一次超时的确认不会把弹窗留在屏幕上。

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
├── sessions/               # 每会话临时目录（session_<id>/）
├── workspace/              # 自动命名的任务目录及 by-name/ 别名
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

**Q: 如何设置模型的思考强度？**
A: 运行 `/model`，在选完模型后接着选择档位；也可以单独使用 `/effort`。不带参数的 `/effort` 会打开选择器，`/effort high` 直接设置，`/model <alias> <effort>` 则一步完成。该档位同时决定发给 Provider 的 `reasoning_effort` 和一整套运行时限制。只有声明支持的模型才会收到这个字段——全部 DeepSeek 别名、`gpt-5.x` 系列和 `o3` 都声明了；未声明的模型上该档位仍会改变本地限制，并且选择器和 `/limits` 都会说明仅本地生效，不会显得像是功能坏了。自定义 Provider 可执行 `/provider effort <name> on` 显式启用。旧的 `/deep`、`/max`、`/ultra` 仍然可用，分别映射到 `high`、`xhigh`、`max`。

**Q: 可以缩写斜杠命令吗？**
A: 可以。输入唯一前缀或子序列，例如 `/plg`；按 Tab 会列出 `/planguard`，直接按 Enter 也会规范化该命令。只有唯一匹配才会被执行；如果存在歧义，Pawn 会列出候选项且不执行任何命令。所有已注册的内置命令都会参与 Prompt Toolkit 和 readline 补全。

**Q: 如何选择 plan-guard 模式？**
A: 在交互式终端运行 `/planguard`（或 `/plg`），用 Up/Down 或 1/2 选择后按 Enter。脚本或非交互环境请使用 `/planguard advisory`、`/planguard strict` 或 `/planguard status`。默认是 advisory；在 strict 模式下，前两批缺少 plan block 的工具调用仍会执行并收到纠正提示，第三次此类尝试会在执行工具前被停止。

**Q: live composer 在 Turn 运行期间如何处理输入？**
A: 在 Prompt Toolkit 模式下，一个持久终端界面会把模型和工具输出放在底部输入编辑区和状态栏上方。状态栏直接回答「到底有没有在干活」：按下 Enter 立刻显示 `Sent · ⏱ 0s`，首个 token 到达后切到 `Thinking`，开始执行工具时显示 `⏱ 12s · list_dir [2/30]`；三者都以 `Esc to interrupt` 结尾。状态段优先占用宽度，终端变窄时它仍然可读，而不会第一个被裁掉。完整输出行会通过 Prompt Toolkit 的安全终端交接写入宿主终端，因此 Application 运行期间仍可使用原生 scrollback、鼠标选择和复制。连续提交的内容会以淡色队列行显示在输入区正上方。命令和模型补全列表单独占用输入区正上方的若干行，不会遮挡底栏或模型字段。Enter 会提交 steer，并在下一个 Tool safe point 生效；如果纯文本响应先自然结束，尚未应用的 steer 会作为相互独立的后续 Turn 依次执行。Alt+Enter 会排队一条在自然完成后执行的 follow-up。Esc 会中断当前 Turn；如果已有排队工作，会立即把控制权交给该工作，如果队列为空，则把被中断的 prompt 变成可编辑的 recovered draft。在 idle 且输入框为空时，Esc、Up 或 Alt+Up 会把排队/恢复工作合并进可编辑草稿。`/queue` 仍是高级诊断与管理命令，且不会暂停当前 Turn。readline 模式明确保持串行，并在 Turn 完成前缓存输入。

**Q: 中断正在运行的 turn 后会怎样？**
A: Pawn 会等待协作式取消完成。如果已有排队工作，Esc 会把它作为新的 steer 继续执行，不会额外创建重复的 recovered 行。如果队列为空，被中断的 prompt 会预填为可编辑的 recovered draft，但不会自动重跑；按 Enter 只重试一次，编辑后按 Enter 只执行替换后的内容一次（包括以 `/` 开头的编辑）。`/queue remove <id>`、`/queue clear`、`/queue steer <id>`、`/queue follow-up <id>` 和 `/queue recall <id>` 仍可用于高级队列管理。`/abort` 会中断当前 Turn 并清除全部排队/恢复工作，不再有单独的 `--all` 形式。重启后，`pawn --continue` 会加载最近的 interrupted、running 或 failed 会话，`pawn resume <session>` 会加载指定会话。两个命令都会显示历史并预填草稿，但不会自动执行。

**Q: Test Connection 失败但 fetch 成功？**
A: 现在两者读的是同一份免费的 `/v1/models` 列表。Fetch 会翻完所有分页，可能因为某一页出错或列表格式异常而失败；Test Connection 只发一次请求。两者结果不一致通常意味着遇到了可重试的错误——再执行一次即可。

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
