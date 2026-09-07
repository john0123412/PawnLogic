"""Tests for the Phase 2a serve-protocol client (frontends/).

Covers the latency recorder state machine and the wire layer against a
scripted fake `pawn serve` subprocess — no real API calls.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from pathlib import Path


from frontends.serve_wire import LatencyRecorder, ServeWire, build_request

ROOT = Path(__file__).resolve().parent.parent

FAKE_SERVER = textwrap.dedent(
    """
    import json, sys, time

    events = [
        {"v": 1, "type": "status", "stage": "ready"},
        {"v": 1, "type": "status", "stage": "turn_started"},
        {"v": 1, "type": "stream", "text": "hel"},
        {"v": 1, "type": "stream", "text": "lo"},
        {"v": 1, "type": "result", "response": "hello"},
        {"v": 1, "type": "status", "stage": "shutdown"},
    ]
    for line in sys.stdin:
        request = json.loads(line)
        if request.get("type") == "prompt":
            for event in events:
                print(json.dumps(event), flush=True)
                time.sleep(0.01)
        elif request.get("type") == "shutdown":
            print(json.dumps({"v": 1, "type": "status", "stage": "shutdown"}), flush=True)
            break
    """
)


def _collect_events(cmd: list[str], requests: list[dict], timeout: float = 10.0):
    """Drive one ServeWire through `requests`, returning all events."""
    events: list[dict] = []
    done = threading_done = None
    import threading

    finished = threading.Event()

    wire = ServeWire(
        cmd, on_event=events.append, on_exit=finished.set
    )
    for request in requests:
        wire.send(request)
        time.sleep(0.05)
    assert finished.wait(timeout=timeout), "fake server did not exit"
    del done, threading_done
    return events


def test_build_request_shapes_v1_envelope():
    assert build_request("shutdown") == {"v": 1, "type": "shutdown"}
    prompt = build_request("prompt", "hi", steer=True)
    assert prompt == {"v": 1, "type": "prompt", "text": "hi", "steer": True}


def test_latency_recorder_prompt_to_turn_started():
    recorder = LatencyRecorder()
    recorder.on_prompt_sent()
    time.sleep(0.02)
    recorder.on_event({"type": "status", "stage": "turn_started"})
    report = recorder.report()
    stats = report["prompt_to_turn_started"]
    assert stats is not None and stats["n"] == 1
    assert 5 <= stats["median_ms"] <= 2000


def test_latency_recorder_interrupt_to_turn_cancelled():
    recorder = LatencyRecorder()
    # The interrupt latency only counts when a turn was observed running.
    recorder.on_prompt_sent()
    recorder.on_event({"type": "status", "stage": "turn_started"})
    recorder.on_interrupt_sent()
    time.sleep(0.02)
    recorder.on_event({"type": "status", "stage": "turn_cancelled"})
    stats = recorder.report()["interrupt_to_turn_cancelled"]
    assert stats is not None and stats["n"] == 1


def test_latency_recorder_ignores_cancelled_without_running_turn():
    recorder = LatencyRecorder()
    recorder.on_interrupt_sent()
    recorder.on_event({"type": "status", "stage": "turn_cancelled"})
    assert recorder.report()["interrupt_to_turn_cancelled"] is None


def test_latency_recorder_chunk_gaps():
    recorder = LatencyRecorder()
    recorder.on_event({"type": "stream", "text": "a"})
    time.sleep(0.03)
    recorder.on_event({"type": "stream", "text": "b"})
    stats = recorder.report()["stream_chunk_gap"]
    assert stats is not None and stats["n"] == 1


def test_serve_wire_against_fake_server():
    server_path = Path("/tmp/pawnlogic_fake_server.py")
    server_path.write_text(FAKE_SERVER, encoding="utf-8")
    events = _collect_events(
        [sys.executable, str(server_path)],
        [build_request("prompt", "hi"), build_request("shutdown")],
    )
    kinds = [event.get("type") for event in events]
    assert "status" in kinds and "stream" in kinds and "result" in kinds
    assert events[0]["stage"] == "ready"
    assert events[-1]["stage"] == "shutdown"


def test_wire_request_reaches_server_stdin():
    """The server must observe the exact v1 envelope the client sent."""
    script = textwrap.dedent(
        """
        import json, sys
        for line in sys.stdin:
            request = json.loads(line)
            print(json.dumps({"v": 1, "type": "echo", "seen": request}), flush=True)
            if request.get("type") == "shutdown":
                break
        """
    )
    server_path = Path("/tmp/pawnlogic_echo_server.py")
    server_path.write_text(script, encoding="utf-8")
    events = _collect_events(
        [sys.executable, str(server_path)],
        [build_request("prompt", "steer me", steer=True), build_request("shutdown")],
    )
    seen = [event for event in events if event.get("type") == "echo"]
    prompt_echoes = [
        event for event in seen if event["seen"].get("type") == "prompt"
    ]
    assert prompt_echoes
    assert prompt_echoes[-1]["seen"]["steer"] is True
    assert prompt_echoes[-1]["seen"]["v"] == 1


def test_fake_server_module_is_invokable():
    """Sanity: the fixture used above is valid Python and runnable."""
    proc = subprocess.run(
        [sys.executable, "-c", "import ast; ast.parse(open('/tmp/pawnlogic_fake_server.py').read())"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
