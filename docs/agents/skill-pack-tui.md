# Skill Pack TUI — Agent Quick Reference

## Status

Branch `feat/skill-pack-management` (PR #97) delivers unified skill pack management.

## What Changed

- `/skills` launches interactive TUI (replaces old `/sp` and `/skillpack`)
- Enable/disable persists to `~/.pawnlogic/skills_enabled.json`
- 41 packs from `zhaoxuya520/reverse-skill` (MIT) added to `skills/`
- New packs default to disabled

## TUI Controls

↑↓ move, Space/Enter toggle, Tab switch list↔buttons, ←→ navigate buttons, / search, Esc quit

Buttons: Save, All, Clear, Invert, Sync, Rescan, Cancel

Text commands: `/skills install <url>`, `/skills view`, `/skills path`

## Key Files

| File | Role |
|---|---|
| `core/skill_tui.py` | TUI class, async run with run_async() |
| `core/skill_manager.py` | SkillScanner with enable/disable, folder-key resolution |
| `core/commands/tools.py` | `/skills` registration (single entry point) |
| `config/paths.py` | `SKILLS_ENABLED_PATH` |
| `tests/test_commands_dispatch.py` | Verb count 56 (removed /sp /skillpack) |
| `tests/test_repository_language_policy.py` | Excludes skills/ from Chinese text check |

## Constraints

- TUI `_PAGE=12` to fit 24-line terminals
- Skills excluded from ruff (`pyproject.toml` exclude) and `.gitattributes export-ignore`
- `THIRD_PARTY_NOTICES.md` records reverse-skill attribution
