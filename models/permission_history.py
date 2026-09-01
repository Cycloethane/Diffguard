# -*- coding: utf-8 -*-
"""权限历史记录模块：使用 SQLModel + SQLite 持久化权限审批记录。

与 history.py 共用同一个 SQLite 文件（diffguard.db）但与审查历史分表，
提供保存权限请求、查询最近记录与更新决策等函数。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import platformdirs
from loguru import logger
from sqlmodel import Field, Session, SQLModel, create_engine, select

from models.permission_prompt import (
    PermissionPrompt,
    PromptAction,
    PromptType,
)

# 权限决策状态常量
PERMISSION_PENDING: str = "pending"
PERMISSION_ONCE_ALLOWED: str = "once_allowed"
PERMISSION_ALWAYS_ALLOWED: str = "always_allowed"
PERMISSION_REJECTED: str = "rejected"


def _permission_db_path() -> Path:
    """返回 SQLite 数据库文件路径（与审查历史共用）。"""
    return Path(platformdirs.user_data_dir("DiffGuard")) / "diffguard.db"


class PermissionRecord(SQLModel, table=True):
    """一条权限审批记录。

    属性:
        id: 主键。
        timestamp: 触发时间。
        source: 来源（OpenCode / Cursor / Cline / Clipboard / Unknown）。
        prompt_type: 请求类型（file_access 等）。
        action: 动作（read / write / ...）。
        target: 目标字符串（路径 / URL / 命令）。
        risk_score: 风险分数（0-100）。
        breakdown_json: 风险评分明细（JSON 字符串）。
        options_json: 检测到的选项按钮文本（JSON 字符串）。
        raw_text: 原始文本（可能较长）。
        user_decision: 用户决策。
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime
    source: str
    prompt_type: str
    action: str
    target: str
    risk_score: int
    breakdown_json: str = "[]"
    options_json: str = "[]"
    raw_text: str = ""
    user_decision: str = PERMISSION_PENDING


# 初始化共享数据库引擎（独立 engine，避免与审查历史模块耦合初始化顺序）
_permission_db_file: Path = _permission_db_path()
try:
    _permission_db_file.parent.mkdir(parents=True, exist_ok=True)
    permission_engine = create_engine(
        f"sqlite:///{_permission_db_file}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(permission_engine)
    logger.info("权限历史数据库初始化完成: {}", _permission_db_file)
except Exception as exc:  # 失败时保证程序仍可启动
    logger.error("权限历史数据库初始化失败: {}", exc)
    permission_engine = None


def _to_record(prompt: PermissionPrompt) -> PermissionRecord:
    """将 PermissionPrompt 转为数据库记录。"""
    return PermissionRecord(
        timestamp=datetime.now(),
        source=prompt.source,
        prompt_type=prompt.prompt_type.value,
        action=prompt.action.value,
        target=prompt.target,
        risk_score=prompt.risk_score,
        breakdown_json=json.dumps(prompt.breakdown, ensure_ascii=False),
        options_json=json.dumps(prompt.options, ensure_ascii=False),
        raw_text=prompt.raw_text,
    )


def save_permission(prompt: PermissionPrompt) -> Optional[int]:
    """保存一条权限审批记录，返回新记录主键；失败返回 None。"""
    if permission_engine is None:
        logger.error("权限历史数据库未初始化，无法保存")
        return None
    record = _to_record(prompt)
    try:
        with Session(permission_engine) as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            logger.info("已保存权限记录 id={} 来源={} 风险={}", record.id, record.source, record.risk_score)
            return record.id
    except Exception as exc:
        logger.error("保存权限记录失败: {}", exc)
        return None


def get_recent_permissions(limit: int = 50) -> list[PermissionRecord]:
    """返回最近 limit 条权限记录，按时间倒序。"""
    if permission_engine is None:
        return []
    try:
        with Session(permission_engine) as session:
            statement = select(PermissionRecord).order_by(
                PermissionRecord.timestamp.desc()
            ).limit(limit)
            return list(session.exec(statement).all())
    except Exception as exc:
        logger.error("查询权限记录失败: {}", exc)
        return []


def update_permission_decision(record_id: int, decision: str) -> bool:
    """更新一条权限记录的 user_decision，成功返回 True。"""
    if permission_engine is None:
        return False
    if decision not in (
        PERMISSION_PENDING,
        PERMISSION_ONCE_ALLOWED,
        PERMISSION_ALWAYS_ALLOWED,
        PERMISSION_REJECTED,
    ):
        logger.warning("非法权限决策值: {}", decision)
        return False
    try:
        with Session(permission_engine) as session:
            record = session.get(PermissionRecord, record_id)
            if record is None:
                logger.warning("更新权限决策失败，记录不存在 id={}", record_id)
                return False
            record.user_decision = decision
            session.add(record)
            session.commit()
            logger.info("已更新权限记录 id={} 决策为 {}", record_id, decision)
            return True
    except Exception as exc:
        logger.error("更新权限决策失败: {}", exc)
        return False