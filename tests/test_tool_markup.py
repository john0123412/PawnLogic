"""Recognising a tool call that was written as text and never parsed.

The incident class: a reply whose text *is* a tool call in a dialect the
extractor does not know reached the turn loop with no tool call, was accepted
as the final answer, and was printed to the user as such.  These tests pin the
two halves of the detector -- it must see those replies, and it must stay quiet
for anything that merely talks about them -- and the nudges that follow.
"""

from __future__ import annotations

import pytest

from core.synthetic_messages import is_synthetic_user_message
from core.tool_markup import (
    SHAPE_FUNCTION_BLOCK,
    SHAPE_JSON,
    SHAPE_SPECIAL_TOKEN,
    SHAPE_TAG_PAIR,
    TOOL_MARKUP_NO_TOOLS_SIGNAL,
    TOOL_MARKUP_RECOVERY_SIGNAL,
    find_unparsed_tool_call,
    offered_tool_names,
)

TOOLS = frozenset({"list_dir", "read_file", "run_shell"})
PLAN = "<plan>\n  <intent>List cwd.</intent>\n  <tool>list_dir</tool>\n</plan>"

BAR = "\uff5c"  # fullwidth vertical line used by DeepSeek's special tokens
LOWER_BLOCK = "\u2581"

DSML = (
    f"<{BAR}DSML{BAR}function_calls><{BAR}DSML{BAR}invoke name=\"list_dir\">"
    f"<{BAR}DSML{BAR}parameter name=\"path\">.</{BAR}DSML{BAR}parameter>"
    f"</{BAR}DSML{BAR}invoke></{BAR}DSML{BAR}function_calls>"
)
DEEPSEEK_V3 = (
    f"<{BAR}tool{LOWER_BLOCK}calls{LOWER_BLOCK}begin{BAR}><{BAR}tool{LOWER_BLOCK}call{LOWER_BLOCK}begin{BAR}>"
    f"function<{BAR}tool{LOWER_BLOCK}sep{BAR}>list_dir\n```json\n{{\"path\": \".\"}}\n```"
    f"<{BAR}tool{LOWER_BLOCK}call{LOWER_BLOCK}end{BAR}><{BAR}tool{LOWER_BLOCK}calls{LOWER_BLOCK}end{BAR}>"
)
KIMI = (
    "<|tool_calls_section_begin|><|tool_call_begin|>functions.list_dir:0"
    "<|tool_call_argument_begin|>{\"path\": \".\"}<|tool_call_end|><|tool_calls_section_end|>"
)
IQUEST = (
    "<iquestcoder_tool_call>list_dir<arg_key>path</arg_key><arg_value>.</arg_value>"
    "</iquestcoder_tool_call>"
)
QWEN_FUNCTION = "<function=list_dir>\n<parameter=path>\n.\n</parameter>\n</function>"
BARE_JSON = '{"name":"list_dir","arguments":{"path":"."}}'


@pytest.mark.parametrize(
    ("label", "text", "shape"),
    [
        ("DeepSeek DSML", DSML, SHAPE_SPECIAL_TOKEN),
        ("DeepSeek V3 tokens", DEEPSEEK_V3, SHAPE_SPECIAL_TOKEN),
        ("Kimi K2 tokens", KIMI, SHAPE_SPECIAL_TOKEN),
        ("Mistral token", '[TOOL_CALLS][{"name": "list_dir", "arguments": {}}]', SHAPE_SPECIAL_TOKEN),
        ("Llama python_tag", '<|python_tag|>{"name": "list_dir", "parameters": {}}', SHAPE_SPECIAL_TOKEN),
        ("provider tool_call tags", IQUEST, SHAPE_TAG_PAIR),
        ("tool_calls wrapper", "<tool_calls>list_dir .</tool_calls>", SHAPE_TAG_PAIR),
        (
            "tool_call tags the extractor could not read",
            '<tool_call>{"tool":"list_dir","args":{"path":"."}}</tool_call>',
            SHAPE_TAG_PAIR,
        ),
        ("Qwen function block", QWEN_FUNCTION, SHAPE_FUNCTION_BLOCK),
        (
            "Qwen function block inside tool_call tags",
            "<tool_call>\n" + QWEN_FUNCTION + "\n</tool_call>",
            SHAPE_TAG_PAIR,
        ),
        ("bare JSON", BARE_JSON, SHAPE_JSON),
        ("bare JSON with parameters", '{"name":"list_dir","parameters":{"path":"."}}', SHAPE_JSON),
        (
            "OpenAI tool_calls envelope",
            '{"tool_calls":[{"id":"c1","type":"function",'
            '"function":{"name":"list_dir","arguments":"{\\"path\\": \\".\\"}"}}]}',
            SHAPE_JSON,
        ),
        ("function object", '{"function":{"name":"read_file","arguments":{"path":"a"}}}', SHAPE_JSON),
        ("function name key", '{"function":"read_file","arguments":{"path":"a"}}', SHAPE_JSON),
        ("list of calls", f"[{BARE_JSON},{BARE_JSON}]", SHAPE_JSON),
        ("fenced JSON as the whole reply", f"```json\n{BARE_JSON}\n```", SHAPE_JSON),
        ("fenced tool_calls", '```json\n{"tool_calls":[{"name":"list_dir","arguments":{}}]}\n```', SHAPE_JSON),
        ("fenced JSON ending a short preface", f"I will list the directory.\n```json\n{BARE_JSON}\n```\n", SHAPE_JSON),
    ],
)
def test_a_reply_that_is_an_unparsed_tool_call_is_recognised(label, text, shape):
    assert find_unparsed_tool_call(text, TOOLS) == shape, label


