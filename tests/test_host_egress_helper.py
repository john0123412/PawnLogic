"""Simulated backend tests for the host egress helper review package.

The helper never executes anything; these tests pin the artifacts an owner
would review before authorizing activation (ADR 0014, plan §5).
"""

import pytest

from tools.host_egress_helper import (
    EgressPolicy,
    build_rules,
    conntrack_revocation,
    dry_run,
    revocation_verification,
    rollback_commands,
    rule_presence_verification,
    validate_backend,
)

CONTAINER_ID = "abcdef1234567890" * 4


def make_policy(**overrides):
    base = dict(
        operation_id="pawn-op-test0001",
        container_id=CONTAINER_ID,
        network_name="pawn_bridge_x",
        bridge_interface="br-abc123",
        container_ipv4=("198.18.0.7",),
        container_ipv6=("fd12::7",),
        allowed_ipv4=("203.0.113.7",),
        allowed_ipv6=("2001:db8::7",),
        tcp_ports=(443, 80),
        udp_ports=(5353,),
        dns_servers_ipv4=("203.0.113.53",),
        dns_servers_ipv6=("2001:db8::53",),
    )
    base.update(overrides)
    return EgressPolicy(**base)


def test_unknown_backend_denies_activation_without_fallback():
    with pytest.raises(ValueError, match="activation denied"):
        build_rules(make_policy(), "ufw")
    with pytest.raises(ValueError, match="activation denied"):
        dry_run(make_policy(), "")
    with pytest.raises(ValueError, match="activation denied"):
        rollback_commands(make_policy(), "firewalld")
    assert validate_backend("iptables") == "iptables"
    assert validate_backend("nftables") == "nftables"


def test_policy_schema_rejects_ambiguous_identity_and_destinations():
    with pytest.raises(ValueError, match="not a numeric address"):
        make_policy(allowed_ipv4=("203.0.113.0/24",))
    with pytest.raises(ValueError, match="not a numeric address"):
        make_policy(allowed_ipv4=("999.999.999.999",))
    with pytest.raises(ValueError, match="not IPv4"):
        make_policy(allowed_ipv4=("2001:db8::7",))
    with pytest.raises(ValueError, match="required"):
        make_policy(bridge_interface="")
    with pytest.raises(ValueError, match="unsupported characters"):
        make_policy(bridge_interface="br-x; rm -rf")
    with pytest.raises(ValueError, match="pawn-op-"):
        make_policy(operation_id="freeform-id")
    with pytest.raises(ValueError, match="pawn-op-"):
        make_policy(operation_id="pawn-op-BAD ID")
    with pytest.raises(ValueError, match="without destinations"):
        make_policy(allowed_ipv4=(), allowed_ipv6=())
    with pytest.raises(ValueError, match="address snapshot"):
        make_policy(container_ipv4=(), container_ipv6=())
    with pytest.raises(ValueError, match="port"):
        make_policy(tcp_ports=(0,))


def test_iptables_rules_bind_network_and_container_identity():
    rules = build_rules(make_policy(), "iptables")
    assert rules
    for rule in rules:
        assert "pawn-op-test0001" in rule
        assert CONTAINER_ID[:12] in rule
        assert "pawn_bridge_x" in rule
        # Traffic reaches FORWARD via the bridge, never the veth, and every
        # rule is scoped to the container's own source addresses.
        assert "-i br-abc123" in rule
        assert "-s 198.18.0.7" in rule or "-s fd12::7" in rule


def test_iptables_rules_cover_both_families_and_fail_closed():
    rules = build_rules(make_policy(), "iptables")
    v4 = [r for r in rules if r.startswith("iptables ")]
    v6 = [r for r in rules if r.startswith("ip6tables ")]
    assert v4 and v6
    assert any("203.0.113.7" in r and "--dport 443" in r and "-j ACCEPT" in r for r in v4)
    assert any("2001:db8::7" in r and "--dport 443" in r and "-j ACCEPT" in r for r in v6)
    assert any("--dport 5353" in r for r in v4), "udp ports must appear for ipv4"
    assert any("--dport 5353" in r for r in v6), "udp ports must appear for ipv6"
    assert any("ESTABLISHED,RELATED" in r and "-j ACCEPT" in r for r in v4)
    assert any("-j DROP" in r for r in v4), "uncovered v4 paths must fail closed"
    assert any("-j DROP" in r for r in v6), "uncovered v6 paths must fail closed"
    # Pinned DNS servers are only ever allowed on udp/53.
    dns_pinned = [r for r in rules if "203.0.113.53" in r or "2001:db8::53" in r]
    assert dns_pinned
    assert all("-p udp --dport 53" in r for r in dns_pinned)
    # Every ACCEPT is scoped to the container's own source addresses; nothing
    # off-scope (e.g. 198.51.100.1) is ever accepted.
    accepts = [r for r in rules if "-j ACCEPT" in r]
    assert accepts
    assert all("-s 198.18.0.7" in r or "-s fd12::7" in r for r in accepts)


