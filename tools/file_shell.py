"""Shell-process implementations used by the public file-tool adapters."""

from __future__ import annotations

from contextlib import suppress
import os
import queue
import re
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any


def run_shell(
    command: str,
    *,
    timeout: int,
    work_dir: str,
    env: dict,
    authorize: Callable[[str, str], tuple[bool, Any]],
    format_policy_block: Callable[[Any], str],
    logger: Any,
    emit_warning: Callable[[], None],
    announce: Callable[[str], None],
    max_chars: Callable[[], int],
    popen: Callable[..., Any] = subprocess.Popen,
    timeout_error: type[BaseException] = subprocess.TimeoutExpired,
) -> str:
    """Run a bounded non-interactive shell process after host authorization."""
    ok, decision = authorize(command, work_dir)
    if not ok:
        return format_policy_block(decision)

    logger.debug(
        "[run_shell] executing | risk={} rule={} cmd={!r} timeout={} cwd={}",
        decision.risk.value,
        decision.matched_rule,
        decision.redacted_command,
        timeout,
        work_dir,
    )
    emit_warning()
    announce(command)
    process = None
    try:
        process = popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            cwd=work_dir,
            env=env,
            start_new_session=True,
        )
        stdout, stderr = process.communicate(timeout=timeout)
        output = stdout.decode("utf-8", errors="ignore") + stderr.decode(
            "utf-8", errors="ignore"
        )
        output = _truncate_shell_output(output, max_chars())
        if process.returncode != 0:
            logger.warning(
                f"[run_shell] command returned non-zero exit code {process.returncode}: "
                f"{command!r}\n  stderr: {stderr[:300]!r}"
            )
        return _add_missing_path_hint(output, command) or "(no output)"
    except timeout_error:
        partial = _timeout_output(process, timeout_error=timeout_error)
        partial_hint = (
            f"\n\n[Partial output received before timeout]:\n{partial[:500]}"
            if partial.strip()
            else ""
        )
        logger.warning(f"[run_shell] timeout ({timeout}s): {command!r}")
        return (
            f"ERROR: command timed out (>{timeout}s); process terminated.{partial_hint}\n\n"
            "Did you run an interactive program such as gdb, python, vim, or nc?\n"
            "  - For GDB, use -batch, e.g. gdb -batch -ex 'run' ./binary\n"
            "  - For interactive processes, use run_interactive with scripted inputs.\n"
            f"  - If the command legitimately takes longer, increase timeout (current: {timeout}s)."
        )
    except Exception as error:
        logger.error(
            f"[run_shell] execution error: {command!r} - "
            f"{type(error).__name__}: {error}"
        )
        return f"ERROR: {type(error).__name__}: {error}"


