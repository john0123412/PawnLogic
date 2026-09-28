#!/usr/bin/env python3
"""Owner acceptance probe for a PawnLogic release binary (0.3.12 S5).

The 0.3.10 plan left "owner terminal acceptance on the published binary"
open as an anecdotal report. This script turns the automatable half of
that gate into a repeatable probe whose JSON output the owner can paste
back, and states plainly which checks still need human eyes.

Run it against the *published* artifact, not the source checkout, e.g.
after unpacking the GitHub Release ratatui tarball::

    python tools/owner_acceptance_probe.py --binary <path>

or, to probe the source checkout instead::

    python tools/owner_acceptance_probe.py --python

Checks marked ``automated`` run here. Checks marked ``manual`` cannot be
decided by a script — clipboard round-trips and mouse selection depend
on the real terminal emulator — so they stay ``manual`` until the owner
records them with repeatable ``--manual-pass`` or ``--manual-fail`` options.

The script itself is a source-checkout developer tool, like
``tools/code_index.py``; it is not part of the installed ``pawn``
command.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

# Terminal mode strings we assert on. Kept as raw escapes so the asserted
# text is pure ASCII and cannot itself be a source of the wide-glyph
# wrapping bug it is meant to detect.
_ENTER_ALT_SCREEN = "\x1b[?1049h"
_EXIT_ALT_SCREEN = "\x1b[?1049l"
_SHOW_CURSOR = "\x1b[?25h"
_HIDE_CURSOR = "\x1b[?25l"
_ENABLE_MOUSE = "\x1b[?1000h"
_DISABLE_MOUSE = "\x1b[?1000l"
_ENABLE_MOUSE_BUTTON = "\x1b[?1002h"
_DISABLE_MOUSE_BUTTON = "\x1b[?1002l"
_ENABLE_MOUSE_ANY = "\x1b[?1003h"
_DISABLE_MOUSE_ANY = "\x1b[?1003l"
_ENABLE_MOUSE_URXVT = "\x1b[?1015h"
_DISABLE_MOUSE_URXVT = "\x1b[?1015l"
_ENABLE_MOUSE_SGR = "\x1b[?1006h"
_DISABLE_MOUSE_SGR = "\x1b[?1006l"
_ENABLE_BRACKETED_PASTE = "\x1b[?2004h"
_DISABLE_BRACKETED_PASTE = "\x1b[?2004l"

# A CJK ideograph, an emoji, and an ASCII run: the exact mix that
# historically desynced the renderer's assumed width from the host's.
# Written as escapes, not literals, because the repository language policy
# forbids Chinese text in Python source -- only the *runtime* string needs
# the wide glyphs.
_GLYPH_PROBE = "probe: \u4e2d\u6587 \U0001f600 ascii"

_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b[()][B0]|\r")


def _clean(text: str) -> str:
    """Strip escape sequences and carriage returns from captured output."""
    return _ANSI.sub("", text).replace("\r", "")


def _result(name: str, status: str, detail: str) -> dict[str, Any]:
    return {"check": name, "status": status, "detail": detail}


def _left_enabled(transcript: str, enable: str, disable: str) -> bool:
    return transcript.rfind(enable) > transcript.rfind(disable)


def evaluate_terminal_transcript(transcript: str) -> dict[str, Any]:
    """Report whether the final terminal state represented by *transcript* is safe."""
    problems: list[str] = []
    if _left_enabled(transcript, _ENTER_ALT_SCREEN, _EXIT_ALT_SCREEN):
        problems.append("entered the alternate screen and never left it")
    if _left_enabled(transcript, _HIDE_CURSOR, _SHOW_CURSOR):
        problems.append("cursor left hidden at exit")
    for enable, disable, name in (
        (_ENABLE_MOUSE, _DISABLE_MOUSE, "mouse reporting"),
        (_ENABLE_MOUSE_BUTTON, _DISABLE_MOUSE_BUTTON, "button-event mouse"),
        (_ENABLE_MOUSE_ANY, _DISABLE_MOUSE_ANY, "any-event mouse"),
        (_ENABLE_MOUSE_URXVT, _DISABLE_MOUSE_URXVT, "URXVT mouse"),
        (_ENABLE_MOUSE_SGR, _DISABLE_MOUSE_SGR, "SGR mouse"),
        (
            _ENABLE_BRACKETED_PASTE,
            _DISABLE_BRACKETED_PASTE,
            "bracketed paste",
        ),
    ):
        if _left_enabled(transcript, enable, disable):
            problems.append(f"{name} left enabled at exit")
    if "Traceback" in transcript:
        problems.append("traceback during the session")

    if problems:
        return _result("terminal_state_restore", "fail", "; ".join(problems))
    return _result(
        "terminal_state_restore", "pass", "terminal modes restored on exit"
    )


# ---------------------------------------------------------------------------
# Automated checks
# ---------------------------------------------------------------------------


def check_entrypoint(argv: list[str], env: dict[str, str]) -> dict[str, Any]:
    """The entry point must start and print help without a traceback."""
    import subprocess

    try:
        proc = subprocess.run(
            [*argv, "--help"],
            capture_output=True,
            text=True,
            timeout=90,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return _result("entrypoint_help", "fail", "timed out after 90s")
    except OSError as exc:
        return _result("entrypoint_help", "fail", f"could not launch: {exc}")

    out = proc.stdout + proc.stderr
    if proc.returncode != 0:
        return _result(
            "entrypoint_help", "fail", f"exit {proc.returncode}: {_clean(out)[:200]}"
        )
    if "Traceback" in out:
        return _result("entrypoint_help", "fail", "traceback in --help output")
    if "usage" not in out.lower():
        return _result("entrypoint_help", "fail", "no usage text in --help output")
    return _result(
        "entrypoint_help", "pass", f"usage printed, exit 0 ({len(out)} bytes)"
    )


def check_pty_session(argv: list[str], env: dict[str, str]) -> dict[str, Any]:
    """Drive a real PTY and assert the terminal guard restores state.

    This is the part of owner acceptance that *is* automatable: whether
    the process leaves the alternate screen active, leaves the cursor
    hidden, or leaves the mouse/bracketed-paste modes enabled. A failure
    here is exactly the corruption the ratatui terminal guard exists to
    prevent, and it is invisible to a non-PTY test.
    """
    try:
        import pexpect
    except ImportError:
        return _result(
            "terminal_state_restore",
            "skip",
            "pexpect not installed; cannot drive a real PTY",
        )

    columns, lines = 100, 30
    # The PTY leg needs a configured provider key or the app never leaves
    # the first-run gate and prints nothing, which would be reported as a
    # terminal-guard failure. Default to the owner's real PAWNLOGIC_HOME
    # (a probe run creates one session, like any other run); --isolated
    # forces a throwaway home for a hermetic check of the state machine.
    if env.get("PAWNLOGIC_PROBE_ISOLATED"):
        home = tempfile.mkdtemp(prefix="pawnlogic-probe-")
    else:
        home = ""
    child_env = dict(env)
    child_env.pop("PAWNLOGIC_PROBE_ISOLATED", None)
    if home:
        child_env["PAWNLOGIC_HOME"] = home
    child_env["MCP_ENABLED"] = "false"
    child_env["TERM"] = "xterm-256color"
    child_env["COLUMNS"] = str(columns)
    child_env["LINES"] = str(lines)

    captured: list[str] = []
    try:
        child = pexpect.spawn(
            argv[0],
            argv[1:],
            timeout=45,
            env=child_env,
            dimensions=(lines, columns),
            encoding="utf-8",
            codec_errors="replace",
        )
        child.logfile_read = None
        # A probe turn that needs no provider: the first-run gate prints
        # its setup hint and returns to the composer on its own.
        with contextlib.suppress(pexpect.TIMEOUT, pexpect.EOF):
            child.expect([r"[$>]\s*$", pexpect.TIMEOUT], timeout=30)
        captured.append(_read_available(child))
        child.sendline(_GLYPH_PROBE)
        with contextlib.suppress(pexpect.TIMEOUT, pexpect.EOF):
            child.expect([pexpect.TIMEOUT, pexpect.EOF], timeout=20)
        captured.append(_read_available(child))
        child.sendcontrol("c")
        try:
            child.expect(pexpect.EOF, timeout=20)
        except (pexpect.TIMEOUT, pexpect.EOF):
            child.close(force=True)
        captured.append(_read_available(child))
        transcript = "".join(captured)
    except Exception as exc:
        return _result("terminal_state_restore", "fail", f"PTY drive failed: {exc}")
    finally:
        if home:
            shutil.rmtree(home, ignore_errors=True)

    if not transcript.strip():
        return _result(
            "terminal_state_restore",
            "skip",
            "the app printed nothing under this PTY. Most likely it is "
            "stopped at the first-run gate: run this with your real "
            "PAWNLOGIC_HOME so a provider key is visible, or pass "
            "--isolated to accept a skip.",
        )

    # The typed probe text is a soft signal only. Prompt Toolkit renders
    # the composer differentially, so the literal string is not
    # guaranteed to appear contiguously in the PTY byte stream even on a
    # healthy run. Reporting it as a hard failure would produce false
    # alarms, so it is reported as its own observation.
    echoed = _GLYPH_PROBE in _clean(transcript)
    result = evaluate_terminal_transcript(transcript)
    result["detail"] += f" (glyph probe echoed: {'yes' if echoed else 'no'})"
    return result


def _read_available(child: Any, budget: float = 2.0) -> str:
    """Drain whatever the child has already written, within a time budget.

    A plain ``while True`` drain never terminates against the live
    terminal: its status line ticks every 250 ms, so output never pauses
    long enough to look idle. The wall-clock budget is what stops the
    probe, not a quiet period.
    """
    import time

    deadline = time.monotonic() + budget
    chunks: list[str] = []
    while time.monotonic() < deadline:
        try:
            piece = child.read_nonblocking(size=8192, timeout=0.25)
        except Exception:
            break
        if piece:
            chunks.append(piece)
    return "".join(chunks)


# ---------------------------------------------------------------------------
# Manual checks
# ---------------------------------------------------------------------------


def manual_checks() -> list[dict[str, Any]]:
    return [
        _result(
            "scrollback",
            "manual",
            "Complete one turn. Does the answer appear in the host's own "
            "scrollback, so the mouse wheel scrolls through it and you can "
            "select and copy it?",
        ),
        _result(
            "selection_copy",
            "manual",
            "Mouse-drag across a multi-line answer and copy it. Does the "
            "clipboard get the text with line breaks intact?",
        ),
        _result(
            "glyph_width",
            "manual",
            "Look at a line containing CJK text and emoji above. Are the "
            "box borders and the composer aligned, with no stray or "
            "duplicated characters?",
        ),
        _result(
            "no_duplicate_output",
            "manual",
            "Does a completed turn appear exactly once, with no echoed or "
            "interleaved residue on the rows it wrapped onto?",
        ),
    ]


def apply_manual_results(
    checks: list[dict[str, Any]],
    passed: list[str],
    failed: list[str],
) -> list[dict[str, Any]]:
    """Apply owner-recorded outcomes while leaving unanswered checks manual."""
    passed_names = set(passed)
    failed_names = set(failed)
    resolved: list[dict[str, Any]] = []
    for check in checks:
        current = dict(check)
        name = current["check"]
        if name in passed_names:
            current["status"] = "pass"
            current["detail"] = f"Owner recorded pass. {current['detail']}"
        elif name in failed_names:
            current["status"] = "fail"
            current["detail"] = f"Owner recorded fail. {current['detail']}"
        resolved.append(current)
    return resolved


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_target_command(args: argparse.Namespace) -> list[str]:
    if args.python:
        return [sys.executable, "-m", "pawnlogic"]
    return [args.binary]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Owner acceptance probe for a PawnLogic release binary."
    )
    parser.add_argument(
        "--binary",
        default=os.environ.get("PAWNLOGIC_PROBE_BINARY", "pawn"),
        help="path to the release binary (default: $PAWNLOGIC_PROBE_BINARY or 'pawn')",
    )
    parser.add_argument(
        "--python",
        action="store_true",
        help="probe the source checkout via 'python -m pawnlogic'",
    )
    parser.add_argument(
        "--isolated",
        action="store_true",
        help=(
            "force a throwaway PAWNLOGIC_HOME. The app then stops at the "
            "first-run gate and the PTY check reports 'skip' rather than "
            "a false failure. Use the default to probe your real setup."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="write the JSON report here instead of stdout",
    )
    manual_names = [check["check"] for check in manual_checks()]
    parser.add_argument(
        "--manual-pass",
        action="append",
        default=[],
        choices=manual_names,
        metavar="CHECK",
        help="record a passed manual check; repeat for additional checks",
    )
    parser.add_argument(
        "--manual-fail",
        action="append",
        default=[],
        choices=manual_names,
        metavar="CHECK",
        help="record a failed manual check; repeat for additional checks",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    conflicting_manual = set(args.manual_pass) & set(args.manual_fail)
    if conflicting_manual:
        parser.error(
            "manual checks cannot be both pass and fail: "
            + ", ".join(sorted(conflicting_manual))
        )

    child_env = dict(os.environ)
    child_env.setdefault("PAWNLOGIC_TEST_MODE", "true")
    child_env.setdefault("MCP_ENABLED", "false")

    automated: list[dict[str, Any]] = []
    command = build_target_command(args)
    if args.isolated:
        isolated_home = tempfile.mkdtemp(prefix="pawnlogic-probe-home-")
        child_env["PAWNLOGIC_HOME"] = isolated_home
        child_env["PAWNLOGIC_PROBE_ISOLATED"] = "1"
    else:
        isolated_home = ""
    try:
        automated.append(check_entrypoint(command, child_env))
        automated.append(check_pty_session(command, child_env))
    finally:
        if isolated_home:
            shutil.rmtree(isolated_home, ignore_errors=True)

    manual = apply_manual_results(
        manual_checks(),
        passed=args.manual_pass,
        failed=args.manual_fail,
    )
    checks = [*automated, *manual]
    decided_automated = [
        check for check in automated if check["status"] in {"pass", "fail"}
    ]
    report = {
        "probe": "owner-acceptance",
        "target": " ".join(build_target_command(args)),
        "automated_passed": sum(
            1 for check in decided_automated if check["status"] == "pass"
        ),
        "automated_total": len(decided_automated),
        "automated_failed": [c["check"] for c in automated if c["status"] == "fail"],
        "automated_skipped": [c["check"] for c in automated if c["status"] == "skip"],
        "manual_passed": [c["check"] for c in manual if c["status"] == "pass"],
        "manual_failed": [c["check"] for c in manual if c["status"] == "fail"],
        "manual_pending": [c["check"] for c in manual if c["status"] == "manual"],
        "checks": checks,
    }

    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)

    return 1 if report["automated_failed"] or report["manual_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
