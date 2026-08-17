# -*- coding: utf-8 -*-
"""日志模块：配置 loguru，控制台与文件同时输出，文件存于用户日志目录。

本模块是整个应用日志的基础，其它模块统一通过 ``from loguru import logger`` 使用。
"""

import sys
from pathlib import Path

import platformdirs
from loguru import logger

# 日志文件名
_LOG_FILE_NAME = "diffguard.log"
# 控制台日志级别
_CONSOLE_LEVEL = "INFO"
# 文件日志级别（保存更详细的信息）
_FILE_LEVEL = "DEBUG"


def log_dir() -> Path:
    """返回应用日志目录（Windows 下为 %LOCALAPPDATA%\\DiffGuard\\logs）。"""
    return Path(platformdirs.user_log_dir("DiffGuard"))


def setup_logger() -> None:
    """配置 loguru 日志，控制台与文件双输出，返回后全局可继续使用 logger。

    该函数应在程序入口处调用一次。重复调用会先移除已有 handler 再重建，
    因此多次调用是安全的。
    """
    path: Path = log_dir()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # 目录创建失败时退化为仅控制台输出
        logger.error("创建日志目录失败，仅启用控制台日志: {}", exc)

    logger.remove()  # 移除默认 handler，避免重复输出

    # 控制台输出（pythonw 等无控制台环境 sys.stderr 为 None，安全跳过）
    try:
        if sys.stderr is not None:
            logger.add(
                sys.stderr,
                format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
                level=_CONSOLE_LEVEL,
                colorize=True,
            )
    except Exception:  # 控制台输出失败不影响程序
        pass

    # 文件输出
    try:
        logger.add(
            path / _LOG_FILE_NAME,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
            level=_FILE_LEVEL,
            encoding="utf-8",
            rotation="10 MB",
            retention="30 days",
            enqueue=True,
        )
    except Exception as exc:  # 文件日志失败不影响程序运行
        logger.error("初始化文件日志失败: {}", exc)

    logger.info("日志系统初始化完成，日志目录: {}", path)