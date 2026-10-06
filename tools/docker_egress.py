"""Operator-declared bridge egress scope for Docker containers.

Host-side configuration, never a tool argument: the model cannot scope its
own network grant (mirrors "never from model authorization" in the network
adapter). ``PAWNLOGIC_DOCKER_EGRESS_ALLOW`` takes hosts, bare IPs, or CIDR
networks, comma/space separated. Approved hostnames are resolved once at
policy time and pinned into bridge-attached containers via ``extra_hosts``,
closing in-container DNS rebinding for the approved names; the grant is
labelled with a scope fingerprint so scoped containers are auditable after
the fact. Any invalid or unresolvable entry fails closed.

Extracted from tools/docker_sandbox.py as a pure policy module (no Docker
SDK import): the only I/O is the injected ``egress_resolver``.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import socket

from utils.ansi import YELLOW, c

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
        entry = chunk.strip().lower()
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


def resolve_egress_scope() -> tuple[dict[str, str], str | None, str | None]:
    """Return (hostname -> pinned IP map, scope fingerprint, error).

    CIDR and bare-IP entries are structural scope declarations and produce no
    host pin; hostname entries are resolved once here so a later DNS change
    cannot rebind an approved name. Any resolution failure fails closed.
    """
    raw = os.environ.get(EGRESS_SCOPE_ENV, "").strip()
    if not raw:
        return {}, None, None
    entries, error = parse_egress_scope(raw)
    if error:
        return {}, None, (
            f"SECURITY BLOCK: {EGRESS_SCOPE_ENV} is set but invalid: {error}"
        )
    pins: dict[str, str] = {}
    for entry in entries:
        try:
            ipaddress.ip_network(entry, strict=False)
            continue  # bare IP or CIDR: no hostname pin to make
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
        pins[entry] = addresses[0]
    fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:12]
    return pins, fingerprint, None


def resolve_scope_for_network(network: str) -> tuple[dict[str, str], str | None, str | None]:
    """Resolve the egress scope for a container network mode.

    Only bridge grants are scoped. Host networking shares the host netstack,
    where the scope cannot be applied, so setting it is called out loudly.
    """
    if network == "bridge":
        return resolve_egress_scope()
    if network == "host" and os.environ.get(EGRESS_SCOPE_ENV, "").strip():
        print(c(YELLOW, "  Note: PAWNLOGIC_DOCKER_EGRESS_ALLOW cannot constrain host networking."))
    return {}, None, None
