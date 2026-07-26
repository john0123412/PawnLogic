# ADR 0007: Explicit Extension Runtime Boundary

## Status

Accepted

## Context

PawnLogic already has a Tool Registry, Operation Policy, MCP integration, and
several built-in Tool families. The 0.3.0 architecture also needs optional
capabilities that can be distributed independently, including the proposed
`pawnlogic-security` package. Without an Extension boundary, each optional
feature would have to be imported and assembled by `core.session` or by CLI
startup code. That would make installation equivalent to activation, couple the
core distribution to optional security code, and make failures in one optional
feature capable of breaking core startup.

The host therefore needs a narrow, versioned seam that can discover installed
Extensions, keep them disabled until the user explicitly enables them, and
register their contributions transactionally. The seam must also preserve the
existing Tool Registry invariants: every Tool has a handler, schema, phase,
trust boundary, and capability declaration, and no Tool may bypass Operation
Policy.

The proposed security distribution must be independently installable and
publishable. Core must be able to discover its metadata without importing
`pawnlogic_security`, and it must not contain security-package files or require
security dependencies for a normal installation.

## Decision

PawnLogic introduces an Extension Runtime owned by a dedicated core module
(planned as `core.extensions` with public contracts in
`core.extension_contracts` if a separate contracts module is useful). The
runtime is the sole host-side owner of Extension discovery, compatibility
validation, enablement, contribution ownership, rollback, disablement, and
shutdown.

### Entry-point contract

Python packaging entry points are the discovery mechanism. Extensions declare
the following group in their distribution metadata:

```toml
[project.entry-points."pawnlogic.extensions"]
security = "pawnlogic_security.extension:extension"
```

The entry-point name is the stable Extension name within the host. The value
resolves, only during enablement, to an Extension export containing an
`ExtensionManifest` and a factory for the Extension implementation. The host
uses `importlib.metadata` to enumerate entry points and distribution metadata;
enumeration must not load the entry-point object or import Extension modules.

The entry-point name, manifest name, and distribution name are separate fields
and must be validated for consistency. A malformed or duplicate entry point is
reported as an unavailable Extension and cannot be enabled. Entry-point names
are normalized before comparison, and status output uses the canonical name.

### Minimum stable contracts

These contracts are the smallest host-facing interface for the 0.3.x Extension
seam. Concrete implementations may add private helpers, but they must not
require private `AgentSession` fields, legacy module globals, or direct mutation
of the Tool Registry.

```python
@dataclass(frozen=True)
class ExtensionDescriptor:
    name: str
    distribution: str
    version: str
    entry_point: str
    enabled: bool
    compatible: bool | None
    error: str | None = None


@dataclass(frozen=True)
class ExtensionManifest:
    name: str
    version: str
    core_version_spec: str
    api_version: int
    description: str
    capabilities: frozenset[str]
    config_schema: Mapping[str, object]


@dataclass(frozen=True)
class ExtensionContext:
    name: str
    core_version: str
    runtime_home: Path
    config: Mapping[str, object]
    tools: "ExtensionToolRegistrar"
    commands: "ExtensionCommandRegistrar"
    prompts: "ExtensionPromptRegistrar"
    events: "ExtensionEventSink"


class ExtensionManager(Protocol):
    def discover(self) -> tuple[ExtensionDescriptor, ...]: ...
    def enable(self, name: str) -> "ExtensionStatus": ...
    def disable(self, name: str) -> "ExtensionStatus": ...
    def status(self, name: str | None = None) -> tuple["ExtensionStatus", ...]: ...
    def shutdown(self) -> None: ...
```

`ExtensionDescriptor` is discovery-time data. It is safe to display in status
output and contains no imported Extension object or secret configuration.
`ExtensionManifest` is enablement-time metadata. It declares the Extension's
identity, host API version, supported core version range, human-readable
description, capability set, and a JSON-compatible configuration schema.
`ExtensionContext` is the controlled runtime dependency object passed to an
enabled Extension. `ExtensionManager` owns the lifecycle and returns a
structured status rather than exposing implementation exceptions to callers.

An enabled Extension provides a lifecycle object with the following conceptual
methods:

```python
class ExtensionImplementation(Protocol):
    manifest: ExtensionManifest

    def start(self, context: ExtensionContext) -> "ExtensionContributions": ...
    def stop(self) -> None: ...
```

`ExtensionContributions` contains Tool, command, phase, and prompt
contributions. Registration is performed by the manager through the registrar
interfaces in the context; an Extension never receives an unrestricted handle
to the host Registry. All contributions carry the owning Extension name so
disablement and rollback cannot remove another source's state.

