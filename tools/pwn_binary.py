"""Pure/cached binary-analysis helpers used by the pwn tool adapters."""

from __future__ import annotations

from collections import OrderedDict
import os
import shlex


def shell_quote(value: str) -> str:
    return shlex.quote(str(value))


class ElfAnalysisCache:
    def __init__(self, max_entries: int = 10) -> None:
        self._entries: OrderedDict[tuple[str, float], dict[str, str]] = OrderedDict()
        self._max_entries = max_entries

    def get(self, path: str, slot: str) -> str | None:
        try:
            key = (os.path.abspath(path), os.path.getmtime(path))
        except OSError:
            return None
        entry = self._entries.get(key)
        if entry is None or slot not in entry:
            return None
        self._entries.move_to_end(key)
        return entry[slot]

    def set(self, path: str, slot: str, value: str) -> None:
        try:
            key = (os.path.abspath(path), os.path.getmtime(path))
        except OSError:
            return
        if key not in self._entries:
            self._entries[key] = {}
            if len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
        self._entries[key][slot] = value
        self._entries.move_to_end(key)

    def clear(self) -> None:
        """Remove all cached entries."""
        self._entries.clear()


def cyclic_result(args: dict) -> str:
    alphabet = b"abcdefghijklmnopqrstuvwxyz"
    width = 4
    array = [0] * width * len(alphabet)
    sequence: list[int] = []

    def debruijn(t: int, period: int) -> None:
        if t > width:
            if width % period == 0:
                sequence.extend(array[1 : period + 1])
            return
        array[t] = array[t - period]
        debruijn(t + 1, period)
        for index in range(array[t - period] + 1, len(alphabet)):
            array[t] = index
            debruijn(t + 1, t)

    debruijn(1, 1)
    pattern = bytes(alphabet[index] for index in sequence)
    action = args["action"]
    if action == "gen":
        length = int(args.get("length", 200))
        repeated = (pattern * (length // len(pattern) + 1))[:length]
        return f"Cyclic ({length} bytes):\n{repeated.decode('latin-1')}"
    if action != "find":
        return "ERROR: action = gen | find"
    value = str(args.get("value", "")).strip()
    if not value:
        return "ERROR: find requires 'value'"
    try:
        raw = bytes.fromhex(value[2:]) if value.startswith("0x") else value.encode("latin-1")[:width]
    except Exception as exc:
        return f"ERROR: {exc}"
    search = pattern * (8192 // len(pattern) + 1)
    for index in range(len(search) - width + 1):
        if search[index : index + width] == raw:
            return f"Offset (little-endian): {index}  (hex: {raw.hex()})"
        if search[index : index + width] == raw[::-1]:
            return f"Offset (big-endian): {index}"
    return f"'{value}' not found. Check format, e.g. 0x61616161 or aaab."


__all__ = ["ElfAnalysisCache", "cyclic_result", "shell_quote"]