@pytest.mark.parametrize("call", [DSML, IQUEST, QWEN_FUNCTION, KIMI])
def test_a_preface_and_a_plan_before_the_call_do_not_hide_it(call):
    assert find_unparsed_tool_call(f"Let me look at the project.\n{call}\n", TOOLS) is not None
    assert find_unparsed_tool_call(f"{PLAN}\n{call}", TOOLS) is not None
    assert find_unparsed_tool_call(f"{PLAN}\nLet me look at the project.\n{call}", TOOLS) is not None


def test_a_plan_before_bare_json_leaves_the_json_as_the_whole_reply():
    # Plan blocks are protocol, not content: with the plan removed the JSON is
    # the whole reply, which is the case the audit reproduced.
    assert find_unparsed_tool_call(f"{PLAN}\n{BARE_JSON}", TOOLS) == SHAPE_JSON
    assert find_unparsed_tool_call(f"{PLAN}\n```json\n{BARE_JSON}\n```", TOOLS) == SHAPE_JSON


def test_unfenced_json_after_prose_is_deliberately_not_matched():
    # Conservative by design: JSON counts as the whole reply or as a whole
    # fenced block, never as the tail of a sentence.
    assert find_unparsed_tool_call(f"Let me look at the project.\n{BARE_JSON}\n", TOOLS) is None


def test_several_calls_in_a_row_are_one_unparsed_reply():
    assert find_unparsed_tool_call(IQUEST + "\n" + IQUEST, TOOLS) == SHAPE_TAG_PAIR
    nested = "<tool_calls>\n<tool_call>list_dir .</tool_call>\n<tool_call>list_dir ..</tool_call>\n</tool_calls>"
    assert find_unparsed_tool_call(nested, TOOLS) == SHAPE_TAG_PAIR


def test_tag_names_match_case_insensitively_and_with_a_hyphen():
    assert find_unparsed_tool_call("<Tool_Call>list_dir</Tool_Call>", TOOLS) == SHAPE_TAG_PAIR
    assert find_unparsed_tool_call("<my-tool-call>list_dir .</my-tool-call>", TOOLS) == SHAPE_TAG_PAIR


