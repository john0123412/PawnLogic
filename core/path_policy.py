"""core/path_policy.py - Canonical path containment utilities.

Provides resolve_within() for safe path resolution that prevents directory
traversal attacks, and safe_filename_fragment() for sanitizing user-supplied
strings used in filenames.

These functions never create directories or files; they only validate and
resolve paths.
"""

from __future__ import annotations

import re
from pathlib import Path

# Characters unsafe for filename fragments.
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def resolve_within(root: Path, candidate: str | Path) -> Path:
    """Resolve *candidate* and ensure the result is inside *root*.

    Both *root* and *candidate* are resolved to absolute, symlink-free paths
    before containment is checked.  ``..`` segments, symlinks, and
    sibling-prefix collisions (``/root-evil`` vs ``/root``) are all handled
    correctly.

    Raises ``ValueError`` if the resolved path escapes *root*.

    This function is pure: it reads the filesystem only to resolve symlinks.
    It never creates directories or files.
    """
    root_resolved = root.expanduser().resolve()
    # If root itself doesn't exist yet, resolve() still returns an absolute
    # path; that's fine for containment checks.
    candidate_path = Path(candidate)
    if candidate_path.is_absolute():
        resolved = candidate_path.resolve()
    else:
        resolved = (root_resolved / candidate_path).resolve()

    # Use relative_to() which rejects prefix matches and requires true
    # ancestry.  A ValueError here means the path escaped root.
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise ValueError(f"path '{candidate}' escapes root '{root}'") from None

    return resolved


def safe_filename_fragment(value: str, *, fallback: str = "unnamed") -> str:
    """Sanitize *value* into a string safe for use inside a filename.

    Strips path separators, ``..`` segments, and any character outside
    ``[A-Za-z0-9._-]``.  Returns *fallback* if the result would be empty.
    """
    # Strip path separators and parent-directory references.
    cleaned = value.replace("\\", "/")
    parts = [seg for seg in cleaned.split("/") if seg and seg != ".."]
    joined = "_".join(parts)
    sanitized = _UNSAFE_FILENAME.sub("_", joined).strip("._")
    return sanitized or fallback
