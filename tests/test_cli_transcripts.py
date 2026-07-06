from __future__ import annotations

from tools.cli_transcript_runner import run_transcript


def test_transcript_runner_covers_core_cli_commands(tmp_path):
    result = run_transcript(
        [
            "/help",
            "/mode",
            "/mode",
            "/provider list",
            "/model",
            "/exit",
        ],
        cwd=tmp_path,
        env={
            "DEEPSEEK_API_KEY": "",
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "PROMPT_TOOLKIT_ENABLED": "0",
        },
    )

    assert result.exit_requested is True
    assert result.commands == [
        "/help",
        "/mode",
        "/mode",
        "/provider list",
        "/model",
        "/exit",
    ]

    transcript = result.output
    assert "PawnLogic" in transcript
    assert "/provider list" in transcript
    assert "Debug mode enabled" in transcript
    assert "User-friendly mode enabled" in transcript
    assert "Providers:" in transcript
    assert "deepseek" in transcript
    assert "No models with configured API keys are available" in transcript


def test_transcript_runner_keeps_unknown_command_user_visible(tmp_path):
    result = run_transcript(["/__missing"], cwd=tmp_path)

    assert result.exit_requested is False
    assert "Unknown command '/__missing'. Type /help." in result.output
