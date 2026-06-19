"""Process-local interrupt state for cooperative turn cancellation."""

from __future__ import annotations

import signal
import threading
import sys
import termios
from contextlib import contextmanager
from types import FrameType
from collections.abc import Callable, Iterator


_INTERRUPT_EVENT = threading.Event()
_CANCEL_LOCK = threading.RLock()
_current_cancel: Callable[[], None] | None = None


def _event() -> threading.Event:
    return _INTERRUPT_EVENT


def request_interrupt() -> None:
    """Mark the current turn as interrupted."""
    _event().set()


def clear_interrupt() -> None:
    """Clear any pending turn-interrupt request."""
    _event().clear()


def interrupted() -> bool:
    """Return whether a turn interrupt has been requested."""
    return _event().is_set()


def raise_if_interrupted() -> None:
    """Raise KeyboardInterrupt when a cooperative interrupt is pending."""
    if interrupted():
        raise KeyboardInterrupt


def set_cancel_callback(callback: Callable[[], None]) -> None:
    """Register a process-wide callback that aborts the active blocking I/O."""
    global _current_cancel
    with _CANCEL_LOCK:
        _current_cancel = callback


def clear_cancel_callback(callback: Callable[[], None]) -> None:
    """Clear the active I/O cancel callback only when it still matches."""
    global _current_cancel
    with _CANCEL_LOCK:
        if _current_cancel is callback:
            _current_cancel = None


def cancel_blocking_io() -> None:
    """Abort the active blocking I/O operation, if one is registered."""
    with _CANCEL_LOCK:
        callback = _current_cancel
    if callback is None:
        return
    try:
        callback()
    except Exception:
        pass


@contextmanager
def turn_interrupt_handler() -> Iterator[None]:
    """Install a SIGINT handler that requests cooperative turn cancellation."""
    previous = signal.getsignal(signal.SIGINT)
    fd: int | None = None
    old_attrs: list[int | bytes] | None = None
    feedback_printed = False

    def _handler(_signum: int, _frame: FrameType | None) -> None:
        nonlocal feedback_printed
        request_interrupt()
        cancel_blocking_io()
        if not feedback_printed:
            feedback_printed = True
            try:
                sys.stdout.write("\n  [interrupt] Stopping current response; returning to edit mode...\n")
                sys.stdout.flush()
            except Exception:
                pass

    clear_interrupt()
    try:
        fd = sys.stdin.fileno()
        old_attrs = termios.tcgetattr(fd)
        echo_flags = getattr(termios, "ECHO", 0) | getattr(termios, "ECHOCTL", 0)
        if echo_flags:
            new_attrs = list(old_attrs)
            new_attrs[3] = new_attrs[3] & ~echo_flags
            termios.tcsetattr(fd, termios.TCSANOW, new_attrs)
    except Exception:
        fd = None
        old_attrs = None

    signal.signal(signal.SIGINT, _handler)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)
        if fd is not None and old_attrs is not None:
            try:
                termios.tcsetattr(fd, termios.TCSANOW, old_attrs)
            except Exception:
                pass
        clear_interrupt()