def run_interactive(
    command: str,
    inputs: Sequence[Any],
    *,
    timeout: int,
    work_dir: str,
    authorize: Callable[[str, str], tuple[bool, Any]],
    format_policy_block: Callable[[Any], str],
    get_shell_env: Callable[[], dict],
    announce: Callable[[str], None],
    announce_input: Callable[[Any], None],
    max_chars: Callable[[], int],
    popen: Callable[..., Any] = subprocess.Popen,
    timeout_error: type[BaseException] = subprocess.TimeoutExpired,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
) -> str:
    """Run a scripted interactive process after host authorization."""
    ok, decision = authorize(command, work_dir)
    if not ok:
        return format_policy_block(decision)

    announce(command)
    output_queue: queue.Queue[str] = queue.Queue()
    try:
        process = popen(
            command,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=work_dir,
            bufsize=0,
            env=get_shell_env(),
        )
    except Exception as error:
        return f"ERROR: failed to start process: {error}"

    _start_reader(process, output_queue)
    output_chunks: list[str] = []
    deadline = clock() + timeout
    try:
        output_chunks.append(_drain_queue(output_queue, 0.6, sleep=sleep))
        for item in inputs:
            if clock() > deadline:
                output_chunks.append("\n[TIMEOUT REACHED: Interactive script aborted]")
                break
            if isinstance(item, str) and item.upper().startswith("SLEEP:"):
                _sleep_input(item, sleep=sleep)
                output_chunks.append(_drain_queue(output_queue, 0.1, sleep=sleep))
                continue
            data = item.encode() if isinstance(item, str) else item
            announce_input(item)
            try:
                process.stdin.write(data)
                process.stdin.flush()
            except BrokenPipeError:
                output_chunks.append("[process closed stdin early]")
                break
            output_chunks.append(_drain_queue(output_queue, 0.4, sleep=sleep))
        try:
            process.wait(timeout=2)
        except timeout_error:
            process.terminate()
        output_chunks.append(_drain_queue(output_queue, 0.3, sleep=sleep))
    except Exception as error:
        output_chunks.append(f"\n[ERROR during interaction: {error}]")
    finally:
        with suppress(Exception):
            process.terminate()

    output = "".join(output_chunks)
    limit = max_chars()
    if len(output) > limit:
        output = output[: limit // 2] + "\n...[truncated]...\n" + output[-limit // 4 :]
    return output or "(no output)"


def _truncate_shell_output(output: str, limit: int) -> str:
    if len(output) <= limit:
        return output
    half = limit // 2
    return (
        output[:half]
        + f"\n...[{len(output)} chars total, truncated to {limit}]...\n"
        + output[-half // 4 :]
    )


def _add_missing_path_hint(output: str, command: str) -> str:
    if not output or "No such file or directory" not in output:
        return output
    match = re.search(r"(?:/|^)([a-zA-Z0-9_.\\-]+)(?:\\s|$)", command)
    filename = match.group(1) if match else ""
    if filename:
        return output + (
            "\n[Path Hint] File not found. Try:\n"
            f"  - find / -name '{filename}' 2>/dev/null   # global search\n"
            "  - ls -la /proc/self/cwd                  # confirm current working directory\n"
            "  - readlink -f /proc/self/exe              # confirm binary location\n"
        )
    return output + (
        "\n[Path Hint] File not found. Try:\n"
        "  - ls -la /proc/self/cwd                  # confirm current working directory\n"
        "  - find / -name '<filename>' 2>/dev/null   # global search\n"
    )


def _process_group_id(process: Any) -> int | None:
    """Return the child's process group id, or None when unavailable."""
    try:
        return os.getpgid(process.pid)
    except Exception:
        return None


def _signal_group(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except Exception:
        return


def _communicate_bounded(
    process: Any,
    *,
    timeout_error: type[BaseException],
) -> str | None:
    """Collect output with a hard bound.

    Returns the decoded output, ``""`` when the pipes closed without data,
    or ``None`` when the attempt timed out again (pipes still open).
    """
    try:
        stdout, stderr = process.communicate(timeout=3)
    except timeout_error:
        return None
    except Exception:
        return ""
    output = stdout.decode("utf-8", errors="ignore")
    return output + (stderr.decode("utf-8", errors="ignore") if stderr else "")


def _timeout_output(
    process: Any,
    *,
    timeout_error: type[BaseException],
) -> str:
    """Collect output from a timed-out child without ever blocking forever.

    The whole process group gets SIGTERM then SIGKILL, and every communicate()
    attempt is bounded. A child stuck in an uninterruptible kernel wait keeps
    the pipe ends open forever even after SIGKILL; in that case the pipes are
    abandoned and whatever was captured so far is returned.
    """
    if process is None:
        return ""
    pgid = _process_group_id(process)
    if pgid is not None:
        _signal_group(pgid, signal.SIGTERM)
    else:
        with suppress(Exception):
            process.terminate()
    partial = _communicate_bounded(process, timeout_error=timeout_error)
    if partial is not None:
        return partial
    if pgid is not None:
        _signal_group(pgid, signal.SIGKILL)
    else:
        with suppress(Exception):
            process.kill()
    partial = _communicate_bounded(process, timeout_error=timeout_error)
    return partial if partial is not None else ""


def _start_reader(process: Any, output_queue: queue.Queue[str]) -> None:
    def reader() -> None:
        try:
            while True:
                chunk = process.stdout.read(512)
                if not chunk:
                    return
                output_queue.put(chunk.decode("utf-8", errors="ignore"))
        except Exception:
            return

    threading.Thread(target=reader, daemon=True).start()


def _drain_queue(
    output_queue: queue.Queue[str],
    wait: float,
    *,
    sleep: Callable[[float], None],
) -> str:
    sleep(wait)
    parts: list[str] = []
    while not output_queue.empty():
        try:
            parts.append(output_queue.get_nowait())
        except queue.Empty:
            break
    return "".join(parts)


def _sleep_input(item: str, *, sleep: Callable[[float], None]) -> None:
    try:
        sleep(float(item.split(":", 1)[1]))
    except Exception:
        return


__all__ = ["run_interactive", "run_shell"]
