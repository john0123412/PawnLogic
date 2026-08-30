"""Offline tests for the pure Network Policy module."""

from __future__ import annotations

import ipaddress

import pytest

from core.network_policy import (
    NetworkAction,
    NetworkOperation,
    NetworkPolicy,
    NetworkRule,
    normalize_url,
)
from core.operation_policy import OperationAction


def _policy(mapping: dict[str, tuple[str, ...]] | None = None) -> NetworkPolicy:
    calls: list[str] = []
    mapping = mapping or {}

    def resolver(host: str):
        calls.append(host)
        return mapping.get(host, ())

    policy = NetworkPolicy(resolver=resolver)
    policy._test_calls = calls  # type: ignore[attr-defined]
    return policy


def test_normalize_url_canonicalizes_scheme_host_default_port_and_fragment():
    assert normalize_url(" HTTPS://Example.COM:443/path?q=1#secret ") == "https://example.com/path?q=1"
    assert normalize_url("http://[2001:DB8::1]:80/") == "http://[2001:db8::1]/"
    assert normalize_url("http://Example.COM:8080") == "http://example.com:8080/"


@pytest.mark.parametrize(
    "url, rule",
    [
        ("", NetworkRule.MALFORMED_URL),
        ("file:///etc/passwd", NetworkRule.UNSUPPORTED_SCHEME),
        ("http://user:pass@example.com/", NetworkRule.URL_CREDENTIALS),
        ("http://example.com:0/", NetworkRule.INVALID_PORT),
        ("http://example.com:65536/", NetworkRule.INVALID_PORT),
        ("http://[2001:db8::1/", NetworkRule.MALFORMED_URL),
    ],
)
def test_malformed_and_unsafe_url_shapes_deny(url, rule):
    decision = NetworkPolicy().evaluate(NetworkOperation(url=url))
    assert decision.action == NetworkAction.DENY
    assert decision.rule == rule.value


@pytest.mark.parametrize(
    "host, rule",
    [
        ("127.0.0.1", NetworkRule.LOOPBACK),
        ("::1", NetworkRule.LOOPBACK),
        ("169.254.1.1", NetworkRule.LINK_LOCAL),
        ("ff02::1", NetworkRule.MULTICAST),
        ("0.0.0.0", NetworkRule.UNSPECIFIED),
    ],
)
def test_special_ip_ranges_deny_for_ipv4_and_ipv6(host, rule):
    decision = NetworkPolicy().evaluate(NetworkOperation(scheme="http", host=host))
    assert decision.action == NetworkAction.DENY
    assert decision.rule == rule.value


@pytest.mark.parametrize(
    "host",
    ["localhost", "service.localhost", "LOCALHOST.", "Service.LocalHost."],
)
def test_localhost_namespace_denies_before_dns(host):
    calls: list[str] = []

    def resolver(value: str):
        calls.append(value)
        raise AssertionError("localhost namespace must not reach DNS")

    decision = NetworkPolicy(resolver=resolver).evaluate(
        NetworkOperation(url=f"http://{host}:8080/")
    )

    assert decision.action == NetworkAction.DENY
    assert decision.rule == NetworkRule.LOOPBACK.value
    assert calls == []


@pytest.mark.parametrize("host", ["metadata", "metadata.google.internal", "metadata.aliyun.com", "service.internal"])
def test_cloud_metadata_and_internal_hosts_deny(host):
    decision = NetworkPolicy().evaluate(NetworkOperation(scheme="http", host=host))
    assert decision.action == NetworkAction.DENY
    assert decision.rule == NetworkRule.CLOUD_METADATA.value


def test_private_literal_requires_authorization_and_noninteractive_fails_closed():
    policy = NetworkPolicy()
    operation = NetworkOperation(url="http://192.168.1.10:8080", interactive=True)
    assert policy.evaluate(operation).action == NetworkAction.CONFIRM
    assert policy.evaluate(operation).rule == NetworkRule.PRIVATE_NETWORK.value
    denied = policy.evaluate(
        NetworkOperation(url=operation.url, interactive=False, explicit_authorization=False)
    )
    assert denied.action == NetworkAction.DENY


