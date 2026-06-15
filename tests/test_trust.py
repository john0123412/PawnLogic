"""Tests for centralized trust-boundary notices."""

from core import provider_runtime
from core.state import state as runtime_state
from core.trust import (
    BROWSER_SANDBOX_DISABLED,
    TrustLevel,
    subagent_notice,
    trust_notice,
    trust_notice_for,
)


def test_trust_notice_adds_standard_prefix():
    assert trust_notice("example") == "  [Trust Boundary] example"


def test_every_trust_level_has_a_standard_notice():
    for level in TrustLevel:
        assert trust_notice_for(level).startswith("  [Trust Boundary] ")


def test_static_trust_notices_match_existing_user_facing_text():
    assert trust_notice_for(TrustLevel.HOST_SHELL) == (
        "  [Trust Boundary] run_shell executes on the host shell. "
        "Pattern filters are limited and not a sandbox."
    )
    assert trust_notice_for(TrustLevel.CONTAINER_EXEC) == (
        "  [Trust Boundary] Container exec runs arbitrary shell inside the target container."
    )
    assert trust_notice_for(TrustLevel.NETWORK) == (
        "  [Trust Boundary] Browser tools are network-capable and not a host sandbox."
    )
    assert trust_notice_for(TrustLevel.PRIVATE_NETWORK) == (
        "  [Trust Boundary] Private network access is allowed, "
        "but this crosses the local trust boundary."
    )
    assert trust_notice_for(TrustLevel.INSECURE_TRANSPORT) == (
        "  [Trust Boundary] Provider uses plain HTTP. "
        "Requests and API keys are not protected by TLS."
    )
    assert trust_notice_for(TrustLevel.SUBAGENT) == (
        "  [Trust Boundary] delegate_task is a non-isolated sub-agent; "
        "tool side effects are real and run with parent permissions."
    )


def test_named_browser_sandbox_notice_is_stable():
    assert trust_notice(BROWSER_SANDBOX_DISABLED) == (
        "  [Trust Boundary] Chromium sandbox is disabled by explicit config."
    )


def test_subagent_notice_includes_capability_profile():
    assert subagent_notice("read_only") == (
        "  [Trust Boundary] delegate_task is a non-isolated sub-agent; "
        "tool side effects are real and run with parent permissions (capability=read_only)."
    )


def test_insecure_provider_warning_uses_centralized_notice(monkeypatch):
    emitted = []
    monkeypatch.setattr(runtime_state, "user_mode", True)
    monkeypatch.setattr(provider_runtime, "_WARNED_HTTP_PROVIDER_URLS", set())

    provider_runtime.maybe_warn_insecure_provider(
        "http://provider.example/v1",
        emit=emitted.append,
    )

    assert emitted == [trust_notice_for(TrustLevel.INSECURE_TRANSPORT)]
