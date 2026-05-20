# 贡献指南

## 开发环境

```bash
git clone https://github.com/john0123412/PawnLogic.git && cd PawnLogic
python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
```

## 如何新增一个 API Provider

1. 打开 `config/providers.py`，在 `PROVIDERS` 中添加一条
2. 在 `MODELS` 中添加对应的模型别名
3. 在 `.env.example` 的"可选"区域添加 `XXX_API_KEY=` 占位
4. 提 PR，标题格式：`feat(providers): add XXX`

## 如何新增一个 MCP 工具

1. 在 `mcp_configs.example.json` 的 `mcpServers` 中添加服务声明
2. 如需密钥，在 `.env.example` 的"MCP 工具密钥"区域添加占位
3. 提 PR，标题格式：`feat(mcp): add XXX tool`

## 核心模块边界

- `core/session.py`：Agentic Loop 核心，改动需非常谨慎，须附测试
- `tools/`：工具实现，新增工具不修改现有文件
- `config/`：配置声明，不包含业务逻辑

## 提交规范

使用 Conventional Commits：`feat` / `fix` / `refactor` / `docs` / `chore`
