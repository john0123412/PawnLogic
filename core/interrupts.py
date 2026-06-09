"""Process-local interrupt state for cooperative turn cancellation."""

from __future__ import annotations

import signal
import threading
import sys
import termios
from contextlib import contextmanager
from types import FrameType
from collections.abc import Iterator


_INTERRUPTS = threading.local()


def _event() -> threading.Event:
    event = getattr(_INTERRUPTS, "event", None)
    if event is None:
        event = threading.Event()
        _INTERRUPTS.event = event
    return event


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
