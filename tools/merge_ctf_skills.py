#!/usr/bin/env python3
"""
merge_ctf_skills.py - merge claude-skills-ctf categories into pawnlogic skills/.
================================================================================
Usage: python3 tools/merge_ctf_skills.py /tmp/claude-skills-ctf

Each CTF category (ctf-pwn, ctf-web, etc.) becomes one skill directory:
  skills/ctf_pwn/
  - skill.md        merged subtopics
  - manifest.json   auto-generated keywords
"""

import json
import re
import sys
from pathlib import Path


def extract_keywords_from_content(content: str) -> list[str]:
    """Extract keywords from Markdown content."""
    kw = set()
    for m in re.finditer(r"^#{1,3}\s+(.+)", content, re.MULTILINE):
        heading = m.group(1).strip()
        for word in re.findall(r"[a-zA-Z_]{2,20}", heading):
            kw.add(word.lower())
        for cn in re.findall(r"[\u4e00-\u9fff]{2,4}", heading):
            kw.add(cn)
    return sorted(kw)


def build_skill(src_dir: Path, dst_dir: Path, category_name: str):
    """Merge one category directory into one skill."""
    dst_dir.mkdir(parents=True, exist_ok=True)

    # Collect all Markdown files and keep SKILL.md as the main entry.
    md_files = sorted(src_dir.glob("*.md"))
    skill_main = src_dir / "SKILL.md"
    other_mds = [f for f in md_files if f.name != "SKILL.md"]

    # Read SKILL.md as the main entry.
    parts = []
    all_content = ""

    if skill_main.exists():
        content = skill_main.read_text(encoding="utf-8", errors="ignore")
        parts.append(content)
        all_content += content

    # Append other subtopics.
    for md in other_mds:
        content = md.read_text(encoding="utf-8", errors="ignore")
        parts.append(f"\n\n---\n\n<!-- Source: {md.name} -->\n\n{content}")
        all_content += content

    # Write merged skill.md.
    merged = "\n".join(parts)
    (dst_dir / "skill.md").write_text(merged, encoding="utf-8")

    # Generate manifest.json.
    keywords = extract_keywords_from_content(all_content)
    # Add category keywords.
    category_kw = category_name.replace("-", "_").split("_")
    keywords.extend(w.lower() for w in category_kw if len(w) > 1)
    keywords = sorted(set(keywords))

    # Extract description from SKILL.md.
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
        "keywords": keywords[:30],
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
    print(f"  OK {dst_dir.name}/ - {len(other_mds)+1} files merged, {total_size/1024:.0f}KB")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 tools/merge_ctf_skills.py <claude-skills-ctf-path>")
        sys.exit(1)

    src_root = Path(sys.argv[1])
    if not src_root.exists():
        print(f"ERROR: path does not exist: {src_root}")
        sys.exit(1)

    # Find the source skills directory.
    skills_src = src_root / "skills"
    if not skills_src.exists():
        print(f"ERROR: skills directory not found: {skills_src}")
        sys.exit(1)

    # Destination directory.
    project_root = Path(__file__).resolve().parent.parent
    skills_dst = project_root / "skills"

    print(f"Source: {skills_src}")
    print(f"Target: {skills_dst}")
    print()

    # Process each category.
    for skill_dir in sorted(skills_src.iterdir()):
        if not skill_dir.is_dir():
            continue
        if skill_dir.name in ("__pycache__", ".git"):
            continue

        # Convert directory names such as ctf-pwn to ctf_pwn.
        safe_name = skill_dir.name.replace("-", "_")
        dst = skills_dst / safe_name

        print(f"{skill_dir.name} -> {safe_name}/")
        build_skill(skill_dir, dst, skill_dir.name)

    print("\nDone. Skill packs were merged into skills/.")


if __name__ == "__main__":
    main()
