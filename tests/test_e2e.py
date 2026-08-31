"""
Dynamic E2E tests — spawn real PawnLogic process and interact via pexpect.

These tests verify the CLI agent can start, process slash commands, and
exit cleanly without requiring real API keys (PAWNLOGIC_TEST_MODE=true).
"""

import importlib.util
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


def test_slash_fuzzy_ultra_sets_150_iteration_limit(spawn_pawnlogic):
    """The unique /ult shorthand selects the 150-iteration Ultra tier."""
    child = spawn_pawnlogic
    try:
        _wait_for_prompt(child)
        child.sendline("/ult")
        child.expect("Auto-corrected: /ult -> /ultra", timeout=10)
        child.expect("iter=150", timeout=10)
        child.expect("max_iter", timeout=10)
        child.expect("150", timeout=10)
    except (pexpect.TIMEOUT, pexpect.EOF) as e:
        print(f"\n=== OUTPUT ===\n{child.before}")
        pytest.fail(f"/ult fuzzy dispatch failed: {e}")


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


@pytest.mark.parametrize("control", ["/queue clear"])
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


def _require_prompt_toolkit():
    """Skip live-composer tests only when the optional UI dependency is absent."""
    if importlib.util.find_spec("prompt_toolkit") is None:
        pytest.skip("prompt_toolkit is required for live-composer E2E tests")


