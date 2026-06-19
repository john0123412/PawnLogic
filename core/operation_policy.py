"""Operation policy for high-risk host-side tool execution.

This module classifies shell operations before execution. It is not a sandbox:
the policy is a confirmation and denial layer for common high-risk actions.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from config.security import DANGEROUS_PATTERNS


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class OperationAction(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


@dataclass(frozen=True)
class OperationDecision:
    action: OperationAction
    risk: RiskLevel
    reason: str
    matched_rule: str
    redacted_command: str

    def to_dict(self) -> dict[str, str]:
        return {
            "action": self.action.value,
            "risk": self.risk.value,
            "reason": self.reason,
            "matched_rule": self.matched_rule,
            "redacted_command": self.redacted_command,
        }

    def with_action(
        self,
        action: OperationAction,
        *,
        risk: RiskLevel | None = None,
        reason: str | None = None,
        matched_rule: str | None = None,
    ) -> OperationDecision:
        return replace(
            self,
            action=action,
            risk=risk or self.risk,
            reason=reason or self.reason,
            matched_rule=matched_rule or self.matched_rule,
        )


_REDIRECT_RE = re.compile(
    r"(?:^|[\s;|&])(?P<op>&>|(?:\d)?>>|(?:\d)?>)\s*"
    r"(?P<target>'[^']+'|\"[^\"]+\"|[^\s;&|]+)"
)
_PIPE_TO_SHELL_RE = re.compile(
    r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:/usr/bin/|/bin/)?(?:sh|bash)\b",
    re.IGNORECASE,
)
_XARGS_RM_RE = re.compile(r"\bxargs\b[^\n;|&]*\brm\b", re.IGNORECASE)
_REVERSE_SHELL_PATTERNS = [
    re.compile(r"\b(?:nc|ncat)\b.*\s(?:-e|--exec)\s*/bin/(?:sh|bash)\b", re.IGNORECASE),
    re.compile(r"\b(?:nc|ncat)\b.*\s-l\b.*\s(?:-e|--exec)\s*/bin/(?:sh|bash)\b", re.IGNORECASE),
    re.compile(r"\bbash\b.*\s-i\b.*(?:/dev/tcp/|/dev/udp/)", re.IGNORECASE),
    re.compile(r"/dev/tcp/[^/\s]+/\d+.*(?:sh|bash)", re.IGNORECASE),
    re.compile(r"\bsocat\b.*\bexec:.*(?:sh|bash)", re.IGNORECASE),
    re.compile(r"\bpython[23]?\b.*socket.*connect.*(?:dup2|subprocess|pty)", re.IGNORECASE),
]
_SENSITIVE_WORD_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?key|token|password|passwd|secret|private[_-]?key)"
    r"(\s*[:=]\s*)(['\"]?)([^'\"\s;&|]+)"
)
_SENSITIVE_FLAG_RE = re.compile(
    r"(?i)(--(?:api[_-]?key|access[_-]?key|token|password|secret|private[_-]?key)"
    r"(?:=|\s+))([^'\"\s;&|]+)"
)
_KNOWN_SECRET_RE = re.compile(
    r"(sk-(?:proj-|svcacct-|live-)?[A-Za-z0-9_-]{12,}|"
    r"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|"
    r"AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16})"
)


def redact_command(command: str) -> str:
    """Redact credential-like values before logging policy decisions."""
    text = _SENSITIVE_WORD_RE.sub(r"\1\2\3<redacted>", command)
    text = _SENSITIVE_FLAG_RE.sub(r"\1<redacted>", text)
    return _KNOWN_SECRET_RE.sub("<redacted>", text)


def _split_shell(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def _strip_shell_token(token: str) -> str:
    return token.strip().strip("'\"")


def _resolve_policy_path(raw_path: str, cwd: str | Path) -> Path:
    """Expand and resolve a path using shell-like user/env expansion."""
    value = _strip_shell_token(raw_path)
    value = os.path.expandvars(os.path.expanduser(value))
    path = Path(value)
    if not path.is_absolute():
        path = Path(cwd).expanduser() / path
    return Path(os.path.realpath(path))


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        return os.path.commonpath([str(candidate), str(root)]) == str(root)
    except ValueError:
        return False


def _default_pawnlogic_home() -> Path:
    raw = os.environ.get("PAWNLOGIC_HOME")
    if raw:
        return Path(raw).expanduser()
    return Path("~/.pawnlogic").expanduser()


def _sensitive_roots() -> list[Path]:
    roots = [
        Path("~/.ssh"),
        Path("~/.aws"),
        Path("~/.gnupg"),
        Path("~/.kube"),
        Path("~/.pawnlogic/.env"),
        _default_pawnlogic_home() / ".env",
    ]
    return [Path(os.path.realpath(os.path.expandvars(os.path.expanduser(str(p))))) for p in roots]


def _system_write_roots() -> list[Path]:
    return [
        Path("/etc"),
        Path("/boot"),
        Path("/dev"),
        Path("/proc"),
        Path("/sys"),
        Path("/usr/bin"),
        Path("/usr/sbin"),
    ]


def _path_is_sensitive(path: Path) -> bool:
    return any(_is_within(path, root) for root in _sensitive_roots())


def _path_is_system_write(path: Path) -> bool:
    return any(_is_within(path, root) for root in _system_write_roots())


def _path_is_critical_write(path: Path) -> bool:
    return _path_is_sensitive(path) or _path_is_system_write(path)


def _looks_like_path(token: str) -> bool:
    if not token:
        return False
    if token.startswith(("-", "|", "&&", "||", ";")):
        return False
    return (
        token.startswith(("/", "~", "$HOME", "${HOME}"))
        or "/" in token
        or token.startswith(".")
    )


def _iter_command_paths(tokens: Iterable[str], cwd: str | Path) -> Iterable[Path]:
    for token in tokens:
        value = _strip_shell_token(token)
        if "=" in value and not value.startswith(("/", "~", "$")):
            _, value = value.split("=", 1)
        if _looks_like_path(value):
            yield _resolve_policy_path(value, cwd)


def _redirection_targets(command: str, cwd: str | Path) -> list[tuple[str, Path]]:
    targets = []
    for match in _REDIRECT_RE.finditer(command):
        targets.append((match.group("op"), _resolve_policy_path(match.group("target"), cwd)))
    return targets


def _tee_targets(tokens: list[str], cwd: str | Path) -> list[Path]:
    targets: list[Path] = []
    for index, token in enumerate(tokens):
        if Path(token).name != "tee":
            continue
        for arg in tokens[index + 1:]:
            if arg in {"|", "&&", "||", ";"}:
                break
            if arg.startswith("-"):
                continue
            targets.append(_resolve_policy_path(arg, cwd))
    return targets


def _dd_targets(tokens: list[str], cwd: str | Path) -> list[Path]:
    targets: list[Path] = []
    if not any(Path(token).name == "dd" for token in tokens):
        return targets
    for token in tokens:
        if token.startswith("of="):
            targets.append(_resolve_policy_path(token.split("=", 1)[1], cwd))
    return targets


def _option_has_recursive_force(token: str) -> bool:
    if not token.startswith("-"):
        return False
    letters = token.lstrip("-")
    return "r" in letters.lower() and "f" in letters.lower()


def _option_has_recursive(token: str) -> bool:
    if token in {"-R", "--recursive"}:
        return True
    if not token.startswith("-"):
        return False
    return "r" in token.lstrip("-").lower()


def _has_rm_rf(tokens: list[str]) -> bool:
    for index, token in enumerate(tokens):
        if Path(token).name != "rm":
            continue
        return any(_option_has_recursive_force(arg) for arg in tokens[index + 1:])
    return False


def _has_recursive_owner_mode_change(tokens: list[str], command_name: str) -> bool:
    for index, token in enumerate(tokens):
        if Path(token).name != command_name:
            continue
        return any(_option_has_recursive(arg) for arg in tokens[index + 1:])
    return False


def _has_sed_in_place(tokens: list[str]) -> bool:
    for index, token in enumerate(tokens):
        if Path(token).name != "sed":
            continue
        return any(arg == "-i" or arg.startswith("-i") for arg in tokens[index + 1:])
    return False


def _has_perl_in_place(tokens: list[str]) -> bool:
    for index, token in enumerate(tokens):
        if Path(token).name != "perl":
            continue
        for arg in tokens[index + 1:]:
            if arg.startswith("-") and "p" in arg and "i" in arg:
                return True
    return False


def _has_find_delete(tokens: list[str]) -> bool:
    return any(Path(token).name == "find" for token in tokens) and "-delete" in tokens


def _critical_path_mentioned(command: str, tokens: list[str], cwd: str | Path) -> str:
    if "docker.sock" in command or "/var/run/docker.sock" in command:
        return "critical_path:docker_socket"
    for path in _iter_command_paths(tokens, cwd):
        if _path_is_sensitive(path):
            return "critical_path:sensitive_user_secret"
    return ""


def _write_targets(tokens: list[str], command: str, cwd: str | Path) -> list[tuple[str, Path]]:
    targets: list[tuple[str, Path]] = []
    targets.extend((f"redirection:{op}", target) for op, target in _redirection_targets(command, cwd))
    targets.extend(("tee", target) for target in _tee_targets(tokens, cwd))
    targets.extend(("dd_of", target) for target in _dd_targets(tokens, cwd))

    write_like = {"rm", "chmod", "chown", "sed", "perl", "find"}
    if any(Path(token).name in write_like for token in tokens):
        targets.extend(("write_command_arg", path) for path in _iter_command_paths(tokens, cwd))
    return targets


def _legacy_misuse_match(command: str) -> str:
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command):
            return pattern
    return ""


def _decision(
    action: OperationAction,
    risk: RiskLevel,
    reason: str,
    matched_rule: str,
    command: str,
) -> OperationDecision:
    return OperationDecision(
        action=action,
        risk=risk,
        reason=reason,
        matched_rule=matched_rule,
        redacted_command=redact_command(command),
    )


def classify_shell_command(
    command: str,
    *,
    cwd: str | Path,
    workspace_dir: str | Path | None = None,
) -> OperationDecision:
    """Classify a host shell command before execution."""
    cwd_path = Path(cwd).expanduser().resolve()
    workspace = Path(workspace_dir or cwd_path).expanduser().resolve()
    tokens = _split_shell(command)

    critical_rule = _critical_path_mentioned(command, tokens, cwd_path)
    if critical_rule:
        return _decision(
            OperationAction.DENY,
            RiskLevel.CRITICAL,
            "Command references a critical credential path or Docker socket.",
            critical_rule,
            command,
        )

    write_targets = _write_targets(tokens, command, cwd_path)
    for kind, target in write_targets:
        if str(target) == "/":
            return _decision(
                OperationAction.DENY,
                RiskLevel.CRITICAL,
                "Command writes to or deletes the filesystem root.",
                f"{kind}:filesystem_root",
                command,
            )
        if _path_is_critical_write(target):
            return _decision(
                OperationAction.DENY,
                RiskLevel.CRITICAL,
                "Command writes to a protected system or credential path.",
                f"{kind}:critical_write_path",
                command,
            )

    for kind, target in write_targets:
        if kind.startswith("redirection") and not _is_within(target, workspace):
            return _decision(
                OperationAction.CONFIRM,
                RiskLevel.HIGH,
                "Shell redirection writes outside the active workspace.",
                f"{kind}:outside_workspace",
                command,
            )

    if _PIPE_TO_SHELL_RE.search(command):
        return _decision(
            OperationAction.CONFIRM,
            RiskLevel.HIGH,
            "Network download piped directly into a shell.",
            "download_pipe_shell",
            command,
        )
    if any(pattern.search(command) for pattern in _REVERSE_SHELL_PATTERNS):
        return _decision(
            OperationAction.CONFIRM,
            RiskLevel.HIGH,
            "Command resembles a reverse shell or bind shell.",
            "reverse_or_bind_shell",
            command,
        )
    if _has_rm_rf(tokens):
        return _decision(
            OperationAction.CONFIRM,
            RiskLevel.HIGH,
            "Recursive forced removal requires explicit confirmation.",
            "rm_rf",
            command,
        )
    if _has_recursive_owner_mode_change(tokens, "chmod"):
        return _decision(
            OperationAction.CONFIRM,
            RiskLevel.HIGH,
            "Recursive chmod can damage access controls.",
            "chmod_recursive",
            command,
        )
    if _has_recursive_owner_mode_change(tokens, "chown"):
        return _decision(
            OperationAction.CONFIRM,
            RiskLevel.HIGH,
            "Recursive chown can damage ownership controls.",
            "chown_recursive",
            command,
        )
    if _has_sed_in_place(tokens):
        return _decision(
            OperationAction.CONFIRM,
            RiskLevel.HIGH,
            "In-place sed edits modify files directly.",
            "sed_in_place",
            command,
        )
    if _has_perl_in_place(tokens):
        return _decision(
            OperationAction.CONFIRM,
            RiskLevel.HIGH,
            "In-place perl edits modify files directly.",
            "perl_in_place",
            command,
        )
    if _has_find_delete(tokens):
        return _decision(
            OperationAction.CONFIRM,
            RiskLevel.HIGH,
            "find -delete removes filesystem entries.",
            "find_delete",
            command,
        )
    if _XARGS_RM_RE.search(command):
        return _decision(
            OperationAction.CONFIRM,
            RiskLevel.HIGH,
            "xargs rm can delete many filesystem entries.",
            "xargs_rm",
            command,
        )
    if any(kind == "tee" for kind, _target in write_targets):
        return _decision(
            OperationAction.CONFIRM,
            RiskLevel.HIGH,
            "tee writes command output to files.",
            "tee_write",
            command,
        )
    if any(kind == "dd_of" for kind, _target in write_targets):
        return _decision(
            OperationAction.CONFIRM,
            RiskLevel.HIGH,
            "dd of= writes raw bytes to a target path.",
            "dd_output",
            command,
        )

    legacy_match = _legacy_misuse_match(command)
    if legacy_match:
        return _decision(
            OperationAction.ALLOW,
            RiskLevel.MEDIUM,
            "Command matches a misuse-risk pattern; this is classified, not sandbox-blocked.",
            f"misuse_pattern:{legacy_match}",
            command,
        )

    return _decision(
        OperationAction.ALLOW,
        RiskLevel.LOW,
        "No high-risk shell operation detected.",
        "default_allow",
        command,
    )


def is_eval_mode(argv: list[str] | None = None) -> bool:
    args = sys.argv[1:] if argv is None else argv
    return any(arg == "--eval" or arg == "-e" or arg.startswith("--eval=") for arg in args)


def is_confirmation_available(*, eval_mode: bool | None = None) -> bool:
    """Return whether an interactive high-risk confirmation can be requested."""
    active_eval_mode = eval_mode if eval_mode is not None else is_eval_mode()
    if active_eval_mode:
        return False
    stdin_tty = bool(getattr(sys.stdin, "isatty", lambda: False)())
    stdout_tty = bool(getattr(sys.stdout, "isatty", lambda: False)())
    return stdin_tty and stdout_tty


def prompt_for_confirmation(decision: OperationDecision) -> bool:
    """Prompt the user to approve a high-risk operation."""
    print("High-risk host shell operation requires confirmation.")
    print(f"Risk: {decision.risk.value}")
    print(f"Reason: {decision.reason}")
    print(f"Rule: {decision.matched_rule}")
    print(f"Command: {decision.redacted_command}")
    answer = input("Type 'yes' to run this command: ")
    return answer.strip().lower() == "yes"


def audit_operation_decision(
    decision: OperationDecision,
    *,
    operation_type: str,
    cwd: str | Path,
    interactive: bool,
) -> None:
    """Write an operation-policy decision to the existing JSONL audit logger."""
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "operation_type": operation_type,
        "action": decision.action.value,
        "risk": decision.risk.value,
        "reason": decision.reason,
        "matched_rule": decision.matched_rule,
        "redacted_command": decision.redacted_command,
        "cwd": str(cwd),
        "interactive": bool(interactive),
    }
    _write_audit_record(record)


def _write_audit_record(record: dict[str, object]) -> None:
    try:
        from core import logger as logger_mod

        if getattr(logger_mod, "_audit_logger", None) is None:
            return
        logger_mod.get_audit_logger().info(json.dumps(record, ensure_ascii=False))
    except Exception:
        pass


__all__ = [
    "OperationAction",
    "OperationDecision",
    "RiskLevel",
    "audit_operation_decision",
    "classify_shell_command",
    "is_confirmation_available",
    "is_eval_mode",
    "prompt_for_confirmation",
    "redact_command",
]
