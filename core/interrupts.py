"""Readline-compatible process interrupt state.

Live Prompt Toolkit Turns use a per-Turn cancellation token owned by
``TurnScheduler``.  This module intentionally remains only for the serial
readline fallback and legacy signal-handler callers; its process-wide event
must not be used to cancel a background Turn in another session.
"""

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
_active_cancels: dict[int, Callable[[], None]] = {}


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
    """Register one process-wide callback that aborts blocking I/O."""
    with _CANCEL_LOCK:
        _active_cancels[id(callback)] = callback


def clear_cancel_callback(callback: Callable[[], None]) -> None:
    """Unregister one I/O callback only when its identity still matches."""
    with _CANCEL_LOCK:
        callback_id = id(callback)
        if _active_cancels.get(callback_id) is callback:
            del _active_cancels[callback_id]


def cancel_blocking_io() -> None:
    """Abort every active blocking I/O operation registered in this process."""
    with _CANCEL_LOCK:
        callbacks = tuple(_active_cancels.values())
    for callback in callbacks:
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
