"""
config/providers.py — API Provider 与模型注册表

所有 API Key 通过环境变量注入，代码中无任何硬编码凭证。
"""
import os
import json
from pathlib import Path

PROVIDERS: dict[str, dict] = {
    "pawn": {
        "base_url":    "https://inference-api.nousresearch.com/v1/chat/completions",
        "api_key_env": "PAWN_API_KEY",
        "label":       "PawnLogic Engine (Nous Research)",
        "models_hint": "hermes, hermes405",
        "api_format":  "openai",
    },
    "openai": {
        "base_url":    "https://api.openai.com/v1/chat/completions",
        "api_key_env": "OPENAI_API_KEY",
        "label":       "OpenAI",
        "models_hint": "gpt-4o, gpt-4o-mini, gpt-4-turbo",
        "api_format":  "openai",
    },
    "deepseek": {
        "base_url":    "https://api.deepseek.com/v1/chat/completions",
        "api_key_env": "DEEPSEEK_API_KEY",
        "label":       "DeepSeek",
        "models_hint": "deepseek-chat (V3), deepseek-reasoner (R1), deepseek-v4-pro, deepseek-v4-flash",
        "api_format":  "openai",
    },
    "qwen": {
        "base_url":    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "api_key_env": "QWEN_API_KEY",
        "label":       "Alibaba Qwen (通义千问)",
        "models_hint": "qwen-max, qwen-plus, qwen-turbo, qwen-3.0-max",
        "api_format":  "openai",
    },
    "zhipuai": {
        "base_url":    "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "api_key_env": "ZHIPU_API_KEY",
        "label":       "ZhipuAI (智谱)",
        "models_hint": "glm-5.1, glm-4.7-plus, glm-4.5-air, glm-4v-plus（视觉）",
        "api_format":  "openai",
    },
    "siliconflow": {
        "base_url":    "https://api.siliconflow.cn/v1/chat/completions",
        "api_key_env": "SILICON_API_KEY",
        "label":       "SiliconFlow (硅基流动)",
        "models_hint": "deepseek-ai/DeepSeek-V3, Qwen/Qwen2.5-72B-Instruct",
        "api_format":  "openai",
    },
    "openrouter": {
        "base_url":    "https://openrouter.ai/api/v1/chat/completions",
        "api_key_env": "OPENROUTER_API_KEY",
        "label":       "OpenRouter",
        "models_hint": "openai/gpt-4o, anthropic/claude-3.5-sonnet, …",
        "api_format":  "openai",
    },
    "moonshot": {
        "base_url":    "https://api.moonshot.cn/v1/chat/completions",
        "api_key_env": "MOONSHOT_API_KEY",
        "label":       "Moonshot (Kimi)",
        "models_hint": "moonshot-v1-128k, moonshot-v1-32k",
        "api_format":  "openai",
    },
    "minimax": {
        "base_url":    "https://api.minimax.chat/v1/text_generation_v2",
        "api_key_env": "MINIMAX_API_KEY",
        "label":       "MiniMax (海螺)",
        "models_hint": "abab6.5s-chat, abab6.5-chat",
        "api_format":  "openai",
    },
    "groq": {
        "base_url":    "https://api.groq.com/openai/v1/chat/completions",
        "api_key_env": "GROQ_API_KEY",
        "label":       "Groq (Ultra-Fast)",
        "models_hint": "llama-3.3-70b-versatile, mixtral-8x7b-32768",
        "api_format":  "openai",
    },
    "xiaomi": {
        "base_url":    "https://token-plan-cn.xiaomimimo.com/v1/chat/completions",
        "api_key_env": "XIAOMI_API_KEY",
        "label":       "Xiaomi MiMo (小米)",
        "models_hint": "MiMo-V2.5-Pro, MiMo-V2.5, MiMo-V2-Pro, MiMo-V2-Omni",
        "api_format":  "openai",
    },
    "local": {
        "base_url":    os.environ.get("LOCAL_API_URL",
                                      "http://localhost:11434/v1/chat/completions"),
        "api_key_env": "LOCAL_API_KEY",
        "label":       "本地 Ollama",
        "models_hint": "无需 Key，需先执行 ollama serve",
        "api_format":  "openai",
    },
    "anthropic": {
        "base_url":    "https://api.anthropic.com/v1/messages",
        "api_key_env": "ANTHROPIC_API_KEY",
        "label":       "Anthropic (Claude)",
        "models_hint": "claude-opus-4-7, claude-sonnet-4-6, claude-haiku-4-5",
        "api_format":  "anthropic",
    },
}

