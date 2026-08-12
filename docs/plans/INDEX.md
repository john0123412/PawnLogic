# PawnLogic Release Plans

> **For agentic workers:** Each plan file is the authoritative source for its
> release scope. Read the active plan before broad code changes or release work.

## Active Plan

| Version | Plan | Status |
|---------|------|--------|
| 0.3.1 | [0.3.1-runtime-hardening-and-release-preparation.md](0.3.1-runtime-hardening-and-release-preparation.md) | Active; the version remains an unreleased candidate. Scope is bounded stream and file recovery, execution-boundary hardening, and release readiness only; do not tag or publish without explicit authorization. |

There is exactly one active plan at a time. When the active plan is completed
and its release is published, it moves to Completed below.

## Proposed Plans

There are no proposed plans.

## Completed Plans

| Version | Plan | Release |
|---------|------|---------|
| 0.3.0 | [0.3.0-extensible-agent-platform-and-security-distribution.md](0.3.0-extensible-agent-platform-and-security-distribution.md) | v0.3.0 |
| 0.2.3 | [0.2.3-autonomous-runtime-reliability-deepening.md](0.2.3-autonomous-runtime-reliability-deepening.md) | v0.2.3 |
| 0.2.2 | [0.2.2-runtime-evaluation-architecture-slimming.md](0.2.2-runtime-evaluation-architecture-slimming.md) | v0.2.2 |
| 0.2.1 | [0.2.1-post-release-stabilization.md](0.2.1-post-release-stabilization.md) | v0.2.1 |
| 0.2.0 | [0.2.0-consolidation-release.md](0.2.0-consolidation-release.md) | v0.2.0 |
| 0.1.7 | [0.1.7-maintenance-hardening.md](0.1.7-maintenance-hardening.md) | v0.1.7 |
| 0.1.6 | [0.1.6-maintenance-hardening.md](0.1.6-maintenance-hardening.md) | v0.1.6 |

## Archived Plans

Older plans live under [archive/](archive/).

## Rules

- Exactly one plan is active at any time, or explicitly none.
- A plan becomes active when its file is added and the first implementation PR
  is opened.
- A plan is completed when its release tag exists on PyPI and GitHub.
- Do not mark implementation checkboxes complete without recording the commit,
  CI run, or release URL as evidence.
