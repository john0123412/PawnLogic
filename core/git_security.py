"""Shared git transport safety helpers."""

from __future__ import annotations

import re
from urllib.parse import urlparse

GIT_SAFE_PROTOCOL_CONFIG = [
    "-c",
    "protocol.ext.allow=never",
    "-c",
    "protocol.fd.allow=never",
    "-c",
    "protocol.file.allow=never",
]

_SCP_LIKE_REMOTE = re.compile(r"^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+:[^\s]+$")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def is_allowed_git_remote(remote: str) -> bool:
    """Return whether a user-supplied git remote uses an allowed transport."""
    value = str(remote or "").strip()
    if not value or _CONTROL_CHARS.search(value):
        return False
    if value.startswith("git@"):
        return bool(_SCP_LIKE_REMOTE.fullmatch(value))

    parsed = urlparse(value)
    if parsed.scheme not in {"https", "ssh"}:
        return False
    return bool(parsed.netloc)


def git_remote_error(remote: str) -> str:
    value = str(remote or "").strip() or "(empty)"
    return (
        f"unsupported git remote '{value}'. Only https://, ssh://, and "
        "git@host:owner/repo.git remotes are allowed."
    )


def git_with_safe_protocol_config(*args: str) -> list[str]:
    """Return a git argv with dangerous transports disabled explicitly."""
    return ["git", *GIT_SAFE_PROTOCOL_CONFIG, *args]


__all__ = [
    "GIT_SAFE_PROTOCOL_CONFIG",
    "git_remote_error",
    "git_with_safe_protocol_config",
    "is_allowed_git_remote",
]
