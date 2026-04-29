"""
core/logger.py — PawnLogic 统一日志模块
=========================================
强制使用 loguru，实现双端输出：
  · 终端   — 带颜色高亮，级别 INFO 及以上
  · 本地文件 — 按大小轮转（10 MB），保留 1 周，级别 DEBUG 及以上

用法（其他模块）:
    from core.logger import logger          # 直接使用
    logger.info("消息")
    logger.warning("警告: {}", detail)
    logger.error("错误: {exc}", exc=e)

初始化（main.py 程序入口处唯一调用一次）:
    from core.logger import setup_logger
    setup_logger()
"""

import sys
from pathlib import Path

from loguru import logger   # noqa: F401  — 让外部模块可以 `from core.logger import logger`

# ── 终端格式 ─────────────────────────────────────────────
_FMT_STDERR = (
    "<green>{time:HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> — "
    "<level>{message}</level>"
)

# ── 文件格式（含 function，便于追踪调用栈）──────────────
_FMT_FILE = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level: <8} | "
    "{name}:{function}:{line} — "
    "{message}"
)


def setup_logger(stderr_level: str = "INFO", file_level: str = "DEBUG") -> None:
    """
    初始化 loguru 双端输出。
    · 应在 main.py 中 argparse 完成、config.QUIET_MODE 确定后调用。
    · 全程只调用一次；重复调用会清除旧 handler 再重建（幂等安全）。

    Parameters
    ----------
    stderr_level : str
        终端输出的最低级别，默认 "INFO"。
        QUIET_MODE 下可传 "WARNING" 减少噪音。
    file_level : str
        文件输出的最低级别，默认 "DEBUG"（完整记录）。
    """
    # 延迟导入，避免循环依赖（config 在 logger 初始化前已被导入）
    try:
        from config import LOG_DIR
        log_dir = Path(LOG_DIR)
    except (ImportError, AttributeError):
        # 若 config 中尚未添加 LOG_DIR，退回默认路径
        log_dir = Path.home() / ".pawnlogic" / "logs"

    # ── 清除所有已有 handler（包括 loguru 默认的 stderr handler）──
    logger.remove()

    # ── Handler 1: 终端彩色输出 ─────────────────────────
    logger.add(
        sys.stderr,
        level=stderr_level,
        colorize=True,
        format=_FMT_STDERR,
        enqueue=False,          # 主线程直接写，保持与 print() 输出的时序一致
    )

    # ── Handler 2: 本地文件轮转输出 ─────────────────────
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "pawnlogic_{time:YYYY-MM-DD}.log"

    logger.add(
        str(log_file),
        level=file_level,
        rotation="10 MB",       # 单文件超过 10 MB 自动切割
        retention="1 week",     # 超过 1 周的旧日志自动删除
        compression="zip",      # 归档时压缩，节省磁盘
        encoding="utf-8",
        format=_FMT_FILE,
        backtrace=True,         # 异常时输出完整回溯
        diagnose=True,          # 输出局部变量值，便于调试
        enqueue=True,           # 文件写入异步化，不阻塞主线程
        catch=True,             # 即使 logger 自身出错也不崩溃主程序
    )

    logger.info(
        "Logger initialized | stderr={} file={} log_dir={}",
        stderr_level, file_level, log_dir,
    )


__all__ = ["logger", "setup_logger"]
