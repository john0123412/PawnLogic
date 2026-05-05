# PawnLogic 开发准则 (P6 专用)

## 1. 输出哲学
- **User Mode**: 极致简洁。禁止打印原始 JSON、Traceback 或底层日志。错误应转化为"❌ 系统忙，请稍后重试"。
- **Developer Mode**: 极致透明。显示所有 Tool Call 详情、异步线程状态和 Scrapling 原始响应。

## 2. 技能系统 (Skills)
- 核心代码 (`core/`) 保持稳定。
- 所有特定领域的 Payload 模板、复杂的正则表达式或特定网站的绕过逻辑，必须存放在 `./skills/` 文件夹下。
- Agent 必须具备"查阅技能书"的意识：在执行复杂任务前，先调用 `list_dir("./skills")`。

### 技能包规范 (Skill Pack Spec)
- 技能以**文件夹**形式存在于 `./skills/`，每个文件夹为一个独立技能包。
- **零配置模式**：文件夹里放一个 `skill.md`（或 `guide.md`）即可，系统自动从文件名和标题提取关键词。
- `manifest.json` **可选**，用于补充 keywords/triggers/scripts 等元数据。
- **优先加载技能包内的脚本执行任务**，而非让 Agent 即兴编写代码。
- `manifest.json` schema（可选）:
  ```json
  {
    "name": "技能包名称",
    "version": "1.0",
    "description": "一句话描述",
    "keywords": ["关键词1", "关键词2"],
    "triggers": ["触发条件描述1", "触发条件描述2"],
    "guide": "guide.md",
    "scripts": ["exploit.py"],
    "author": "作者名"
  }
  ```
- User 模式下，仅告知用户"已加载 [技能名] 插件"，不展示包内具体路径和代码。

## 3. 安全与编码
- 严格遵守 P4 读写隔离：任何工具产生的文件必须存入 `~/.pawnlogic/workspace`。
- 强制使用 `errors='ignore'` 处理所有外部 IO 数据流。
