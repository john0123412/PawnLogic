"""tools/eval/redaction.py - Redaction utilities for evaluation artifacts.

Redacts local paths and secret-shaped values before artifact persistence.
"""

from __future__ import annotations

import re

SECRET_RE = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{20,}|"
    r"sk-(proj-|svcacct-|live-)?[A-Za-z0-9_-]{20,}|"
    r"ghp_[A-Za-z0-9]{36}|"
    r"github_pat_[A-Za-z0-9_]{50,}|"
    r"tp-[a-z0-9]{30,}|"
    r"AIza[A-Za-z0-9_-]{35}|"
    r"AKIA[0-9A-Z]{16}|"
    r"ASIA[0-9A-Z]{16}|"
    r"(OPENAI|ANTHROPIC|DEEPSEEK|AZURE|GOOGLE|GEMINI|MISTRAL|OPENROUTER|"
    r"TOGETHER|DASHSCOPE|MOONSHOT|ZHIPU|XAI)[A-Z0-9_]*(API_)?KEY"
    r"[ \t]*[:=][ \t]*['\"]?[A-Za-z0-9_./+=-]{20,}"
)

LINUX_HOME_PREFIX = "/" + "home/"
MAC_USERS_PREFIX = "/" + "Users/"
WINDOWS_USERS_PREFIX = "C:" + "\\Users\\"

LOCAL_PATH_RE = re.compile(
    re.escape(LINUX_HOME_PREFIX)
    + r"[^/ ]+(?:/[^ \n\t]*)?|"
    + re.escape(MAC_USERS_PREFIX)
    + r"[^/ ]+(?:/[^ \n\t]*)?|"
    + re.escape(WINDOWS_USERS_PREFIX)
    + r"[^\\ \n\t]+(?:\\[^ \n\t]*)?"
)


def redact_summary(summary: str) -> str:
    """Redact local paths and secret-shaped values before artifact persistence."""
    summary = SECRET_RE.sub("[REDACTED_SECRET]", summary)
    return LOCAL_PATH_RE.sub("[REDACTED_PATH]", summary)
