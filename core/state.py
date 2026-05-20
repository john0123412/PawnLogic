"""
core/state.py — PawnLogic 运行时状态管理

所有运行时可变状态集中在此，与静态配置彻底分离。
其他模块通过 `from core.state import state` 访问。
"""
from dataclasses import dataclass, field


@dataclass
class RuntimeState:
    # 输出模式
    user_mode: bool = False       # True = 用户友好模式，False = 开发者模式
    quiet_mode: bool = False      # True = 静默模式

    # 模型状态
    current_model: str = "ds-chat"
    current_worker: str = "auto"

    # 算力档位（从 config.tiers 初始化，运行时可修改）
    dynamic_config: dict = field(default_factory=dict)

    # 时间预算
    time_budget_sec: int = 0
    time_start: float = 0.0

    # 当前工作目录
    work_dir: str = "."

    # 首次运行标记
    is_first_run: bool = False


# 全局单例，所有模块共享
state = RuntimeState()
