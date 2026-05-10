"""
PawnLogic 1.1 (GitHub Release) — config.py
全生态 API 路由 · 2026 主流模型适配 · 视觉模型支持 · 三档预设 · 安全名单 · GSA 技能存档

所有 API Key 通过环境变量注入（.env 文件 + python-dotenv）。
代码中无任何硬编码凭证。
"""
import os
import re
import json
from pathlib import Path

# python-dotenv 可选：存在则自动加载项目根 .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # 未安装 python-dotenv 时降级为纯 os.environ

VERSION = "1.1"

# ── 路径 ──────────────────────────────────────────────────
SESSIONS_DIR       = Path.home() / ".pawnlogic" / "sessions"
DB_PATH            = Path.home() / ".pawnlogic" / "pawn.db"
GLOBAL_SKILLS_PATH = Path.home() / ".pawnlogic" / "global_skills.md"   # GSA 技能存档
# ★ P6: 技能引擎 — 本地技能目录
SKILLS_DIR         = Path(__file__).resolve().parent / "skills"
# ★ 新增：日志存储目录，供 core/logger.py 读取
LOG_DIR            = Path.home() / ".pawnlogic" / "logs"
# ★ 文件写入沙箱：所有工具产出的文件自动重定向到此目录
WORKSPACE_DIR      = str(Path.home() / ".pawnlogic" / "workspace")