def _spawn_controlled_turn_process(
    tmp_path,
    *,
    prompt_toolkit_enabled: bool,
    stream_mode: str,
):
    """Spawn a process with a deterministic native stream and blocking tool."""
    test_home = tmp_path / f"controlled-{stream_mode}-home"
    pawnlogic_home = test_home / ".pawnlogic"
    pawnlogic_home.mkdir(parents=True)
    trace_path = tmp_path / f"{stream_mode}-stream-trace.jsonl"
    tool_started_path = tmp_path / f"{stream_mode}-tool-started"
    tool_invocations_path = tmp_path / f"{stream_mode}-tool-invocations"
    stream_open_path = tmp_path / f"{stream_mode}-stream-open"
    stream_complete_path = tmp_path / f"{stream_mode}-stream-complete"
    release_path = tmp_path / f"{stream_mode}-release"
    mode_path = tmp_path / f"{stream_mode}-input-mode"
    bootstrap_dir = tmp_path / f"{stream_mode}-bootstrap"
    bootstrap_dir.mkdir()
    (bootstrap_dir / "sitecustomize.py").write_text(
        """
import json
import os
import time
from pathlib import Path

import core.session
from core.turn_cancellation import current_turn_cancellation
import pawnlogic.cli as cli

trace_path = Path(os.environ["PAWNLOGIC_CONTROL_TRACE"])
tool_started_path = Path(os.environ["PAWNLOGIC_CONTROL_TOOL_STARTED"])
tool_invocations_path = Path(os.environ["PAWNLOGIC_CONTROL_TOOL_INVOCATIONS"])
stream_open_path = Path(os.environ["PAWNLOGIC_CONTROL_STREAM_OPEN"])
stream_complete_path = Path(os.environ["PAWNLOGIC_CONTROL_STREAM_COMPLETE"])
release_path = Path(os.environ["PAWNLOGIC_CONTROL_RELEASE"])
mode_path = Path(os.environ["PAWNLOGIC_CONTROL_MODE_PATH"])
stream_mode = os.environ["PAWNLOGIC_CONTROL_STREAM_MODE"]
expected_mode = os.environ["PAWNLOGIC_CONTROL_EXPECTED_MODE"]
actual_mode = "prompt_toolkit" if cli._HAS_PROMPT_TOOLKIT else "readline"
if actual_mode != expected_mode:
    raise RuntimeError(
        f"expected {expected_mode} input mode, got {actual_mode}"
    )
mode_path.write_text(actual_mode, encoding="utf-8")

request_count = 0


def _trace_request(messages):
    users = [
        message.get("content", "")
        for message in messages
        if message.get("role") == "user"
    ]
    tool_results = [
        {
            "tool_call_id": message.get("tool_call_id", ""),
            "content": message.get("content", ""),
        }
        for message in messages
        if message.get("role") == "tool"
    ]
    with trace_path.open("a", encoding="utf-8") as trace:
        trace.write(
            json.dumps(
                {
                    "request": request_count,
                    "users": users,
                    "tool_results": tool_results,
                }
            )
            + "\\n"
        )


def controlled_read_file(_args):
    invocation_count = (
        tool_invocations_path.read_text(encoding="utf-8").count("\\n") + 1
        if tool_invocations_path.exists()
        else 1
    )
    with tool_invocations_path.open("a", encoding="utf-8") as invocations:
        invocations.write(f"call-{invocation_count}\\n")
    tool_started_path.write_text("started", encoding="utf-8")
    if invocation_count == 1:
        if stream_mode == "cancel":
            cancellation = current_turn_cancellation()
            while not release_path.exists():
                if cancellation is not None and cancellation.wait(timeout=5):
                    break
        else:
            while not release_path.exists():
                time.sleep(0.02)
    return "controlled read_file result"


core.session.TOOL_MAP["read_file"] = controlled_read_file

def controlled_stream(messages, *_args, **_kwargs):
    global request_count
    request_count += 1
    _trace_request(messages)

    if stream_mode in {"tool", "multi_tool", "cancel"} and request_count == 1:
        tool_calls = [{
            "index": 0,
            "id": "call_blocking_read",
            "function": {
                "name": "read_file",
                "arguments": "{\\"path\\":\\"controlled\\"}",
            },
        }]
        if stream_mode == "multi_tool":
            tool_calls.append({
                "index": 1,
                "id": "call_skipped_read",
                "function": {
                    "name": "read_file",
                    "arguments": "{\\"path\\":\\"should-not-run\\"}",
                },
            })
        yield {
            "choices": [{
                "delta": {
                    "tool_calls": tool_calls,
                },
            }],
        }
        return

    if stream_mode == "text" and request_count == 1:
        yield {"choices": [{"delta": {"content": "first chunk "}}]}
        stream_open_path.write_text("open", encoding="utf-8")
        while not release_path.exists():
            time.sleep(0.02)
        yield {"choices": [{"delta": {"content": "second chunk"}}]}
        stream_complete_path.write_text("complete", encoding="utf-8")
        return

    users = [
        message.get("content", "")
        for message in messages
        if message.get("role") == "user"
    ]
    if stream_mode in {"tool", "multi_tool", "cancel"} and "steer: switch to plan B" in users:
        content = "steer applied"
    elif stream_mode in {"tool", "multi_tool", "cancel"} and request_count >= 3:
        content = "follow-up done"
    elif stream_mode in {"tool", "multi_tool", "cancel"}:
        content = "first turn done"
    else:
        content = "follow-up done"
    yield {"choices": [{"delta": {"content": content}}]}

core.session.stream_request = controlled_stream
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
        "PROMPT_TOOLKIT_ENABLED": "1" if prompt_toolkit_enabled else "0",
        "TERM": "xterm" if prompt_toolkit_enabled else "dumb",
        "NO_COLOR": "1",
        "PAWNLOGIC_CONTROL_TRACE": str(trace_path),
        "PAWNLOGIC_CONTROL_TOOL_STARTED": str(tool_started_path),
        "PAWNLOGIC_CONTROL_TOOL_INVOCATIONS": str(tool_invocations_path),
        "PAWNLOGIC_CONTROL_STREAM_OPEN": str(stream_open_path),
        "PAWNLOGIC_CONTROL_STREAM_COMPLETE": str(stream_complete_path),
        "PAWNLOGIC_CONTROL_RELEASE": str(release_path),
        "PAWNLOGIC_CONTROL_MODE_PATH": str(mode_path),
        "PAWNLOGIC_CONTROL_STREAM_MODE": stream_mode,
        "PAWNLOGIC_CONTROL_EXPECTED_MODE": (
            "prompt_toolkit" if prompt_toolkit_enabled else "readline"
        ),
    })
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(ROOT), str(bootstrap_dir), existing_pythonpath) if part
    )
    child = pexpect.spawn(
        f"{sys.executable} main.py",
        cwd=str(ROOT),
        timeout=15,
        encoding="utf-8",
        env=env,
    )
    return {
        "child": child,
        "trace": trace_path,
        "tool_started": tool_started_path,
        "tool_invocations": tool_invocations_path,
        "stream_open": stream_open_path,
        "stream_complete": stream_complete_path,
        "release": release_path,
        "mode": mode_path,
    }


def _read_control_trace(trace_path: Path) -> list[dict]:
    if not trace_path.exists():
        return []
    return [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _wait_for_control_trace(trace_path: Path, expected: int, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        records = _read_control_trace(trace_path)
        if len(records) >= expected:
            return records
        time.sleep(0.05)
    records = _read_control_trace(trace_path)
    raise AssertionError(f"expected {expected} model requests, got {records!r}")


def _wait_for_control_marker(marker_path: Path, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if marker_path.exists():
            return
        time.sleep(0.05)
    raise AssertionError(f"expected marker {marker_path.name!r}")


def _assert_no_control_trace(trace_path: Path, expected: int, timeout: float = 1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        records = _read_control_trace(trace_path)
        assert len(records) < expected, (
            f"unexpected model request before safe point: {records!r}"
        )
        time.sleep(0.05)


def test_mid_turn_tool_steer_applies_at_tool_safe_point(tmp_path):
    """A Prompt Toolkit steer is consumed after a blocking Tool Call completes."""
    _require_prompt_toolkit()
    process = _spawn_controlled_turn_process(
        tmp_path, prompt_toolkit_enabled=True, stream_mode="tool"
    )
    child = process["child"]
    try:
        _wait_for_prompt(child)
        child.sendline("long running task")
        records = _wait_for_control_trace(process["trace"], 1)
        assert records[0]["users"][-1] == "long running task"
        _wait_for_control_marker(process["mode"])
        assert process["mode"].read_text(encoding="utf-8") == "prompt_toolkit"
        _wait_for_control_marker(process["tool_started"])
        assert not process["release"].exists()

        child.sendline("steer: switch to plan B")
        _assert_no_control_trace(process["trace"], 2)

        process["release"].write_text("release", encoding="utf-8")
        records = _wait_for_control_trace(process["trace"], 2)
        second_users = records[1]["users"]
        assert second_users, f"second request has no user context: {records!r}"
        assert second_users[-1] == "steer: switch to plan B"
        child.expect("steer applied", timeout=10)
    finally:
        child.close(force=True)


def test_mid_turn_tool_steer_skips_unstarted_batch_calls(tmp_path):
    """A steer preserves protocol results without executing later tool calls."""
    _require_prompt_toolkit()
    process = _spawn_controlled_turn_process(
        tmp_path, prompt_toolkit_enabled=True, stream_mode="multi_tool"
    )
    child = process["child"]
    try:
        _wait_for_prompt(child)
        child.sendline("multi tool task")
        _wait_for_control_trace(process["trace"], 1)
        _wait_for_control_marker(process["tool_started"])

        child.sendline("steer: switch to plan B")
        _assert_no_control_trace(process["trace"], 2)

        process["release"].write_text("release", encoding="utf-8")
        records = _wait_for_control_trace(process["trace"], 2)
        assert records[1]["users"][-1] == "steer: switch to plan B"
        skipped = {
            result["tool_call_id"]: result["content"]
            for result in records[1]["tool_results"]
        }
        assert "call_skipped_read" in skipped
        assert skipped["call_skipped_read"].startswith("SKIPPED:")
        assert process["tool_invocations"].read_text(encoding="utf-8").splitlines() == [
            "call-1"
        ]
        child.expect("steer applied", timeout=10)
    finally:
        child.close(force=True)


def test_live_composer_defers_unsafe_slash_commands_but_allows_controls(tmp_path):
    """The live composer keeps queue controls usable during a running Turn."""
    _require_prompt_toolkit()
    process = _spawn_controlled_turn_process(
        tmp_path, prompt_toolkit_enabled=True, stream_mode="tool"
    )
    child = process["child"]
    try:
        _wait_for_prompt(child)
        child.sendline("long running task")
        _wait_for_control_trace(process["trace"], 1)
        _wait_for_control_marker(process["tool_started"])

        child.sendline("/model")
        child.expect("only /queue, /abort", timeout=5)
        _assert_no_control_trace(process["trace"], 2)

        child.sendline("/queue")
        child.expect("Message Queue Status", timeout=5)
        _assert_no_control_trace(process["trace"], 2)
    finally:
        process["release"].write_text("release", encoding="utf-8")
        child.close(force=True)


def test_live_ctrl_c_interrupts_one_turn_and_preserves_recovered_draft(tmp_path):
    """Prompt Toolkit Ctrl+C cancels the active Turn through its own token."""
    _require_prompt_toolkit()
    process = _spawn_controlled_turn_process(
        tmp_path, prompt_toolkit_enabled=True, stream_mode="cancel"
    )
    child = process["child"]
    try:
        _wait_for_prompt(child)
        child.sendline("cancel this task")
        _wait_for_control_trace(process["trace"], 1)
        _wait_for_control_marker(process["tool_started"])

        child.sendcontrol("c")
        child.sendline("/queue")
        child.expect("Status: interrupted", timeout=10)
        child.expect(r"Queued: 1 message\(s\)", timeout=10)

        child.sendline("/abort")
        child.expect("no active Turn; queued messages preserved", timeout=10)
        child.sendline("/abort --all")
        child.expect("cleared 1 queued message", timeout=10)
        child.sendline("/queue")
        child.expect(r"Queued: 0 message\(s\)", timeout=10)
    except (pexpect.TIMEOUT, pexpect.EOF) as e:
        print(f"\n=== OUTPUT ===\n{child.before}")
        pytest.fail(f"live Ctrl+C cancellation failed: {e}")
    finally:
        if child.isalive():
            child.close(force=True)


def test_prompt_toolkit_text_stream_is_not_torn_apart(tmp_path):
    """A text-only stream completes before a submitted follow-up is requested."""
    _require_prompt_toolkit()
    process = _spawn_controlled_turn_process(
        tmp_path, prompt_toolkit_enabled=True, stream_mode="text"
    )
    child = process["child"]
    try:
        _wait_for_prompt(child)
        child.sendline("text streaming task")
        _wait_for_control_trace(process["trace"], 1)
        _wait_for_control_marker(process["stream_open"])
        assert process["mode"].read_text(encoding="utf-8") == "prompt_toolkit"

        # Alt+Enter explicitly queues a natural-completion follow-up while a
        # text-only stream is active; plain Enter is reserved for steering.
        child.send("follow-up after text")
        child.send("\x1b\r")
        _assert_no_control_trace(process["trace"], 2)

        process["release"].write_text("release", encoding="utf-8")
        _wait_for_control_marker(process["stream_complete"])
        child.expect("second chunk", timeout=10)
        records = _wait_for_control_trace(process["trace"], 2)
        assert records[1]["users"][-1] == "follow-up after text"
        child.expect("follow-up done", timeout=10)
    finally:
        child.close(force=True)


def test_readline_fallback_stays_serial_during_blocking_tool(tmp_path):
    """The readline fallback buffers input until the active Turn completes."""
    process = _spawn_controlled_turn_process(
        tmp_path, prompt_toolkit_enabled=False, stream_mode="tool"
    )
    child = process["child"]
    try:
        _wait_for_prompt(child)
        child.sendline("serial task")
        records = _wait_for_control_trace(process["trace"], 1)
        assert records[0]["users"][-1] == "serial task"
        _wait_for_control_marker(process["tool_started"])
        assert process["mode"].read_text(encoding="utf-8") == "readline"

        child.sendline("buffered follow-up")
        _assert_no_control_trace(process["trace"], 2)

        process["release"].write_text("release", encoding="utf-8")
        records = _wait_for_control_trace(process["trace"], 2)
        assert records[1]["users"][-1] == "serial task"
        child.expect("first turn done", timeout=10)

        records = _wait_for_control_trace(process["trace"], 3)
        assert records[2]["users"][-1] == "buffered follow-up"
        child.expect("follow-up done", timeout=10)
    finally:
        child.close(force=True)
