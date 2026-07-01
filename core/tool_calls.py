"""Hybrid XML/JSON tool call parsing helpers."""

from __future__ import annotations

from collections.abc import Callable
import json
from json import JSONDecodeError
import re
from typing import Any


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
