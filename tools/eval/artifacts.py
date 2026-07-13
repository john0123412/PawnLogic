"""tools/eval/artifacts.py - Atomic artifact writing for runtime evaluation.

Provides unique run IDs and atomic JSONL artifact replacement.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from tools.eval.contracts import RuntimeEvalRecord


def unique_run_id() -> str:
    """Generate a unique run ID using timestamp and random suffix."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = os.urandom(4).hex()
    return f"{stamp}-{suffix}"


def write_artifact_atomic(
    records: Sequence[RuntimeEvalRecord],
    *,
    output_dir: Path,
    suite: str,
) -> Path:
    """Write evaluation records to a JSONL artifact atomically.

    Uses temp-file-then-rename to prevent partial writes from being read.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = output_dir / f"{stamp}-{suite}.jsonl"

    # Write to a temp file first, then atomically rename.
    fd, tmp_path = tempfile.mkstemp(
        dir=str(output_dir), suffix=".tmp", prefix=f"{suite}-"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record.to_json(), sort_keys=True) + "\n")
        os.replace(tmp_path, target)
    except BaseException:
        # Clean up temp file on failure.
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
    return target
