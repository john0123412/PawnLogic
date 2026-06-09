"""
tools/vision.py - local image recognition and multimodal analysis.

Tool: analyze_local_image(path, prompt, model_alias?)
  1. Read a local image and Base64-encode it.
  2. Build an OpenAI Vision-compatible payload.
  3. Prefer glm-4v-plus (ZhipuAI), then gpt-4o (OpenRouter).
  4. Call call_once() in non-streaming mode and return analysis text.

Supported formats: jpg / jpeg / png / gif / webp / bmp.
"""

import os, base64, mimetypes
from pathlib import Path
from config import (
    MODELS, get_best_vision_model, list_vision_models,
)
from core.api_client import call_once
from utils.ansi import c, BLUE

# MIME types accepted by OpenAI-compatible vision APIs.
_MIME_MAP = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".gif":  "image/gif",
    ".webp": "image/webp",
    ".bmp":  "image/bmp",
}

# ════════════════════════════════════════════════════════
# Main tool function.
# ════════════════════════════════════════════════════════

def analyze_local_image(a: dict) -> str:
    """
    Analyze a local image.

    Args:
      path: local image path (required)
      prompt: analysis prompt (optional)
      model_alias: optional vision model alias; auto-selects by default
      max_tokens: max output tokens (default 1024)
    """
    image_path   = a.get("path", "")
    prompt       = a.get("prompt", "Describe this image in detail, including all visible text, code, diagrams, or scene information.")
    model_alias  = a.get("model_alias", "")
    max_tokens   = int(a.get("max_tokens", 1024))

    # 1. Validate file.
    p = Path(image_path).expanduser()
    if not p.exists():
        return f"ERROR: image file does not exist: {image_path}"
    if not p.is_file():
        return f"ERROR: path is not a file: {image_path}"

    suffix = p.suffix.lower()
    mime   = _MIME_MAP.get(suffix)
    if not mime:
        # Try system mimetype detection.
        mime, _ = mimetypes.guess_type(str(p))
        if not mime or not mime.startswith("image/"):
            return (f"ERROR: unsupported image format '{suffix}'.\n"
                    f"Supported: {', '.join(_MIME_MAP.keys())}")

    file_size_mb = p.stat().st_size / (1024 * 1024)
    if file_size_mb > 10:
        return f"ERROR: image is too large ({file_size_mb:.1f}MB); compress it below 10MB."

    # 2. Select vision model.
    if model_alias:
        m = MODELS.get(model_alias)
        if not m:
            return f"ERROR: unknown model '{model_alias}'. Available vision models: {list_vision_models()}"
        if not m.get("vision"):
            return (f"ERROR: '{model_alias}' does not support vision analysis.\n"
                    f"Choose a vision model: {list_vision_models()}")
        from config import PROVIDERS
        prov   = PROVIDERS[m["provider"]]
        key    = os.environ.get(prov["api_key_env"], "")
        if not key:
            return (f"ERROR: {model_alias} requires {prov['api_key_env']}; "
                    f"export {prov['api_key_env']}=sk-...")
    else:
        # Auto-select.
        model_alias, _, _ = get_best_vision_model()
        if not model_alias:
            avail = list_vision_models()
            return (
                f"ERROR: no available vision model found.\n"
                f"Configure one of these API keys:\n"
                f"  ZHIPU_API_KEY      -> glm-4v-plus\n"
                f"  OPENROUTER_API_KEY -> gpt-4o\n\n"
                f"All vision models: {avail}\n"
                f"After configuration, switch with /model glm-4v or pass model_alias in the tool call."
            )

    print(c(BLUE, f"  [Vision] analyzing image: {p.name}  ({file_size_mb:.2f}MB)  model: {model_alias}"))

    # 3. Base64 encode.
    try:
        raw_bytes  = p.read_bytes()
        b64_data   = base64.b64encode(raw_bytes).decode("ascii")
        data_url   = f"data:{mime};base64,{b64_data}"
    except Exception as e:
        return f"ERROR: failed to read or encode image: {e}"

    # 4. Build multimodal payload.
    # OpenAI Vision-compatible format: content is a list.
    # Compatible with ZhipuAI GLM-4V, OpenRouter GPT-4o, and other compatible models.
    vision_payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url":    data_url,
                            "detail": "high",   # high / low / auto
                        },
                    },
                ],
            }
        ],
        # model / max_tokens / stream are filled by call_once.
    }

    # 5. Call API.
    result, err = call_once(
        messages       = [],
        model_alias    = model_alias,
        max_tokens     = max_tokens,
        vision_payload_override = vision_payload,
    )

    if err:
        return f"ERROR: vision API call failed: {err}"

    return (
        f"[Image analysis - model: {model_alias} | file: {p.name}]\n"
        f"{result}"
    )

# ════════════════════════════════════════════════════════
# Schema
# ════════════════════════════════════════════════════════

VISION_SCHEMAS = [
    {"type": "function", "function": {
        "name":        "analyze_local_image",
        "description": (
            "Read a local image and call a vision AI model to analyze its content.\n"
            "Supports jpg/png/gif/webp/bmp. Auto-selects glm-4v-plus or gpt-4o.\n"
            "Use for screenshots, code/text in images, architecture diagrams, and CTF image tasks."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type":        "string",
                    "description": "Local image file path.",
                },
                "prompt": {
                    "type":        "string",
                    "description": "Analysis prompt, such as 'extract all code from this image' or 'describe this architecture diagram'.",
                },
                "model_alias": {
                    "type":        "string",
                    "description": "Optional vision model alias, such as glm-4v or gpt-4o.",
                },
                "max_tokens": {
                    "type":        "integer",
                    "description": "Maximum output tokens (default 1024).",
                },
            },
            "required": ["path"],
        },
    }},
]
