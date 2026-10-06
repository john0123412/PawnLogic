"""Docker mount-safety policy (the one-way glass between host and container).

Validates host paths before they are bind-mounted into a sandbox:
- Absolute paths with symlinks resolved.
- RW mode is limited to the workspace directory.
- RO mode is limited to the workspace by default; explicit
  ``allow_host_read_mount`` permits trusted read-only challenge files, but
  credential paths, docker.sock, and sensitive system locations stay denied —
  in both directions (a candidate may not sit under a sensitive path nor be
  an ancestor of one, since mounting an ancestor would expose the sensitive
  location inside the container).

Extracted from tools/docker_sandbox.py as a pure policy module.
"""

from __future__ import annotations

import os

from config import READ_BLACKLIST, WORKSPACE_DIR

SAFE_WORKSPACE = os.path.abspath(os.path.expanduser(WORKSPACE_DIR))
os.makedirs(SAFE_WORKSPACE, exist_ok=True)


def is_under(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


# System locations that must never be host-mounted into a sandbox, even
# read-only. Checked under-only (a candidate inside them is denied).
HOST_SENSITIVE_DIRS = ("/var/run", "/run", "/root", "/etc")


def is_sensitive_host_path(path: str) -> bool:
    if os.path.basename(path) == "docker.sock":
        return True
    real = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
    if real == "/":
        return True
    # Bidirectional check against credential locations: deny the candidate
    # when it is *under* a sensitive path OR when it is an *ancestor* of one
    # (e.g. mounting "/" or "/home" would expose ~/.ssh inside the container).
    for blocked in READ_BLACKLIST:
        blocked_real = os.path.realpath(os.path.abspath(os.path.expanduser(blocked)))
        if is_under(real, blocked_real) or is_under(blocked_real, real):
            return True
    for blocked in HOST_SENSITIVE_DIRS:
        blocked_real = os.path.realpath(blocked)
        if is_under(real, blocked_real) or is_under(blocked_real, real):
            return True
    return False


def check_path_safety(host_path: str, mode: str, *, allow_host_read_mount: bool = False) -> str:
    """
    Validate mount path safety.
    - Resolve absolute paths, removing .. and symlinks.
    - rw mode: path must be inside SAFE_WORKSPACE or PermissionError is raised.
    - ro mode: path must also be inside SAFE_WORKSPACE by default. Explicit
      allow_host_read_mount permits outside read-only challenge files, but
      credential paths, docker.sock, and sensitive system locations
      (/var/run, /run, /root, /etc, /) remain denied — in both directions
      (the candidate may not sit under a sensitive path nor be an ancestor
      of one, since mounting an ancestor would expose it inside the
      container).
    Returns the canonical absolute path string.
    """
    mode = str(mode or "ro").lower()
    if mode not in {"ro", "rw"}:
        raise PermissionError("mount mode must be 'ro' or 'rw'")
    real = os.path.realpath(os.path.abspath(os.path.expanduser(host_path)))
    in_workspace = is_under(real, SAFE_WORKSPACE)
    if is_sensitive_host_path(real):
        raise PermissionError(f"mount path may contain credentials or host control sockets: {real}")
    if mode == "rw" and not in_workspace:
        raise PermissionError(
            f"RW mode is limited to the workspace directory ({SAFE_WORKSPACE}); "
            f"denied path: {real}"
        )
    if mode == "ro" and not in_workspace and not allow_host_read_mount:
        raise PermissionError(
            f"RO mounts are limited to the workspace directory ({SAFE_WORKSPACE}) by default; "
            "set allow_host_read_mount=true only for trusted read-only challenge files. "
            f"denied path: {real}"
        )
    return real
