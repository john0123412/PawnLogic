"""
core/state.py - PawnLogic runtime state management.

All mutable runtime state lives here, separated from static configuration.
Other modules access it with `from core.state import state`.
"""
from dataclasses import dataclass, field
from collections.abc import Mapping, MutableMapping
from typing import Any


@dataclass
class RuntimeState:
    # Output mode.
    user_mode: bool = True        # True = user-friendly mode; False = debug mode.
    debug_mode: bool = False      # True = detailed terminal diagnostics.
    quiet_mode: bool = False      # Legacy compatibility; no CLI flag sets this.

    # Model state.
    current_model: str = "ds-v4-flash"
    current_worker: str = "auto"

    # Compute tier, initialized from config.tiers and mutable at runtime.
    dynamic_config: dict = field(default_factory=dict)

    # Time budget.
    time_budget_sec: int = 0
    time_start: float = 0.0

    # Current working directory.
    work_dir: str = "."

    # First-run flag.
    is_first_run: bool = False


# Shared global singleton.
state = RuntimeState()


def bind_dynamic_config(config: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Bind the shared runtime config mapping used by legacy config imports."""
    state.dynamic_config = config
    _sync_dynamic_state_fields()
    return config


def runtime_config() -> MutableMapping[str, Any]:
    """Return the active context config or the legacy process-wide mapping."""
    try:
        from core.runtime_context import current_runtime_context

        context = current_runtime_context()
        if context is not None:
            return context.dynamic_config
    except Exception:
        pass
    try:
        from config import DYNAMIC_CONFIG
        if state.dynamic_config is not DYNAMIC_CONFIG:
            bind_dynamic_config(DYNAMIC_CONFIG)
    except Exception:
        pass
    return state.dynamic_config


def update_dynamic_config(values: Mapping[str, Any]) -> MutableMapping[str, Any]:
    """Update dynamic config through the runtime-state write path."""
    cfg = runtime_config()
    cfg.update(values)
    _sync_dynamic_state_fields(cfg)
    return cfg


def set_dynamic_config_value(key: str, value: Any) -> MutableMapping[str, Any]:
    """Set one dynamic config value through the runtime-state write path."""
    cfg = runtime_config()
    cfg[key] = value
    _sync_dynamic_state_fields(cfg)
    return cfg


def get_dynamic_config_value(key: str, default: Any = None) -> Any:
    """Read one dynamic config value through the runtime-state read path."""
    return runtime_config().get(key, default)


def dynamic_config_snapshot() -> dict:
    """Return a shallow copy of the dynamic config for a consistent read view."""
    return dict(runtime_config())


def set_output_mode(*, debug_mode: bool, user_mode: bool | None = None, quiet_mode: bool | None = None) -> None:
    """Set the active context mode and refresh compatibility globals."""
    try:
        from core.runtime_context import current_runtime_context

        context = current_runtime_context()
    except Exception:
        context = None
    if context is not None:
        context.debug_mode = bool(debug_mode)
        context.user_mode = (not context.debug_mode) if user_mode is None else bool(user_mode)
    state.debug_mode = bool(debug_mode)
    state.user_mode = (not state.debug_mode) if user_mode is None else bool(user_mode)
    if quiet_mode is not None:
        state.quiet_mode = bool(quiet_mode)
    try:
        import config
        config.USER_MODE = state.user_mode
        config.QUIET_MODE = state.quiet_mode
    except Exception:
        pass


def mirror_runtime_context(context: Any) -> None:
    """Mirror a RuntimeContext into globals retained for legacy call sites."""
    state.debug_mode = bool(context.debug_mode)
    state.user_mode = bool(context.user_mode)
    state.dynamic_config = context.dynamic_config
    _sync_dynamic_state_fields(context.dynamic_config)
    try:
        import config

        config.USER_MODE = state.user_mode
        config.QUIET_MODE = state.quiet_mode
    except Exception:
        pass


def _sync_dynamic_state_fields(config: Mapping[str, Any] | None = None) -> None:
    cfg = state.dynamic_config if config is None else config
    if "preferred_worker" in cfg:
        state.current_worker = str(cfg.get("preferred_worker") or "auto")
    if "time_budget_sec" in cfg:
        try:
            state.time_budget_sec = int(cfg.get("time_budget_sec") or 0)
        except (TypeError, ValueError):
            state.time_budget_sec = 0
