from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from core import ctf_workspace
from core.commands import CommandContext, dispatch
from core.commands import ctf as ctf_cmd
from core.ctf_workspace import (
    add_artifact,
    add_flag_candidate,
    add_remote_target,
    ctf_audit_metadata,
    export_ctf_writeup,
    format_ctf_status,
    init_ctf_metadata,
    load_ctf_metadata,
    metadata_path,
)
from core import logger as logger_mod


class CaptureSink:
    def __init__(self):
        self.output: list[str] = []

    def print(self, text: str = "") -> None:
        self.output.append(text)

    def write(self, text: str) -> None:
        self.output.append(text)


def test_ctf_metadata_round_trip(tmp_path):
    metadata = init_ctf_metadata(
        tmp_path,
        challenge_name="heap warmup",
        category="pwn",
        source="local lab",
    )
    assert metadata.challenge_name == "heap warmup"

    add_artifact(tmp_path, "challenge")
    add_remote_target(tmp_path, "localhost:31337")
    add_flag_candidate(tmp_path, "flag{candidate}")

    loaded = load_ctf_metadata(tmp_path)
    assert loaded is not None
    assert loaded.category == "pwn"
    assert loaded.artifacts == ["challenge"]
    assert loaded.remote_targets == ["localhost:31337"]
    assert loaded.flag_candidates == ["flag{candidate}"]
    assert loaded.status == "flag-candidate"

    audit = ctf_audit_metadata(tmp_path)
    assert audit == {
        "challenge_name": "heap warmup",
        "category": "pwn",
        "workspace": str(tmp_path),
        "status": "flag-candidate",
        "artifacts": ["challenge"],
        "remote_targets": ["localhost:31337"],
        "flag_candidates": ["flag{candidate}"],
    }


def test_metadata_path_does_not_create_workspace(tmp_path):
    missing = tmp_path / "missing"

    assert metadata_path(missing) == missing / "ctf.json"
    assert not missing.exists()


def test_ctf_metadata_save_uses_same_directory_atomic_replace(monkeypatch, tmp_path):
    calls: list[tuple[Path, Path]] = []
    original_replace = ctf_workspace.os.replace

    def fake_replace(src, dst):
        src_path = Path(src)
        dst_path = Path(dst)
        calls.append((src_path, dst_path))
        assert src_path.parent == tmp_path
        assert src_path.name.startswith(".ctf.json.")
        assert src_path.name.endswith(".tmp")
        assert dst_path == tmp_path / "ctf.json"
        original_replace(src, dst)

    monkeypatch.setattr(ctf_workspace.os, "replace", fake_replace)

    metadata = ctf_workspace.CTFMetadata.new(challenge_name="atomic warmup")
    ctf_workspace.save_ctf_metadata(tmp_path, metadata)

    assert calls
    assert json.loads((tmp_path / "ctf.json").read_text(encoding="utf-8"))[
        "challenge_name"
    ] == "atomic warmup"


def test_ctf_metadata_save_cleans_temp_file_on_replace_failure(monkeypatch, tmp_path):
    def fail_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(ctf_workspace.os, "replace", fail_replace)

    metadata = ctf_workspace.CTFMetadata.new(challenge_name="write failure")
    try:
        ctf_workspace.save_ctf_metadata(tmp_path, metadata)
    except OSError as exc:
        assert "disk full" in str(exc)
    else:
        raise AssertionError("expected OSError")

    assert not list(tmp_path.glob(".ctf.json.*.tmp"))
    assert not (tmp_path / "ctf.json").exists()


def test_load_ctf_metadata_corrupt_json_and_non_dict_paths(tmp_path):
    path = tmp_path / "ctf.json"
    path.write_text("{bad json", encoding="utf-8")

    assert load_ctf_metadata(tmp_path) is None
    try:
        load_ctf_metadata(tmp_path, strict=True)
    except ctf_workspace.CTFMetadataReadError as exc:
        assert "Invalid CTF metadata JSON" in str(exc)
    else:
        raise AssertionError("expected CTFMetadataReadError")

    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_ctf_metadata(tmp_path) is None
    try:
        load_ctf_metadata(tmp_path, strict=True)
    except ctf_workspace.CTFMetadataReadError as exc:
        assert "must contain a JSON object" in str(exc)
    else:
        raise AssertionError("expected CTFMetadataReadError")


