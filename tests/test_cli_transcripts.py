from __future__ import annotations

from config.providers import PROVIDERS
from config import providers as provider_config
from core.commands import provider as provider_cmd
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
    assert "Delegated Agents" in transcript
    assert "/agent policy show" in transcript
    assert "Debug mode enabled" in transcript
    assert "User-friendly mode enabled" in transcript
    assert "Providers:" in transcript
    assert "deepseek" in transcript
    assert "No models with configured API keys are available" in transcript


def test_transcript_runner_isolates_registered_provider_api_keys(tmp_path, monkeypatch):
    async def unexpected_model_selector(*_args, **_kwargs):
        raise AssertionError("/model must not open an interactive selector in transcripts")

    monkeypatch.setattr(provider_cmd, "cc_style_model_selector", unexpected_model_selector)

    provider_env = {
        str(provider["api_key_env"]): "test-transcript-key"
        for provider in PROVIDERS.values()
        if provider.get("api_key_env")
    }
    result = run_transcript(["/model"], cwd=tmp_path, env=provider_env)

    assert "No models with configured API keys are available" in result.output
    assert "Available models" not in result.output


def test_transcript_runner_does_not_initialize_runtime_provider_config(tmp_path, monkeypatch):
    monkeypatch.setattr(provider_config, "_providers_initialized", False)

    def unexpected_provider_load():
        raise AssertionError("transcripts must not load runtime provider configuration")

    monkeypatch.setattr(provider_config, "load_custom_providers", unexpected_provider_load)

    result = run_transcript(["/model"], cwd=tmp_path)

    assert "No models with configured API keys are available" in result.output


def test_transcript_runner_keeps_unknown_command_user_visible(tmp_path):
    result = run_transcript(["/__missing"], cwd=tmp_path)

    assert result.exit_requested is False
    assert "Unknown command '/__missing'. Type /help." in result.output


def test_transcript_runner_exposes_extension_command_without_startup_manager(tmp_path):
    result = run_transcript(["/extension"], cwd=tmp_path)

    assert result.exit_requested is False
    assert "Extension manager is unavailable" in result.output
