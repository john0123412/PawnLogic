# PawnLogic Skills Engine

This directory holds domain-specific skill files that the agent can retrieve at runtime.

## File Format

Each `.md` file is a skill module. The agent scans filenames and reads matching files when a task aligns with the skill domain.

## Naming Convention

- Use lowercase with underscores: `pwn_stack_overflow.md`, `web_sql_injection.md`
- The filename (minus `.md`) becomes the skill keyword

## Structure

```markdown
# Skill Name

## Trigger
When to activate this skill (keywords / task patterns)

## Steps
1. Step one
2. Step two

## Payload Template
```python
# reusable code snippet
```

## Gotcha
Critical pitfalls to avoid
```

## How It Works

1. Agent receives user task
2. System prompt scans `./skills/` for relevant `.md` files
3. Matching skills are injected into the context
4. Agent follows skill instructions to solve the task
