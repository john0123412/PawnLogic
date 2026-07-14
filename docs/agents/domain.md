# Domain Context For Agents

This file points agents to the authoritative domain context. Do not duplicate
the content here; read the source files directly.

## Primary Context

- **Project vocabulary:** [`CONTEXT.md`](../../CONTEXT.md) defines Turn, Provider,
  Model Alias, Runtime Home, Workspace, Tool Call, Skill Pack, RuntimeContext,
  and Output Sink.
- **Architecture decisions:** [`docs/adr/`](../adr/) records accepted ADRs.
  Read the ADR before changing the module it governs.
- **Module ownership:** [`docs/MODULE_MAP.md`](../MODULE_MAP.md) lists Interface,
  Implementation, Seam, Adapter, owning tests, and invariants per module.
- **Release plans:** [`docs/plans/INDEX.md`](../plans/INDEX.md) identifies the
  active plan and completed releases.

## How To Use

1. Before broad code changes, read `CONTEXT.md` for terminology.
2. Before editing a module, check `MODULE_MAP.md` for its role and owning tests.
3. Before architectural decisions, check `docs/adr/` for prior decisions.
4. Before release work, read the active plan in `docs/plans/`.
5. Do not introduce new domain terms without adding them to `CONTEXT.md`.
