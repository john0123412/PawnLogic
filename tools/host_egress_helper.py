"""Host-managed transparent TCP/UDP egress helper — REVIEW PACKAGE ONLY.

This module implements the review-package deliverable of
docs/plans/container-boundary-followups.md §5 and ADR 0014. It builds
policy objects, candidate firewall rules, dry-run text and rollback
commands for OWNER REVIEW. It is NOT installed, NOT registered as a tool,
and NEVER executes anything: there is no subprocess, no file write and no
Docker call here. Applying anything to the host firewall requires separate
owner authorization; until then an unknown or unsupported backend denies
activation instead of falling back to an unfiltered bridge.

Design constraints that the generated artifacts must keep visible:

- Traffic from a container reaches FORWARD through its BRIDGE device, not
  the veth, so rules match the bridge interface plus the container's
  frozen source-address snapshot; the operation id ties the artifacts
  together. Labels or IPs alone are insufficient when addresses are reused.
- Each hostname is resolved once when the operation is established; its
  snapshot is immutable until operation end. New answers require a new
  operation with renewed authorization.
- One managed operation at a time: the future helper must deny concurrent
  activation.
- DOCKER-USER only covers the Docker FORWARD path; host INPUT, same-bridge
  peers, published-port hairpin and embedded-DNS forwarding need the
  additional hooks listed in the ADR's traffic-path matrix and must be
  verified against the actual backend before activation.
- Expiry, failure, daemon restart and helper restart must never leave an
  unfiltered live container: revoke rules and conntrack flows, then VERIFY
  revocation — an unverifiable revocation is a containment failure.
"""

import ipaddress
import re
from dataclasses import dataclass, field

BACKENDS = ("iptables", "nftables")

# Hooks the generated rules rely on, per backend, with their coverage.
IPTABLES_HOOKS = {
    "filter": "DOCKER-USER (Docker-managed FORWARD entry point) — FORWARD only",
}
NFTABLES_HOOKS = {
    "table": "inet pawnlogic_egress (owner table; Docker-owned tables are never edited)",
    "chain": "one per-operation chain op_<id>; concurrent operations are denied",
}

RESERVED_OPERATION_PREFIX = "pawn-op-"
_OPERATION_SUFFIX_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_INTERFACE_RE = re.compile(r"^[A-Za-z0-9.@:_-]+$")

# ADR 0014 row 9: link-local and cloud-metadata ranges are hard denials and
# never enter a policy allowlist.
_HARD_DENIED_NETWORKS = (
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("fd00:ec2::254/128"),
    ipaddress.ip_network("100.100.100.200/32"),
)


def _numeric_addresses(kind: str, addresses) -> tuple:
    checked = []
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ValueError(f"{kind} entry {address!r} is not a numeric address") from exc
        expected = "IPv6" if kind.endswith("ipv6") else "IPv4"
        wrong_family = (parsed.version == 6 and expected == "IPv4") or (
            parsed.version == 4 and expected == "IPv6"
        )
        if wrong_family:
            raise ValueError(f"{kind} entry {address!r} is not {expected}")
        # IPv4-mapped IPv6 spellings classify by their effective IPv4
        # address, or ::ffff:169.254.169.254 would dodge the v4 hard denial.
        effective = getattr(parsed, "ipv4_mapped", None) or parsed
        if kind.startswith(("allowed_", "dns_servers_")) and any(
            effective in network for network in _HARD_DENIED_NETWORKS
        ):
            raise ValueError(
                f"{kind} entry {address!r} is hard-denied (link-local or cloud metadata)"
            )
        checked.append(str(parsed))
    return tuple(checked)


