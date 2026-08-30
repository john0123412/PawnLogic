"""Pure network-target authorization policy.

The policy evaluates a normalized description of a network operation.  It does
not open sockets, perform DNS lookups, follow redirects, or otherwise produce
network traffic.  A host application may inject a resolver whose results are
evaluated as untrusted input.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import SplitResult, urlsplit, urlunsplit

from core.operation_policy import OperationAction


NetworkAction = OperationAction


class NetworkRule(str, Enum):
    MALFORMED_URL = "malformed_url"
    UNSUPPORTED_SCHEME = "unsupported_scheme"
    URL_CREDENTIALS = "url_credentials"
    INVALID_PORT = "invalid_port"
    CLOUD_METADATA = "cloud_metadata"
    LOOPBACK = "loopback"
    LINK_LOCAL = "link_local"
    MULTICAST = "multicast"
    UNSPECIFIED = "unspecified"
    RESERVED = "reserved"
    PRIVATE_NETWORK = "private_network"
    PRIVATE_NETWORK_AUTHORIZED = "private_network_authorized"
    NETWORK_CAPABILITY_AUTHORIZATION = "network_capability_authorization"
    ACTIVE_OPERATION_AUTHORIZATION = "active_operation_authorization"
    ENGAGEMENT_SCOPE_REQUIRED = "engagement_scope_required"
    DNS_RESULT_INVALID = "dns_result_invalid"
    ALLOW_PUBLIC = "allow_public"


@dataclass(frozen=True)
class NetworkOperation:
    """Input to :class:`NetworkPolicy`.

    ``url`` is the preferred input.  ``scheme`` and ``host`` are retained as
    explicit fields so adapters that already parsed a request can avoid
    reconstructing it.  When ``url`` is empty, the policy builds a URL from
    those fields.

    ``explicit_authorization`` is a host-provided authorization decision, not
    something inferred from the URL.  If ``authorized_targets`` is non-empty,
    the authorization must also match every evaluated redirect target.
    """

    url: str = ""
    tool_name: str = "network"
    scheme: str = ""
    host: str = ""
    port: int | None = None
    action: str = "fetch"
    method: str = "GET"
    redirect_chain: tuple[str, ...] = ()
    resolved_addresses: tuple[str, ...] = ()
    resolved_ips: tuple[str, ...] = ()
    interactive: bool = True
    explicit_authorization: bool = False
    engagement_scope: str | None = None
    scope_valid: bool = False
    authorized_targets: tuple[str, ...] = ()
    active_probe: bool = False
    capability_only: bool = False

    def __post_init__(self) -> None:
        """Keep both names usable while callers migrate to ``resolved_addresses``."""
        if self.resolved_addresses and self.resolved_ips and self.resolved_addresses != self.resolved_ips:
            raise ValueError("resolved_addresses and resolved_ips must agree")
        if self.resolved_addresses and not self.resolved_ips:
            object.__setattr__(self, "resolved_ips", self.resolved_addresses)
        elif self.resolved_ips and not self.resolved_addresses:
            object.__setattr__(self, "resolved_addresses", self.resolved_ips)


@dataclass(frozen=True)
class NetworkDecision:
    """A deterministic policy result with no executable side effects."""

    action: NetworkAction
    reason: str
    rule: str
    normalized_target: str

    @property
    def matched_rule(self) -> str:
        """Compatibility spelling matching ``OperationDecision``."""
        return self.rule

    def to_dict(self) -> dict[str, str]:
        return {
            "action": self.action.value,
            "reason": self.reason,
            "rule": self.rule,
            "normalized_target": self.normalized_target,
        }


@dataclass(frozen=True)
class _NormalizedTarget:
    url: str
    parsed: SplitResult
    scheme: str
    host: str
    port: int
    explicit_port: bool
    address: ipaddress.IPv4Address | ipaddress.IPv6Address | None


_SUPPORTED_SCHEMES = frozenset({"http", "https"})
_DEFAULT_PORTS = {"http": 80, "https": 443}
_METADATA_HOSTS = frozenset(
    {
        "metadata",
        "metadata.google.internal",
        "metadata.aliyun.com",
        "metadata.azure.internal",
        "instance-data.ec2.internal",
    }
)
_METADATA_IPS = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("169.254.170.2"),
        ipaddress.ip_address("100.100.100.200"),
    }
)
_MAX_URL_LENGTH = 8192
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f\s]")

Resolver = Callable[[str], Iterable[str | ipaddress.IPv4Address | ipaddress.IPv6Address]]


def _redacted_target(raw: object) -> str:
    """Return a safe diagnostic target without exposing URL credentials."""
    text = str(raw).strip()
    try:
        parsed = urlsplit(text)
    except ValueError:
        return "<invalid>"
    if parsed.username is None and parsed.password is None:
        return text[:_MAX_URL_LENGTH]
    host = parsed.hostname or "<invalid>"
    return urlunsplit((parsed.scheme, f"<redacted>@{host}", parsed.path, parsed.query, ""))


def _format_host(host: str, address: ipaddress._BaseAddress | None) -> str:
    value = str(address) if address is not None else host
    return f"[{value}]" if ":" in value else value


def _build_url(operation: NetworkOperation) -> str:
    if operation.url.strip():
        return operation.url
    if not operation.scheme or not operation.host:
        return ""
    host = operation.host
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = "" if operation.port is None else f":{operation.port}"
    return f"{operation.scheme}://{host}{port}/"


def _parse_port(parsed: SplitResult) -> tuple[int, bool]:
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise ValueError("port is not a valid integer") from exc
    if parsed_port is None:
        return _DEFAULT_PORTS[parsed.scheme], False
    if not 1 <= parsed_port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    return parsed_port, True


def _normalize_target(raw_url: str) -> _NormalizedTarget:
    text = str(raw_url).strip()
    if not text or len(text) > _MAX_URL_LENGTH or _CONTROL_RE.search(text):
        raise ValueError("URL is empty, too long, or contains whitespace/control characters")
    try:
        parsed = urlsplit(text)
    except ValueError as exc:
        raise ValueError("URL cannot be parsed") from exc
    scheme = parsed.scheme.lower()
    if scheme not in _SUPPORTED_SCHEMES:
        raise LookupError(f"unsupported URL scheme '{parsed.scheme or '(missing)'}'")
    if not parsed.netloc or parsed.hostname is None:
        raise ValueError("URL must include a host")
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise PermissionError("URL credentials are not allowed")
    try:
        raw_host = parsed.hostname.strip().rstrip(".")
    except AttributeError as exc:
        raise ValueError("URL host is invalid") from exc
    if not raw_host or len(raw_host) > 253:
        raise ValueError("URL host is invalid")
    if _CONTROL_RE.search(raw_host) or "%" in raw_host:
        raise ValueError("URL host contains whitespace/control characters")
    try:
        host = raw_host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("URL host is not valid IDNA") from exc
    port, explicit_port = _parse_port(parsed)
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    normalized_host = _format_host(host, address)
    normalized_netloc = normalized_host
    if explicit_port and port != _DEFAULT_PORTS[scheme]:
        normalized_netloc += f":{port}"
    normalized = urlunsplit(
        (scheme, normalized_netloc, parsed.path or "/", parsed.query, "")
    )
    return _NormalizedTarget(
        url=normalized,
        parsed=parsed,
        scheme=scheme,
        host=host,
        port=port,
        explicit_port=explicit_port,
        address=address,
    )


def normalize_url(url: str) -> str:
    """Normalize an HTTP(S) URL without resolving or contacting its host.

    ``ValueError`` is raised for malformed URLs and ``LookupError`` for an
    unsupported scheme.  ``PermissionError`` indicates embedded credentials.
    ``NetworkPolicy.evaluate`` converts these failures into deny decisions.
    """
    return _normalize_target(url).url


def _default_resolver(_: str) -> tuple[str, ...]:
    """A no-network resolver used unless the host explicitly injects one."""
    return ()


def _coerce_addresses(values: Iterable[object]) -> tuple[ipaddress._BaseAddress, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("resolver must return an iterable of IP addresses")
    addresses: list[ipaddress._BaseAddress] = []
    try:
        iterator = iter(values)
    except TypeError as exc:
        raise ValueError("resolver must return an iterable of IP addresses") from exc
    for value in iterator:
        try:
            address = value if isinstance(value, ipaddress._BaseAddress) else ipaddress.ip_address(str(value))
        except ValueError as exc:
            raise ValueError(f"resolver returned an invalid address: {value!r}") from exc
        if address not in addresses:
            addresses.append(address)
    return tuple(addresses)


def _target_authorized(
    target: _NormalizedTarget,
    operation: NetworkOperation,
    addresses: Iterable[ipaddress._BaseAddress] = (),
) -> bool:
    if not operation.explicit_authorization:
        return False
    if not operation.authorized_targets:
        return True
    candidates: list[str] = [target.host]
    if target.address is not None:
        candidates.append(str(target.address))
    candidates.extend(str(address) for address in addresses)
    for raw_scope in operation.authorized_targets:
        scope = str(raw_scope).strip().lower()
        if not scope:
            continue
        try:
            network = ipaddress.ip_network(scope, strict=False)
            if any(address in network for address in addresses):
                return True
            if target.address is not None and target.address in network:
                return True
        except ValueError:
            pass
        try:
            scope_target = _normalize_target(scope)
            scope = scope_target.host
        except (LookupError, PermissionError, ValueError):
            scope = scope.rstrip(".")
        if scope in candidates:
            return True
    return False


def _special_rule(address: ipaddress._BaseAddress) -> NetworkRule | None:
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        return _special_rule(mapped)
    if address.is_loopback:
        return NetworkRule.LOOPBACK
    if address.is_link_local:
        return NetworkRule.LINK_LOCAL
    if address.is_multicast:
        return NetworkRule.MULTICAST
    if address.is_unspecified:
        return NetworkRule.UNSPECIFIED
    if address.is_reserved:
        return NetworkRule.RESERVED
    return None


@dataclass
class NetworkPolicy:
    """Evaluate network operations through one deterministic policy seam."""

    resolver: Resolver = _default_resolver
    supported_schemes: frozenset[str] = field(default_factory=lambda: _SUPPORTED_SCHEMES)

    def evaluate(self, operation: NetworkOperation) -> NetworkDecision:
        """Return allow/confirm/deny without performing any network request."""
        raw_targets = (_build_url(operation), *operation.redirect_chain)
        if operation.capability_only and not raw_targets[0].strip():
            return self._evaluate_capability(operation)
        if not raw_targets or not raw_targets[0].strip():
            return self._deny(NetworkRule.MALFORMED_URL, "network operation has no target", "")

        last_decision: NetworkDecision | None = None
        for index, raw_target in enumerate(raw_targets):
            decision = self._evaluate_target(operation, raw_target, index)
            if decision.action != NetworkAction.ALLOW:
                return decision
            last_decision = decision
        assert last_decision is not None
        return last_decision

    def _evaluate_capability(self, operation: NetworkOperation) -> NetworkDecision:
        if operation.explicit_authorization:
            return NetworkDecision(
                NetworkAction.ALLOW,
                "network capability is explicitly authorized",
                NetworkRule.NETWORK_CAPABILITY_AUTHORIZATION.value,
                "",
            )
        if operation.interactive:
            return self._confirm(
                NetworkRule.NETWORK_CAPABILITY_AUTHORIZATION,
                "network capability requires explicit authorization",
                "",
            )
        return self._deny(
            NetworkRule.NETWORK_CAPABILITY_AUTHORIZATION,
            "network capability requires explicit authorization in non-interactive mode",
            "",
        )

    def _evaluate_target(
        self,
        operation: NetworkOperation,
        raw_target: str,
        hop: int,
    ) -> NetworkDecision:
        try:
            target = _normalize_target(raw_target)
        except LookupError as exc:
            return self._deny(NetworkRule.UNSUPPORTED_SCHEME, str(exc), _redacted_target(raw_target))
        except PermissionError as exc:
            return self._deny(NetworkRule.URL_CREDENTIALS, str(exc), _redacted_target(raw_target))
        except ValueError as exc:
            message = str(exc)
            rule = NetworkRule.INVALID_PORT if "port" in message else NetworkRule.MALFORMED_URL
            return self._deny(rule, f"redirect hop {hop}: {message}", _redacted_target(raw_target))

        if target.scheme not in self.supported_schemes:
            return self._deny(
                NetworkRule.UNSUPPORTED_SCHEME,
                f"scheme '{target.scheme}' is not allowed",
                target.url,
            )
        if target.host == "localhost" or target.host.endswith(".localhost"):
            return self._deny(
                NetworkRule.LOOPBACK,
                "localhost namespace is a loopback target",
                target.url,
            )
        if target.host in _METADATA_HOSTS or target.host.endswith(".internal"):
            return self._deny(NetworkRule.CLOUD_METADATA, "cloud metadata/internal host is denied", target.url)

        addresses: tuple[ipaddress._BaseAddress, ...]
        if target.address is not None:
            addresses = (target.address,)
        else:
            supplied = operation.resolved_addresses if hop == 0 else ()
            if supplied:
                raw_addresses: Iterable[object] = supplied
            else:
                try:
                    raw_addresses = self.resolver(target.host)
                except Exception as exc:  # Resolver is an untrusted adapter.
                    if not operation.interactive:
                        return self._deny(
                            NetworkRule.DNS_RESULT_INVALID,
                            f"DNS resolution failed for '{target.host}' in non-interactive mode",
                            target.url,
                        )
                    return self._confirm(
                        NetworkRule.DNS_RESULT_INVALID,
                        f"DNS resolution failed for '{target.host}': {type(exc).__name__}",
                        target.url,
                    )
            try:
                addresses = _coerce_addresses(raw_addresses)
            except ValueError as exc:
                return self._deny(NetworkRule.DNS_RESULT_INVALID, str(exc), target.url)

        if any(address in _METADATA_IPS for address in addresses):
            return self._deny(NetworkRule.CLOUD_METADATA, "target resolves to a cloud metadata address", target.url)
        special = next((_special_rule(address) for address in addresses if _special_rule(address)), None)
        if special is not None:
            return self._deny(special, f"target resolves to a {special.value.replace('_', ' ')} address", target.url)

        private = target.address is not None and target.address.is_private
        private = private or any(address.is_private for address in addresses)
        authorized = _target_authorized(target, operation, addresses)
        if operation.active_probe and (
            not operation.engagement_scope or not operation.scope_valid
        ):
            return self._deny(
                NetworkRule.ENGAGEMENT_SCOPE_REQUIRED,
                "active network operation requires a valid Engagement Scope",
                target.url,
            )
        if private and not authorized:
            if not operation.interactive:
                return self._deny(
                    NetworkRule.PRIVATE_NETWORK,
                    "private-network target requires explicit authorization in non-interactive mode",
                    target.url,
                )
            return self._confirm(
                NetworkRule.PRIVATE_NETWORK,
                "private-network target requires explicit authorization",
                target.url,
            )
        if private and authorized:
            return NetworkDecision(
                action=NetworkAction.ALLOW,
                reason="private-network target is explicitly authorized",
                rule=NetworkRule.PRIVATE_NETWORK_AUTHORIZED.value,
                normalized_target=target.url,
            )

        if operation.active_probe and not authorized:
            if not operation.interactive:
                return self._deny(
                    NetworkRule.ACTIVE_OPERATION_AUTHORIZATION,
                    "active network operation requires explicit authorization in non-interactive mode",
                    target.url,
                )
            return self._confirm(
                NetworkRule.ACTIVE_OPERATION_AUTHORIZATION,
                "active network operation requires explicit authorization",
                target.url,
            )
        return NetworkDecision(
            action=NetworkAction.ALLOW,
            reason="public target satisfies network policy",
            rule=NetworkRule.ALLOW_PUBLIC.value,
            normalized_target=target.url,
        )

    @staticmethod
    def _deny(rule: NetworkRule, reason: str, target: str) -> NetworkDecision:
        return NetworkDecision(NetworkAction.DENY, reason, rule.value, target)

    @staticmethod
    def _confirm(rule: NetworkRule, reason: str, target: str) -> NetworkDecision:
        return NetworkDecision(NetworkAction.CONFIRM, reason, rule.value, target)


__all__ = [
    "NetworkAction",
    "NetworkDecision",
    "NetworkOperation",
    "NetworkPolicy",
    "NetworkRule",
    "normalize_url",
]
