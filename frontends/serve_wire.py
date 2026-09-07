"""Wire client + latency instrumentation for the headless serve protocol.

Phase 2a (ADR 0011): a reference client that drives `pawn serve` over the
versioned NDJSON wire and measures the interaction latencies a native
frontend will see. The wire layer (ServeWire) is UI-free and fully
unit-testable; `python -m frontends.ptk_client` adds a minimal Prompt
Toolkit shell on top.

Semantics mirror the live REPL after P2-0:
  * Enter with an active turn sends `prompt` + `"steer": true`.
  * Esc sends `interrupt`.
  * `/quit` shuts the server down gracefully.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import threading
import time
from collections.abc import Callable
from typing import Any

PROTOCOL_VERSION = 1


class LatencyRecorder:
    """Collect timestamped protocol milestones into a latency report."""

    def __init__(self) -> None:
        self._t_send_prompt: float | None = None
        self._t_send_interrupt: float | None = None
        self._waiting_turn_started = False
        self._waiting_turn_cancelled = False
        self.turn_start_latencies_ms: list[float] = []
        self.interrupt_latencies_ms: list[float] = []
        self.chunk_gap_ms: list[float] = []
        self._t_last_chunk: float | None = None

    def on_prompt_sent(self) -> None:
        self._t_send_prompt = time.monotonic()
        self._waiting_turn_started = True
        self._t_last_chunk = None

    def on_interrupt_sent(self) -> None:
        self._t_send_interrupt = time.monotonic()
        if self.turn_start_latencies_ms:
            self._waiting_turn_cancelled = True

    def on_event(self, event: dict) -> None:
        kind = event.get("type")
        now = time.monotonic()
        if kind == "status":
            stage = event.get("stage")
            if stage == "turn_started" and self._waiting_turn_started:
                if self._t_send_prompt is not None:
                    self.turn_start_latencies_ms.append(
                        round((now - self._t_send_prompt) * 1000, 1)
                    )
                self._waiting_turn_started = False
            elif stage == "turn_cancelled" and self._waiting_turn_cancelled:
                if self._t_send_interrupt is not None:
                    self.interrupt_latencies_ms.append(
                        round((now - self._t_send_interrupt) * 1000, 1)
                    )
                self._waiting_turn_cancelled = False
        elif kind == "stream":
            if self._t_last_chunk is not None:
                self.chunk_gap_ms.append(round((now - self._t_last_chunk) * 1000, 1))
            self._t_last_chunk = now

    def report(self) -> dict:
        def stats(values: list[float]) -> dict | None:
            if not values:
                return None
            ordered = sorted(values)
            mid = ordered[len(ordered) // 2]
            return {
                "n": len(values),
                "min_ms": ordered[0],
                "median_ms": mid,
                "max_ms": ordered[-1],
            }

        return {
            "prompt_to_turn_started": stats(self.turn_start_latencies_ms),
            "interrupt_to_turn_cancelled": stats(self.interrupt_latencies_ms),
            "stream_chunk_gap": stats(self.chunk_gap_ms),
        }


class ServeWire:
    """Spawn `pawn serve` and speak the NDJSON protocol over stdio.

    Reading happens on a daemon thread (the server pushes events at any
    time); writes happen from the UI thread. `on_event` is invoked for
    every parsed server message and `on_exit` when the process dies.
    """

    def __init__(
        self,
        server_cmd: list[str],
        *,
        on_event: Callable[[dict], None],
        on_exit: Callable[[], None],
    ) -> None:
        self._on_event = on_event
        self._on_exit = on_exit
        self._proc = subprocess.Popen(
            server_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._lock = threading.Lock()
        self._alive = True
        self._reader = threading.Thread(
            target=self._read_loop, name="serve-wire-reader", daemon=True
        )
        self._reader.start()

    def send(self, request: dict) -> None:
        if self._proc.stdin is None or not self._alive:
            return
        with self._lock:
            try:
                self._proc.stdin.write(
                    json.dumps(request, ensure_ascii=False) + "\n"
                )
                self._proc.stdin.flush()
            except (BrokenPipeError, ValueError):
                self._alive = False

    def close(self) -> None:
        self._alive = False
        with contextlib.suppress(Exception):
            self._proc.terminate()

    def _read_loop(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                self._on_event(event)
        self._alive = False
        self._on_exit()


def build_request(
    kind: str, text: str = "", *, steer: bool = False
) -> dict:
    """Build one versioned request for the v1 wire."""
    request: dict[str, Any] = {"v": PROTOCOL_VERSION, "type": kind}
    if kind == "prompt":
        request["text"] = text
        request["steer"] = bool(steer)
    return request
