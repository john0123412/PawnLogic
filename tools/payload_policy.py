"""tools/payload_policy.py - operation-policy gate for run_code payload content.

The run-command gate in ``tools.sandbox`` only sees
``<interpreter> <temp script>``; the payload's own content is invisible to
it. This module extracts the tractable literal shell surface embedded in a
payload — bash lines and Python ``os.system`` / ``os.popen`` /
``subprocess(..., shell=True)`` commands — and classifies each with the
same operation policy as a direct command, failing closed on anything but
``ALLOW``.

Still not a sandbox boundary: dynamic (non-literal) command construction,
``from os import system`` aliases, writes outside credential directories,
and the payload surface of javascript/go/compiled languages stay invisible
to the classifier (residual recorded under Known Risks in AGENT.md).
"""

from __future__ import annotations

import ast
import os

from config import READ_BLACKLIST
from core.operation_policy import OperationAction, classify_shell_command

# Python call targets whose first literal string argument is always a shell
# command line, and those that spawn one only when ``shell=True`` is passed.
_PY_ALWAYS_SHELL_CALLS = {"os.system", "os.popen",
                          "subprocess.getoutput", "subprocess.getstatusoutput"}
_PY_OPTIONAL_SHELL_CALLS = {"subprocess.run", "subprocess.call",
                            "subprocess.check_call", "subprocess.check_output",
                            "subprocess.Popen"}


def _dotted_call_name(func: ast.expr) -> str | None:
    """Return ``module.func`` for a dotted call target, else None."""
    parts: list[str] = []
    node: ast.expr = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def python_payload_commands(code: str) -> list[str]:
    """Literal shell commands a Python payload is guaranteed to spawn.

    Only fully literal, statically visible call shapes are extracted;
    anything dynamic is invisible here and stays a Known Risks residual.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []  # The interpreter rejects it at run time; nothing to judge.
    commands: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = _dotted_call_name(node.func)
        if target is None:
            continue
        shell_invoked = target in _PY_ALWAYS_SHELL_CALLS or (
            target in _PY_OPTIONAL_SHELL_CALLS
            and any(
                kw.arg == "shell"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
                for kw in node.keywords
            )
        )
        if (
            shell_invoked
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            commands.append(node.args[0].value)
    return commands


def bash_payload_commands(code: str) -> list[str]:
    """Non-comment, non-blank lines of a bash payload."""
    return [
        stripped
        for line in code.splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    ]


# ── Filesystem-access bypass scan ─────────────────────────
# Pure-Python reads/writes (open(), pathlib, os/shutil mutators) bypass the
# read/write path policy that gates read_file/write_file. This scan flags
# statically visible accesses whose target resolves inside a READ_BLACKLIST
# credential directory. Conservative by design: relative paths and targets
# outside the blacklist are untouched; only literal (or expanduser/expandvars
# wrapped literal) paths are judged.

_sensitive_roots: tuple[str, ...] | None = None


def _blacklist_roots() -> tuple[str, ...]:
    global _sensitive_roots
    if _sensitive_roots is None:
        roots = []
        for entry in READ_BLACKLIST:
            try:
                roots.append(
                    os.path.realpath(os.path.abspath(os.path.expanduser(entry)))
                )
            except Exception:
                continue
        _sensitive_roots = tuple(roots)
    return _sensitive_roots


def _path_under_blacklist(path: str) -> bool:
    try:
        real = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
    except Exception:
        return False
    return any(
        os.path.commonpath([real, root]) == root for root in _blacklist_roots()
    )


def _static_path_string(expr: ast.expr) -> str | None:
    """Resolve a statically visible path expression to a string, else None."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.Call):
        target = _dotted_call_name(expr.func)
        if target in {"os.path.expanduser", "os.path.expandvars",
                      "os.path.abspath", "os.path.realpath", "os.path.normpath"} \
                and expr.args:
            inner = _static_path_string(expr.args[0])
            if inner is None:
                return None
            if target == "os.path.expanduser":
                return os.path.expanduser(inner)
            if target == "os.path.expandvars":
                return os.path.expandvars(inner)
            return inner
    return None


# Dotted call targets whose first positional argument is a filesystem path.
_FS_PATH_CALLS = {
    "open", "io.open", "os.remove", "os.unlink", "os.rmdir",
    "os.removedirs", "os.mkdir", "os.makedirs", "os.rename", "os.replace",
    "os.chmod", "os.chown", "os.truncate",
    "shutil.rmtree", "shutil.copy", "shutil.copy2", "shutil.copyfile",
    "shutil.copytree", "shutil.move",
}
# pathlib.Path(<path>) methods that touch the filesystem.
_FS_PATHLIB_METHODS = {
    "read_text", "read_bytes", "write_text", "write_bytes", "open",
    "unlink", "mkdir", "rmdir", "rename", "replace", "chmod", "touch",
}


