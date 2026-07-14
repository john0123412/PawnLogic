"""Focused tests for startup and REPL ownership extracted from cli.py."""

from pawnlogic.repl import ReplSignalState, restore_last_input_buffer
from pawnlogic.startup import default_pawnlogic_home, ensure_runtime_dir_writable


def test_default_home_honors_runtime_override(monkeypatch, tmp_path):
    monkeypatch.setenv("PAWNLOGIC_HOME", str(tmp_path / "runtime"))
    assert default_pawnlogic_home() == tmp_path / "runtime"


def test_runtime_probe_is_removed(monkeypatch, tmp_path):
    runtime = tmp_path / "runtime"
    ensure_runtime_dir_writable(runtime)
    assert runtime.is_dir()
    assert not (runtime / ".write_test").exists()


def test_repl_signal_state_requires_two_interrupts_inside_window():
    state = ReplSignalState()
    assert state.interrupt_requests_exit(now=10.0) is False
    assert state.interrupt_requests_exit(now=14.9) is True
    state.submitted()
    assert state.interrupt_requests_exit(now=15.0) is False


def test_repl_restore_request_is_consumed_once():
    state = ReplSignalState()
    state.request_last_input_restore()
    assert state.consume_last_input_restore() is True
    assert state.consume_last_input_restore() is False


def test_restore_buffer_preserves_unsent_alternate():
    class Buffer:
        text = "draft"
        cursor_position = 0

    buffer = Buffer()
    state: dict[str, str] = {}
    assert restore_last_input_buffer(buffer, "last", state) is True
    assert buffer.text == "last"
    assert state == {"alternate": "draft"}
    assert restore_last_input_buffer(buffer, "last", state) is True
    assert buffer.text == "draft"
