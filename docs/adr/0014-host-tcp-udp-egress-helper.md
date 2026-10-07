# ADR 0014 — Host-Managed Transparent TCP/UDP Egress Helper (Authorization-Gated)

**Status:** Proposed — review package only. Nothing in this ADR is installed,
wired into a tool, or executed against the host. Activation requires separate
owner authorization of the exact helper installation, its narrowly scoped
privilege policy, the affected network paths and the rollback procedure
(docs/plans/container-boundary-followups.md §5). No broad sudo, sandbox
NET_ADMIN, privileged gateway, model-supplied firewall commands, Docker-socket
mount or automatic service installation is authorized by this document.

## Context

Scoped disposable Python runs enforce destinations through the offline
HTTP/CONNECT relay (ADR 0013), but unscoped bridge/host grants remain
capability-only, and non-HTTP protocols (arbitrary TCP/UDP) have no
destination enforcement at all. Model-generated semi-trusted code bypasses
environment proxies via raw sockets, so a transparent host-side filter is the
only remaining enforcement point. The machine has no passwordless sudo; any
helper therefore needs an explicit, narrow privilege grant from the owner.

## Decision

Prepare, review and simulate — but do not install — a host egress helper:

1. **Identity binding.** Container traffic reaches the FORWARD path through
   its BRIDGE device, never the veth, so iptables rules match the bridge
   interface of the managed network plus the container's frozen
   source-address snapshot (one rule per source address), and every rule
   carries a unique operation id (`pawn-op-…`, lowercase alphanumeric
   suffix); the nftables rules match the source snapshot on the per-operation
   chain. Labels or IPs alone are insufficient when addresses
   are reused. Each hostname resolves exactly once when the operation is
   established; its snapshot is immutable until operation end. New answers
   require a new operation with renewed authorization; retries never add
   addresses.
2. **Backends.** iptables uses the Docker-supported `DOCKER-USER` chain
   (FORWARD entry point only), mirrored per family via `ip6tables`. nftables
   uses a separate owner table `inet pawnlogic_egress` with one per-operation
   chain (`op_<id>`, hook priority −110); Docker-owned tables are never
   edited. The host firewall backend is not migrated as part of this work.
   Unknown or unsupported backends deny activation rather than falling back
   to an unfiltered bridge.
3. **Fail-closed coverage, scoped, drop-first.** A per-interface drop
   terminates the managed container's uncovered traffic (matched on its own
   source addresses on the bridge interface) so uncovered paths are denied,
   not silently passed, while sibling containers on the same bridge are not
   collateral. Rules are INSERTED at the top of `DOCKER-USER` in reverse
   order with the drop first — appended rules could land after a pre-existing
   owner RETURN rule and become dead code, and drop-first keeps the
   container fail-closed during the whole activation sequence. An
   `ESTABLISHED,RELATED` allowance is limited to the REPLY direction so
   published-port responses keep flowing. Original-direction packets,
   including connections established before activation, must still match
   pinned destinations and ports; state alone never grants outbound access.
   Expiry/rollback revocation still needs real backend verification (row 8).
   Link-local and cloud-metadata destinations are
   rejected at policy time, including `100.100.100.200` and mapped IPv4
   spellings (they can never enter an allowlist). The future
   helper must deny concurrent activation (one managed operation at a
   time).
4. **Lifecycle.** Expiry, failure, daemon restart and helper restart revoke
   the operation's rules and conntrack flows and then VERIFY revocation with
   listing checks; every verification command branches on the query itself,
   so a failing or unauthorized query reports a containment failure instead
   of a false success. nft chain absence is established from a successful
   complete owner-table snapshot, never from a failed chain query; iptables
   snapshots are matched without a short-circuit pipeline that can SIGPIPE
   under `pipefail`. A remaining flow or rule is a containment failure,
   never a clean report.

## Traffic-path-to-hook matrix (required before implementation approval)

Every row must be verified against the actual backend with owned fixtures;
an uncovered path denies activation.

