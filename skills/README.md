# PawnLogic Skills — 技能包规范

## 目录结构

```
skills/
├── demo_stack_overflow/      # 技能包文件夹
│   ├── manifest.json         # 必须：元数据描述
│   ├── guide.md              # 推荐：使用指南
│   └── exploit.py            # 可选：可执行脚本
├── web_sql_injection/
│   ├── manifest.json
│   ├── guide.md
│   └── payloads.py
└── README.md                 # 本文件
```

## manifest.json Schema

```json
{
  "name": "技能包名称",
  "version": "1.0",
  "description": "一句话描述该技能的用途",
  "keywords": ["关键词1", "关键词2", "关键词3"],
  "triggers": ["触发条件描述1", "触发条件描述2"],
  "guide": "guide.md",
  "scripts": ["exploit.py", "helper.sh"],
  "author": "作者名"
}
```

### 字段说明

| 字段 | 必须 | 说明 |
|------|------|------|
| `name` | ✓ | 技能包显示名称 |
| `version` | | 版本号，默认 "1.0" |
| `description` | | 一句话描述，用于匹配和展示 |
| `keywords` | ✓ | 关键词数组，Agent 按此匹配任务 |
| `triggers` | | 触发条件（中文描述），增强匹配 |
| `guide` | | 指南文件名，Agent 优先读取 |
| `scripts` | | 可执行脚本列表，Agent 优先调用 |
| `author` | | 作者信息 |

## 工作流程

1. 用户提出任务（如 "分析这个栈溢出漏洞"）
2. `SkillScanner` 扫描 `./skills/*/manifest.json`
3. 按 keywords + triggers 匹配，返回 top 3 技能包
4. Agent 读取 `guide.md`，按步骤执行
5. 优先运行包内 `scripts/`，避免即兴编码

## USER 模式

技能包加载后仅显示：`✓ 已加载技能包: [名称]`，不展示内部路径和代码。

## 创建新技能包

```bash
mkdir -p skills/my_skill
cat > skills/my_skill/manifest.json << 'EOF'
{
  "name": "My Skill",
  "version": "1.0",
  "description": "技能描述",
  "keywords": ["keyword1", "keyword2"],
  "triggers": ["触发条件"],
  "guide": "guide.md",
  "scripts": ["run.py"],
  "author": "your_name"
}
EOF
```
