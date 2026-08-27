"""Hybrid XML/JSON tool call parsing helpers."""

from __future__ import annotations

from collections.abc import Callable
import json
from json import JSONDecodeError
import re
from typing import Any, Dict, List, Optional, Tuple


class ToolCallValidator:
    """Validate and repair tool calls from model output to prevent parsing failures."""

    # Common tool names that are likely to appear in malformed output
    COMMON_TOOLS = {
        'run_shell', 'read_file', 'write_file', 'list_dir', 'find_files',
        'search_skills', 'web_search', 'web_fetch', 'git_op', 'run_code',
        'read_file_lines', 'pwn_env', 'inspect_binary', 'pwn_rop', 'pwn_cyclic',
        'pwn_disasm', 'pwn_libc', 'pwn_debug', 'pwn_one_gadget', 'pwn_timed_debug',
        'analyze_local_image', 'tool_web_fetch', 'tool_web_click', 'tool_web_screenshot',
        'tool_web_select', 'tool_web_type', 'tool_web_navigate', 'check_service'
    }

    @classmethod
    def validate_and_repair(cls, text: str) -> Tuple[bool, str]:
        """
        Validate tool calls in text and attempt to repair common issues.

        Returns:
            Tuple of (is_valid, repaired_text)
            If is_valid is True, text contains parsable tool calls
            If is_valid is False, repaired_text contains best-effort repairs
        """
        # First, try to parse as-is
        from core.tool_calls import extract_tool_calls
        calls = extract_tool_calls(text)
        if calls:
            return True, text

        # If no calls found, attempt repair strategies
        repaired = cls._attempt_repair(text)
        if repaired != text:
            calls = extract_tool_calls(repaired)
            if calls:
                return True, repaired

        # If still no calls, return original with repair attempts logged
        return False, text

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
        """Attempt to close unclosed <call> tags."""
        import re

        # Find all opening <call tags
        open_pattern = r'<call\s+name="[^"]*"[^>]*>'
        opens = list(re.finditer(open_pattern, text))

        if not opens:
            return text

        # Work backwards to avoid index shifting issues
        # We'll try to add closing tags where they're missing
        result = list(text)
        offset = 0

        for match in reversed(opens):
            start, end = match.span()
            start += offset
            end += offset

            # Look for a closing tag after this opening
            search_start = end
            closing_tag = '</call>'
            closing_pos = text.find(closing_tag, search_start)

            # If no closing tag found, or if another opening tag appears first
            next_open = text.find('<call', search_start)
            if closing_pos == -1 or (next_open != -1 and next_open < closing_pos):
                # Insert closing tag after the opening tag's content
                # Heuristic: insert after the opening tag or at end of string
                insert_pos = end
                # But don't insert if we're already at the end
                if insert_pos < len(text):
                    result.insert(insert_pos, closing_tag)
                    offset += len(closing_tag)

        return ''.join(result)

    @classmethod
    def _repair_common_json_issues(cls, text: str) -> str:
        """Attempt to fix common JSON formatting issues."""
        import re

        # Look for 3.14{...} patterns that might be malformed
        json_pattern = r'3\.14\s*(\{.*?\})(?=\s*3\.14|\s*<|\s*$|$)'

        def fix_json_match(match):
            json_str = match.group(1)
            # Try to fix common JSON issues
            fixed = cls._attempt_fix_json(json_str)
            if fixed != json_str:
                return f'3.14{fixed}'
            return match.group(0)

        return re.sub(json_pattern, fix_json_match, text, flags=re.DOTALL)

    @classmethod
    def _attempt_fix_json(cls, json_str: str) -> str:
        """Attempt to fix a JSON string with common issues."""
        # Remove trailing commas before } or ]
        json_str = re.sub(r',\s*([}\]])', r'\1', json_str)

        # Fix unquoted keys (simple case)
        json_str = re.sub(r'([{,]\s*)(\w+)(\s*:)', r'\1"\2"\3', json_str)

        # Try to balance braces and brackets
        open_braces = json_str.count('{')
        close_braces = json_str.count('}')
        open_brackets = json_str.count('[')
        close_brackets = json_str.count(']')

        # Add missing closing braces/brackets at the end
        if open_braces > close_braces:
            json_str += '}' * (open_braces - close_braces)
        if open_brackets > close_brackets:
            json_str += ']' * (open_brackets - close_brackets)

        return json_str


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
_CONTENT_FIELD_RE = re.compile(r'"content"\s*:\s*"(.*)"\s*\}', re.DOTALL)
_UNESCAPED_QUOTE_RE = re.compile(r'(?<!\\)"')


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

    json_match = _TOOL_CALL_JSON_RE.search(text_buf)
    if not json_match:
        return results

    json_str = _TOOL_CALL_CLOSE_RE.sub("", json_match.group(1)).strip()
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
