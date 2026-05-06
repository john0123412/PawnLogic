#!/usr/bin/env python3
"""
merge_ctf_skills.py — 将 claude-skills-ctf 仓库按分类聚合到 pawnlogic skills/ 目录
================================================================
用法: python3 tools/merge_ctf_skills.py /tmp/claude-skills-ctf

每个 CTF 分类（ctf-pwn, ctf-web 等）合并为一个 skill 目录:
  skills/ctf_pwn/
  ├── skill.md        ← 所有子主题合并
  └── manifest.json   ← 自动生成的关键词
"""

import json
import re
import shutil
import sys
from pathlib import Path


def extract_keywords_from_content(content: str) -> list[str]:
    """从 .md 内容提取关键词。"""
    kw = set()
    for m in re.finditer(r"^#{1,3}\s+(.+)", content, re.MULTILINE):
        heading = m.group(1).strip()
        for word in re.findall(r"[a-zA-Z_]{2,20}", heading):
            kw.add(word.lower())
        for cn in re.findall(r"[一-鿿]{2,4}", heading):
            kw.add(cn)
    return sorted(kw)


def build_skill(src_dir: Path, dst_dir: Path, category_name: str):
    """将一个分类目录聚合为一个 skill。"""
    dst_dir.mkdir(parents=True, exist_ok=True)

    # 收集所有 .md 文件，SKILL.md 排到最后作为附录
    md_files = sorted(src_dir.glob("*.md"))
    skill_main = src_dir / "SKILL.md"
    other_mds = [f for f in md_files if f.name != "SKILL.md"]

    # 读取 SKILL.md 作为主入口
    parts = []
    all_content = ""

    if skill_main.exists():
        content = skill_main.read_text(encoding="utf-8", errors="ignore")
        parts.append(content)
        all_content += content

    # 追加其他子主题
    for md in other_mds:
        content = md.read_text(encoding="utf-8", errors="ignore")
        parts.append(f"\n\n---\n\n<!-- Source: {md.name} -->\n\n{content}")
        all_content += content

    # 写入聚合后的 skill.md
    merged = "\n".join(parts)
    (dst_dir / "skill.md").write_text(merged, encoding="utf-8")

    # 生成 manifest.json
    keywords = extract_keywords_from_content(all_content)
    # 添加分类名关键词
    category_kw = category_name.replace("-", "_").split("_")
    keywords.extend(w.lower() for w in category_kw if len(w) > 1)
    keywords = sorted(set(keywords))

    # 从 SKILL.md 提取描述
    description = ""
    if skill_main.exists():
        skill_content = skill_main.read_text(encoding="utf-8", errors="ignore")
        for line in skill_content.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and len(line) > 10:
                description = line[:150]
                break

    manifest = {
        "name": f"CTF {category_name.replace('ctf-', '').replace('-', ' ').title()}",
        "version": "1.0",
        "description": description or f"CTF {category_name} skills",
        "keywords": keywords[:30],  # 限制数量
        "triggers": [
            f"CTF {category_name} challenge",
            f"{category_name.replace('ctf-', '')} exploit",
        ],
        "author": "MateoBogo/claude-skills-ctf",
    }
    (dst_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    total_size = sum(f.stat().st_size for f in dst_dir.iterdir())
    print(f"  ✓ {dst_dir.name}/ — {len(other_mds)+1} files merged, {total_size/1024:.0f}KB")


def main():
    if len(sys.argv) < 2:
        print("用法: python3 tools/merge_ctf_skills.py <claude-skills-ctf-path>")
        sys.exit(1)

    src_root = Path(sys.argv[1])
    if not src_root.exists():
        print(f"❌ 路径不存在: {src_root}")
        sys.exit(1)

    # 找到 skills 子目录
    skills_src = src_root / "skills"
    if not skills_src.exists():
        print(f"❌ 找不到 {skills_src}/skills/ 目录")
        sys.exit(1)

    # 目标目录
    project_root = Path(__file__).resolve().parent.parent
    skills_dst = project_root / "skills"

    print(f"📦 源: {skills_src}")
    print(f"📁 目标: {skills_dst}")
    print()

    # 处理每个分类
    for skill_dir in sorted(skills_src.iterdir()):
        if not skill_dir.is_dir():
            continue
        if skill_dir.name in ("__pycache__", ".git"):
            continue

        # 转换目录名：ctf-pwn → ctf_pwn
        safe_name = skill_dir.name.replace("-", "_")
        dst = skills_dst / safe_name

        print(f"🔄 {skill_dir.name} → {safe_name}/")
        build_skill(skill_dir, dst, skill_dir.name)

    print("\n✅ 完成！技能包已聚合到 skills/ 目录")


if __name__ == "__main__":
    main()
