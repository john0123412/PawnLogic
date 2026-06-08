"""Plan guard helpers for tool-call authorization."""

import json


PLAN_EXEMPT_TOOLS = {
    "pwn_env",        # 环境探测，无副作用
    "list_dir",       # 目录列出，无副作用
    "search_skills",  # P6: 技能包检索，只读操作
    "check_service",  # P6: 环境嗅探，只读操作
    # git_op 仅只读操作豁免（见 is_plan_exempt）
}


def is_plan_exempt(tc_buf: dict) -> bool:
    """若本次所有工具调用均属于豁免名单（只读），允许跳过 <plan> 检查。"""
    for idx in tc_buf:
        name = tc_buf[idx]["name"]
        if name not in PLAN_EXEMPT_TOOLS and name != "git_op":
            return False
        if name == "git_op":
            try:
                args = json.loads(tc_buf[idx]["args"])
                if args.get("action") not in ("status", "log", "diff", "branch"):
                    return False
            except Exception:
                return False
    return True


def tool_call_missing_plan(text_buf: str, tc_buf: dict) -> bool:
    """Return True when a non-exempt tool call was emitted without a plan."""
    if not tc_buf:
        return False
    if is_plan_exempt(tc_buf):
        return False
    return "<plan>" not in text_buf or "</plan>" not in text_buf
