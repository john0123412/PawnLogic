"""utils/ansi.py — ANSI 颜色辅助

修复 WSL2 / Ubuntu readline 光标错位问题：
  readline 在计算 input() 提示符宽度时会把 ANSI 转义序列
  （\033[...m）当作可见字符，导致光标偏移，输入覆盖上一行输出。

  修复方案：用 readline 专用标记包裹转义序列：
    \001  = RL_PROMPT_START_IGNORE（告知 readline：忽略宽度计算开始）
    \002  = RL_PROMPT_END_IGNORE  （告知 readline：忽略宽度计算结束）

  普通输出（print / sys.stdout.write）用 c()，不需要这些标记。
  只有 input() 的 prompt 参数才用 cp() / rl_wrap()。
"""

import re as _re

# ── 基础颜色常量 ────────────────────────────────────────
R       = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
GRAY    = "\033[90m"
CYAN    = "\033[96m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
RED     = "\033[91m"
BLUE    = "\033[94m"
MAGENTA = "\033[95m"

# ── 普通输出用（print / sys.stdout.write）──────────────

def c(col: str, txt: str) -> str:
    """为普通输出着色。不可用于 input() prompt。"""
    return f"{col}{txt}{R}"

def box(txt: str, col: str = CYAN) -> str:
    return f"{col}│{R} {txt}"

# ── readline prompt 专用 ────────────────────────────────
#
# \001 和 \002 是 readline 的 RL_PROMPT_START_IGNORE /
# RL_PROMPT_END_IGNORE 标记，告诉 readline 忽略这段字节的
# 显示宽度，从而正确计算光标位置。
#
# 原理：readline 对 prompt 宽度的计算公式是
#   visible_width = len(prompt) - len(所有 \001...\002 之间的字节)
# 把所有 \033[...m 包进 \001...\002，宽度偏差归零。

_ANSI_RE = _re.compile(r'(\033\[[0-9;]*m)')

def rl_wrap(text: str) -> str:
    """
    将字符串中所有 ANSI 转义序列包裹上 readline 忽略标记。
    用于需要传入 input() 的任何含颜色的字符串。
    """
    return _ANSI_RE.sub(r'\001\1\002', text)

def cp(col: str, txt: str) -> str:
    """
    readline-safe 版 c()。
    用于 input() prompt，其余场合用 c()。

    示例：
        # 普通输出
        print(c(GREEN, "完成"))

        # input 提示符
        raw = input(cp(BOLD+GREEN, "▶ ") + cp(BOLD, "You > "))
    """
    return rl_wrap(f"{col}{txt}{R}")