# ── what must NOT match ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("label", "text"),
    [
        ("empty", ""),
        ("whitespace", "  \n\t"),
        ("plain answer", "The project is a terminal agent. It keeps memory in SQLite."),
        ("the word in a sentence", "A tool_call is how the model asks the host to run a function."),
        ("the words tool_calls and function in prose", "The tool_calls field holds a function name and its arguments."),
        (
            "prose that quotes the tag pair and keeps going",
            "Models such as Hermes wrap a call in <tool_call>{...}</tool_call> tags, "
            "and the host parses the JSON inside.",
        ),
        (
            "inline code",
            "The extractor looks for `<tool_call>{\"name\": ...}</tool_call>` and for `<call name=\"x\">`.",
        ),
        (
            "inline code with the pair at the very end",
            "The wrapper is `<tool_call>x</tool_call>`",
        ),
        (
            "an answer explaining XML formats with a fenced sample first",
            "Qwen3 emits this:\n```xml\n<tool_call>\n<function=get_weather>\n</function>\n</tool_call>\n```\n"
            "Hermes uses JSON inside the same tags, which the host parses.",
        ),
        (
            "a fenced XML sample that ends the answer",
            "Here is the format:\n```xml\n<tool_call>\n<function=list_dir>\n</function>\n</tool_call>\n```",
        ),
        (
            "a fenced special-token sample",
            "DeepSeek's template looks like this:\n```\n" + DSML + "\n```\nIt is rendered by the server.",
        ),
        (
            "special tokens quoted in inline code",
            f"The server may print `<{BAR}DSML{BAR}function_calls>` when parsing fails.",
        ),
        (
            "a code sample in a fence",
            "```python\nfor name in tools:\n    # <function=name> is an XML tool call\n    print(name)\n```\nDone.",
        ),
        (
            "a fenced JSON sample followed by an explanation",
            f"The payload looks like this:\n```json\n{BARE_JSON}\n```\nThe host reads name and arguments.",
        ),
        (
            "the product's own format quoted on its own line at the end of an answer",
            'The text fallback format is:\n<tool_call>{"name":"tool_name","arguments":{"key":"value"}}</tool_call>',
        ),
        ("a function block example with placeholders", "Qwen3:\n<function=function_name>\n</function>"),
        (
            "a JSON example for a tool the agent does not have",
            '{"name":"get_weather","arguments":{"city":"Oslo"}}',
        ),
        ("JSON that is not call-shaped", '{"name":"Alice","age":3}'),
        ("a name without arguments", '{"name":"list_dir"}'),
        ("a package manifest ending the answer", 'Config:\n```json\n{"name": "pkg", "version": "1.0"}\n```'),
        ("JSON that is a list of strings", '["list_dir", "read_file"]'),
        ("function= in the middle of a sentence", "Qwen writes <function=name> before the parameters."),
        ("a function block that is never closed", "<function=list_dir>\n<parameter=path>\n.\n"),
        ("a tool_call tag that is never closed", '<tool_call>{"name":"list_dir","arguments":{"path":"/ho'),
        ("an unterminated fence swallowing the markup", "Example:\n```xml\n" + IQUEST),
        ("the plan's own <tool> tag", PLAN),
        ("a plan and a normal answer", PLAN + "\nThe directory holds three files."),
        ("tag names that merely contain tool", "<toolbox>list_dir</toolbox> and <tools>x</tools>"),
    ],
)
def test_prose_examples_and_code_never_look_like_a_tool_call(label, text):
    assert find_unparsed_tool_call(text, TOOLS) is None, label


def test_a_reply_that_keeps_talking_after_the_markup_is_an_explanation():
    for call in (IQUEST, QWEN_FUNCTION, BARE_JSON):
        assert find_unparsed_tool_call(f"{call}\nThat is how the call is written.", TOOLS) is None


def test_chinese_prose_about_the_format_does_not_match():
    # "A tool call is JSON with name and arguments" -- written as escapes: the
    # repository keeps non-English text out of source files.
    prose = "\u5de5\u5177\u8c03\u7528\u662f\u5e26 name \u548c arguments \u7684 JSON\u3002"

    assert find_unparsed_tool_call(prose, TOOLS) is None
    assert find_unparsed_tool_call(prose + "\n" + IQUEST, TOOLS) == SHAPE_TAG_PAIR


def test_json_is_gated_by_the_tools_the_request_offered():
    assert find_unparsed_tool_call(BARE_JSON, frozenset({"read_file"})) is None
    assert find_unparsed_tool_call(BARE_JSON, frozenset()) is None
    assert find_unparsed_tool_call(BARE_JSON, None) == SHAPE_JSON  # None accepts any name


def test_tag_pairs_and_function_blocks_need_an_offered_tool_name_too():
    """A call is useless without its tool; an explanation shows placeholders."""
    placeholder_pair = '<tool_call>{"name":"tool_name","arguments":{"key":"value"}}</tool_call>'
    placeholder_block = "<function=function_name>\n<parameter=key>\nvalue\n</parameter>\n</function>"

    assert find_unparsed_tool_call(placeholder_pair, TOOLS) is None
    assert find_unparsed_tool_call(placeholder_block, TOOLS) is None
    assert find_unparsed_tool_call(IQUEST, frozenset({"read_file"})) is None
    assert find_unparsed_tool_call(IQUEST, frozenset()) is None
    assert find_unparsed_tool_call(IQUEST, TOOLS) == SHAPE_TAG_PAIR
    assert find_unparsed_tool_call(QWEN_FUNCTION, frozenset({"list_dir"})) == SHAPE_FUNCTION_BLOCK
    # No gate when the caller gives no names (the pure-shape view).
    assert find_unparsed_tool_call(placeholder_pair, None) == SHAPE_TAG_PAIR
    # Whole words only: "list_directory" is not the offered "list_dir".
    assert find_unparsed_tool_call("<tool_call>list_directory .</tool_call>", TOOLS) is None