def test_explicitly_authorized_local_lab_is_allowed():
    decision = NetworkPolicy().evaluate(
        NetworkOperation(
            url="http://192.168.1.10:8080/lab",
            explicit_authorization=True,
            authorized_targets=("192.168.1.0/24",),
            interactive=False,
        )
    )
    assert decision.action == NetworkAction.ALLOW
    assert decision.rule == NetworkRule.PRIVATE_NETWORK_AUTHORIZED.value


def test_private_dns_result_is_evaluated_without_real_dns():
    policy = _policy({"lab.example": ("10.0.0.8",)})
    decision = policy.evaluate(NetworkOperation(url="https://lab.example/"))
    assert decision.action == NetworkAction.CONFIRM
    assert decision.rule == NetworkRule.PRIVATE_NETWORK.value
    assert policy._test_calls == ["lab.example"]  # type: ignore[attr-defined]


def test_dns_result_special_range_deny_even_with_authorization():
    policy = _policy({"evil.example": ("127.0.0.1",)})
    decision = policy.evaluate(
        NetworkOperation(url="https://evil.example/", explicit_authorization=True)
    )
    assert decision.action == NetworkAction.DENY
    assert decision.rule == NetworkRule.LOOPBACK.value


def test_dns_result_cloud_metadata_ip_has_dedicated_rule():
    policy = _policy({"metadata-alias.example": ("169.254.169.254",)})
    decision = policy.evaluate(NetworkOperation(url="https://metadata-alias.example/"))
    assert decision.action == NetworkAction.DENY
    assert decision.rule == NetworkRule.CLOUD_METADATA.value


def test_hostname_authorization_can_match_resolved_private_network():
    policy = _policy({"lab.example": ("10.20.30.40",)})
    decision = policy.evaluate(
        NetworkOperation(
            url="https://lab.example/",
            explicit_authorization=True,
            authorized_targets=("10.0.0.0/8",),
            interactive=False,
        )
    )
    assert decision.action == NetworkAction.ALLOW
    assert decision.rule == NetworkRule.PRIVATE_NETWORK_AUTHORIZED.value


def test_redirect_each_hop_is_normalized_and_resolved_again():
    policy = _policy({"public.example": ("93.184.216.34",), "lab.example": ("10.0.0.9",)})
    operation = NetworkOperation(
        url="https://PUBLIC.example/start",
        redirect_chain=("https://lab.example/final",),
        explicit_authorization=True,
        authorized_targets=("lab.example", "public.example"),
        interactive=False,
    )
    decision = policy.evaluate(operation)
    assert decision.action == NetworkAction.ALLOW
    assert decision.normalized_target == "https://lab.example/final"
    assert policy._test_calls == ["public.example", "lab.example"]  # type: ignore[attr-defined]


def test_redirect_to_private_target_is_denied_in_noninteractive_mode_without_scope_match():
    policy = _policy({"public.example": ("93.184.216.34",), "lab.example": ("10.0.0.9",)})
    decision = policy.evaluate(
        NetworkOperation(
            url="https://public.example/",
            redirect_chain=("https://lab.example/",),
            interactive=False,
            explicit_authorization=True,
            authorized_targets=("public.example",),
        )
    )
    assert decision.action == NetworkAction.DENY
    assert decision.rule == NetworkRule.PRIVATE_NETWORK.value
    assert decision.normalized_target == "https://lab.example/"


