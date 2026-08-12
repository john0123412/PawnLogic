"""Task-local cancellation helpers for blocking provider stream transport."""

from __future__ import annotations

import http.client
import socket
from contextlib import suppress
from typing import Any, Protocol


class StreamCancellation(Protocol):
    """Minimal task-local cancellation state used by streaming requests."""

    @property
    def cancelled(self) -> bool: ...

    @property
    def reason(self) -> str | None: ...


class StreamCancellationError(Exception):
    """Raised when a task-local cancellation stops one stream request."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def raise_if_task_cancelled(cancellation: StreamCancellation | None) -> None:
    """Raise the stable stream cancellation error when a token is set."""
    if cancellation is not None and _is_cancelled(cancellation):
        raise StreamCancellationError(_reason(cancellation))


def cancel_connection(
    conn: http.client.HTTPConnection,
    response: http.client.HTTPResponse | None = None,
) -> None:
    """Best-effort close of one stream without touching global interrupts."""
    sockets = _connection_sockets(conn, response)
    for active_sock in sockets:
        _close_socket(active_sock)
    _close_quietly(response)
    _close_quietly(conn)


def _is_cancelled(cancellation: StreamCancellation) -> bool:
    cancelled = getattr(cancellation, "cancelled", None)
    if callable(cancelled):
        cancelled = cancelled()
    if cancelled is not None:
        return bool(cancelled)
    is_cancelled = getattr(cancellation, "is_cancelled", None)
    return bool(is_cancelled()) if callable(is_cancelled) else False


def _reason(cancellation: StreamCancellation) -> str:
    reason = getattr(cancellation, "reason", None)
    return reason.strip() if isinstance(reason, str) and reason.strip() else "task cancelled"


def _connection_sockets(
    conn: http.client.HTTPConnection,
    response: http.client.HTTPResponse | None,
) -> list[Any]:
    sockets = [sock] if (sock := getattr(conn, "sock", None)) else []
    if response is None:
        return sockets
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    for owner in (raw, fp):
        if owner is None:
            continue
        sock = getattr(owner, "_sock", None) or getattr(owner, "sock", None)
        if sock:
            sockets.append(sock)
    return sockets


def _close_socket(active_sock: Any) -> None:
    with suppress(Exception):
        active_sock.shutdown(socket.SHUT_RDWR)
    with suppress(Exception):
        active_sock.close()


def _close_quietly(value: object | None) -> None:
    if value is None:
        return
    close = getattr(value, "close", None)
    if callable(close):
        with suppress(Exception):
            close()


__all__ = [
    "StreamCancellation",
    "StreamCancellationError",
    "cancel_connection",
    "raise_if_task_cancelled",
]
