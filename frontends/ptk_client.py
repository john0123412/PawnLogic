"""Minimal Prompt Toolkit shell for the headless serve protocol (Phase 2a).

Run with:  python -m frontends.ptk_client --model <alias> [--report out.json]

The shell validates the ADR 0011 wire under real interaction: streamed
model output, Enter-while-running steering, Esc interrupt, and latency
instrumentation for the Rust frontend decision.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension

from frontends.serve_wire import LatencyRecorder, ServeWire, build_request

MODEL_DEFAULT = "ds-v4-flash"


class ClientApp:
    """Drive one serve process with a two-window inline UI."""

    def __init__(self, model: str, report_path: str | None) -> None:
        self._model = model
        self._report_path = report_path
        self._recorder = LatencyRecorder()
        self._transcript: list[str] = []
        self._running = False
        self._buffer = Buffer(multiline=False)
        self._app: Application | None = None
        self.wire: ServeWire | None = None

    # ── wire callbacks ──────────────────────────────────

    def _append(self, line: str) -> None:
        self._transcript.append(line)
        del self._transcript[:-400]

    def _on_event(self, event: dict) -> None:
        kind = event.get("type")
        self._recorder.on_event(event)
        if kind == "status":
            stage = event.get("stage", "")
            if stage == "turn_started":
                self._running = True
                self._append("── turn started ──")
            elif stage in ("turn_completed", "turn_failed", "turn_interrupted"):
                self._running = False
                self._append(f"── turn {stage.split('_', 1)[1]} ──")
            elif stage in ("interrupt_requested", "steer_queued"):
                self._append(f"· {stage}")
        elif kind == "stream":
            text = event.get("text", "")
            if self._transcript and not self._transcript[-1].startswith("│ "):
                self._append("│ ")
            self._transcript[-1] += text
        elif kind == "result":
            self._append(f"= {event.get('response', '')!r}")
            self._running = False
        elif kind == "error":
            self._append(f"✗ [{event.get('stage')}] {event.get('detail', '')}")
            if event.get("stage") in ("run_turn", "steer"):
                self._running = False
        self._invalidate()

    def _on_exit(self) -> None:
        self._running = False
        self._append("── server exited ──")
        self._invalidate()

    def _invalidate(self) -> None:
        if self._app is not None:
            self._app.invalidate()

    # ── input handling ──────────────────────────────────

    def _submit(self) -> None:
        text = self._buffer.text.strip()
        self._buffer.reset()
        if not text:
            return
        if text == "/quit":
            self.wire.send(build_request("shutdown"))
            return
        if self.wire is not None:
            self.wire.send(build_request("prompt", text, steer=self._running))
            self._recorder.on_prompt_sent()

    def _interrupt(self) -> None:
        if self.wire is not None and self._running:
            self.wire.send(build_request("interrupt"))
            self._recorder.on_interrupt_sent()
            self._append("· Esc → interrupt sent")

    # ── layout ──────────────────────────────────────────

    def _render_output(self) -> str:
        return "\n".join(self._transcript[-40:])

    def _build_app(self) -> Application:
        bindings = KeyBindings()

        @bindings.add("escape", eager=True)
        def _on_escape(_event) -> None:
            self._interrupt()

        @bindings.add("c-c", eager=True)
        def _on_ctrl_c(_event) -> None:
            self.wire.send(build_request("shutdown"))
            if self._app is not None:
                self._app.exit()

        output_window = Window(
            FormattedTextControl(lambda: self._render_output()),
            wrap_lines=True,
            scroll_to_end=True,
        )
        input_window = Window(
            self._buffer.control,
            height=Dimension(min=1, max=3),
            wrap_lines=True,
        )
        body = HSplit([output_window, Window(height=1), input_window])
        return Application(
            layout=Layout(body, focused_element=self._buffer),
            key_bindings=bindings,
            full_screen=False,
        )

    @staticmethod
    def _print_report(report: dict, path: str | None) -> None:
        print("\n=== serve latency report ===")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        if path:
            Path(path).write_text(
                json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"report written to {path}")

    # ── lifecycle ───────────────────────────────────────

    def run(self) -> dict:
        server_cmd = [
            sys.executable, "-m", "pawnlogic", "serve", "--model", self._model
        ]
        self.wire = ServeWire(
            server_cmd, on_event=self._on_event, on_exit=self._on_exit
        )
        self._app = self._build_app()

        @self._buffer.accept_handler
        def _on_accept(_buffer: Buffer) -> None:
            self._submit()

        self._app.run()
        self.wire.close()
        report = self._recorder.report()
        self._print_report(report, self._report_path)
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ptk_client",
        description="Prompt Toolkit client for the pawnlogic serve wire.",
    )
    parser.add_argument("--model", default=MODEL_DEFAULT, help="model alias")
    parser.add_argument(
        "--report", default=None, help="write the latency report JSON here"
    )
    args = parser.parse_args(argv)
    ClientApp(args.model, args.report).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
