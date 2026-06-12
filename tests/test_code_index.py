from __future__ import annotations

import json
from pathlib import Path

from tools import code_index


def _write_sample_project(root: Path) -> None:
    (root / "core").mkdir()
    (root / "pawnlogic").mkdir()
    (root / "core" / "session.py").write_text(
        """
class AgentSession:
    def handle_interrupt(self):
        return "stopped"

    async def run_turn(self):
        self.handle_interrupt()


def helper():
    session = AgentSession()
    return session.handle_interrupt()
""".lstrip(),
        encoding="utf-8",
    )
    (root / "pawnlogic" / "cli.py").write_text(
        """
from core.session import AgentSession


def main():
    agent = AgentSession()
    return agent.handle_interrupt()
""".lstrip(),
        encoding="utf-8",
    )


def test_build_generates_index(tmp_path, monkeypatch):
    _write_sample_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert code_index.main(["build"]) == 0

    index_path = tmp_path / ".pawnlogic_index" / "code_index.json"
    meta_path = tmp_path / ".pawnlogic_index" / "code_index.meta.json"
    assert index_path.exists()
    assert meta_path.exists()

    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert sorted(index["files"]) == ["core/session.py", "pawnlogic/cli.py"]
    assert "handle_interrupt" in index["symbols"]
    assert "handle_interrupt" in index["refs"]

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["file_count"] == 2
    assert meta["symbol_count"] >= 4


def test_symbol_finds_method_location(tmp_path, monkeypatch, capsys):
    _write_sample_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    code_index.main(["build"])

    assert code_index.main(["symbol", "handle_interrupt"]) == 0

    out = capsys.readouterr().out
    assert "core/session.py:2-3" in out
    assert "method  AgentSession.handle_interrupt" in out


def test_refs_finds_name_and_attribute_references(tmp_path, monkeypatch, capsys):
    _write_sample_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    code_index.main(["build"])

    assert code_index.main(["refs", "handle_interrupt"]) == 0

    out = capsys.readouterr().out
    assert "core/session.py:6" in out
    assert "self.handle_interrupt()" in out
    assert "pawnlogic/cli.py:6" in out
    assert "agent.handle_interrupt()" in out


def test_update_replaces_single_file_entries(tmp_path, monkeypatch, capsys):
    _write_sample_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    code_index.main(["build"])

    (tmp_path / "core" / "session.py").write_text(
        """
def renamed_interrupt():
    return True
""".lstrip(),
        encoding="utf-8",
    )

    assert code_index.main(["update", "core/session.py"]) == 0

    index = json.loads((tmp_path / ".pawnlogic_index" / "code_index.json").read_text(encoding="utf-8"))
    assert "renamed_interrupt" in index["symbols"]
    assert "AgentSession.handle_interrupt" not in index["symbols"]
    assert code_index.main(["symbol", "renamed_interrupt"]) == 0
    assert "core/session.py:1-2" in capsys.readouterr().out


def test_update_removes_deleted_file(tmp_path, monkeypatch):
    _write_sample_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    code_index.main(["build"])

    (tmp_path / "pawnlogic" / "cli.py").unlink()

    assert code_index.main(["update", "pawnlogic/cli.py"]) == 0

    index = json.loads((tmp_path / ".pawnlogic_index" / "code_index.json").read_text(encoding="utf-8"))
    assert "pawnlogic/cli.py" not in index["files"]
