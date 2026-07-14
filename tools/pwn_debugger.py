"""Pure GDB command/script planning for pwn debugger adapters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GdbPlan:
    script_lines: tuple[str, ...]
    interactive_inputs: tuple[str, ...]


def build_gdb_plan(
    *,
    breakpoints: list[str],
    commands: list[str],
    input_file: str = "",
) -> GdbPlan:
    lines = ["set pagination off", "set confirm off", "set debuginfod enabled off"]
    inputs: list[str] = []
    for breakpoint in breakpoints:
        command = (
            f"b *{breakpoint}"
            if breakpoint.startswith("0x") or breakpoint.isdigit()
            else f"b {breakpoint}"
        )
        lines.append(command)
        inputs.append(command + "\n")
    lines.append(f"run < '{input_file}'" if input_file else "run")
    lines.extend(commands)
    lines.append("quit")
    inputs.extend(f"{command}\n" for command in commands)
    inputs.append("quit\n")
    return GdbPlan(tuple(lines), tuple(inputs))


__all__ = ["GdbPlan", "build_gdb_plan"]
