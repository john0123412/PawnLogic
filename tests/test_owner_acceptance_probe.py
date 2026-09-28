from __future__ import annotations

import json

import pytest

from tools import owner_acceptance_probe
from tools.owner_acceptance_probe import (
    build_parser,
    build_target_command,
    evaluate_terminal_transcript,
)


def test_healthy_ratatui_terminal_restore_sequence_passes() -> None:
    transcript = "".join(
        (
            "\x1b[?1049h",
            "\x1b[?25l",
            "\x1b[?1000h",
            "\x1b[?1006h",
            "\x1b[?2004h",
            "application output",
            "\x1b[?25h",
            "\x1b[?2004l",
            "\x1b[?1006l",
            "\x1b[?1015l",
            "\x1b[?1003l",
            "\x1b[?1002l",
            "\x1b[?1000l",
            "\x1b[?1049l",
        )
    )

    result = evaluate_terminal_transcript(transcript)

    assert result["status"] == "pass"


@pytest.mark.parametrize(
    ("enabled", "disabled"),
    (
        ("\x1b[?2004h", "\x1b[?2004l"),
        ("\x1b[?1000h", "\x1b[?1000l"),
    ),
)
def test_terminal_mode_without_a_later_disable_fails(
    enabled: str, disabled: str
) -> None:
    transcript = f"{disabled}{enabled}application output"

    result = evaluate_terminal_transcript(transcript)

    assert result["status"] == "fail"
    assert "left enabled at exit" in result["detail"]


def test_cli_builds_binary_and_source_checkout_commands() -> None:
    parser = build_parser()

    binary_args = parser.parse_args(["--binary", "/release/pawnlogic-tui"])
    source_args = parser.parse_args(["--python"])

    assert build_target_command(binary_args) == ["/release/pawnlogic-tui"]
    assert build_target_command(source_args) == [
        owner_acceptance_probe.sys.executable,
        "-m",
        "pawnlogic",
    ]
    assert "python tools/owner_acceptance_probe.py --binary <path>" in (
        owner_acceptance_probe.__doc__ or ""
    )
    assert "python tools/owner_acceptance_probe.py --python" in (
        owner_acceptance_probe.__doc__ or ""
    )


def test_repeated_manual_results_are_reflected_in_json_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        owner_acceptance_probe,
        "check_entrypoint",
        lambda argv, env: {
            "check": "entrypoint_help",
            "status": "pass",
            "detail": "ok",
        },
    )
    monkeypatch.setattr(
        owner_acceptance_probe,
        "check_pty_session",
        lambda argv, env: {
            "check": "terminal_state_restore",
            "status": "pass",
            "detail": "ok",
        },
    )

    exit_code = owner_acceptance_probe.main(
        [
            "--binary",
            "/release/pawnlogic-tui",
            "--isolated",
            "--manual-pass",
            "scrollback",
            "--manual-pass",
            "selection_copy",
            "--manual-fail",
            "glyph_width",
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert report["automated_passed"] == 2
    assert report["automated_total"] == 2
    assert report["automated_failed"] == []
    assert report["manual_passed"] == ["scrollback", "selection_copy"]
    assert report["manual_failed"] == ["glyph_width"]
    assert report["manual_pending"] == ["no_duplicate_output"]
    assert {check["check"]: check["status"] for check in report["checks"]} == {
        "entrypoint_help": "pass",
        "terminal_state_restore": "pass",
        "scrollback": "pass",
        "selection_copy": "pass",
        "glyph_width": "fail",
        "no_duplicate_output": "manual",
    }


def test_skipped_automation_is_not_counted_as_a_decided_check(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        owner_acceptance_probe,
        "check_entrypoint",
        lambda argv, env: {
            "check": "entrypoint_help",
            "status": "pass",
            "detail": "ok",
        },
    )
    monkeypatch.setattr(
        owner_acceptance_probe,
        "check_pty_session",
        lambda argv, env: {
            "check": "terminal_state_restore",
            "status": "skip",
            "detail": "not available",
        },
    )

    exit_code = owner_acceptance_probe.main(["--binary", "/bin/true", "--isolated"])
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["automated_passed"] == 1
    assert report["automated_total"] == 1
    assert report["automated_skipped"] == ["terminal_state_restore"]