MODELS: dict[str, dict] = {
    "hermes": {
        "id":       "NousResearch/Hermes-4-70B",
        "provider": "pawn",
        "desc":     "PawnLogic Default — 极高指令遵循度",
        "color":    "\033[95m",
        "vision":   False,
    },
    "hermes405": {
        "id":       "NousResearch/Hermes-4-405B",
        "provider": "pawn",
        "desc":     "Top-Tier Hermes — 旗舰，按量计费",
        "color":    "\033[91m",
        "vision":   False,
    },
    "gpt-4o": {
        "id":       "gpt-4o",
        "provider": "openai",
        "desc":     "OpenAI GPT-4o — 视觉+强推理",
        "color":    "\033[97m",
        "vision":   True,
    },
    "gpt-4o-mini": {
        "id":       "gpt-4o-mini",
        "provider": "openai",
        "desc":     "OpenAI GPT-4o Mini — 轻量高速",
        "color":    "\033[37m",
        "vision":   True,
    },
    "ds-chat": {
        "id":       "deepseek-chat",
        "provider": "deepseek",
        "desc":     "DeepSeek V3 — 高性价比日常主力",
        "color":    "\033[92m",
        "vision":   False,
    },
    "ds-r1": {
        "id":       "deepseek-reasoner",
        "provider": "deepseek",
        "desc":     "DeepSeek R1 — 深度推理（CTF 首选）",
        "color":    "\033[1;32m",
        "vision":   False,
    },
    "ds-v4-pro": {
        "id":       "deepseek-v4-pro",
        "provider": "deepseek",
        "desc":     "DeepSeek V4 Pro — 全能旗舰",
        "color":    "\033[92m",
        "vision":   False,
    },
    "ds-v4-flash": {
        "id":       "deepseek-v4-flash",
        "provider": "deepseek",
        "desc":     "DeepSeek V4 Flash — 毫秒级响应",
        "color":    "\033[32m",
        "vision":   False,
    },
    "qwen-max": {
        "id":       "qwen-max",
        "provider": "qwen",
        "desc":     "通义千问 Max — 旗舰综合能力",
        "color":    "\033[94m",
        "vision":   False,
    },
    "qwen-turbo": {
        "id":       "qwen-turbo",
        "provider": "qwen",
        "desc":     "通义千问 Turbo — 极速轻量",
        "color":    "\033[34m",
        "vision":   False,
    },
    "qwen-3.0": {
        "id":       "qwen-3.0-max",
        "provider": "qwen",
        "desc":     "Qwen 3.0 Max — 阿里 2026 旗舰",
        "color":    "\033[94m",
        "vision":   False,
    },
    "glm-5.1": {
        "id":       "glm-5.1",
        "provider": "zhipuai",
        "desc":     "GLM-5.1 — 国产推理旗舰",
        "color":    "\033[93m",
        "vision":   False,
    },
    "glm-4.7": {
        "id":       "glm-4.7-plus",
        "provider": "zhipuai",
        "desc":     "GLM-4.7 Plus — 稳定生产力",
        "color":    "\033[33m",
        "vision":   False,
    },
    "glm-4.5-air": {
        "id":       "glm-4.5-air",
        "provider": "zhipuai",
        "desc":     "GLM-4.5 Air — 极高性价比",
        "color":    "\033[36m",
        "vision":   False,
    },
    "glm-4": {
        "id":       "glm-4-plus",
        "provider": "zhipuai",
        "desc":     "GLM-4-Plus — 通用旗舰（兼容别名）",
        "color":    "\033[33m",
        "vision":   False,
    },
    "glm-air": {
        "id":       "glm-4-air",
        "provider": "zhipuai",
        "desc":     "GLM-4-Air — 极速高性价比（兼容别名）",
        "color":    "\033[96m",
        "vision":   False,
    },
    "glm-4v": {
        "id":       "glm-4v-plus",
        "provider": "zhipuai",
        "desc":     "GLM-4V-Plus — 视觉多模态（国内直连）",
        "color":    "\033[36m",
        "vision":   True,
    },
    "sf-ds-v3": {
        "id":       "deepseek-ai/DeepSeek-V3",
        "provider": "siliconflow",
        "desc":     "SiliconFlow · DeepSeek-V3 — 低成本推理",
        "color":    "\033[32m",
        "vision":   False,
    },
    "sf-qwen72b": {
        "id":       "Qwen/Qwen2.5-72B-Instruct",
        "provider": "siliconflow",
        "desc":     "SiliconFlow · Qwen2.5-72B — 代码与逻辑",
        "color":    "\033[94m",
        "vision":   False,
    },
    "kimi": {
        "id":       "moonshot-v1-128k",
        "provider": "moonshot",
        "desc":     "Kimi 128K — 超长上下文日志分析",
        "color":    "\033[34m",
        "vision":   False,
    },
    "groq-llama3": {
        "id":       "llama-3.3-70b-versatile",
        "provider": "groq",
        "desc":     "Groq Llama 3.3 — 极速利用脚本生成",
        "color":    "\033[91m",
        "vision":   False,
    },
    "mimo-v2.5-pro": {
        "id":       "mimo-v2.5-pro",
        "provider": "xiaomi",
        "desc":     "小米 MiMo V2.5 Pro — 旗舰推理",
        "color":    "\033[96m",
        "vision":   False,
    },
    "mimo-v2.5": {
        "id":       "mimo-v2.5",
        "provider": "xiaomi",
        "desc":     "小米 MiMo V2.5 — 高性价比主力",
        "color":    "\033[36m",
        "vision":   False,
    },
    "mimo": {
        "id":       "mimo-v2.5",
        "provider": "xiaomi",
        "desc":     "小米 MiMo (legacy alias → mimo-v2.5)",
        "color":    "\033[36m",
        "vision":   False,
    },
    "mimo-v2-pro": {
        "id":       "mimo-v2-pro",
        "provider": "xiaomi",
        "desc":     "小米 MiMo V2 Pro — 稳定生产力",
        "color":    "\033[96m",
        "vision":   False,
    },
    "mimo-v2-omni": {
        "id":       "mimo-v2-omni",
        "provider": "xiaomi",
        "desc":     "小米 MiMo V2 Omni — 多模态全能",
        "color":    "\033[36m",
        "vision":   False,
    },
    "qwen-local": {
        "id":       "qwen2.5-7b-instruct",
        "provider": "local",
        "desc":     "Ollama 本地 — 离线可用，零泄密风险",
        "color":    "\033[90m",
        "vision":   False,
    },
    "claude-opus": {
        "id":       "claude-opus-4-7",
        "provider": "anthropic",
        "desc":     "Claude Opus 4.7 — 旗舰推理",
        "color":    "\033[91m",
        "vision":   True,
    },
    "claude-sonnet": {
        "id":       "claude-sonnet-4-6",
        "provider": "anthropic",
        "desc":     "Claude Sonnet 4.6 — 均衡性能",
        "color":    "\033[95m",
        "vision":   True,
    },
    "claude-haiku": {
        "id":       "claude-haiku-4-5",
        "provider": "anthropic",
        "desc":     "Claude Haiku 4.5 — 极速响应",
        "color":    "\033[35m",
        "vision":   True,
    },
}

