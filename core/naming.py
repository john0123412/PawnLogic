"""
core/naming.py — Semantic session naming and workspace aliases.
"""

import json
import os
import re
from pathlib import Path

from config import WORKSPACE_DIR, get_api_format, NAMING_MODEL_CHAIN, MODELS, validate_api_key, is_fast_model, find_fast_peer
from core.api_client import stream_request
from core.logger import logger


_SLUG_RE = re.compile(r"[^a-z0-9_-]+")
_WEAK_USER_MESSAGES = {"hi", "hello", "hey", "你好", "您好", "在吗", "test", "测试"}


def pick_naming_model(fallback: str) -> str:
    """Return a fast-tier, non-reasoning model for background naming tasks."""
    from config import MODELS

    def _ok_for_naming(alias: str) -> bool:
        """Must have a valid key AND must NOT be a reasoning model."""
        if not alias or alias not in MODELS:
            return False
        if MODELS[alias].get("reasoning", False):
            return False
        try:
            ok, _ = validate_api_key(alias)
            return ok
        except Exception:
            return False

    # 1. If fallback is already fast + non-reasoning, use it directly.
    if is_fast_model(fallback) and _ok_for_naming(fallback):
        return fallback

    # 2. Fast peer in same provider that is non-reasoning.
    m = MODELS.get(fallback)
    if m:
        provider = m.get("provider", "")
        for alias, cfg in MODELS.items():
            if cfg.get("provider") != provider:
                continue
            if not is_fast_model(alias):
                continue
            if _ok_for_naming(alias):
                return alias

    # 3. Walk NAMING_MODEL_CHAIN for any available non-reasoning model.
    for alias in NAMING_MODEL_CHAIN:
        if _ok_for_naming(alias):
            return alias

    # 4. Any non-reasoning model with a valid key.
    for alias in MODELS:
        if _ok_for_naming(alias):
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
        if "已写入" in content or "write_file" in content:
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
    # 剥离 Markdown 代码块（```json ... ``` 或 ``` ... ```）
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
    # 优先收集有实质文本的 user/assistant 消息，跳过系统注入信号和纯工具调用
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
    # 有效文本不足 2 条时，补充工具调用名称作为上下文
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
        "你是会话命名器。根据下面的 CLI agent 对话，为该任务生成便于归类检索的名称。\n"
        "只输出一个 JSON object，不要 Markdown，不要解释。\n"
        "JSON schema: {\"title\": \"中文友好标题\", \"slug\": \"ascii-safe-name\"}\n"
        "title: 4-18 个中文字符或简短英文短语。\n"
        "slug: 只用小写 ASCII 字母、数字、连字符或下划线，8-48 字符。\n\n"
        f"cwd_basename: {Path(cwd).name or cwd}\n"
        "conversation:\n" + "\n".join(snippets)
    )
    req_messages = [
        {"role": "system", "content": "Return JSON only."},
        {"role": "user", "content": prompt},
    ]

    text = ""
    kwargs = {}
    # 只对明确支持 json_object 的 OpenAI 官方模型传 response_format
    _SUPPORTS_JSON_FORMAT = {"gpt-4o", "gpt-4.1", "gpt-4-turbo"}
    if model_alias in _SUPPORTS_JSON_FORMAT:
        kwargs["response_format"] = {"type": "json_object"}
    for delta in stream_request(
        req_messages,
        model_alias,
        tools_schema=None,
        max_tokens=128,
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
