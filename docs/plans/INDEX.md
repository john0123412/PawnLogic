# PawnLogic Release Plans

> **For agentic workers:** Each plan file is the authoritative source for its
> release scope. Read the active plan before broad code changes or release work.

## Active Plan

[0.3.7-inline-terminal-stability.md](0.3.7-inline-terminal-stability.md) is
active. It restores native terminal scrollback / mouse selection / copy in the
live terminal by removing the alternate-screen application mode, and unifies
`/model`, `/planguard`, and other interactive selectors into a single
Prompt Toolkit Application dialog state. See
[ADR 0010](../adr/0010-inline-terminal-modal.md) for the architectural
constraints. The cycle is declared as a 0.3.7 patch release per the AGENT.md
Version Numbering Policy; the version PR stays unmerged until the previous
release has completed.

There is exactly one active plan at a time. When the active plan is completed
and its release is published, it moves to Completed below.

## Completed Plans

| Version | Plan | Release |
|---------|------|---------| 
| 0.3.6 | [0.3.6-live-turn-control.md](0.3.6-live-turn-control.md) | [v0.3.6](https://github.com/john0123412/PawnLogic/releases/tag/v0.3.6) |
| 0.3.5 | [0.3.5-command-recovery-hardening.md](0.3.5-command-recovery-hardening.md) | [v0.3.5](https://github.com/john0123412/PawnLogic/releases/tag/v0.3.5) |
| 0.3.2 | [0.3.2-bounded-concurrency-two.md](0.3.2-bounded-concurrency-two.md) | [v0.3.2](https://github.com/john0123412/PawnLogic/releases/tag/v0.3.2) |
| 0.3.1 | [0.3.1-runtime-hardening-and-release-preparation.md](0.3.1-runtime-hardening-and-release-preparation.md) | v0.3.1 |
| 0.3.0 | [0.3.0-extensible-agent-platform-and-security-distribution.md](0.3.0-extensible-agent-platform-and-security-distribution.md) | v0.3.0 |
| 0.2.3 | [archive/0.2.3-autonomous-runtime-reliability-deepening.md](archive/0.2.3-autonomous-runtime-reliability-deepening.md) | v0.2.3 |
| 0.2.2 | [archive/0.2.2-runtime-evaluation-architecture-slimming.md](archive/0.2.2-runtime-evaluation-architecture-slimming.md) | v0.2.2 |
| 0.2.1 | [archive/0.2.1-post-release-stabilization.md](archive/0.2.1-post-release-stabilization.md) | v0.2.1 |
| 0.2.0 | [archive/0.2.0-consolidation-release.md](archive/0.2.0-consolidation-release.md) | v0.2.0 |
| 0.1.7 | [archive/0.1.7-maintenance-hardening.md](archive/0.1.7-maintenance-hardening.md) | v0.1.7 |
| 0.1.6 | [archive/0.1.6-maintenance-hardening.md](archive/0.1.6-maintenance-hardening.md) | v0.1.6 |

## Archived Plans

Older completed plans live under [archive/](archive/).

## Rules

- Exactly one plan is active at any time, or explicitly none.
- A plan becomes active when its file is added and the first implementation PR
  is opened.
- A plan is completed when its release tag exists on PyPI and GitHub.
- Do not mark implementation checkboxes complete without recording the commit,
  CI run, or release URL as evidence.
