"""Read-only preflight for PawnLogic-labelled containers.

Implements the legacy-container report from
docs/plans/container-boundary-followups.md §4: identify running
PawnLogic-labelled containers that still have network access and explain
that enabling an operator scope does not quarantine them. The report is
pure (classification plus text); the caller supplies docker-py objects and
the tool layer never mutates a container here. Missing or ambiguous daemon
state is reported as `unknown`, which is treated as needing attention, not
as safe.
"""

from collections.abc import Iterable
from typing import Any

PAWN_LABEL = "pawn=true"

# Classifications that mean the container can still send network traffic.
RISKY_NETWORK_KINDS = frozenset({"bridge", "host", "other", "unknown"})


def classify_container_network(attrs: Any) -> str:
    """
    Classify a container's actual network membership from its attrs:
    `host` (host network mode), `bridge` (default bridge endpoint),
    `other` (user-defined network attachment), `none` (offline), or
    `unknown` (missing/malformed daemon state — never treated as safe).
    """
    if not isinstance(attrs, dict):
        return "unknown"
    settings = attrs.get("NetworkSettings")
    if not isinstance(settings, dict):
        return "unknown"
    networks = settings.get("Networks")
    if not isinstance(networks, dict):
        return "unknown"
    host_config = attrs.get("HostConfig")
    mode = host_config.get("NetworkMode") if isinstance(host_config, dict) else None
    # A host-mode container cannot gain additional attachments, so the
    # explicit mode wins; running host containers also show a live "host"
    # endpoint with a populated NetworkID.
    if mode == "host" or any(
        name == "host" and isinstance(net, dict) and net.get("NetworkID")
        for name, net in networks.items()
    ):
        return "host"
    attached = sorted(
        name
        for name, net in networks.items()
        if name not in ("none", "host") and isinstance(net, dict) and net.get("NetworkID")
    )
    if "bridge" in attached:
        return "bridge"
    if attached:
        return "other"
    offline = any(
        name == "none" and isinstance(net, dict) and net.get("NetworkID")
        for name, net in networks.items()
    )
    return "none" if offline else "unknown"


def collect_network_entries(running: Iterable[Any]) -> list:
    """
    Inspect docker-py container objects read-only and build the report
    entries. A container whose state cannot be read is reported as unknown,
    never as safe.
    """
    entries: list = []
    for ctr in running:
        try:
            ctr.reload()
            entries.append((ctr.name, ctr.status, classify_container_network(ctr.attrs)))
        except Exception:
            entries.append((getattr(ctr, "name", "?"), "unknown", "unknown"))
    return entries


def preflight_report(client: Any) -> str:
    """
    Full read-only report for a docker client: list PawnLogic-labelled
    running containers, classify their networks, and explain that an
    operator scope never quarantines them. A daemon listing failure is an
    explicit error, not a clean report.
    """
    try:
        running = client.containers.list(
            filters={"label": PAWN_LABEL}, ignore_removed=True
        )
    except Exception as exc:
        return f"ERROR: preflight inspection failed: {type(exc).__name__}: {exc}"
    return build_preflight_report(collect_network_entries(running))


def build_preflight_report(entries: Iterable) -> str:
    """
    Build the read-only report from (name, status, classification) entries.
    The text never implies retroactive isolation: an operator scope only
    governs new disposable runs, so flagged containers need an explicit
    owner-driven stop/destroy.
    """
    lines = ["  Read-only preflight for PawnLogic-labelled containers:"]
    risky = 0
    for name, status, kind in entries:
        marker = "NEEDS ATTENTION" if kind in RISKY_NETWORK_KINDS else "offline"
        if kind in RISKY_NETWORK_KINDS:
            risky += 1
        lines.append(f"    {name:22} {status:12} network={kind:8} [{marker}]")
    if risky:
        lines.append(
            f"  {risky} running container(s) are NOT isolated. Enabling "
            f"PAWNLOGIC_DOCKER_EGRESS_ALLOW only scopes new disposable runs; it does "
            f"not quarantine these containers. Stop or destroy them explicitly if "
            f"you need isolation; this preflight never mutates them."
        )
    else:
        lines.append("  No running PawnLogic-labelled container currently has network access.")
    return "\n".join(lines)
