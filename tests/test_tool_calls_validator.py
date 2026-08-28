"""Regression tests for ToolCallValidator repair logic (P0/P1/P2 fixes)."""

from core.tool_calls import extract_tool_calls, ToolCallValidator


# ── P0: XML Auto-Closure Tests ───────────────────

def test_validator_repair_unclosed_xml_appends_call_close():
    """A <call> without </call> should be auto-closed so the call is extractable."""
    text = '<call name="run_shell"><command>ls -la</command>'
    repaired = ToolCallValidator._repair_unclosed_xml_tags(text)
    assert '</call>' in repaired
    calls = extract_tool_calls(repaired)
    assert calls[0]["name"] == "run_shell"
    assert calls[0]["args"]["command"] == "ls -la"


def test_validator_repair_multiple_unclosed_xml():
    """Multiple unclosed <call> blocks should each get </call>."""
    text = (
        '<call name="run_shell"><command>echo a</command>'
        '<call name="read_file"><path>/tmp/test</path>'
    )
    repaired = ToolCallValidator._repair_unclosed_xml_tags(text)
    calls = extract_tool_calls(repaired)
    assert len(calls) == 2
    assert calls[0]["name"] == "run_shell"
    assert calls[1]["name"] == "read_file"


def test_validator_repair_preserves_already_closed_xml():
    """Already-closed <call> blocks should not be touched."""
    text = '<call name="run_shell"><command>ls</command></call>'
    repaired = ToolCallValidator._repair_unclosed_xml_tags(text)
    assert repaired == text


# ── P1/P2: JSON Format Repair Tests ───────────────────

def test_validator_repair_json_fixes_trailing_comma():
    """Trailing comma in JSON should be removed."""
    text = '<tool_call>{"name":"run_shell","arguments":{"cmd":"ls",}}</tool_call>'
    repaired = ToolCallValidator._repair_common_json_issues(text)
    calls = extract_tool_calls(repaired)
    assert len(calls) == 1
    assert calls[0]["name"] == "run_shell"


def test_validator_repair_json_balances_braces():
    """Missing closing braces in JSON should be added."""
    text = '<tool_call>{"name":"run_shell","arguments":{"cmd":"ls"</tool_call>'
    repaired = ToolCallValidator._repair_common_json_issues(text)
    calls = extract_tool_calls(repaired)
    assert len(calls) == 1
    assert calls[0]["name"] == "run_shell"


def test_validator_repair_json_closes_nested_object_and_array_in_stack_order():
    """Nested JSON recovery must close the innermost object before its array."""
    text = (
        '<tool_call>{"name":"fake_tool","arguments":'
        '{"items":[{"id":"fake"</tool_call>'
    )
    repaired = ToolCallValidator._repair_common_json_issues(text)

    assert repaired == (
        '<tool_call>{"name":"fake_tool","arguments":'
        '{"items":[{"id":"fake"}]}}</tool_call>'
    )
    calls = extract_tool_calls(repaired)
    assert calls == [
        {
            "name": "fake_tool",
            "args": {"items": [{"id": "fake"}]},
            "_source": "json",
        }
    ]
    is_valid, validated = ToolCallValidator.validate_and_repair(text)
    assert is_valid is True
    assert validated == repaired


def test_validator_repair_json_closes_mixed_nesting_in_stack_order():
    """Mixed arrays and objects must be closed in last-opened-first-closed order."""
    text = (
        '<tool_call>{"name":"fake_tool","arguments":'
        '{"filters":[{"tags":["alpha",{"key":"beta"</tool_call>'
    )
    repaired = ToolCallValidator._repair_common_json_issues(text)

    assert repaired == (
        '<tool_call>{"name":"fake_tool","arguments":'
        '{"filters":[{"tags":["alpha",{"key":"beta"}]}]}}</tool_call>'
    )
    calls = extract_tool_calls(repaired)
    assert calls[0]["args"] == {
        "filters": [{"tags": ["alpha", {"key": "beta"}]}]
    }


def test_validator_repair_preserves_closed_json_with_brackets_in_a_string():
    """Brackets inside JSON strings are content, not repairable structure."""
    text = (
        '<tool_call>{"name":"fake_tool","arguments":'
        '{"content":"literal [ { remains text"}}</tool_call>'
    )

    repaired = ToolCallValidator._repair_common_json_issues(text)

    assert repaired == text
    assert extract_tool_calls(repaired)[0]["args"] == {
        "content": "literal [ { remains text"
    }