### Discovery is separate from enablement

Discovery is cheap, read-only, and non-importing. It lists installed
distributions, entry-point names, versions, and persisted enablement state.
Discovery may occur during startup and must succeed when no Extensions are
installed.

Enablement is explicit. The host loads the entry point, reads and validates the
manifest, checks compatibility and policy, validates the Extension's persisted
configuration, creates an `ExtensionContext`, starts the implementation, and
registers all contributions as one transaction. Only after the transaction
commits does the Extension become visible to Tool, command, phase, and prompt
consumers.

Installation never implies enablement. A newly installed Extension is
discoverable but disabled by default. Previously enabled Extensions may be
re-enabled at startup only when their persisted state says enabled and their
current manifest remains compatible; a failed activation is isolated and does
not fail core startup. Explicit enablement and disablement are persisted
atomically under Runtime Home without storing secrets.

### Deterministic source priority and conflicts

Contribution assembly uses a deterministic source order:

1. built-in PawnLogic Tools and commands;
2. explicitly enabled Extensions, ordered by canonical Extension name;
3. enabled MCP servers, ordered by canonical server identity and Tool name.

This priority defines assembly and visibility order only. It is not permission
to silently overwrite a contribution. Public Tool names, command names, phase
names, and other globally addressable identifiers must be unique. A lower
priority contribution that claims an identifier already owned by a higher
priority source causes that source's registration transaction to fail. The
existing runtime remains unchanged. Two Extensions that conflict with each
other are resolved by the same deterministic ordering: the later transaction
is rejected, never merged by accident and never allowed to replace the first
owner. MCP adapters must use a stable server-qualified name where necessary;
qualified naming does not bypass trust or policy checks.

Within one Extension, contribution order is the manifest-declared order. The
manager validates the complete contribution set before mutating any registry.
An Extension with a conflict is reported as failed or unavailable, while core
startup and already committed sources continue operating.

### Capabilities, configuration, and compatibility

Manifest capabilities are declarative, stable identifiers such as
`tools.read_only`, `tools.network`, `commands`, `prompts`, or
`mcp.stdio`. A capability declaration does not grant authority by itself. The
host intersects it with the Extension's contribution metadata, the active
Operation Policy, user configuration, and any applicable Network Policy.
Security capabilities must additionally require a valid Engagement Scope at
execution time.

`config_schema` is a JSON-compatible schema describing the Extension's
configuration shape, defaults, and validation constraints. Configuration is
stored in an Extension-owned namespace under Runtime Home and is validated
before `start`. Invalid configuration prevents enablement and leaves no partial
registration. Status, descriptors, and errors must never expose secret values;
secret material is referenced through approved runtime secret configuration,
not embedded in manifests or persisted enablement records.

The manifest declares an integer Extension API version and a PEP 440-compatible
core version specifier. Discovery does not load the entry-point export. During
explicit enablement, the manager loads only that export, reads its manifest,
and rejects unsupported API major versions or core versions outside
`core_version_spec` before creating or starting the Extension implementation.
Entry-point identity, manifest identity, and distribution metadata must agree.
Core 0.3.x preserves the stable contracts in this ADR; incompatible changes
require a new API version and an explicit migration or deprecation period.

### Lifecycle and failure isolation

The manager exposes the lifecycle states needed for status and diagnostics:

```text
discovered -> validating -> starting -> enabled
                               \-> failed
enabled    -> stopping -> disabled
```

Enablement and disablement are idempotent. On any validation, start, or
registration failure, the manager calls `stop` when the implementation has
started, removes only the failed Extension's contributions, restores the
previous Registry/command/phase/prompt state, and records a redacted failure
reason. Shutdown is best effort, idempotent, and must not prevent other
Extensions or core cleanup from running. Extension code must not execute on
mere discovery, and a failed Extension must not crash default startup or
corrupt enablement state.

The manager runs lifecycle code through the existing trust and process
boundaries where applicable. A Tool supplied by an Extension still goes through
the normal Tool Executor, Operation Policy, path policy, network policy, audit,
and output controls. Extensions cannot widen a delegated Agent's capabilities
by declaring a broader capability set.

### Optional stdio MCP boundary

An Extension may later expose a stdio MCP or child-process Adapter, but this is
an optional boundary rather than a second Extension loading mechanism. The
host treats the process as a separate trust boundary and registers only
validated, namespaced MCP Tool specifications after enablement.

