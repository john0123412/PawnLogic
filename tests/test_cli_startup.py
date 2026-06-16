"""CLI startup behavior tests."""

from __future__ import annotations

from types import SimpleNamespace

from core import memory
from pawnlogic import cli as cli_mod


def test_startup_resume_prompt_warns_and_continues_on_session_lookup_failure(
    monkeypatch,
    capsys,
):
    logged: list[str] = []

    class FakeLogger:
        def warning(self, msg, *args):
            logged.append(msg.format(*args))

    def fail_list_sessions(_limit):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(memory, "list_sessions", fail_list_sessions)
    monkeypatch.setattr(cli_mod, "logger", FakeLogger())
    monkeypatch.setattr(cli_mod._runtime_state, "user_mode", True)

    resumed = cli_mod._prompt_startup_resume(SimpleNamespace(messages=[]))

    assert resumed is False
    assert "Startup session resume failed" in logged[0]
    assert "database unavailable" in logged[0]
    assert "Could not load recent sessions" in capsys.readouterr().out