def test_export_ctf_writeup_does_not_overwrite_corrupt_metadata(tmp_path):
    path = tmp_path / "ctf.json"
    path.write_text("{bad json", encoding="utf-8")

    try:
        export_ctf_writeup(tmp_path, messages=[], session_id="sid")
    except ctf_workspace.CTFMetadataReadError:
        pass
    else:
        raise AssertionError("expected CTFMetadataReadError")

    assert path.read_text(encoding="utf-8") == "{bad json"
    assert not (tmp_path / "writeup.md").exists()


def test_ctf_status_does_not_create_missing_workspace(tmp_path):
    missing = tmp_path / "missing"
    sink = CaptureSink()
    session = SimpleNamespace(
        workspace_dir=str(missing),
        cwd=str(missing),
        messages=[],
        session_id="sid",
    )

    asyncio.run(dispatch(CommandContext(
        verb="/ctf",
        arg="status",
        arg2="",
        session=session,
        sink=sink,
    )))

    assert not missing.exists()
    assert any("No CTF metadata found" in line for line in sink.output)


def test_ctf_command_reports_write_errors(monkeypatch, tmp_path):
    def fail_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(ctf_workspace.os, "replace", fail_replace)
    sink = CaptureSink()
    session = SimpleNamespace(
        workspace_dir=str(tmp_path),
        cwd=str(tmp_path),
        messages=[],
        session_id="sid",
    )

    asyncio.run(dispatch(CommandContext(
        verb="/ctf",
        arg="init",
        arg2="heap warmup",
        session=session,
        sink=sink,
    )))

    assert any("Unable to update CTF workspace" in line for line in sink.output)


def test_ctf_command_writes_workspace_metadata(tmp_path):
    sink = CaptureSink()
    session = SimpleNamespace(
        workspace_dir=str(tmp_path),
        cwd=str(tmp_path),
        messages=[],
        session_id="sid",
    )

    asyncio.run(dispatch(CommandContext(
        verb="/ctf",
        arg="init",
        arg2="heap warmup --category pwn --source local",
        session=session,
        sink=sink,
    )))
    asyncio.run(dispatch(CommandContext(
        verb="/ctf",
        arg="artifact",
        arg2="./challenge",
        session=session,
        sink=sink,
    )))
    asyncio.run(dispatch(CommandContext(
        verb="/ctf",
        arg="flag",
        arg2="flag{candidate}",
        session=session,
        sink=sink,
    )))

    data = json.loads((tmp_path / "ctf.json").read_text(encoding="utf-8"))
    assert data["challenge_name"] == "heap warmup"
    assert data["category"] == "pwn"
    assert data["source"] == "local"
    assert data["artifacts"] == ["./challenge"]
    assert data["flag_candidates"] == ["flag{candidate}"]
    assert any("Recorded flag candidate" in line for line in sink.output)


def test_ctf_writeup_export_redacts_sensitive_message_lines(tmp_path):
    init_ctf_metadata(tmp_path, challenge_name="crypto warmup", category="crypto")
    add_artifact(tmp_path, "cipher.txt")
    messages = [
        {"role": "user", "content": "OPENAI_API_KEY=sk-secret-value"},
        {"role": "assistant", "content": "Recovered xor key from known plaintext."},
    ]

    output = export_ctf_writeup(tmp_path, messages=messages, session_id="sid")
    text = output.read_text(encoding="utf-8")

    assert output == tmp_path / "writeup.md"
    assert "# crypto warmup Writeup" in text
    assert "cipher.txt" in text
    assert "[redacted sensitive line]" in text
    assert "sk-secret-value" not in text
    assert "Draft: no confirmed flag candidate recorded." in text


