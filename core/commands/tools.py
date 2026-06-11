"""
Tool-status, sandbox, knowledge-base and skill-pack slash commands.

Migrated from main.py's _legacy_slash_dispatch in stage-1 step 6 (final).

Commands in this module:
    /knowledge [query]     search or list knowledge-base entries
    /webstatus             show web-fetch tool availability
    /browserstatus         show Scrapling browser tool availability
    /pwnenv                show CTF/Pwn toolchain integrity
    /docker [sub]          status / images / ps / pull / clean
    /worker [alias|auto]   pick the delegate-task worker model
    /skills [sub]          GSA archive: toc / packs / view / path
    /skillpack /sp [sub]   local skill-pack management:
                           list / rescan / sync / install / <name>

This is the last theme module: after this step the legacy dispatcher in
main.py is gone, dispatch() consults only the registry.
"""

from __future__ import annotations

from config import DYNAMIC_CONFIG, MODELS, validate_api_key
from core.memory import list_knowledge, search_knowledge
from core.state import state as _runtime_state
from tools.pwn_chain import tool_pwn_env
from tools.web_ops import web_tool_status
from utils.ansi import (
    c, BOLD, CYAN, GRAY, GREEN, MAGENTA, RED, YELLOW, Spinner,
)

from core.commands import CommandContext, register
from core.commands._common import sink_print as _print


# ════════════════════════════════════════════════════════
# /knowledge
# ════════════════════════════════════════════════════════

@register("/knowledge")
async def cmd_knowledge(ctx: CommandContext) -> None:
    query = (ctx.arg + " " + ctx.arg2).strip()
    if query:
        rows = search_knowledge(query, limit=10)
        _print(c(BOLD, f"\n  Knowledge search: '{query}' - {len(rows)} results:"))
    else:
        rows = list(list_knowledge(20))
        _print(c(BOLD, f"\n  Knowledge base (latest {len(rows)}):"))
    if not rows:
        _print(c(GRAY, "  (empty)"))
    else:
        for r in rows:
            _print(c(CYAN, f"  [{r['id']:3d}] ") + c(YELLOW, r["topic"]) +
                  c(GRAY, f"  {r['created_at'][:16]}  tags={r['tags'] or '-'}"))
            _print(c(GRAY, f"       {str(r['content'])[:100]}"))


# ════════════════════════════════════════════════════════
# Tool status
# ════════════════════════════════════════════════════════

@register("/webstatus")
async def cmd_webstatus(ctx: CommandContext) -> None:
    _print(c(BOLD, "\n  Web fetch tool status:"))
    _print(web_tool_status())


@register("/browserstatus")
async def cmd_browserstatus(ctx: CommandContext) -> None:
    try:
        from tools.browser_ops import browser_tool_status
        _print(c(BOLD, "\n  Scrapling browser tool status:"))
        _print(browser_tool_status())
    except ImportError:
        _print(c(RED, "  ✗ browser_ops module is not loaded"))


@register("/pwnenv")
async def cmd_pwnenv(ctx: CommandContext) -> None:
    _print(tool_pwn_env({}))


# ════════════════════════════════════════════════════════
# /docker
# ════════════════════════════════════════════════════════

