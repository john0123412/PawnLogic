"""
Dynamic E2E tests — spawn real PawnLogic process and interact via pexpect.

These tests verify the CLI agent can start, process slash commands, and
exit cleanly without requiring real API keys (PAWNLOGIC_TEST_MODE=true).
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parent.parent

try:
    import pexpect
except ImportError:
    pytest.skip("pexpect not available (Windows or not installed)", allow_module_level=True)


def _wait_for_prompt(child, timeout=15):
    """Wait for PawnLogic to show main prompt, handling session selection first."""
    try:
        # Try to match session selection screen first
        idx = child.expect([
            "Resume session", "Enter",              # Session selection
            "You >", "You>"                          # Direct prompt (no sessions)
        ], timeout=timeout)
        
        if idx < 3:
            # Got session selection screen, press Enter to create new
            child.sendline("")
            child.expect(["You >", "You>"], timeout=10)
        # else: already at prompt, idx >= 3
    except pexpect.TIMEOUT:
        # Might be stuck, print debug info
        raise


def _spawn_pawnlogic_process(tmp_path, *, prompt_toolkit_enabled: bool):
    """Spawn an isolated PawnLogic process for either terminal input mode."""
    test_home = tmp_path / "home"
    pawnlogic_home = test_home / ".pawnlogic"
    pawnlogic_home.mkdir(parents=True)

    env = os.environ.copy()
    env.update({
        "HOME": str(test_home),
        "PAWNLOGIC_HOME": str(pawnlogic_home),
        "PAWNLOGIC_TEST_MODE": "true",
        "DEEPSEEK_API_KEY": "sk-test-fake-key-for-ci",
        "PAWN_API_KEY": "test-fake-key",
        "ANTHROPIC_API_KEY": "sk-ant-test-fake",
        "TERM": "xterm" if prompt_toolkit_enabled else "dumb",
        "NO_COLOR": "1",
        "MCP_ENABLED": "false",  # Skip MCP for faster E2E startup
    })
    if prompt_toolkit_enabled:
        env.pop("PROMPT_TOOLKIT_ENABLED", None)
    else:
        env["PROMPT_TOOLKIT_ENABLED"] = "0"  # Force simple input() mode

    # Use sys.executable to ensure we use the correct python interpreter
    python_cmd = sys.executable if sys.executable else "python"
    return pexpect.spawn(
        f"{python_cmd} main.py",
        timeout=15,
        encoding="utf-8",
        env=env,
    )


def _spawn_interruptible_pawnlogic_process(tmp_path):
    """Spawn the fallback REPL with a stream that waits for Ctrl+C."""
    test_home = tmp_path / "interrupt-home"
    pawnlogic_home = test_home / ".pawnlogic"
    pawnlogic_home.mkdir(parents=True)
    trace_path = tmp_path / "stream-starts.log"
    bootstrap_dir = tmp_path / "interrupt-bootstrap"
    bootstrap_dir.mkdir()
    (bootstrap_dir / "sitecustomize.py").write_text(
        """
import os
import json
import time
from pathlib import Path

import core.session
from core.interrupts import raise_if_interrupted

trace_path = Path(os.environ["PAWNLOGIC_INTERRUPT_TRACE"])

def delayed_stream(*_args, **_kwargs):
    messages = _args[0]
    last_user = next(
        (message.get("content", "") for message in reversed(messages)
         if message.get("role") == "user"),
        "",
    )
    with trace_path.open("a", encoding="utf-8") as trace:
        trace.write(json.dumps(last_user) + "\\n")
    while True:
        time.sleep(0.02)
        raise_if_interrupted()
        yield {"choices": [{"delta": {"content": ""}}]}

