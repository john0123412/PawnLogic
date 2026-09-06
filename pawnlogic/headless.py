"""Headless core protocol server (ADR 0011).

Versioned NDJSON over stdio: one JSON object per line in both
directions, every message carrying a `{"v": 1, "type": ...}` envelope.

Request surface (v1): `prompt` (with optional `"steer": true` for the
active turn), `command`, `interrupt`, `shutdown`. Event vocabulary:
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
import traceback
from collections.abc import Callable
from typing import Any

from core.persistence import session_load
from core.session import (
    AgentSession,
    TurnInterrupted,
    detach_external_mcp_tools,
)
from core.state import state as _runtime_state
from utils.ansi import RED, c

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

        if bool(request.get("steer")):
            self._handle_steer(text)
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

        An interrupt can legally arrive in the window between a prompt
        request being read and the scheduler registering the turn (the
        reader thread runs ahead). Declining there is a race, not a
        user error, so the request is retried briefly before reporting
        `interrupt_ignored`.
        """
        import time

        from core.live_turn_control import interrupt_session

        deadline = time.monotonic() + 2.0
        while True:
            if interrupt_session(self._session):
                self._emit(make_event("status", stage="interrupt_requested"))
                return
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        self._emit(make_event(
            "status", stage="interrupt_ignored",
            detail="no active turn",
        ))

    def _handle_steer(self, text: str) -> None:
        """Queue a steer for the active turn (prompt with "steer": true).

        The steer is delivered at the next Tool safe point of the running
        turn, or — when the turn settles first — starts as a fresh turn
        from the queue lanes. Requires an active turn; without one a plain
        prompt request is the correct call.
        """
        from core.turn_scheduler import Submission, SubmissionKind

        scheduler = getattr(self._session, "_turn_scheduler", None)
        view = getattr(scheduler, "view", None)
        if scheduler is None or view is None or view().active is None:
            self._emit(make_event(
                "error", stage="steer",
                detail="steer requires an active turn; send a prompt instead",
            ))
            return
        try:
            scheduler.submit(
                Submission(text, kind=SubmissionKind.STEER, source="serve")
            )
        except Exception as exc:
            self._emit(make_event("error", stage="steer", detail=str(exc)))
            return
        self._emit(make_event("status", stage="steer_queued"))

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


# ════════════════════════════════════════════════════════
# Stage-2: --eval single-shot execution mode.
# Lives here (not cli.py) so the one-shot headless entry and the
# serve protocol share one module and one architecture budget.
# ════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════
# Stage-2: --eval single-shot execution mode
# ════════════════════════════════════════════════════════

async def _run_eval_mode(session: AgentSession, args: Any, sink: Any) -> None:
    """Single-shot run: execute one prompt and exit.

    Behavior:
      · If `--session <id>` is given, load that session first; on failure
        emit a structured error and exit non-zero.
      · Run `session.run_turn(args.eval)`. In human (default) mode, the
        agent's streaming output flows directly to stdout exactly as it
        would in the REPL.
      · In JSON mode the streaming output is captured (so the JSON wire
        stays clean), and a single structured `result` event is emitted
        from the final assistant message in `session.messages`.
      · If the turn fails at the API level (retries exhausted, circuit
        breaker open), emit a structured error and exit non-zero.
      · A missing provider key for the selected model exits 2 before any
        API call is attempted.
      · Always shut down MCP subprocesses on exit.
    """
    is_json = bool(args.json)

    # 1. Optionally load a saved session before running.
    if args.session:
        result = session_load(session, args.session)
        if not result.startswith("OK"):
            if is_json:
                sink.print_json({
                    "type":  "error",
                    "stage": "session_load",
                    "query": args.session,
                    "detail": result,
                })
            else:
                sink.print(c(RED, f"  ✗ Session load failed: {result}"))
            detach_external_mcp_tools()
            sys.exit(2)

    # 2. Fail fast on a missing provider key: a 401 cannot recover, so
    #    spending the retry/circuit-breaker budget on it only wastes time.
    #    Shared with the headless server so both surfaces agree on the
    #    pre-flight semantics (unknown aliases keep the historical
    #    DEFAULT_MODEL fallback).
    from pawnlogic.headless import final_assistant_text, missing_key_detail

    detail = missing_key_detail(session)
    if detail:
        if is_json:
            sink.print_json({
                "type":   "error",
                "stage":  "api_key",
                "detail": detail,
            })
        else:
            sink.print(c(RED, f"  ✗ {detail}"))
        detach_external_mcp_tools()
        sys.exit(2)

    # 3. Execute one turn.
    if is_json:
        # Suppress streaming prints so the JSON wire stays valid;
        # we re-emit the final assistant text as a structured event.
        import contextlib
        import io
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                session.run_turn(args.eval)
        except Exception as exc:
            sink.print_json({
                "type":   "error",
                "stage":  "run_turn",
                "detail": str(exc),
            })
            detach_external_mcp_tools()
            sys.exit(1)

        api_error = getattr(session, "last_turn_api_error", None)
        if api_error:
            # The turn ended without raising (stream errors are consumed by
            # the retry/circuit-breaker layer); signal failure via exit code.
            sink.print_json({
                "type":   "error",
                "stage":  "run_turn",
                "detail": f"API turn failed: {api_error}",
                "session_id":        session.session_id,
                "model":             session.model_alias,
                "prompt_tokens":     session.total_prompt_tokens,
                "completion_tokens": session.total_completion_tokens,
                "tool_calls":        session.total_tool_calls,
            })
            detach_external_mcp_tools()
            sys.exit(1)

        last_assistant = final_assistant_text(session.messages)
        sink.print_json({
            "type":         "result",
            "prompt":       args.eval,
            "response":     last_assistant,
            "session_id":   session.session_id,
            "model":        session.model_alias,
            "prompt_tokens":     session.total_prompt_tokens,
            "completion_tokens": session.total_completion_tokens,
            "tool_calls":        session.total_tool_calls,
        })
    else:
        # Human mode — let run_turn print directly, exactly as in the REPL.
        try:
            session.run_turn(args.eval)
        except Exception as exc:
            sink.print(c(RED, f"  ✗ {exc}"))
            if _runtime_state.debug_mode:
                traceback.print_exc()
            detach_external_mcp_tools()
            sys.exit(1)

        api_error = getattr(session, "last_turn_api_error", None)
        if api_error:
            sink.print(c(RED, f"  ✗ API turn failed: {api_error}"))
            detach_external_mcp_tools()
            sys.exit(1)

    # 4. Clean shutdown of MCP subprocesses.
    detach_external_mcp_tools()
    sys.exit(0)


def _serve_blocking(session: Any) -> int:
    """Run the synchronous serve loop on the calling thread."""
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


def run_serve(session: Any) -> int:
    """CLI entry: serve the protocol over real stdin/stdout.

    Called from inside the CLI's running event loop (async main), the
    serve loop must not stay on the loop thread: it is a blocking
    synchronous pump, and `_handle_command` needs a fresh event loop for
    `asyncio.run(dispatch(...))`. Running the loop on a worker thread
    satisfies both; the CLI thread just joins it.
    """
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _serve_blocking(session)

    result: list[int] = []

    def _run() -> None:
        result.append(_serve_blocking(session))

    worker = threading.Thread(
        target=_run, name="pawnlogic-serve", daemon=True,
    )
    worker.start()
    worker.join()
    return result[0]
