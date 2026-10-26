"""Recognise a reply that is a tool call written as text nothing parsed.

A model asked to call a tool through the provider's interface sometimes writes
the call into its reply instead, in a dialect of its own training: DeepSeek's
``DSML`` function-call tokens, Qwen's ``<function=name>``, a provider's
``<xyz_tool_call>`` tags, a bare JSON object.  The session's extractor parses
only the product's own text formats, so such a reply reaches the turn loop with
no tool call and used to be accepted as the turn's final answer: nothing ran,
and the markup was printed as the answer (a provider answering a
``tool_choice="none"`` request printed
``<iquestcoder_tool_call>list_dir<arg_key>path</arg_key>...`` as its reply).
``core/plan_recovery.py`` now treats such a reply like a plan-only one -- the
same bounded ladder, with a nudge saying the call was written as text.

This module only *recognises* a shape.  It parses no dialect and adds none to
the extractor: a call it recognises is never executed from the reply text.

It is deliberately conservative, because a false positive costs a recovery
round trip on an honest answer.  Prose, quoted examples and code samples must
never match:

* fenced code blocks and inline code spans are blanked before any search, so a
  format that is merely being *shown* is not a call;
* a tag pair, a ``<function=`` block or a JSON object counts only when it
  *ends* the reply (what follows is whitespace or a closing tag).  A model
  stops after emitting a call; an explanation of the format keeps talking;
* a tag pair, a ``<function=`` block or a JSON object counts only when it names
  a tool this request offered.  A call is useless without its tool, while an
  explanation shows placeholders (``tool_name``, ``get_weather``) -- including
  the product's own ``<tool_call>{"name":"tool_name",...}</tool_call>`` format
  quoted on a line of its own at the end of an answer.  JSON additionally needs
  to be the whole reply or a whole fenced block at the end of it.

A reply cut off mid-call (no closing tag) is not recognised: with no pair there
is no way to tell a truncated call from an unfinished sentence about one.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

# Sent with tool_choice="required": the provider is asked to refuse a reply that
# is not a tool call, so the text must not offer a final answer as an escape.
TOOL_MARKUP_RECOVERY_SIGNAL = (
    "[SYSTEM: TOOL_CALL_AS_TEXT]\n"
    "Your last reply wrote a tool call as plain text, so nothing was executed. "
    "The reply is saved in the conversation history.\n"
    "This reply must call a tool: make the call now through the current "
    "provider's tool interface. Do NOT write tool-call markup or JSON in the "
    "reply text."
)

# Sent with tool_choice="none": the last attempt asks for words, not a call.
TOOL_MARKUP_NO_TOOLS_SIGNAL = (
    "[SYSTEM: TOOL_CALL_AS_TEXT_NO_TOOLS]\n"
    "Two replies in a row wrote tool calls as plain text, so tools are switched "
    "off for this reply.\n"
    "Answer the user directly with what you already know, or ask them one "
    "clarifying question. Do NOT write a tool call, tool-call markup or JSON "
    "in the reply."
)

SHAPE_SPECIAL_TOKEN = "special_token"
SHAPE_TAG_PAIR = "tool_call_tag"
SHAPE_FUNCTION_BLOCK = "function_block"
SHAPE_JSON = "json_call"

# Tokens a model's chat template reserves for tool calls.  They appear in
# visible output only when the serving layer failed to parse the call, and
# prose almost never contains them.  U+FF5C is the fullwidth vertical line and
# U+2581 the lower-one-eighth block that DeepSeek's tokens are spelled with.
_SPECIAL_TOKEN_RE = re.compile(
    "|".join(
        (
            "</?\uff5cDSML\uff5c",  # DeepSeek V3.2 (DSML)
            "<\uff5ctool[\u2581_ ]calls?[\u2581_ ](?:begin|end)\uff5c>",  # DeepSeek V3 / R1
            "<\uff5ctool[\u2581_ ]sep\uff5c>",
            r"<\|tool_calls?_(?:section_)?(?:begin|end)\|>",  # Kimi K2
            r"<\|python_tag\|>",  # Llama 3.1
            r"\[TOOL_CALLS\]",  # Mistral
        )
    )
)

_OPEN_TAG_RE = re.compile(r"<([A-Za-z][\w:.-]*)>")
_TOOL_CALL_NAME_RE = re.compile(r"tool[_-]calls?$", re.IGNORECASE)
_FUNCTION_OPEN_RE = re.compile(r"^[ \t]*<function=[\w.:-]+>", re.MULTILINE)
_FUNCTION_CLOSE_RE = re.compile(r"</function\s*>")
_FENCE_OPEN_RE = re.compile(r"[ \t]{0,3}(`{3,}|~{3,})")
_INLINE_CODE_RE = re.compile(r"``[^\n]+?``|`[^`\n]+`")
_TAIL_RE = re.compile(r"(?:\s|</[\w:.-]+>)*")
_NOT_NEWLINE_RE = re.compile(r"[^\r\n]")


@dataclass(frozen=True)
class _Fence:
    """A fenced code block: ``text[start:end]`` including both fence lines."""

    start: int
    end: int
    body: str
    closed: bool


def _fences(text: str) -> list[_Fence]:
    """Return the fenced code blocks of ``text`` (an unclosed one runs to the end)."""
    fences: list[_Fence] = []
    opened: tuple[int, str, int] | None = None  # (start, marker, body_start)
    position = 0
    for line in text.splitlines(keepends=True):
        line_start = position
        position += len(line)
        if opened is None:
            match = _FENCE_OPEN_RE.match(line)
            if match is None:
                continue
            marker = match.group(1)
            if marker[0] == "`" and "`" in line[match.end():]:
                continue  # ```x``` on one line is an inline span, not a fence
            opened = (line_start, marker, position)
            continue
        start, marker, body_start = opened
        stripped = line.strip()
        if stripped and set(stripped) == {marker[0]} and len(stripped) >= len(marker):
            fences.append(_Fence(start, position, text[body_start:line_start], True))
            opened = None
    if opened is not None:
        start, _marker, body_start = opened
        fences.append(_Fence(start, len(text), text[body_start:], False))
    return fences


def _blank(chunk: str) -> str:
    """Replace everything but line breaks with spaces, keeping every offset."""
    return _NOT_NEWLINE_RE.sub(" ", chunk)


def _mask_code(text: str, fences: Iterable[_Fence]) -> str:
    """Return ``text`` with fenced blocks and inline code spans blanked out."""
    pieces: list[str] = []
    cursor = 0
    for fence in fences:
        pieces.append(text[cursor:fence.start])
        pieces.append(_blank(text[fence.start:fence.end]))
        cursor = fence.end
    pieces.append(text[cursor:])
    return _INLINE_CODE_RE.sub(lambda match: _blank(match.group()), "".join(pieces))


def _tail_is_clear(text: str, end: int) -> bool:
    """Return whether only whitespace or closing tags follow ``text[:end]``."""
    return _TAIL_RE.fullmatch(text, end) is not None


def _tool_call_pair_span(masked: str) -> tuple[int, int] | None:
    """Return the span of the pair ending last: ``<x_tool_call>...</x_tool_call>``.

    A wrapper around several calls (``<tool_calls>``) ends after the calls it
    holds, so the outermost pair is the one returned.
    """
    span: tuple[int, int] | None = None
    for opening in _OPEN_TAG_RE.finditer(masked):
        name = opening.group(1)
        if _TOOL_CALL_NAME_RE.search(name) is None:
            continue
        closing = re.compile(rf"</{re.escape(name)}\s*>", re.IGNORECASE).search(
            masked, opening.end()
        )
        if closing is not None and (span is None or closing.end() > span[1]):
            span = (opening.start(), closing.end())
    return span


def _function_block_span(masked: str) -> tuple[int, int] | None:
    """Return the span of a line-start ``<function=name>...</function>`` block."""
    opening = _FUNCTION_OPEN_RE.search(masked)
    if opening is None:
        return None
    end: int | None = None
    for closing in _FUNCTION_CLOSE_RE.finditer(masked, opening.end()):
        end = closing.end()
    return None if end is None else (opening.start(), end)


def _names_an_offered_tool(chunk: str, tool_names: Collection[str] | None) -> bool:
    """Return whether ``chunk`` names a tool the request offered (``None``: any)."""
    if tool_names is None:
        return True
    return any(
        re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", chunk) is not None
        for name in tool_names
    )


def _call_objects(value: Any) -> Iterator[Mapping[str, Any]]:
    """Yield the objects of a decoded JSON value that could be tool calls.

    Iterative: a reply of deeply nested (but valid) JSON must not exhaust the
    interpreter stack here after ``json`` itself accepted it.
    """
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, list):
            stack.extend(reversed(item))
        elif isinstance(item, dict):
            calls = item.get("tool_calls")
            if isinstance(calls, list):
                stack.extend(reversed(calls))
            else:
                yield item


def _has_arguments(obj: Mapping[str, Any]) -> bool:
    return "arguments" in obj or "parameters" in obj


def _call_name(obj: Mapping[str, Any]) -> str | None:
    """Return the tool name a call-shaped JSON object names, or ``None``.

    Accepted shapes: ``{"name": n, "arguments": ...}``,
    ``{"function": {"name": n, "arguments": ...}}`` (OpenAI) and
    ``{"function": n, "arguments": ...}``.  ``parameters`` is accepted for
    ``arguments`` (Llama).
    """
    function = obj.get("function")
    if isinstance(function, Mapping):
        name = function.get("name")
        return name if isinstance(name, str) and _has_arguments(function) else None
    if isinstance(function, str) and _has_arguments(obj):
        return function
    name = obj.get("name")
    return name if isinstance(name, str) and _has_arguments(obj) else None


def _is_tool_call_json(candidate: str, tool_names: Collection[str] | None) -> bool:
    try:
        value = json.loads(candidate.strip(), strict=False)
    except (ValueError, RecursionError):  # deep nesting raises RecursionError, not ValueError
        return False
    for call in _call_objects(value):
        name = _call_name(call)
        if name is not None and (tool_names is None or name in tool_names):
            return True
    return False


def _strip_plan_blocks(text: str) -> str:
    """Remove complete ``<plan>...</plan>`` blocks in one linear pass.

    ``find`` rather than a lazy regex: a reply that repeats ``<plan>`` without
    ever closing it would cost the regex a scan to the end per occurrence.
    """
    pieces: list[str] = []
    cursor = 0
    while True:
        start = text.find("<plan>", cursor)
        end = text.find("</plan>", start + 6) if start >= 0 else -1
        if end < 0:
            break
        pieces.append(text[cursor:start])
        cursor = end + len("</plan>")
    pieces.append(text[cursor:])
    return "".join(pieces)


def _ends_with_json_call(text: str, tool_names: Collection[str] | None) -> bool:
    """Return whether the reply is, or ends with a fenced block that is, a call."""
    body = _strip_plan_blocks(text).strip()
    if not body:
        return False
    if body[0] in "{[" and _is_tool_call_json(body, tool_names):
        return True
    fences = _fences(body)
    if not fences:
        return False
    last = fences[-1]
    return last.closed and last.end >= len(body) and _is_tool_call_json(last.body, tool_names)


def find_unparsed_tool_call(
    text: str,
    tool_names: Collection[str] | None = None,
) -> str | None:
    """Return the shape of the tool-call markup ``text`` ends with, else ``None``.

    ``tool_names`` is the set of tools the request offered.  It gates every
    shape except the reserved special tokens: an example that names a tool the
    agent does not have (or none) is an example, not a call.  ``None`` accepts
    any name.
    """
    if not text or not text.strip():
        return None
    fences = _fences(text)
    masked = _mask_code(text, fences)
    if _SPECIAL_TOKEN_RE.search(masked) is not None:
        return SHAPE_SPECIAL_TOKEN
    for span, shape in (
        (_tool_call_pair_span(masked), SHAPE_TAG_PAIR),
        (_function_block_span(masked), SHAPE_FUNCTION_BLOCK),
    ):
        if (
            span is not None
            and _tail_is_clear(text, span[1])
            and _names_an_offered_tool(masked[span[0]:span[1]], tool_names)
        ):
            return shape
    if _ends_with_json_call(text, tool_names):
        return SHAPE_JSON
    return None


def offered_tool_names(tools: Iterable[Mapping[str, Any]] | None) -> frozenset[str]:
    """Return the names in an OpenAI-shaped tool schema list."""
    names: set[str] = set()
    for tool in tools or ():
        function = tool.get("function") if isinstance(tool, Mapping) else None
        name = function.get("name") if isinstance(function, Mapping) else None
        if isinstance(name, str):
            names.add(name)
    return frozenset(names)


__all__ = [
    "SHAPE_FUNCTION_BLOCK",
    "SHAPE_JSON",
    "SHAPE_SPECIAL_TOKEN",
    "SHAPE_TAG_PAIR",
    "TOOL_MARKUP_NO_TOOLS_SIGNAL",
    "TOOL_MARKUP_RECOVERY_SIGNAL",
    "find_unparsed_tool_call",
    "offered_tool_names",
]
