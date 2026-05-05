"""
core/skill_manager.py — SkillScanner: 技能包扫描与匹配引擎
============================================================
P6.5 升级：从单一 *.md 文件模式升级为文件夹包模式。
每个技能包 = 一个子目录，包含 manifest.json 描述元数据。

用法：
    from core.skill_manager import SkillScanner
    scanner = SkillScanner(skills_dir)
    packs = scanner.match("pwn stack overflow", top_k=3)
    prompt_text = scanner.format_for_prompt(packs)
"""

import json
import re
from pathlib import Path


class SkillScanner:
    """扫描 ./skills/*/manifest.json，按关键词匹配技能包。"""

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self._cache: list[dict] | None = None

    def scan_all(self) -> list[dict]:
        """扫描所有技能包，返回 manifest 元数据列表（带 _path 字段）。"""
        if self._cache is not None:
            return self._cache

        if not self.skills_dir.exists() or not self.skills_dir.is_dir():
            self._cache = []
            return []

        packs = []
        for manifest_path in sorted(self.skills_dir.glob("*/manifest.json")):
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8", errors="ignore"))
            except (json.JSONDecodeError, OSError):
                continue

            # 必须字段校验
            if not data.get("name"):
                continue

            data["_path"] = manifest_path.parent  # 技能包根目录
            data["_manifest_path"] = manifest_path
            packs.append(data)

        self._cache = packs
        return packs

    def match(self, query: str, top_k: int = 3) -> list[dict]:
        """
        按查询关键词匹配技能包。
        评分规则：
          - keywords 命中: +3 分/词
          - triggers 命中: +2 分/词
          - name 命中: +5 分/词
          - description 命中: +1 分/词
        """
        packs = self.scan_all()
        if not packs or not query.strip():
            return []

        keywords = self._extract_keywords(query)
        if not keywords:
            return []

        scored = []
        for pack in packs:
            score = 0
            pack_name = pack.get("name", "").lower()
            pack_desc = pack.get("description", "").lower()
            pack_keywords = [k.lower() for k in pack.get("keywords", [])]
            pack_triggers = [t.lower() for t in pack.get("triggers", [])]

            for kw in keywords:
                kw_l = kw.lower()
                # name 命中
                if kw_l in pack_name:
                    score += 5
                # keywords 命中
                for pk in pack_keywords:
                    if kw_l in pk or pk in kw_l:
                        score += 3
                        break
                # triggers 命中
                for pt in pack_triggers:
                    if kw_l in pt:
                        score += 2
                        break
                # description 命中
                if kw_l in pack_desc:
                    score += 1

            if score > 0:
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
            version = pack.get("version", "1.0")
            guide = pack.get("guide", "")
            scripts = pack.get("scripts", [])
            pack_path = pack.get("_path", "")

            lines = [f"=== Skill Pack: {name} v{version} ==="]
            lines.append(f"Description: {desc}")
            lines.append(f"Location: {pack_path}/")

            if guide:
                guide_path = pack_path / guide
                lines.append(f"Guide: read_file(path='{guide_path}')")
                lines.append("ACTION REQUIRED: Read the guide FIRST, then follow its steps.")

            if scripts:
                script_paths = [str(pack_path / s) for s in scripts]
                lines.append(f"Scripts: {', '.join(script_paths)}")
                lines.append("PREFERENCE: Run these scripts instead of writing new code.")

            blocks.append("\n".join(lines))

        return "\n\n".join(blocks)

    def format_user_message(self, packs: list[dict]) -> str:
        """USER_MODE 下的简洁提示。"""
        if not packs:
            return ""
        names = [p.get("name", "unknown") for p in packs]
        return f"  ✓ 已加载技能包: {', '.join(names)}"

    @staticmethod
    def _extract_keywords(query: str) -> list[str]:
        """从查询中提取关键词（英文按词，中文按字）。"""
        words = []
        # 英文单词
        words.extend(w.lower() for w in re.findall(r"[a-zA-Z_]+", query) if len(w) > 1)
        # 中文字符
        words.extend(c for c in query if "一" <= c <= "鿿")
        return words
