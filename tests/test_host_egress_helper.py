"""Simulated backend tests for the host egress helper review package.

The helper never executes anything; these tests pin the artifacts an owner
would review before authorizing activation (ADR 0014, plan §5).
"""

import subprocess
import shlex

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
        conntrack_zone=42,
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


def _run_stubbed_shell(command: str, stubs: str) -> subprocess.CompletedProcess:
    """Run one generated query with shell functions standing in for binaries."""
    script = f"set -o pipefail\n{stubs}\n{command}\n"
    return subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )


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


@pytest.mark.parametrize("field", ["container_ipv6", "allowed_ipv6", "dns_servers_ipv6"])
def test_policy_rejects_ipv6_zone_identifiers_in_command_artifacts(field):
    # ipaddress accepts arbitrary scope strings; interpolating such a scope
    # into a reviewed shell artifact must never introduce command syntax.
    with pytest.raises(ValueError, match="scope"):
        make_policy(**{field: ("2001:db8::7%$(id)",)})


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


def test_nft_rules_bind_every_packet_match_to_the_exact_bridge():
    rules = build_rules(make_policy(bridge_interface="br-other.42"), "nftables")
    packets = [shlex.split(rule) for rule in rules if rule.startswith("nft add rule")]
    assert packets
    for argv in packets:
        assert "iifname" in argv
        assert argv[argv.index("iifname") + 1] == '"br-other.42"'


@pytest.mark.parametrize("zone", [None, True, False, -1, 65536, "42", 1.5])
def test_conntrack_zone_must_be_an_explicit_numeric_policy_binding(zone):
    with pytest.raises(ValueError, match="conntrack_zone"):
        make_policy(conntrack_zone=zone)


def test_conntrack_zone_has_no_implicit_default():
    with pytest.raises(TypeError, match="conntrack_zone"):
        EgressPolicy(operation_id="pawn-op-test", container_id=CONTAINER_ID,
                     network_name="pawn_test", bridge_interface="br-test")


@pytest.mark.parametrize("zone", [0, 65535])
def test_explicit_conntrack_zone_boundaries_are_preserved(zone):
    policy = make_policy(conntrack_zone=zone)
    commands = conntrack_revocation(policy, "iptables") + revocation_verification(policy, "iptables")
    assert commands and all(f"--orig-zone {zone}" in command for command in commands)
    assert f"conntrack zone: {zone}" in dry_run(policy, "iptables")


@pytest.mark.parametrize("backend", ["iptables", "nftables"])
def test_revocation_covers_unapproved_outbound_flows_without_crossing_zone(backend):
    policy = make_policy()
    commands = conntrack_revocation(policy, backend)
    assert len(commands) == 2
    for command, family, source in zip(commands, ("ipv4", "ipv6"), ("198.18.0.7", "fd12::7"), strict=True):
        argv = shlex.split(command, comments=True)
        assert argv == ["conntrack", "-D", "-f", family, "--orig-zone", "42", "-s", source]
    check = revocation_verification(policy, backend)[0]
    result = _run_stubbed_shell(check, """
conntrack() {
    [ "$*" = '-L -f ipv4 --orig-zone 42 -s 198.18.0.7' ] || return 2
    printf '%s\\n' 'tcp ESTABLISHED src=198.18.0.7 dst=198.51.100.99 zone=42'
}
""")
    assert "CONTAINMENT FAILURE: flows remain" in result.stdout
    assert "flows revoked" not in result.stdout


@pytest.mark.parametrize("family,source", [("ipv4", "198.18.0.7"), ("ipv6", "fd12::7")])
@pytest.mark.parametrize("state", ["empty", "remaining", "error"])
def test_revocation_query_checks_exact_original_zone_and_all_destinations(family, source, state):
    index = 0 if family == "ipv4" else 1
    command = revocation_verification(make_policy(), "iptables")[index]
    behavior = {
        "empty": "printf '%s\\n' '0 flow entries' >&2; return 0",
        "remaining": "printf '%s\\n' 'tcp ESTABLISHED remaining'; return 0",
        "error": "return 1",
    }[state]
    stub = (
        "conntrack() { "
        f"[ \"$*\" = '-L -f {family} --orig-zone 42 -s {source}' ] || return 2; "
        + behavior + "; }"
    )
    result = _run_stubbed_shell(command, stub)
    assert ("flows revoked" in result.stdout) is (state == "empty")
    assert ("CONTAINMENT FAILURE" in result.stdout) is (state != "empty")


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