def test_multi_address_snapshots_emit_one_rule_per_source():
    policy = make_policy(
        container_ipv4=("198.18.0.7", "198.18.0.8"),
        container_ipv6=("fd12::7", "fd12::8"),
    )
    rules = build_rules(policy, "iptables")
    for rule in rules:
        if rule.startswith("iptables "):
            assert "-s 198.18.0.7" in rule or "-s 198.18.0.8" in rule
            assert "|" not in rule, "pipe-joined source lists are invalid xtables syntax"
    drops = [r for r in rules if "-j DROP" in r]
    assert len(drops) == len(policy.container_ipv4) + len(policy.container_ipv6)
    nft = build_rules(policy, "nftables")
    assert sum(1 for r in nft if r.startswith("nft add rule") and "198.18.0.7" in r) > 0
    assert sum(1 for r in nft if r.startswith("nft add rule") and "198.18.0.8" in r) > 0


def test_nftables_uses_per_operation_chain_in_an_owner_table():
    rules = build_rules(make_policy(), "nftables")
    joined = "\n".join(rules)
    assert "table inet pawnlogic_egress" in joined
    assert "chain inet pawnlogic_egress op_test0001" in joined
    assert "DOCKER" not in joined
    # One verdict per command: terminal rules end in exactly one verdict; the
    # only non-terminal statement is the logging rule.
    for rule in rules:
        if rule.startswith("nft add rule"):
            ok = rule.rstrip().endswith(("accept", "drop")) or "log prefix" in rule
            assert ok, f"unexpected rule shape: {rule}"
            assert rule.count(" accept") <= 1 and not rule.rstrip().endswith("accept accept")
    assert any("counter drop" in r for r in rules)
    assert any("udp dport 5353" in r for r in rules), "udp ports must appear for nftables"
    assert any("ct state established,related accept" in r for r in rules), (
        "published-port replies must keep flowing on nftables too"
    )
    assert any(
        r.startswith("nft list table inet pawnlogic_egress")
        for r in rules
    ), "table creation must be idempotent across operations"


def test_dry_run_discloses_plan_and_caveats_without_activation():
    text = dry_run(make_policy(), "iptables")
    assert text.startswith("DRY RUN")
    assert "coverage caveats" in text
    assert "host INPUT" in text and "same-bridge" in text
    assert "one managed operation at a time" in text
    assert "revocation verification" in text
    assert "rollback:" in text
    assert "pinned ipv4: 203.0.113.7" in text


def test_conntrack_revocation_is_source_scoped():
    commands = conntrack_revocation(make_policy(), "iptables")
    assert any("conntrack -D -s 198.18.0.7 -d 203.0.113.7" in c for c in commands)
    assert any("conntrack -D -f ipv6 -s fd12::7 -d 2001:db8::7" in c for c in commands)
    assert all("pawn-op-test0001" in c for c in commands)


def test_revocation_and_rule_presence_are_verified():
    flow_checks = revocation_verification(make_policy(), "iptables")
    assert flow_checks
    for command in flow_checks:
        assert "CONTAINMENT FAILURE" in command or "flows revoked" in command
    assert any("198.18.0.7" in c and "203.0.113.7" in c for c in flow_checks)
    presence = rule_presence_verification(make_policy(), "iptables")
    assert any("rules remain" in c for c in presence)
    assert any("rules removed" in c for c in presence)
    nft_presence = rule_presence_verification(make_policy(), "nftables")
    assert any("chain remains" in c for c in nft_presence)


def test_rollback_removes_only_this_operation():
    policy = make_policy()
    rollback = rollback_commands(policy, "iptables")
    assert any(f"grep -vF 'pawnlogic {policy.operation_id} '" in c for c in rollback)
    assert any("iptables-restore" in c for c in rollback)
    assert any("ip6tables-restore" in c for c in rollback)
    assert any("conntrack -L" in c for c in rollback), "rollback must verify revocation"
    nft = rollback_commands(policy, "nftables")
    assert any("delete chain inet pawnlogic_egress op_test0001" in c for c in nft)
    assert not any("delete table" in c for c in nft), "rollback must stay per-operation"
    assert any("conntrack -L" in c for c in nft)