@register("/docker")
async def cmd_docker(ctx: CommandContext) -> None:
    arg = ctx.arg
    arg2 = ctx.arg2
    from tools.docker_sandbox import (
        _get_docker_client, docker_status, _active_containers, DEFAULT_DOCKER_IMAGES,  # noqa: F401
    )
    sub = arg.lower().strip() if arg else "status"
    if sub == "status":
        _print(c(BOLD, "\n  Docker status:"))
        _print(docker_status())
        _print(c(GRAY, f"\n  Available image aliases: {', '.join(DEFAULT_DOCKER_IMAGES.keys())}"))
        _print(c(GRAY, "  Usage: /docker status | /docker images | /docker ps | /docker containers"))
    elif sub == "images":
        client = _get_docker_client()
        if not client:
            _print(c(RED, "  ✗ Docker is unavailable"))
        else:
            images = client.images.list()
            _print(c(BOLD, f"\n  Local images ({len(images)}):"))
            for img in images[:20]:
                tags = ", ".join(img.tags) if img.tags else "<none>"
                size_mb = img.attrs.get("Size", 0) / (1024 * 1024)
                _print(f"  {c(CYAN, tags):40} {c(GRAY, f'{size_mb:.0f}MB')}")
    elif sub in ("ps", "containers"):
        client = _get_docker_client()
        if not client:
            _print(c(RED, "  ✗ Docker is unavailable"))
        else:
            containers = client.containers.list(all=True)
            pawn_containers = [ct for ct in containers if ct.labels.get("pawn") == "true"]
            _print(c(BOLD, f"\n  PawnLogic containers ({len(pawn_containers)}):"))
            for ct in pawn_containers:
                name = ct.labels.get("pawn_name", ct.name)
                status_color = GREEN if ct.status == "running" else RED
                _print(f"  {c(CYAN, name):20} {c(status_color, ct.status):12} {c(GRAY, ct.id[:12])}")
            if not pawn_containers:
                _print(c(GRAY, "  (no PawnLogic containers)"))
    elif sub == "pull":
        image = arg2.strip() if arg2 else ""
        if not image:
            _print(c(RED, "  Usage: /docker pull <image name or alias>"))
        else:
            from tools.docker_sandbox import _resolve_image
            resolved = _resolve_image(image)
            client = _get_docker_client()
            if not client:
                _print(c(RED, "  ✗ Docker is unavailable"))
            else:
                _print(c(YELLOW, f"  📥 Pulling {resolved} ..."))
                try:
                    client.images.pull(resolved)
                    _print(c(GREEN, f"  ✓ Pulled {resolved}"))
                except Exception as e:
                    _print(c(RED, f"  ✗ Pull failed: {e}"))
    elif sub == "clean":
        from tools.docker_sandbox import docker_prune_resources
        _print(c(YELLOW, "  🧹 Cleaning Docker resources..."))
        result = docker_prune_resources()
        col = GREEN if result.startswith("✓") else RED
        _print(c(col, f"  {result}"))
    else:
        _print(c(GRAY, "  Usage: /docker status | /docker images | /docker ps | /docker pull <image> | /docker clean"))


# ════════════════════════════════════════════════════════
# /worker
# ════════════════════════════════════════════════════════

@register("/worker")
async def cmd_worker(ctx: CommandContext) -> None:
    session = ctx.session
    arg = ctx.arg
    from tools.delegate_tool import _WORKER_MODEL_CANDIDATES
    target = arg.lower().strip() if arg else ""

    if not target:
        # No argument: show an interactive-style menu.
        current = DYNAMIC_CONFIG.get("preferred_worker", "auto")
        _print(c(BOLD, "\n  Subtask worker models (used by delegate_task):"))
        for i, alias in enumerate(_WORKER_MODEL_CANDIDATES):
            if alias not in MODELS:
                continue
            ok, env = validate_api_key(alias)
            ktag = c(GREEN, "[key✓]") if ok else c(RED, "[key✗]")
            desc = MODELS[alias].get("desc", "")
            tick = c(GREEN, " ◀ current") if alias == current else ""
            _print(
                c(GRAY, f"  [{i+1}] ")
                + c(CYAN, f"{alias:16}")
                + f" {desc:30} {ktag}{tick}"
            )
        # auto option
        auto_tick = c(GREEN, " ◀ current") if current == "auto" else ""
        _print(
            c(GRAY, "  [A] ")
            + c(YELLOW, f"{'auto':16}")
            + f" {'Automatic routing by priority':30} {auto_tick}"
        )
        _print(c(GRAY, "\n  Usage: /worker <alias> or /worker auto"))
        return

    if target == "auto":
        DYNAMIC_CONFIG["preferred_worker"] = "auto"
        session._reset_system_prompt()
        _print(c(GREEN, "  ✓ Worker restored to automatic routing mode"))
        return

    if target in MODELS:
        ok, env = validate_api_key(target)
        if not ok:
            _print(c(YELLOW, f"  ⚠ Switched to {target}, but {env} is not set. Configure it with /setkey."))
        DYNAMIC_CONFIG["preferred_worker"] = target
        session._reset_system_prompt()
        _print(c(GREEN, f"  ✓ Worker locked to {c(CYAN, target)}; subtasks will force this model."))
        return

    # Try numeric index matching.
    try:
        idx = int(target) - 1
        if 0 <= idx < len(_WORKER_MODEL_CANDIDATES):
            alias = _WORKER_MODEL_CANDIDATES[idx]
            DYNAMIC_CONFIG["preferred_worker"] = alias
            session._reset_system_prompt()
            _print(c(GREEN, f"  ✓ Worker locked to {c(CYAN, alias)}"))
        else:
            _print(c(RED, "  ✗ Selection out of range"))
    except ValueError:
        _print(c(RED, f"  ✗ Unknown model '{target}'. Use /worker to list candidates."))


# ════════════════════════════════════════════════════════
# /skills
# ════════════════════════════════════════════════════════

