"""Standard-library container launcher for a per-operation Unix HTTP proxy.

Mounted into a network=none Python container. Proxy variables help clients;
Docker's absent external routes, not these variables, provide the isolation.
"""
from __future__ import annotations

import contextlib
import os
import select
import socket
import subprocess
import sys
import threading


class ContainerRelay:
    """Bounded loopback-to-Unix byte relay with explicit socket revocation."""

    def __init__(self, socket_path: str):
        self.socket_path = socket_path
        self.address = ('127.0.0.1', 0)
        self._listener: socket.socket | None = None
        self._stopped = threading.Event()
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(16)
        self._sockets: set[socket.socket] = set()
        self._threads: set[threading.Thread] = set()
        self._accept_thread: threading.Thread | None = None

    def start(self) -> None:
        if self._stopped.is_set() or self._listener is not None:
            raise RuntimeError('relay cannot be restarted')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(2)
            probe.connect(self.socket_path)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(('127.0.0.1', 0))
            listener.listen(16)
            listener.settimeout(0.1)
            self.address = listener.getsockname()
            self._listener = listener
            self._accept_thread = threading.Thread(target=self._accept, daemon=True)
            self._accept_thread.start()
        except BaseException:
            listener.close()
            raise

    def _accept(self) -> None:
        listener = self._listener
        if listener is None:
            return
        while not self._stopped.is_set():
            try:
                client, _ = listener.accept()
            except TimeoutError:
                continue
            except (OSError, AttributeError):
                break
            if not self._slots.acquire(blocking=False):
                client.close()
                continue
            with self._lock:
                if self._stopped.is_set():
                    client.close()
                    self._slots.release()
                    break
                self._sockets.add(client)
                worker = threading.Thread(target=self._handle, args=(client,), daemon=True)
                self._threads.add(worker)
                worker.start()

    def _handle(self, client: socket.socket) -> None:
        upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            with self._lock:
                if self._stopped.is_set():
                    return
                self._sockets.add(upstream)
            upstream.settimeout(2)
            upstream.connect(self.socket_path)
            client.settimeout(10)
            upstream.settimeout(10)
            reading = [client, upstream]
            while reading and not self._stopped.is_set():
                ready, _, _ = select.select(reading, [], [], 0.1)
                for source in ready:
                    target = upstream if source is client else client
                    chunk = source.recv(65536)
                    if chunk:
                        target.sendall(chunk)
                    else:
                        reading.remove(source)
                        with contextlib.suppress(OSError):
                            target.shutdown(socket.SHUT_WR)
        except (OSError, ValueError):
            pass
        finally:
            with self._lock:
                self._sockets.discard(client)
                self._sockets.discard(upstream)
                self._threads.discard(threading.current_thread())
            client.close()
            upstream.close()
            self._slots.release()

    def stop(self) -> None:
        self._stopped.set()
        if self._listener is not None:
            self._listener.close()
        with self._lock:
            sockets = tuple(self._sockets)
            workers = tuple(self._threads)
        for active in sockets:
            with contextlib.suppress(OSError):
                active.shutdown(socket.SHUT_RDWR)
                active.close()
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=1)
        for worker in workers:
            worker.join(timeout=0.2)


def proxy_environment(environment: dict[str, str], address: tuple[str, int]) -> dict[str, str]:
    """Override client proxy/bypass settings without copying host credentials."""
    result = {key: value for key, value in environment.items()
              if key.lower() not in {'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'}}
    url = f'http://{address[0]}:{address[1]}'
    result.update(HTTP_PROXY=url, HTTPS_PROXY=url, http_proxy=url, https_proxy=url,
                  ALL_PROXY=url, all_proxy=url, NO_PROXY='', no_proxy='')
    return result


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 3 or args[1] != '--':
        print('Usage: relay.py <unix-socket> -- <command> [args...]', file=sys.stderr)
        return 2
    relay = ContainerRelay(args[0])
    try:
        relay.start()
        return subprocess.call(args[2:], env=proxy_environment(dict(os.environ), relay.address))
    except (OSError, RuntimeError) as error:
        print(f'SECURITY BLOCK: container HTTP relay unavailable: {error}', file=sys.stderr)
        return 125
    finally:
        relay.stop()


if __name__ == '__main__':
    raise SystemExit(main())