| # | Traffic path | Hook / coverage in this design | Verification required before activation |
|---|---|---|---|
| 1 | External IPv4 forwarding (container → host → internet) | `DOCKER-USER` scoped to bridge + container source (iptables) / per-op forward chain (nftables) | Owned dual-stack positive/negative TCP+UDP fixture |
| 2 | External IPv6 forwarding (incl. NAT66) | `ip6tables DOCKER-USER` / `ip6 saddr…ip6 daddr` rules | Same fixture over IPv6 |
| 3 | Original destinations after DNAT (published ports) | `ESTABLISHED,RELATED` reply allowance keeps published-port replies flowing; original-direction flows to non-pinned destinations are NOT accepted | Fixture: published port + reverse path probe (no leak out, replies work) |
| 4 | Host INPUT and host gateway paths | NOT covered by `DOCKER-USER`; needs a dedicated INPUT hook or justification that no path exists | Probe from container to host-owned services |
| 5 | Same-bridge peer traffic | NOT covered by the container-scoped rules; peer-to-peer frames may not traverse FORWARD at all | Two-container peer probe on the managed bridge |
| 6 | Host/embedded DNS forwarding (127.0.0.11) | Embedded DNS forwards from the host namespace — container→DNS may not traverse FORWARD; pinned resolvers + drop rule must be verified | `docker exec` dig against 127.0.0.11 and against arbitrary resolver |
| 7 | Direct alternate resolvers | udp/53 restricted to pinned servers; other UDP dropped (policy pins udp ports explicitly) | Negative fixture on udp/5353 to non-pinned targets |
| 8 | Established flows after rule change | Original-direction packets must match pinned destinations even when established; only replies get the blanket state allowance. Candidate destination-scoped deletion still needs lifecycle and DNAT verification before use | Pre-activation out-of-scope connection and expiry fixture with a long-lived approved connection |
| 9 | Link-local / cloud metadata (169.254.169.254, 100.100.100.200, fd00:ec2::254, mapped IPv4 forms) | Fail-closed drop (never in any policy allowlist); Network Policy hard denial (ADR 0013) applies only on the relay path, which is separate | Backend fixture probe from the container |
| 10 | Additional network attachments and IPv6 routes | Policy covers one managed network; attaching a second network must re-run policy or be denied | Attach-second-network probe |
| 11 | Published-port hairpin / reverse paths | Container-originated hairpin is denied by the source-scoped drop; external-hairpin paths still need verification | Hairpin probe |
| 12 | Container restart / IP reuse | Rules bind bridge + source snapshot + operation id comment; identity re-verified against the daemon before activation | Reuse probe with a recycled address |
| 13 | Daemon / helper restart | Rules must be re-verified (present, scoped to the live operation) before an operation continues; absence is a containment failure | Kill-and-restart probe mid-operation |

## Threat review (summary)

- **Model-supplied firewall commands are forbidden.** The helper is
  owner-installed; the model can only request operations whose policies are
  operator-owned. No model field can grant destinations, extend time, or
  disable enforcement.
- **Address reuse.** Operation id + bridge/source-snapshot binding +
  daemon-side identity verification before activation; stale rules are never
  reused.
- **DNS escape.** Alternate resolvers and DoH/DoT endpoints are denied by the
  container-scoped drop; only pinned resolvers pass, and only on udp/53 in
  the candidate rules (DoT 853 must be added explicitly if ever needed).
- **Command injection into reviewed artifacts.** Operation ids, interface
  names and addresses are charset-validated (numeric addresses only, no
  shell metacharacters) before they are interpolated into commands. IPv6
  scope suffixes are rejected: `ipaddress` alone accepts nonnumeric zone text
  that must never be interpolated into a shell artifact.
- **Privilege scope.** The helper's privilege policy must be a narrow
  sudoers rule set for the exact commands it runs (rule add/delete,
  conntrack delete/list, save/restore for rollback), never broad sudo; the
  Docker socket is never mounted into any container for this purpose.
- **Uninstall/restart safety.** iptables rollback removes only rules
  carrying this operation's anchored comment (`pawnlogic <op-id> ` fixed
  string, suffix-charset enforced against prefix collisions); nftables
  rollback deletes only the operation's own chain. `iptables-save | restore`
  rewrites the table from a snapshot: Docker churn must be quiesced (or the
  xtables lock held) while rollback runs. nftables chains must be flushed
  before they can be deleted (`nft flush chain`, then `nft delete chain`),
  and rollback ends with conntrack and rule-presence checks whose failure is
  a containment failure with the exact residual state, never as success.

## Rollback

The commands below are candidate artifact deletion, NOT a safe standalone
live-container rollback. Before deleting the last blocking rule, a future
executor must stop/quarantine the owned container and verify containment.
Deleting rules while a live bridge container remains connected restores its
unfiltered access. Query failures retain containment and require administrator
attention; a save/restore command must never be suggested as a universal
"one-line cleanup" while other operations or Docker are changing the table.

iptables: `iptables-save | grep -vF 'pawnlogic <op-id> ' | iptables-restore`
(and the ip6tables mirror) — the fixed-string filter is anchored with a
trailing delimiter so concurrent operation ids cannot be over-matched —
followed by per-destination `conntrack -L` checks that report
`CONTAINMENT FAILURE` when flows remain. nftables: `nft flush chain inet
pawnlogic_egress op_<id>` then `nft delete chain inet pawnlogic_egress
op_<id>` (per-operation chain; other operations' chains are untouched) plus
the same verification. A failed rollback or a failing verification query is
reported as a containment failure with the exact residual state, never as
success.

## Consequences

The stage-one runbook is [host-egress-stage-one.md](../runbooks/host-egress-stage-one.md).
The read-only prerequisite CLI reports missing binaries/administrator access
and initializes all matrix rows as `not_run`; even a ready prerequisite report
never authorizes activation or installs a sudoers entry.

Until the owner authorizes and the backend verification matrix passes,
unscoped bridge/host grants remain capability-only, and the CHANGELOG keeps
saying so. After authorization, acceptance follows §5: owned dual-stack
positive/negative TCP, UDP and DNS fixtures; direct IP and hostname changes;
same-peer/host paths; revocation of established sockets; failure/restart and
concurrent-operation isolation; only then a bounded real IQuest workflow.

## References

- [Docker iptables](https://docs.docker.com/engine/network/firewall-iptables/)
- [Docker nftables](https://docs.docker.com/engine/network/firewall-nftables/)
- [Netfilter conntrack expressions and directions](https://www.netfilter.org/projects/nftables/manpage.html)
- ADR 0013 (scoped HTTP/CONNECT relay), plan §5