@register("/skills")
async def cmd_skills(ctx: CommandContext) -> None:
    arg = ctx.arg
    arg2 = ctx.arg2
    from config import GLOBAL_SKILLS_PATH
    sub = arg.lower().strip() if arg else "toc"

    if sub == "path":
        _print(c(GRAY, f"  {GLOBAL_SKILLS_PATH}"))
        return

    if sub == "packs":
        from core.session import _skill_scanner
        from config import SKILLS_DIR
        packs = _skill_scanner.scan_all()
        if not packs:
            _print(c(GRAY,
                f"  No skill packs found under skills/.\n"
                f"  Path: {SKILLS_DIR}\n"
                "  Create one with: mkdir -p skills/my_skill && echo '# My Skill' > skills/my_skill/skill.md"
            ))
        else:
            _print(c(BOLD, f"\n  📦 Local skill packs ({len(packs)})"))
            _print(c(GRAY,  f"  Path: {SKILLS_DIR}\n"))
            _print(_skill_scanner.format_list())
            _print(c(GRAY, "\n  /skillpack rescan -> rescan  |  /skillpack <name> -> show details"))
        return

    if sub == "view":
        if not GLOBAL_SKILLS_PATH.exists():
            _print(c(GRAY, "  global_skills.md has not been created. The agent can generate it after tasks, or use /memo."))
            return
        lines_all = GLOBAL_SKILLS_PATH.read_text(encoding="utf-8").splitlines()
        total = len(lines_all)
        page_size = 40
        try:
            page = max(0, int(arg2) - 1) if arg2 and arg2.isdigit() else 0
        except Exception:
            page = 0
        start = page * page_size
        end = min(start + page_size, total)
        _print(c(BOLD, f"\n  global_skills.md  ({total} lines, showing {start+1}-{end})\n"))
        for line in lines_all[start:end]:
            if line.startswith("# "):
                _print(c(CYAN, line))
            elif line.startswith("## "):
                _print(c(YELLOW, line))
            else:
                _print(f"  {line}")
        if end < total:
            rem = (total - end + page_size - 1) // page_size
            _print(c(GRAY, f"\n  {rem} pages remain. Continue with /skills view <page>."))
        return

    # Default: table of contents.
    try:
        from core.gsa import load_toc
        toc = load_toc(max_lines=120)
    except ImportError:
        if not GLOBAL_SKILLS_PATH.exists():
            toc = "(not created yet)"
        else:
            toc = "\n".join(
                line for line in GLOBAL_SKILLS_PATH.read_text(encoding="utf-8").splitlines()[:80]
                if line.startswith("#")
            )
    if not GLOBAL_SKILLS_PATH.exists():
        _print(c(GRAY,
            f"  global_skills.md has not been created.\n"
            f"  Path: {GLOBAL_SKILLS_PATH}\n"
            "  The agent can create it after tasks, or you can archive manually with /memo."
        ))
    else:
        _print(c(BOLD, "\n  📚 Global Skills Archive - Table of Contents"))
        _print(c(GRAY,  f"  Path: {GLOBAL_SKILLS_PATH}\n"))
        for line in toc.splitlines():
            if line.startswith("# "):
                _print(c(CYAN + BOLD, f"  {line}"))
            elif line.startswith("## "):
                _print(c(YELLOW, f"    {line}"))
            else:
                _print(c(GRAY, f"  {line}"))
        _print(c(GRAY, "\n  /skills view -> full content  |  /skills packs -> local packs  |  /memo -> manual archive"))


# ════════════════════════════════════════════════════════
# /skillpack /sp
# ════════════════════════════════════════════════════════

