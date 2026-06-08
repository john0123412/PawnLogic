"""
config/__init__.py — 向后兼容入口

外部代码 `from config import X` 或 `import config; config.X` 无需任何修改。
"""
from .providers import (
    PROVIDERS, MODELS, DEFAULT_MODEL, VISION_PRIORITY,
    NAMING_MODEL_CHAIN, CUSTOM_PROVIDERS_PATH,
    get_api_config, get_api_format, get_provider_config,
    validate_api_key, list_configured_models,
    get_best_vision_model, list_vision_models,
    load_custom_providers, save_custom_provider, remove_custom_provider,
    is_fast_model, find_fast_peer, models_url_from_base_url,
)
from .tiers import TIER_LOW, TIER_MID, TIER_DEEP, TIER_MAX
from .security import (
    READ_BLACKLIST, WRITE_BLACKLIST, DANGEROUS_PATTERNS,
    smart_truncate, user_friendly_error, scrub_sensitive_env,
)
from .sandbox import SANDBOX_LANGS, DOCKER_IMAGES, BROWSER_CONFIG, USER_AGENTS
from .phases import AGENT_PHASES
from .paths import (
    VERSION, PAWNLOGIC_HOME, SESSIONS_DIR, DB_PATH, GLOBAL_SKILLS_PATH,
    SKILLS_DIR, LOG_DIR, WORKSPACE_DIR, WORKSPACE_ROOT,
)

__all__ = [
    "PROVIDERS", "MODELS", "DEFAULT_MODEL", "VISION_PRIORITY",
    "NAMING_MODEL_CHAIN", "CUSTOM_PROVIDERS_PATH",
    "get_api_config", "get_api_format", "get_provider_config",
    "validate_api_key", "list_configured_models",
    "get_best_vision_model", "list_vision_models",
    "load_custom_providers", "save_custom_provider", "remove_custom_provider",
    "is_fast_model", "find_fast_peer", "models_url_from_base_url",
    "TIER_LOW", "TIER_MID", "TIER_DEEP", "TIER_MAX",
    "READ_BLACKLIST", "WRITE_BLACKLIST", "DANGEROUS_PATTERNS",
    "smart_truncate", "user_friendly_error", "scrub_sensitive_env",
    "SANDBOX_LANGS", "DOCKER_IMAGES", "BROWSER_CONFIG", "USER_AGENTS",
    "AGENT_PHASES",
    "VERSION", "PAWNLOGIC_HOME", "SESSIONS_DIR", "DB_PATH", "GLOBAL_SKILLS_PATH",
    "SKILLS_DIR", "LOG_DIR", "WORKSPACE_DIR", "WORKSPACE_ROOT",
    "DYNAMIC_CONFIG", "NORMAL_CONFIG", "WEB_STRATEGY", "USER_MODE", "QUIET_MODE",
]

# ── 向后兼容：DYNAMIC_CONFIG / NORMAL_CONFIG ──────────────
# 这两个可变 dict 由 main.py 在运行时修改（/mid /deep /low 等命令）。
# 保留在此处以兼容所有 `from config import DYNAMIC_CONFIG` 的调用。
DYNAMIC_CONFIG: dict = dict(TIER_MID)
NORMAL_CONFIG:  dict = dict(TIER_MID)

# ── 向后兼容：WEB_STRATEGY ────────────────────────────────
WEB_STRATEGY = {
    "jina_base":     "https://r.jina.ai/",
    "use_pandoc":    True,
    "timeout":       20,
    "max_html_read": 600_000,
}

# ── 向后兼容：USER_MODE / QUIET_MODE ─────────────────────
# 这两个标志现在由 core.state 管理。
# 保留模块级变量以兼容 `import config; config.QUIET_MODE = True` 的写法。
# 注意：直接赋值此处的变量不会影响 core.state.state，
# 推荐新代码使用 `from core.state import state`。
USER_MODE: bool = False
QUIET_MODE: bool = False
