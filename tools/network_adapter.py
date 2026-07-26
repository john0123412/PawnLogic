"""Host adapters for the pure :mod:`core.network_policy` decision module."""

from __future__ import annotations

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
        is_confirmation_available()
        if confirmation_available is None
        else confirmation_available
    )
    return {
        "interactive": bool(
            host_confirmation and values.get("interactive", True)
        ),
        "explicit_authorization": False,
        "authorized_targets": (),
    }


def evaluate_network_url(
    url: str,
    *,
    arguments: dict | None = None,
    redirect_chain: tuple[str, ...] = (),
    confirmation_available: bool | None = None,
) -> NetworkDecision:
    """Evaluate a web target through the shared NetworkPolicy adapter."""
    options = _network_options(
        arguments,
        confirmation_available=confirmation_available,
    )
    operation = NetworkOperation(
        url=str(url),
        tool_name="web_fetch",
        action="fetch",
        redirect_chain=tuple(redirect_chain),
        interactive=bool(options["interactive"]),
        explicit_authorization=bool(options["explicit_authorization"]),
        authorized_targets=options["authorized_targets"],  # type: ignore[arg-type]
    )
    return NetworkPolicy(resolver=_resolve_host_addresses).evaluate(operation)


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
        return (
            f"SECURITY BLOCK: target '{host}' resolves to a loopback address; "
            "denied by default."
        )
    if decision.rule == "link_local":
        if literal_host:
            return f"SECURITY BLOCK: link-local target '{host}' is denied by default."
        return (
            f"SECURITY BLOCK: target '{host}' resolves to a link-local address; "
            "denied by default."
        )
    reason = decision.reason.replace("link local", "link-local")
    return (
        f"SECURITY BLOCK: {reason} "
        f"[rule={decision.rule}; target={target}]"
    )


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


class NetworkRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-evaluate every urllib redirect before following it."""

    def __init__(self, arguments: dict | None = None) -> None:
        super().__init__()
        self._arguments = arguments

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        decision = evaluate_network_url(newurl, arguments=self._arguments)
        if not confirm_network_decision(decision, self._arguments):
            raise NetworkPolicyBlocked(decision)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url_with_policy(
    request: urllib.request.Request,
    *,
    timeout: int,
    arguments: dict | None = None,
):
    """Open a URL with redirect policy enforcement."""
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
            "Private network target authorized for this request: "
            f"{decision.normalized_target}"
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
