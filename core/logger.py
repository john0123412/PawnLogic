"""
core/logger.py — PawnLogic unified logging module.

Uses loguru for dual output:
  · terminal   — colorized, INFO and above
  · local file — rotates at 10 MB, retained for 1 week, DEBUG and above

Usage from other modules:
    from core.logger import logger
    logger.info("message")
    logger.warning("warning: {}", detail)
    logger.error("error: {exc}", exc=e)

Initialization, called once from main.py:
    from core.logger import setup_logger
    setup_logger()
"""

import os, sys, json, time
from pathlib import Path

from loguru import logger   # noqa: F401  — exported for `from core.logger import logger`
from core.file_store import ensure_private_dir

# Terminal format.
_FMT_STDERR = (
    "<green>{time:HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> — "
    "<level>{message}</level>"
)

# File format with function for stack tracing.
_FMT_FILE = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level: <8} | "
    "{name}:{function}:{line} — "
    "{message}"
)

# Dedicated tool-call audit log in JSONL format for ELK/Loki-style parsing.
_audit_logger = None


def _safe_default_log_dir() -> Path:
    raw = os.environ.get("PAWNLOGIC_HOME")
    if raw:
        return Path(raw).expanduser() / "logs"
    try:
        home = Path.home()
    except Exception:
        home = Path(os.environ.get("TMPDIR") or "/tmp")
    return (home / ".pawnlogic" / "logs").expanduser()


def _private_log_opener(path: str, flags: int) -> int:
    return os.open(path, flags, 0o600)


def audit_tool_call(
    tool_name: str,
    args_summary: str,
    result_len: int,
    elapsed_ms: int,
    session_id: str = "",
    model_alias: str = "",
    iteration: int = 0,
    success: bool = True,
    metadata: dict | None = None,
) -> None:
    """
    Record a tool-call audit log entry in JSON format.
    Each record contains timestamp, tool name, args summary, result length,
    elapsed time, session id, and related metadata.
    """
    global _audit_logger
    if _audit_logger is None:
        return  # Not initialized yet; skip silently.

    record = {
        "ts":       time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tool":     tool_name,
        "args":     args_summary[:200],
        "result_bytes": result_len,
        "elapsed_ms":  elapsed_ms,
        "success":  success,
        "session":  session_id[:16] if session_id else "",
        "model":    model_alias,
        "iter":     iteration,
    }
    if metadata:
        record["metadata"] = metadata
    try:
        _audit_logger.info(json.dumps(record, ensure_ascii=False))
    except Exception:
        pass  # Audit logging must not block the main flow.


def setup_logger(stderr_level: str = "INFO", file_level: str = "DEBUG") -> None:
    """
    Initialize loguru dual output.
    Call after argparse has completed and the runtime output mode is known.
    Repeated calls remove and rebuild handlers, so this is idempotent.

    Parameters
    ----------
    stderr_level : str
        Minimum terminal output level. Defaults to "INFO".
        Use "CRITICAL" in default user mode or JSON mode to suppress internal
        non-fatal diagnostics on the terminal.
    file_level : str
        Minimum file output level. Defaults to "DEBUG" for full records.
    """
    # Delayed import avoids cycles because config can import before logger setup.
    try:
        from config import LOG_DIR
        log_dir = Path(LOG_DIR)
    except (ImportError, AttributeError):
        # Fall back when LOG_DIR is not available from config.
        log_dir = _safe_default_log_dir()

    # Remove all existing handlers, including loguru's default stderr handler.
    logger.remove()

    # Handler 1: colorized terminal output.
    logger.add(
        sys.stderr,
        level=stderr_level,
        colorize=True,
        format=_FMT_STDERR,
        enqueue=False,          # Write on main thread to preserve print() ordering.
    )

    # Handler 2: rotating local file output.
    ensure_private_dir(log_dir)
    log_file = log_dir / "pawnlogic_{time:YYYY-MM-DD}.log"

    logger.add(
        str(log_file),
        level=file_level,
        rotation="10 MB",       # Rotate files above 10 MB.
        retention="1 week",     # Delete logs older than 1 week.
        compression="zip",      # Compress archives to save disk.
        encoding="utf-8",
        opener=_private_log_opener,
        format=_FMT_FILE,
        backtrace=True,         # Full traceback on exceptions.
        diagnose=True,          # Include local variables for debugging.
        enqueue=True,           # Async file writes so main thread is not blocked.
        catch=True,             # Logger errors must not crash the main program.
    )

    logger.info(
        "Logger initialized | stderr={} file={} log_dir={}",
        stderr_level, file_level, log_dir,
    )

    # Handler 3: tool-call audit log in JSON format.
    global _audit_logger
    try:
        from loguru import logger as _audit
        # Must bind(audit=True), otherwise the filter drops audit records.
        _audit_logger = _audit.bind(audit=True)
        audit_file = log_dir / "audit_{time:YYYY-MM-DD}.jsonl"
        _audit_logger.add(
            str(audit_file),
            level="INFO",
            rotation="10 MB",
            retention="4 weeks",    # Keep audit logs longer.
            compression="zip",
            encoding="utf-8",
            opener=_private_log_opener,
            format="{message}",     # Pure JSON, no extra log formatting.
            enqueue=True,
            catch=True,
            filter=lambda record: record["extra"].get("audit", False),
        )
        logger.debug("Audit logger initialized | file={}", audit_file)
    except Exception:
        _audit_logger = None  # Audit logger failure must not affect the main program.


# Dedicated audit logger instance with audit=True marker.
def get_audit_logger():
    """Return the audit=True logger instance that writes only to the audit file."""
    if _audit_logger is None:
        return logger.bind(audit=False)  # No-op fallback.
    return _audit_logger.bind(audit=True)


__all__ = ["logger", "setup_logger", "audit_tool_call", "get_audit_logger"]
