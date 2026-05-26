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
- [ ] 初始规划

## ✅ Completed
(none yet)

## 📝 Architecture Notes
(agent will update this as work progresses)

## ⚠ Known Issues
(none)
"""


def _init_project(cwd: str, description: str) -> str:
    """在 cwd 生成 .pawn_state.md，返回成功/失败消息。"""
    state_path = Path(cwd) / STATE_FILENAME
    if state_path.exists():
        overwrite = input(
            c(YELLOW, "  .pawn_state.md 已存在，覆盖? [y/N]: ")
        ).strip().lower()
        if overwrite != "y":
            return "已取消"

    content = _STATE_TEMPLATE.format(
        ts=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        cwd=cwd,
        goal=description or "(未填写，请直接编辑 .pawn_state.md)",
    )
    state_path.write_text(content, encoding="utf-8")
    return str(state_path)


# ════════════════════════════════════════════════════════
# /workspace dispatcher
# ════════════════════════════════════════════════════════

def _handle_workspace_cmd(arg: str, arg2: str, session) -> None:
    """``/workspace`` 子命令分派器。

    支持：
        /workspace                         — 等价 status
        /workspace status                  — 概览
        /workspace cleanup                 — 等价 cleanup plan
        /workspace cleanup plan            — 生成清理清单（只读 + 备份）
        /workspace cleanup execute         — 按清单归档 + DB 同步
        /workspace cleanup restore [path]  — 从备份回滚
    """
    from core import workspace_cleanup as wc

    sub = (arg or "status").strip().lower()
    sub2 = (arg2 or "").strip().lower()

    # ── status ─────────────────────────────────────────
    if sub == "status":
        info = wc.workspace_status()
        if not info.get("exists"):
            print(c(RED, "  workspace 目录不存在"))
            return
        print(c(BOLD, "\n  Workspace 状态:"))
        print(f"  路径        : {c(CYAN, info['path'])}")
        print(f"  总大小      : {c(GREEN, info['size_human'])}")
        print(f"  文件数      : {info['n_files']}")
        print(f"  子目录      : {info['n_dirs']}（其中 session_*: {info['session_dirs']}）")
        print(f"  symlinks   : {info['n_symlinks']}")
        print(c(GRAY, f"  DB 会话数  : {info['db_sessions']}（workspace_dir 为空: {info['db_empty']}）"))
        if info["last_backup"]:
            print(c(GRAY, f"  最近备份   : {info['last_backup']}"))
        print()
        return

    # ── cleanup ────────────────────────────────────────
    if sub == "cleanup":
        action = sub2 or "plan"

        if action == "plan":
            print(c(YELLOW, "  ▶ Phase 0: 生成全量备份..."))
            try:
                bak = wc.make_backup()
                print(c(GREEN, f"    ✓ 备份: {bak.name} ({bak.stat().st_size // 1024} KB)"))
            except Exception as exc:
                print(c(RED, f"    ✗ 备份失败: {exc}"))
                return

            print(c(YELLOW, "  ▶ Phase 1: 扫描 + 分类 (只读)..."))
            rows, db = wc.scan()
            plan_path = wc.render_plan(rows, db)
            stats: dict[str, int] = {}
            for r in rows:
                stats[r["confidence"]] = stats.get(r["confidence"], 0) + 1
            print(c(GREEN, f"    ✓ 清单: {plan_path}"))
            print(c(BOLD, "\n  扫描结果:"))
            for k in ("LOCKED", "SAFE", "MID", "HIGH", "SENSITIVE"):
                cnt = stats.get(k, 0)
                if cnt:
                    print(f"    {wc._CONF_ICON[k]} {k:10} {cnt}")
            print(c(GRAY, "\n  审阅清单后，使用 /workspace cleanup execute 按建议归档"))
            print(c(GRAY, "  或编辑清单文件后再 execute（人工确认 SENSITIVE 项）"))
            return

        elif action == "execute":
            print(c(YELLOW, "  ▶ 重新扫描以获取最新状态..."))
            rows, db = wc.scan()
            plan_action_count = sum(1 for r in rows if r["action"] == "ARCHIVE")
            if plan_action_count == 0:
                print(c(GREEN, "  ✓ 没有可归档项，workspace 已经整洁"))
                return
            print(c(YELLOW, f"  ▶ 即将归档 {plan_action_count} 项 + DB workspace_dir 补写..."))
            try:
                result = wc.execute_cleanup(rows, db)
                print(c(GREEN, f"    ✓ 归档: {len(result['moved'])} 项"))
                print(c(GRAY,  f"      跳过: {len(result['skipped'])} 项"))
                print(c(GREEN, f"    ✓ DB 补写: {result['db_updated']} 条会话"))
                print(c(GRAY,  f"    归档目录: {result['archive_root']}"))
                print(c(GRAY,  f"    Manifest: {result['manifest']}"))
            except Exception as exc:
                logger.error("cleanup execute failed | exc={!r}", exc)
                print(c(RED, f"    ✗ 失败: {exc}"))
            return

        elif action == "restore":
            backup_arg = parts[3].strip() if (parts := arg2.split(None, 1)) and len(parts) > 1 else ""
            backup_path = Path(backup_arg).expanduser() if backup_arg else None
            print(c(YELLOW, "  ⚠ 即将从备份回滚 workspace（当前内容会被重命名为 _replaced_<ts>/）"))
            try:
                from core.workspace_cleanup import restore_from_backup
                result = restore_from_backup(backup_path)
                if result["ok"]:
                    print(c(GREEN, f"    ✓ 已回滚: {result['restored_from']}"))
                    if result.get("old_workspace_renamed_to"):
                        print(c(GRAY, f"      旧 workspace 备份: {result['old_workspace_renamed_to']}"))
                else:
                    print(c(RED, f"    ✗ {result.get('error')}"))
            except Exception as exc:
                logger.error("cleanup restore failed | exc={!r}", exc)
                print(c(RED, f"    ✗ 失败: {exc}"))
            return

        else:
            print(c(RED, f"  未知子命令 'cleanup {action}'"))
            print(c(GRAY, "  可用: plan / execute / restore"))
            return

    print(c(RED, f"  未知子命令 'workspace {sub}'"))
    print(c(GRAY, "  可用: status | cleanup [plan|execute|restore]"))


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
        state_tag = c(CYAN, "  [State.md 已检测]") if state_exists else ""
        print(c(GREEN, f"  ✓ cwd: {session.cwd}{state_tag}"))
    except Exception as e:
        print(c(RED, f"  ✗ {e}"))


@register("/file")
async def cmd_file(ctx: CommandContext) -> None:
    session = ctx.session
    arg = ctx.arg
    if not arg:
        print(c(RED, "  用法: /file <path>"))
        return
    content = tool_read_file({"path": arg})
    session.messages.append({
        "role": "user",
        "content": f"[Loaded: {arg}]\n```\n{content}\n```",
    })
    session.messages.append({
        "role": "assistant",
        "content": f"已载入 `{arg}` ({len(content)} 字符)",
    })
    print(c(GREEN, f"  ✓ 已载入 {arg}"))


@register("/init_project")
async def cmd_init_project(ctx: CommandContext) -> None:
    session = ctx.session
    desc = (ctx.arg + " " + ctx.arg2).strip()
    result = _init_project(session.cwd, desc)
    if result == "已取消":
        print(c(YELLOW, "  已取消"))
    else:
        session._reset_system_prompt()   # 立即注入新的 State.md
        print(c(GREEN, f"  ✓ 已创建 {result}"))
        print(c(GRAY,  "  State.md 已注入 System Prompt，/clear 后也会保持。"))
        print(c(GRAY,  "  提示：直接说出任务，Agent 将遵循规格驱动格式执行并自动提交 git。"))


@register("/workspace")
async def cmd_workspace(ctx: CommandContext) -> None:
    _handle_workspace_cmd(ctx.arg, ctx.arg2, ctx.session)