# ════════════════════════════════════════════════════════
# 厂商注册表
# api_format: "openai"（默认）或 "anthropic"，决定请求构建和响应解析路径。
# api_key_env：从环境变量读取 Key，绝不硬编码。
# ════════════════════════════════════════════════════════
PROVIDERS: dict[str, dict] = {
    # ── PawnLogic 默认引擎（Nous Research）──────────────
    "pawn": {
        "base_url":    "https://inference-api.nousresearch.com/v1/chat/completions",
        "api_key_env": "PAWN_API_KEY",
        "label":       "PawnLogic Engine (Nous Research)",
        "models_hint": "hermes, hermes405",
        "api_format":  "openai",
    },
    # ── OpenAI ─────────────────────────────────────────
    "openai": {
        "base_url":    "https://api.openai.com/v1/chat/completions",
        "api_key_env": "OPENAI_API_KEY",
        "label":       "OpenAI",
        "models_hint": "gpt-4o, gpt-4o-mini, gpt-4-turbo",
        "api_format":  "openai",
    },
    # ── DeepSeek ────────────────────────────────────────
    "deepseek": {
        "base_url":    "https://api.deepseek.com/v1/chat/completions",
        "api_key_env": "DEEPSEEK_API_KEY",
        "label":       "DeepSeek",
        "models_hint": "deepseek-chat (V3), deepseek-reasoner (R1), deepseek-v4-pro, deepseek-v4-flash",
        "api_format":  "openai",
    },
    # ── 通义千问 Qwen (阿里云百炼) ──────────────────────
    "qwen": {
        "base_url":    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "api_key_env": "QWEN_API_KEY",
        "label":       "Alibaba Qwen (通义千问)",
        "models_hint": "qwen-max, qwen-plus, qwen-turbo, qwen-3.0-max",
        "api_format":  "openai",
    },
    # ── 智谱 GLM ────────────────────────────────────────
    "zhipuai": {
        "base_url":    "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "api_key_env": "ZHIPU_API_KEY",
        "label":       "ZhipuAI (智谱)",
        "models_hint": "glm-5.1, glm-4.7-plus, glm-4.5-air, glm-4v-plus（视觉）",
        "api_format":  "openai",
    },
    # ── 硅基流动 SiliconFlow ────────────────────────────
    "siliconflow": {
        "base_url":    "https://api.siliconflow.cn/v1/chat/completions",
        "api_key_env": "SILICON_API_KEY",
        "label":       "SiliconFlow (硅基流动)",
        "models_hint": "deepseek-ai/DeepSeek-V3, Qwen/Qwen2.5-72B-Instruct",
        "api_format":  "openai",
    },
    # ── OpenRouter（多模型聚合网关）─────────────────────
    "openrouter": {
        "base_url":    "https://openrouter.ai/api/v1/chat/completions",
        "api_key_env": "OPENROUTER_API_KEY",
        "label":       "OpenRouter",
        "models_hint": "openai/gpt-4o, anthropic/claude-3.5-sonnet, …",
        "api_format":  "openai",
    },
    # ── Moonshot (Kimi) ─────────────────────────────────
    "moonshot": {
        "base_url":    "https://api.moonshot.cn/v1/chat/completions",
        "api_key_env": "MOONSHOT_API_KEY",
        "label":       "Moonshot (Kimi)",
        "models_hint": "moonshot-v1-128k, moonshot-v1-32k",
        "api_format":  "openai",
    },
    # ── MiniMax (海螺) ──────────────────────────────────
    "minimax": {
        "base_url":    "https://api.minimax.chat/v1/text_generation_v2",
        "api_key_env": "MINIMAX_API_KEY",
        "label":       "MiniMax (海螺)",
        "models_hint": "abab6.5s-chat, abab6.5-chat",
        "api_format":  "openai",
    },
    # ── Groq（极速推理）────────────────────────────────
    "groq": {
        "base_url":    "https://api.groq.com/openai/v1/chat/completions",
        "api_key_env": "GROQ_API_KEY",
        "label":       "Groq (Ultra-Fast)",
        "models_hint": "llama-3.3-70b-versatile, mixtral-8x7b-32768",
        "api_format":  "openai",
    },
    # ── 小米 MiMo ────────────────────────────────────────
    "xiaomi": {
        "base_url":    "https://token-plan-cn.xiaomimimo.com/v1/chat/completions",
        "api_key_env": "XIAOMI_API_KEY",
        "label":       "Xiaomi MiMo (小米)",
        "models_hint": "MiMo-V2.5-Pro, MiMo-V2.5, MiMo-V2-Pro, MiMo-V2-Omni",
        "api_format":  "openai",
    },
    # ── 本地 Ollama ─────────────────────────────────────
    "local": {
        "base_url":    os.environ.get("LOCAL_API_URL",
                                      "http://localhost:11434/v1/chat/completions"),
        "api_key_env": "LOCAL_API_KEY",   # Ollama 通常无需 Key；留空即可
        "label":       "本地 Ollama",
        "models_hint": "无需 Key，需先执行 ollama serve",
        "api_format":  "openai",
    },
    # ── Anthropic (Claude) ──────────────────────────────
    "anthropic": {
        "base_url":    "https://api.anthropic.com/v1/messages",
        "api_key_env": "ANTHROPIC_API_KEY",
        "label":       "Anthropic (Claude)",
        "models_hint": "claude-opus-4-7, claude-sonnet-4-6, claude-haiku-4-5",
        "api_format":  "anthropic",
    },
}