def test_active_probe_requires_confirmation_unless_authorized():
    decision = NetworkPolicy().evaluate(
        NetworkOperation(url="https://example.com/", active_probe=True)
    )
    assert decision.action == NetworkAction.DENY
    assert decision.rule == NetworkRule.ENGAGEMENT_SCOPE_REQUIRED.value
    allowed = NetworkPolicy().evaluate(
        NetworkOperation(
            url="https://example.com/",
            active_probe=True,
            explicit_authorization=True,
            engagement_scope="engagement-1",
            scope_valid=True,
        )
    )
    assert allowed.action == NetworkAction.ALLOW


@pytest.mark.parametrize(
    ("engagement_scope", "scope_valid"),
    [(None, False), ("expired-engagement", False)],
)
def test_authorized_private_active_probe_requires_valid_engagement_scope(
    engagement_scope, scope_valid
):
    decision = NetworkPolicy().evaluate(
        NetworkOperation(
            url="http://192.168.1.10:8080/lab",
            active_probe=True,
            explicit_authorization=True,
            authorized_targets=("192.168.1.0/24",),
            engagement_scope=engagement_scope,
            scope_valid=scope_valid,
            interactive=False,
        )
    )

    assert decision.action == NetworkAction.DENY
    assert decision.rule == NetworkRule.ENGAGEMENT_SCOPE_REQUIRED.value


def test_network_capability_without_target_uses_explicit_authorization_gate():
    policy = NetworkPolicy()
    denied = policy.evaluate(
        NetworkOperation(
            action="container_network",
            capability_only=True,
            interactive=False,
        )
    )
    allowed = policy.evaluate(
        NetworkOperation(
            action="container_network",
            capability_only=True,
            interactive=False,
            explicit_authorization=True,
        )
    )

    assert denied.action == NetworkAction.DENY
    assert denied.rule == NetworkRule.NETWORK_CAPABILITY_AUTHORIZATION.value
    assert allowed.action == NetworkAction.ALLOW


def test_invalid_injected_dns_address_denies_without_network_access():
    policy = _policy({"example.com": ("not-an-ip",)})
    decision = policy.evaluate(NetworkOperation(url="https://example.com/"))
    assert decision.action == NetworkAction.DENY
    assert decision.rule == NetworkRule.DNS_RESULT_INVALID.value


def test_invalid_injected_dns_result_type_fails_closed():
    policy = NetworkPolicy(resolver=lambda _: None)  # type: ignore[return-value]
    decision = policy.evaluate(NetworkOperation(url="https://example.com/"))
    assert decision.action == NetworkAction.DENY
    assert decision.rule == NetworkRule.DNS_RESULT_INVALID.value


def test_ipv4_mapped_ipv6_loopback_is_denied():
    policy = _policy({"mapped.example": ("::ffff:127.0.0.1",)})
    decision = policy.evaluate(NetworkOperation(url="https://mapped.example/"))
    assert decision.action == NetworkAction.DENY
    assert decision.rule == NetworkRule.LOOPBACK.value


def test_resolved_address_inputs_are_supported_for_ipv6():
    decision = NetworkPolicy().evaluate(
        NetworkOperation(
            url="https://example.com/",
            resolved_addresses=(str(ipaddress.ip_address("2001:4860:4860::8888")),),
        )
    )
    assert decision.action == NetworkAction.ALLOW
    assert decision.normalized_target == "https://example.com/"


def test_operation_action_enum_is_reusable_without_importing_shell_classifier():
    assert NetworkAction is OperationAction
    assert NetworkOperation(action="fetch").action == "fetch"


def test_resolved_ips_legacy_keyword_is_mirrored():
    operation = NetworkOperation(url="https://example.com/", resolved_ips=("1.1.1.1",))
    assert operation.resolved_addresses == operation.resolved_ips == ("1.1.1.1",)


def test_decision_is_serializable_and_exposes_matched_rule_alias():
    decision = NetworkPolicy().evaluate(NetworkOperation(url="https://example.com"))
    assert decision.matched_rule == decision.rule
    assert decision.to_dict()["normalized_target"] == "https://example.com/"
