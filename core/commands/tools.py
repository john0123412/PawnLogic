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


# ════════════════════════════════════════════════════════
# /knowledge
# ════════════════════════════════════════════════════════

@register("/knowledge")
async def cmd_knowledge(ctx: CommandContext) -> None:
    query = (ctx.arg + " " + ctx.arg2).strip()
    if query:
        rows = search_knowledge(query, limit=10)
        print(c(BOLD, f"\n  知识库搜索: '{query}' — {len(rows)} 条："))
    else:
        rows = list(list_knowledge(20))
        print(c(BOLD, f"\n  知识库（最近 {len(rows)} 条）："))
    if not rows:
        print(c(GRAY, "  (空)"))
    else:
        for r in rows:
            print(c(CYAN, f"  [{r['id']:3d}] ") + c(YELLOW, r["topic"]) +
                  c(GRAY, f"  {r['created_at'][:16]}  tags={r['tags'] or '-'}"))
            print(c(GRAY, f"       {str(r['content'])[:100]}"))


# ════════════════════════════════════════════════════════
# Tool status
# ════════════════════════════════════════════════════════

@register("/webstatus")
async def cmd_webstatus(ctx: CommandContext) -> None:
    print(c(BOLD, "\n  网页抓取工具状态："))
    print(web_tool_status())


@register("/browserstatus")
async def cmd_browserstatus(ctx: CommandContext) -> None:
    try:
        from tools.browser_ops import browser_tool_status
        print(c(BOLD, "\n  Scrapling 浏览器工具状态："))
        print(browser_tool_status())
    except ImportError:
        print(c(RED, "  ✗ browser_ops 模块未加载"))


