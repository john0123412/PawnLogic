# ADR 0012 — Reasoning Effort as a Single Knob

> **Status:** Accepted.
> The implementation merges the six legacy tier commands into one
> effort ladder that drives both the provider wire value and the
> runtime limits, and selects the level inside `/model`.
> See `docs/plans/reasoning-effort-unification.md` for the plan and
> `AGENT.md` Known Risks for the invariants this binds going forward.

## Context

PawnLogic had six commands — `/low`, `/mid`, `/deep`, `/max`,
`/ultra`, `/normal` — controlling eleven local runtime limits:
`max_tokens`, `max_iter`, `ctx_max_chars`, `ctx_trim_to`,
`tool_max_chars`, `fetch_max_chars`, and friends. None of them had
anything to do with how hard a model thinks; they were named after
the limits they set.

Meanwhile the product never sent a `reasoning_effort` field to any
provider. `_build_openai_payload` constructed `model`, `messages`,
`max_tokens`, `stream`, `tools`, `tool_choice`, `response_format`,
and `stream_options`, and nothing else. So "think harder" was not a
capability PawnLogic had, only a way to make the local numbers larger.

Mainstream agents expose this as a small set of named levels chosen
at model-selection time (OpenAI's `reasoning_effort`, Claude Code's
`/effort`, DeepSeek's `thinking` plus `reasoning_effort`). Three
questions had to be answered.

## Decision

### One level, two effects

A level selects both the wire value and a complete set of runtime
limits, so the user learns one axis. The six rungs are `off`, `low`,
`medium`, `high`, `xhigh`, `max`, defaulting to `medium`.

| Level | Wire value | Limits | `max_iter` | Legacy command |
|-------|-----------|--------|-----------|----------------|
| `off` | `none` | `TIER_LOW` | 10 | — |
| `low` | `low` | `TIER_LOW` | 10 | `/low` |
| `medium` | `medium` | `TIER_MID` | 30 | `/mid`, `/normal` |
| `high` | `high` | `TIER_DEEP` | 50 | `/deep` |
| `xhigh` | `xhigh` | `TIER_MAX` | 100 | `/max` |
| `max` | `max` | `TIER_ULTRA` | 150 | `/ultra` |

`max` maps to `TIER_ULTRA` rather than `TIER_MAX` because the
150-iteration ceiling `/ultra` provided has no separate rung any more,
and folding it into the top rung preserves the capability instead of
silently dropping it.

`TIER_*` constants are kept. They are the limit definitions; the
ladder references them and does not relocate them.

### Capability is declared per model, per rung

`MODELS[alias]["effort"]` is a `{rung: wire_value}` map, not a
boolean. A model that accepts `low`/`medium`/`high` but not `xhigh`
simply has no `xhigh` entry, and that rung is not sent. A model with
no map, and a provider with no opt-in, gets an empty map and the
field is never written.

This is what makes the feature safe on the default configuration. An
OpenAI-compatible relay that rejects `reasoning_effort` with a 400
cannot be reached by moving a slider, because the field only appears
for a model that declared it. A boolean could not express
"accepts some of these".

Custom providers opt in through `reasoning_effort` in
`~/.pawnlogic/custom_providers.json`, toggled with
`/provider effort <name> on|off` rather than a new provider-TUI row —
the Add and Edit forms are one renderer, and a new row is a known way
to make a locked field reachable.

### One resolution seam, no per-call-site switches

`core/api_payloads.resolve_reasoning_effort(model_alias)` reads the
active level and the model's map. It is called from
`_build_openai_payload`, which has exactly one caller
(`core/api_client.py:407`) even though `stream_request` has six.

The alternative — threading a level argument through the main Turn,
delegation, `/think`, history summaries, and workspace naming — was
rejected because a missed call site fails as "the setting silently
does nothing", which is the hardest class of bug to notice and report.
Resolving at the payload builder covers all five paths with no
threading.

`/model` chains the effort picker immediately after a model is
selected, since that is where the user is already choosing how the
model should behave. The chain is skipped for a model that declares
nothing: the level would still move local limits, but there is no
negotiation to have, so prompting would be noise. `/effort` still
reaches those models, and `/model <alias> <effort>` sets both at once.

### Anthropic is out of scope for now

The Messages API expresses extended thinking as
`thinking.budget_tokens`, and `core/provider_streams.py` has no
`thinking_delta` branch. Sending a parameter whose reasoning the
transcript cannot display is half a feature, so Anthropic models take
the local limits only and `/limits` says the value was not sent.

## Consequences

- The six legacy commands remain registered as aliases. A user's
  existing habit is never wrong; it prints where the setting moved.
- `apply_effort` is the single write path for the live selector,
  `/effort`, and the aliases, so they cannot drift apart. It carries
  `preferred_worker` across, which fixes a pre-existing bug: the tier
  presets all pinned it to `"auto"`, so `/deep` silently undid an
  explicit `/worker <alias>` lock while the worker menu — which reads
  the on-disk policy first — kept showing the old value.
- A delegated worker inherits the parent's level, because it resolves
  from its own model alias. Its `max_tokens` is clamped by
  `SubAgentSession.MAX_TOKENS` so a worker chosen for speed does not
  inherit the 32k ceiling that `high` implies.
- Sessions saved before this change carry limits but no
  `effort_level`. `infer_effort_level` reverse-infers the rung so an
  old `/ultra` session restores as `max` rather than snapping to the
  default.
- `/effort` is a modal selector, so the wire-v1 ratatui client
  intercepts a bare `/effort` the same way it already intercepted bare
  `/model`, pointing the user at `/effort <level>`.
- The toolbar field is `Effort:` rather than `Tier:`, reading
  `effort_level` directly and falling back to reverse inference.