@dataclass(frozen=True)
class EgressPolicy:
    """Operator-owned destination scope for one host-managed operation."""

    operation_id: str
    container_id: str
    network_name: str
    bridge_interface: str
    container_ipv4: tuple = field(default=())
    container_ipv6: tuple = field(default=())
    allowed_ipv4: tuple = field(default=())
    allowed_ipv6: tuple = field(default=())
    tcp_ports: tuple = field(default=())
    udp_ports: tuple = field(default=())
    dns_servers_ipv4: tuple = field(default=())
    dns_servers_ipv6: tuple = field(default=())

    def __post_init__(self):
        if not self.operation_id.startswith(RESERVED_OPERATION_PREFIX) or not _OPERATION_SUFFIX_RE.match(
            self.operation_id[len(RESERVED_OPERATION_PREFIX):]
        ):
            raise ValueError("operation_id must be 'pawn-op-' plus lowercase alphanumeric segments")
        if not self.container_id or not self.network_name or not self.bridge_interface:
            raise ValueError("container_id, network_name and bridge_interface are required")
        if not _INTERFACE_RE.match(self.bridge_interface):
            raise ValueError("bridge_interface contains unsupported characters")
        if not re.fullmatch(r"[a-f0-9]{32,64}", self.container_id):
            raise ValueError("container_id must be the hexadecimal Docker container id")
        if not _INTERFACE_RE.match(self.network_name):
            raise ValueError("network_name contains unsupported characters")
        if not (self.allowed_ipv4 or self.allowed_ipv6):
            raise ValueError("an operation without destinations is not meaningful")
        if not (self.container_ipv4 or self.container_ipv6):
            raise ValueError("the container's own address snapshot is required for identity binding")
        for kind, addresses in (
            ("container_ipv4", self.container_ipv4),
            ("container_ipv6", self.container_ipv6),
            ("allowed_ipv4", self.allowed_ipv4),
            ("allowed_ipv6", self.allowed_ipv6),
            ("dns_servers_ipv4", self.dns_servers_ipv4),
            ("dns_servers_ipv6", self.dns_servers_ipv6),
        ):
            _numeric_addresses(kind, addresses)
        for ports in (self.tcp_ports, self.udp_ports):
            for port in ports:
                if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
                    raise ValueError(f"port {port!r} is not a TCP/UDP port number")

    @property
    def operation_suffix(self) -> str:
        return self.operation_id[len(RESERVED_OPERATION_PREFIX):]


def validate_backend(backend: str) -> str:
    """Unknown or unsupported backends deny activation — no fallback."""
    if backend not in BACKENDS:
        raise ValueError(f"unsupported firewall backend {backend!r}; activation denied")
    return backend


def _iptables_family(policy: EgressPolicy, binary: str, bridge: str, sources, destinations,
                     dns_servers, ports_tcp, ports_udp) -> tuple:
    """Candidate rules for one address family, split into (drops, allows).

    DOCKER-USER may already contain owner rules ending in RETURN, so the
    artifact inserts at the TOP in reverse order instead of appending, and
    the caller emits every source's DROP across both families before any
    allow rule so no source stays unfiltered during activation. The final
    chain order is [EST, accepts..., LOG, DROP...].
    """
    comment = f"pawnlogic {policy.operation_id} {policy.container_id[:12]} {policy.network_name}"
    drops: list = []
    logs: list = []
    accepts: list = []
    established: list = []
    for source in sources:
        drops.append(
            f"{binary} -I DOCKER-USER 1 -i {bridge} -s {source} -j DROP "
            f"-m comment --comment '{comment}'"
        )
        logs.append(
            f"{binary} -I DOCKER-USER 1 -i {bridge} -s {source} "
            f"-m limit --limit 5/min -j LOG --log-prefix 'PAWNEGRESS-DENY ' "
            f"-m comment --comment '{comment}'"
        )
        for server in dns_servers:
            accepts.append(
                f"{binary} -I DOCKER-USER 1 -i {bridge} -s {source} -d {server} "
                f"-p udp --dport 53 -j ACCEPT -m comment --comment '{comment}'"
            )
        for destination in destinations:
            for port in ports_udp:
                accepts.append(
                    f"{binary} -I DOCKER-USER 1 -i {bridge} -s {source} -d {destination} "
                    f"-p udp --dport {port} -j ACCEPT -m comment --comment '{comment}'"
                )
            for port in ports_tcp:
                accepts.append(
                    f"{binary} -I DOCKER-USER 1 -i {bridge} -s {source} -d {destination} "
                    f"-p tcp --dport {port} -m conntrack --ctstate NEW,ESTABLISHED "
                    f"-j ACCEPT -m comment --comment '{comment}'"
                )
        # Replies of established flows (e.g. DNAT'd published-port services)
        # pass before the fail-closed drop; matrix row 3 covers the
        # original-direction caveat. Emitted last so it lands on top.
        established.append(
            f"{binary} -I DOCKER-USER 1 -i {bridge} -s {source} "
            f"-m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT "
            f"-m comment --comment '{comment}'"
        )
    return drops, logs + accepts + established


