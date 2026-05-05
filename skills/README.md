# PawnLogic Skills — 技能包规范

## 零配置模式（推荐）

最简用法：**新建文件夹，扔一个 `skill.md` 进去，完事。**

```
skills/
├── my_skill/
│   └── skill.md              ← 就这一个文件，系统自动识别
├── demo_stack_overflow/
│   └── guide.md              ← 也行，guide.md 同样有效
└── heap_exploit/
    └── skill.md
```

系统自动从文件夹名和 `.md` 标题提取关键词，无需任何配置。

## 进阶用法（可选）

需要更多控制时，可添加 `manifest.json` 和脚本：

```
skills/
└── my_skill/
    ├── skill.md              ← 主内容（Agent 读取执行）
    ├── manifest.json         ← 可选：补充元数据
    └── exploit.py            ← 可选：Agent 优先调用的脚本
```

### manifest.json Schema

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

| 字段 | 必须 | 说明 |
|------|------|------|
| `name` | | 技能包名称，默认取 .md 一级标题或文件夹名 |
| `description` | | 一句话描述，默认自动提取 .md 首段 |
| `keywords` | | 关键词数组，默认从标题自动提取 |
| `triggers` | | 触发条件（中文描述），增强匹配 |
| `scripts` | | 可执行脚本列表，Agent 优先调用 |

## .md 文件查找优先级

1. `skill.md` — 最高优先级
2. `guide.md` — 次优先级
3. 目录内第一个 `*.md` 文件

## 工作流程

1. 用户提出任务（如 "分析这个堆漏洞"）
2. `SkillScanner` 扫描 `./skills/*/`，自动提取元数据
3. 按关键词匹配，返回 top 3 技能包
4. Agent 读取 `.md` 指南，按步骤执行
5. 若有脚本，优先运行脚本而非即兴编码

## 创建新技能包

```bash
mkdir -p skills/my_skill
cat > skills/my_skill/skill.md << 'EOF'
# My Skill 名称

## 触发条件
当用户要求 XXX 时，按以下步骤执行。

## Step 1
...

## Step 2
...
EOF
```

就这么简单。需要更多控制再加 `manifest.json`。
