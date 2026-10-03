"""Host adapters for the pure :mod:`core.network_policy` decision module.

DNS-pinning contract (issue #177, finding 3): every URL is resolved exactly
once, at policy-check time, and the connection layer only dials those pinned
addresses.  Re-resolving at connect time would reopen the DNS-rebinding
TOCTOU gap (benign IP at check time, malicious IP at connect time), so the
pinned handlers below fail closed when a host has no pin record instead of
falling back to a fresh lookup.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import urllib.parse
import urllib.request
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from core.network_policy import (
    NetworkAction,
    NetworkDecision,
    NetworkOperation,
    NetworkPolicy,
)
from core.operation_policy import (
    OperationAction,
    OperationDecision,
    RiskLevel,
    is_confirmation_available,
    prompt_for_confirmation,
)


def _resolve_host_addresses(host: str) -> tuple[str, ...]:
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    addresses: list[str] = []
    for info in infos:
        sockaddr = info[4]
        if sockaddr and str(sockaddr[0]) not in addresses:
            addresses.append(str(sockaddr[0]))
    return tuple(addresses)


def _network_options(
    arguments: dict | None,
    *,
    confirmation_available: bool | None = None,
) -> dict[str, object]:
    """Build options from trusted host state, never from model authorization."""
    values = arguments or {}
    host_confirmation = (
        is_confirmation_available() if confirmation_available is None else confirmation_available
    )
    return {
        "interactive": bool(host_confirmation and values.get("interactive", True)),
        "explicit_authorization": False,
        "authorized_targets": (),
    }


def _pin_key(host: str) -> str:
    """Normalize a hostname for the DNS pin table."""
    return host.strip().lower().rstrip(".")


def _pinned_addresses_for_url(url: str) -> tuple[str, ...]:
    """Resolve a URL's host exactly once, at policy-check time.

    Returns the addresses the policy evaluated.  An empty tuple means the
    pre-resolution failed or was skipped; the policy then falls back to its
    own resolver, preserving the existing DNS-failure behavior.

    Hosts are only resolved for http(s) URLs: unsupported schemes are denied
    by the policy without DNS, and must stay that way.
    """
    try:
        parts = urllib.parse.urlsplit(str(url))
    except ValueError:
        # Malformed URL (e.g. unmatched IPv6 bracket): leave DNS alone;
        # the policy denies the URL without resolving.
        return ()
    if parts.scheme not in ("http", "https"):
        return ()
    try:
        host = parts.hostname or ""
    except ValueError:
        return ()
    if not host:
        return ()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        # Literal IP: nothing to resolve, and the policy short-circuits on
        # ``target.address`` anyway.  Pin it so the connect path is uniform.
        return (host,)
    try:
        return _resolve_host_addresses(host)
    except OSError:
        return ()


def _evaluate_network_url_pinned(
    url: str,
    *,
    arguments: dict | None = None,
    redirect_chain: tuple[str, ...] = (),
    confirmation_available: bool | None = None,
) -> tuple[NetworkDecision, tuple[str, ...]]:
    """Evaluate a URL and return the decision plus its DNS pin set.

    The pin set is the exact address list the policy evaluated.  Callers
    that open a connection must dial only these addresses.
    """
    options = _network_options(
        arguments,
        confirmation_available=confirmation_available,
    )
    pins = _pinned_addresses_for_url(url)
    operation = NetworkOperation(
        url=str(url),
        tool_name="web_fetch",
        action="fetch",
        redirect_chain=tuple(redirect_chain),
        interactive=bool(options["interactive"]),
        explicit_authorization=bool(options["explicit_authorization"]),
        authorized_targets=options["authorized_targets"],  # type: ignore[arg-type]
        resolved_addresses=pins,
    )
    decision = NetworkPolicy(resolver=_resolve_host_addresses).evaluate(operation)
    return decision, pins


def evaluate_network_url(
    url: str,
    *,
    arguments: dict | None = None,
    redirect_chain: tuple[str, ...] = (),
    confirmation_available: bool | None = None,
) -> NetworkDecision:
    """Evaluate a web target through the shared NetworkPolicy adapter."""
    decision, _ = _evaluate_network_url_pinned(
        url,
        arguments=arguments,
        redirect_chain=redirect_chain,
        confirmation_available=confirmation_available,
    )
    return decision


def decision_message(decision: NetworkDecision) -> str:
    """Render a stable, credential-safe policy denial."""
    target = decision.normalized_target or "(network capability)"
    host = urllib.parse.urlsplit(target).hostname or ""
    try:
        literal_host = ipaddress.ip_address(host) is not None
    except ValueError:
        literal_host = False
    if decision.rule == "unsupported_scheme":
        scheme = urllib.parse.urlsplit(target).scheme or "(missing)"
        return (
            f"SECURITY BLOCK: unsupported URL scheme '{scheme}'. "
            "Only http:// and https:// are allowed."
        )
    if decision.rule == "loopback":
        if literal_host:
            return f"SECURITY BLOCK: loopback target '{host}' is denied by default."
        return f"SECURITY BLOCK: target '{host}' resolves to a loopback address; denied by default."
    if decision.rule == "link_local":
        if literal_host:
            return f"SECURITY BLOCK: link-local target '{host}' is denied by default."
        return (
            f"SECURITY BLOCK: target '{host}' resolves to a link-local address; denied by default."
        )
    reason = decision.reason.replace("link local", "link-local")
    return f"SECURITY BLOCK: {reason} [rule={decision.rule}; target={target}]"


def confirm_network_decision(
    decision: NetworkDecision,
    arguments: dict | None = None,
) -> bool:
    """Adapt NetworkPolicy CONFIRM to the existing host confirmation UX."""
    if decision.action == NetworkAction.ALLOW:
        return True
    options = _network_options(arguments)
    if (
        decision.action == NetworkAction.DENY
        or not bool(options["interactive"])
        or not is_confirmation_available()
    ):
        return False
    host_decision = OperationDecision(
        action=OperationAction.CONFIRM,
        risk=RiskLevel.HIGH,
        reason=f"Network operation requires confirmation: {decision.reason}",
        matched_rule=f"network:{decision.rule}",
        redacted_command=decision.normalized_target,
    )
    return prompt_for_confirmation(host_decision)


class NetworkPolicyBlocked(RuntimeError):
    """Stop an outbound client before it follows an unsafe redirect."""

    def __init__(self, decision: NetworkDecision) -> None:
        super().__init__(decision_message(decision))
        self.decision = decision


class _DNSPinMissingError(OSError):
    """A connection was attempted without a policy-check-time DNS pin."""


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTP connection that only dials policy-check-time pinned addresses.

    Never performs DNS resolution itself: a missing pin record fails closed
    instead of re-resolving, which is what closes the rebinding gap.
    """

    def __init__(
        self,
        *args: Any,
        host_pins: dict[str, tuple[str, ...]] | None = None,
        **kwargs: Any,
    ) -> None:
        self._host_pins = host_pins if host_pins is not None else {}
        super().__init__(*args, **kwargs)

    def _dial_pinned(self) -> socket.socket:
        pins = self._host_pins.get(_pin_key(self.host), ())
        if not pins:
            raise _DNSPinMissingError(
                f"refusing to resolve {self.host!r} at connect time: "
                "no DNS pin record from policy evaluation"
            )
        last_error: OSError | None = None
        for pin in pins:
            try:
                return socket.create_connection((pin, self.port), self.timeout, self.source_address)
            except OSError as exc:
                last_error = exc
        assert last_error is not None  # pins non-empty: loop ran at least once
        raise last_error

    def connect(self) -> None:
        self.sock = self._dial_pinned()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection dialing pinned IPs with SNI/cert checks on the host.

    The TCP dial goes to a pinned address, but TLS server_hostname stays the
    original hostname, so certificate validation is unchanged.
    """

    def __init__(
        self,
        *args: Any,
        host_pins: dict[str, tuple[str, ...]] | None = None,
        **kwargs: Any,
    ) -> None:
        self._host_pins = host_pins if host_pins is not None else {}
        super().__init__(*args, **kwargs)

    def connect(self) -> None:
        if self._tunnel_host:
            # Proxy CONNECT tunneling: the proxy resolves the target, so the
            # stdlib path applies unchanged.
            http.client.HTTPConnection.connect(self)
            self.sock = self._context.wrap_socket(self.sock, server_hostname=self._tunnel_host)
            return
        pins = self._host_pins.get(_pin_key(self.host), ())
        if not pins:
            raise _DNSPinMissingError(
                f"refusing to resolve {self.host!r} at connect time: "
                "no DNS pin record from policy evaluation"
            )
        last_error: OSError | None = None
        raw_sock: socket.socket | None = None
        for pin in pins:
            try:
                raw_sock = socket.create_connection(
                    (pin, self.port), self.timeout, self.source_address
                )
                break
            except OSError as exc:
                last_error = exc
        if raw_sock is None:
            assert last_error is not None
            raise last_error
        self.sock = self._context.wrap_socket(raw_sock, server_hostname=self.host)


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    """HTTPHandler wiring pinned connections into urllib."""

    def __init__(
        self,
        host_pins: dict[str, tuple[str, ...]] | None = None,
        debuglevel: int = 0,
    ) -> None:
        super().__init__(debuglevel)
        self._host_pins = host_pins if host_pins is not None else {}

    def http_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(_PinnedHTTPConnection, req, host_pins=self._host_pins)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    """HTTPSHandler wiring pinned connections into urllib."""

    def __init__(
        self,
        host_pins: dict[str, tuple[str, ...]] | None = None,
        debuglevel: int = 0,
        context: Any = None,
        check_hostname: Any = None,
    ) -> None:
        super().__init__(debuglevel, context, check_hostname)
        self._host_pins = host_pins if host_pins is not None else {}

    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(
            _PinnedHTTPSConnection,
            req,
            host_pins=self._host_pins,
            context=self._context,
        )


class NetworkRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-evaluate every urllib redirect before following it.

    Each redirect hop is resolved and pinned independently, so a hop that
    rebinds between its own evaluation and connection is still contained.
    """

    def __init__(
        self,
        arguments: dict | None = None,
        host_pins: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        super().__init__()
        self._arguments = arguments
        self._host_pins = host_pins if host_pins is not None else {}

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        decision, pins = _evaluate_network_url_pinned(newurl, arguments=self._arguments)
        if not confirm_network_decision(decision, self._arguments):
            raise NetworkPolicyBlocked(decision)
        self._host_pins[_pin_key(urllib.parse.urlsplit(newurl).hostname or "")] = pins
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _proxy_for_url(url: str) -> str | None:
    """Return the proxy urllib would use for *url*, or None for direct.

    When a proxy is configured, the proxy (operator-trusted) performs DNS
    and the connection, so end-to-end DNS pinning cannot apply.  The policy
    gate still decides which URLs may be fetched at all.
    """
    parts = urllib.parse.urlsplit(str(url))
    if not parts.scheme:
        return None
    proxy = urllib.request.getproxies().get(parts.scheme)
    if not proxy:
        return None
    if urllib.request.proxy_bypass(parts.hostname or ""):
        return None
    return proxy


def open_url_with_policy(
    request: urllib.request.Request,
    *,
    timeout: int,
    arguments: dict | None = None,
):
    """Open a URL with redirect policy enforcement and DNS pinning.

    The URL's host is resolved once during policy evaluation; a direct
    connection only dials those pinned addresses, so a DNS record that
    changes between the check and the connection cannot steer the socket
    elsewhere (issue #177, DNS-rebinding TOCTOU).  When a proxy is
    configured, the proxy performs the connection and pinning does not
    apply end-to-end.
    """
    url = request.full_url
    host_pins: dict[str, tuple[str, ...]] = {}
    decision, pins = _evaluate_network_url_pinned(url, arguments=arguments)
    if not confirm_network_decision(decision, arguments):
        raise NetworkPolicyBlocked(decision)
    host_pins[_pin_key(urllib.parse.urlsplit(url).hostname or "")] = pins
    if _proxy_for_url(url) is None:
        opener = urllib.request.build_opener(
            NetworkRedirectHandler(arguments, host_pins),
            _PinnedHTTPHandler(host_pins),
            _PinnedHTTPSHandler(host_pins),
        )
    else:
        opener = urllib.request.build_opener(NetworkRedirectHandler(arguments))
    return opener.open(request, timeout=timeout)


def validate_browser_url(
    url: str,
    arguments: dict | None = None,
) -> tuple[str | None, list[str]]:
    decision = evaluate_network_url(url, arguments=arguments)
    if not confirm_network_decision(decision, arguments):
        return decision_message(decision), []
    warnings: list[str] = []
    if decision.rule == "private_network_authorized":
        warnings.append(
            f"Private network target authorized for this request: {decision.normalized_target}"
        )
    return None, warnings


def _navigation_guard(page: Any, arguments: dict | None):
    route = getattr(page, "route", None)
    unroute = getattr(page, "unroute", None)
    if not callable(route) or not callable(unroute):
        return None, []

    blocked: list[NetworkDecision] = []

    def guard(route_obj: Any, request: Any) -> None:
        target = str(getattr(request, "url", "") or "")
        decision = evaluate_network_url(target, arguments=arguments)
        if not confirm_network_decision(decision, arguments):
            blocked.append(decision)
            route_obj.abort()
            return
        route_obj.continue_()

    try:
        route("**/*", guard)
    except Exception:
        return None, []
    return guard, blocked


def _remove_navigation_guard(page: Any, guard: Any) -> None:
    if guard is None:
        return
    try:
        page.unroute("**/*", guard)
    except TypeError:
        with suppress(Exception):
            page.unroute("**/*")
    except Exception:
        pass


def navigate_with_policy(
    page: Any,
    url: str,
    *,
    timeout_ms: int,
    arguments: dict | None = None,
) -> tuple[str | None, str]:
    """Navigate with request interception and a final-URL defense."""
    guard, blocked = _navigation_guard(page, arguments)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception:
        if blocked:
            return decision_message(blocked[0]), ""
        raise
    finally:
        _remove_navigation_guard(page, guard)

    final_url = str(getattr(page, "url", "") or url)
    final_decision = evaluate_network_url(final_url, arguments=arguments)
    if not confirm_network_decision(final_decision, arguments):
        return decision_message(final_decision), ""
    return None, final_url


def ensure_page_url(
    url: str,
    *,
    arguments: dict | None,
    current_url: str | None,
    get_page: Callable[[], Any | None],
    timeout_ms: int,
    emit_warnings: bool,
    warning_sink: Callable[[str], None],
) -> tuple[str | None, str | None]:
    """Synchronize a lazy browser page without leaking policy branches upstream."""
    error, warnings = validate_browser_url(url, arguments)
    if error:
        return error, None
    page = get_page()
    if page is None:
        return None, current_url
    try:
        if emit_warnings:
            for warning in warnings:
                warning_sink(warning)
        page_url = str(getattr(page, "url", "") or "")
        if not page_url or page_url == "about:blank" or page_url != url:
            error, final_url = navigate_with_policy(
                page,
                url,
                timeout_ms=timeout_ms,
                arguments=arguments,
            )
            if error:
                return error, None
            return None, final_url
    except Exception:
        return None, current_url
    return None, current_url


def response_url_with_policy(
    response: Any,
    requested_url: str,
    *,
    arguments: dict | None,
    emit_warnings: bool,
    warning_sink: Callable[[str], None],
) -> tuple[str | None, str | None]:
    """Validate a fetcher's final URL and return the safe current URL."""
    final_url = getattr(response, "url", None)
    if not final_url and hasattr(response, "geturl"):
        final_url = response.geturl()
    if not final_url:
        return None, requested_url
    error, warnings = validate_browser_url(str(final_url), arguments)
    if error:
        return error, None
    if emit_warnings:
        for warning in warnings:
            warning_sink(warning)
    return None, str(final_url)
