from __future__ import annotations

from pathlib import Path

from tools import lsp_lite


def test_find_symbol_uses_python_ast_for_functions_and_classes(tmp_path, capsys):
    source = tmp_path / "sample.py"
    source.write_text(
        "class TargetThing:\n"
        "    pass\n\n"
        "def target_function():\n"
        "    return 1\n",
        encoding="utf-8",
    )

    result = lsp_lite.tool_find_symbol({"symbol": "target", "root": str(tmp_path)})

    assert "Found 2 definition(s)" in result
    assert f"{source}:1" in result
    assert f"{source}:4" in result
    assert "TargetThing" in result
    assert "target_function" in result
    assert "[LSP-lite] find_symbol" in capsys.readouterr().out


def test_find_symbol_reports_missing_symbol_without_crashing(tmp_path):
    (tmp_path / "sample.py").write_text("def present():\n    return 1\n", encoding="utf-8")

    result = lsp_lite.tool_find_symbol({"symbol": "absent", "root": str(tmp_path)})

    assert "No definitions found for 'absent'" in result
    assert "try find_refs" in result


def test_find_symbol_requires_symbol_parameter():
    assert lsp_lite.tool_find_symbol({"root": "."}) == "ERROR: 'symbol' parameter is required"


def test_find_refs_limits_results_and_prints_relative_paths(tmp_path):
    for index in range(5):
        (tmp_path / f"file_{index}.py").write_text(
            f"target_name = {index}\nprint(target_name)\n",
            encoding="utf-8",
        )

    result = lsp_lite.tool_find_refs({
        "symbol": "target_name",
        "root": str(tmp_path),
        "max_results": 3,
    })

    lines = result.splitlines()
    assert lines[0] == "Found 3 reference(s) for 'target_name':"
    assert len(lines) == 4
    assert all(str(tmp_path) not in line for line in lines[1:])


def test_walk_files_skips_generated_and_dependency_directories(tmp_path):
    kept = tmp_path / "src" / "app.py"
    kept.parent.mkdir()
    kept.write_text("x = 1\n", encoding="utf-8")
    skipped = tmp_path / ".venv" / "lib.py"
    skipped.parent.mkdir()
    skipped.write_text("x = 2\n", encoding="utf-8")
    git_file = tmp_path / ".git" / "config"
    git_file.parent.mkdir()
    git_file.write_text("[core]\n", encoding="utf-8")

    paths = {Path(path).relative_to(tmp_path).as_posix() for path in lsp_lite._walk_files(str(tmp_path))}

    assert paths == {"src/app.py"}


def test_class_tree_lists_python_classes_and_bases(tmp_path):
    source = tmp_path / "classes.py"
    source.write_text(
        "class Base:\n"
        "    pass\n\n"
        "class Child(Base):\n"
        "    pass\n",
        encoding="utf-8",
    )

    result = lsp_lite.tool_class_tree({"root": str(tmp_path)})

    assert "Python class hierarchy (2 classes found" in result
    assert "Child" in result
    assert "extends [Base]" in result
