# Issue Tracker

PawnLogic uses local markdown files under `.scratch/<feature>/` for lightweight
issue tracking during development. This is not a replacement for GitHub Issues;
it is a local workspace for agents and maintainers to track work-in-progress
items that have not yet been promoted to a GitHub Issue or PR.

## Structure

```
.scratch/
  <feature-slug>/
    issue-001.md
    issue-002.md
```

Each issue file follows this template:

```markdown
# <Short title>

**Status:** open | in-progress | blocked | closed
**Labels:** <one or more triage labels>
**Assignee:** <agent name or maintainer>

## Description

<What needs to be done and why.>

## Acceptance Criteria

- [ ] Criterion 1
- [ ] Criterion 2

## Notes

<Implementation notes, blockers, related PRs.>
```

## Rules

- `.scratch/` is gitignored. Do not commit local issue files.
- When an issue is ready for a PR, create a GitHub Issue or branch directly.
- Do not use `.scratch/` for tracking release plans; use `docs/plans/` instead.
- Agents should check `.scratch/` at the start of a work session for assigned
  items.

## Triage Labels

See [triage-labels.md](triage-labels.md) for the canonical label vocabulary.
