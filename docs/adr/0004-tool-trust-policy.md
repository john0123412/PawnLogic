# ADR 0004: Tool Trust Policy

## Status

Accepted

## Context

PawnLogic tools range from safe read-only operations (file reading, symbol
lookup) to destructive or network-dependent operations (Docker execution, shell
commands, browser automation, CTF exploit chains). Before a unified trust
policy:

- Each tool implemented its own safety checks or relied on callers to gate
  dangerous operations.
- Docker operations could bypass network restrictions or pull images without
  explicit authorization.
- Host shell operations did not always scrub environment variables containing
  API keys.
- Delegate capabilities could potentially bypass host, network, or destructive
  gates.

## Decision

Define a trust boundary model in `core.trust`:

1. **TrustBoundaryKind enum:** Each tool is classified into a trust boundary
   (e.g., `LOCAL`, `HOST_PROCESS`, `DOCKER`, `BROWSER_NETWORK`, `PRIVATE_NETWORK`).
2. **OperationPolicy:** `core.operation_policy` gates network, destructive, and
   interactive operations behind explicit authorization flags.
3. **PathPolicy:** `core.path_policy` enforces canonical path containment for
   all file operations.
4. **HostProcessRunner:** `core.host_process` centralizes environment scrubbing,
   timeout, and process-group cleanup for all host shell operations.
5. **Container labelling:** Docker resources are labelled as PawnLogic-managed.
   Cleanup is restricted to labelled resources; unscoped global prune is
   forbidden.

## Consequences

Every tool must declare its trust boundary. The Tool Registry records the trust
boundary alongside the handler, schema, and capabilities.

Tests in `test_operation_policy.py`, `test_run_shell_policy.py`,
`test_docker_policy.py`, and `test_security.py` verify that trust boundaries are
enforced.

New tools that perform network, destructive, or host operations must go through
the OperationPolicy gate. Adding a new trust boundary requires an ADR update.
