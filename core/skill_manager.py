"""
core/skill_manager.py — SkillScanner: skill-pack scanning and matching engine.
============================================================
Zero-config mode: drop one .md file into a folder and it works.

Minimal layout:
    skills/
    └── pwn_stack/
        └── skill.md        ← only file needed

Advanced layout, optional:
    skills/
    └── pwn_stack/
        ├── skill.md        ← main content read by the agent
        ├── exploit.py      ← optional script the agent should prefer
        └── manifest.json   ← optional metadata: keywords/triggers

Scanning:
    1. Iterate ./skills/*/ directories.
    2. Find skill.md, guide.md, or the first .md file.
    3. Auto-extract keywords from the folder name and Markdown headings.
    4. manifest.json keywords/triggers override auto extraction when present.
"""

import json
import re
import subprocess
from pathlib import Path
from config import scrub_sensitive_env


class SkillScanner:
    """Scan ./skills/*/, auto-extract metadata from .md files, and match packs."""

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self._cache: list[dict] | None = None

    def invalidate_cache(self):
        """Clear cache so scan_all() re-scans the disk next time."""
        self._cache = None

    def sync_packs(self) -> list[dict]:
        """Run git pull for every ./skills/ child directory containing .git.

        Returns [{"name": str, "status": "ok"|"error", "detail": str}, ...].
        """
        results = []
        if not self.skills_dir.exists():
            return results

        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            git_dir = skill_dir / ".git"
            if not git_dir.exists():
                continue

            name = skill_dir.name
            try:
                proc = subprocess.run(
                    ["git", "pull", "--ff-only"],
                    cwd=str(skill_dir),
                    capture_output=True, text=True,
                    timeout=30, errors="ignore",
                    env=scrub_sensitive_env(),
                )
                if proc.returncode == 0:
                    detail = proc.stdout.strip().split("\n")[-1][:100]
                    results.append({"name": name, "status": "ok", "detail": detail})
                else:
                    detail = proc.stderr.strip().split("\n")[-1][:100]
                    results.append({"name": name, "status": "error", "detail": detail})
            except subprocess.TimeoutExpired:
                results.append({"name": name, "status": "error", "detail": "git pull timed out (30s)"})
            except Exception as e:
                results.append({"name": name, "status": "error", "detail": str(e)[:80]})

        self.invalidate_cache()
        return results

    def install_pack(self, repo_url: str) -> dict:
        """Clone a remote repository into a ./skills/ subdirectory.

        Invalidates cache on success. Returns
        {"status": "ok"|"error", "name": str, "detail": str}.
        """
        if not self.skills_dir.exists():
            self.skills_dir.mkdir(parents=True, exist_ok=True)

        # Extract repository name from URL to use as directory name.
        # https://github.com/user/repo.git -> repo
        name = repo_url.rstrip("/").split("/")[-1]
        if name.endswith(".git"):
            name = name[:-4]
        # Sanitize illegal characters.
        name = re.sub(r"[^a-zA-Z0-9_\-.]", "_", name)

        target_dir = self.skills_dir / name
        if target_dir.exists():
            return {
                "status": "error",
                "name": name,
                "detail": f"directory already exists: {target_dir}",
            }

        try:
            proc = subprocess.run(
                ["git", "clone", "--depth=1", repo_url, str(target_dir)],
                capture_output=True, text=True,
                timeout=60, errors="ignore",
                env=scrub_sensitive_env(),
            )
            if proc.returncode != 0:
                # Clean up failed clone directory.
                import shutil
                if target_dir.exists():
                    shutil.rmtree(str(target_dir), ignore_errors=True)
                detail = proc.stderr.strip().split("\n")[-1][:120]
                return {"status": "error", "name": name, "detail": detail}

            # Ensure file permissions are usable.
            subprocess.run(
                ["chmod", "-R", "u+rwX,go+rX", str(target_dir)],
                capture_output=True, timeout=10,
                env=scrub_sensitive_env(),
            )

            # Remove noisy non-skill repository files.
            _IGNORE_PATTERNS = [".git", "__pycache__", "*.pyc", ".DS_Store", "node_modules"]
            for pattern in _IGNORE_PATTERNS:
                for p in target_dir.glob(pattern):
                    if p.is_dir():
                        import shutil
                        shutil.rmtree(str(p), ignore_errors=True)

            self.invalidate_cache()
            return {"status": "ok", "name": name, "detail": f"installed to {target_dir}"}

        except subprocess.TimeoutExpired:
            import shutil
            if target_dir.exists():
                shutil.rmtree(str(target_dir), ignore_errors=True)
            return {"status": "error", "name": name, "detail": "git clone timed out (60s)"}
        except Exception as e:
            return {"status": "error", "name": name, "detail": str(e)[:120]}

    def scan_all(self) -> list[dict]:
        """Scan all skill packs and return metadata."""
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
        """Scan one skill-pack directory and return metadata or None."""
        # 1. Find main .md file: skill.md > guide.md > first .md.
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
            return None  # No .md file; skip.

        # 2. Read Markdown content.
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None

        # 3. Try to load optional manifest.json.
        manifest = {}
        manifest_path = skill_dir / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8", errors="ignore"))
            except (json.JSONDecodeError, OSError):
                pass

        # 4. Name: manifest.name > level-1 Markdown heading > folder name.
        name = manifest.get("name")
        if not name:
            heading = re.search(r"^#\s+(.+)", content, re.MULTILINE)
            name = heading.group(1).strip() if heading else skill_dir.name

        # 5. Keywords: manifest.keywords > auto extraction.
        keywords = manifest.get("keywords", [])
        triggers = manifest.get("triggers", [])
        if not keywords:
            keywords = self._auto_extract_keywords(skill_dir.name, content)

        # 6. Find executable scripts.
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

    def match(self, query: str, top_k: int = 3, min_score: int = 3) -> list[dict]:
        """Match skill packs by query and return a sorted list.

        min_score is the minimum threshold; below it packs are not returned to
        avoid noisy prompt injection.
        """
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
                # Name match; longer grams carry slightly higher weight.
                if kw_l in pack_name:
                    score += 6 if kw_len >= 3 else 5
                # Keyword match.
                for pk in pack_kw:
                    if kw_l in pk or pk in kw_l:
                        score += 4 if kw_len >= 3 else 3
                        break
                # Trigger match: require enough length to avoid short generic hits.
                for pt in pack_tr:
                    if kw_l in pt and kw_len * 2 >= len(pt):
                        score += 3 if kw_len >= 3 else 2
                        break

            # Fallback: query keywords appear in .md content.
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

            if score >= min_score:
                scored.append((score, pack))

        scored.sort(key=lambda x: -x[0])
        return [pack for _, pack in scored[:top_k]]

    def format_for_prompt(self, packs: list[dict]) -> str:
        """Format matched skill packs for System Prompt injection."""
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
                lines.append(f"  Read: read_file('{pack_path / guide}')")
            if scripts:
                lines.append(f"  Scripts: {', '.join(scripts)}")
                for script in scripts:
                    script_path = pack_path / script
                    if script.endswith(".py"):
                        lines.append(f"  Run: python3 {script_path} --url <TARGET>")
                    elif script.endswith(".sh"):
                        lines.append(f"  Run: bash {script_path} <TARGET>")
                    else:
                        lines.append(f"  Run: {script_path} <args>")
                lines.append("  P6: Prefer scripts first. If they fail, read guide.md before modifying parameters. Do not skip directly to hand-written code.")

            blocks.append("\n".join(lines))

        return "\n\n".join(blocks)

    def format_user_message(self, packs: list[dict]) -> str:
        """Concise user-mode status message."""
        if not packs:
            return ""
        names = [p.get("name", "?") for p in packs]
        return f"  ✓ Loaded skills: {', '.join(names)}"

    def format_list(self) -> str:
        """Format all scanned skill packs for /skillpack."""
        packs = self.scan_all()
        if not packs:
            return "(no skill packs found under skills/)"
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

    # Internal helpers.

    @staticmethod
    def _auto_extract_keywords(dirname: str, content: str) -> list[str]:
        """Auto-extract keywords from folder name and Markdown headings."""
        kw = set()
        # Split folder name into English words.
        for word in re.split(r"[_\-\s]+", dirname):
            if 2 <= len(word) <= 15 and word.isascii():
                kw.add(word.lower())
        # English words in Markdown headings.
        for m in re.finditer(r"^#{1,3}\s+(.+)", content, re.MULTILINE):
            heading = m.group(1).strip()
            for word in re.findall(r"[a-zA-Z_]{2,15}", heading):
                kw.add(word.lower())
        # Chinese terms in Markdown headings, preserved for matching user queries.
        for m in re.finditer(r"^#{1,3}\s+(.+)", content, re.MULTILINE):
            heading = m.group(1).strip()
            for cn in re.findall(r"[\u4e00-\u9fff]{2,4}", heading):
                kw.add(cn)
        return list(kw)

    @staticmethod
    def _auto_extract_desc(content: str) -> str:
        """Extract the first non-heading paragraph from Markdown as description."""
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and len(line) > 5:
                return line[:120]
        return ""

    @staticmethod
    def _extract_query_keywords(query: str) -> list[str]:
        """Extract English word keywords plus Chinese 2-grams and 3-grams."""
        words = []
        words.extend(w.lower() for w in re.findall(r"[a-zA-Z_]+", query) if len(w) > 1)
        cn_chars = [c for c in query if "\u4e00" <= c <= "\u9fff"]
        # 3-grams first for better precision; match() weights by length.
        for i in range(len(cn_chars) - 2):
            words.append(cn_chars[i] + cn_chars[i + 1] + cn_chars[i + 2])
        for i in range(len(cn_chars) - 1):
            words.append(cn_chars[i] + cn_chars[i + 1])
        return words