# ════════════════════════════════════════════════════════
# 模型注册表
# vision=True  → 支持多模态图片输入
# provider     → 必须是 PROVIDERS 中已定义的键
# color        → ANSI 转义码，用于 CTF 滚动日志中区分不同模型输出
# ════════════════════════════════════════════════════════
MODELS: dict[str, dict] = {
    # ── PawnLogic 默认系列 ───────────────────────────────
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
    # ── OpenAI ─────────────────────────────────────────
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
    # ── DeepSeek V3 / R1 (稳定版) ───────────────────────
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
    # ── DeepSeek V4 系列 (前沿版) ────────────────────────
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
    # ── 通义千问 Qwen ────────────────────────────────────
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
    # ── 智谱 GLM 系列 ────────────────────────────────────
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
    # ── 硅基流动 SiliconFlow ─────────────────────────────
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
    # ── Moonshot (Kimi) ──────────────────────────────────
    "kimi": {
        "id":       "moonshot-v1-128k",
        "provider": "moonshot",
        "desc":     "Kimi 128K — 超长上下文日志分析",
        "color":    "\033[34m",
        "vision":   False,
    },
    # ── Groq (极速推理) ──────────────────────────────────
    "groq-llama3": {
        "id":       "llama-3.3-70b-versatile",
        "provider": "groq",
        "desc":     "Groq Llama 3.3 — 极速利用脚本生成",
        "color":    "\033[91m",
        "vision":   False,
    },
    # ── 小米 MiMo 系列 ──────────────────────────────────
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
    # ── 本地 Ollama ─────────────────────────────────────
    "qwen-local": {
        "id":       "qwen2.5-7b-instruct",
        "provider": "local",
        "desc":     "Ollama 本地 — 离线可用，零泄密风险",
        "color":    "\033[90m",
        "vision":   False,
    },
    # ── Anthropic Claude ─────────────────────────────────
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

# ════════════════════════════════════════════════════════
# API 配置获取
# ════════════════════════════════════════════════════════

def get_api_config(model_alias: str) -> tuple[str, str]:
    """
    返回 (base_url, api_key)。
    Key 通过 os.getenv 从环境变量读取，永远不在代码中硬编码。
    """
    m    = MODELS.get(model_alias, MODELS[DEFAULT_MODEL])
    prov = PROVIDERS.get(m["provider"], PROVIDERS["pawn"])
    key  = os.getenv(prov["api_key_env"], "")
    return prov["base_url"], key


def get_api_format(model_alias: str) -> str:
    """返回 API 格式: 'openai' 或 'anthropic'。"""
    m    = MODELS.get(model_alias, MODELS[DEFAULT_MODEL])
    prov = PROVIDERS.get(m["provider"], {})
    return prov.get("api_format", "openai")


def get_provider_config(model_alias: str) -> dict:
    """返回完整 provider 配置 {base_url, api_key, api_format, label}。"""
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
    """
    检查指定模型的 Key 是否已正确配置。
    返回 (ok: bool, missing_env_var: str)。
    """
    _, key = get_api_config(model_alias)
    if not key:
        m    = MODELS.get(model_alias, MODELS[DEFAULT_MODEL])
        prov = PROVIDERS[m["provider"]]
        return False, prov["api_key_env"]
    return True, ""


def list_configured_models() -> list[str]:
    """返回所有已配置 Key 的模型别名列表（可用于 /model 下拉）。"""
    result = []
    for alias in MODELS:
        ok, _ = validate_api_key(alias)
        if ok:
            result.append(alias)
    return result

# ════════════════════════════════════════════════════════
# 视觉模型辅助
# ════════════════════════════════════════════════════════

# 视觉模型优先级（按推荐顺序，需已配置对应 Key）
VISION_PRIORITY = ["glm-4v", "gpt-4o", "gpt-4o-mini", "claude-sonnet", "claude-opus"]


def get_best_vision_model() -> tuple[str | None, str | None, str | None]:
    """
    按优先级找到第一个已配置 Key 的视觉模型。
    返回 (model_alias, base_url, api_key)，或 (None, None, None)。
    """
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


# ════════════════════════════════════════════════════════
# 自定义 Provider 加载
# 从 ~/.pawnlogic/custom_providers.json 读取（不含 Key）。
# Key 通过 api_key_env 引用 .env 中的环境变量。
# ════════════════════════════════════════════════════════
CUSTOM_PROVIDERS_PATH = Path.home() / ".pawnlogic" / "custom_providers.json"


def load_custom_providers() -> None:
    """加载自定义 provider/model，合并进 PROVIDERS/MODELS。"""
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
    """保存自定义 provider 到 JSON 文件（不含 Key）。"""
    data = {"providers": {}, "models": {}}
    if CUSTOM_PROVIDERS_PATH.exists():
        try:
            data = json.loads(CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    data["providers"][name] = prov_cfg
    data["models"].update(models_cfg)
    CUSTOM_PROVIDERS_PATH.parent.mkdir(parents=True, exist_ok=True)
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
    # 删除关联的 models
    to_remove = [a for a, m in data.get("models", {}).items() if m.get("provider") == name]
    for a in to_remove:
        del data["models"][a]
    CUSTOM_PROVIDERS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return True


# 模块加载时自动读取自定义 provider
load_custom_providers()

# ════════════════════════════════════════════════════════
# 三档预设
# ════════════════════════════════════════════════════════
TIER_LOW = {
    "max_tokens":      4_096,
    "ctx_max_chars":   40_000,
    "ctx_trim_to":     30_000,
    "max_iter":        10,
    "tool_max_chars":   6_000,
    "fetch_max_chars":  8_000,
    "preferred_worker": "auto",
    "time_budget_sec":  300,      # 5 分钟
}
TIER_MID = {
    "max_tokens":      8_192,
    "ctx_max_chars":   150_000,
    "ctx_trim_to":     110_000,
    "max_iter":        30,
    "tool_max_chars":   15_000,
    "fetch_max_chars":  20_000,
    "preferred_worker": "auto",
    "time_budget_sec":  600,      # 10 分钟
}
TIER_DEEP = {
    "max_tokens":      32_768,
    "ctx_max_chars":   400_000,
    "ctx_trim_to":     300_000,
    "max_iter":        50,
    "tool_max_chars":   20_000,
    "fetch_max_chars":  30_000,
    "preferred_worker": "auto",
    "time_budget_sec":  1800,     # 30 分钟
}

TIER_MAX = {
    "max_tokens":      32_768,
    "ctx_max_chars":   600_000,
    "ctx_trim_to":     450_000,
    "max_iter":        100,
    "tool_max_chars":   30_000,
    "fetch_max_chars":  40_000,
    "preferred_worker": "auto",
    "time_budget_sec":  3600,     # 60 分钟
}

DYNAMIC_CONFIG: dict = dict(TIER_MID)
NORMAL_CONFIG:  dict = dict(TIER_MID)

# ════════════════════════════════════════════════════════
# Web 抓取策略
# ════════════════════════════════════════════════════════
WEB_STRATEGY = {
    "jina_base":     "https://r.jina.ai/",
    "use_pandoc":    True,
    "timeout":       20,
    "max_html_read": 600_000,
}

# ════════════════════════════════════════════════════════
# 沙箱语言表
# ════════════════════════════════════════════════════════
SANDBOX_LANGS = {
    "python":     {"ext": ".py",   "cmd": None,           "compile": None},
    "c":          {"ext": ".c",    "cmd": None,           "compile": "gcc -O0 -g {src} -o {bin} -lm 2>&1"},
    "cpp":        {"ext": ".cpp",  "cmd": None,           "compile": "g++ -O0 -g -std=c++17 {src} -o {bin} 2>&1"},
    "javascript": {"ext": ".js",   "cmd": "node {src}",   "compile": None},
    "js":         {"ext": ".js",   "cmd": "node {src}",   "compile": None},
    "bash":       {"ext": ".sh",   "cmd": "bash {src}",   "compile": None},
    "rust":       {"ext": ".rs",   "cmd": None,           "compile": "rustc {src} -o {bin} 2>&1"},
    "go":         {"ext": ".go",   "cmd": "go run {src}", "compile": None},
    "java":       {"ext": ".java", "cmd": None,           "compile": "javac {src} 2>&1"},
}

# ════════════════════════════════════════════════════════
# 安全名单
# ════════════════════════════════════════════════════════
READ_BLACKLIST = [os.path.expanduser(p) for p in
    ["~/.ssh", "~/.gnupg", "~/.config/gcloud", "~/.aws", "~/.kube"]]

WRITE_BLACKLIST = [
    "/etc", "/bin", "/sbin", "/usr/bin", "/usr/sbin",
    "/boot", "/lib", "/lib64", "/dev", "/proc", "/sys",
]

DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+[/~]", r"sudo\s+rm\s+-rf", r"mkfs\.",
    r"dd\s+if=", r">\s*/dev/sd", r"chmod\s+-R\s+777\s+/", r"\bshred\b",
    r":\(\)\s*\{.*\|.*&\s*\};\s*:",                     # fork bomb :(){ :|:& };:
    r"curl\s.*\|\s*(ba)?sh",                             # remote code exec via curl|sh
    r"wget\s.*\|\s*(ba)?sh",                             # remote code exec via wget|sh
    r"wget\s.*-O\s*-\s*\|\s*(ba)?sh",                    # wget -O- | bash variant
    r"\bnc\s.*-[celp]\s*\d*\s*/bin/(ba)?sh",             # netcat reverse/bind shell
    r"\bncat\s.*-e\s*/bin/(ba)?sh",                      # ncat reverse shell
    r"python[23]?\s*-c.*socket.*connect",                 # python reverse shell
    r"mkfifo\s.*/tmp/",                                   # named pipe for reverse shell
    r"\bsudo\b",                                          # 宿主机提权禁止，Root 需通过 Docker 容器
    r"docker\s+(run|exec|rm)",                            # 禁止直接 docker CLI，必须走工具层
]

# ════════════════════════════════════════════════════════
# P5: Scrapling 浏览器配置
# ════════════════════════════════════════════════════════
BROWSER_CONFIG = {
    "timeout":        30,                                                    # 默认超时（秒）
    "screenshot_dir": str(Path.home() / ".pawnlogic" / "workspace" / "screenshots"),
# （mcp_server_cmd 已移除：改用 Scrapling 本地 Python API，无需 npm）
    "stealthy":       True,                                                  # 默认开启 StealthyFetcher
    "solve_cf":       True,                                                  # 默认解 Cloudflare
}

# ════════════════════════════════════════════════════════
# UA 池（网页抓取随机轮换）
# ════════════════════════════════════════════════════════
USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 Version/17.4 Safari/605.1.15",
]

