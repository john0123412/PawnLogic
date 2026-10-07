# Container Boundary Follow-ups

**Status:** Partially implemented on main (`ea6600f`…`5efe42b`). Merged:
final-code evidence (§1), the offline attach compatibility guard (§3),
Airlock operation deadlines including the post-merge failure-path fixes (§2),
and the legacy-container read-only preflight (§4). Prepared but NOT
installed: the host TCP/UDP review package (§5). Open: owner terminal
acceptance (§6), separately authorized §5 activation, and a passing
final-code IQuest run (the bounded attempt produced no tool calls and stays
recorded as failed). Version remains 0.4.3; no tag, release, host firewall
change or privilege installation has been authorized. Delivery follows
independent review, the protected-branch PR flow and required CI.

## Goal and existing guarantees

Close the remaining evidence and lifecycle gaps before extending container
network enforcement. Preserve [ADR 0013](../adr/0013-docker-scoped-http-egress.md):
configured scopes force supported disposable Python operations through an
offline HTTP/CONNECT relay. Unconfigured bridge/host grants remain
capability-level authorizations. This plan does not silently change that
compatibility contract or claim transparent TCP/UDP filtering is implemented.

The execution order is evidence, explicit rejection of unsupported offline
attachment, bounded Airlock execution, scope activation checks, then separately
authorized host filtering. Owner
terminal acceptance can proceed alongside these items.

## 1. Final-code evidence

- Run the existing owned-fixture deterministic harness and one bounded
  IQuest-Q1 attempt against the current commit after the mapped-IPv6 fix.
- Preserve earlier reports separately; record commit, actual tool calls,
  nudges, container state, target events and every canary event.
- Require HTTP proof, chunked upload, 9 MiB upload, verified HTTPS, redirect
  denial, distinct-IP destination denial, direct TCP/UDP denial and daemon
  hardening inspection. Model behavior does not replace these assertions.
- Keep mapped metadata verification offline and assert denial before dialing;
  never contact real cloud metadata for acceptance.
- A model plan without a tool call, an API error or any safety violation is
  a failed attempt. Do not automatically retry to obtain a green summary.

**Transport/security evidence is done when:** the deterministic final-code
report passes and independent review identifies its exact commit. The IQuest
workflow has its own pass/fail result; absence of a model tool call leaves that
workflow unverified and does not erase deterministic results or block lifecycle
fixes. Failed attempts remain available.

Current `ea6600f` evidence: all nine real deterministic checks passed. The
bounded IQuest attempt produced zero tool calls after two nudges, with no API
error; model acceptance failed. It is not recorded as an overall pass.

## 2. Airlock deadline (after the small compatibility guard PR)

Affected ownership: `tools/docker_sandbox.py`, Airlock schema in
`tools/docker_schemas.py`, focused Docker policy tests, and lifecycle helpers
only if the existing architecture budget requires a cohesive extraction.

- Add an integer operation timeout, proposed default 120 seconds and range
  1–300 seconds. Reject booleans, non-integers and out-of-range values before
  any connect or exec. Make the schema and implementation agree.
- Start the monotonic deadline before temporary connection. Include apt update,
  package install and pip in the same budget. HTTP-client timeouts or a shell
  `timeout` command alone do not establish containment.
- Use finite daemon request timeouts and an independent deadline watchdog.
  On expiry revoke the tool handle before terminating the container; use
  forced removal if kill fails, and report unresolved cleanup explicitly.
- Expiry must stop package processes and their children, including operations
  on a container already connected to bridge. Merely timing out a waiting
  host thread leaves network-capable code running and is insufficient.
- Normal completion preserves an existing bridge connection and removes only
  the attachment owned by the operation. Timed-out persistent containers are
  terminated: document this behavior before enabling the contract.
- Serialize Airlock operations for the same container and bind every callback
  to an operation generation/token. Atomically invalidate old callbacks before
  allowing another operation, so an old timer cannot kill its successor.
  Use bounded joins only: a stuck Docker SDK request must not reintroduce
  unlimited waiting. Cannot confirm process termination or cleanup means
  containment failure, never success.
- Retain the configured-scope Airlock denial. Package execution deadlines
  must not introduce a scoped package-install bypass.

**Red tests first:** stalled exec; apt update consuming the budget; already-on-
bridge expiry; response loss after attach; disconnect failure; kill/remove
failure; deadline/completion race; invalid timeout causing zero daemon
mutations; two operations on one container.

**Real acceptance:** use owned containers and a local sleeping installer
fixture, with no package downloads. Verify deadline, process/container state,
handle revocation, network cleanup and zero post-expiry fixture traffic.
Daemon unavailability must be an explicit containment failure, not a claim
of successful revocation.

## 3. Offline attach/restore compatibility

Docker rejects bridge attachment to containers created in private `none`
network mode. Record this as an engine contract, not a transient failure.

- First deliver a small compatibility guard PR: refresh the container and
  its actual membership; reject `none` before calling network connect, and
  fail closed on unknown state. Preserve existing authorized bridge behavior.
  Report the unsupported operation clearly without suggesting host networking
  or removing scope enforcement. This guard precedes the deadline PR.
- Reproduce the current daemon behavior with an owned container and retain
  the existing guarantee that a confirmed offline rejection preserves it.
