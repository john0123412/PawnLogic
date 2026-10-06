"""Enforcement must reach the Docker boundary, not only proxy environment hints."""
import os
import tempfile
from pathlib import Path

import pytest

from tools import docker_egress, docker_sandbox


class Client:
    def __init__(self, events):
        self.events = events
        self.calls = []
        self.images = self
        self.containers = self

    def get(self, image):
        return object()

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self

    def wait(self, timeout):
        return {'StatusCode':0}

    def logs(self, stdout=True, stderr=False):
        return b'ok\n' if stdout else b''

    def remove(self, force=False):
        self.events.append('remove')


def setup_scope(monkeypatch):
    monkeypatch.setenv('PAWNLOGIC_DOCKER_EGRESS_ALLOW', 'ctf.example.com,10.0.0.0/8')
    monkeypatch.delenv('PAWNLOGIC_DOCKER_ALLOW_NETWORK', raising=False)
    monkeypatch.setattr(docker_egress, 'egress_resolver', lambda host: ('93.184.216.34',))
    monkeypatch.setattr('tools.docker_spawn.host_uid_gid', lambda: '1000:1000')


def test_scoped_run_has_no_bridge_and_revokes_before_removal(monkeypatch):
    setup_scope(monkeypatch)
    events = []
    client = Client(events)
    monkeypatch.setattr(docker_sandbox, '_get_docker_client', lambda: client)

    class Proxy:
        def stop(self):
            events.append('revoke')

    def start(directory, raw_scope, hosts, timeout):
        assert raw_scope == 'ctf.example.com,10.0.0.0/8'
        assert hosts == {'ctf.example.com':('93.184.216.34',)}
        assert timeout == 30
        assert os.stat(Path(directory).parent).st_mode & 0o777 == 0o700
        events.append('start')
        return Proxy()

    monkeypatch.setattr(docker_sandbox, 'start_transport', start)
    result = docker_sandbox.tool_run_code_docker({'language':'python','code':'print(1)',
        'network':'bridge','allow_network':True})
    assert 'network: none' in result and 'egress: enforced HTTP/CONNECT' in result
    assert len(client.calls) == 1
    kwargs = client.calls[0]
    assert kwargs['network_mode'] == 'none'
    assert kwargs['cap_drop'] == ['ALL'] and kwargs['read_only']
    assert 'extra_hosts' not in kwargs
    assert kwargs['command'][:4] == ['python3','/pawn-http/relay.py','/pawn-http/egress.sock','--']
    mounts = kwargs['volumes']
    assert {spec['bind'] for spec in mounts.values()} == {'/code','/pawn-http'}
    assert next(spec for spec in mounts.values() if spec['bind']=='/pawn-http')['mode']=='ro'
    assert events == ['start','revoke','remove']


@pytest.mark.parametrize('extra', [
    {'network':'host'}, {'language':'bash'}, {'image':'custom/python'},
    {'container_user':'root'}, {'install_deps':'requests'}, {'timeout':0},
    {'mount_files':{'challenge':{'bind':'/pawn-http','mode':'ro'}}},
])
def test_unsupported_scoped_paths_deny_before_docker(monkeypatch, extra):
    setup_scope(monkeypatch)
    monkeypatch.setattr(docker_sandbox, '_get_docker_client',
        lambda: pytest.fail('unsupported scope must not touch Docker'))
    result = docker_sandbox.tool_run_code_docker({'language':'python','code':'print(1)',
        'network':'bridge','allow_network':True, **extra})
    assert result.startswith('SECURITY BLOCK:'), result


@pytest.mark.parametrize('action', ['create','exec'])
def test_scoped_persistent_networking_is_not_a_bypass(monkeypatch, action):
    setup_scope(monkeypatch)
    monkeypatch.setattr(docker_sandbox, '_get_docker_client',
        lambda: pytest.fail('persistent scope must reject before Docker'))
    result = docker_sandbox.tool_pwn_container({'action':action,'name':'lab','command':'true',
        'network':'bridge','allow_network':True})
    assert result.startswith('SECURITY BLOCK:')