def test_ctf_writeup_redaction_avoids_secret_substring_false_positive(tmp_path):
    init_ctf_metadata(tmp_path, challenge_name="redaction warmup")
    messages = [
        {"role": "assistant", "content": "The secretive-looking clue is harmless."},
        {"role": "assistant", "content": "conservative parsing still matters."},
        {"role": "user", "content": "password=hunter2"},
    ]

    text = export_ctf_writeup(tmp_path, messages=messages, session_id="sid").read_text(
        encoding="utf-8"
    )

    assert "secretive-looking clue is harmless" in text
    assert "conservative parsing still matters" in text
    assert "hunter2" not in text
    assert "[redacted sensitive line]" in text


def test_ctf_writeup_requires_explicit_solved_status_for_flag_candidates(tmp_path):
    init_ctf_metadata(tmp_path, challenge_name="web warmup", category="web")
    add_flag_candidate(tmp_path, "flag{maybe}")

    output = export_ctf_writeup(tmp_path, messages=[], session_id="sid")
    text = output.read_text(encoding="utf-8")

    assert "| Status | flag-candidate |" in text
    assert "solved-draft" not in text
    assert "Unconfirmed flag candidate: flag{maybe}" in text

    ctf_workspace.confirm_flag_candidate(tmp_path)
    confirmed = export_ctf_writeup(tmp_path, messages=[], session_id="sid").read_text(
        encoding="utf-8"
    )
    assert "| Status | solved |" in confirmed
    assert "Unconfirmed flag candidate" not in confirmed
    assert "flag{maybe}" in confirmed


def test_ctf_writeup_escapes_session_id_table_cell(tmp_path):
    init_ctf_metadata(
        tmp_path,
        challenge_name="table|warmup",
        category="web|pwn",
        source="ctf`event",
    )

    output = export_ctf_writeup(tmp_path, messages=[], session_id="sid|with`chars")
    text = output.read_text(encoding="utf-8")

    assert "| Challenge | table\\|warmup |" in text
    assert "| Category | web\\|pwn |" in text
    assert "| Source | ctf\\`event |" in text
    assert "| Session | sid\\|with\\`chars |" in text


def test_ctf_lists_are_bounded_and_flags_keep_case_sensitive_values(tmp_path):
    init_ctf_metadata(tmp_path, challenge_name="bounded")

    for index in range(ctf_workspace.MAX_CTF_ITEMS + 5):
        add_artifact(tmp_path, f"artifact-{index}")
        add_remote_target(tmp_path, f"host-{index}:31337")
    add_flag_candidate(tmp_path, "flag{ABC}")
    add_flag_candidate(tmp_path, "flag{ABC}")
    add_flag_candidate(tmp_path, "flag{abc}")

    metadata = load_ctf_metadata(tmp_path)
    assert metadata is not None
    assert len(metadata.artifacts) == ctf_workspace.MAX_CTF_ITEMS
    assert len(metadata.remote_targets) == ctf_workspace.MAX_CTF_ITEMS
    assert metadata.artifacts[0] == "artifact-5"
    assert metadata.remote_targets[0] == "host-5:31337"
    assert metadata.flag_candidates == ["flag{ABC}", "flag{abc}"]


def test_ctf_audit_metadata_keeps_all_lists_and_zero_strings(tmp_path):
    init_ctf_metadata(tmp_path, challenge_name="0", category="0")
    add_artifact(tmp_path, "artifact-a")
    add_artifact(tmp_path, "artifact-b")
    add_remote_target(tmp_path, "0")
    add_flag_candidate(tmp_path, "0")

    assert ctf_audit_metadata(tmp_path) == {
        "challenge_name": "0",
        "category": "0",
        "workspace": str(tmp_path),
        "status": "flag-candidate",
        "artifacts": ["artifact-a", "artifact-b"],
        "remote_targets": ["0"],
        "flag_candidates": ["0"],
    }


def test_format_ctf_status_none_branch_does_not_create_workspace(tmp_path):
    missing = tmp_path / "missing"

    text = format_ctf_status(None, missing)

    assert "No CTF metadata found" in text
    assert str(missing) in text
    assert not missing.exists()