@pytest.mark.parametrize("backend", ["iptables", "nftables"])
def test_unpinned_established_original_traffic_has_no_blanket_allow(backend):
    # A socket opened before activation remains ESTABLISHED in ORIGINAL
    # direction. State alone must not let it bypass destination enforcement.
    rules = build_rules(make_policy(), backend)
    broad = [r for r in rules if "established,related" in r.lower()]
    assert broad
    for rule in broad:
        if backend == "iptables":
            assert "--ctdir REPLY" in rule
        else:
            assert "ct direction reply" in rule


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


def test_policy_hard_denies_link_local_and_metadata_destinations():
    # ADR 0014 row 9: metadata/link-local addresses are never allowed into a
    # policy allowlist — including IPv4-mapped spellings.
    for bad in ("169.254.169.254", "169.254.1.1", "fe80::1", "fd00:ec2::254"):
        with pytest.raises(ValueError, match="hard-denied"):
            make_policy(allowed_ipv4=(bad,) if bad.count(":") == 0 else (),
                        allowed_ipv6=() if bad.count(":") == 0 else (bad,))
    with pytest.raises(ValueError, match="hard-denied"):
        make_policy(allowed_ipv6=("::ffff:169.254.169.254",))
    with pytest.raises(ValueError, match="hard-denied"):
        make_policy(dns_servers_ipv4=("169.254.169.254",))


@pytest.mark.parametrize(
    ("field", "address"),
    [
        ("allowed_ipv4", "100.100.100.200"),
        ("allowed_ipv6", "::ffff:100.100.100.200"),
        ("dns_servers_ipv4", "100.100.100.200"),
        ("dns_servers_ipv6", "::ffff:100.100.100.200"),
    ],
)
def test_policy_hard_denies_all_mapped_metadata_allowlist_fields(field, address):
    overrides = {field: (address,)}
    if field == "allowed_ipv4":
        overrides["allowed_ipv6"] = ("2001:db8::7",)
    elif field == "allowed_ipv6":
        overrides["allowed_ipv4"] = ("203.0.113.7",)
    with pytest.raises(ValueError, match="hard-denied"):
        make_policy(**overrides)


def test_policy_hard_denies_expanded_mapped_metadata_in_every_allowlist_family():
    # The mapped form can also be written with an expanded IPv6 tail; it must
    # classify by its effective IPv4 address in both destination and DNS fields.
    expanded = "0:0:0:0:0:ffff:6464:64c8"
    for field, address in (
        ("allowed_ipv4", "100.100.100.200"),
        ("allowed_ipv6", expanded),
        ("dns_servers_ipv4", "100.100.100.200"),
        ("dns_servers_ipv6", expanded),
    ):
        overrides = {field: (address,)}
        if field.endswith("ipv4"):
            overrides["allowed_ipv6"] = ("2001:db8::7",)
        else:
            overrides["allowed_ipv4"] = ("203.0.113.7",)
        with pytest.raises(ValueError, match="hard-denied"):
            make_policy(**overrides)


def test_iptables_inserts_drop_first_so_preexisting_return_cannot_shadow():
    # Appended (-A) rules may land after an owner's RETURN rule in
    # DOCKER-USER and become dead code. The artifact must insert at the top
    # in reverse order, and every source's DROP (both families) must precede
    # any allow rule so no source stays unfiltered during activation.
    policy = make_policy()
    rules = build_rules(policy, "iptables")
    assert all("-A DOCKER-USER" not in r for r in rules)
    assert "-I DOCKER-USER 1" in rules[0] and "-j DROP" in rules[0]
    assert "ESTABLISHED,RELATED" in rules[-1] and "-I DOCKER-USER 1" in rules[-1]
    last_drop = max(i for i, r in enumerate(rules) if "-j DROP" in r)
    first_accept = min(i for i, r in enumerate(rules) if "-j ACCEPT" in r)
    assert last_drop < first_accept
    # Every rule still carries the operation and container identity.
    for rule in rules:
        assert "pawn-op-test0001" in rule
        assert "-s 198.18.0.7" in rule or "-s fd12::7" in rule


