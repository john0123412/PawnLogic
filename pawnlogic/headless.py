"""Headless core protocol server (ADR 0011).

Versioned NDJSON over stdio: one JSON object per line in both
directions, every message carrying a `{"v": 1, "type": ...}` envelope.

Request surface (v1): `prompt`, `command`, `interrupt`, `shutdown`. Event vocabulary:
`status`, `stream` (content deltas), `tool` (started/result), `result`,
`error` (with `stage`), `command_result`. Unknown
request types are ignored so the wire can evolve without a handshake.

One process serves exactly one AgentSession, and requests are processed
serially: a turn runs to completion before the next request is read.
The Python core stays authoritative — policies, tools, and provider
routing are never bypassed through this boundary.
"""

from __future__ import annotations

import contextlib
import io
import json
import queue
import sys
import threading
from collections.abc import Callable
from typing import Any

from core.session import TurnInterrupted

PROTOCOL_VERSION = 1


def make_event(event_type: str, **fields: Any) -> dict:
    """Build a wire message with the mandatory version envelope."""
    event: dict = {"v": PROTOCOL_VERSION, "type": event_type}
    event.update(fields)
    return event


def missing_key_detail(session: Any) -> str | None:
    """Return the api_key failure detail for the session's model, or None.

    Unknown aliases return None: they keep the historical fallback to
    DEFAULT_MODEL inside get_provider_config. Shared by `--eval` and the
    headless server so both surfaces report identical pre-flight detail.
    """
    from config.providers import MODELS, validate_api_key

    model_alias = getattr(session, "model_alias", "")
    if not model_alias or model_alias not in MODELS:
        return None
    key_ok, key_env = validate_api_key(model_alias)
    if key_ok:
        return None
    return (
        f"no API key configured for model '{model_alias}' "
        f"— set {key_env} or run /provider"
    )


def final_assistant_text(messages: list) -> str:
    """Return the content of the last non-empty assistant message."""
    return next(
        (
            m.get("content", "")
            for m in reversed(messages)
            if m.get("role") == "assistant" and m.get("content")
        ),
        "",
    )


