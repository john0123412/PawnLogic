"""CLI argument and loading helpers for restart recovery."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any


def parse_cli_arguments(parser: argparse.ArgumentParser) -> Any:
    """Add restart options, parse the command line, and validate combinations."""
    parser.add_argument(
        "--continue",
        dest="continue_session",
        action="store_true",
        help="Load the newest interrupted/running/failed session as an editable draft.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        metavar="COMMAND",
        help="Use `resume <session>` to load a session without running it.",
    )
    parser.add_argument(
        "command_arg",
        nargs="?",
        metavar="SESSION",
        help="Session ID, name, or index used with `resume`.",
    )
    args = parser.parse_args()
    if args.command and args.command.lower() != "resume":
        parser.error(f"unknown command: {args.command}")
    if args.command == "resume" and not args.command_arg:
        parser.error("resume requires a session ID, name, or index")
    if args.command_arg and args.command != "resume":
        parser.error("a session argument is only valid with `resume`")
    if args.continue_session and args.command:
        parser.error("--continue cannot be combined with `resume`")
    if args.continue_session and (args.eval or args.session or args.json):
        parser.error(
            "--continue is interactive and cannot be combined with "
            "--eval, --session, or --json"
        )
    if args.command and (args.eval or args.session or args.json):
        parser.error(
            "`resume` is interactive and cannot be combined with "
            "--eval, --session, or --json"
        )
    return args


def load_cli_recovery(
    session: Any,
    *,
    latest: bool,
    query: str | None,
    latest_loader: Callable[[Any], str],
    query_loader: Callable[[Any, str], str],
    set_history: Callable[[list[dict[str, Any]]], None],
) -> tuple[str, str]:
    """Load a recoverable session and return its editable draft, if any."""
    result = (
        latest_loader(session)
        if latest
        else query_loader(session, query or "")
    )
    if not result.startswith("OK"):
        return result, ""
    set_history(session.messages)
    try:
        draft = next(iter(session.peek_queue(1)), "")
    except Exception:
        draft = ""
    return result, draft


def prepare_cli_recovery(
    session: Any,
    *,
    latest: bool,
    query: str | None,
    latest_loader: Callable[[Any], str],
    query_loader: Callable[[Any, str], str],
    set_history: Callable[[list[dict[str, Any]]], None],
) -> tuple[bool, str, str]:
    """Resolve an optional CLI recovery request without executing a Turn."""
    requested = bool(latest or query)
    if not requested:
        return False, "", ""
    result, draft = load_cli_recovery(
        session,
        latest=latest,
        query=query,
        latest_loader=latest_loader,
        query_loader=query_loader,
        set_history=set_history,
    )
    return True, result, draft


__all__ = ["load_cli_recovery", "parse_cli_arguments", "prepare_cli_recovery"]
