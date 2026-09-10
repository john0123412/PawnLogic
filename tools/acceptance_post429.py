"""Real-PTY acceptance for the post-429 freeze fixes.

Drives the actual CLI under a pseudo-terminal with a deterministic backend
stream that fails the first Turn the way a rate-limited provider does
(HTTP 429 retries, then a circuit-open error), then verifies the user can
keep working afterwards.  A second scenario ends the live Application
without close() and asserts the CLI is released instead of parking forever.

This is an acceptance probe, not a unit test: it runs in a scratch HOME, is
not wired into the default suite, and takes about a minute.

Run:  python tools/acceptance_post429.py
Exit: 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pexpect

ROOT = Path(__file__).resolve().parent.parent


BOOTSTRAP = r'''
import json
import os
import time
from pathlib import Path

import core.session

trace_path = Path(os.environ["ACCEPT_TRACE"])
request_count = 0


def _trace(messages):
    users = [
        m.get("content", "")
        for m in messages
        if m.get("role") == "user"
    ]
    with trace_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"request": request_count, "users": users}) + "\n")


def flaky_stream(messages, *_args, **_kwargs):
    """Fail the first Turn the way a rate-limited provider does.

    Request 1 replays the owner's log shape: two 429 retry notices followed
    by a circuit-open error, which core.session turns into a FAILED Turn.
    Later requests answer normally.
    """
    global request_count
    request_count += 1
    _trace(messages)

    if request_count == 1:
        msg = (
            "HTTP 429 Rate Limited: provider rate limit or quota was hit; "
            "wait before retrying. Response: The request rate exceeds the "
            "current model TPM limit | gateway_error | 429001"
        )
        yield {"_retry": f"{msg} Retrying in 1s (1/5)."}
        yield {"_retry": f"{msg} Retrying in 1s (2/5)."}
        yield {"_error": (
            "circuit open: https://api.b.ai/v1/chat/completions "
            "(consecutive failures; paused 30s)"
        )}
        return

    yield {"choices": [{"delta": {"content": "ACK-%d" % request_count}}]}


core.session.stream_request = flaky_stream
'''


DEATH_BOOTSTRAP = r'''
import asyncio
import os
from pathlib import Path

import pawnlogic.live_terminal as lt

mark = Path(os.environ["ACCEPT_DEATH_MARK"])
_orig_run = lt.PersistentTerminal.run


def _patched_run(self):
    """Make the Application task itself fail, as a real crash does.

    The production shape is a *failed* task (the owner's log records
    ``Persistent terminal application failed: KeyboardInterrupt()``), not a
    cancelled one: cancellation sets ``Task.cancelled()`` and the observer
    correctly treats that as an orderly stop.

    The failure is raised from inside the Application's own await chain via
    the run_async wrapper, so the task completes with an exception exactly
    like a renderer crash.
    """
    async def wrapper():
        async def failing_run_async(real_run_async, *args, **kwargs):
            """Run the real Application, then fail the task hosting it.

            The real Application must start (otherwise ``wait_until_ready``
            blocks), so it runs as a child task.  After it is up, this
            coroutine — which runs inside ``PersistentTerminal.run()``'s own
            task — raises.  That makes the run task complete with an
            exception, which is the production shape the observer reports on.
            A *cancelled* task is deliberately treated as an orderly stop and
            would not exercise the branch under test.
            """
            child = asyncio.ensure_future(real_run_async(*args, **kwargs))
            child.add_done_callback(lambda fut: fut.cancelled() or fut.exception())
            await asyncio.sleep(1.5)
            mark.write_text("fired", encoding="utf-8")
            raise KeyboardInterrupt("simulated application death")

        original_builder = self._build_application_locked

        def builder():
            app = original_builder()
            real_run_async = app.run_async          # capture BEFORE patching

            async def injected(*args, **kwargs):
                return await failing_run_async(real_run_async, *args, **kwargs)

            app.run_async = injected
            return app

        self._build_application_locked = builder
        try:
            return await _orig_run(self)
        finally:
            self._build_application_locked = original_builder

    return wrapper()


lt.PersistentTerminal.run = lambda self: _patched_run(self)
'''


def _spawn(test_home: Path, bootstrap: str, extra_env: dict) -> pexpect.spawn:
    pawnlogic_home = test_home / ".pawnlogic"
    pawnlogic_home.mkdir(parents=True, exist_ok=True)
    bootstrap_dir = test_home / "bootstrap"
    bootstrap_dir.mkdir(exist_ok=True)
    (bootstrap_dir / "sitecustomize.py").write_text(bootstrap, encoding="utf-8")

    env = os.environ.copy()
    env.update({
        "HOME": str(test_home),
        "PAWNLOGIC_HOME": str(pawnlogic_home),
        "PAWNLOGIC_TEST_MODE": "true",
        "DEEPSEEK_API_KEY": "test-key",
        "MCP_ENABLED": "false",
        "PROMPT_TOOLKIT_ENABLED": "1",
        "TERM": "xterm",
        "NO_COLOR": "1",
    })
    env.update(extra_env)
    env["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (str(ROOT), str(bootstrap_dir), env.get("PYTHONPATH", ""))
        if part
    )
    return pexpect.spawn(
        f"{sys.executable} main.py",
        cwd=str(ROOT),
        env=env,
        encoding="utf-8",
        timeout=30,
        dimensions=(30, 100),
    )


def _run_death_scenario() -> list[tuple[str, bool, str]]:
    """An Application ending without close() must release the CLI loop."""
    checks: list[tuple[str, bool, str]] = []
    test_home = Path(tempfile.mkdtemp(prefix="appdeath-"))
    mark = test_home / "death-mark"
    child = _spawn(
        test_home,
        DEATH_BOOTSTRAP,
        {"ACCEPT_DEATH_MARK": str(mark)},
    )
    blob: list[str] = []
    child.logfile_read = type(
        "F", (), {"write": lambda _s, d: blob.append(d), "flush": lambda _s: None}
    )()
    try:
        child.expect(["Resume session", "You >", "You>"], timeout=30)
        if "Resume" in (child.after or ""):
            child.sendline("")
            child.expect(["You >", "You>"], timeout=20)
        checks.append(("death: REPL running before the crash", True, ""))

        try:
            child.expect(pexpect.EOF, timeout=25)
            checks.append((
                "death: CLI exits instead of parking (no force-quit)",
                True,
                "",
            ))
        except pexpect.TIMEOUT:
            checks.append((
                "death: CLI exits instead of parking (no force-quit)",
                False,
                "process still parked after the Application died",
            ))
        checks.append((
            "death: injection fired",
            mark.exists(),
            "" if mark.exists() else "application death was never simulated",
        ))
        checks.append((
            "death: user-visible explanation printed",
            "stopped unexpectedly" in "".join(blob),
            "" if "stopped unexpectedly" in "".join(blob) else "no message seen",
        ))
    except (pexpect.TIMEOUT, pexpect.EOF) as exc:
        checks.append(("death: scenario completed", False, str(exc)))
    finally:
        if child.isalive():
            child.close(force=True)
        shutil.rmtree(test_home, ignore_errors=True)
    return checks


def main() -> int:
    test_home = Path(tempfile.mkdtemp(prefix="post429-"))
    trace_path = test_home / "trace.jsonl"

    checks: list[tuple[str, bool]] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok))
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name}" + (f"  -- {detail}" if detail else ""))

    child = _spawn(test_home, BOOTSTRAP, {"ACCEPT_TRACE": str(trace_path)})
    transcript: list[str] = []
    try:
        # ── start ────────────────────────────────────────────────
        child.expect(["Resume session", "You >", "You>"], timeout=30)
        if "Resume" in (child.after or ""):
            child.sendline("")
            child.expect(["You >", "You>"], timeout=20)
        record("live REPL reached the composer", True)

        # ── Turn 1: provider fails (429) ─────────────────────────
        child.sendline("first question")
        time.sleep(4)
        try:
            child.expect(["429", "Rate Limited", "circuit", "quota"], timeout=20)
            record("429 failure surfaced to the user", True)
        except pexpect.TIMEOUT:
            record("429 failure surfaced to the user", False, "no error text seen")
        transcript.append(child.before or "")

        # ── Turn 2: the reported freeze ──────────────────────────
        # Before the fix this prompt was queued silently and never ran.
        time.sleep(1)
        child.sendline("second question")
        try:
            child.expect("ACK-2", timeout=25)
            record("prompt after the failure actually runs", True)
        except pexpect.TIMEOUT:
            record(
                "prompt after the failure actually runs",
                False,
                "no ACK-2: the prompt was parked silently (regression)",
            )
        transcript.append(child.before or "")

        # ── Turn 3: keep going ───────────────────────────────────
        child.sendline("third question")
        try:
            child.expect("ACK-3", timeout=25)
            record("subsequent prompts keep working", True)
        except pexpect.TIMEOUT:
            record("subsequent prompts keep working", False, "no ACK-3")
        transcript.append(child.before or "")

        # ── slash command still responsive ───────────────────────
        child.sendline("/queue")
        try:
            child.expect(["Queued:", "Status:"], timeout=15)
            record("slash commands remain responsive", True)
        except pexpect.TIMEOUT:
            record("slash commands remain responsive", False, "no /queue output")

        # ── clean quit ───────────────────────────────────────────
        child.sendline("/q")
        try:
            child.expect(pexpect.EOF, timeout=20)
            record("clean exit restores the terminal", True)
        except pexpect.TIMEOUT:
            record("clean exit restores the terminal", False, "no EOF after /q")

        requests = []
        if trace_path.exists():
            for line in trace_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    requests.append(line)
        users = trace_path.read_text(encoding="utf-8") if trace_path.exists() else ""
        record(
            "backend saw all three prompts",
            all(q in users for q in ("first question", "second question", "third question")),
            f"{len(requests)} request(s) traced",
        )
    finally:
        if child.isalive():
            child.close(force=True)
        shutil.rmtree(test_home, ignore_errors=True)

    print()
    print("Application-death scenario:")
    for name, ok, detail in _run_death_scenario():
        record(name, ok, detail)

    print()
    failed = [name for name, ok in checks if not ok]
    if failed:
        print(f"RESULT: FAILED ({len(failed)}/{len(checks)} checks failed)")
        for name in failed:
            print(f"  - {name}")
        if transcript:
            print("\n--- last captured output ---")
            print(transcript[-1][-2000:])
        return 1
    print(f"RESULT: PASSED ({len(checks)}/{len(checks)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