def test_parse_kv_args_supports_quotes_and_edge_cases():
    challenge, values = ctf_cmd._parse_kv_args(
        'heap warmup --category "web exploitation" --source "local lab"'
    )
    assert challenge == "heap warmup"
    assert values == {"category": "web exploitation", "source": "local lab"}

    challenge, values = ctf_cmd._parse_kv_args("heap -c pwn -s remote")
    assert challenge == "heap"
    assert values == {"category": "pwn", "source": "remote"}

    assert ctf_cmd._parse_kv_args("") == ("", {})
    assert ctf_cmd._parse_kv_args("heap --category") == ("heap --category", {})


def test_writeup_ignores_unknown_roles_and_non_dict_messages(tmp_path):
    init_ctf_metadata(tmp_path, challenge_name="message warmup")
    messages = [
        "not a dict",
        {"role": "system", "content": "hidden instruction"},
        {"role": "assistant", "content": "Visible evidence."},
    ]

    text = export_ctf_writeup(tmp_path, messages=messages, session_id="sid").read_text(
        encoding="utf-8"
    )

    assert "Visible evidence." in text
    assert "hidden instruction" not in text
    assert "not a dict" not in text


def test_export_ctf_writeup_without_existing_metadata_creates_draft(tmp_path):
    output = export_ctf_writeup(tmp_path, messages=[], session_id="sid")
    metadata = load_ctf_metadata(tmp_path)

    assert output == tmp_path / "writeup.md"
    assert metadata is not None
    assert metadata.status == "draft"
    assert "Untitled CTF Challenge" in output.read_text(encoding="utf-8")


def test_audit_tool_call_accepts_optional_metadata(monkeypatch):
    records: list[dict] = []

    class FakeAuditLogger:
        def info(self, payload: str) -> None:
            records.append(json.loads(payload))

    monkeypatch.setattr(logger_mod, "_audit_logger", FakeAuditLogger())

    logger_mod.audit_tool_call(
        tool_name="run_shell",
        args_summary="command='./solve'",
        result_len=12,
        elapsed_ms=34,
        session_id="session-123",
        model_alias="ds-v4-flash",
        iteration=2,
        success=True,
        metadata={"ctf": {"challenge_name": "warmup"}},
    )

    assert records
    assert records[0]["metadata"] == {"ctf": {"challenge_name": "warmup"}}
    assert records[0]["tool"] == "run_shell"


def test_third_party_notices_cover_tracked_ctf_skill_candidates():
    notices = (Path(__file__).resolve().parents[1] / "THIRD_PARTY_NOTICES.md").read_text(
        encoding="utf-8"
    )
    expected_paths = [
        "skills/ctf_app_system",
        "skills/ctf_automation",
        "skills/ctf_crypto",
        "skills/ctf_forensics",
        "skills/ctf_malware",
        "skills/ctf_misc",
        "skills/ctf_osint",
        "skills/ctf_pwn",
        "skills/ctf_reverse",
        "skills/ctf_web",
        "skills/solve_challenge",
        "skills/heap_exploit",
        "skills/demo_stack_overflow",
    ]

    for path in expected_paths:
        assert path in notices
    assert "generated release source archives" in notices


def test_ctf_skill_examples_do_not_embed_root_me_passwords():
    skill = (
        Path(__file__).resolve().parents[1] / "skills" / "ctf_app_system" / "skill.md"
    ).read_text(encoding="utf-8")

    assert "app-systeme-ch0" not in skill
    assert "app-systeme-ch12" not in skill
    assert "app-systeme-ch21" not in skill
    assert "password='<public-challenge-password>'" in skill


def test_changelog_012_has_tests_section():
    changelog = (Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text(
        encoding="utf-8"
    )
    section = changelog.split("## [0.1.2] - 2026-06-18", 1)[1].split("## [0.1.1]", 1)[0]

    assert "### Tests" in section
    assert "passed" in section