@register("/pwnenv")
async def cmd_pwnenv(ctx: CommandContext) -> None:
    print(tool_pwn_env({}))


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
        print(c(BOLD, "\n  Docker 状态："))
        print(docker_status())
        print(c(GRAY, f"\n  可用镜像别名: {', '.join(DEFAULT_DOCKER_IMAGES.keys())}"))
        print(c(GRAY, "  用法: /docker status | /docker images | /docker ps | /docker containers"))
    elif sub == "images":
        client = _get_docker_client()
        if not client:
            print(c(RED, "  ✗ Docker 不可用"))
        else:
            images = client.images.list()
            print(c(BOLD, f"\n  本地镜像（{len(images)} 个）："))
            for img in images[:20]:
                tags = ", ".join(img.tags) if img.tags else "<none>"
                size_mb = img.attrs.get("Size", 0) / (1024 * 1024)
                print(f"  {c(CYAN, tags):40} {c(GRAY, f'{size_mb:.0f}MB')}")
    elif sub in ("ps", "containers"):
        client = _get_docker_client()
        if not client:
            print(c(RED, "  ✗ Docker 不可用"))
        else:
            containers = client.containers.list(all=True)
            pawn_containers = [ct for ct in containers if ct.labels.get("pawn") == "true"]
            print(c(BOLD, f"\n  PawnLogic 容器（{len(pawn_containers)} 个）："))
            for ct in pawn_containers:
                name = ct.labels.get("pawn_name", ct.name)
                status_color = GREEN if ct.status == "running" else RED
                print(f"  {c(CYAN, name):20} {c(status_color, ct.status):12} {c(GRAY, ct.id[:12])}")
            if not pawn_containers:
                print(c(GRAY, "  (无 PawnLogic 容器)"))
    elif sub == "pull":
        image = arg2.strip() if arg2 else ""
        if not image:
            print(c(RED, "  用法: /docker pull <镜像名或别名>"))
        else:
            from tools.docker_sandbox import _resolve_image
            resolved = _resolve_image(image)
            client = _get_docker_client()
            if not client:
                print(c(RED, "  ✗ Docker 不可用"))
            else:
                print(c(YELLOW, f"  📥 正在拉取 {resolved} ..."))
                try:
                    client.images.pull(resolved)
                    print(c(GREEN, f"  ✓ {resolved} 拉取完成"))
                except Exception as e:
                    print(c(RED, f"  ✗ 拉取失败: {e}"))
    elif sub == "clean":
        from tools.docker_sandbox import docker_prune_resources
        print(c(YELLOW, "  🧹 正在清理 Docker 资源..."))
        result = docker_prune_resources()
        col = GREEN if result.startswith("✓") else RED
        print(c(col, f"  {result}"))
    else:
        print(c(GRAY, "  用法: /docker status | /docker images | /docker ps | /docker pull <镜像> | /docker clean"))


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
        # 无参数：显示交互式菜单
        current = DYNAMIC_CONFIG.get("preferred_worker", "auto")
        print(c(BOLD, "\n  子任务 Worker 模型（delegate_task 使用）："))
        for i, alias in enumerate(_WORKER_MODEL_CANDIDATES):
            if alias not in MODELS:
                continue
            ok, env = validate_api_key(alias)
            ktag = c(GREEN, "[key✓]") if ok else c(RED, "[key✗]")
            desc = MODELS[alias].get("desc", "")
            tick = c(GREEN, " ◀ 当前") if alias == current else ""
            print(
                c(GRAY, f"  [{i+1}] ")
                + c(CYAN, f"{alias:16}")
                + f" {desc:30} {ktag}{tick}"
            )
        # auto 选项
        auto_tick = c(GREEN, " ◀ 当前") if current == "auto" else ""
        print(
            c(GRAY, "  [A] ")
            + c(YELLOW, f"{'auto':16}")
            + f" {'系统自动路由（按优先级选取首个可用模型）':30} {auto_tick}"
        )
        print(c(GRAY, "\n  用法: /worker <alias> 或 /worker auto"))
        return

    if target == "auto":
        DYNAMIC_CONFIG["preferred_worker"] = "auto"
        session._reset_system_prompt()
        print(c(GREEN, "  ✓ Worker 已恢复为自动路由模式"))
        return

    if target in MODELS:
        ok, env = validate_api_key(target)
        if not ok:
            print(c(YELLOW, f"  ⚠ 已切换到 {target}，但 {env} 未设置。用 /setkey 配置。"))
        DYNAMIC_CONFIG["preferred_worker"] = target
        session._reset_system_prompt()
        print(c(GREEN, f"  ✓ Worker 已锁定为 {c(CYAN, target)}（子任务将强制使用此模型）"))
        return

    # 尝试按序号匹配
    try:
        idx = int(target) - 1
        if 0 <= idx < len(_WORKER_MODEL_CANDIDATES):
            alias = _WORKER_MODEL_CANDIDATES[idx]
            DYNAMIC_CONFIG["preferred_worker"] = alias
            session._reset_system_prompt()
            print(c(GREEN, f"  ✓ Worker 已锁定为 {c(CYAN, alias)}"))
        else:
            print(c(RED, "  ✗ 序号超出范围"))
    except ValueError:
        print(c(RED, f"  ✗ 未知模型 '{target}'。用 /worker 查看候选列表。"))


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
        print(c(GRAY, f"  {GLOBAL_SKILLS_PATH}"))
        return

    if sub == "packs":
        from core.session import _skill_scanner
        from config import SKILLS_DIR
        packs = _skill_scanner.scan_all()
        if not packs:
            print(c(GRAY,
                f"  skills/ 目录下暂无技能包。\n"
                f"  路径: {SKILLS_DIR}\n"
                "  创建: mkdir -p skills/my_skill && echo '# My Skill' > skills/my_skill/skill.md"
            ))
        else:
            print(c(BOLD, f"\n  📦 本地技能包（{len(packs)} 个）"))
            print(c(GRAY,  f"  路径: {SKILLS_DIR}\n"))
            print(_skill_scanner.format_list())
            print(c(GRAY, "\n  /skillpack rescan → 重新扫描  |  /skillpack <名称> → 查看详情"))
        return

    if sub == "view":
        if not GLOBAL_SKILLS_PATH.exists():
            print(c(GRAY, "  global_skills.md 尚未创建。完成任务后由 AI 自动生成，或使用 /memo。"))
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
        print(c(BOLD, f"\n  global_skills.md  ({total} 行，显示 {start+1}-{end})\n"))
        for line in lines_all[start:end]:
            if line.startswith("# "):
                print(c(CYAN, line))
            elif line.startswith("## "):
                print(c(YELLOW, line))
            else:
                print(f"  {line}")
        if end < total:
            rem = (total - end + page_size - 1) // page_size
            print(c(GRAY, f"\n  还有 {rem} 页，/skills view <页码> 继续"))
        return

    # 默认：toc 分类目录
    try:
        from core.gsa import load_toc
        toc = load_toc(max_lines=120)
    except ImportError:
        if not GLOBAL_SKILLS_PATH.exists():
            toc = "(尚未创建)"
        else:
            toc = "\n".join(
                line for line in GLOBAL_SKILLS_PATH.read_text(encoding="utf-8").splitlines()[:80]
                if line.startswith("#")
            )
    if not GLOBAL_SKILLS_PATH.exists():
        print(c(GRAY,
            f"  global_skills.md 尚未创建。\n"
            f"  路径: {GLOBAL_SKILLS_PATH}\n"
            "  完成任务后 AI 自动创建，或用 /memo 手动存档。"
        ))
    else:
        print(c(BOLD, "\n  📚 Global Skills Archive — 分类目录"))
        print(c(GRAY,  f"  路径: {GLOBAL_SKILLS_PATH}\n"))
        for line in toc.splitlines():
            if line.startswith("# "):
                print(c(CYAN + BOLD, f"  {line}"))
            elif line.startswith("## "):
                print(c(YELLOW, f"    {line}"))
            else:
                print(c(GRAY, f"  {line}"))
        print(c(GRAY, "\n  /skills view → 完整内容  |  /skills packs → 本地技能包  |  /memo → 手动存档"))


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
        print(c(GREEN, f"  ✓ 已重新扫描 skills/ 目录，发现 {len(packs)} 个技能包"))
        if packs:
            print(c(BOLD, "\n  本地技能包："))
            print(_skill_scanner.format_list())
        return

    if sub == "sync":
        if _runtime_state.user_mode:
            with Spinner("正在同步技能包"):
                results = _skill_scanner.sync_packs()
        else:
            print(c(CYAN, "  🔄 正在同步所有带 .git 的技能包..."))
            results = _skill_scanner.sync_packs()
        if not results:
            print(c(GRAY, "  没有发现带 .git 的技能包目录"))
            return
        ok_count = sum(1 for r in results if r["status"] == "ok")
        err_count = len(results) - ok_count
        print(c(GREEN, f"  ✓ 同步完成: {ok_count} 成功, {err_count} 失败"))
        for r in results:
            tag = c(GREEN, "✓") if r["status"] == "ok" else c(RED, "✗")
            detail = ""
            if not _runtime_state.user_mode:
                detail = c(GRAY, f"  {r['detail']}")
            print(f"    {tag} {r['name']}{detail}")
        if err_count > 0:
            print(c(GRAY, "  提示: 手动进入失败的目录执行 git pull 查看详细错误"))
        return

    if sub == "install":
        repo_url = arg2.strip() if arg2 else ""
        if not repo_url:
            print(c(RED, "  用法: /sp install <repo_url>"))
            print(c(GRAY, "  例: /sp install https://github.com/user/exploit-pack.git"))
            return
        if _runtime_state.user_mode:
            with Spinner("正在安装技能包"):
                result = _skill_scanner.install_pack(repo_url)
        else:
            print(c(CYAN, f"  📥 正在克隆 {repo_url} ..."))
            result = _skill_scanner.install_pack(repo_url)
        if result["status"] == "ok":
            print(c(GREEN, f"  ✓ {result['detail']}"))
            packs = _skill_scanner.scan_all()
            installed = [p for p in packs if result["name"] in p.get("_path", "").name]
            if installed:
                print(c(BOLD, "\n  新安装的技能包:"))
                for p in installed:
                    name = p.get("name", "?")
                    desc = p.get("description", "")
                    scripts = p.get("scripts", [])
                    print(c(GREEN, f"    📦 {name}"))
                    if desc:
                        print(c(GRAY, f"       {desc[:60]}"))
                    if scripts:
                        print(c(GRAY, f"       scripts: {', '.join(scripts)}"))
        else:
            print(c(RED, f"  ✗ 安装失败: {result['detail']}"))
        return

    if sub == "list" or sub == "":
        packs = _skill_scanner.scan_all()
        if not packs:
            print(c(GRAY,
                f"  skills/ 目录下暂无技能包。\n"
                f"  路径: {SKILLS_DIR}\n"
                "  创建: mkdir -p skills/my_skill && echo '# My Skill' > skills/my_skill/skill.md"
            ))
        else:
            print(c(BOLD, f"\n  📦 本地技能包（{len(packs)} 个）"))
            print(c(GRAY,  f"  路径: {SKILLS_DIR}\n"))
            print(_skill_scanner.format_list())
            print(c(GRAY,
                "\n  /sp rescan → 重新扫描  |  /sp sync → 同步更新  |"
                "  /sp install <url> → 安装新包  |  /sp <名称> → 查看详情"
            ))
        return

    # 按名称查看详情
    packs = _skill_scanner.scan_all()
    matched = [p for p in packs if sub in p.get("name", "").lower()
               or sub in p.get("_path", "").name.lower()]
    if not matched:
        print(c(RED, f"  ✗ 未找到名为 '{sub}' 的技能包"))
        print(c(GRAY, "  用 /skillpack 查看所有可用技能包"))
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

        print(c(BOLD, f"\n  📦 {name} v{ver}"))
        if desc:
            print(f"  {desc}")
        print(c(GRAY, f"  路径: {pack_path}"))
        if kw:
            print(c(CYAN, f"  关键词: {', '.join(kw)}"))
        if tr:
            print(c(CYAN, f"  触发词: {', '.join(tr)}"))
        if guide:
            print(c(GREEN, f"  指南: {pack_path / guide}"))
            print(c(GRAY,  f"    → read_file(path='{pack_path / guide}')"))
        if scripts:
            print(c(GREEN, f"  脚本: {', '.join(scripts)}"))
            print(c(GRAY,  "    → 优先运行脚本而非即兴编码"))


# Reference MAGENTA so that ruff doesn't flag the import as unused.
# (MAGENTA is exported by utils.ansi alongside other colors used in this
# module; importing them as a group keeps the import tidy.)
_ = MAGENTA
