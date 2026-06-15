"""Centralized trust-boundary notices and permission levels.

PawnLogic executes tools on the local host with the invoking user's own
permissions. It is NOT a security sandbox: pattern filters, container
boundaries, and capability profiles reduce accidents but do not contain a
determined attacker. This module is the single source of truth for the
user-facing trust-boundary phrasing, so the shell / browser / fetch / docker /
delegate notices stay consistent.

Call sites keep their own display-mode gating (these notices are shown in
user-friendly mode; debug mode additionally surfaces low-level details). This
module only owns the wording and the permission taxonomy, not when to print.
"""

from __future__ import annotations

from enum import Enum

_PREFIX = "  [Trust Boundary] "


class TrustLevel(str, Enum):
    """The permission surface a tool touches when it runs on the local host."""

    HOST_SHELL = "host_shell"  # arbitrary host command execution
    CONTAINER_EXEC = "container_exec"  # arbitrary shell inside a container
    NETWORK = "network"  # outbound network access
    PRIVATE_NETWORK = "private_network"  # reaching private / loopback hosts
    INSECURE_TRANSPORT = "insecure_transport"  # plaintext HTTP (no TLS)
    SUBAGENT = "subagent"  # non-isolated delegated sub-agent


# Canonical static notice text per level. Kept identical to the strings that
# were previously inlined at each call site.
TRUST_NOTICES: dict[TrustLevel, str] = {
    TrustLevel.HOST_SHELL: (
        "run_shell executes on the host shell. Pattern filters are limited "
        "and not a sandbox."
    ),
    TrustLevel.CONTAINER_EXEC: (
        "Container exec runs arbitrary shell inside the target container."
    ),
    TrustLevel.NETWORK: "Browser tools are network-capable and not a host sandbox.",
    TrustLevel.PRIVATE_NETWORK: (
        "Private network access is allowed, but this crosses the local trust boundary."
    ),
    TrustLevel.INSECURE_TRANSPORT: (
        "Provider uses plain HTTP. Requests and API keys are not protected by TLS."
    ),
    TrustLevel.SUBAGENT: (
        "delegate_task is a non-isolated sub-agent; tool side effects are real "
        "and run with parent permissions."
    ),
}

# Named static notices that do not map one-to-one to a level.
BROWSER_SANDBOX_DISABLED = "Chromium sandbox is disabled by explicit config."


def trust_notice(message: str) -> str:
    """Return a trust-boundary notice line with the standard prefix.

    Use for dynamic notices (e.g. a resolved hostname or capability profile).
    """
    return f"{_PREFIX}{message}"


def trust_notice_for(level: TrustLevel) -> str:
    """Return the standard notice line for a known trust level."""
    return trust_notice(TRUST_NOTICES[level])


def subagent_notice(capability: str) -> str:
    """Return the delegate non-isolated sub-agent notice for a capability profile."""
    base_notice = TRUST_NOTICES[TrustLevel.SUBAGENT].removesuffix(".")
    return trust_notice(f"{base_notice} (capability={capability}).")


__all__ = [
    "BROWSER_SANDBOX_DISABLED",
    "TRUST_NOTICES",
    "TrustLevel",
    "subagent_notice",
    "trust_notice",
    "trust_notice_for",
]