core.session.stream_request = delayed_stream
""".lstrip(),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update({
        "HOME": str(test_home),
        "PAWNLOGIC_HOME": str(pawnlogic_home),
        "PAWNLOGIC_TEST_MODE": "true",
        "DEEPSEEK_API_KEY": "test-key",
        "MCP_ENABLED": "false",
        "PROMPT_TOOLKIT_ENABLED": "0",
        "TERM": "dumb",
        "NO_COLOR": "1",
        "PAWNLOGIC_INTERRUPT_TRACE": str(trace_path),
    })
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(ROOT), str(bootstrap_dir), existing_pythonpath) if part
    )
    return pexpect.spawn(
        f"{sys.executable} main.py",
        cwd=str(ROOT),
        timeout=15,
        encoding="utf-8",
        env=env,
    ), trace_path


def _wait_for_stream_count(trace_path: Path, expected: int, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if trace_path.exists():
            starts = trace_path.read_text(encoding="utf-8").splitlines()
            if len(starts) >= expected:
                return starts
        time.sleep(0.05)
    starts = trace_path.read_text(encoding="utf-8").splitlines() if trace_path.exists() else []
    raise AssertionError(f"expected {expected} stream starts, got {starts!r}")


@pytest.fixture
def spawn_pawnlogic(tmp_path):
    """Spawn a PawnLogic process with simple input() for broad CLI coverage."""
    child = _spawn_pawnlogic_process(tmp_path, prompt_toolkit_enabled=False)
    try:
        yield child
    finally:
        if child.isalive():
            child.close(force=True)


@pytest.fixture
def spawn_pawnlogic_tui(tmp_path):
    """Spawn a PawnLogic process with Prompt Toolkit enabled."""
    child = _spawn_pawnlogic_process(tmp_path, prompt_toolkit_enabled=True)
    try:
        yield child
    finally:
        if child.isalive():
            child.close(force=True)


def test_startup_and_prompt(spawn_pawnlogic):
    """Verify PawnLogic starts and shows prompt without crashing."""
    child = spawn_pawnlogic
    try:
        _wait_for_prompt(child)
        assert "Traceback" not in child.before
        assert "ImportError" not in child.before
    except (pexpect.TIMEOUT, pexpect.EOF) as e:
        print(f"\n=== OUTPUT BEFORE TIMEOUT/EOF ===\n{child.before}")
        pytest.fail(f"Startup failed: {e}")


def test_slash_help(spawn_pawnlogic):
    """Send /help and verify output contains command info."""
    child = spawn_pawnlogic
    try:
        _wait_for_prompt(child)
        child.sendline("/help")
        child.expect(["Commands", "commands", "model", "/model"], timeout=10)
    except (pexpect.TIMEOUT, pexpect.EOF) as e:
        print(f"\n=== OUTPUT ===\n{child.before}")
        pytest.fail(f"/help failed: {e}")


def test_slash_fuzzy_planguard(spawn_pawnlogic):
    """A unique slash-command subsequence reaches the registered handler."""
    child = spawn_pawnlogic
    try:
        _wait_for_prompt(child)
        child.sendline("/plg")
        child.expect("Auto-corrected: /plg -> /planguard", timeout=10)
        child.expect("Interactive plan-guard selector is unavailable", timeout=10)
    except (pexpect.TIMEOUT, pexpect.EOF) as e:
        print(f"\n=== OUTPUT ===\n{child.before}")
        pytest.fail(f"/plg fuzzy dispatch failed: {e}")


def test_slash_ambiguous_fuzzy_command_lists_candidates(spawn_pawnlogic):
    """Ambiguous fuzzy input stays in the REPL and executes no candidate."""
    child = spawn_pawnlogic
    try:
        _wait_for_prompt(child)
        child.sendline("/qu")
        child.expect("Ambiguous command '/qu'", timeout=10)
        child.expect("/queue, /quit", timeout=10)
        _wait_for_prompt(child)
        child.sendline("/help")
        child.expect(["Commands", "commands", "model", "/model"], timeout=10)
    except (pexpect.TIMEOUT, pexpect.EOF) as e:
        print(f"\n=== OUTPUT ===\n{child.before}")
        pytest.fail(f"Ambiguous fuzzy dispatch failed: {e}")


def test_slash_queue_resume_reports_empty_queue(spawn_pawnlogic):
    """The documented resume subcommand reaches the real queue handler."""
    child = spawn_pawnlogic
    try:
        _wait_for_prompt(child)
        child.sendline("/queue resume")
        child.expect("queue empty", timeout=10)
    except (pexpect.TIMEOUT, pexpect.EOF) as e:
        print(f"\n=== OUTPUT ===\n{child.before}")
        pytest.fail(f"/queue resume failed: {e}")


def test_ctrl_c_retry_and_queue_resume_keep_one_recoverable_message(tmp_path):
    """Ctrl+C preserves one retry, whether the user presses Enter or resumes it."""
    child, trace_path = _spawn_interruptible_pawnlogic_process(tmp_path)
    try:
        _wait_for_prompt(child)
        child.sendline("retry once")
        _wait_for_stream_count(trace_path, 1)

        child.sendcontrol("c")
        child.expect("Saved 1 queued message", timeout=10)
        child.expect(r"You > .*retry once", timeout=10)

        # Pressing Enter consumes the preserved prompt once, rather than adding
        # a duplicate queue entry.
        child.sendline("")
        _wait_for_stream_count(trace_path, 2)
        time.sleep(0.2)
        assert len(trace_path.read_text(encoding="utf-8").splitlines()) == 2

        child.sendcontrol("c")
        child.expect("Saved 1 queued message", timeout=10)
        child.sendline("/queue")
        child.expect(r"Queued: 1 message\(s\)", timeout=10)

        # The explicit command follows the same recovery path and is
        # interruptible without losing or duplicating the queued input.
        child.sendline("/queue resume")
        _wait_for_stream_count(trace_path, 3)
        time.sleep(0.2)
        assert len(trace_path.read_text(encoding="utf-8").splitlines()) == 3
        child.sendcontrol("c")
        child.expect("Saved 1 queued message", timeout=10)
    except (pexpect.TIMEOUT, pexpect.EOF) as e:
        print(f"\n=== OUTPUT ===\n{child.before}")
        pytest.fail(f"Ctrl+C recovery flow failed: {e}")
    finally:
        if child.isalive():
            child.close(force=True)


@pytest.mark.parametrize("replacement", ["edited prompt", "/replacement prompt"])
def test_ctrl_c_edit_replaces_the_preserved_prompt(tmp_path, replacement):
    """Plain and slash-prefixed edits replace the preserved prompt once."""
    child, trace_path = _spawn_interruptible_pawnlogic_process(tmp_path)
    try:
        _wait_for_prompt(child)
        child.sendline("original prompt")
        starts = _wait_for_stream_count(trace_path, 1)
        assert json.loads(starts[-1]) == "original prompt"

        child.sendcontrol("c")
        child.expect("Saved 1 queued message", timeout=10)
        child.expect(r"You > .*original prompt", timeout=10)

        child.sendline(replacement)
        starts = _wait_for_stream_count(trace_path, 2)
        assert json.loads(starts[-1]) == replacement
        child.sendcontrol("c")
        child.expect("Saved 1 queued message", timeout=10)
        child.expect(rf"You > .*{re.escape(replacement)}", timeout=10)

        # Enter must retry the edited prompt even when it starts with '/'.
        child.sendline("")
        starts = _wait_for_stream_count(trace_path, 3)
        assert json.loads(starts[-1]) == replacement
        child.sendcontrol("c")
        child.expect("Saved 1 queued message", timeout=10)
    except (pexpect.TIMEOUT, pexpect.EOF) as e:
        print(f"\n=== OUTPUT ===\n{child.before}")
        pytest.fail(f"Ctrl+C edit recovery failed: {e}")
    finally:
        if child.isalive():
            child.close(force=True)


@pytest.mark.parametrize("control", ["/abort", "/queue clear"])
def test_ctrl_c_clear_control_discards_the_preserved_prompt(tmp_path, control):
    """Documented clear controls remain available during retry editing."""
    child, trace_path = _spawn_interruptible_pawnlogic_process(tmp_path)
    try:
        _wait_for_prompt(child)
        child.sendline("discard me")
        _wait_for_stream_count(trace_path, 1)

        child.sendcontrol("c")
        child.expect("Saved 1 queued message", timeout=10)
        child.expect(r"You > .*discard me", timeout=10)

        child.sendline(control)
        child.expect("Cleared 1 queued message", timeout=10)
        child.sendline("/queue")
        child.expect(r"Queued: 0 message\(s\)", timeout=10)
        assert len(trace_path.read_text(encoding="utf-8").splitlines()) == 1
    except (pexpect.TIMEOUT, pexpect.EOF) as e:
        print(f"\n=== OUTPUT ===\n{child.before}")
        pytest.fail(f"Ctrl+C clear-control recovery failed: {e}")
    finally:
        if child.isalive():
            child.close(force=True)


def test_slash_planguard_tui_applies_selected_mode(spawn_pawnlogic_tui):
    """The interactive selector applies the mode chosen after fuzzy dispatch."""
    child = spawn_pawnlogic_tui
    try:
        _wait_for_prompt(child)
        child.sendline("/plg")
        child.expect("Auto-corrected: /plg -> /planguard", timeout=10)
        child.expect("Plan Guard Mode", timeout=10)
        child.send("2")
        child.send("\r")
        child.expect("plan_guard_mode=strict", timeout=10)
    except (pexpect.TIMEOUT, pexpect.EOF) as e:
        print(f"\n=== OUTPUT ===\n{child.before}")
        pytest.fail(f"/planguard selector failed: {e}")


def test_slash_keys(spawn_pawnlogic):
    """Send /keys and verify output contains provider/API info."""
    child = spawn_pawnlogic
    try:
        _wait_for_prompt(child)
        child.sendline("/keys")
        child.expect(["Provider", "API", "Key"], timeout=10)
    except (pexpect.TIMEOUT, pexpect.EOF) as e:
        print(f"\n=== OUTPUT ===\n{child.before}")
        pytest.fail(f"/keys failed: {e}")


def test_slash_mode(spawn_pawnlogic):
    """Send /mode and verify output contains user/debug mode info."""
    child = spawn_pawnlogic
    try:
        _wait_for_prompt(child)
        child.sendline("/mode")
        child.expect(["Debug mode enabled", "User-friendly mode enabled"], timeout=10)
    except (pexpect.TIMEOUT, pexpect.EOF) as e:
        print(f"\n=== OUTPUT ===\n{child.before}")
        pytest.fail(f"/mode failed: {e}")


def test_slash_limits(spawn_pawnlogic):
    """Send /limits and verify output contains token/ctx info."""
    child = spawn_pawnlogic
    try:
        _wait_for_prompt(child)
        child.sendline("/limits")
        child.expect(["tokens", "token", "ctx", "Context"], timeout=10)
    except (pexpect.TIMEOUT, pexpect.EOF) as e:
        print(f"\n=== OUTPUT ===\n{child.before}")
        pytest.fail(f"/limits failed: {e}")


def test_slash_sessions(spawn_pawnlogic):
    """Send /sessions and verify output contains session info."""
    child = spawn_pawnlogic
    try:
        _wait_for_prompt(child)
        child.sendline("/sessions")
        child.expect(["session", "Session", "No saved", r"\(no"], timeout=10)
    except (pexpect.TIMEOUT, pexpect.EOF) as e:
        print(f"\n=== OUTPUT ===\n{child.before}")
        pytest.fail(f"/sessions failed: {e}")


def test_slash_model_list(spawn_pawnlogic):
    """Send /model and verify output contains model list."""
    child = spawn_pawnlogic
    try:
        _wait_for_prompt(child)
        child.sendline("/model")
        child.expect(["ds-", "claude", "hermes", "model", "Model"], timeout=10)
    except (pexpect.TIMEOUT, pexpect.EOF) as e:
        print(f"\n=== OUTPUT ===\n{child.before}")
        pytest.fail(f"/model failed: {e}")


def test_clean_exit(spawn_pawnlogic):
    """Send EOF (ctrl+d) and verify clean exit."""
    child = spawn_pawnlogic
    try:
        _wait_for_prompt(child)
        child.sendeof()
        child.expect(pexpect.EOF, timeout=5)
        child.close()
        assert child.exitstatus != 1, f"Process crashed with exit code {child.exitstatus}"
    except pexpect.TIMEOUT as e:
        print(f"\n=== OUTPUT ===\n{child.before}")
        pytest.fail(f"Clean exit failed: process didn't exit in 5s: {e}")
