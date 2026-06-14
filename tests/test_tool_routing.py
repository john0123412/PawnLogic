"""Tests for phase-aware tool schema routing."""

from core.tool_routing import phase_tool_names, select_phase_tools


def _schema(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}


def test_select_phase_tools_keeps_phase_and_always_available_tools():
    schemas = [
        _schema("read_file"),
        _schema("run_shell"),
        _schema("switch_phase"),
        _schema("bump_skill"),
        _schema("web_search"),
    ]
    phases = {"RECON": ["read_file", "web_search"], "EXPLOIT": ["run_shell"]}

    selected = select_phase_tools(schemas, phases, "RECON")

    assert [s["function"]["name"] for s in selected] == [
        "read_file",
        "switch_phase",
        "bump_skill",
        "web_search",
    ]


def test_select_phase_tools_keeps_always_available_tools_for_unknown_phase():
    schemas = [_schema("read_file"), _schema("switch_phase"), _schema("bump_skill")]

    selected = select_phase_tools(schemas, {"RECON": ["read_file"]}, "MISSING")

    assert [s["function"]["name"] for s in selected] == ["switch_phase", "bump_skill"]


def test_select_phase_tools_allows_custom_always_available_set():
    schemas = [_schema("read_file"), _schema("audit_payload"), _schema("switch_phase")]

    selected = select_phase_tools(
        schemas,
        {"RECON": []},
        "RECON",
        always_available=("audit_payload",),
    )

    assert [s["function"]["name"] for s in selected] == ["audit_payload"]


def test_phase_tool_names_returns_configured_phase_set():
    assert phase_tool_names({"RECON": ["read_file", "web_search"]}, "RECON") == {
        "read_file",
        "web_search",
    }
    assert phase_tool_names({"RECON": ["read_file"]}, "MISSING") == set()
