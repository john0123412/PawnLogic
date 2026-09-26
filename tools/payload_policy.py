"""tools/payload_policy.py - operation-policy gate for run_code payload content.

The run-command gate in ``tools.sandbox`` only sees
``<interpreter> <temp script>``; the payload's own content is invisible to
it. This module extracts the tractable literal shell surface embedded in a
payload — bash lines and Python ``os.system`` / ``os.popen`` /
``subprocess(..., shell=True)`` commands — and classifies each with the
same operation policy as a direct command, failing closed on anything but
``ALLOW``.

Still not a sandbox boundary: dynamic (non-literal) command construction,
``from os import system`` aliases, and the payload surface of
javascript/go/compiled languages stay invisible to the classifier
(residual recorded under Known Risks in AGENT.md).
"""

from __future__ import annotations

import ast

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


def payload_policy_errors(language: str, code: str, cwd: str) -> list[str]:
    """Judge shell commands embedded in a run_code payload.

    For the two languages whose payloads carry a tractable literal shell
    surface, classify each embedded command with the same operation policy
    as a direct command and fail closed on anything but ``ALLOW``.
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
    return errors