def test_the_names_must_sit_inside_the_markup_not_in_the_prose_around_it():
    text = 'I will use list_dir to look.\n<tool_call>{"name":"tool_name"}</tool_call>'

    assert find_unparsed_tool_call(text, TOOLS) is None


def test_reserved_special_tokens_need_no_tool_name():
    # They never occur in prose, and a half-rendered template names nothing.
    assert find_unparsed_tool_call(DSML, frozenset()) == SHAPE_SPECIAL_TOKEN
    assert find_unparsed_tool_call(KIMI, frozenset({"read_file"})) == SHAPE_SPECIAL_TOKEN


def test_a_quoted_example_that_uses_a_real_tool_name_is_a_known_limit():
    # Indistinguishable from a call without a model: documented, not hidden.
    quoted = 'The format is:\n<tool_call>{"name":"list_dir","arguments":{"path":"."}}</tool_call>'

    assert find_unparsed_tool_call(quoted, TOOLS) == SHAPE_TAG_PAIR


def test_offered_tool_names_reads_openai_shaped_schemas():
    schemas = [
        {"type": "function", "function": {"name": "list_dir", "parameters": {}}},
        {"type": "function", "function": {"name": "read_file"}},
        {"type": "function", "function": {}},
        {"type": "function"},
        "not a schema",
    ]

    assert offered_tool_names(schemas) == frozenset({"list_dir", "read_file"})
    assert offered_tool_names(None) == frozenset()
    assert offered_tool_names([]) == frozenset()


# ── the nudges ───────────────────────────────────────────────────────


def test_the_nudges_are_framework_messages_and_say_what_the_reply_must_do():
    for signal in (TOOL_MARKUP_RECOVERY_SIGNAL, TOOL_MARKUP_NO_TOOLS_SIGNAL):
        assert is_synthetic_user_message({"role": "user", "content": signal})
        assert "plain text" in signal

    assert "must call a tool" in TOOL_MARKUP_RECOVERY_SIGNAL
    assert "provider's tool interface" in TOOL_MARKUP_RECOVERY_SIGNAL
    # The required step must not offer the escape the provider is closing off.
    assert "final answer" not in TOOL_MARKUP_RECOVERY_SIGNAL
    assert "tools are switched off" in TOOL_MARKUP_NO_TOOLS_SIGNAL
    assert "clarifying question" in TOOL_MARKUP_NO_TOOLS_SIGNAL


# ── bounded cost on hostile or degenerate replies ────────────────────


DEGENERATE_REPLIES = {
    "backtick run": "`" * 200_000,
    "double backtick run": "``" * 100_000,
    "empty fences": "```\n" * 50_000,
    "unclosed tool_call tags": "<a_tool_call>" * 5_000,
    "unclosed plans": "<plan>" * 20_000,
    "closed plans": "<plan></plan>" * 5_000,
    "open braces": "{" * 100_000,
    "open brackets": "[" * 100_000,
    "nested objects": '{"a":' * 100_000,
    "deep but valid json": "[" * 900 + "]" * 900,
    "deep valid json around a call": "[" * 400 + BARE_JSON.replace("list_dir", "other") + "]" * 400,
    "long lines then an open tag": ("x" * 80 + "\n") * 5_000 + "<tool_call>",
}


@pytest.mark.timeout(10)
@pytest.mark.parametrize("label", sorted(DEGENERATE_REPLIES))
def test_degenerate_replies_are_scanned_in_bounded_time_and_never_raise(label):
    # A model stuck in a repetition loop can emit megabytes of one token, and the
    # recogniser runs on every reply that carries no tool call.  It must stay
    # linear-ish on all of them, and deeply nested JSON must not escape as a
    # RecursionError (json raises that, not ValueError) and kill the turn.
    assert find_unparsed_tool_call(DEGENERATE_REPLIES[label], TOOLS) is None


def test_a_plan_with_nested_json_after_it_is_still_judged():
    deep = "[" * 100_000
    assert find_unparsed_tool_call(PLAN + "\n" + deep, TOOLS) is None
    assert find_unparsed_tool_call(PLAN + "\n" + BARE_JSON, TOOLS) == SHAPE_JSON
