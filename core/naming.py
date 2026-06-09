"""
core/naming.py — Semantic session naming and workspace aliases.
"""

import json
import re
from pathlib import Path

from config import WORKSPACE_DIR, NAMING_MODEL_CHAIN, MODELS, validate_api_key, is_fast_model, find_fast_peer
from core.api_client import stream_request
from core.logger import logger


_SLUG_RE = re.compile(r"[^a-z0-9_-]+")
_WEAK_USER_MESSAGES = {
    "hi", "hello", "hey",
    "\u4f60\u597d", "\u60a8\u597d", "\u5728\u5417", "test", "\u6d4b\u8bd5",
}


def pick_naming_model(fallback: str) -> str:
    """Return a fast-tier model for background naming tasks.

    Priority:
    1. If fallback is already fast-tier, use it directly.
    2. Find a fast peer in the same provider as fallback.
    3. Walk NAMING_MODEL_CHAIN for any available fast model.
    4. Return fallback.
    """
    if is_fast_model(fallback):
        ok, _ = validate_api_key(fallback)
        if ok:
            return fallback

    peer = find_fast_peer(fallback)
    if peer:
        return peer

    for alias in NAMING_MODEL_CHAIN:
        if not alias or alias not in MODELS:
            continue
        try:
            ok, _ = validate_api_key(alias)
        except Exception:
            ok = False
        if ok:
            return alias
    return fallback


def stable_workspace_dir(session_id: str) -> str:
    path = Path(WORKSPACE_DIR).expanduser() / f"session_{session_id}"
    path.mkdir(parents=True, exist_ok=True)
    return str(path.resolve())


def normalize_slug(raw: str, fallback: str) -> str:
    text = (raw or "").strip().lower()
    text = text.replace(" ", "-")
    text = _SLUG_RE.sub("-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-_")
    if len(text) > 48:
        text = text[:48].strip("-_")
    if len(text) < 8:
        text = fallback
    return text


def should_name_session(messages: list) -> bool:
    user_texts: list[str] = []
    has_tool_or_write = False

    for msg in messages:
        role = msg.get("role")
        if msg.get("tool_calls") or role == "tool":
            has_tool_or_write = True
        content = str(msg.get("content") or "")
        if "\u5df2\u5199\u5165" in content or "write_file" in content:
            has_tool_or_write = True
        if role == "user":
            stripped = content.strip()
            lowered = stripped.lower()
            if not stripped or stripped.startswith("/") or lowered in _WEAK_USER_MESSAGES:
                continue
            user_texts.append(stripped)

    if has_tool_or_write and user_texts:
        return True
    if any(len(t) >= 20 for t in user_texts):
        return True
    return len(user_texts) >= 2 and sum(len(t) for t in user_texts) >= 40


def create_workspace_alias(session_id: str, slug: str, workspace_dir: str) -> str:
    by_name = Path(WORKSPACE_DIR).expanduser() / "by-name"
    by_name.mkdir(parents=True, exist_ok=True)
    target = Path(workspace_dir).expanduser().resolve()
    short = session_id[-4:] if len(session_id) >= 4 else session_id

    candidates = [slug, f"{slug}-{short}"]
    candidates.extend(f"{slug}-{short}-{i}" for i in range(2, 100))

    for candidate in candidates:
        link = by_name / candidate
        try:
            if link.is_symlink():
                existing = link.resolve()
                if existing == target:
                    return candidate
                continue
            if link.exists():
                continue
            link.symlink_to(Path("..") / target.name)
            return candidate
        except OSError as exc:
            logger.warning("Workspace alias symlink failed | alias={} exc={!r}", candidate, exc)
            continue
    return f"{slug}-{short}"


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty naming response")
    # Strip Markdown code fences such as ```json ... ``` or ``` ... ```.
    md = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if md:
        text = md.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def generate_session_name(
    *,
    messages: list,
    model_alias: str,
    session_id: str,
    cwd: str,
) -> dict:
    fallback_slug = f"task_{session_id[:8]}"
    snippets = []
    # Prefer substantive user/assistant text, skipping system injections and tool-only calls.
    for msg in messages:
        role = msg.get("role", "")
        if role in ("system", "tool"):
            continue
        content = str(msg.get("content") or "").strip()
        if content.startswith("[SYSTEM:") or content.startswith("[System]"):
            continue
        if content and role in ("user", "assistant"):
            snippets.append(f"[{role}] {content[:400]}")
        if len(snippets) >= 6:
            break
    # If there are fewer than 2 useful snippets, add tool-call names as context.
    if len(snippets) < 2:
        for msg in messages:
            if msg.get("tool_calls"):
                names = ", ".join(
                    tc.get("function", {}).get("name", "?")
                    for tc in msg.get("tool_calls", [])
                )
                snippets.append(f"[tool_calls] {names}")
            if len(snippets) >= 6:
                break

    prompt = (
        "You are a session naming assistant. Based on the CLI agent conversation below, "
        "generate a name that is easy to categorize and search.\n"
        "Output only one JSON object. No Markdown. No explanation.\n"
        "JSON schema: {\"title\": \"short friendly title\", \"slug\": \"ascii-safe-name\"}\n"
        "title: 4-8 English words or a concise phrase.\n"
        "slug: lowercase ASCII letters, digits, hyphens, or underscores only; 8-48 chars.\n\n"
        f"cwd_basename: {Path(cwd).name or cwd}\n"
        "conversation:\n" + "\n".join(snippets)
    )
    req_messages = [
        {"role": "system", "content": "Return JSON only."},
        {"role": "user", "content": prompt},
    ]

    text = ""
    kwargs = {}
    # Only pass response_format to official OpenAI models known to support json_object.
    _SUPPORTS_JSON_FORMAT = {"gpt-4o", "gpt-4.1", "gpt-4-turbo"}
    if model_alias in _SUPPORTS_JSON_FORMAT:
        kwargs["response_format"] = {"type": "json_object"}

    # Reasoning models consume tokens before final content, so 128 max_tokens is
    # often too small. Increase the budget and suppress reasoning in the prompt.
    from core.api_client import _is_reasoning_model
    is_reasoning = _is_reasoning_model(model_alias)
    naming_max_tokens = 512 if is_reasoning else 128
    if is_reasoning:
        req_messages[0]["content"] = "Return JSON only. No reasoning, no explanation."

    for delta in stream_request(
        req_messages,
        model_alias,
        tools_schema=None,
        max_tokens=naming_max_tokens,
        **kwargs,
    ):
        if "_error" in delta:
            raise RuntimeError(delta["_error"])
        choices = delta.get("choices") or []
        if choices:
            text += choices[0].get("delta", {}).get("content", "") or ""

    data = _extract_json(text)
    title = str(data.get("title") or "").strip()
    slug = normalize_slug(str(data.get("slug") or ""), fallback_slug)
    if not title:
        title = slug.replace("-", " ")
    return {"title": title[:64], "slug": slug}
