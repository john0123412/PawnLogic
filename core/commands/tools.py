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
    /skills [sub]          skill pack management TUI:
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
# /skills — unified skill pack management
# ════════════════════════════════════════════════════════

@register("/skills")
async def cmd_skills(ctx: CommandContext) -> None:
    arg = ctx.arg
    arg2 = ctx.arg2
    sub = arg.lower().strip() if arg else ""

    # /skills install <url> — needs a URL argument, stays as text command
    if sub == "install":
        from core.session import _skill_scanner
        repo_url = (arg2 or "").strip()
        if not repo_url:
            _print(c(RED, "  Usage: /skills install <repo_url>"))
            _print(c(GRAY, "  Example: /skills install https://github.com/user/exploit-pack.git"))
            return
        if _runtime_state.user_mode:
            with Spinner("Installing skill pack"):
                result = _skill_scanner.install_pack(repo_url)
        else:
            _print(c(CYAN, f"  Cloning {repo_url} ..."))
            result = _skill_scanner.install_pack(repo_url)
        if result["status"] == "ok":
            _print(c(GREEN, f"  {result['detail']}"))
            _print(c(GRAY, "  Run /skills to manage enabled packs"))
        else:
            _print(c(RED, f"  Install failed: {result['detail']}"))
        return

    # /skills view [page] — view GSA content (text only)
    if sub == "view":
        from config import GLOBAL_SKILLS_PATH
        if not GLOBAL_SKILLS_PATH.exists():
            _print(c(GRAY, "  global_skills.md has not been created. Use /memo to archive."))
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

    # /skills path — show GSA path
    if sub == "path":
        from config import GLOBAL_SKILLS_PATH
        _print(c(GRAY, f"  {GLOBAL_SKILLS_PATH}"))
        return

    # Default: launch the TUI
    from core.session import _skill_scanner
    from core.skill_tui import run_skill_tui
    saved = run_skill_tui(_skill_scanner)
    if saved:
        _print(c(GREEN, "  Skill pack selection saved"))
    else:
        _print(c(GRAY, "  Cancelled"))


# Reference MAGENTA so that ruff doesn't flag the import as unused.
# (MAGENTA is exported by utils.ansi alongside other colors used in this
# module; importing them as a group keeps the import tidy.)
_ = MAGENTA