def _fs_path_arg(target: str, node: ast.Call) -> ast.expr | None:
    """Return the AST node holding the filesystem path argument, if any."""
    if target == "pathlib.Path":
        args = node.args
        return args[0] if args else None
    if target in _FS_PATH_CALLS:
        if node.args:
            return node.args[0]
        for kw in node.keywords:
            if kw.arg in {"file", "path", "src", "dst"}:
                return kw.value
    return None


def _is_path_constructor_call(node: ast.expr) -> bool:
    """True when ``node`` is a ``Path(<literal>)`` / ``pathlib.Path(<literal>)`` call."""
    return (
        isinstance(node, ast.Call)
        and _dotted_call_name(node.func) in {"Path", "pathlib.Path"}
    )


def python_fs_bypass_errors(code: str, cwd: str) -> list[str]:
    """Deny statically visible filesystem access to credential directories.

    Catches ``open("~/.ssh/id_rsa")``, ``pathlib.Path(...).read_text()``,
    ``os.remove``/``shutil.*`` and similar calls whose literal target
    resolves under a READ_BLACKLIST entry. Relative and non-sensitive
    targets are left alone.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    # Track simple ``name = Path(<literal>)`` aliases so
    # ``p = Path("~/.ssh/id_rsa"); p.read_text()`` is still judged.
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and _is_path_constructor_call(node.value)
            and node.value.args
        ):
            literal = _static_path_string(node.value.args[0])
            if literal is not None:
                aliases[node.targets[0].id] = literal
    errors: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        target = _dotted_call_name(func)
        path_expr: ast.expr | None = None
        label = target or ""
        if target == "pathlib.Path" or target == "Path":
            # Defer: judged when a filesystem method is called on it.
            continue
        if target in _FS_PATH_CALLS:
            path_expr = _fs_path_arg(target, node)
        elif isinstance(func, ast.Attribute):
            method = func.attr
            if method in _FS_PATHLIB_METHODS:
                receiver = func.value
                if _is_path_constructor_call(receiver):
                    path_expr = _fs_path_arg("pathlib.Path", receiver)
                    label = f"pathlib.Path.{method}"
                elif isinstance(receiver, ast.Name) and receiver.id in aliases:
                    path_expr = None
                    raw_alias = aliases[receiver.id]
                    label = f"pathlib.Path.{method}"
                    candidate = (
                        raw_alias
                        if os.path.isabs(os.path.expanduser(raw_alias))
                        else os.path.join(cwd, raw_alias)
                    )
                    if _path_under_blacklist(candidate):
                        shown = raw_alias if len(raw_alias) <= 80 else raw_alias[:77] + "..."
                        errors.append(
                            f"  [python_fs_policy] {label}(...): path '{shown}' resolves "
                            "inside a protected credential directory; direct filesystem "
                            "access to credentials is denied."
                        )
                    continue
        if path_expr is None:
            continue
        raw = _static_path_string(path_expr)
        if raw is None:
            continue
        candidate = raw if os.path.isabs(os.path.expanduser(raw)) else os.path.join(cwd, raw)
        if _path_under_blacklist(candidate):
            shown = raw if len(raw) <= 80 else raw[:77] + "..."
            errors.append(
                f"  [python_fs_policy] {label}(...): path '{shown}' resolves "
                "inside a protected credential directory; direct filesystem "
                "access to credentials is denied."
            )
    return errors


def payload_policy_errors(language: str, code: str, cwd: str) -> list[str]:
    """Judge shell commands embedded in a run_code payload.

    For the two languages whose payloads carry a tractable literal shell
    surface, classify each embedded command with the same operation policy
    as a direct command and fail closed on anything but ``ALLOW``.
    Python payloads are additionally scanned for direct filesystem access
    to credential directories (the ``open("~/.ssh/id_rsa")`` bypass).
    Returns one human-readable error line per blocked command.
    """
    if language == "bash":
        embedded = bash_payload_commands(code)
    elif language == "python":
        embedded = python_payload_commands(code)
    else:
        return []
    errors: list[str] = []
    for command in embedded:
        decision = classify_shell_command(command, cwd=cwd)
        if decision.action is not OperationAction.ALLOW:
            errors.append(
                f"  [{decision.matched_rule}] {decision.redacted_command}: "
                f"{decision.reason}"
            )
    if language == "python":
        errors.extend(python_fs_bypass_errors(code, cwd))
    return errors
