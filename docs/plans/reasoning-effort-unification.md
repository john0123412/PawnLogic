# Reasoning-Effort Unification

> **Status:** Implemented and released in `0.4.0` (PR #165, then the
> `test/release-0.4.0` candidate and `test/release-0.4.0-finalize`
> finalization PRs). The tag is not pushed yet, so `0.4.0` is staged
> rather than published.
> Design rationale: [ADR 0012](../adr/0012-reasoning-effort-control.md).
>
> **Owner decision on the version bump (required by the AGENT.md
> Version Numbering Policy):** the owner chose **0.4.0**, a minor bump,
> when approving the release preparation on 2026-09-30, together with the
> boundary that the work stops at the release-ready state — both release
> PRs merged and green, with no tag and no PyPI publish. The bump is
> therefore authorized in writing; the plan stayed in Active Plans because
> `docs/plans/INDEX.md` treats a plan as complete only once its release
> tag exists.

## Goal

Replace the six tier commands with a single reasoning-effort control,
chosen inside `/model`, following how mainstream agents expose it.

Before this change `/low`, `/mid`, `/deep`, `/max`, `/ultra`, and
`/normal` set eleven local runtime limits and nothing else: the product
never sent a `reasoning_effort` field to any provider. The user should
learn one axis that controls both how hard the model thinks and how much
room it gets.

## Three owner decisions

1. **Merge into one knob.** Each level drives the wire value *and* the
   full set of runtime limits.
2. **Declare per-model capability.** An undeclared model never receives
   the field, so there is no 400 risk; the level still moves local
   limits and is never a no-op.
3. **Keep the old commands as aliases** that map to levels, with a
   one-time migration note pointing at `/model` and `/effort`.

## The ladder

| Level | Wire value | Limits | `max_iter` | Replaces |
|-------|-----------|--------|-----------|----------|
| `off` | `none` | `TIER_LOW` | 10 | — |
| `low` | `low` | `TIER_LOW` | 10 | `/low` |
| `medium` | `medium` | `TIER_MID` | 30 | `/mid`, `/normal` |
| `high` | `high` | `TIER_DEEP` | 50 | `/deep` |
| `xhigh` | `xhigh` | `TIER_MAX` | 100 | `/max` |
| `max` | `max` | `TIER_ULTRA` | 150 | `/ultra` |

`high` is the owner-confirmed preview value: `iter=50`, `ctx=400k`,
`tokens=32k`, `tool_out=20k`, `time_budget=1800s` — TIER_DEEP item by
item. `max` maps to TIER_ULTRA so the 150-iteration ceiling survives
the collapse from seven tiers to six levels.

## Files

| File | Change |
|------|--------|
| `config/tiers.py` | `EFFORT_LEVELS`, `EFFORT_PRESETS`, `EFFORT_WIRE_VALUES`, `is_effort_level`, `effort_preset`, `effort_options`, `effort_delivery`, `infer_effort_level`. References `TIER_*`; does not move them. |
| `config/__init__.py` | Seeds `DYNAMIC_CONFIG` / `NORMAL_CONFIG` from `effort_preset("medium")`. |
| `config/providers.py` | Per-rung `effort` maps on DeepSeek and OpenAI reasoning aliases; `set_provider_reasoning_effort` / `provider_supports_reasoning_effort`. |
| `core/api_payloads.py` | `model_effort_map`, `resolve_reasoning_effort`, and the single `payload["reasoning_effort"]` write. |
| `core/commands/system.py` | `apply_effort` (the one write path), `/effort`, six thin aliases, `/limits` footer. |
| `core/commands/provider.py` | `/model` chains the picker; `/model <alias> <effort>`; `/provider effort <name> on\|off`. |
| `pawnlogic/selectors.py` | `EffortSelector`. |
| `pawnlogic/live_repl.py` | Toolbar reads `effort_level`, falling back to reverse inference. |
| `core/prompt_builder.py` | `Limits :` line leads with `effort=<level>`. |
| `core/delegation_runtime.py` | `SubAgentSession.MAX_TOKENS` clamp. |
| `core/persistence.py` | Backfills `effort_level` for pre-ladder snapshots. |
| `core/session.py` | Error text points at `/effort`, not `/max, /ultra`. |
| `pawnlogic/cli.py` | Help text, command descriptions, startup banner, `/ultra` line. |
| `frontends/ratatui/src/main.rs` | wire v1 intercepts a bare `/effort`. |

## Defects found and fixed while implementing