def test_airlock_cannot_bypass_scope(monkeypatch):
    setup_scope(monkeypatch)
    monkeypatch.setattr(docker_sandbox, '_get_docker_client',
        lambda: pytest.fail('Airlock scope must reject before Docker'))
    result = docker_sandbox.tool_install_package({'container_name':'lab','pkg_manager':'pip',
        'packages':['requests'],'allow_network':True})
    assert result.startswith('SECURITY BLOCK:')


def test_proxy_setup_failure_never_spawns_a_bridge_container(monkeypatch):
    setup_scope(monkeypatch)
    client = Client([])
    monkeypatch.setattr(docker_sandbox, '_get_docker_client', lambda: client)
    def fail(*args):
        raise OSError('Unix proxy unavailable')
    monkeypatch.setattr(docker_sandbox, 'start_transport', fail)
    result = docker_sandbox.tool_run_code_docker({'language':'python','code':'print(1)',
        'network':'bridge','allow_network':True})
    assert result.startswith('SECURITY BLOCK:')
    assert client.calls == []


@pytest.mark.parametrize('network', ['bridge', 'host', None])
def test_spawn_funnel_never_grants_unfiltered_network_with_scope(monkeypatch, network):
    from tools.docker_spawn import spawn_container
    setup_scope(monkeypatch)
    client = Client([])
    kwargs = {} if network is None else {'network_mode':network}
    with pytest.raises(PermissionError, match='scoped networking'):
        spawn_container(client, image='python:3.12-slim', **kwargs)
    assert client.calls == []


@pytest.mark.parametrize('key', ['network', 'networking_config', 'links', 'host_config', '--network-mode'])
def test_scoped_funnel_rejects_alternate_network_configuration(monkeypatch, key):
    from tools.docker_spawn import spawn_container
    setup_scope(monkeypatch)
    client = Client([])
    with pytest.raises(PermissionError, match='scoped networking'):
        spawn_container(client, image='python:3.12-slim', network_mode='none', **{key:'bridge'})
    assert client.calls == []


@pytest.mark.parametrize('proxy_error,container_error', [(True,False),(False,True),(True,True)])
def test_scoped_cleanup_errors_are_never_success(proxy_error, container_error):
    from tools.docker_http import finish_transport
    events = []
    class Proxy:
        def stop(self):
            events.append('revoke')
            if proxy_error:
                raise OSError('revocation unavailable')
    class Container:
        def remove(self, force):
            events.append('remove')
            if container_error:
                raise OSError('daemon unavailable')
    result = finish_transport(Proxy(), Container(), True)
    assert result.startswith('SECURITY BLOCK:') and 'manual cleanup required' in result
    assert events == ['revoke','remove']


def test_scope_snapshot_keeps_all_answers_and_ignores_environment_change(monkeypatch):
    setup_scope(monkeypatch)
    calls = []
    def resolver(host):
        calls.append(host)
        monkeypatch.setenv('PAWNLOGIC_DOCKER_EGRESS_ALLOW', 'other.example.com')
        return ('93.184.216.34','2606:2800:220:1:248:1893:25c8:1946')
    monkeypatch.setattr(docker_egress, 'egress_resolver', resolver)
    addresses, fingerprint, error = docker_egress.resolve_egress_addresses('ctf.example.com')
    assert calls == ['ctf.example.com'] and error is None and fingerprint
    assert len(addresses['ctf.example.com']) == 2


def test_transport_permissions_preserve_private_parent_and_nonroot_socket_access():
    from tools.docker_http import code_directory, start_transport
    parent = Path(__file__).resolve().parents[1] / '.agent-work/tmp'
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='u-', dir=parent) as directory:
        code = Path(code_directory(directory, True))
        transport = Path(directory) / 'transport'
        proxy = start_transport(str(transport), 'ctf.example.com',
                                {'ctf.example.com': ('93.184.216.34',)}, 5)
        try:
            assert Path(directory).stat().st_mode & 0o777 == 0o700
            assert code.stat().st_mode & 0o777 == 0o755
            assert transport.stat().st_mode & 0o777 == 0o755
            assert (transport / 'relay.py').stat().st_mode & 0o777 == 0o644
            assert proxy.socket_path.stat().st_mode & 0o777 == 0o666
        finally:
            proxy.stop()
