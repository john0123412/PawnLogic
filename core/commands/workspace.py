"""
Workspace, filesystem and project-init slash commands.

Migrated from main.py's _legacy_slash_dispatch in stage-1 step 5.

Commands in this module:
    /cd <path>             change working directory
    /file <path>           load a file's contents into the conversation
    /init_project [desc]   create .pawn_state.md in the current cwd
    /workspace [sub]       inspect / cleanup workspace (status | cleanup ...)

Module-private helpers:
    _STATE_TEMPLATE        Markdown template used by /init_project
    _init_project          create the state file in cwd
    _handle_workspace_cmd  /workspace sub-command dispatcher
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path

from core.logger import logger
from core.session import STATE_FILENAME
from tools.file_ops import _session_cwd, tool_read_file
from utils.ansi import c, BOLD, GRAY, CYAN, GREEN, YELLOW, RED

from core.commands import CommandContext, register
from core.commands._common import sink_print as _print


# ════════════════════════════════════════════════════════
# /init_project: state file template + helper
# ════════════════════════════════════════════════════════

_STATE_TEMPLATE = """\
# PawnLogic Project State
Created: {ts}
Directory: {cwd}

## 🎯 Project Goal
{goal}

## 📋 Current Tasks
- [ ] Initial planning

## ✅ Completed
(none yet)

## 📝 Architecture Notes
(agent will update this as work progresses)