These were not in the original scope; each was found by a test written
for this change and each is now pinned.

1. **`/model <alias> <effort>` was unreachable through the CLI.**
   `handle_slash` splits the line as `split(None, 2)`, so the command
   received `arg="<alias>"` and `arg2="<effort>"`, while `cmd_model`
   only ever split `ctx.arg`. The unit test passed the whole remainder
   as `arg`, so it exercised a path the product never takes. Now both
   forms are accepted, and the test builds the context the way the CLI
   does.
2. **The scripted form re-opened the effort picker.** `apply_effort`
   now runs first and `_apply_model` takes `offer_effort=False`, so a
   caller who typed the level does not get a modal they did not ask for.
3. **A bad level half-applied the model switch.** Validation now runs
   before the switch and reports the level list.
4. **`infer_effort_level({})` returned `"low"`.** With no limits to read,
   `0 <= TIER_LOW` matched and an empty or truncated snapshot restored
   *below* the default. Guarded.
5. **Tier changes silently cleared `/worker`.** Pre-existing: every
   preset pins `preferred_worker` to `"auto"`, so `/deep` undid an
   explicit lock while the worker menu — which reads the on-disk policy
   first — still showed the old value. `apply_effort` carries it across.
6. **A delegated worker would have inherited 32k of output budget**
   from the `high` rung, contradicting the reason a fast worker was
   chosen. Clamped by `SubAgentSession.MAX_TOKENS`.

## CI-only failure: the architecture budget gate

The first push failed on `test/reasoning-effort-unification` in a step
AGENT.md's Required Verification section does not list:
`tools/check_architecture_budget.py`, which CI runs as part of "Lint".
`core/commands/provider.py` had reached 929/850 lines and 152/130
complexity.

The file sat at *exactly* its budget before this feature, so the gate was
reporting a real boundary rather than an arbitrary one. The ceiling was
left alone and two cohesive seams were extracted instead:

- `core/commands/_effort_flow.py` — the effort half of `/model`: the
  chained picker, the "level is not sent" report, scripted level
  validation, and `/provider effort`.
- `core/commands/_model_picker.py` — the standalone Prompt Toolkit
  `Application` used when no terminal controller owns the PTY.

Result: 788/850 lines, 127/130 complexity.

**Why the budget gate is not in AGENT.md's verification list.** It is a
separate CI step from `ruff check .`, so a clean local lint run says
nothing about it. Run `python tools/check_architecture_budget.py` before
pushing any change that grows a budgeted file; `core/commands/provider.py`,
`core/session.py`, `core/provider_tui.py`, and `pawnlogic/cli.py` are the
ones most likely to trip it.

The move also exposed a coverage gap, now fixed: the only test of the
standalone picker asserted it is *not* called when a controller is
present, so it stayed green if the call site stopped resolving at all.
`test_model_dispatch_reaches_standalone_picker_when_no_controller` drives
the no-controller path and is the only test that goes red when the call
is removed.

## Verification

- [x] Fast suite green: `1721 passed` (`not slow and not e2e and not packaging`).
- [x] Full e2e green: `31 passed`.
- [x] `ruff check .` clean.
- [x] `cargo test` green: 28 passed, including the wire-v1 `/effort` interception.
- [x] `tools/check_doc_structure.py` passes; both READMEs updated together.
- [x] Every new invariant mutation-tested: reverting the
      `preferred_worker` carry, the sub-agent clamp, the
      `reasoning_content` read-back, the capability gate, the
      empty-snapshot guard, the `arg2` handling, the picker suppression,
      and the level validation each turns a test red.
- [ ] Owner PTY acceptance: `/model` chains into the effort screen;
      `/effort` opens the selector; `/deep` reports the merge; `/limits`
      shows the level and whether it is sent; a `/worker` lock survives
      an effort change. Left unchecked deliberately: these are visual and
      interactive judgements on a real terminal, which synthetic input
      cannot attest. Do not tick this from a green test run.

## Not in this change

- **Anthropic-format models** take local limits only. The Messages API
  uses `thinking.budget_tokens`, and `core/provider_streams.py` has no
  `thinking_delta` branch, so the value could not be displayed.
- **The version bump was decided later.** The original change was
  committed without a release, so `config/paths.py:VERSION`, the README
  badges, `SECURITY.md`, and `CHANGELOG.md` were untouched at that point.
  The owner subsequently chose 0.4.0 for the release that carries this
  work; see the status block at the top of this file.
- **The four owner-terminal acceptance checks** carried since 0.3.12
  remain unverified.
