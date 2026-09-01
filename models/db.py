# -*- coding: utf-8 -*-
"""数据库基础设施:单一 SQLModel engine,三张历史表共用。

三个历史模块(history / permission_history / decision_history)指向同一个
SQLite 文件(%LOCALAPPDATA%\\DiffGuard\\diffguard.db)。此前各模块在导入期
各自创建 engine 并建表;现收敛为本模块的惰性单例:首次调用 get_engine()
时才建目录、创建 engine 与全部表结构,消除模块导入期副作用。

初始化失败时 get_engine() 返回 None,调用方沿用原有软失败模式
(记日志、返回 None/[]/False),保证程序仍可启动。
"""

from pathlib import Path
from typing import Optional

import platformdirs
from loguru import logger
from sqlmodel import SQLModel, create_engine

_engine: Optional[object] = None
_initialized: bool = False


def db_path() -> Path:
    """返回 SQLite 数据库文件路径。"""
    return Path(platformdirs.user_data_dir("DiffGuard")) / "diffguard.db"


def get_engine():
    """返回共享 engine(惰性创建);初始化失败返回 None。

    首次调用时导入全部表模型再 create_all,确保三张表都能建出来;
    之后调用直接返回缓存实例。结果会被缓存,失败同样只判定一次。
    """
    global _engine, _initialized
    if _initialized:
        return _engine
    _initialized = True
    try:
        path: Path = db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # 导入各表模型,把表类注册进共享的 SQLModel.metadata
        import models.history  # noqa: F401
        import models.permission_history  # noqa: F401
        import models.decision_history  # noqa: F401

        _engine = create_engine(
            f"sqlite:///{path}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(_engine)
        logger.info("数据库初始化完成: {}", path)
    except Exception as exc:  # 初始化失败时保证程序仍可启动
        logger.error("数据库初始化失败: {}", exc)
        _engine = None
    return _engine


def reset_engine() -> None:
    """重置 engine 缓存(仅供测试隔离使用)。"""
    global _engine, _initialized
    _engine = None
    _initialized = False
