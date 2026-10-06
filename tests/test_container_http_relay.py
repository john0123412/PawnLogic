"""Local-only checks for the container HTTP Unix-socket relay."""
from pathlib import Path
import tempfile

import pytest
import contextlib
import socket
import subprocess
import sys
import threading


from tools.container_http_relay import ContainerRelay, proxy_environment


@pytest.fixture
def tmp_path():
    parent = Path(__file__).resolve().parents[1] / '.agent-work/tmp'
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='u-', dir=parent) as directory:
        yield Path(directory)


class UnixEcho:
    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(str(path))
        self.sock.listen(8)
        self.sock.settimeout(0.1)
        self.stopped = threading.Event()
        self.clients = []
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.stopped.is_set():
            try:
                client, _ = self.sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            self.clients.append(client)
            thread = threading.Thread(target=self.echo, args=(client,), daemon=True)
            thread.start()

    def echo(self, client):
        with contextlib.suppress(OSError), client:
            while chunk := client.recv(65536):
                client.sendall(chunk)

    def stop(self):
        self.stopped.set()
        self.sock.close()
        for client in self.clients:
            with contextlib.suppress(OSError):
                client.shutdown(socket.SHUT_RDWR)
                client.close()
        self.thread.join(timeout=1)


def test_relay_transfers_bytes_and_revokes_live_connection(tmp_path):
    server = UnixEcho(tmp_path / 'egress.sock')
    relay = ContainerRelay(str(tmp_path / 'egress.sock'))
    try:
        relay.start()
        with socket.create_connection(relay.address, timeout=2) as client:
            client.sendall(b'GET http://target.example/ HTTP/1.1\r\n\r\n')
            assert client.recv(65536).startswith(b'GET http://target.example/')
            relay.stop()
            with contextlib.suppress(ConnectionResetError):
                assert client.recv(65536) == b''
    finally:
        relay.stop()
        server.stop()


def test_proxy_environment_overrides_bypass_and_preserves_other_variables():
    env = proxy_environment({'NO_PROXY':'*','no_proxy':'localhost','ALL_PROXY':'old',
        'HTTP_PROXY':'old','PATH':'keep'}, ('127.0.0.1', 1234))
    for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
        assert env[key] == 'http://127.0.0.1:1234'
    assert env.get('NO_PROXY', '') == env.get('no_proxy', '') == ''
    assert env['ALL_PROXY'] == env['all_proxy'] == env['HTTP_PROXY']
    assert env['PATH'] == 'keep'


def test_unavailable_unix_socket_prevents_user_command(tmp_path):
    marker = tmp_path / 'ran'
    result = subprocess.run([sys.executable, '-m', 'tools.container_http_relay',
        str(tmp_path / 'absent.sock'), '--', sys.executable, '-c',
        f"open({str(marker)!r}, 'w').close()"], capture_output=True, timeout=5)
    assert result.returncode != 0
    assert not marker.exists()
    assert b'SECURITY BLOCK' in result.stderr


def test_wrapper_propagates_command_exit_status(tmp_path):
    server = UnixEcho(tmp_path / 'egress.sock')
    try:
        result = subprocess.run([sys.executable, '-m', 'tools.container_http_relay',
            str(tmp_path / 'egress.sock'), '--', sys.executable, '-c',
            "import os,sys; assert os.environ['http_proxy'].startswith('http://127.0.0.1:'); sys.exit(7)"],
            capture_output=True, timeout=5)
        assert result.returncode == 7, result.stderr
    finally:
        server.stop()


def test_relay_module_uses_only_standard_library():
    import ast
    from pathlib import Path
    tree = ast.parse(Path('tools/container_http_relay.py').read_text())
    modules = {node.module.split('.')[0] for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom) and node.module}
    modules |= {name.name.split('.')[0] for node in ast.walk(tree)
                if isinstance(node, ast.Import) for name in node.names}
    assert modules <= sys.stdlib_module_names | {'__future__'}
