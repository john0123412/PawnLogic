"""
core/state.py — PawnLogic runtime state management.

All mutable runtime state lives here, separated from static configuration.
Other modules access it with `from core.state import state`.
"""
from dataclasses import dataclass, field


@dataclass
class RuntimeState:
    # Output mode.
    user_mode: bool = False       # True = user-friendly mode; False = developer mode.
    quiet_mode: bool = False      # True = quiet mode.

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