def build_rules(policy: EgressPolicy, backend: str) -> list:
    """Candidate rules binding the policy identity to the allowed paths."""
    validate_backend(backend)
    if backend == "iptables":
        drops: list = []
        allows: list = []
        if policy.container_ipv4:
            family_drops, family_allows = _iptables_family(
                policy, "iptables", policy.bridge_interface, policy.container_ipv4,
                policy.allowed_ipv4, policy.dns_servers_ipv4, policy.tcp_ports, policy.udp_ports,
            )
            drops.extend(family_drops)
            allows.extend(family_allows)
        if policy.container_ipv6:
            family_drops, family_allows = _iptables_family(
                policy, "ip6tables", policy.bridge_interface, policy.container_ipv6,
                policy.allowed_ipv6, policy.dns_servers_ipv6, policy.tcp_ports, policy.udp_ports,
            )
            drops.extend(family_drops)
            allows.extend(family_allows)
        # Every source's drop (both families) precedes any allow rule, so no
        # source stays unfiltered at any point of the activation sequence.
        return drops + allows

    chain = f"op_{policy.operation_suffix}"
    table_chain = f"inet pawnlogic_egress {chain}"
    rules = [
        "nft list table inet pawnlogic_egress >/dev/null 2>&1 || "
        "nft add table inet pawnlogic_egress",
        f"nft add chain {table_chain} '{{ type filter hook forward priority -110; }}'",
    ]
    for source in policy.container_ipv4:
        rules.append(
            f"nft add rule {table_chain} ip saddr {source} "
            f"ct state established,related accept"
        )
        for destination in policy.allowed_ipv4:
            for port in policy.tcp_ports:
                rules.append(
                    f"nft add rule {table_chain} ip saddr {source} ip daddr {destination} "
                    f"tcp dport {port} ct state new,established accept"
                )
            for port in policy.udp_ports:
                rules.append(
                    f"nft add rule {table_chain} ip saddr {source} ip daddr {destination} "
                    f"udp dport {port} accept"
                )
        for server in policy.dns_servers_ipv4:
            rules.append(
                f"nft add rule {table_chain} ip saddr {source} ip daddr {server} "
                f"udp dport 53 accept"
            )
        rules.append(
            f"nft add rule {table_chain} ip saddr {source} limit rate 5/minute "
            f"log prefix 'PAWNEGRESS-DENY '"
        )
        rules.append(f"nft add rule {table_chain} ip saddr {source} counter drop")
    for source in policy.container_ipv6:
        rules.append(
            f"nft add rule {table_chain} ip6 saddr {source} "
            f"ct state established,related accept"
        )
        for destination in policy.allowed_ipv6:
            for port in policy.tcp_ports:
                rules.append(
                    f"nft add rule {table_chain} ip6 saddr {source} ip6 daddr {destination} "
                    f"tcp dport {port} ct state new,established accept"
                )
            for port in policy.udp_ports:
                rules.append(
                    f"nft add rule {table_chain} ip6 saddr {source} ip6 daddr {destination} "
                    f"udp dport {port} accept"
                )
        for server in policy.dns_servers_ipv6:
            rules.append(
                f"nft add rule {table_chain} ip6 saddr {source} ip6 daddr {server} "
                f"udp dport 53 accept"
            )
        rules.append(f"nft add rule {table_chain} ip6 saddr {source} counter drop")
    return rules


def conntrack_revocation(policy: EgressPolicy, backend: str) -> list:
    """Delete the operation's flows, scoped to the container's own source
    addresses so other tenants of the pinned destinations are not hit."""
    validate_backend(backend)
    commands = []
    for source in policy.container_ipv4:
        for address in policy.allowed_ipv4 + policy.dns_servers_ipv4:
            commands.append(f"conntrack -D -s {source} -d {address}  # {policy.operation_id}")
    for source in policy.container_ipv6:
        for address in policy.allowed_ipv6 + policy.dns_servers_ipv6:
            commands.append(
                f"conntrack -D -f ipv6 -s {source} -d {address}  # {policy.operation_id}"
            )
    return commands


def revocation_verification(policy: EgressPolicy, backend: str) -> list:
    """Commands that VERIFY flows are gone. The check branches on the query
    itself: a failing or unauthorized query is a containment failure, never
    a silent success."""
    validate_backend(backend)
    commands = []

    def flow_check(source: str, address: str) -> str:
        family = "-f ipv6 " if ":" in source else ""
        return (
            f"if out=$(conntrack -L {family}-s {source} -d {address} 2>/dev/null); then "
            f"if [ -n \"$out\" ]; then echo 'CONTAINMENT FAILURE: flows remain for {address}'; "
            f"else echo 'flows revoked for {address}'; fi; "
            f"else echo 'CONTAINMENT FAILURE: revocation check failed for {address} (query error)'; fi"
            f"  # {policy.operation_id}"
        )

    for source in policy.container_ipv4:
        for address in policy.allowed_ipv4 + policy.dns_servers_ipv4:
            commands.append(flow_check(source, address))
    for source in policy.container_ipv6:
        for address in policy.allowed_ipv6 + policy.dns_servers_ipv6:
            commands.append(flow_check(source, address))
    return commands