def test_validator_repair_ignores_string_brackets_while_closing_outer_json():
    """Recovery must preserve string content while closing real nested structures."""
    text = (
        '<tool_call>{"name":"fake_tool","arguments":'
        '{"content":"literal [ {,}","items":[1</tool_call>'
    )

    repaired = ToolCallValidator._repair_common_json_issues(text)

    assert repaired == (
        '<tool_call>{"name":"fake_tool","arguments":'
        '{"content":"literal [ {,}","items":[1]}}</tool_call>'
    )
    assert extract_tool_calls(repaired)[0]["args"] == {
        "content": "literal [ {,}",
        "items": [1],
    }


def test_extract_tool_calls_returns_all_complete_wrapped_json_blocks():
    """Each complete wrapped JSON call should produce its own extracted call."""
    text = (
        '<tool_call>{"name":"fake_first","arguments":{"value":"one"}}</tool_call>'
        '<tool_call>{"name":"fake_second","arguments":'
        '{"content":"closed [ {,} ] </tool_call> string"}}</tool_call>'
    )

    calls = extract_tool_calls(text)

    assert calls == [
        {
            "name": "fake_first",
            "args": {"value": "one"},
            "_source": "json",
        },
        {
            "name": "fake_second",
            "args": {"content": "closed [ {,} ] </tool_call> string"},
            "_source": "json",
        },
    ]


def test_validator_repairs_a_malformed_wrapper_alongside_a_valid_wrapper():
    """Repairing one wrapper must retain calls extracted from the other wrapper."""
    valid = '<tool_call>{"name":"fake_first","arguments":{"value":"one"}}</tool_call>'
    repairable = (
        '<tool_call>{"name":"fake_second","arguments":'
        '{"items":[{"id":"second",}]</tool_call>'
    )

    is_valid, repaired = ToolCallValidator.validate_and_repair(valid + repairable)

    assert is_valid is True
    assert repaired == (
        valid
        + '<tool_call>{"name":"fake_second","arguments":'
        '{"items":[{"id":"second"}]}}</tool_call>'
    )
    assert extract_tool_calls(repaired) == [
        {
            "name": "fake_first",
            "args": {"value": "one"},
            "_source": "json",
        },
        {
            "name": "fake_second",
            "args": {"items": [{"id": "second"}]},
            "_source": "json",
        },
    ]


def test_extract_tool_calls_keeps_xml_priority_over_wrapped_json():
    """Legacy XML remains the selected path when both formats are present."""
    text = (
        '<call name="fake_xml"><path>fake.txt</path></call>'
        '<tool_call>{"name":"fake_json","arguments":{"value":"ignored"}}</tool_call>'
    )

    assert extract_tool_calls(text) == [
        {
            "name": "fake_xml",
            "args": {"path": "fake.txt"},
            "_source": "xml",
        }
    ]


def test_validator_validate_and_repair_preserves_multiple_closed_xml_calls():
    """The legacy XML compatibility path still handles multiple complete calls."""
    text = (
        '<call name="fake_first"><path>first.txt</path></call>'
        '<call name="fake_second"><path>second.txt</path></call>'
    )

    is_valid, repaired = ToolCallValidator.validate_and_repair(text)

    assert is_valid is True
    assert repaired == text
    assert [call["name"] for call in extract_tool_calls(repaired)] == [
        "fake_first",
        "fake_second",
    ]


def test_validator_validate_and_repair_preserves_simple_wrapped_json():
    """A complete wrapped JSON tool call remains unchanged."""
    text = '<tool_call>{"name":"fake_tool","arguments":{"value":"fake"}}</tool_call>'

    is_valid, repaired = ToolCallValidator.validate_and_repair(text)

    assert is_valid is True
    assert repaired == text


def test_validator_validate_and_repair_returns_valid_for_parsable():
    """validate_and_repair should return True for already-valid tool calls."""
    text = '<call name="run_shell"><command>ls</command></call>'
    is_valid, repaired = ToolCallValidator.validate_and_repair(text)
    assert is_valid is True
    assert repaired == text


def test_validator_validate_and_repair_fixes_unclosed_xml():
    """validate_and_repair should normalize an unclosed legacy XML call."""
    text = '<call name="run_shell"><command>ls</command>'
    is_valid, repaired = ToolCallValidator.validate_and_repair(text)

    assert is_valid is True
    assert repaired == text + "</call>"
    calls = extract_tool_calls(repaired)
    assert calls[0]["name"] == "run_shell"


def test_validator_validate_and_repair_fixes_json():
    """validate_and_repair should fix JSON issues and return valid."""
    text = '<tool_call>{"name":"run_shell","arguments":{"cmd":"ls",}}</tool_call>'
    is_valid, repaired = ToolCallValidator.validate_and_repair(text)
    assert is_valid is True
    calls = extract_tool_calls(repaired)
    assert len(calls) >= 1
    assert calls[0]["name"] == "run_shell"
