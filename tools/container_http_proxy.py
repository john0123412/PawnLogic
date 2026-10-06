"""A private Unix-socket HTTP/CONNECT egress proxy for Docker containers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from pathlib import Path
import os
import socket
import stat
import threading
import time

from core.network_policy import NetworkOperation, NetworkPolicy
from tools.container_http_protocol import (
    EgressScopeError,
    HTTPProtocolError,
    MAX_TIMEOUT_SECONDS,
    close_socket,
    dial_pinned,
    forward_http,
    parse_connect_target,
    parse_egress_scope,
    parse_http_target,
    read_request,
    ResolvedEgressScope,
    relay_streams,
)


_LISTEN_BACKLOG = 16
_MAX_HANDLERS = 16


class ContainerHTTPProxy:
    """Serve scoped HTTP and CONNECT requests on a private Unix socket.

    The listener has no TCP fallback.  The egress scope is parsed and all
    declared hostnames are resolved before the socket is created.  A caller
    that already resolved the hostnames in a trusted policy layer can pass
    ``resolved_hosts`` to avoid a second DNS lookup.
    """

    def __init__(
        self,
        directory: str,
        raw_scope: str,
        timeout_seconds: int = 30,
        *,
        resolved_hosts: Mapping[str, Iterable[str] | str] | None = None,
    ) -> None:
        if not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise ValueError("timeout_seconds must be between 1 and 300")
        self.directory = Path(directory)
        self.raw_scope = raw_scope
        self.timeout_seconds = float(timeout_seconds)
        self._resolved_hosts = resolved_hosts
        self._socket_path = self.directory / "egress.sock"
        self._socket_inode: int | None = None
        self._scope: ResolvedEgressScope | None = None
        self._network_policy = NetworkPolicy()
        self._listener: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._handler_slots = threading.BoundedSemaphore(_MAX_HANDLERS)
        self._active_sockets: set[socket.socket] = set()
        self._lock = threading.RLock()
        self._stopping = True
        self._started_once = False
        self._operation_deadline: float | None = None
        self._operation_timer: threading.Timer | None = None

    @property
    def socket_path(self) -> Path:
        """The deterministic Unix socket path used by ``start``."""
        return self._socket_path

    @property
    def scope(self) -> ResolvedEgressScope | None:
        """The startup-resolved scope, or ``None`` before ``start``."""
        return self._scope

    @property
    def running(self) -> bool:
        with self._lock:
            return not self._stopping and self._listener is not None

    def start(self) -> Path:
        """Resolve policy, create the Unix listener, and start accepting."""
        with self._lock:
            if not self._stopping and self._listener is not None:
                return self._socket_path
            if self._started_once:
                raise RuntimeError("proxy cannot be restarted")
            self._started_once = True
            # Resolve before creating a listener: setup errors never expose a
            # partially configured proxy.  Holding the state lock serializes
            # concurrent start/stop calls around the socket path.
            resolved_scope = parse_egress_scope(self.raw_scope).resolve(
                resolved_hosts=self._resolved_hosts,
            )
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._prepare_socket_path()
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                listener.bind(str(self._socket_path))
                os.chmod(self._socket_path, stat.S_IRUSR | stat.S_IWUSR)
                self._socket_inode = self._socket_path.stat().st_ino
                listener.listen(_LISTEN_BACKLOG)
                listener.settimeout(0.2)
                executor = ThreadPoolExecutor(
                    max_workers=_MAX_HANDLERS,
                    thread_name_prefix="pawn-container-egress",
                )
            except Exception:
                close_socket(listener)
                self._unlink_socket_path()
                raise
            self._scope = resolved_scope
            self._listener = listener
            self._executor = executor
            self._stopping = False
            self._operation_deadline = time.monotonic() + self.timeout_seconds
            self._operation_timer = threading.Timer(
                self.timeout_seconds,
                self.stop,
            )
            self._operation_timer.daemon = True
            self._accept_thread = threading.Thread(
                target=self._accept_loop,
                name="pawn-container-egress-accept",
                daemon=True,
            )
            self._accept_thread.start()
            self._operation_timer.start()
        return self._socket_path

    def stop(self) -> None:
        """Revoke new requests and close every accepted socket."""
        with self._lock:
            listener = self._listener
            thread = self._accept_thread
            executor = self._executor
            timer = self._operation_timer
            self._listener = None
            self._accept_thread = None
            self._executor = None
            self._operation_timer = None
            self._operation_deadline = None
            self._stopping = True
            active = tuple(self._active_sockets)
        if timer is not None:
            timer.cancel()
        if listener is not None:
            close_socket(listener)
        for sock_obj in active:
            close_socket(sock_obj)
        self._unlink_socket_path()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=min(self.timeout_seconds + 1, 10.0))
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

    def __enter__(self) -> ContainerHTTPProxy:
        self.start()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.stop()

    def _prepare_socket_path(self) -> None:
        if len(str(self._socket_path).encode()) >= 108:
            raise OSError("Unix socket path is too long")
        try:
            mode = self._socket_path.stat().st_mode
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(mode):
            raise FileExistsError(f"refusing to replace non-socket {self._socket_path}")
        self._socket_path.unlink()

    def _unlink_socket_path(self) -> None:
        try:
            if self._socket_inode is not None and self._socket_path.stat().st_ino != self._socket_inode:
                return
            self._socket_path.unlink()
            self._socket_inode = None
        except FileNotFoundError:
            self._socket_inode = None
        except OSError:
            # A stop operation is best effort; do not replace a path that may
            # have been recreated by another owner after this listener closed.
            pass

    def _accept_loop(self) -> None:
        while True:
            with self._lock:
                listener = self._listener
                executor = self._executor
                stopping = self._stopping
            if stopping or listener is None or executor is None:
                return
            try:
                client, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with self._lock:
                if self._stopping or self._listener is not listener:
                    close_socket(client)
                    return
            if not self._handler_slots.acquire(blocking=False):
                self._send_error(client, 503, "Proxy busy")
                close_socket(client)
                continue
            self._register_socket(client)
            try:
                future = executor.submit(self._handle_client_wrapper, client)
                future.add_done_callback(
                    partial(self._cancelled_client, client=client)
                )
            except RuntimeError:
                self._unregister_socket(client)
                self._handler_slots.release()
                close_socket(client)
                return

    def _handle_client_wrapper(self, client: socket.socket) -> None:
        try:
            self._handle_client(client)
        finally:
            self._unregister_socket(client)
            close_socket(client)
            self._handler_slots.release()

    def _cancelled_client(self, future: Future[None], client: socket.socket) -> None:
        if not future.cancelled():
            return
        self._unregister_socket(client)
        close_socket(client)
        self._handler_slots.release()

    def _handle_client(self, client: socket.socket) -> None:
        client.settimeout(self.timeout_seconds)
        upstream: socket.socket | None = None
        try:
            request = read_request(client)
            if request.method == "CONNECT":
                host, port = parse_connect_target(request)
            else:
                host, port, _path = parse_http_target(request)
            with self._lock:
                scope = self._scope
                stopping = self._stopping
                deadline = self._operation_deadline
            if stopping or scope is None:
                return
            _requested_host, port, addresses = scope.resolve_target(host, port)
            self._authorize_target(scope.entries, host, port, addresses, request.method)
            upstream = dial_pinned(
                addresses,
                port,
                self.timeout_seconds,
                register=self._register_socket,
                unregister=self._unregister_socket,
                stop_predicate=self._is_stopping,
                deadline=deadline,
            )
            with self._lock:
                if self._stopping:
                    return
            if request.method == "CONNECT":
                client.sendall(b"HTTP/1.1 200 Connection Established\r\nConnection: close\r\n\r\n")
                relay_streams(
                    client,
                    upstream,
                    request.pending,
                    timeout_seconds=self.timeout_seconds,
                    close_sockets=False,
                )
            else:
                forward_http(
                    client,
                    upstream,
                    request,
                    timeout_seconds=self.timeout_seconds,
                )
        except EgressScopeError:
            self._send_error(client, 403, "Target denied")
        except HTTPProtocolError:
            self._send_error(client, 400, "Bad request")
        except (OSError, TimeoutError):
            self._send_error(client, 502, "Upstream unavailable")
        finally:
            if upstream is not None:
                self._unregister_socket(upstream)
                close_socket(upstream)

    def _authorize_target(
        self,
        entries: tuple[str, ...],
        host: str,
        port: int,
        addresses: tuple[str, ...],
        method: str,
    ) -> None:
        scheme = "https" if method == "CONNECT" else "http"
        authority = f"[{host}]" if ":" in host else host
        decision = self._network_policy.evaluate(
            NetworkOperation(
                url=f"{scheme}://{authority}:{port}/",
                method=method,
                resolved_addresses=addresses,
                interactive=False,
                explicit_authorization=True,
                authorized_targets=entries,
            )
        )
        if decision.action.value != "allow":
            raise EgressScopeError(
                f"target denied by network policy: {decision.rule}"
            )

    def _send_error(self, client: socket.socket, status: int, reason: str) -> None:
        response = (
            f"HTTP/1.1 {status} {reason}\r\n"
            "Connection: close\r\n"
            "Content-Length: 0\r\n\r\n"
        ).encode("ascii")
        try:
            client.sendall(response)
        except OSError:
            return

    def _register_socket(self, sock_obj: socket.socket) -> None:
        with self._lock:
            if self._stopping:
                close_socket(sock_obj)
                return
            self._active_sockets.add(sock_obj)

    def _unregister_socket(self, sock_obj: socket.socket) -> None:
        with self._lock:
            self._active_sockets.discard(sock_obj)

    def _is_stopping(self) -> bool:
        with self._lock:
            return self._stopping


__all__ = ["ContainerHTTPProxy"]
