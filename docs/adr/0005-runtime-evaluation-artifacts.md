# ADR 0005: Runtime Evaluation Artifacts

## Status

Accepted

## Context

PawnLogic includes a runtime evaluation system (`tools/runtime_eval.py`) that
runs scenarios and produces JSONL artifacts. Before this ADR:

- Artifacts had no schema version, making it hard to evolve the format.
- Duration was measured after a scenario returned, not enforced during
  execution, so a stuck scenario could block the entire suite.
- Artifacts could overwrite each other if created in the same second.
- Raw Provider output was occasionally stored in artifacts, leaking API keys
  or model responses.

## Decision

Define a runtime evaluation artifact contract:

1. **Schema version:** Every artifact includes `schema_version` (currently 1).
   Format changes must bump the version.
2. **Run ID:** Every run produces a unique `run_id` (UUID-based) used in the
   artifact filename.
3. **Monotonic timing:** Duration is measured with `time.monotonic()`, not
   wall-clock, and enforced with a real deadline that can terminate a stuck
   scenario via child process signal.
4. **Atomic replacement:** Artifacts are written to a temp file and atomically
   renamed. No overwrites of existing files.
5. **Allowlisted fields:** Artifact fields are allowlisted. Raw Provider output,
   API keys, tokens, and environment values are never stored.
6. **Redaction:** `tools/eval/redaction.py` ensures summary fields are redacted
   before writing.

## Consequences

All evaluation scenarios produce artifacts conforming to this contract. Tests
in `test_runtime_eval.py` and `test_runtime_eval_artifacts.py` verify schema
version, unique run IDs, atomic writes, redaction, and deadline enforcement.

Adding a new artifact field requires updating the allowlist in
`tools/eval/artifacts.py` and the contract tests.
