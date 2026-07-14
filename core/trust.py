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

from dataclasses import dataclass
from enum import Enum

_PREFIX = "  [Trust Boundary] "


class TrustLevel(str, Enum):
    """The permission surface a tool touches when it runs on the local host."""

    LOCAL = "local"  # safe local read/config operations
    HOST_SHELL = "host_shell"  # arbitrary host command execution
    CONTAINER_EXEC = "container_exec"  # arbitrary shell inside a container
    NETWORK = "network"  # outbound network access
    PRIVATE_NETWORK = "private_network"  # reaching private / loopback hosts
    INSECURE_TRANSPORT = "insecure_transport"  # plaintext HTTP (no TLS)
    SUBAGENT = "subagent"  # non-isolated delegated sub-agent


class TrustBoundaryKind(str, Enum):
    """Stable internal names for tool trust-boundary categories."""

    LOCAL = "local"
    HOST_SHELL = "host_shell"
    CONTAINER_EXEC = "container_exec"
    BROWSER_NETWORK = "browser_network"
    PRIVATE_NETWORK = "private_network"
    PLAIN_HTTP = "plain_http"
    DELEGATE = "delegate"


@dataclass(frozen=True)
class TrustBoundary:
    """Internal trust-boundary description used by tool call sites."""

    kind: TrustBoundaryKind
    level: TrustLevel
    message: str

    @property
    def notice(self) -> str:
        """Return the standard prefixed notice for this boundary."""
        return trust_notice(self.message)


# Canonical static boundaries. Message text is kept identical to the strings
# that were previously inlined at each call site.
TRUST_BOUNDARIES: dict[TrustBoundaryKind, TrustBoundary] = {
    TrustBoundaryKind.LOCAL: TrustBoundary(
        TrustBoundaryKind.LOCAL,
        TrustLevel.LOCAL,
        "Local read-only tool. No host shell, network, or destructive side effects.",
    ),
    TrustBoundaryKind.HOST_SHELL: TrustBoundary(
        TrustBoundaryKind.HOST_SHELL,
        TrustLevel.HOST_SHELL,
        "run_shell executes on the host shell. Pattern filters are limited "
        "and not a sandbox.",
    ),
    TrustBoundaryKind.CONTAINER_EXEC: TrustBoundary(
        TrustBoundaryKind.CONTAINER_EXEC,
        TrustLevel.CONTAINER_EXEC,
        "Container exec runs arbitrary shell inside the target container.",
    ),
    TrustBoundaryKind.BROWSER_NETWORK: TrustBoundary(
        TrustBoundaryKind.BROWSER_NETWORK,
        TrustLevel.NETWORK,
        "Browser tools are network-capable and not a host sandbox.",
    ),
    TrustBoundaryKind.PRIVATE_NETWORK: TrustBoundary(
        TrustBoundaryKind.PRIVATE_NETWORK,
        TrustLevel.PRIVATE_NETWORK,
        "Private network access is allowed, but this crosses the local trust boundary."
    ),
    TrustBoundaryKind.PLAIN_HTTP: TrustBoundary(
        TrustBoundaryKind.PLAIN_HTTP,
        TrustLevel.INSECURE_TRANSPORT,
        "Provider uses plain HTTP. Requests and API keys are not protected by TLS."
    ),
    TrustBoundaryKind.DELEGATE: TrustBoundary(
        TrustBoundaryKind.DELEGATE,
        TrustLevel.SUBAGENT,
        "delegate_task is a non-isolated sub-agent; tool side effects are real "
        "and run with parent permissions.",
    ),
}

# Compatibility mapping for existing call sites and tests that still use the
# older permission-surface enum directly.
_LEVEL_TO_BOUNDARY: dict[TrustLevel, TrustBoundaryKind] = {
    boundary.level: kind for kind, boundary in TRUST_BOUNDARIES.items()
}

# Canonical static notice text per level. Kept for compatibility.
TRUST_NOTICES: dict[TrustLevel, str] = {
    boundary.level: boundary.message for boundary in TRUST_BOUNDARIES.values()
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
    return trust_boundary_for(level).notice


def trust_boundary_for(level: TrustLevel) -> TrustBoundary:
    """Return the internal trust boundary for an existing trust level."""
    return TRUST_BOUNDARIES[_LEVEL_TO_BOUNDARY[level]]


def trust_notice_for_boundary(kind: TrustBoundaryKind) -> str:
    """Return the standard notice line for a named trust boundary."""
    return TRUST_BOUNDARIES[kind].notice


def subagent_notice(capability: str) -> str:
    """Return the delegate non-isolated sub-agent notice for a capability profile."""
    base_notice = TRUST_BOUNDARIES[TrustBoundaryKind.DELEGATE].message.removesuffix(".")
    return trust_notice(f"{base_notice} (capability={capability}).")


__all__ = [
    "BROWSER_SANDBOX_DISABLED",
    "TRUST_BOUNDARIES",
    "TRUST_NOTICES",
    "TrustBoundary",
    "TrustBoundaryKind",
    "TrustLevel",
    "subagent_notice",
    "trust_boundary_for",
    "trust_notice",
    "trust_notice_for",
    "trust_notice_for_boundary",
]
