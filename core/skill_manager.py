"""
core/skill_manager.py — SkillScanner: 技能包扫描与匹配引擎
============================================================
零配置模式：文件夹里扔一个 .md 文件就能用。

最简用法：
    skills/
    └── pwn_stack/
        └── skill.md        ← 就这一个文件，完事

进阶用法（可选）：
    skills/
    └── pwn_stack/
        ├── skill.md        ← 主内容（Agent 读取执行）
        ├── exploit.py      ← 可选：Agent 优先调用的脚本
        └── manifest.json   ← 可选：额外元数据（keywords/triggers）

扫描逻辑：
    1. 遍历 ./skills/*/ 目录
    2. 找 skill.md（或 guide.md / 目录内第一个 .md）
    3. 从文件名 + 内容标题自动提取关键词
    4. manifest.json 若存在，其 keywords/triggers 优先级更高
"""

import json
import re
from pathlib import Path


class SkillScanner:
    """扫描 ./skills/*/，从 .md 文件自动提取元数据并匹配。"""

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self._cache: list[dict] | None = None

    def invalidate_cache(self):
        """清除缓存，下次 scan_all() 时重新扫描磁盘。"""
        self._cache = None

    def scan_all(self) -> list[dict]:
        """扫描所有技能包，返回元数据列表。"""
        if self._cache is not None:
            return self._cache

        if not self.skills_dir.exists() or not self.skills_dir.is_dir():
            self._cache = []
            return []

        packs = []
        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue

            pack = self._scan_one(skill_dir)
            if pack:
                packs.append(pack)

        self._cache = packs
        return packs

    def _scan_one(self, skill_dir: Path) -> dict | None:
        """扫描单个技能包目录，返回元数据 dict 或 None。"""
        # 1. 找主 .md 文件：skill.md > guide.md > 第一个 .md
        md_file = None
        for name in ("skill.md", "guide.md"):
            candidate = skill_dir / name
            if candidate.exists():
                md_file = candidate
                break
        if not md_file:
            mds = sorted(skill_dir.glob("*.md"))
            if mds:
                md_file = mds[0]
        if not md_file:
            return None  # 没有 .md 文件，跳过

        # 2. 读取 .md 内容
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None

        # 3. 尝试加载 manifest.json（可选）
        manifest = {}
        manifest_path = skill_dir / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8", errors="ignore"))
            except (json.JSONDecodeError, OSError):
                pass

        # 4. 提取名称：manifest.name > .md 一级标题 > 文件夹名
        name = manifest.get("name")
        if not name:
            heading = re.search(r"^#\s+(.+)", content, re.MULTILINE)
            name = heading.group(1).strip() if heading else skill_dir.name

        # 5. 提取关键词：manifest.keywords > 自动提取
        keywords = manifest.get("keywords", [])
        triggers = manifest.get("triggers", [])
        if not keywords:
            keywords = self._auto_extract_keywords(skill_dir.name, content)

        # 6. 找可执行脚本
        scripts = manifest.get("scripts", [])
        if not scripts:
            for ext in ("*.py", "*.sh"):
                scripts.extend(f.name for f in sorted(skill_dir.glob(ext)))

        return {
            "name": name,
            "description": manifest.get("description", self._auto_extract_desc(content)),
            "version": manifest.get("version", "1.0"),
            "keywords": keywords,
            "triggers": triggers,
            "guide": md_file.name,
            "scripts": scripts,
            "_path": skill_dir,
            "_md_file": md_file,
        }

    def match(self, query: str, top_k: int = 3) -> list[dict]:
        """按查询匹配技能包，返回排序后的列表。"""
        packs = self.scan_all()
        if not packs or not query.strip():
            return []

        keywords = self._extract_query_keywords(query)
        if not keywords:
            return []

        scored = []
        for pack in packs:
            score = 0
            pack_name = pack.get("name", "").lower()
            pack_kw = [k.lower() for k in pack.get("keywords", [])]
            pack_tr = [t.lower() for t in pack.get("triggers", [])]

            for kw in keywords:
                kw_l = kw.lower()
                kw_len = len(kw_l)
                # 名称匹配（中文 3-gram 权重更高）
                if kw_l in pack_name:
                    score += 6 if kw_len >= 3 else 5
                # 关键词匹配
                for pk in pack_kw:
                    if kw_l in pk or pk in kw_l:
                        score += 4 if kw_len >= 3 else 3
                        break
                # 触发词匹配：要求匹配长度 >= 触发词长度的一半（过滤短泛词命中长触发词）
                for pt in pack_tr:
                    if kw_l in pt and kw_len * 2 >= len(pt):
                        score += 3 if kw_len >= 3 else 2
                        break

            # 兜底：查询关键词在 .md 内容中出现（需含至少 1 个 3-gram 或 3+ 个 2-gram 命中）
            if score == 0:
                md_file = pack.get("_md_file")
                if md_file:
                    try:
                        content = md_file.read_text(encoding="utf-8", errors="ignore")[:1500].lower()
                        long_hits = sum(1 for kw in keywords if len(kw) >= 3 and kw in content)
                        short_hits = sum(1 for kw in keywords if len(kw) < 3 and kw in content)
                        if long_hits >= 1 or short_hits >= 3:
                            score = 2
                    except OSError:
                        pass

            if score >= 2:
                scored.append((score, pack))

        scored.sort(key=lambda x: -x[0])
        return [pack for _, pack in scored[:top_k]]

    def format_for_prompt(self, packs: list[dict]) -> str:
        """将匹配到的技能包格式化为系统提示词注入文本。"""
        if not packs:
            return ""

        blocks = []
        for pack in packs:
            name = pack.get("name", "unknown")
            desc = pack.get("description", "")
            guide = pack.get("guide", "")
            scripts = pack.get("scripts", [])
            pack_path = pack.get("_path", "")

            lines = [f"=== Skill: {name} ==="]
            if desc:
                lines.append(f"  {desc}")
            if guide:
                lines.append(f"  Read: read_file(path='{pack_path / guide}')")
                lines.append(f"  Follow the guide step by step.")
            if scripts:
                lines.append(f"  Scripts: {', '.join(scripts)}")
                # P6: 明确的脚本执行指令
                lines.append(f"  --- AUTO-EXECUTE DIRECTIVE (P6) ---")
                lines.append(f"  该技能包含预置脚本，你必须优先执行，禁止在未尝试前自主编写 Payload。")
                for script in scripts:
                    script_path = pack_path / script
                    if script.endswith(".py"):
                        lines.append(
                            f"  Execute: run_shell(command='python3 {script_path} --url <TARGET_URL>')"
                        )
                    elif script.endswith(".sh"):
                        lines.append(
                            f"  Execute: run_shell(command='bash {script_path} <TARGET_URL>')"
                        )
                    else:
                        lines.append(
                            f"  Execute: run_shell(command='{script_path} <args>')"
                        )
                lines.append(f"  若脚本执行失败，阅读 guide.md 分析原因后再修改，不要从零编写。")

            blocks.append("\n".join(lines))

        return "\n\n".join(blocks)

    def format_user_message(self, packs: list[dict]) -> str:
        """USER_MODE 简洁提示。"""
        if not packs:
            return ""
        names = [p.get("name", "?") for p in packs]
        return f"  ✓ 已加载技能: {', '.join(names)}"

    def format_list(self) -> str:
        """格式化所有已扫描的技能包列表（用于 /skillpack 命令）。"""
        packs = self.scan_all()
        if not packs:
            return "(skills/ 目录下暂无技能包)"
        lines = []
        for i, p in enumerate(packs):
            name = p.get("name", "?")
            desc = p.get("description", "")
            ver  = p.get("version", "1.0")
            kw   = ", ".join(p.get("keywords", [])[:5])
            scripts = p.get("scripts", [])
            line = f"  [{i+1}] {name} v{ver}"
            if desc:
                line += f" — {desc[:60]}"
            lines.append(line)
            detail = f"       keywords: {kw}" if kw else ""
            if scripts:
                detail += f"  scripts: {', '.join(scripts)}"
            if detail:
                lines.append(detail)
        return "\n".join(lines)

    # ── 内部辅助 ──────────────────────────────────────────

    @staticmethod
    def _auto_extract_keywords(dirname: str, content: str) -> list[str]:
        """从文件夹名 + .md 标题自动提取关键词。"""
        kw = set()
        # 文件夹名拆词（英文）
        for word in re.split(r"[_\-\s]+", dirname):
            if 2 <= len(word) <= 15 and word.isascii():
                kw.add(word.lower())
        # .md 标题中的英文单词
        for m in re.finditer(r"^#{1,3}\s+(.+)", content, re.MULTILINE):
            heading = m.group(1).strip()
            for word in re.findall(r"[a-zA-Z_]{2,15}", heading):
                kw.add(word.lower())
        # .md 标题中的中文词（连续 2-4 个汉字）
        for m in re.finditer(r"^#{1,3}\s+(.+)", content, re.MULTILINE):
            heading = m.group(1).strip()
            for cn in re.findall(r"[一-鿿]{2,4}", heading):
                kw.add(cn)
        return list(kw)

    @staticmethod
    def _auto_extract_desc(content: str) -> str:
        """从 .md 内容提取第一段非标题文本作为描述。"""
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and len(line) > 5:
                return line[:120]
        return ""

    @staticmethod
    def _extract_query_keywords(query: str) -> list[str]:
        """从查询中提取关键词（英文按词，中文按 2-gram + 3-gram）。"""
        words = []
        words.extend(w.lower() for w in re.findall(r"[a-zA-Z_]+", query) if len(w) > 1)
        cn_chars = [c for c in query if "一" <= c <= "鿿"]
        # 3-gram 优先（更精确），权重由 match() 中按长度加权
        for i in range(len(cn_chars) - 2):
            words.append(cn_chars[i] + cn_chars[i + 1] + cn_chars[i + 2])
        for i in range(len(cn_chars) - 1):
            words.append(cn_chars[i] + cn_chars[i + 1])
        return words
