"""Scoped one-shot Docker HTTP transport setup; never changes host networking."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from tools.docker_egress import EGRESS_SCOPE_ENV, parse_egress_scope, resolve_egress_addresses


HTTP_MOUNT = '/pawn-http'


def scoped_mode_error(args: dict[str, Any], *, network: str, language: str,
                      image: str, user: str | None, installs_packages: bool,
                      timeout: int, raw_scope: str | None = None) -> str | None:
    """Fail closed on unsupported scoped executions, including offline mounts."""
    if not (os.environ.get(EGRESS_SCOPE_ENV, '') if raw_scope is None else raw_scope).strip():
        return None
    if args.get('mount_files'):
        return 'SECURITY BLOCK: scoped Docker runs do not allow additional host mounts.'
    if network == 'host':
        return 'SECURITY BLOCK: host networking cannot enforce the Docker egress scope.'
    if network != 'bridge':
        return None
    if language != 'python' or image != 'python:3.12-slim':
        return 'SECURITY BLOCK: scoped HTTP currently requires language=python and the built-in python image.'
    if installs_packages:
        return 'SECURITY BLOCK: scoped HTTP does not support install_deps; use standard-library clients.'
    if user is None or not re.fullmatch(r'[1-9][0-9]*:[0-9]+', user):
        return 'SECURITY BLOCK: scoped HTTP requires an explicit non-root numeric UID:GID or non-root host IDs.'
    if not 1 <= timeout <= 300:
        return 'SECURITY BLOCK: scoped HTTP timeout must be between 1 and 300 seconds.'
    if not hasattr(os, 'getuid') or os.name != 'posix':
        return 'SECURITY BLOCK: scoped HTTP requires a Unix host with Docker Unix-socket bind support.'
    return None


def persistent_scope_error(args: dict[str, Any], *, operation: str, network: str = 'none') -> str | None:
    """Reject unsupported persistent/airlock paths while operator scope is set."""
    if operation not in {'create', 'exec', 'airlock'}:
        return None
    raw = os.environ.get(EGRESS_SCOPE_ENV, '').strip()
    if not raw:
        return None
    _, error = parse_egress_scope(raw)
    if error:
        return f'SECURITY BLOCK: {EGRESS_SCOPE_ENV} is set but invalid: {error}'
    if operation == 'create' and network == 'none' and not args.get('mount_files'):
        return None
    return ('SECURITY BLOCK: operator-scoped networking currently supports only disposable '
            'Python HTTP/CONNECT runs; persistent exec, connected containers, mounts and Airlock are unavailable.')


def start_transport(directory: str, raw_scope: str, resolved_hosts: dict[str, tuple[str, ...]],
                    timeout: int) -> Any:
    """Start the trusted proxy in a private parent; expose only its child mount."""
    from tools.container_http_proxy import ContainerHTTPProxy

    os.mkdir(directory, mode=0o755)
    relay = Path(__file__).with_name('container_http_relay.py').read_bytes()
    destination = Path(directory) / 'relay.py'
    destination.write_bytes(relay)
    destination.chmod(0o644)
    proxy = ContainerHTTPProxy(directory, raw_scope, timeout_seconds=timeout,
        resolved_hosts=resolved_hosts)
    try:
        proxy.start()
        # The random parent remains mode 0700 on the host. The child is mounted
        # read-only and must support the chosen non-root container UID.
        os.chmod(proxy.socket_path, 0o666)
        return proxy
    except BaseException:
        proxy.stop()
        raise


def code_directory(parent: str, scoped: bool) -> str:
    """Keep code and the trusted proxy in separate children of a private parent."""
    directory = os.path.join(parent, 'code') if scoped else parent
    if scoped:
        os.mkdir(directory, mode=0o755)
    return directory


def prepare_transport(parent: str, scoped: bool, raw_scope: str,
                      hosts: dict[str, tuple[str, ...]], timeout: int, command: str,
                      volumes: dict[str, dict[str, str]], start_proxy: Any) -> tuple[Any, list[str]]:
    """Bind the Unix transport without granting a container any external routes."""
    if not scoped:
        return None, ['bash', '-c', command]
    directory = os.path.join(parent, 'transport')
    try:
        proxy = start_proxy(directory, raw_scope, hosts, timeout)
    except Exception as error:
        raise PermissionError(f'SECURITY BLOCK: scoped HTTP proxy setup failed: {error}') from error
    volumes[directory] = {'bind':HTTP_MOUNT, 'mode':'ro'}
    return proxy, ['python3', f'{HTTP_MOUNT}/relay.py', f'{HTTP_MOUNT}/egress.sock',
                   '--', 'bash', '-c', command]


def finish_transport(proxy: Any, container: Any, scoped: bool) -> str | None:
    """Revoke upstream sockets before removing the container; report failures."""
    errors = []
    if proxy is not None:
        try:
            proxy.stop()
        except Exception as error:
            errors.append(f'proxy revocation failed: {error}')
    if container is not None:
        try:
            container.remove(force=True)
        except Exception as error:
            errors.append(f'container removal failed: {error}')
    if scoped and errors:
        return 'SECURITY BLOCK: scoped HTTP cleanup failed; manual cleanup required: ' + '; '.join(errors)
    return None


def scoped_addresses(network: str, raw_scope: str | None = None) -> tuple[dict[str, tuple[str, ...]], str | None, str | None]:
    """Resolve scoped bridge hostnames once, preserving every A/AAAA answer."""
    if network == 'bridge':
        return resolve_egress_addresses(raw_scope)
    return {}, None, None
