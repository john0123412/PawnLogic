# PawnLogic Release Plans

> **For agentic workers:** Each plan file is the authoritative source for its
> release scope. Read the active plan before broad code changes or release work.

## Active Plan

- [reasoning-effort-unification.md](reasoning-effort-unification.md) — one
  reasoning-effort level selected inside `/model`, driving both the provider
  wire value and the runtime limits, replacing the six tier commands. See
  [ADR 0012](../adr/0012-reasoning-effort-control.md). Merged by PR #165 and
  shipping in the `0.4.0` release candidate; it moves to Completed Plans once
  the `v0.4.0` tag exists, per the rule below.

## Completed Plans

| Version | Plan | Release |
|---------|------|---------| 
| 0.3.12 | [0.3.12-confirmation-modal-lifecycle.md](0.3.12-confirmation-modal-lifecycle.md) | [v0.3.12](https://github.com/john0123412/PawnLogic/releases/tag/v0.3.12) |
| 0.3.11 | released from `CHANGELOG.md` `[0.3.11]` (no plan file) | [v0.3.11](https://github.com/john0123412/PawnLogic/releases/tag/v0.3.11) |
| 0.3.10 | [0.3.10-terminal-and-release-hardening.md](0.3.10-terminal-and-release-hardening.md) | [v0.3.10](https://github.com/john0123412/PawnLogic/releases/tag/v0.3.10) |
| 0.3.9 | [p2-steer-and-headless-frontends.md](p2-steer-and-headless-frontends.md) | [v0.3.9](https://github.com/john0123412/PawnLogic/releases/tag/v0.3.9) |
| 0.3.8 | [p2-steer-and-headless-frontends.md](p2-steer-and-headless-frontends.md) | [v0.3.8](https://github.com/john0123412/PawnLogic/releases/tag/v0.3.8) |
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
