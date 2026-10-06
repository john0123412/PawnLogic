"""Container creation choke point and one-shot hardening defaults.

PawnLogic containers are never privileged and never gain extra Linux
capabilities — deny-by-policy, not deny-by-omission. Every container creation
funnels through ``spawn_container()``, which rejects the forbidden kwargs and
then merges the one-shot hardening defaults, so tool arguments can neither
inject privilege flags nor supply raw hardening kwargs. Trusted Python
callers can explicitly override read_only and tmpfs; dependency installation
uses the read_only exception. Extracted from
tools/docker_sandbox.py so the funnel stays small, pure, and auditable.
"""

from __future__ import annotations

import os
import re

# Issue #177.5: PawnLogic containers are NEVER privileged and NEVER gain
# extra Linux capabilities — deny-by-policy, not deny-by-omission.
FORBIDDEN_CONTAINER_KWARGS = frozenset({"privileged", "cap_add", "cap_drop", "security_opt"})

# Hardening defaults merged by the funnel itself when a caller opts in with
# ``harden=True``. They are applied AFTER the caller-kwarg deny check, so tool
# arguments cannot supply raw hardening kwargs: model-supplied privileged /
# cap_add / cap_drop / security_opt stay blocked, while one-shot containers
# still get capabilities dropped, a read-only rootfs, and tmpfs scratch.
HARDENING_TMPFS = {"/tmp": "rw,nosuid,size=256m", "/run": "rw,nosuid,size=64m"}

CONTAINER_USER_RE = re.compile(r"^[A-Za-z0-9_.-]+(?::[A-Za-z0-9_.-]+)?$")


def normalize_container_kwarg(key: object) -> str:
    """Normalize SDK and CLI spellings to one canonical kwarg name.

    Covers ``privileged`` / ``--privileged``, ``cap_add`` / ``cap-add`` /
    ``--cap-add``, and the same for ``cap_drop`` / ``security_opt``, so a
    caller cannot dodge the deny-list with an alternate spelling.
    """
    return str(key).strip().lower().lstrip("-").replace("-", "_")


def check_privilege_flags(a: dict) -> str | None:
    """Reject tool arguments requesting container privilege escalation."""
    hit = sorted({normalize_container_kwarg(k) for k in a} & FORBIDDEN_CONTAINER_KWARGS)
    if hit:
        return (
            "SECURITY BLOCK: privileged/capability flags are never permitted in "
            f"PawnLogic containers (rejected: {', '.join(hit)})."
        )
    return None


def spawn_container(client, *args, harden: bool = False, **kwargs):
    """Container creation choke point: privilege-escalation kwargs are forbidden.

    Raises unconditionally (never ``assert``) so the invariant holds even
    under ``python -O``. ``harden=True`` merges the one-shot hardening
    defaults after the deny check; explicit caller values win (``setdefault``).
    """
    bad = sorted({normalize_container_kwarg(k) for k in kwargs} & FORBIDDEN_CONTAINER_KWARGS)
    if bad:
        raise PermissionError(
            "privileged flags forbidden in PawnLogic containers: " + ", ".join(bad)
        )
    if harden:
        kwargs.setdefault("cap_drop", ["ALL"])
        kwargs.setdefault("read_only", True)
        kwargs.setdefault("tmpfs", dict(HARDENING_TMPFS))
    return client.containers.run(*args, **kwargs)


def host_uid_gid() -> str | None:
    """Return host ids, including root, or None when host ids are unavailable."""
    uid = getattr(os, "getuid", None)
    gid = getattr(os, "getgid", None)
    if uid is None or gid is None:
        return None
    return f"{uid()}:{gid()}"


def resolve_container_user(a: dict, *, allow_default: bool) -> tuple[str | None, str | None]:
    """Validate the optional container_user arg and apply the one-shot default.

    ``allow_default=False`` (persistent containers, dependency installs) keeps
    the image default user, which debugging and package installation expect.
    """
    raw = str(a.get("container_user", "")).strip()
    if raw and not CONTAINER_USER_RE.fullmatch(raw):
        return None, "ERROR: invalid container_user (use 'name', 'uid', or 'uid:gid')"
    if raw:
        return raw, None
    if not allow_default:
        return None, None
    return host_uid_gid(), None
