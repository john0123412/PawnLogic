"""
Dynamic E2E tests — spawn real PawnLogic process and interact via pexpect.

These tests verify the CLI agent can start, process slash commands, and
exit cleanly without requiring real API keys (PAWNLOGIC_TEST_MODE=true).
"""

import os
import sys
import pytest

try:
    import pexpect
except ImportError:
    pytest.skip("pexpect not available (Windows or not installed)", allow_module_level=True)


def _wait_for_prompt(child, timeout=15):
    """Wait for PawnLogic to show main prompt, handling session selection first."""
    try:
        # First, handle session selection screen
        child.expect(["恢复会话", "Resume session", "Enter"], timeout=timeout)
        child.sendline("")  # Start new session
        # Then wait for main prompt
        child.expect(["You >", "You>"], timeout=10)
    except pexpect.TIMEOUT:
        # Maybe already at prompt (no sessions to select)
        pass


@pytest.fixture
def spawn_pawnlogic():
    """Spawn a PawnLogic process with test env vars, yield child, cleanup."""
    import shutil
    from pathlib import Path
    
    # Temporarily rename mcp_configs.json to prevent MCP loading in E2E tests
    mcp_config = Path.home() / ".pawnlogic" / "mcp_configs.json"
    mcp_backup = mcp_config.with_suffix(".json.e2e_backup")
    if mcp_config.exists():
        shutil.move(str(mcp_config), str(mcp_backup))
    
    env = os.environ.copy()
    env.update({
        "PAWNLOGIC_TEST_MODE": "true",
        "DEEPSEEK_API_KEY": "sk-test-fake-key-for-ci",
        "PAWN_API_KEY": "test-fake-key",
        "ANTHROPIC_API_KEY": "sk-ant-test-fake",
        "TERM": "dumb",
        "NO_COLOR": "1",
        "MCP_ENABLED": "false",  # Skip MCP for faster E2E startup
        "PROMPT_TOOLKIT_ENABLED": "0",  # Force simple input() mode
    })

    # Use sys.executable to ensure we use the correct python interpreter
    python_cmd = sys.executable if sys.executable else "python"
    child = pexpect.spawn(
        f"{python_cmd} main.py",
        timeout=15,
        encoding="utf-8",
        env=env,
    )

    try:
        yield child
    finally:
        if child.isalive():
            child.close(force=True)
        # Restore mcp_configs.json
        if mcp_backup.exists():
            shutil.move(str(mcp_backup), str(mcp_config))


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


def test_slash_keys(spawn_pawnlogic):
    """Send /keys and verify output contains provider/API info."""
    child = spawn_pawnlogic
    try:
        _wait_for_prompt(child)
        child.sendline("/keys")
        child.expect(["Provider", "API", "Key", "配置"], timeout=10)
    except (pexpect.TIMEOUT, pexpect.EOF) as e:
        print(f"\n=== OUTPUT ===\n{child.before}")
        pytest.fail(f"/keys failed: {e}")


def test_slash_mode(spawn_pawnlogic):
    """Send /mode and verify output contains USER/DEV mode info."""
    child = spawn_pawnlogic
    try:
        _wait_for_prompt(child)
        child.sendline("/mode")
        child.expect(["USER", "DEV", "模式"], timeout=10)
    except (pexpect.TIMEOUT, pexpect.EOF) as e:
        print(f"\n=== OUTPUT ===\n{child.before}")
        pytest.fail(f"/mode failed: {e}")


def test_slash_limits(spawn_pawnlogic):
    """Send /limits and verify output contains token/ctx info."""
    child = spawn_pawnlogic
    try:
        _wait_for_prompt(child)
        child.sendline("/limits")
        child.expect(["tokens", "token", "ctx", "上下文"], timeout=10)
    except (pexpect.TIMEOUT, pexpect.EOF) as e:
        print(f"\n=== OUTPUT ===\n{child.before}")
        pytest.fail(f"/limits failed: {e}")


def test_slash_sessions(spawn_pawnlogic):
    """Send /sessions and verify output contains session info."""
    child = spawn_pawnlogic
    try:
        _wait_for_prompt(child)
        child.sendline("/sessions")
        child.expect(["session", "Session", "暂无", r"\(无", "会话"], timeout=10)
    except (pexpect.TIMEOUT, pexpect.EOF) as e:
        print(f"\n=== OUTPUT ===\n{child.before}")
        pytest.fail(f"/sessions failed: {e}")


def test_slash_model_list(spawn_pawnlogic):
    """Send /model and verify output contains model list."""
    child = spawn_pawnlogic
    try:
        _wait_for_prompt(child)
        child.sendline("/model")
        child.expect(["ds-", "claude", "hermes", "模型"], timeout=10)
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
