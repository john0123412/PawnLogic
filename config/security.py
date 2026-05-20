"""config/security.py — 安全名单与输出工具函数"""
import os
from core.state import state as _state

READ_BLACKLIST = [os.path.expanduser(p) for p in
    ["~/.ssh", "~/.gnupg", "~/.config/gcloud", "~/.aws", "~/.kube"]]

WRITE_BLACKLIST = [
    "/etc", "/bin", "/sbin", "/usr/bin", "/usr/sbin",
    "/boot", "/lib", "/lib64", "/dev", "/proc", "/sys",
]

DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+[/~]", r"sudo\s+rm\s+-rf", r"mkfs\.",
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
    "Traceback":            "❌ 系统忙，请稍后重试",
    "ConnectionError":      "❌ 网络连接失败，请检查网络",
    "TimeoutError":         "❌ 请求超时，请稍后重试",
    "RateLimitError":       "❌ API 调用频率过高，请稍后重试",
    "AuthenticationError":  "❌ API Key 无效，请用 /setkey 重新配置",
    "PermissionError":      "❌ 权限不足，请检查文件权限",
    "FileNotFoundError":    "❌ 文件未找到，请检查路径",
    "ModuleNotFoundError":  "❌ 缺少依赖模块，请安装后重试",
    "JSONDecodeError":      "❌ 数据解析失败，请稍后重试",
    "API Error":            "❌ API 调用失败，请稍后重试",
    "ERROR":                "❌ 操作失败，请稍后重试",
}


def user_friendly_error(raw_error: str) -> str:
    """USER_MODE 专用：将原始错误信息转为用户友好的简洁提示。"""
    if not _state.user_mode:
        return raw_error
    for keyword, friendly in _ERROR_MAP.items():
        if keyword.lower() in raw_error.lower():
            return friendly
    first_line = raw_error.split("\n")[0][:80]
    return f"❌ {first_line}"


def smart_truncate(text: str, head: int = 30, tail: int = 30) -> str:
    """保留文本前 head 行和后 tail 行，丢弃中间内容并插入标记。"""
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
