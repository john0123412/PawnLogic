"""Hybrid XML/JSON tool call parsing helpers."""

from __future__ import annotations

from collections.abc import Callable
import json
from json import JSONDecodeError
import re
from typing import Any


class ToolCallValidator:
    """Validate and repair tool calls from model output to prevent parsing failures."""

    @classmethod
    def validate_and_repair(cls, text: str) -> tuple[bool, str]:
        """
        Validate tool calls in text and attempt to repair common issues.

        Returns:
            Tuple of (is_valid, repaired_text)
            If is_valid is True, text contains parsable tool calls
            If is_valid is False, repaired_text contains best-effort repairs
        """
        # First, try to parse as-is
        from core.tool_calls import extract_tool_calls
        original_calls = extract_tool_calls(text)

        # A later wrapper may still need repair even when earlier calls parsed.
        needs_repair = cls._needs_repair(text, original_calls)

        if original_calls and not needs_repair:
            return True, text

        # Attempt repair strategies
        repaired = cls._attempt_repair(text)
        if repaired != text:
            repaired_calls = extract_tool_calls(repaired)
            if repaired_calls:
                return True, repaired

        # Keep any calls that were already extractable when another block could not be repaired.
        return bool(original_calls), text

    @classmethod
    def _needs_repair(cls, text: str, calls: list[dict]) -> bool:
        """Return whether legacy XML or wrapped JSON needs normalization."""
        if any(call.get("_source") == "xml" for call in calls):
            open_calls = re.findall(r'<call\s+name="[^"]*"[^>]*>', text)
            close_calls = re.findall(r'</call>', text)
            return len(open_calls) > len(close_calls)

        return any(
            not cls._is_valid_json(text[start:end].strip())
            for start, end in _find_complete_tool_call_json_blocks(text)
        )

    @classmethod
    def _attempt_repair(cls, text: str) -> str:
        """Attempt various repair strategies on malformed tool call text."""
        repaired = text

        # Strategy 1: Fix unclosed XML tags
        repaired = cls._repair_unclosed_xml_tags(repaired)

        # Strategy 2: Fix common JSON issues
        repaired = cls._repair_common_json_issues(repaired)

        return repaired

    @classmethod
    def _repair_unclosed_xml_tags(cls, text: str) -> str:
        """Attempt to close unclosed <call> tags.

        Since <call> tags are flat (non-nesting), we simply find any <call> that
        lacks a closing </call> after it, and append </call> at the very end of the
        string so that the hybrid parser can extract it.
        """
        import re as _re

        result = text
        # Find all opening <call> tags
        open_pattern = r'<call\s+name="[^"]*"[^>]*>'
        opens = list(_re.finditer(open_pattern, result))

        if not opens:
            return result

        # Find all <call> tags and track their positions
        # We need to add </call> after each <call> that doesn't have one
        # but before the next <call> starts
        parts = []
        last_end = 0

        for i, match in enumerate(opens):
            # Add text before this opening tag
            parts.append(result[last_end:match.start()])
            # Add the opening tag
            parts.append(match.group(0))
            match_end = match.end()

            # Look for the next opening tag or end of string
            next_open = opens[i + 1].start() if i + 1 < len(opens) else len(result)

            # Check if there's a closing tag between this opening and the next opening
            search_area = result[match_end:next_open]
            if '</call>' not in search_area:
                # No closing tag found, add one at the end of this call's content
                parts.append(search_area)
                parts.append('</call>')
                last_end = next_open
            else:
                # There is a closing tag, find it
                close_pos = result.find('</call>', match_end)
                if close_pos != -1 and close_pos < next_open:
                    # Found closing tag within bounds
                    parts.append(result[match_end:close_pos + len('</call>')])
                    last_end = close_pos + len('</call>')
                else:
                    # No closing tag before next opening, add one
                    parts.append(result[match_end:next_open])
                    parts.append('</call>')
                    last_end = next_open

        # Add any remaining text after the last <call>
        if last_end < len(result):
            remaining = result[last_end:]
            # Check if remaining text has unclosed <call>
            if '<call' in remaining and '</call>' not in remaining:
                parts.append(remaining)
                parts.append('</call>')
            else:
                parts.append(remaining)

        return ''.join(parts)
    @classmethod
    def _repair_common_json_issues(cls, text: str) -> str:
        """Attempt to fix common JSON formatting issues inside <tool_call> blocks."""
        blocks = _find_complete_tool_call_json_blocks(text)
        if not blocks:
            return text

        parts: list[str] = []
        cursor = 0
        changed = False
        for start, end in blocks:
            json_str = text[start:end]
            fixed = cls._attempt_fix_json(json_str)
            if fixed == json_str:
                continue
            parts.append(text[cursor:start])
            parts.append(fixed)
            cursor = end
            changed = True

        if not changed:
            return text
        parts.append(text[cursor:])
        return "".join(parts)

    @classmethod
    def _attempt_fix_json(cls, json_str: str) -> str:
        """Attempt to fix a JSON string with common issues."""
        if cls._is_valid_json(json_str):
            return json_str

        repaired = cls._remove_trailing_json_commas(json_str)
        repaired = cls._quote_unquoted_json_keys(repaired)
        completed = cls._close_unclosed_json_structures(repaired)
        if completed is None or not cls._is_valid_json(completed):
            return json_str
        return completed

    @staticmethod
    def _is_valid_json(json_str: str) -> bool:
        """Return whether a JSON fragment is already parseable."""
        try:
            json.loads(json_str, strict=False)
        except JSONDecodeError:
            return False
        return True

    @staticmethod
    def _remove_trailing_json_commas(json_str: str) -> str:
        """Remove commas before a closing token or end-of-input, outside strings."""
        result: list[str] = []
        in_string = False
        escaped = False
        index = 0

        while index < len(json_str):
            char = json_str[index]
            if in_string:
                result.append(char)
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                index += 1
                continue

            if char == '"':
                in_string = True
                result.append(char)
                index += 1
                continue

            if char == ",":
                next_index = index + 1
                while next_index < len(json_str) and json_str[next_index].isspace():
                    next_index += 1
                if next_index == len(json_str) or json_str[next_index] in "}]":
                    index += 1
                    continue

            result.append(char)
            index += 1

        return "".join(result)

    @staticmethod
    def _quote_unquoted_json_keys(json_str: str) -> str:
        """Quote simple object keys while leaving quoted string content untouched."""
        result: list[str] = []
        in_string = False
        escaped = False
        index = 0

        while index < len(json_str):
            char = json_str[index]
            if in_string:
                result.append(char)
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                index += 1
                continue

            if char == '"':
                in_string = True
                result.append(char)
                index += 1
                continue

            if char in "{,":
                match = re.match(r"([,{])(\s*)(\w+)(\s*:)", json_str[index:])
                if match is not None:
                    result.append(
                        f'{match.group(1)}{match.group(2)}"{match.group(3)}"{match.group(4)}'
                    )
                    index += len(match.group(0))
                    continue

            result.append(char)
            index += 1

        return "".join(result)

    @staticmethod
    def _close_unclosed_json_structures(json_str: str) -> str | None:
        """Append missing JSON closers in LIFO order, ignoring quoted content."""
        closing_stack: list[str] = []
        in_string = False
        escaped = False

        for char in json_str:
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                closing_stack.append("}")
            elif char == "[":
                closing_stack.append("]")
            elif char in "}]":
                if not closing_stack or closing_stack[-1] != char:
                    return None
                closing_stack.pop()

        if in_string:
            return None
        return json_str + "".join(reversed(closing_stack))


