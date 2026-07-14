"""State and storage helpers for the interactive prompt loop."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any


async def terminal_notice(
    text: str,
    run_in_terminal: Callable[[Callable[[], None]], Awaitable[Any]] | None = None,
) -> None:
    if run_in_terminal is not None:
        await run_in_terminal(lambda: print(text))
    else:
        print(text)


def restore_last_input_buffer(
    buffer: Any,
    last_input: str,
    state: dict[str, str],
) -> bool:
    if not last_input:
        return False
    current = getattr(buffer, "text", "")
    alternate = state.get("alternate", "")
    if current == last_input and alternate:
        target = alternate
        state["alternate"] = last_input
    else:
        if current and current != last_input:
            state["alternate"] = current
        target = last_input
    buffer.text = target
    buffer.cursor_position = len(target)
    return True


def read_text_cache(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def write_text_cache(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.strip() + "\n", encoding="utf-8")
    except Exception:
        return


def safe_write_history(readline_module: Any, path: str) -> None:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        readline_module.write_history_file(path)
    except Exception:
        return


@dataclass(slots=True)
class ReplSignalState:
    last_sigint_time: float = 0.0
    sigint_pending: bool = False
    pending_last_input_restore: bool = False

    def submitted(self) -> None:
        self.sigint_pending = False

    def request_last_input_restore(self) -> None:
        self.pending_last_input_restore = True

    def consume_last_input_restore(self) -> bool:
        requested = self.pending_last_input_restore
        self.pending_last_input_restore = False
        return requested

    def interrupt_requests_exit(
        self,
        *,
        now: float | None = None,
        window_seconds: float = 5.0,
    ) -> bool:
        current = time.monotonic() if now is None else now
        should_exit = self.sigint_pending and (
            current - self.last_sigint_time < window_seconds
        )
        self.last_sigint_time = current
        self.sigint_pending = True
        return should_exit


__all__ = [
    "ReplSignalState",
    "read_text_cache",
    "restore_last_input_buffer",
    "safe_write_history",
    "terminal_notice",
    "write_text_cache",
]
