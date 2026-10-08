# PawnLogic Release Plans

> **For agentic workers:** Each plan file is the authoritative source for its
> release scope. Read the active plan before broad code changes or release work.

## Active Plan

[Container boundary follow-ups](container-boundary-followups.md): final-code
evidence, Airlock deadlines, offline lifecycle, legacy-container preflight,
separately authorized TCP/UDP filtering and owner terminal acceptance.
Sections 1–4 are implemented on main (including post-merge independent
review fixes); section 5 is prepared as an uninstalled review package;
owner terminal acceptance and second-stage operational host activation remain
open. The scoped HTTP IQuest workflow passed on `bf6e9cb`, produced no tool
calls on `44114c1`, and passed again on the merged head `35aa6c5` (one
actual tool call, canary ignored); deterministic transport checks passed on
all three. The implemented changes are included in 0.4.4;
the remaining host and visual acceptance work keeps this plan active.
Stage-one implementation/verification is authorized, but administrator
credentials and conntrack prerequisites block real kernel acceptance. See the
[stage-one runbook](../runbooks/host-egress-stage-one.md); its read-only
preflight never turns `not_run` matrix entries into passes.
The 0.4.4 candidate attempt failed model execution and remains recorded.
A later explicitly requested, bounded finalization attempt on `452ce5e` passed:
one real tool call, one offline non-root container, no nudges/API error,
proof independently verified and no out-of-scope canary requests; all nine
deterministic checks passed. Argument evidence is now retained without
weakening the harness policy. The earlier failure cause remains unproven.
The published 0.4.4 binary passed its checksum-verified automated probe (2/2,
zero skips); four visual checks remain manual. Post-release review-artifact
fixes bind nftables packet rules to the bridge and scope all outbound-flow
revocation to an explicitly approved original conntrack zone/source binding.
They neither install a privileged executor nor complete the kernel matrix.

## Proposed Plans

None.

## Completed Plans

| Version | Plan | Release |
|---------|------|---------| 
| 0.4.0 | [reasoning-effort-unification.md](reasoning-effort-unification.md) | [v0.4.0](https://github.com/john0123412/PawnLogic/releases/tag/v0.4.0) |
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
