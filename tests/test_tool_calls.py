"""Tests for hybrid XML/JSON tool call parsing helpers."""

from __future__ import annotations

import json

from core.tool_calls import extract_tool_calls


def test_extract_tool_calls_xml_full():
    text = '<call name="run_shell"><command>ls -la</command></call>'

    calls = extract_tool_calls(text)

    assert calls == [
        {
            "name": "run_shell",
            "args": {"command": "ls -la"},
            "_source": "xml",
        }
    ]


def test_extract_tool_calls_xml_multiline():
    text = (
        '<call name="write_file">\n'
        "<path>test.py</path>\n"
        '<content>print("hi")\n</content>\n'
        "</call>"
    )

    calls = extract_tool_calls(text)

    assert calls[0]["name"] == "write_file"
    assert calls[0]["args"]["path"] == "test.py"
    assert calls[0]["args"]["content"] == 'print("hi")'


def test_extract_tool_calls_xml_coerces_int_and_bool():
    text = (
        '<call name="run_code">'
        "<timeout>30</timeout>"
        "<use_venv>true</use_venv>"
        "<debug>false</debug>"
        "<code>x=1</code>"
        "</call>"
    )

    calls = extract_tool_calls(text)

    assert calls[0]["args"] == {
        "timeout": 30,
        "use_venv": True,
        "debug": False,
        "code": "x=1",
    }


def test_extract_tool_calls_xml_partial_invokes_callback():
    partial_hits = []
    text = '<call name="run_shell"><command>echo hi</command>'

    calls = extract_tool_calls(text, on_partial_xml=lambda: partial_hits.append(True))

    assert calls[0]["name"] == "run_shell"
    assert calls[0]["args"]["command"] == "echo hi"
    assert partial_hits == [True]


def test_extract_tool_calls_json_fallback():
    payload = {"name": "list_dir", "arguments": {"path": "/tmp"}}
    text = f"<tool_call>{json.dumps(payload)}</tool_call>"

    calls = extract_tool_calls(text)

    assert calls == [
        {
            "name": "list_dir",
            "args": {"path": "/tmp"},
            "_source": "json",
        }
    ]


def test_extract_tool_calls_json_non_dict_arguments_are_wrapped():
    payload = {"name": "run_shell", "arguments": "echo hi"}
    text = f"<tool_call>{json.dumps(payload)}</tool_call>"

    calls = extract_tool_calls(text)

    assert calls[0]["args"] == {"_raw_args": "echo hi"}


def test_extract_tool_calls_dirty_json_rescue_invokes_callback():
    rescued_hits = []
    text = (
        '<tool_call>{"name":"write_file","arguments":'
        '{"path":"x.py","content":"print("hi")"}}</tool_call>'
    )

    calls = extract_tool_calls(
        text,
        on_dirty_json_rescued=lambda: rescued_hits.append(True),
    )

    assert calls == [
        {
            "name": "write_file",
            "args": {"path": "x.py", "content": 'print("hi")'},
            "_source": "json_rescued",
        }
    ]
    assert rescued_hits == [True]


def test_extract_tool_calls_malformed_json_invokes_error_callback():
    errors = []
    text = '<tool_call>{"name":</tool_call>'

    calls = extract_tool_calls(
        text,
        on_json_error=lambda exc, raw: errors.append((exc, raw)),
    )

    assert calls == []
    assert len(errors) == 1
    assert errors[0][1] == '{"name":'