- Any positive offline attach/restore workflow needs a separate design/PR.
  Evaluate a dedicated internal network for newly created managed persistent
  containers. Prove absence of external routes and isolate peers; "internal"
  alone is not sufficient evidence that the container cannot reach the host.
- Before enabling any temporary attachment, specify exact original membership
  and routes, connect ownership, disconnect/restore order and response-loss
  handling. Restoration failure invokes the same containment contract.
- Existing `network=none` containers are not automatically recreated, migrated
  or deleted. If an isolated reversible topology cannot be demonstrated,
  retain the explicit rejection and provide a documented owner-controlled
  migration path instead of relaxing the isolation guarantee.
- Configured scopes continue to reject Airlock and persistent execution.

**Compatibility guard is done when:** none/unknown state is rejected before
connect or install, the existing container is preserved, and the authorized
already-bridge path remains covered. No alternative topology is required to
complete that guard.

**A later positive topology is done when:** install simulation restores the proven offline state;
negative attach/restore and lost-response cases do not leave an unreported
live connection. Unsupported topology fails before installer execution.

## 4. Scope activation and legacy-container handling

- Add a read-only preflight/report for PawnLogic-labelled containers. Identify
  running bridge/host or unknown-network containers and explain that enabling
  a scope does not quarantine them. Do not list or manage unrelated containers.
- Owner selects stop/destroy actions explicitly; preflight itself never mutates
  an existing container. Missing or ambiguous daemon state is reported as
  unknown, not safe.
- Keep declarations fixed during an operation. Scope remains operator-owned,
  with no model field that can grant destinations or disable enforcement.
- An unscoped grant remains clearly labelled capability-only. Making scope
  mandatory or removing host mode globally requires a separate compatibility
  decision; this plan does not infer it from an HTTP workflow request.

**Done when:** mixed legacy/new fixtures are accurately reported, scope
operations remain fail-closed, and reports never imply retroactive isolation.

## 5. Host-managed transparent TCP/UDP (authorization gate)

First prepare a concrete review package without installing it: helper interface,
policy/identity schema, generated rule examples, dry-run output, rollback,
threat review and simulated backend tests. Unknown or unsupported Docker
backends deny activation rather than falling back to unfiltered bridge.

Rules must bind to the actual managed container/network and operation identity;
labels or IPs alone are insufficient when addresses can be reused. Cover
IPv4/IPv6, mapped addresses, host-local destinations, same-bridge peers,
forwarded traffic, approved DNS, direct alternate resolvers, established flows
and conntrack revocation. Do not assume DOCKER-USER covers host INPUT or all
same-bridge traffic. Resolve each hostname once when an operation is established;
its snapshot is immutable until operation end. New answers require a new
operation and renewed authorization; retries never add addresses. Confirm
expiry, failure, daemon restart and helper restart
cannot leave an unfiltered live container.

Before helper implementation approval, deliver a traffic-path-to-hook matrix:
external IPv4/IPv6 forwarding; original destinations after DNAT; host INPUT
and host gateway; same-bridge peers; host/embedded DNS forwarding; published
port hairpin/reverse paths; link-local/metadata; additional network attachments
and IPv6 routes. Verify each actual backend path with owned fixtures rather
than assuming which hook it traverses. An uncovered path denies activation.

For iptables, use the Docker-supported DOCKER-USER integration where applicable,
plus justified hooks for other paths. For nftables, use a separate owner table
and reviewed hook priorities; never edit Docker-owned tables. Do not migrate
the host firewall backend as part of this work.

**Required owner approval before application:** the exact helper installation,
its narrowly scoped privilege policy, affected network paths and rollback.
No broad sudo, sandbox NET_ADMIN, privileged gateway, model-supplied firewall
commands, Docker-socket mount or automatic service installation.

**Acceptance after authorization:** owned dual-stack positive/negative TCP,
UDP and DNS fixtures; direct IP and hostname changes; same-peer/host paths;
revocation of established sockets; failure/restart and concurrent-operation
isolation. Only then run a bounded real IQuest workflow.

Sources verified for this plan:
[Docker iptables](https://docs.docker.com/engine/network/firewall-iptables/),
[Docker nftables](https://docs.docker.com/engine/network/firewall-nftables/).

## 6. Owner terminal acceptance and release boundary

Run `tools/owner_acceptance_probe.py` against the intended Python frontend or
published binary, and record which target was tested. Its automated checks
do not prove the four visual checks on the owner's terminal emulator.
Scrollback, selection/copy, CJK/emoji width and duplicate output stay manual
until the owner actually observes and records each outcome. A checkout test
does not replace published-binary acceptance.

Each implementation PR requires focused red/green regression, ruff, the
authoritative typed-island mypy command, architecture budget, code index,
bilingual docs/release checks, fast suite and relevant E2E. Record independent
luna_max findings before pushing, then required PR and merged-main CI.
Do not raise budgets merely to fit new lifecycle code.

Review README pairs, SECURITY, CHANGELOG Unreleased and AGENT release state,
typed island and Known Risks when runtime contracts change. These records
are the project memory; local acceptance logs are supporting evidence.
Do not select a version, open preparation/finalization release PRs or create
a tag until a separate release instruction is given.