DEFAULT_MODEL = "hermes"

NAMING_MODEL_CHAIN: list = [
    "claude-haiku",
    "ds-chat",
    "glm-4.5-air",
    "qwen-turbo",
]

VISION_PRIORITY = ["glm-4v", "gpt-4o", "gpt-4o-mini", "claude-sonnet", "claude-opus"]

CUSTOM_PROVIDERS_PATH = Path.home() / ".pawnlogic" / "custom_providers.json"


def get_api_config(model_alias: str) -> tuple[str, str]:
    """返回 (base_url, api_key)。Key 从环境变量读取，永不硬编码。"""
    m    = MODELS.get(model_alias, MODELS[DEFAULT_MODEL])
    prov = PROVIDERS.get(m["provider"], PROVIDERS["pawn"])
    key  = os.getenv(prov["api_key_env"], "")
    return prov["base_url"], key


def get_api_format(model_alias: str) -> str:
    """返回 'openai' 或 'anthropic'。"""
    m    = MODELS.get(model_alias, MODELS[DEFAULT_MODEL])
    prov = PROVIDERS.get(m["provider"], {})
    return prov.get("api_format", "openai")


def get_provider_config(model_alias: str) -> dict:
    """返回完整 provider 配置字典。"""
    m    = MODELS.get(model_alias, MODELS[DEFAULT_MODEL])
    prov = PROVIDERS.get(m["provider"], PROVIDERS["pawn"])
    key  = os.getenv(prov["api_key_env"], "")
    return {
        "base_url":   prov["base_url"],
        "api_key":    key,
        "api_format": prov.get("api_format", "openai"),
        "label":      prov.get("label", ""),
    }


