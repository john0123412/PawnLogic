"""
Tool-status, sandbox, knowledge-base and skill-pack slash commands.

Migrated from main.py's _legacy_slash_dispatch in stage-1 step 6 (final).

Commands in this module:
    /knowledge [query]     search or list knowledge-base entries
    /webstatus             show web-fetch tool availability
    /browserstatus         show Scrapling browser tool availability
    /pwnenv                show CTF/Pwn toolchain integrity
    /docker [sub]          status / images / ps / pull / clean
    /agent [sub]           delegated-agent policy and run guidance
    /worker [alias|auto]   pick the delegate-task worker model
    /skills [sub]          GSA archive: toc / packs / view / path
    /skillpack /sp [sub]   local skill-pack management:
                           list / rescan / sync / install / <name>

This is the last theme module: after this step the legacy dispatcher in
main.py is gone, dispatch() consults only the registry.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, InvalidOperation
import json

from config import MODELS
from core.memory import list_knowledge, search_knowledge
from core.state import (
    state as _runtime_state,
    get_dynamic_config_value,
    set_dynamic_config_value,
)
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
# /agent and /worker
# ════════════════════════════════════════════════════════

def _delegation_policy_store():
    """Build a policy store against the live Runtime Home."""
    import config.paths as path_config
    from core.delegation import DelegationPolicyStore

    return DelegationPolicyStore(path_config.PAWNLOGIC_HOME)


def _visible_worker_models() -> dict:
    """Use the same live provider/key visibility contract as /model."""
    from core.commands.provider import _visible_models

    return _visible_models()


def _policy_models(policy, field: str) -> tuple[str, ...]:
    return tuple(getattr(policy, field, ()) or ())


def _format_policy_cost(value) -> str:
    if value is None:
        return "off"
    return format(value, "g")


def _show_agent_policy(policy) -> None:
    allowed = _policy_models(policy, "allowed_models")
    denied = _policy_models(policy, "denied_models")
    preferred = getattr(policy, "preferred_model", None) or "auto"
    _print(c(BOLD, "\n  Delegated-agent model policy:"))
    _print(f"  default mode    : {getattr(policy, 'default_mode', 'auto')}")
    _print(f"  preferred model : {preferred}")
    _print(f"  allowed models  : {', '.join(allowed) if allowed else '(all visible models)'}")
    _print(f"  denied models   : {', '.join(denied) if denied else '(none)'}")
    _print(f"  max cost        : {_format_policy_cost(getattr(policy, 'max_cost', None))}")
    _print(f"  max concurrency : {getattr(policy, 'max_concurrency', 1)}")


def _parse_nonnegative_cost(raw: str) -> float | None:
    if raw.lower() == "off":
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("cost must be a nonnegative number or 'off'") from exc
    if not value.is_finite() or value < 0:
        raise ValueError("cost must be a nonnegative number or 'off'")
    return float(value)


def _agent_usage() -> None:
    _print(c(GRAY, "  Usage:"))
    _print(c(GRAY, "    /agent policy show"))
    _print(c(GRAY, "    /agent policy model allow <alias>"))
    _print(c(GRAY, "    /agent policy model deny <alias>"))
    _print(c(GRAY, "    /agent policy default auto|same|fast|reasoning"))
    _print(c(GRAY, "    /agent policy max-cost <nonnegative|off>"))
    _print(c(GRAY, "    /agent policy max-concurrency 1|2"))
    _print(c(GRAY, "    /agent run <role> <objective>"))


def _save_agent_policy(store, policy, message: str) -> None:
    store.save(policy)
    _print(c(GREEN, f"  ✓ {message}"))


async def _cmd_agent_policy(raw: str) -> None:
    parts = raw.split()
    if not parts:
        _agent_usage()
        return

    action = parts[0].lower()
    store = _delegation_policy_store()
    policy = store.load()

    if action == "show" and len(parts) == 1:
        _show_agent_policy(policy)
        return

    if action == "model" and len(parts) == 3:
        decision = parts[1].lower()
        alias = parts[2]
        if decision not in {"allow", "deny"}:
            _agent_usage()
            return
        if alias not in MODELS:
            _print(c(RED, f"  ✗ Unknown model alias '{alias}'."))
            return
        if alias not in _visible_worker_models():
            _print(c(
                RED,
                f"  ✗ Model '{alias}' is not active and configured; "
                "it is unavailable in /model.",
            ))
            return

        allowed = list(_policy_models(policy, "allowed_models"))
        denied = list(_policy_models(policy, "denied_models"))
        if decision == "allow":
            if alias not in allowed:
                allowed.append(alias)
            denied = [item for item in denied if item != alias]
        else:
            if alias not in denied:
                denied.append(alias)
            allowed = [item for item in allowed if item != alias]
        preferred = getattr(policy, "preferred_model", None)
        if decision == "deny" and preferred == alias:
            preferred = None
        updated = replace(
            policy,
            allowed_models=tuple(allowed),
            denied_models=tuple(denied),
            preferred_model=preferred,
        )
        status = "allowed" if decision == "allow" else "denied"
        _save_agent_policy(store, updated, f"Model '{alias}' is now {status}.")
        return

    if action == "default" and len(parts) == 2:
        mode = parts[1].lower()
        if mode not in {"auto", "same", "fast", "reasoning"}:
            _print(c(RED, "  ✗ Default mode must be auto, same, fast, or reasoning."))
            return
        _save_agent_policy(
            store,
            replace(policy, default_mode=mode),
            f"Default delegated-agent mode set to '{mode}'.",
        )
        return

    if action == "max-cost" and len(parts) == 2:
        try:
            max_cost = _parse_nonnegative_cost(parts[1])
        except ValueError as exc:
            _print(c(RED, f"  ✗ {exc}"))
            return
        _save_agent_policy(
            store,
            replace(policy, max_cost=max_cost),
            f"Maximum delegated-agent cost set to '{_format_policy_cost(max_cost)}'.",
        )
        return

    if action == "max-concurrency" and len(parts) == 2:
        if parts[1] not in {"1", "2"}:
            _print(c(RED, "  ✗ Maximum concurrency must be 1 or 2."))
            return
        value = int(parts[1])
        _save_agent_policy(
            store,
            replace(policy, max_concurrency=value),
            f"Maximum delegated-agent concurrency set to {value}.",
        )
        return

    _agent_usage()


@register("/agent")
async def cmd_agent(ctx: CommandContext) -> None:
    action = ctx.arg.lower().strip() if ctx.arg else ""
    raw = ctx.arg2.strip() if ctx.arg2 else ""
    if action == "policy":
        await _cmd_agent_policy(raw)
        return
    if action == "run":
        run_parts = raw.split(None, 1)
        if len(run_parts) != 2 or not all(part.strip() for part in run_parts):
            _print(c(RED, "  Usage: /agent run <role> <objective>"))
            return
        role, objective = run_parts
        request = {
            "task_description": objective,
            "role": role,
        }
        _print(c(BOLD, "\n  Delegated-agent request template:"))
        _print("  Ask the current agent to call delegate_task with:")
        _print(f"  {json.dumps(request, ensure_ascii=True)}")
        _print(c(GRAY, "  This command prepares guidance only; it does not call a provider."))
        return
    _agent_usage()


@register("/worker")
async def cmd_worker(ctx: CommandContext) -> None:
    session = ctx.session
    arg = ctx.arg
    target = arg.lower().strip() if arg else ""
    visible_models = _visible_worker_models()
    visible_aliases = list(visible_models)

    if not target:
        # No argument: show an interactive-style menu.
        policy = _delegation_policy_store().load()
        current = (
            getattr(policy, "preferred_model", None)
            or get_dynamic_config_value("preferred_worker", "auto")
        )
        _print(c(BOLD, "\n  Subtask worker models (used by delegate_task):"))
        for i, alias in enumerate(visible_aliases):
            desc = visible_models[alias].get("desc", "")
            tick = c(GREEN, " ◀ current") if alias == current else ""
            _print(
                c(GRAY, f"  [{i+1}] ")
                + c(CYAN, f"{alias:16}")
                + f" {desc:30}{tick}"
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
        store = _delegation_policy_store()
        policy = store.load()
        store.save(replace(policy, preferred_model=None))
        set_dynamic_config_value("preferred_worker", "auto")
        session._reset_system_prompt()
        _print(c(GREEN, "  ✓ Worker restored to automatic routing mode"))
        return

    # Try numeric index matching.
    alias = target
    try:
        idx = int(target) - 1
        if not 0 <= idx < len(visible_aliases):
            _print(c(RED, "  ✗ Selection out of range"))
            return
        alias = visible_aliases[idx]
    except ValueError:
        pass

    if alias not in MODELS:
        _print(c(RED, f"  ✗ Unknown model '{target}'. Use /worker to list candidates."))
        return
    if alias not in visible_models:
        _print(c(
            RED,
            f"  ✗ Model '{alias}' is not active and configured; "
            "it is unavailable in /model.",
        ))
        return

    store = _delegation_policy_store()
    policy = store.load()
    denied = _policy_models(policy, "denied_models")
    allowed = _policy_models(policy, "allowed_models")
    if alias in denied:
        _print(c(
            RED,
            f"  ✗ Model '{alias}' is denied by delegated-agent policy.",
        ))
        return
    if allowed and alias not in allowed:
        _print(c(
            RED,
            f"  ✗ Model '{alias}' is not in the delegated-agent allowlist.",
        ))
        return
    store.save(replace(policy, preferred_model=alias))
    set_dynamic_config_value("preferred_worker", alias)
    session._reset_system_prompt()
    _print(c(
        GREEN,
        f"  ✓ Worker locked to {c(CYAN, alias)}; subtasks will prefer this model.",
    ))


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

    if sub in ("manage", "toggle", "tui"):
        from core.session import _skill_scanner
        from core.skill_tui import run_skill_tui
        saved = run_skill_tui(_skill_scanner)
        if saved:
            _print(c(GREEN, "  ✓ Skill pack selection saved"))
        else:
            _print(c(GRAY, "  Cancelled — no changes saved"))
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
        _print(c(GRAY, "\n  /skills manage -> TUI toggle  |  /skills view -> full content  |  /skills packs -> local packs  |  /memo -> manual archive"))


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
        packs = _skill_scanner.scan_all(include_disabled=True)
        enabled_count = sum(1 for p in packs if p.get("_enabled", True))
        _print(c(GREEN, f"  ✓ Rescanned skills/ and found {len(packs)} skill packs ({enabled_count} enabled)"))
        if packs:
            _print(c(BOLD, "\n  Local skill packs:"))
            _print(_skill_scanner.format_list(include_disabled=True))
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

    if sub == "enable":
        target = (arg2 or "").strip()
        if not target:
            _print(c(RED, "  Usage: /sp enable <name>  |  /sp enable all"))
            return
        if target == "all":
            count = _skill_scanner.enable_all()
            _print(c(GREEN, f"  ✓ Enabled all {count} skill packs"))
            return
        # Find pack by name (case-insensitive partial match).
        all_packs = _skill_scanner.scan_all(include_disabled=True)
        matched = [p for p in all_packs if target.lower() in p.get("name", "").lower()
                   or target.lower() in p.get("_path", "").name.lower()]
        if not matched:
            _print(c(RED, f"  ✗ No skill pack named '{target}' found"))
            return
        for p in matched:
            name = p.get("name", "?")
            if _skill_scanner.enable(name):
                _print(c(GREEN, f"  ✓ Enabled: {name}"))
            else:
                _print(c(GRAY, f"  Already enabled: {name}"))
        return

    if sub == "disable":
        target = (arg2 or "").strip()
        if not target:
            _print(c(RED, "  Usage: /sp disable <name>  |  /sp disable all"))
            return
        if target == "all":
            count = _skill_scanner.disable_all()
            _print(c(GREEN, f"  ✓ Disabled all {count} skill packs"))
            return
        all_packs = _skill_scanner.scan_all(include_disabled=True)
        matched = [p for p in all_packs if target.lower() in p.get("name", "").lower()
                   or target.lower() in p.get("_path", "").name.lower()]
        if not matched:
            _print(c(RED, f"  ✗ No skill pack named '{target}' found"))
            return
        for p in matched:
            name = p.get("name", "?")
            if _skill_scanner.disable(name):
                _print(c(GREEN, f"  ✓ Disabled: {name}"))
            else:
                _print(c(GRAY, f"  Already disabled: {name}"))
        return

    if sub == "status":
        packs = _skill_scanner.scan_all(include_disabled=True)
        if not packs:
            _print(c(GRAY, "  No skill packs found"))
            return
        enabled = [p for p in packs if p.get("_enabled", True)]
        disabled = [p for p in packs if not p.get("_enabled", True)]
        _print(c(BOLD, f"\n  Skill Pack Status ({len(enabled)} enabled, {len(disabled)} disabled)"))
        _print(c(GRAY,  f"  Path: {SKILLS_DIR}\n"))
        _print(_skill_scanner.format_list(include_disabled=True))
        _print(c(GRAY,
            "\n  /sp enable <name>   -> enable a pack"
            "\n  /sp disable <name>  -> disable a pack"
            "\n  /sp enable all      -> enable all"
            "\n  /sp disable all     -> disable all"
        ))
        return

    if sub == "list" or sub == "":
        packs = _skill_scanner.scan_all()
        all_packs = _skill_scanner.scan_all(include_disabled=True)
        if not all_packs:
            _print(c(GRAY,
                f"  No skill packs found under skills/.\n"
                f"  Path: {SKILLS_DIR}\n"
                "  Create one with: mkdir -p skills/my_skill && echo '# My Skill' > skills/my_skill/skill.md"
            ))
        else:
            enabled_count = len(packs)
            total_count = len(all_packs)
            _print(c(BOLD, f"\n  📦 Local skill packs ({enabled_count}/{total_count} enabled)"))
            _print(c(GRAY,  f"  Path: {SKILLS_DIR}\n"))
            _print(_skill_scanner.format_list(include_disabled=True))
            _print(c(GRAY,
                "\n  /skills manage -> TUI toggle (space to toggle, / to search)"
                "\n  /sp enable <name> -> enable  |  /sp disable <name> -> disable  |"
                "  /sp status -> full status"
                "\n  /sp rescan -> rescan  |  /sp sync -> sync updates  |"
                "  /sp install <url> -> install new pack  |  /sp <name> -> show details"
            ))
        return

    # Show details by name.
    packs = _skill_scanner.scan_all(include_disabled=True)
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

        is_enabled = pack.get("_enabled", True)
        status_tag = c(GREEN, "✓ enabled") if is_enabled else c(RED, "✗ disabled")
        _print(c(BOLD, f"\n  📦 {name} v{ver}  [{status_tag}]"))
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