@register("/skillpack", "/sp")
async def cmd_skillpack(ctx: CommandContext) -> None:
    arg = ctx.arg
    arg2 = ctx.arg2
    from config import SKILLS_DIR
    from core.session import _skill_scanner
    sub = arg.lower().strip() if arg else "list"

    if sub == "rescan":
        _skill_scanner.invalidate_cache()
        packs = _skill_scanner.scan_all()
        _print(c(GREEN, f"  ✓ Rescanned skills/ and found {len(packs)} skill packs"))
        if packs:
            _print(c(BOLD, "\n  Local skill packs:"))
            _print(_skill_scanner.format_list())
        return

    if sub == "sync":
        if _runtime_state.user_mode:
            with Spinner("Syncing skill packs"):
                results = _skill_scanner.sync_packs()
        else:
            _print(c(CYAN, "  🔄 Syncing all git-backed skill packs..."))
            results = _skill_scanner.sync_packs()
        if not results:
            _print(c(GRAY, "  No git-backed skill pack directories found"))
            return
        ok_count = sum(1 for r in results if r["status"] == "ok")
        err_count = len(results) - ok_count
        _print(c(GREEN, f"  ✓ Sync complete: {ok_count} succeeded, {err_count} failed"))
        for r in results:
            tag = c(GREEN, "✓") if r["status"] == "ok" else c(RED, "✗")
            detail = ""
            if not _runtime_state.user_mode:
                detail = c(GRAY, f"  {r['detail']}")
            _print(f"    {tag} {r['name']}{detail}")
        if err_count > 0:
            _print(c(GRAY, "  Tip: enter the failed directory and run git pull for details"))
        return

    if sub == "install":
        repo_url = arg2.strip() if arg2 else ""
        if not repo_url:
            _print(c(RED, "  Usage: /sp install <repo_url>"))
            _print(c(GRAY, "  Example: /sp install https://github.com/user/exploit-pack.git"))
            return
        if _runtime_state.user_mode:
            with Spinner("Installing skill pack"):
                result = _skill_scanner.install_pack(repo_url)
        else:
            _print(c(CYAN, f"  📥 Cloning {repo_url} ..."))
            result = _skill_scanner.install_pack(repo_url)
        if result["status"] == "ok":
            _print(c(GREEN, f"  ✓ {result['detail']}"))
            packs = _skill_scanner.scan_all()
            installed = [p for p in packs if result["name"] in p.get("_path", "").name]
            if installed:
                _print(c(BOLD, "\n  Newly installed skill packs:"))
                for p in installed:
                    name = p.get("name", "?")
                    desc = p.get("description", "")
                    scripts = p.get("scripts", [])
                    _print(c(GREEN, f"    📦 {name}"))
                    if desc:
                        _print(c(GRAY, f"       {desc[:60]}"))
                    if scripts:
                        _print(c(GRAY, f"       scripts: {', '.join(scripts)}"))
        else:
            _print(c(RED, f"  ✗ Install failed: {result['detail']}"))
        return

    if sub == "list" or sub == "":
        packs = _skill_scanner.scan_all()
        if not packs:
            _print(c(GRAY,
                f"  No skill packs found under skills/.\n"
                f"  Path: {SKILLS_DIR}\n"
                "  Create one with: mkdir -p skills/my_skill && echo '# My Skill' > skills/my_skill/skill.md"
            ))
        else:
            _print(c(BOLD, f"\n  📦 Local skill packs ({len(packs)})"))
            _print(c(GRAY,  f"  Path: {SKILLS_DIR}\n"))
            _print(_skill_scanner.format_list())
            _print(c(GRAY,
                "\n  /sp rescan -> rescan  |  /sp sync -> sync updates  |"
                "  /sp install <url> -> install new pack  |  /sp <name> -> show details"
            ))
        return

    # Show details by name.
    packs = _skill_scanner.scan_all()
    matched = [p for p in packs if sub in p.get("name", "").lower()
               or sub in p.get("_path", "").name.lower()]
    if not matched:
        _print(c(RED, f"  ✗ No skill pack named '{sub}' was found"))
        _print(c(GRAY, "  Use /skillpack to list all available skill packs"))
        return
    for pack in matched:
        name = pack.get("name", "?")
        desc = pack.get("description", "")
        ver = pack.get("version", "1.0")
        kw = pack.get("keywords", [])
        tr = pack.get("triggers", [])
        scripts = pack.get("scripts", [])
        guide = pack.get("guide", "")
        pack_path = pack.get("_path", "")

        _print(c(BOLD, f"\n  📦 {name} v{ver}"))
        if desc:
            _print(f"  {desc}")
        _print(c(GRAY, f"  Path: {pack_path}"))
        if kw:
            _print(c(CYAN, f"  Keywords: {', '.join(kw)}"))
        if tr:
            _print(c(CYAN, f"  Triggers: {', '.join(tr)}"))
        if guide:
            _print(c(GREEN, f"  Guide: {pack_path / guide}"))
            _print(c(GRAY,  f"    → read_file(path='{pack_path / guide}')"))
        if scripts:
            _print(c(GREEN, f"  Scripts: {', '.join(scripts)}"))
            _print(c(GRAY,  "    → Prefer running scripts over ad-hoc code"))


# Reference MAGENTA so that ruff doesn't flag the import as unused.
# (MAGENTA is exported by utils.ansi alongside other colors used in this
# module; importing them as a group keeps the import tidy.)
_ = MAGENTA
