# ADR 0013 — Offline Containers with Scoped HTTP/CONNECT Egress

**Status:** Accepted for Phase 1. Independent luna_max re-audit passed;
local staged regression and owned-fixture acceptance passed. Delivery is Unreleased.
No release or tag is implied. Phase 2 requires separate host authorization.

## Context

A bridge authorization enables connectivity but cannot enforce a destination
allowlist. Hosts-file mappings and scope fingerprints did not prevent direct
IP connections, custom DNS, or redirects. Owned-fixture negative probes
demonstrated this limitation. Containers must not gain NET_ADMIN, privileged
mode, the Docker socket, or host credentials to implement a filter.

## Decision

When the operator sets `PAWNLOGIC_DOCKER_EGRESS_ALLOW`, an explicitly authorized
bridge request for disposable built-in Python runs uses Docker `network=none`.
A separately mounted, read-only Unix relay carries HTTP/CONNECT bytes to a
trusted host proxy. The container has no external route. It can talk directly
to the Unix socket, so the host proxy enforces every request independently;
proxy environment settings are conveniences rather than security controls.

Capture the operator declaration once. Resolve each declared hostname once
before startup, preserve all numeric answers, and connect with explicit
IPv4/IPv6 numeric sockets. Host declarations authorize that exact hostname;
literal IP declarations/CIDRs authorize literal IP targets. Unlisted names
fail without DNS. Network Policy hard-denied addresses remain denied.

Use a private operation parent, separate writable code and read-only relay
mounts, non-root numeric UID:GID, all capabilities dropped, read-only rootfs,
and existing resource ceilings. UID must be nonzero; numeric GID may be zero. No additional host mounts or dependencies
are supported by this phase. Operation duration is 1–300 seconds. Setup errors
deny execution; operation expiry closes pending dials and active sockets;
cleanup revokes the proxy before container removal and reports unresolved
cleanup as SECURITY BLOCK.

HTTP accepts one request per connection, streams fixed/chunked uploads up to
64 MiB decoded / 128 MiB wire bytes, and bounds headers, trailers, buffers and
concurrent handlers. Expect and upgrades are rejected. CONNECT remains opaque
TCP to a declared target/port, including non-TLS CTF protocols; it does not
provide transparent arbitrary TCP/UDP/ICMP networking or inspect TLS.

Scoped host networking, connected persistent creation, persistent exec and
Airlock are rejected. Offline runs and unmounted offline persistent creation
remain allowed; list/destroy remain allowed. Without the operator setting,
legacy authorized bridge/host access remains capability-only. Scope does not
quarantine already-running connected containers: stop/destroy them first, and
change the operator declaration only between operations. No silent
fallback from scoped transport to bridge is permitted.

## Validation

Protocol tests cover fragmented chunk framing, ambiguous framing, body/trailer
ceilings, pinned numeric dialing and revocation races. Integration tests check
the actual Docker kwargs, early denials, mount separation and cleanup errors.
Real fixtures must use distinct IPs: scope is host/IP based, not a port filter.
Required real probes include HTTP, chunked, 9 MiB fixed upload, verified HTTPS,
redirect/out-of-scope refusal, raw TCP/UDP refusal and daemon hardening state.
A separately recorded IQuest-Q1 turn checks the actual tool workflow without
replacing deterministic transport or security assertions with model behavior.

## Phase 2: Host-Managed Arbitrary TCP/UDP Filtering

Prepare a narrowly defined helper for owner review; tool arguments cannot
edit firewall rules or grant their own destinations. The helper must identify
the container/network, support IPv4 and IPv6, constrain DNS, bind grants to
operation identity, revoke established conntrack state and restore resources
after failure/restart. Negative direct TCP, UDP, DNS and redirect tests must
precede model acceptance. Package-install deadlines and persistent offline
attach/restore semantics also need explicit design before that path is enabled.

Detect Docker's firewall backend first. On the iptables backend, Docker places
user rules in DOCKER-USER; original destinations after DNAT require conntrack
matching. On the nftables backend there is no DOCKER-USER chain; use a separate
owner-managed table/hook and never edit Docker-owned tables. See Docker's
[iptables guide](https://docs.docker.com/engine/network/firewall-iptables/) and
[nftables guide](https://docs.docker.com/engine/network/firewall-nftables/).

Neither broad sudo nor an unreviewed gateway container with NET_ADMIN is an
acceptable shortcut. The owner must explicitly approve a narrow helper
installation/privilege policy or apply reviewed rules. Phase 1 does not make
that choice and performs no host firewall changes.