class HeadlessServer:
    """Drive one session over scripted/stdin request lines.

    Reading happens on a daemon reader thread so an `interrupt` request
    can be dispatched while a prompt turn blocks the main loop. Wire
    emission is lock-protected: turn events are forwarded from the
    scheduler/worker side while request handlers emit from the main
    thread, and the two streams must never interleave mid-line.
    """

    def __init__(
        self,
        session: Any,
        read_line: Callable[[], str | None],
        emit: Callable[[dict], None],
    ) -> None:
        self._session = session
        self._read_line = read_line
        self._user_emit = emit
        self._emit_lock = threading.Lock()

    def _emit(self, event: dict) -> None:
        with self._emit_lock:
            self._user_emit(event)

    # ── wire loop ────────────────────────────────────────

    def serve(self) -> int:
        """Process requests until shutdown/EOF. Returns the exit code."""
        requests: queue.Queue[str | None] = queue.Queue()

        def reader() -> None:
            while True:
                line = self._read_line()
                if line is None:
                    requests.put(None)
                    return
                stripped = line.strip()
                if not stripped:
                    continue
                if self._is_interrupt_request(stripped):
                    # Dispatch immediately: the whole point of interrupt is
                    # to arrive while a prompt turn blocks the main loop.
                    # A handler failure must not wedge the wire loop.
                    try:
                        self._handle_interrupt()
                    except Exception as exc:
                        self._emit(make_event(
                            "error", stage="interrupt", detail=str(exc),
                        ))
                    continue
                requests.put(stripped)

        # The ready event must precede reader startup: an interrupt on the
        # first line would otherwise race the ready status onto the wire.
        self._emit(make_event(
            "status",
            stage="ready",
            model=self._session.model_alias,
            session_id=self._session.session_id,
        ))
        reader_thread = threading.Thread(
            target=reader, name="pawnlogic-headless-reader", daemon=True,
        )
        reader_thread.start()
        while True:
            line = requests.get()
            if line is None:
                return self._shutdown()
            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                self._emit(make_event(
                    "error", stage="protocol",
                    detail=f"malformed JSON line: {exc}",
                ))
                continue
            if not isinstance(request, dict):
                self._emit(make_event(
                    "error", stage="protocol",
                    detail="request must be a JSON object",
                ))
                continue
            request_type = request.get("type")
            if request_type == "shutdown":
                return self._shutdown()
            if request_type == "prompt":
                self._handle_prompt(request)
            elif request_type == "command":
                self._handle_command(request)
            # Unknown request types are ignored per ADR 0011 (§2).

    @staticmethod
    def _is_interrupt_request(line: str) -> bool:
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            return False
        return isinstance(request, dict) and request.get("type") == "interrupt"

    # ── request handlers ─────────────────────────────────

    def _handle_prompt(self, request: dict) -> None:
        text = str(request.get("text", "")).strip()
        if not text:
            self._emit(make_event(
                "error", stage="prompt", detail="prompt.text is required",
            ))
            return

        detail = missing_key_detail(self._session)
        if detail:
            self._emit(make_event("error", stage="api_key", detail=detail))
            return

        unsubscribe = self._subscribe_event_forwarder()
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                self._session.run_turn(text)
        except TurnInterrupted:
            self._emit(make_event("status", stage="turn_interrupted"))
            return
        except Exception as exc:
            self._emit(make_event(
                "error", stage="run_turn", detail=str(exc),
            ))
            return
        finally:
            unsubscribe()

        api_error = getattr(self._session, "last_turn_api_error", None)
        if api_error:
            self._emit(make_event(
                "error", stage="run_turn",
                detail=f"API turn failed: {api_error}",
            ))
            return

        self._emit(make_event(
            "result",
            prompt=text,
            response=final_assistant_text(self._session.messages),
            session_id=self._session.session_id,
            model=self._session.model_alias,
            prompt_tokens=self._session.total_prompt_tokens,
            completion_tokens=self._session.total_completion_tokens,
            tool_calls=self._session.total_tool_calls,
        ))

    def _subscribe_event_forwarder(self) -> Callable[[], None]:
        """Map the session's Agent Events onto the wire while a turn runs.

        The Python core already publishes a typed event stream
        (core.agent_events); this forwarder is the only bridge to the
        headless wire, so event fidelity cannot drift between --eval,
        the REPL, and serve. Sessions without a runtime context (fakes,
        some tests) simply get no live events.
        """
        context = getattr(self._session, "runtime_context", None)
        publisher = getattr(context, "event_publisher", None)
        if publisher is None or not hasattr(publisher, "subscribe"):
            return lambda: None

        def forward(event: Any) -> None:
            kind = getattr(getattr(event, "event_type", None), "value", "")
            payload = getattr(event, "payload", {}) or {}
            if kind == "text.delta":
                text = payload.get("text")
                if isinstance(text, str) and text:
                    self._emit(make_event("stream", text=text))
            elif kind == "tool.started":
                self._emit(make_event(
                    "tool", stage="started",
                    tool_call_id=payload.get("tool_call_id"),
                    tool_name=payload.get("tool_name"),
                    iteration=payload.get("iteration"),
                ))
            elif kind == "tool.result":
                self._emit(make_event(
                    "tool", stage="result",
                    tool_call_id=payload.get("tool_call_id"),
                    tool_name=payload.get("tool_name"),
                    iteration=payload.get("iteration"),
                    status=payload.get("status"),
                    error_type=payload.get("error_type"),
                    side_effect=payload.get("side_effect"),
                ))
            elif kind in ("turn.started", "turn.completed", "turn.failed", "turn.cancelled"):
                stage = "turn_" + kind.split(".", 1)[1]
                fields: dict = {"stage": stage}
                if payload.get("model_alias") is not None:
                    fields["model"] = payload["model_alias"]
                if payload.get("phase") is not None:
                    fields["phase"] = payload["phase"]
                self._emit(make_event("status", **fields))
            # Everything else stays internal to the core.

        return publisher.subscribe(forward)

    def _handle_interrupt(self) -> None:
        """Cancel the active turn; safe to call while a prompt blocks.

        Routes through the scheduler's typed control seam (the same path
        the live REPL's Esc uses): the scheduler cancels its active-turn
        token, which the synchronous executor now forwards into the turn.
        """
        from core.live_turn_control import interrupt_session

        if interrupt_session(self._session):
            self._emit(make_event("status", stage="interrupt_requested"))
        else:
            self._emit(make_event(
                "status", stage="interrupt_ignored",
                detail="no active turn",
            ))

    def _handle_command(self, request: dict) -> None:
        from core.commands import CommandContext, dispatch
        from core.output import JsonSink

        line = str(request.get("line", "")).strip()
        if not line:
            self._emit(make_event(
                "error", stage="command", detail="command.line is required",
            ))
            return
        if not line.startswith("/"):
            line = "/" + line

        parts = line.split(None, 2)
        verb = parts[0].lower()
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured):
                asyncio_run(dispatch(CommandContext(
                    verb=verb,
                    arg=parts[1].strip() if len(parts) > 1 else "",
                    arg2=parts[2].strip() if len(parts) > 2 else "",
                    session=self._session,
                    sink=JsonSink(),
                )))
        except Exception as exc:
            self._emit(make_event(
                "error", stage="command", detail=str(exc),
            ))
            return

        self._emit(make_event(
            "command_result",
            verb=verb,
            output=[out for out in captured.getvalue().splitlines() if out],
        ))

    def _shutdown(self) -> int:
        with contextlib.suppress(Exception):
            self._session.shutdown()
        from core.session import detach_external_mcp_tools
        detach_external_mcp_tools()
        self._emit(make_event("status", stage="shutdown"))
        return 0


def asyncio_run(awaitable: Any) -> Any:
    """Small indirection so tests can patch the event-loop entry if needed."""
    import asyncio
    return asyncio.run(awaitable)


def run_serve(session: Any) -> int:
    """CLI entry: serve the protocol over real stdin/stdout."""
    # Bind the real stdout now: prompt handling redirects sys.stdout into a
    # capture buffer while a turn runs, and in-turn events must still reach
    # the wire, not that buffer.
    wire = sys.stdout

    def read_line() -> str | None:
        raw = sys.stdin.readline()
        return raw if raw else None

    def emit(event: dict) -> None:
        wire.write(json.dumps(event, ensure_ascii=False) + "\n")
        wire.flush()

    return HeadlessServer(session, read_line=read_line, emit=emit).serve()