def test_nftables_rollback_flushes_the_chain_before_deleting():
    # `nft delete chain` fails while the chain still holds rules.
    rollback = rollback_commands(make_policy(), "nftables")
    flush_index = next(i for i, c in enumerate(rollback) if "flush chain" in c)
    delete_index = next(i for i, c in enumerate(rollback) if "delete chain" in c)
    assert flush_index < delete_index


def test_verification_distinguishes_query_failure_from_revoked():
    # A failing or unauthorized query must NOT be reported as success.
    flow_checks = revocation_verification(make_policy(), "iptables")
    for command in flow_checks:
        assert "check failed" in command, command
        # The conflated `grep -q . && echo ok || echo done` pattern reports
        # query errors as success; the artifact must branch on the query.
        assert "| grep -q . && echo" not in command
    presence = rule_presence_verification(make_policy(), "iptables")
    for command in presence:
        assert "query error" in command or "check failed" in command, command


def test_nft_chain_query_failure_is_not_reported_as_removed():
    command = rule_presence_verification(make_policy(), "nftables")[0]
    result = _run_stubbed_shell(
        command,
        """
nft() {
    if [ "$1" = list ] && [ "$2" = chain ]; then return 1; fi
    if [ "$1" = list ] && [ "$2" = tables ]; then
        printf '%s\\n' 'table inet pawnlogic_egress'
        return 0
    fi
    return 1
}
""",
    )
    assert "CONTAINMENT FAILURE" in result.stdout
    assert "chain removed" not in result.stdout


def test_nft_successful_full_table_without_target_chain_reports_removed():
    command = rule_presence_verification(make_policy(), "nftables")[0]
    result = _run_stubbed_shell(
        command,
        """
nft() {
    if [ "$1" = list ] && [ "$2" = table ]; then
        printf '%s\\n' 'table inet pawnlogic_egress {' \
            '    chain op_other {' '    }' '}'
        return 0
    fi
    return 1
}
""",
    )
    assert "nft chain removed" in result.stdout
    assert "CONTAINMENT FAILURE" not in result.stdout


def test_iptables_presence_query_drains_all_matches_under_pipefail():
    command = rule_presence_verification(make_policy(), "iptables")[0]
    result = _run_stubbed_shell(
        command,
        """
iptables-save() {
    i=0
    while [ "$i" -lt 4096 ]; do
        printf '%s\\n' "-A DOCKER-USER -m comment --comment 'pawnlogic pawn-op-test0001 abc'"
        i=$((i + 1))
    done
    return 0
}
""",
    )
    assert "CONTAINMENT FAILURE" in result.stdout
    assert "rules removed" not in result.stdout


def test_iptables_presence_query_error_is_containment_failure():
    stubs = """
iptables-save() { return 1; }
ip6tables-save() { return 1; }
"""
    for command in rule_presence_verification(make_policy(), "iptables"):
        result = _run_stubbed_shell(command, stubs)
        assert "CONTAINMENT FAILURE" in result.stdout
        assert "rules removed" not in result.stdout


@pytest.mark.parametrize("chain,present", [("op_test0001", True), ("op_test00012", False)])
def test_nft_presence_matches_complete_chain_identifier(chain, present):
    command = rule_presence_verification(make_policy(), "nftables")[0]
    result = _run_stubbed_shell(
        command,
        "nft() { printf '%s\\n' 'table inet pawnlogic_egress {' "
        + f"'    chain {chain} {{' "
        + "'    }' '}'; }",
    )
    assert ("CONTAINMENT FAILURE" in result.stdout) is present
    assert ("chain removed" in result.stdout) is not present


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
    assert any("ct state established,related ct direction reply accept" in r for r in rules), (
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


def test_conntrack_revocation_is_zone_and_source_scoped():
    commands = conntrack_revocation(make_policy(), "iptables")
    assert any("conntrack -D -f ipv4 --orig-zone 42 -s 198.18.0.7" in c for c in commands)
    assert any("conntrack -D -f ipv6 --orig-zone 42 -s fd12::7" in c for c in commands)
    assert all("pawn-op-test0001" in c for c in commands)


def test_revocation_and_rule_presence_are_verified():
    flow_checks = revocation_verification(make_policy(), "iptables")
    assert flow_checks
    for command in flow_checks:
        assert "CONTAINMENT FAILURE" in command or "flows revoked" in command
    assert any("--orig-zone 42 -s 198.18.0.7" in c for c in flow_checks)
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