The Adapter must use the shared host-process controls: explicit executable
configuration, no implicit shell expansion, scrubbed environment, bounded
startup/request/idle timeouts, process-group cleanup, protocol and output-size
validation, and cancellation handling. It must not silently download binaries,
wordlists, browsers, containers, or system packages. Network and destructive
operations remain subject to Operation Policy and, for security workflows,
Engagement Scope. A crashed or timed-out MCP process is isolated, its Tools are
removed transactionally, and core remains usable.

## Why this boundary

### Do not scan arbitrary directories

Directory scanning would make import paths, precedence, packaging behavior, and
security review dependent on filesystem layout and `sys.path` conventions. It
would also make it difficult to distinguish a deliberately installed
distribution from an arbitrary folder, and would encourage import-time side
effects. Python entry points provide distribution metadata, a canonical name,
the owning distribution, and a standard discovery API. Metadata enumeration
also lets PawnLogic list an installed-but-disabled Extension without importing
its code.

### Do not couple security code into core

The security feature has different dependencies, release cadence, trust
boundary, authorization requirements, and potentially different licensing or
operator review. Keeping `pawnlogic-security` independent means the core wheel
remains usable without security dependencies, security workflows can be
versioned and tested separately, and users opt into installation and explicit
enablement. Core depends only on this stable host contract; it must never import
`pawnlogic_security` or contain its package files. The security distribution may
depend on a compatible core release and declare its
`pawnlogic.extensions` entry point.

## Consequences

Core startup remains functional with no Extensions, and installation is no
longer an implicit authority grant. Users gain inspectable status and explicit
lifecycle control, while Extension authors receive a stable contribution seam
instead of relying on private core globals.

The manager and Tool Registry must support ownership-aware transactional
registration. This adds implementation and contract-test work, including
fake entry points, incompatible manifests, duplicate contributions, failed
startup, rollback, persisted enablement, and shutdown cleanup.

The source priority is deterministic, but it intentionally does not provide a
plugin override mechanism. Replacing a built-in Tool or command requires a
deliberate core change or a future separately documented override policy. MCP
servers and Extensions cannot hide a collision by relying on load order.

The public compatibility surface includes the entry-point group, canonical
names, manifest fields, API version, Tool/command names, capability identifiers,
configuration schema behavior, lifecycle status values, and ownership/rollback
semantics. Changes to these surfaces require an ADR update and focused tests.

## Alternatives rejected

- **Import every installed package at startup:** rejected because it makes
  optional code executable before user consent and turns Extension failures
  into core-startup failures.
- **Scan `~/.pawnlogic/extensions` or arbitrary source directories:** rejected
  because filesystem precedence and untrusted import paths are not a stable
  packaging contract.
- **Register contributions by last-write-wins:** rejected because behavior
  would depend on nondeterministic discovery order and could silently replace a
  trusted Tool.
- **Ship `pawnlogic-security` inside the core package or behind a core extra:**
  rejected because it couples release, dependency, trust, and packaging
  boundaries; the independent PyPI distribution is the required ownership
  seam.
- **Treat stdio MCP as trusted in-process code:** rejected because a child
  process needs explicit process, environment, timeout, output, and policy
  controls.

## Implementation notes

The first implementation must add contract tests before freezing concrete
public imports. It should use `importlib.metadata` without introducing a new
runtime dependency solely for discovery, add an in-memory Extension Adapter,
and prove that:

- no installed Extension is imported during discovery;
- an installed Extension is disabled by default;
- explicit enablement makes all contributions visible atomically;
- incompatible, malformed, conflicting, or failing Extensions roll back;
- disablement removes only owned contributions;
- a core-only wheel contains no `pawnlogic_security` files; and
- MCP enablement and failure preserve the same trust and conflict invariants.

The existing built-in assembly should be moved behind the manager only when
that creates a real ownership seam and removes import-time assembly from
`core.session`; a pass-through wrapper is not an architectural improvement.

## Implementation status

Implemented on the 0.3.0 stacked development branches. `core.extension_contracts`
owns the stable values, `core.extensions` owns discovery and lifecycle, and
`pawnlogic.extension_host` is the CLI startup/shutdown Adapter. Installed-layout
fixtures prove disabled discovery without import, explicit transactional
enablement, incompatibility/start failure rollback, and contribution cleanup.
Core wheel inspection also rejects `pawnlogic_security` files, Extension entry
points, security console scripts, and security dependencies. The independent
security distribution and its TestPyPI publication remain a separate external
release gate.
