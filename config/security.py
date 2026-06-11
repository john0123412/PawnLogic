"""config/security.py - security allow/deny lists and output helpers."""
import os
import re
from .paths import PAWNLOGIC_HOME
from core.state import state as _state

READ_BLACKLIST = [os.path.expanduser(p) for p in
    ["~/.ssh", "~/.gnupg", "~/.config/gcloud", "~/.aws", "~/.kube"]]
READ_BLACKLIST.extend([
    str(PAWNLOGIC_HOME / ".env"),
])

WRITE_BLACKLIST = [
    "/etc", "/bin", "/sbin", "/usr/bin", "/usr/sbin",
    "/boot", "/lib", "/lib64", "/dev", "/proc", "/sys",
]

SENSITIVE_ENV_KEYS = {
    "PAWN_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
    "QWEN_API_KEY", "ZHIPU_API_KEY", "SILICON_API_KEY", "OPENROUTER_API_KEY",
    "MOONSHOT_API_KEY", "MINIMAX_API_KEY", "GROQ_API_KEY", "LOCAL_API_KEY",
    "XIAOMI_API_KEY", "TAVILY_API_KEY", "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN", "GITHUB_TOKEN", "GH_TOKEN",
}

SENSITIVE_ENV_MARKERS = (
    "API_KEY", "ACCESS_KEY", "SECRET", "TOKEN", "PASSWORD", "PRIVATE_KEY",
)


def scrub_sensitive_env(env: dict | None = None) -> dict:
    """Return a copy of env with credentials removed for tool subprocesses."""
    source = os.environ if env is None else env
    clean = {}
    for key, value in source.items():
        upper = str(key).upper()
        if upper in SENSITIVE_ENV_KEYS:
            continue
        if any(marker in upper for marker in SENSITIVE_ENV_MARKERS):
            continue
        clean[key] = value
    return clean

DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+[/~]", r"sudo\s+rm\s+-rf", r"mkfs\.",
    r"rm\s+-rf\s+(\*|\.\/|\./\*|\.)($|\s)",
    r"dd\s+if=", r">\s*/dev/sd", r"chmod\s+-R\s+777\s+/", r"\bshred\b",
    r":\(\)\s*\{.*\|.*&\s*\};\s*:",
    r"curl\s.*\|\s*(ba)?sh",
    r"wget\s.*\|\s*(ba)?sh",
    r"wget\s.*-O\s*-\s*\|\s*(ba)?sh",
    r"\bnc\s.*-[celp]\s*\d*\s*/bin/(ba)?sh",
    r"\bncat\s.*-e\s*/bin/(ba)?sh",
    r"python[23]?\s*-c.*socket.*connect",
    r"mkfifo\s.*/tmp/",
    r"\bsudo\b",
    r"docker\s+(run|exec|rm)",
]

_ERROR_MAP = {
    "Traceback":            "❌ System is busy. Please try again later.",
    "ConnectionError":      "❌ Network connection failed. Please check your network.",
    "TimeoutError":         "❌ Request timed out. Please try again later.",
    "RateLimitError":       "❌ API rate limit exceeded. Please try again later.",
    "AuthenticationError":  "❌ API key is invalid. Reconfigure it with /setkey.",
    "PermissionError":      "❌ Permission denied. Please check file permissions.",
    "FileNotFoundError":    "❌ File not found. Please check the path.",
    "ModuleNotFoundError":  "❌ Missing dependency module. Install it and try again.",
    "JSONDecodeError":      "❌ Failed to parse response data. Please try again later.",
    "API Error":            "❌ API call failed. Please try again later.",
    "ERROR":                "❌ Operation failed. Please try again later.",
}

_HTTP_USER_HINTS = {
    400: "Bad request. Check the model, base URL, and provider compatibility.",
    401: "Unauthorized. The API key is missing or invalid; reconfigure it with /setkey.",
    403: "Forbidden. The API key was rejected or lacks access to this model/provider.",
    404: "Not found. Check the provider Base URL and model ID.",
    408: "Request timed out at the provider.",
    422: "Provider rejected the request payload.",
    429: "Rate limit or quota exceeded. Wait before retrying.",
    500: "Provider internal server error. Retry later or switch provider.",
    502: "Provider bad gateway. The upstream model service failed.",
    503: "Provider unavailable or overloaded. Retry later or switch provider.",
    504: "Provider gateway timeout. Retry later or switch provider.",
}


def _friendly_http_error(raw_error: str) -> str | None:
    match = re.search(r"\bHTTP\s+(\d{3})\b", raw_error, flags=re.IGNORECASE)
    if not match:
        return None
    status = int(match.group(1))
    hint = _HTTP_USER_HINTS.get(status, "Provider returned an HTTP error.")
    first_line = " ".join(raw_error.split())
    if len(first_line) > 180:
        first_line = first_line[:177] + "..."
    return f"❌ HTTP {status}: {hint} ({first_line})"


def user_friendly_error(raw_error: str) -> str:
    """Convert raw errors into concise user-facing messages in user mode."""
    if not _state.user_mode:
        return raw_error
    http_msg = _friendly_http_error(raw_error)
    if http_msg:
        return http_msg
    for keyword, friendly in _ERROR_MAP.items():
        if keyword.lower() in raw_error.lower():
            return friendly
    first_line = raw_error.split("\n")[0][:80]
    return f"❌ {first_line}"


def smart_truncate(text: str, head: int = 30, tail: int = 30) -> str:
    """Keep the first head lines and last tail lines, replacing the middle."""
    lines = text.splitlines()
    total = len(lines)
    if total <= head + tail:
        return text
    kept_head = lines[:head]
    kept_tail = lines[total - tail:]
    dropped   = total - head - tail
    marker    = (f"[... {dropped} lines truncated for token efficiency "
                 f"(total {total}, kept first {head} + last {tail}) ...]")
    return "\n".join(kept_head + [marker] + kept_tail)
