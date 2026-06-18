"""CTF workspace metadata and writeup helpers."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import tempfile
from typing import Any


CTF_METADATA_FILENAME = "ctf.json"
CTF_WRITEUP_FILENAME = "writeup.md"
MAX_CTF_ITEMS = 100
_SECRET_KEY_RE = re.compile(
    r"(^|[^A-Za-z0-9])(api[_-]?key|token|secret|password|private[_-]?key)($|[^A-Za-z0-9])",
    re.IGNORECASE,
)


class CTFMetadataError(Exception):
    """Base error for CTF workspace metadata operations."""


class CTFMetadataReadError(CTFMetadataError):
    """Raised when an existing CTF metadata file cannot be parsed safely."""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_text(value: Any, max_len: int = 240) -> str:
    text = str(value or "").replace("\x00", "").strip()
    text = " ".join(text.split())
    return text[:max_len]


def _clean_list(values: Any, max_items: int = MAX_CTF_ITEMS) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        raw_items = [values]
    elif isinstance(values, set):
        raw_items = sorted(values, key=str)
    elif isinstance(values, list | tuple | set):
        raw_items = list(values)
    else:
        raw_items = [values]

    cleaned: list[str] = []
    seen: set[str] = set()
    for value in raw_items:
        item = _clean_text(value, 500)
        if not item or item in seen:
            continue
        cleaned.append(item)
        seen.add(item)
    return cleaned[-max_items:]


def _workspace_path(workspace_dir: str | Path) -> Path:
    return Path(workspace_dir).expanduser()


def _append_unique_bounded(values: list[str], item: str) -> None:
    if item and item not in values:
        values.append(item)
    if len(values) > MAX_CTF_ITEMS:
        del values[:-MAX_CTF_ITEMS]


def _atomic_write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            tmp_path = Path(handle.name)
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            with suppress(OSError):
                tmp_path.unlink()


@dataclass(slots=True)
class CTFMetadata:
    challenge_name: str = ""
    category: str = ""
    source: str = ""
    artifacts: list[str] = field(default_factory=list)
    remote_targets: list[str] = field(default_factory=list)
    flag_candidates: list[str] = field(default_factory=list)
    status: str = "draft"
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def new(cls, *, challenge_name: str = "", category: str = "", source: str = "") -> CTFMetadata:
        now = _now()
        return cls(
            challenge_name=_clean_text(challenge_name),
            category=_clean_text(category, 80),
            source=_clean_text(source, 500),
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CTFMetadata:
        return cls(
            challenge_name=_clean_text(data.get("challenge_name")),
            category=_clean_text(data.get("category"), 80),
            source=_clean_text(data.get("source"), 500),
            artifacts=_clean_list(data.get("artifacts")),
            remote_targets=_clean_list(data.get("remote_targets")),
            flag_candidates=_clean_list(data.get("flag_candidates")),
            status=_clean_text(data.get("status") or "draft", 40) or "draft",
            created_at=_clean_text(data.get("created_at"), 40),
            updated_at=_clean_text(data.get("updated_at"), 40),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "challenge_name": self.challenge_name,
            "category": self.category,
            "source": self.source,
            "artifacts": list(self.artifacts),
            "remote_targets": list(self.remote_targets),
            "flag_candidates": list(self.flag_candidates),
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def touch(self) -> None:
        if not self.created_at:
            self.created_at = _now()
        self.updated_at = _now()


def metadata_path(workspace_dir: str | Path) -> Path:
    return _workspace_path(workspace_dir) / CTF_METADATA_FILENAME


def writeup_path(workspace_dir: str | Path) -> Path:
    return _workspace_path(workspace_dir) / CTF_WRITEUP_FILENAME


def load_ctf_metadata(workspace_dir: str | Path, *, strict: bool = False) -> CTFMetadata | None:
    path = metadata_path(workspace_dir)
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        if strict:
            raise CTFMetadataReadError(f"Unable to read CTF metadata at {path}: {exc}") from exc
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        if strict:
            raise CTFMetadataReadError(f"Invalid CTF metadata JSON at {path}: {exc}") from exc
        return None
    if not isinstance(data, dict):
        if strict:
            raise CTFMetadataReadError(f"CTF metadata at {path} must contain a JSON object")
        return None
    return CTFMetadata.from_dict(data)


def save_ctf_metadata(workspace_dir: str | Path, metadata: CTFMetadata) -> Path:
    metadata.touch()
    path = metadata_path(workspace_dir)
    payload = json.dumps(metadata.to_dict(), indent=2, ensure_ascii=False) + "\n"
    _atomic_write_text(path, payload)
    return path


def init_ctf_metadata(
    workspace_dir: str | Path,
    *,
    challenge_name: str = "",
    category: str = "",
    source: str = "",
) -> CTFMetadata:
    existing = load_ctf_metadata(workspace_dir, strict=True)
    metadata = existing or CTFMetadata.new()
    if challenge_name:
        metadata.challenge_name = _clean_text(challenge_name)
    if category:
        metadata.category = _clean_text(category, 80)
    if source:
        metadata.source = _clean_text(source, 500)
    metadata.status = metadata.status or "draft"
    save_ctf_metadata(workspace_dir, metadata)
    return metadata


def add_artifact(workspace_dir: str | Path, artifact: str) -> CTFMetadata:
    metadata = load_ctf_metadata(workspace_dir, strict=True) or CTFMetadata.new()
    item = _clean_text(artifact, 500)
    _append_unique_bounded(metadata.artifacts, item)
    save_ctf_metadata(workspace_dir, metadata)
    return metadata


def add_remote_target(workspace_dir: str | Path, target: str) -> CTFMetadata:
    metadata = load_ctf_metadata(workspace_dir, strict=True) or CTFMetadata.new()
    item = _clean_text(target, 500)
    _append_unique_bounded(metadata.remote_targets, item)
    save_ctf_metadata(workspace_dir, metadata)
    return metadata


def add_flag_candidate(workspace_dir: str | Path, flag: str) -> CTFMetadata:
    metadata = load_ctf_metadata(workspace_dir, strict=True) or CTFMetadata.new()
    item = _clean_text(flag, 500)
    _append_unique_bounded(metadata.flag_candidates, item)
    if item:
        metadata.status = "flag-candidate"
    save_ctf_metadata(workspace_dir, metadata)
    return metadata


def confirm_flag_candidate(workspace_dir: str | Path, flag: str = "") -> CTFMetadata:
    metadata = load_ctf_metadata(workspace_dir, strict=True) or CTFMetadata.new()
    item = _clean_text(flag, 500)
    _append_unique_bounded(metadata.flag_candidates, item)
    if not metadata.flag_candidates:
        return metadata
    metadata.status = "solved"
    save_ctf_metadata(workspace_dir, metadata)
    return metadata


def ctf_audit_metadata(workspace_dir: str | Path) -> dict[str, Any] | None:
    metadata = load_ctf_metadata(workspace_dir)
    if metadata is None:
        return None
    payload = {
        "challenge_name": metadata.challenge_name,
        "category": metadata.category,
        "workspace": str(Path(workspace_dir).expanduser()),
        "status": metadata.status,
    }
    if metadata.artifacts:
        payload["artifacts"] = list(metadata.artifacts)
    if metadata.remote_targets:
        payload["remote_targets"] = list(metadata.remote_targets)
    if metadata.flag_candidates:
        payload["flag_candidates"] = list(metadata.flag_candidates)
    return {
        key: value
        for key, value in payload.items()
        if value is not None and value != "" and value != []
    }


def format_ctf_status(metadata: CTFMetadata | None, workspace_dir: str | Path) -> str:
    if metadata is None:
        return (
            "No CTF metadata found.\n"
            f"Workspace: {Path(workspace_dir).expanduser()}\n"
            "Start with: /ctf init <challenge name>"
        )

    def _items(values: list[str]) -> str:
        return ", ".join(values) if values else "-"

    return "\n".join([
        "CTF workspace metadata",
        f"  Challenge : {metadata.challenge_name or '-'}",
        f"  Category  : {metadata.category or '-'}",
        f"  Source    : {metadata.source or '-'}",
        f"  Status    : {metadata.status or '-'}",
        f"  Artifacts : {_items(metadata.artifacts)}",
        f"  Remotes   : {_items(metadata.remote_targets)}",
        f"  Flags     : {_items(metadata.flag_candidates)}",
        f"  Updated   : {metadata.updated_at or '-'}",
    ])


def _redact_line(line: str) -> str:
    if _SECRET_KEY_RE.search(line):
        return "[redacted sensitive line]"
    return line


def _escape_table_cell(value: Any) -> str:
    text = _clean_text(value, 500)
    if not text:
        return "-"
    return text.replace("|", r"\|").replace("`", r"\`")


def _summarize_messages(messages: list[Any], max_items: int = 12) -> list[str]:
    items: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "")).strip()
        if role not in {"user", "assistant", "tool"}:
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        first_line = _redact_line(content.splitlines()[0].strip())
        if len(first_line) > 180:
            first_line = first_line[:177] + "..."
        items.append(f"- {role}: {first_line}")
        if len(items) >= max_items:
            break
    return items


def build_ctf_writeup(
    *,
    metadata: CTFMetadata,
    messages: list[Any],
    session_id: str = "",
) -> str:
    solved = metadata.status == "solved" and bool(metadata.flag_candidates)
    title = metadata.challenge_name or "Untitled CTF Challenge"
    if solved:
        flag_text = metadata.flag_candidates[-1]
    elif metadata.flag_candidates:
        flag_text = f"Unconfirmed flag candidate: {metadata.flag_candidates[-1]}"
    else:
        flag_text = "Draft: no confirmed flag candidate recorded."
    status = "solved" if solved else (metadata.status or "draft")
    evidence = _summarize_messages(messages)
    if not evidence:
        evidence = ["- No conversation evidence recorded yet."]

    artifacts = metadata.artifacts or ["-"]
    remotes = metadata.remote_targets or ["-"]

    lines = [
        f"# {title} Writeup",
        "",
        "| Field | Value |",
        "|------|-------|",
        f"| Challenge | {_escape_table_cell(title)} |",
        f"| Category | {_escape_table_cell(metadata.category)} |",
        f"| Source | {_escape_table_cell(metadata.source)} |",
        f"| Status | {_escape_table_cell(status)} |",
        f"| Session | {_escape_table_cell(session_id)} |",
        "",
        "## Environment",
        "",
        "- Workspace metadata: `ctf.json`",
        f"- Updated: {metadata.updated_at or '-'}",
        "",
        "## Artifacts",
        "",
    ]
    lines.extend(f"- {item}" for item in artifacts)
    lines.extend([
        "",
        "## Remote Targets",
        "",
    ])
    lines.extend(f"- {item}" for item in remotes)
    lines.extend([
        "",
        "## Approach",
        "",
        "Draft notes generated from the recorded PawnLogic session. Review and edit before submission.",
        "",
        "## Evidence",
        "",
    ])
    lines.extend(evidence)
    lines.extend([
        "",
        "## Exploit Or Script",
        "",
        "Add final exploit commands or script snippets here.",
        "",
        "## Flag",
        "",
        flag_text,
        "",
        "## Lessons Learned",
        "",
        "- Add challenge-specific lessons after verification.",
        "",
        "## Attribution",
        "",
        "CTF skill packs, if used, should be attributed according to `THIRD_PARTY_NOTICES.md`.",
        "",
    ])
    return "\n".join(lines)


def export_ctf_writeup(
    workspace_dir: str | Path,
    *,
    messages: list[Any],
    session_id: str = "",
) -> Path:
    metadata = load_ctf_metadata(workspace_dir, strict=True) or CTFMetadata.new()
    save_ctf_metadata(workspace_dir, metadata)
    output = writeup_path(workspace_dir)
    _atomic_write_text(
        output,
        build_ctf_writeup(metadata=metadata, messages=messages, session_id=session_id),
    )
    return output
