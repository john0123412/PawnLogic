"""Pure GDB command/script planning for pwn debugger adapters."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GdbPlan:
    script_lines: tuple[str, ...]
    interactive_inputs: tuple[str, ...]


# Breakpoints are interpolated into ``b <bp>`` / ``b *<bp>`` lines of a GDB
# script; anything outside this character class could break out into
# arbitrary GDB commands.
_BREAKPOINT_RE = re.compile(r"^[0-9a-zA-Z_.*+\- ]+$")

# GDB script lines that escape to a host shell or the Python API. Rejected
# outright: the debugger already runs with real local execution.
_GDB_DANGEROUS_COMMAND_RE = re.compile(r"^\s*(shell|python|!|py\b)")

# input_file is interpolated into ``run < '<path>'``; newlines would inject
# extra GDB script lines and quotes would break out of the quoting.
_INPUT_FILE_FORBIDDEN = ("\n", "\r", "'", '"', "\\")


def _validate_breakpoint(breakpoint: object) -> str:
    bp = str(breakpoint)
    if not _BREAKPOINT_RE.fullmatch(bp):
        raise ValueError(
            f"invalid breakpoint {bp!r}: only [0-9a-zA-Z_.*+- ] characters allowed"
        )
    return bp


def _validate_input_file(input_file: object) -> str:
    path = str(input_file or "")
    if not path:
        return ""
    if (
        any(ch in path for ch in _INPUT_FILE_FORBIDDEN)
        or path.startswith("-")
        or path.startswith("~")
    ):
        raise ValueError(
            f"invalid input_file {path!r}: newlines, quotes, backslashes, "
            "and leading '-'/'~' are not allowed"
        )
    return path


def _validate_commands(commands: list[str]) -> list[str]:
    clean: list[str] = []
    for command in commands:
        cmd = str(command)
        if _GDB_DANGEROUS_COMMAND_RE.match(cmd):
            raise ValueError(
                f"rejected GDB command {cmd!r}: shell/python escapes are not allowed"
            )
        if "\n" in cmd or "\r" in cmd:
            raise ValueError(
                f"rejected GDB command {cmd!r}: multi-line commands are not allowed"
            )
        clean.append(cmd)
    return clean


def build_gdb_plan(
    *,
    breakpoints: list[str],
    commands: list[str],
    input_file: str = "",
) -> GdbPlan:
    lines = ["set pagination off", "set confirm off", "set debuginfod enabled off"]
    inputs: list[str] = []
    for breakpoint in (_validate_breakpoint(bp) for bp in breakpoints):
        command = (
            f"b *{breakpoint}"
            if breakpoint.startswith("0x") or breakpoint.isdigit()
            else f"b {breakpoint}"
        )
        lines.append(command)
        inputs.append(command + "\n")
    safe_input = _validate_input_file(input_file)
    lines.append(f"run < '{safe_input}'" if safe_input else "run")
    safe_commands = _validate_commands(commands)
    lines.extend(safe_commands)
    lines.append("quit")
    inputs.extend(f"{command}\n" for command in safe_commands)
    inputs.append("quit\n")
    return GdbPlan(tuple(lines), tuple(inputs))


__all__ = ["GdbPlan", "build_gdb_plan"]
