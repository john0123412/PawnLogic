"""Operator-declared Docker scope and per-operation DNS snapshots.

Host configuration accepts hosts, IPs and CIDRs. A hostname resolves once into
all numeric addresses; scoped HTTP consumes that snapshot and enforces target
selection at the socket boundary. The legacy hosts-file view remains available
for policy tests but is not itself a destination filter. Never let a tool arg
supply or override the operator configuration.
"""
from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import socket


EGRESS_SCOPE_ENV = "PAWNLOGIC_DOCKER_EGRESS_ALLOW"

_EGRESS_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")


def egress_resolver(host: str) -> tuple[str, ...]:
    """Resolve an egress-scope hostname once, at policy time.

    Module-level so tests can inject a fake resolver; the real path uses
    ``socket.getaddrinfo`` and returns unique textual addresses in order.
    """
    infos = socket.getaddrinfo(host, None)
    addresses: list[str] = []
    for info in infos:
        address = str(info[4][0])
        if address not in addresses:
            addresses.append(address)
    return tuple(addresses)


def parse_egress_scope(raw: str) -> tuple[tuple[str, ...], str | None]:
    """Split and validate a comma/space-separated host/IP/CIDR scope list."""
    entries: list[str] = []
    for chunk in raw.replace(",", " ").split():
        entry = chunk.strip().lower().rstrip(".")
        if not entry:
            continue
        try:
            ipaddress.ip_network(entry, strict=False)
        except ValueError:
            if len(entry) > 253 or not _EGRESS_HOST_RE.fullmatch(entry):
                return (), f"invalid egress scope entry '{entry}' (use host, IP, or CIDR)"
        if entry not in entries:
            entries.append(entry)
    return tuple(entries), None


def resolve_egress_addresses(raw_scope: str | None = None) -> tuple[dict[str, tuple[str, ...]], str | None, str | None]:
    """Return the complete per-operation hostname address snapshot.

    CIDR and bare-IP entries need no DNS lookup. Hostnames resolve once;
    the scoped HTTP proxy validates and dials these numeric snapshots.
    """
    raw = (os.environ.get(EGRESS_SCOPE_ENV, "") if raw_scope is None else raw_scope).strip()
    if not raw:
        return {}, None, None
    entries, error = parse_egress_scope(raw)
    if error:
        return {}, None, (
            f"SECURITY BLOCK: {EGRESS_SCOPE_ENV} is set but invalid: {error}"
        )
    host_addresses: dict[str, tuple[str, ...]] = {}
    for entry in entries:
        try:
            ipaddress.ip_network(entry, strict=False)
            continue  # bare IP or CIDR: no hostname mapping to add
        except ValueError:
            pass
        try:
            addresses = egress_resolver(entry)
        except Exception as exc:
            return {}, None, (
                f"SECURITY BLOCK: egress scope host '{entry}' could not be "
                f"resolved at policy time: {exc}"
            )
        if not addresses:
            return {}, None, (
                f"SECURITY BLOCK: egress scope host '{entry}' resolved to no addresses."
            )
        host_addresses[entry.rstrip(".")] = tuple(addresses)
    fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:12]
    return host_addresses, fingerprint, None


def resolve_egress_scope() -> tuple[dict[str, str], str | None, str | None]:
    """Legacy hosts-file view of the address snapshot; not a destination filter."""
    addresses, fingerprint, error = resolve_egress_addresses()
    return {host: values[0] for host, values in addresses.items()}, fingerprint, error


def resolve_scope_for_network(network: str) -> tuple[dict[str, str], str | None, str | None]:
    """Resolve the egress scope for a container network mode.

    Only bridge grants are scoped. Host networking shares the host netstack,
    where the scope cannot be applied, so setting it is called out loudly.
    """
    if network == "bridge":
        return resolve_egress_scope()
    if network == "host" and os.environ.get(EGRESS_SCOPE_ENV, "").strip():
        return {}, None, "SECURITY BLOCK: host networking cannot enforce the Docker egress scope."
    return {}, None, None
