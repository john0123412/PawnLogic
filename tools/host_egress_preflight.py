#!/usr/bin/env python3
"""Read-only local-host prerequisites, never a privileged helper or installer.

No firewall commands are applied, and no model tool registers this script.
A ready prerequisite report is NOT proof of the ADR 0014 coverage matrix.
"""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

MATRIX_PATHS = (
    "external IPv4", "external IPv6", "DNAT original and reply",
    "host INPUT", "same-bridge peers", "embedded DNS", "alternate DNS",
    "established-flow revocation", "metadata", "additional attachments",
    "hairpin", "IP reuse", "helper/daemon restart",
)
REQUIRED_BINARIES = (
    "docker", "iptables", "ip6tables", "iptables-save", "ip6tables-save",
    "iptables-restore", "ip6tables-restore", "conntrack",
)


def _query(argv: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    return result.returncode == 0, result.stdout


def collect_readiness() -> dict:
    """Inspect the local daemon and noninteractive privilege availability.

    Raw command outputs/errors and environment variables are never reported.
    This developer script must not be installed as a sudoers entry point.
    """
    paths = {name: shutil.which(name) for name in REQUIRED_BINARIES}
    backend = "unknown"
    if paths["docker"]:
        ok, output = _query([
            paths["docker"], "--host", "unix:///var/run/docker.sock", "info",
            "--format", "{{json .FirewallBackend}}",
        ])
        if ok:
            try:
                data = json.loads(output)
                backend = data.get("Driver", "unknown") if isinstance(data, dict) else "unknown"
            except (ValueError, TypeError):
                pass
    administrative = getattr(os, "geteuid", lambda: -1)() == 0
    sudo = shutil.which("sudo")
    if not administrative and sudo:
        administrative, _ = _query([sudo, "-n", "true"])
    blockers = [f"missing_binary:{name}" for name, path in paths.items() if not path]
    if backend != "iptables":
        blockers.append("unsupported_or_unknown_local_backend")
    if not administrative:
        blockers.append("administrator_credentials_unavailable")
    return {
        "schema": 1,
        "local_backend": backend if backend in ("iptables", "nftables") else "unknown",
        "administrator_available": administrative,
        "missing_binaries": [name for name, path in paths.items() if not path],
        "ready_for_admin_validation": not blockers,
        "blockers": blockers,
        "activation_ready": False,
        "firewall_changed": False,
        "matrix": [{"row": n, "path": path, "status": "not_run"}
                   for n, path in enumerate(MATRIX_PATHS, 1)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="write the read-only prerequisite report")
    args = parser.parse_args()
    report = collect_readiness()
    rendered = json.dumps(report, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["ready_for_admin_validation"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
