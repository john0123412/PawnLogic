# PawnLogic Skills - Skill Pack Specification

## Zero-Config Mode

The simplest skill pack is a directory containing one `skill.md` file.

```text
skills/
|-- my_skill/
|   `-- skill.md              # Automatically detected
|-- demo_stack_overflow/
|   `-- guide.md              # `guide.md` is also valid
`-- heap_exploit/
    `-- skill.md
```

PawnLogic extracts keywords automatically from the directory name and Markdown
heading. No manifest is required for basic usage.

## Advanced Mode

Add `manifest.json` and scripts when a skill needs more control.

```text
skills/
`-- my_skill/
    |-- skill.md              # Primary content read by the agent
    |-- manifest.json         # Optional metadata
    `-- exploit.py            # Optional script preferred by the agent
```

### manifest.json Schema

```json
{
  "name": "Skill pack name",
  "version": "1.0",
  "description": "One-sentence description of what this skill does",
  "keywords": ["keyword1", "keyword2", "keyword3"],
  "triggers": ["When the user asks for X", "When artifact Y is present"],
  "guide": "guide.md",
  "scripts": ["exploit.py", "helper.sh"],
  "author": "Author name"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | | Skill pack name. Defaults to the Markdown H1 or directory name. |
| `description` | | One-sentence description. Defaults to the first Markdown paragraph. |
| `keywords` | | Keyword array. Defaults to values extracted from the title. |
| `triggers` | | Trigger descriptions that improve matching. |
| `scripts` | | Executable scripts the agent should prefer when relevant. |

## Markdown Lookup Priority

1. `skill.md`
2. `guide.md`
3. The first `*.md` file in the directory

## Workflow

1. The user asks for a task.
2. `SkillScanner` scans `./skills/*/` and extracts metadata.
3. Skills are matched by keywords and the top results are returned.
4. The agent reads the Markdown guide and follows its steps.
5. If scripts are available, the agent prefers them over ad hoc code.

## Creating a Skill Pack

```bash
mkdir -p skills/my_skill
cat > skills/my_skill/skill.md << 'EOF'
# My Skill Name

## Triggers
Use this skill when the user asks for XXX.

## Step 1
...

## Step 2
...
EOF
```

Add `manifest.json` only when the default metadata extraction is not enough.