def validate_api_key(model_alias: str) -> tuple[bool, str]:
    """检查指定模型的 Key 是否已正确配置。返回 (ok, missing_env_var)。"""
    _, key = get_api_config(model_alias)
    if not key:
        m    = MODELS.get(model_alias, MODELS[DEFAULT_MODEL])
        prov = PROVIDERS[m["provider"]]
        return False, prov["api_key_env"]
    return True, ""


def list_configured_models() -> list[str]:
    """返回所有已配置 Key 的模型别名列表。"""
    return [alias for alias in MODELS if validate_api_key(alias)[0]]


def get_best_vision_model() -> tuple[str | None, str | None, str | None]:
    """按优先级找到第一个已配置 Key 的视觉模型。"""
    for alias in VISION_PRIORITY:
        m = MODELS.get(alias)
        if not m or not m.get("vision"):
            continue
        url, key = get_api_config(alias)
        if key:
            return alias, url, key
    return None, None, None


def list_vision_models() -> list[str]:
    """返回所有标记了 vision=True 的模型别名。"""
    return [alias for alias, m in MODELS.items() if m.get("vision")]


def load_custom_providers() -> None:
    """从 custom_providers.json 加载用户自定义 provider，合并进 PROVIDERS/MODELS。"""
    if not CUSTOM_PROVIDERS_PATH.exists():
        return
    try:
        data = json.loads(CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    for name, prov in data.get("providers", {}).items():
        if name not in PROVIDERS:
            prov.setdefault("api_format", "openai")
            PROVIDERS[name] = prov
    for alias, model in data.get("models", {}).items():
        if alias not in MODELS:
            model.setdefault("color", "\033[37m")
            model.setdefault("vision", False)
            MODELS[alias] = model


def save_custom_provider(name: str, prov_cfg: dict, models_cfg: dict) -> None:
    """将自定义 provider 持久化到 custom_providers.json（不含 Key）。"""
    CUSTOM_PROVIDERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {"providers": {}, "models": {}}
    if CUSTOM_PROVIDERS_PATH.exists():
        try:
            data = json.loads(CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    data["providers"][name] = prov_cfg
    data["models"].update(models_cfg)
    CUSTOM_PROVIDERS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def remove_custom_provider(name: str) -> bool:
    """从 JSON 文件删除自定义 provider。返回是否成功。"""
    if not CUSTOM_PROVIDERS_PATH.exists():
        return False
    try:
        data = json.loads(CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return False
    if name not in data.get("providers", {}):
        return False
    del data["providers"][name]
    to_remove = [a for a, m in data.get("models", {}).items()
                 if m.get("provider") == name]
    for a in to_remove:
        del data["models"][a]
    CUSTOM_PROVIDERS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return True


# 模块加载时自动读取自定义 provider
load_custom_providers()