# ════════════════════════════════════════════════════════
# Quiet Mode & Token-Efficient Output Truncation
# ════════════════════════════════════════════════════════
# main.py 在 argparse 后设置此标志，其他模块读取。
# 集中定义以避免循环导入：main.py → session.py → main.py。

QUIET_MODE: bool = False

# ★ P6: 双模输出 — USER_MODE
# USER_MODE = True  → 用户模式：屏蔽原始 Traceback、Tool Call JSON、底层日志
# USER_MODE = False → 开发者模式：极致透明，显示所有底层细节
USER_MODE: bool = False


def user_friendly_error(raw_error: str) -> str:
    """
    USER_MODE 专用：将原始错误信息转为用户友好的简洁提示。
    开发者模式下原样返回。
    """
    if not USER_MODE:
        return raw_error
    # 关键词 → 友好提示映射
    _ERROR_MAP = {
        "Traceback":            "❌ 系统忙，请稍后重试",
        "ConnectionError":      "❌ 网络连接失败，请检查网络",
        "TimeoutError":         "❌ 请求超时，请稍后重试",
        "RateLimitError":       "❌ API 调用频率过高，请稍后重试",
        "AuthenticationError":  "❌ API Key 无效，请用 /setkey 重新配置",
        "PermissionError":      "❌ 权限不足，请检查文件权限",
        "FileNotFoundError":    "❌ 文件未找到，请检查路径",
        "ModuleNotFoundError":  "❌ 缺少依赖模块，请安装后重试",
        "JSONDecodeError":      "❌ 数据解析失败，请稍后重试",
        "API Error":            "❌ API 调用失败，请稍后重试",
        "ERROR":                "❌ 操作失败，请稍后重试",
    }
    for keyword, friendly in _ERROR_MAP.items():
        if keyword.lower() in raw_error.lower():
            return friendly
    # 兜底：截断到第一行，去除技术细节
    first_line = raw_error.split("\n")[0][:80]
    return f"❌ {first_line}"