_XML_FULL_RE = re.compile(
    r'<call\s+name="(?P<name>[^"]+)">(?P<args_block>.*?)</call>',
    re.DOTALL,
)
_XML_PARTIAL_RE = re.compile(
    r'<call\s+name="(?P<name>[^"]+)">(?P<args_block>.*)',
    re.DOTALL,
)
_XML_PARAM_RE = re.compile(
    r'<(?P<key>[a-zA-Z_][a-zA-Z0-9_]*)>(?P<val>.*?)</(?P=key)>',
    re.DOTALL,
)
_TOOL_CALL_JSON_RE = re.compile(r"<tool_call>\s*(\{.*)", re.DOTALL)
_TOOL_CALL_CLOSE_RE = re.compile(r"</tool_call>.*$", re.DOTALL)
_TOOL_CALL_OPEN_TAG = "<tool_call>"
_TOOL_CALL_CLOSE_TAG = "</tool_call>"
_CONTENT_FIELD_RE = re.compile(r'"content"\s*:\s*"(.*)"\s*\}', re.DOTALL)
_UNESCAPED_QUOTE_RE = re.compile(r'(?<!\\)"')


def _find_complete_tool_call_json_blocks(text_buf: str) -> list[tuple[int, int]]:
    """Find complete wrapper bodies without treating string content as a closing tag."""
    blocks: list[tuple[int, int]] = []
    search_start = 0

    while True:
        open_start = text_buf.find(_TOOL_CALL_OPEN_TAG, search_start)
        if open_start == -1:
            break

        content_start = open_start + len(_TOOL_CALL_OPEN_TAG)
        index = content_start
        in_string = False
        escaped = False
        close_start = -1

        while index < len(text_buf):
            char = text_buf[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif text_buf.startswith(_TOOL_CALL_CLOSE_TAG, index):
                close_start = index
                break
            index += 1

        if close_start == -1:
            # Preserve dirty-JSON recovery when broken quotes hide the closing tag.
            close_start = text_buf.find(_TOOL_CALL_CLOSE_TAG, content_start)
        if close_start == -1:
            break

        blocks.append((content_start, close_start))
        search_start = close_start + len(_TOOL_CALL_CLOSE_TAG)

    return blocks


def _coerce_xml_value(val_raw: str) -> object:
    if val_raw.lstrip("-").isdigit():
        return int(val_raw)
    if val_raw.lower() == "true":
        return True
    if val_raw.lower() == "false":
        return False
    return val_raw


def _parse_xml_args(args_block: str) -> dict:
    args: dict[str, object] = {}
    for pm in _XML_PARAM_RE.finditer(args_block):
        key = pm.group("key").strip()
        val_raw = pm.group("val").strip()
        args[key] = _coerce_xml_value(val_raw)
    return args


def _call_from_json(parsed_tc: Any, source: str) -> dict | None:
    if not isinstance(parsed_tc, dict):
        return None
    if "name" not in parsed_tc or "arguments" not in parsed_tc:
        return None

    raw_args = parsed_tc["arguments"]
    args_dict = raw_args if isinstance(raw_args, dict) else {"_raw_args": str(raw_args)}
    return {
        "name": parsed_tc["name"],
        "args": args_dict,
        "_source": source,
    }


def _try_dirty_json_rescue(json_str: str) -> dict | None:
    content_match = _CONTENT_FIELD_RE.search(json_str)
    if not content_match:
        return None

    bad_content = content_match.group(1)
    fixed_content = _UNESCAPED_QUOTE_RE.sub(r'\"', bad_content)
    fixed_j_str = json_str.replace(bad_content, fixed_content)

    parsed_tc = json.loads(fixed_j_str, strict=False)
    return _call_from_json(parsed_tc, "json_rescued")


def extract_tool_calls(
    text_buf: str,
    *,
    on_partial_xml: Callable[[], None] | None = None,
    on_dirty_json_rescued: Callable[[], None] | None = None,
    on_json_error: Callable[[JSONDecodeError, str], None] | None = None,
) -> list[dict]:
    """
    Extract hybrid XML/JSON tool calls from model text.

    Priority:
      1. XML <call name="...">...</call>
      2. JSON <tool_call>{...}</tool_call>
    """
    results: list[dict] = []

    xml_matches = list(_XML_FULL_RE.finditer(text_buf))
    used_partial = False
    if not xml_matches:
        xml_matches = list(_XML_PARTIAL_RE.finditer(text_buf))
        used_partial = bool(xml_matches)

    if xml_matches:
        for match in xml_matches:
            name = match.group("name").strip()
            args_block = match.group("args_block")
            if used_partial and on_partial_xml is not None:
                on_partial_xml()

            args = _parse_xml_args(args_block)
            if name and args:
                results.append({"name": name, "args": args, "_source": "xml"})

        if results:
            return results

    if "<tool_call>" not in text_buf:
        return results

    json_spans = _find_complete_tool_call_json_blocks(text_buf)
    if json_spans:
        json_blocks = [text_buf[start:end].strip() for start, end in json_spans]
    else:
        json_match = _TOOL_CALL_JSON_RE.search(text_buf)
        if not json_match:
            return results
        json_blocks = [_TOOL_CALL_CLOSE_RE.sub("", json_match.group(1)).strip()]

    for json_str in json_blocks:
        try:
            parsed_tc = json.loads(json_str, strict=False)
            parsed_call = _call_from_json(parsed_tc, "json")
            if parsed_call is not None:
                results.append(parsed_call)
        except JSONDecodeError as exc:
            rescued_call = None
            try:
                rescued_call = _try_dirty_json_rescue(json_str)
            except Exception:
                rescued_call = None

            if rescued_call is None:
                if on_json_error is not None:
                    on_json_error(exc, json_str)
            else:
                results.append(rescued_call)
                if on_dirty_json_rescued is not None:
                    on_dirty_json_rescued()

    return results
