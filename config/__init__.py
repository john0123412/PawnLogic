"""
config/__init__.py - backward-compatible import entry point.

External code can keep using `from config import X` or `import config; config.X`.
"""
from .providers import (
    PROVIDERS, MODELS, DEFAULT_MODEL, VISION_PRIORITY,
    NAMING_MODEL_CHAIN, CUSTOM_PROVIDERS_PATH,
    get_api_config, get_api_format, get_provider_config,
    validate_api_key, list_configured_models,
    get_best_vision_model, list_vision_models,
    load_custom_providers, save_custom_provider, remove_custom_provider,
    is_fast_model, find_fast_peer, models_url_from_base_url,
    custom_model_alias, is_chat_model_candidate,
    is_provider_active, set_provider_active,
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
    "custom_model_alias", "is_chat_model_candidate",
    "is_provider_active", "set_provider_active",
    "TIER_LOW", "TIER_MID", "TIER_DEEP", "TIER_MAX",
    "READ_BLACKLIST", "WRITE_BLACKLIST", "DANGEROUS_PATTERNS",
    "smart_truncate", "user_friendly_error", "scrub_sensitive_env",
    "SANDBOX_LANGS", "DOCKER_IMAGES", "BROWSER_CONFIG", "USER_AGENTS",
    "AGENT_PHASES",
    "VERSION", "PAWNLOGIC_HOME", "SESSIONS_DIR", "DB_PATH", "GLOBAL_SKILLS_PATH",
    "SKILLS_DIR", "LOG_DIR", "WORKSPACE_DIR", "WORKSPACE_ROOT",
    "DYNAMIC_CONFIG", "NORMAL_CONFIG", "WEB_STRATEGY", "USER_MODE", "QUIET_MODE",
]

# Backward compatibility: DYNAMIC_CONFIG / NORMAL_CONFIG.
# These mutable dicts are changed at runtime by tier commands such as /mid.
# Keep them here for existing `from config import DYNAMIC_CONFIG` imports.
DYNAMIC_CONFIG: dict = dict(TIER_MID)
NORMAL_CONFIG:  dict = dict(TIER_MID)

# Backward compatibility: WEB_STRATEGY.
WEB_STRATEGY = {
    "jina_base":     "https://r.jina.ai/",
    "use_pandoc":    True,
    "timeout":       20,
    "max_html_read": 600_000,
}

# Backward compatibility: USER_MODE / QUIET_MODE.
# These flags are now managed by core.state.
# Module-level variables remain for `import config; config.QUIET_MODE = True`.
# Direct assignment here does not update core.state.state; new code should
# import `state` from core.state instead.
USER_MODE: bool = False
QUIET_MODE: bool = False
