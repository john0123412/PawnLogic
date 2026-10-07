"""Readiness must not imply kernel validation or activation."""

import subprocess

import pytest

from tools import host_egress_preflight as preflight


def configure(monkeypatch, *, backend='{"Driver":"iptables"}', root=False, missing=()):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: None if name in missing else "/usr/bin/" + name)
    monkeypatch.setattr(preflight.os, "geteuid", lambda: 0 if root else 1000)
    calls = []

    def query(argv):
        calls.append(argv)
        return (True, backend) if "docker" in argv[0] else (False, "")

    monkeypatch.setattr(preflight, "_query", query)
    return calls


def test_missing_privilege_and_conntrack_block_without_claiming_matrix_pass(monkeypatch):
    calls = configure(monkeypatch, missing=("conntrack",))
    report = preflight.collect_readiness()
    assert report["blockers"] == ["missing_binary:conntrack", "administrator_credentials_unavailable"]
    assert not report["ready_for_admin_validation"]
    assert not report["activation_ready"] and not report["firewall_changed"]
    assert len(report["matrix"]) == 13
    assert all(row["status"] == "not_run" for row in report["matrix"])
    assert len(calls) == 2
    assert calls[0][1:3] == ["--host", "unix:///var/run/docker.sock"]
    assert calls[1] == ["/usr/bin/sudo", "-n", "true"]


@pytest.mark.parametrize("backend", ['{"Driver":"nftables"}', '{}', 'null', 'bad json'])
def test_unproven_or_unselected_backend_blocks_validation(monkeypatch, backend):
    configure(monkeypatch, backend=backend, root=True)
    report = preflight.collect_readiness()
    assert "unsupported_or_unknown_local_backend" in report["blockers"]
    assert not report["ready_for_admin_validation"]


def test_prerequisites_are_not_activation_evidence(monkeypatch):
    configure(monkeypatch, root=True)
    report = preflight.collect_readiness()
    assert report["ready_for_admin_validation"]
    assert not report["activation_ready"]
    assert all(row["status"] == "not_run" for row in report["matrix"])


@pytest.mark.parametrize("exception", [OSError("error"), subprocess.TimeoutExpired("command", 5)])
def test_query_failure_discards_raw_error_and_output(monkeypatch, exception):
    def run(*args, **kwargs):
        assert kwargs["timeout"] == 5 and not kwargs.get("shell", False)
        raise exception

    monkeypatch.setattr(preflight.subprocess, "run", run)
    assert preflight._query(["/usr/bin/docker", "info"]) == (False, "")
