"""
tools/vision.py — 模块 1：本地图片识别与多模态分析

工具：analyze_local_image(path, prompt, model_alias?)
  1. 读取本地图片 → Base64 编码
  2. 构建 OpenAI Vision 格式 payload（content 为列表）
  3. 优先使用 glm-4v-plus（ZhipuAI），其次 gpt-4o（OpenRouter）
  4. 调用 call_once() 非流式接口，返回分析文本

支持格式: jpg / jpeg / png / gif / webp / bmp
"""

import os, base64, mimetypes
from pathlib import Path
from config import (
    MODELS, get_api_config, get_best_vision_model, list_vision_models,
    DYNAMIC_CONFIG,
)
from core.api_client import call_once
from utils.ansi import c, BLUE, YELLOW, GREEN, RED, GRAY

# ── MIME 类型映射（OpenAI vision 接受的格式）─────────────
_MIME_MAP = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".gif":  "image/gif",
    ".webp": "image/webp",
    ".bmp":  "image/bmp",
}

# ════════════════════════════════════════════════════════
# 工具主函数
# ════════════════════════════════════════════════════════

def analyze_local_image(a: dict) -> str:
    """
    分析本地图片。

    参数:
      path         — 本地图片路径（必须）
      prompt       — 分析提示词（可选，默认"请详细描述这张图片"）
      model_alias  — 指定视觉模型别名（可选，默认自动选择最优可用模型）
      max_tokens   — 最大输出 token（可选，默认 1024）
    """
    image_path   = a.get("path", "")
    prompt       = a.get("prompt", "请详细描述这张图片的内容，包括所有可见的文字、代码、图表或场景信息。")
    model_alias  = a.get("model_alias", "")
    max_tokens   = int(a.get("max_tokens", 1024))

    # ── 1. 验证文件 ────────────────────────────────────
    p = Path(image_path).expanduser()
    if not p.exists():
        return f"ERROR: 图片文件不存在: {image_path}"
    if not p.is_file():
        return f"ERROR: 路径不是文件: {image_path}"

    suffix = p.suffix.lower()
    mime   = _MIME_MAP.get(suffix)
    if not mime:
        # 尝试系统 mimetypes 猜测
        mime, _ = mimetypes.guess_type(str(p))
        if not mime or not mime.startswith("image/"):
            return (f"ERROR: 不支持的图片格式 '{suffix}'。\n"
                    f"支持: {', '.join(_MIME_MAP.keys())}")

    file_size_mb = p.stat().st_size / (1024 * 1024)
    if file_size_mb > 10:
        return f"ERROR: 图片过大 ({file_size_mb:.1f}MB)，请压缩到 10MB 以内。"

    # ── 2. 选择视觉模型 ────────────────────────────────
    if model_alias:
        m = MODELS.get(model_alias)
        if not m:
            return f"ERROR: 未知模型 '{model_alias}'，可用视觉模型: {list_vision_models()}"
        if not m.get("vision"):
            return (f"ERROR: '{model_alias}' 不支持视觉分析。\n"
                    f"请选择视觉模型: {list_vision_models()}")
        from config import PROVIDERS
        prov   = PROVIDERS[m["provider"]]
        key    = os.environ.get(prov["api_key_env"], "")
        if not key:
            return (f"ERROR: {model_alias} 需要 {prov['api_key_env']}，"
                    f"请 export {prov['api_key_env']}=sk-...")
    else:
        # 自动选择
        model_alias, _, _ = get_best_vision_model()
        if not model_alias:
            avail = list_vision_models()
            return (
                f"ERROR: 未找到可用的视觉模型。\n"
                f"请配置以下任一 API Key:\n"
                f"  ZHIPU_API_KEY   → glm-4v-plus (推荐，国内直连)\n"
                f"  OPENROUTER_API_KEY → gpt-4o (需代理)\n\n"
                f"所有视觉模型: {avail}\n"
                f"配置后用 /model glm-4v 切换，或在工具调用时指定 model_alias。"
            )

    print(c(BLUE, f"  🖼  分析图片: {p.name}  ({file_size_mb:.2f}MB)  模型: {model_alias}"))

    # ── 3. Base64 编码 ─────────────────────────────────
    try:
        raw_bytes  = p.read_bytes()
        b64_data   = base64.b64encode(raw_bytes).decode("ascii")
        data_url   = f"data:{mime};base64,{b64_data}"
    except Exception as e:
        return f"ERROR: 读取/编码图片失败: {e}"

    # ── 4. 构建多模态 payload ──────────────────────────
    # 使用 OpenAI Vision 格式：content 为 list
    # 兼容: ZhipuAI GLM-4V / OpenRouter GPT-4o / 其他兼容模型
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
        # model / max_tokens / stream 由 call_once 填入
    }

    # ── 5. 调用 API ────────────────────────────────────
    result, err = call_once(
        messages       = [],          # 由 vision_payload_override 提供
        model_alias    = model_alias,
        max_tokens     = max_tokens,
        vision_payload_override = vision_payload,
    )

    if err:
        return f"ERROR: 视觉 API 调用失败: {err}"

    return (
        f"[图片分析 — 模型: {model_alias} | 文件: {p.name}]\n"
        f"{result}"
    )

# ════════════════════════════════════════════════════════
# Schema
# ════════════════════════════════════════════════════════

VISION_SCHEMAS = [
    {"type": "function", "function": {
        "name":        "analyze_local_image",
        "description": (
            "读取本地图片并调用视觉 AI 分析其内容。\n"
            "支持 jpg/png/gif/webp/bmp。自动选择 glm-4v-plus 或 gpt-4o。\n"
            "适用场景：分析截图、读取图片中的代码/文字、理解架构图、CTF 图片题等。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type":        "string",
                    "description": "本地图片文件路径",
                },
                "prompt": {
                    "type":        "string",
                    "description": "分析提示词，如'提取图片中所有代码'或'描述架构图'",
                },
                "model_alias": {
                    "type":        "string",
                    "description": "视觉模型别名（可选）：glm-4v 或 gpt-4o",
                },
                "max_tokens": {
                    "type":        "integer",
                    "description": "最大输出 token（默认 1024）",
                },
            },
            "required": ["path"],
        },
    }},
]