def smart_truncate(text: str, head: int = 30, tail: int = 30) -> str:
    """
    保留文本前 `head` 行和后 `tail` 行，丢弃中间内容并插入标记。
    用于 GDB / ROPgadget / Shell 等冗长工具输出，节省 Token。
    """
    lines = text.splitlines()
    total = len(lines)
    if total <= head + tail:
        return text
    kept_head = lines[:head]
    kept_tail = lines[total - tail:]
    dropped   = total - head - tail
    marker    = (f"[... {dropped} lines truncated for token efficiency "
                 f"(total {total}, kept first {head} + last {tail}) ...]")
    return "\n".join(kept_head + [marker] + kept_tail)


# ════════════════════════════════════════════════════════
# MoE 动态工具裁剪 — 专家路由表
# ════════════════════════════════════════════════════════
# 每个 Phase 只暴露对应"专家组"的工具白名单。
# switch_phase / /chat 系列属于全局基础工具，由框架强制附加，无需在此列出。
AGENT_PHASES: dict[str, list[str]] = {
    # 侦察阶段：了解目标环境和二进制特征
    "RECON": [
        "pwn_env", "list_dir", "find_files", "read_file", "inspect_binary",
        "pwn_timed_debug",   # CTF 动态靶机随时可用
        "search_skills",     # P6: 指纹匹配技能包
        "check_service",     # P6: 环境嗅探（端口→进程详情）
    ],
    # 漏洞开发阶段：定位偏移、反汇编、构建 ROP 链
    "VULN_DEV": [
        "pwn_cyclic", "pwn_disasm", "pwn_rop", "pwn_libc", "pwn_one_gadget", "run_shell",
        "pwn_timed_debug",
    ],
    # 利用阶段：编写 / 调试 exploit，交互式验证
    "EXPLOIT": [
        "write_file", "patch_file", "run_code", "pwn_debug", "pwn_timed_debug",
        "run_interactive", "run_shell",
        "run_code_docker", "pwn_container",   # P3: Docker 容器化
        "tool_install_package",               # P4.2: 气闸舱安装
        "docker_prune_resources",             # P4.3: 资源回收
    ],
    # 通用后备阶段：研究、文件操作、联网
    "GENERAL": [
        "read_file", "write_file", "patch_file", "run_shell", "web_search", "fetch_url",
        "pwn_timed_debug",
        "run_code_docker", "pwn_container",    # P3: Docker 容器化
        "tool_install_package",                # P4.2: 气闸舱安装
        "docker_prune_resources",              # P4.3: 资源回收
        "bump_skill",   # ★ GSA 反馈，全阶段可用
        "search_skills",  # P6: 指纹匹配技能包
        "check_service",  # P6: 环境嗅探（端口→进程详情）
    ],
    # P5: Web 渗透阶段 — Scrapling 浏览器武器库
    "WEB_PEN": [
        "web_fetch", "web_click", "web_screenshot", "web_select", "web_type", "web_navigate",
        "web_search", "fetch_url",   # 传统搜索/抓取仍可用
        "read_file", "write_file",   # 读写报告
        "run_shell",                 # 辅助命令
        "bump_skill",
        "search_skills",             # P6: 指纹匹配技能包
        "check_service",             # P6: 环境嗅探（端口→进程详情）
    ],
}

# ════════════════════════════════════════════════════════
# P3: Docker 镜像注册表
# ════════════════════════════════════════════════════════
DOCKER_IMAGES = {
    "pwndocker":  "skysider/pwndocker",   # Pwn 全能靶机（含 GDB/pwntools/ROPgadget）
    "ubuntu18":   "ubuntu:18.04",          # glibc 2.27 — 老题常用
    "ubuntu22":   "ubuntu:22.04",          # glibc 2.35 — 新题常用
    "kali":       "kalilinux/kali-rolling", # Kali 渗透测试
    "python":     "python:3.12-slim",      # 纯 Python 环境
    "gcc":        "gcc:latest",            # C/C++ 编译环境
}
