[English](README.md) | **[中文](README_zh-CN.md)**

# PawnLogic

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/pypi/v/pawnlogic.svg?label=version&cacheSeconds=0)](https://pypi.org/project/pawnlogic/)
[![CI](https://github.com/john0123412/PawnLogic/actions/workflows/main_ci.yml/badge.svg)](https://github.com/john0123412/PawnLogic/actions/workflows/main_ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20WSL2-lightgrey.svg)]()

PawnLogic 是一个 terminal-first 的自主 AI agent：多 provider 模型路由、
持久记忆、真实的本地工具执行、MCP 集成，以及面向 CTF 的工具链。当前公开发布版本是 **0.4.3**。

## 快速开始

环境要求：Linux 或 WSL2、Python 3.10+、`pip`。只有源码安装和 git skill
包才需要 `git`。全局启动器需要 `~/.local/bin` 在 `PATH` 中。

**从 PyPI 安装：**

```bash
pip install pawnlogic
pawn
```

**一键安装脚本**（隔离 venv，并写入 `~/.local/bin/pawn`）：

```bash
curl -fsSL https://raw.githubusercontent.com/john0123412/PawnLogic/main/install.sh | bash
pawn
```

**源码安装**（开发用）：

```bash
git clone https://github.com/john0123412/PawnLogic.git
cd PawnLogic
python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
pawn
```

可选依赖：`pawnlogic[docker]`、`pawnlogic[browser]`、`pawnlogic[ctf]`。
`[ctf]` 只装工具（pwntools、ROPgadget、ropper）；skill 包是独立的，用
`/skills install <repo_url>` 显式安装，装到 `~/.pawnlogic/skills`；
若从自带 `skills/` 目录的源码 checkout 运行，则装到该目录。

首次运行会进入 API key 配置。运行时数据全部在 `~/.pawnlogic/` 下，不会
写进项目目录。

```bash
pawn                                     # 交互式 TUI
pawn --eval "summarize this repository"   # 单次执行，非交互
pawn --eval "..." --json                 # NDJSON 输出
pawn --continue                          # 恢复最近的可恢复会话
pawn resume <session>                    # 加载指定会话，不执行
pawn --debug                             # 完整诊断输出
```

默认输出隐藏工具调用细节。模型推理过程以暗色 `🧠 [thinking]` 流显示，
便于区分"首 token 慢"和"连接已死"。`--debug`（或 `/mode`）显示全部细节。

## 模型与 Provider

内置别名（只有配置了 key 的 provider 才会出现在 `/model` 里）。
每个别名都指向一个真实模型 ID；provider 发布新模型时别名会跟着走，
添加 key 后跑一遍 `/provider fetch <name>` 即可同步最新列表。

| 别名 | 模型 | Provider |
|------|------|----------|
| `ds-v4-flash` | `deepseek-v4-flash` | DeepSeek |
| `ds-v4-pro` | `deepseek-v4-pro` | DeepSeek |
| `gpt-5.5` | `gpt-5.5` | OpenAI |
| `gpt-5.4` | `gpt-5.4` | OpenAI |
| `gpt-5.4-mini` | `gpt-5.4-mini` | OpenAI |
| `gpt-5.4-nano` | `gpt-5.4-nano` | OpenAI |
| `gpt-4o` | `gpt-4o` | OpenAI |
| `gpt-4.1` | `gpt-4.1` | OpenAI |
| `o3` | `o3` | OpenAI |
| `claude-opus` | `claude-opus-4-6` | Anthropic |
| `claude-sonnet` | `claude-sonnet-4-6` | Anthropic |
| `claude-haiku` | `claude-haiku-4-5-20251001` | Anthropic |

```bash
/provider                              # provider TUI
/provider add <name> <base_url> <ENV_KEY> [format] [auth]
/provider fetch <name>                 # 拉取模型列表并选择别名
/provider update <name>                # 重新拉取模型
/provider activate|deactivate <name>    # 显示或隐藏某 provider 的模型
/provider list                         # provider 与 key 状态
/provider test <model>                 # 免费连通性检查，不推理
/setkey                                # 重新跑 key 配置
/keys                                  # key 状态
```

Key 存放在 `~/.pawnlogic/.env`；provider 配置在
`~/.pawnlogic/custom_providers.json`（不含密钥）。配置过程不会改 shell
启动文件。

### 协议与鉴权

| Format | 请求地址 |
|---|---|
| `openai` | `POST {base}/chat/completions` |
| `anthropic` | `POST {base}/messages` |
| `responses` | `POST {base}/responses` |

鉴权与协议是两套独立设置：`auto`、`bearer`、`x_api_key`、`both`。默认
`auto` 沿用各协议的历史鉴权方式，已有 provider 不受影响。401 报错时会
指明实际发送的 credential header——先改 `Auth`，确认不行再换 key。

## 推理强度

一个旋钮同时控制思考强度和运行时上限（输出 token、工具调用轮数、
上下文预算、时间预算）：

| 档位 | 发给 provider 的值 | 工具调用轮数 | 替代旧命令 |
|-------|------------------|----------------------|----------|
| `off` | `none` | 10 | — |
| `low` | `low` | 10 | `/low` |
| `medium` | `medium` | 30 | `/mid`、`/normal` |
| `high` | `high` | 50 | `/deep` |
| `xhigh` | `xhigh` | 100 | `/max` |
| `max` | `max` | 150 | `/ultra` |

默认 `medium`；旧的档位命令仍可作为别名使用。该参数只发给声明支持的
模型。自定义 provider 用 `/provider effort <name> on` 主动加入。

## 命令

```bash
/model <alias> [effort]        # 切换模型，可同时设强度
/effort [level]                # off|low|medium|high|xhigh|max
/mode                          # 切换简洁/调试输出
/chat find <keyword>           # 全会话搜索
/think <prompt>                # 一次更深的推理
/compact                       # 总结并压缩上下文
/undo [n]                      # 回滚最近若干轮
/queue                         # 查看排队/转向中的工作
/abort                         # 中断当前 Turn
/init_project [desc]           # 初始化项目状态
/pwnenv                        # 检查 CTF 工具链完整性
/ctf init <name>               # 新建 CTF 工作区元数据
/ctf solved [flag]             # 标记已确认的 flag
/ctf writeup                   # 导出 CTF writeup 草稿
/skills install <repo_url>     # 安装 git skill 包
/worker [alias|auto]           # 查看或设置首选 worker
/planguard [strict|advisory|status]
/agent policy show             # 委派 agent 策略
```

`/help` 列出全部命令，包括 `/extension` 管理。

## 信任边界

PawnLogic 以你的用户权限执行真实工具。它是 agent 执行工具，不是安全
沙箱。高风险 shell 命令需要显式确认（确认框默认停在**拒绝**）；非交互
运行时直接失败而非放行。明文 `http://` 的 provider 和跨边界工具调用会
打印显式警告。模式过滤和 Docker 隔离能减少误操作，拦不住存心作恶的
攻击者。

0.4.3 已在代码中收紧出站边界：Docker 网络模式只允许 `none`、`bridge`、`host`。
`container:<id>` 这类共享其他容器网络的模式和未知模式会在调用 Docker SDK
之前被拒绝，即使设置了 `allow_network=true`。Bridge 和 host 仍需显式网络授权。
浏览器工具（Patchright 与 Scrapling）的 HTTP/HTTPS 连接强制经过本地回环代理，
只拨打策略检查时固定的 IP。两条 Chromium 路径都禁用 HTTP/2 与 QUIC，显式
让 loopback 经过代理，请求禁用 Service Worker，并限制 WebRTC 的非代理 UDP。
context 级 route guard 对可拦截的请求做二次检查，安装失败会关闭上下文。
已确认的私有目标只在当前操作中使用确认时的 IP，操作结束会关闭既有连接。
明文 HTTP 每个连接只处理一个请求，不支持 chunked 上传、协议升级、`Expect`
和超过 8 MiB 的请求体。HTTPS 内容保持端到端加密；该目标访问边界不是操作系统
沙箱。当前 Patchright 的 Service Worker 注册屏蔽可从原型方法绕过；即使注册成功，
其出站连接仍由代理检查。不支持所需 setup 契约的 Scrapling 版本会在抓取前被拒绝。

授权 CTF 靶场允许使用明文 HTTP。获得明确联网授权后，通过 `run_code_docker`
运行 HTTP 客户端代码，设置 `network="bridge"`、`allow_network=true`；优先使用
本地 `python` 镜像，标准库足够时不挂载宿主文件、不安装依赖。一次性容器仍受
512 MiB 内存、0.5 CPU 和 256 PID 限制；容器内客户端不受浏览器代理的上传和
请求封帧限制。Docker bridge 授权代表允许联网，不是目标地址白名单：请求必须
保持在约定靶场范围内。不要通过 host 网络或关闭浏览器代理绕过限制。
一次性 `run_code_docker` 容器现在移除全部 Linux capabilities，为 `/tmp` 和 `/run`
挂载 tmpfs，并采用只读根文件系统。Python `install_deps` 会使用可写根文件系统；
未指定 `container_user` 时保留镜像默认用户。其他情况默认匹配宿主 UID:GID，
仅在宿主 UID 非零时是非 root；无法获取宿主 ID 的平台使用镜像默认用户。
`container_user="root"` 显式选择 root。持久 `pwn_container` 保留镜像默认配置。
额外工作区挂载仍须满足挂载策略。

Airlock 安装包前也会验证操作者声明的范围，保留既有 bridge 连接，只清理本次建立的临时连接。临时断网失败时，工具会撤销容器访问并终止容器，失败后尝试强制删除；若 Docker 仍无法清理，会明确报告容器可能继续运行、需要人工处理，不会报告安装成功。Airlock 不修改既有 hosts 文件映射，也不执行目标过滤。

可选宿主配置 `PAWNLOGIC_DOCKER_EGRESS_ALLOW` 接受域名、IP 和 CIDR，仅记录声明范围，
并将解析后的域名映射写入容器 hosts 文件。它不进行 socket 过滤、强制 CIDR 限制，
也不阻止范围外的直接 IP 连接、自定义 DNS 查询或 HTTP 重定向。hosts 映射不是传输层
DNS pinning；目标级出站强制控制仍需额外的网络边界。

## 数据目录

```text
~/.pawnlogic/
├── .env                    # API key
├── custom_providers.json   # provider 配置，不含密钥
├── mcp_configs.json        # MCP server 声明
├── pawn.db                 # 会话、消息、知识库
├── skills/                 # 用户安装的 skill 包
├── sessions/               # 会话 scratch 目录
├── workspace/              # 任务工作区
└── logs/                   # 审计日志
```

项目目录不含任何密钥，可以放心分享。

## 常见问题

**加了 provider，`/model` 里看不到新模型？**
先配好 key，再跑 `/provider fetch <name>` 选模型，最后
`/provider activate <name>`。

**API key 存哪？**
`~/.pawnlogic/.env`——在项目之外，git 不跟踪。

**`pawn: command not found`？**
`export PATH="$HOME/.local/bin:$PATH"`。

**怎么加 MCP server？**

```bash
cp ~/.pawnlogic/mcp_configs.example.json ~/.pawnlogic/mcp_configs.json
# 然后编辑 mcp_configs.json
```

**浏览器工具报模块缺失？**
`pip install 'pawnlogic[browser]'`，再跑 `patchright install chromium`。

**本地 Ollama 模型？**
`/provider add`，base URL 填 `http://localhost:11434`，key 留空。

## 文档

| 文档 | 说明 |
|----------|-------------|
| [CHANGELOG.md](CHANGELOG.md) | 版本历史与发布说明 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 贡献、provider 与测试流程 |
| [SECURITY.md](SECURITY.md) | 漏洞报告政策 |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | 第三方归属 |

## 支持

- GitHub：[github.com/john0123412/PawnLogic](https://github.com/john0123412/PawnLogic)
- 报 bug、提需求请走 GitHub Issues。
