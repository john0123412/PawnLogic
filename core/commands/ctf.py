"""CTF workspace metadata slash commands."""

from __future__ import annotations

from pathlib import Path
import shlex

from core.commands import CommandContext, register
from core.commands._common import sink_print as _print
from core.ctf_workspace import (
    CTFMetadataReadError,
    add_artifact,
    add_flag_candidate,
    add_remote_target,
    confirm_flag_candidate,
    export_ctf_writeup,
    format_ctf_status,
    init_ctf_metadata,
    load_ctf_metadata,
)
from utils.ansi import BOLD, CYAN, GRAY, GREEN, RED, YELLOW, c


def _workspace_path(ctx: CommandContext, *, create: bool = False) -> Path:
    session = ctx.session
    raw = getattr(session, "workspace_dir", "") or getattr(session, "cwd", "") or "."
    path = Path(raw).expanduser()
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _usage() -> str:
    return "\n".join([
        "  Usage:",
        "    /ctf init <challenge name>",
        "    /ctf status",
        "    /ctf artifact <path-or-note>",
        "    /ctf remote <host:port-or-url>",
        "    /ctf flag <candidate>",
        "    /ctf solved [confirmed-flag]",
        "    /ctf writeup",
    ])


def _parse_kv_args(text: str) -> tuple[str, dict[str, str]]:
    try:
        parts = shlex.split(text)
    except ValueError:
        parts = text.split()
    values: dict[str, str] = {}
    remaining: list[str] = []
    index = 0
    while index < len(parts):
        part = parts[index]
        if part in {"--category", "-c"} and index + 1 < len(parts):
            values["category"] = parts[index + 1]
            index += 2
            continue
        if part in {"--source", "-s"} and index + 1 < len(parts):
            values["source"] = parts[index + 1]
            index += 2
            continue
        remaining.append(part)
        index += 1
    return " ".join(remaining).strip(), values


@register("/ctf")
async def cmd_ctf(ctx: CommandContext) -> None:
    sub = (ctx.arg or "status").strip().lower()
    rest = (ctx.arg2 or "").strip()

    if sub in {"help", "-h", "--help"}:
        _print(c(BOLD, "\n  CTF workspace commands"))
        _print(c(GRAY, _usage()))
        return

    if sub == "init":
        challenge_name, values = _parse_kv_args(rest)
        if not challenge_name and not values:
            _print(c(RED, "  Usage: /ctf init <challenge name> [--category pwn] [--source url]"))
            return
        try:
            workspace = _workspace_path(ctx, create=True)
            metadata = init_ctf_metadata(
                workspace,
                challenge_name=challenge_name,
                category=values.get("category", ""),
                source=values.get("source", ""),
            )
        except (OSError, CTFMetadataReadError) as exc:
            _print(c(RED, f"  Unable to update CTF workspace: {exc}"))
            return
        _print(c(GREEN, f"  ✓ CTF metadata initialized: {metadata.challenge_name or '(unnamed)'}"))
        _print(c(GRAY, f"  Path: {workspace / 'ctf.json'}"))
        return

    if sub == "status":
        workspace = _workspace_path(ctx)
        try:
            metadata = load_ctf_metadata(workspace, strict=True)
        except CTFMetadataReadError as exc:
            _print(c(RED, f"  Unable to read CTF workspace: {exc}"))
            return
        _print(c(CYAN, "\n  " + format_ctf_status(metadata, workspace)))
        return

    if sub == "artifact":
        if not rest:
            _print(c(RED, "  Usage: /ctf artifact <path-or-note>"))
            return
        try:
            metadata = add_artifact(_workspace_path(ctx, create=True), rest)
        except (OSError, CTFMetadataReadError) as exc:
            _print(c(RED, f"  Unable to update CTF workspace: {exc}"))
            return
        _print(c(GREEN, f"  ✓ Recorded artifact ({len(metadata.artifacts)} total)"))
        return

    if sub == "remote":
        if not rest:
            _print(c(RED, "  Usage: /ctf remote <host:port-or-url>"))
            return
        try:
            metadata = add_remote_target(_workspace_path(ctx, create=True), rest)
        except (OSError, CTFMetadataReadError) as exc:
            _print(c(RED, f"  Unable to update CTF workspace: {exc}"))
            return
        _print(c(GREEN, f"  ✓ Recorded remote target ({len(metadata.remote_targets)} total)"))
        return

    if sub == "flag":
        if not rest:
            _print(c(RED, "  Usage: /ctf flag <candidate>"))
            return
        try:
            metadata = add_flag_candidate(_workspace_path(ctx, create=True), rest)
        except (OSError, CTFMetadataReadError) as exc:
            _print(c(RED, f"  Unable to update CTF workspace: {exc}"))
            return
        _print(c(GREEN, f"  ✓ Recorded flag candidate ({len(metadata.flag_candidates)} total)"))
        return

    if sub in {"solved", "confirm"}:
        try:
            metadata = confirm_flag_candidate(_workspace_path(ctx, create=True), rest)
        except (OSError, CTFMetadataReadError) as exc:
            _print(c(RED, f"  Unable to update CTF workspace: {exc}"))
            return
        if metadata.status != "solved":
            _print(c(RED, "  Usage: /ctf solved <confirmed-flag>"))
            return
        _print(c(GREEN, "  ✓ Marked CTF challenge as solved"))
        return

    if sub == "writeup":
        try:
            output = export_ctf_writeup(
                _workspace_path(ctx, create=True),
                messages=getattr(ctx.session, "messages", []),
                session_id=getattr(ctx.session, "session_id", ""),
            )
        except (OSError, CTFMetadataReadError) as exc:
            _print(c(RED, f"  Unable to update CTF workspace: {exc}"))
            return
        _print(c(GREEN, "  ✓ Wrote CTF writeup draft"))
        _print(c(GRAY, f"  Path: {output}"))
        return

    _print(c(YELLOW, f"  Unknown /ctf subcommand: {sub}"))
    _print(c(GRAY, _usage()))