## ⚠ Known Issues
(none)
"""


def _init_project(cwd: str, description: str) -> str:
    """Create .pawn_state.md in cwd and return a status path or cancellation."""
    state_path = Path(cwd) / STATE_FILENAME
    if state_path.exists():
        overwrite = input(
            c(YELLOW, "  .pawn_state.md already exists. Overwrite? [y/N]: ")
        ).strip().lower()
        if overwrite != "y":
            return "cancelled"

    content = _STATE_TEMPLATE.format(
        ts=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        cwd=cwd,
        goal=description or "(Not filled in. Edit .pawn_state.md directly.)",
    )
    state_path.write_text(content, encoding="utf-8")
    return str(state_path)


# ════════════════════════════════════════════════════════
# /workspace dispatcher
# ════════════════════════════════════════════════════════

def _handle_workspace_cmd(arg: str, arg2: str, session) -> None:
    """``/workspace`` sub-command dispatcher.

    Supported:
        /workspace                         - same as status
        /workspace status                  - overview
        /workspace cleanup                 - same as cleanup plan
        /workspace cleanup plan            - generate plan (read-only + backup)
        /workspace cleanup execute         - archive by plan + DB sync
        /workspace cleanup restore [path]  - restore from backup
    """
    from core import workspace_cleanup as wc

    sub = (arg or "status").strip().lower()
    sub2 = (arg2 or "").strip().lower()

    # ── status ─────────────────────────────────────────
    if sub == "status":
        info = wc.workspace_status()
        if not info.get("exists"):
            _print(c(RED, "  workspace directory does not exist"))
            return
        _print(c(BOLD, "\n  Workspace status:"))
        _print(f"  Path        : {c(CYAN, info['path'])}")
        _print(f"  Total size  : {c(GREEN, info['size_human'])}")
        _print(f"  Files       : {info['n_files']}")
        _print(f"  Directories : {info['n_dirs']} (session_*: {info['session_dirs']})")
        _print(f"  symlinks   : {info['n_symlinks']}")
        _print(c(GRAY, f"  DB sessions : {info['db_sessions']} (empty workspace_dir: {info['db_empty']})"))
        if info["last_backup"]:
            _print(c(GRAY, f"  Last backup : {info['last_backup']}"))
        _print()
        return

    # ── cleanup ────────────────────────────────────────
    if sub == "cleanup":
        action = sub2 or "plan"

        if action == "plan":
            _print(c(YELLOW, "  ▶ Phase 0: creating full backup..."))
            try:
                bak = wc.make_backup()
                _print(c(GREEN, f"    ✓ Backup: {bak.name} ({bak.stat().st_size // 1024} KB)"))
            except Exception as exc:
                _print(c(RED, f"    ✗ Backup failed: {exc}"))
                return

            _print(c(YELLOW, "  ▶ Phase 1: scan + classify (read-only)..."))
            rows, db = wc.scan()
            plan_path = wc.render_plan(rows, db)
            stats: dict[str, int] = {}
            for r in rows:
                stats[r["confidence"]] = stats.get(r["confidence"], 0) + 1
            _print(c(GREEN, f"    ✓ Plan: {plan_path}"))
            _print(c(BOLD, "\n  Scan results:"))
            for k in ("LOCKED", "SAFE", "MID", "HIGH", "SENSITIVE"):
                cnt = stats.get(k, 0)
                if cnt:
                    _print(f"    {wc._CONF_ICON[k]} {k:10} {cnt}")
            _print(c(GRAY, "\n  Review the plan, then run /workspace cleanup execute to archive suggested items."))
            _print(c(GRAY, "  Or edit the plan file first, especially to manually confirm SENSITIVE items."))
            return

        elif action == "execute":
            _print(c(YELLOW, "  ▶ Rescanning for the latest state..."))
            rows, db = wc.scan()
            plan_action_count = sum(1 for r in rows if r["action"] == "ARCHIVE")
            if plan_action_count == 0:
                _print(c(GREEN, "  ✓ Nothing to archive; workspace is already clean."))
                return
            _print(c(YELLOW, f"  ▶ Archiving {plan_action_count} items and backfilling DB workspace_dir..."))
            try:
                result = wc.execute_cleanup(rows, db)
                _print(c(GREEN, f"    ✓ Archived: {len(result['moved'])} items"))
                _print(c(GRAY,  f"      Skipped: {len(result['skipped'])} items"))
                _print(c(GREEN, f"    ✓ DB backfilled: {result['db_updated']} sessions"))
                _print(c(GRAY,  f"    Archive directory: {result['archive_root']}"))
                _print(c(GRAY,  f"    Manifest: {result['manifest']}"))
            except Exception as exc:
                logger.error("cleanup execute failed | exc={!r}", exc)
                _print(c(RED, f"    ✗ Failed: {exc}"))
            return

        elif action == "restore":
            backup_arg = parts[3].strip() if (parts := arg2.split(None, 1)) and len(parts) > 1 else ""
            backup_path = Path(backup_arg).expanduser() if backup_arg else None
            _print(c(YELLOW, "  ⚠ Restoring workspace from backup. Current contents will be renamed to _replaced_<ts>/."))
            try:
                from core.workspace_cleanup import restore_from_backup
                result = restore_from_backup(backup_path)
                if result["ok"]:
                    _print(c(GREEN, f"    ✓ Restored from: {result['restored_from']}"))
                    if result.get("old_workspace_renamed_to"):
                        _print(c(GRAY, f"      Previous workspace backup: {result['old_workspace_renamed_to']}"))
                else:
                    _print(c(RED, f"    ✗ {result.get('error')}"))
            except Exception as exc:
                logger.error("cleanup restore failed | exc={!r}", exc)
                _print(c(RED, f"    ✗ Failed: {exc}"))
            return

        else:
            _print(c(RED, f"  Unknown sub-command 'cleanup {action}'"))
            _print(c(GRAY, "  Available: plan / execute / restore"))
            return

    _print(c(RED, f"  Unknown sub-command 'workspace {sub}'"))
    _print(c(GRAY, "  Available: status | cleanup [plan|execute|restore]"))


# ════════════════════════════════════════════════════════
# Command handlers
# ════════════════════════════════════════════════════════

@register("/cd")
async def cmd_cd(ctx: CommandContext) -> None:
    session = ctx.session
    target = ctx.arg or "~"
    try:
        os.chdir(Path(target).expanduser())
        session.cwd = os.getcwd()
        _session_cwd[0] = session.cwd
        session._reset_system_prompt()
        state_exists = (Path(session.cwd) / STATE_FILENAME).exists()
        state_tag = c(CYAN, "  [State.md detected]") if state_exists else ""
        _print(c(GREEN, f"  ✓ cwd: {session.cwd}{state_tag}"))
    except Exception as e:
        _print(c(RED, f"  ✗ {e}"))


@register("/file")
async def cmd_file(ctx: CommandContext) -> None:
    session = ctx.session
    arg = ctx.arg
    if not arg:
        _print(c(RED, "  Usage: /file <path>"))
        return
    content = tool_read_file({"path": arg})
    session.messages.append({
        "role": "user",
        "content": f"[Loaded: {arg}]\n```\n{content}\n```",
    })
    session.messages.append({
        "role": "assistant",
        "content": f"Loaded `{arg}` ({len(content)} characters)",
    })
    _print(c(GREEN, f"  ✓ Loaded {arg}"))


@register("/init_project")
async def cmd_init_project(ctx: CommandContext) -> None:
    session = ctx.session
    desc = (ctx.arg + " " + ctx.arg2).strip()
    result = _init_project(session.cwd, desc)
    if result == "cancelled":
        _print(c(YELLOW, "  Cancelled"))
    else:
        session._reset_system_prompt()   # inject the new State.md immediately
        _print(c(GREEN, f"  ✓ Created {result}"))
        _print(c(GRAY,  "  State.md has been injected into the system prompt and persists after /clear."))
        _print(c(GRAY,  "  Tip: state the task directly; the agent will follow the spec-driven flow and commit automatically."))


@register("/workspace")
async def cmd_workspace(ctx: CommandContext) -> None:
    _handle_workspace_cmd(ctx.arg, ctx.arg2, ctx.session)