def rule_presence_verification(policy: EgressPolicy, backend: str) -> list:
    """Commands that VERIFY the operation's rules are gone after rollback.
    A failing query is a containment failure, never a silent success."""
    validate_backend(backend)
    comment_filter = f"pawnlogic {policy.operation_id} "
    if backend == "iptables":
        return [
            (
                f"if save=$(iptables-save 2>/dev/null); then "
                f"case \"$save\" in *'{comment_filter}'*) "
                f"echo 'CONTAINMENT FAILURE: iptables rules remain for {policy.operation_id}';; "
                f"*) echo 'iptables rules removed';; esac; "
                f"else echo 'CONTAINMENT FAILURE: iptables-save failed (query error)'; fi"
            ),
            (
                f"if save6=$(ip6tables-save 2>/dev/null); then "
                f"case \"$save6\" in *'{comment_filter}'*) "
                f"echo 'CONTAINMENT FAILURE: ip6tables rules remain for {policy.operation_id}';; "
                f"*) echo 'ip6tables rules removed';; esac; "
                f"else echo 'CONTAINMENT FAILURE: ip6tables-save failed (query error)'; fi"
            ),
        ]
    return [
        (
            f"if snapshot=$(nft list table inet pawnlogic_egress 2>/dev/null); then "
            f"case \"$snapshot\" in *'chain op_{policy.operation_suffix} {{'*) "
            f"echo 'CONTAINMENT FAILURE: nft chain remains for {policy.operation_id}';; "
            f"*) echo 'nft chain removed';; esac; "
            f"else echo 'CONTAINMENT FAILURE: nft chain remains or table query failed "
            f"for {policy.operation_id} (query error)'; fi"
        ),
    ]


def rollback_commands(policy: EgressPolicy, backend: str) -> list:
    """Exact inverse of build_rules: only this operation's artifacts.

    iptables rollback rewrites the table from a save snapshot: quiesce
    Docker churn (or hold the xtables lock) while it runs, per ADR 0014.
    nftables chains must be flushed before they can be deleted.
    """
    validate_backend(backend)
    comment_filter = f"pawnlogic {policy.operation_id} "
    verification = (
        revocation_verification(policy, backend)
        + rule_presence_verification(policy, backend)
    )
    if backend == "iptables":
        return [
            f"iptables-save | grep -vF '{comment_filter}' | iptables-restore",
            f"ip6tables-save | grep -vF '{comment_filter}' | ip6tables-restore",
            *verification,
        ]
    return [
        f"nft flush chain inet pawnlogic_egress op_{policy.operation_suffix}",
        f"nft delete chain inet pawnlogic_egress op_{policy.operation_suffix}",
        *verification,
    ]


def dry_run(policy: EgressPolicy, backend: str) -> str:
    """Human-readable activation plan. Contains no execution verbs."""
    validate_backend(backend)
    hooks = IPTABLES_HOOKS if backend == "iptables" else NFTABLES_HOOKS
    lines = [
        f"DRY RUN — host egress helper for operation {policy.operation_id}",
        f"  backend: {backend}",
        f"  hooks: {'; '.join(f'{k}: {v}' for k, v in hooks.items())}",
        f"  container: {policy.container_id[:12]} on network '{policy.network_name}' "
        f"via bridge {policy.bridge_interface}",
        f"  container source snapshot: "
        f"{', '.join(policy.container_ipv4 + policy.container_ipv6)}",
        f"  tcp ports: {', '.join(map(str, policy.tcp_ports)) or '-'}",
        f"  udp ports: {', '.join(map(str, policy.udp_ports)) or '-'}",
        f"  pinned ipv4: {', '.join(policy.allowed_ipv4) or '-'}",
        f"  pinned ipv6: {', '.join(policy.allowed_ipv6) or '-'}",
        f"  dns servers: {', '.join(policy.dns_servers_ipv4 + policy.dns_servers_ipv6) or '-'}",
        "  prerequisites: DOCKER-USER exists for both families (iptables) or nftables support;",
        "  the future helper must deny concurrent activation (one managed operation at a time);",
        "  insertion is drop-first, so the container stays fail-closed during activation and",
        "  pre-existing DOCKER-USER RETURN rules cannot shadow it; metadata/link-local",
        "  destinations are rejected at policy time.",
        "  coverage caveats (see ADR 0014 matrix): host INPUT, same-bridge peers,",
        "  published-port hairpin and embedded-DNS forwarding need the documented",
        "  additional hooks and backend verification before activation.",
        "  rules:",
    ]
    lines.extend(f"    {rule}" for rule in build_rules(policy, backend))
    lines.append("  conntrack revocation on expiry:")
    lines.extend(f"    {cmd}" for cmd in conntrack_revocation(policy, backend))
    lines.append("  revocation verification (remaining flows are a containment failure):")
    lines.extend(f"    {cmd}" for cmd in revocation_verification(policy, backend))
    lines.append("  rollback:")
    lines.extend(f"    {cmd}" for cmd in rollback_commands(policy, backend))
    if backend == "iptables":
        lines.append(
            "  note: save/restore rewrite the table from a snapshot — quiesce Docker"
        )
        lines.append("  churn (or hold the xtables lock) while rollback runs.")
    return "\n".join(lines)
