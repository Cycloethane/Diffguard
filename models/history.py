# -*- coding: utf-8 -*-
"""历史记录模块：使用 SQLModel + SQLite 持久化 AI 审查历史。

数据库文件保存在平台用户数据目录（Windows 下为 %LOCALAPPDATA%\\DiffGuard\\
diffguard.db），提供保存、查询最近记录与按主键查询等函数。
"""

from datetime import datetime
from typing import Optional

from loguru import logger
from sqlmodel import Field, Session, SQLModel, select

from models.db import get_engine

# 用户决策状态常量
DECISION_PENDING: str = "pending"
DECISION_APPROVED: str = "approved"
DECISION_REJECTED: str = "rejected"

# 风险等级常量
RISK_LOW: str = "low"
RISK_MEDIUM: str = "medium"
RISK_HIGH: str = "high"


class ReviewHistory(SQLModel, table=True):
    """一条 AI 审查历史记录。

    属性:
        id: 主键。
        timestamp: 审查时间。
        title: 变更摘要（自动提取）。
        file_count: 变更文件数量。
        risk_level: 风险等级（low/medium/high）。
        ai_report: 完整审查报告。
        user_decision: 用户决策（pending/approved/rejected）。
        raw_diff: 原始 diff 文本。
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime
    title: str
    file_count: int
    risk_level: str
    ai_report: str
    user_decision: str = DECISION_PENDING
    raw_diff: str


def save_review(
    title: str,
    file_count: int,
    risk_level: str,
    ai_report: str,
    raw_diff: str,
    user_decision: str = DECISION_PENDING,
    timestamp: Optional[datetime] = None,
) -> Optional[int]:
    """保存一条审查历史，返回新记录的主键；失败返回 None。"""
    engine = get_engine()
    if engine is None:
        logger.error("数据库未初始化，无法保存历史")
        return None
    record = ReviewHistory(
        timestamp=timestamp or datetime.now(),
        title=title,
        file_count=file_count,
        risk_level=risk_level,
        ai_report=ai_report,
        user_decision=user_decision,
        raw_diff=raw_diff,
    )
    try:
        with Session(engine) as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            logger.info("已保存审查历史 id={}", record.id)
            return record.id
    except Exception as exc:
        logger.error("保存历史记录失败: {}", exc)
        return None


def get_recent(limit: int = 50) -> list[ReviewHistory]:
    """返回最近 limit 条审查记录，按时间倒序。"""
    engine = get_engine()
    if engine is None:
        logger.error("数据库未初始化，无法查询历史")
        return []
    try:
        with Session(engine) as session:
            statement = select(ReviewHistory).order_by(
                ReviewHistory.timestamp.desc()
            ).limit(limit)
            records = session.exec(statement).all()
            return list(records)
    except Exception as exc:
        logger.error("查询历史记录失败: {}", exc)
        return []


def get_by_id(record_id: int) -> Optional[ReviewHistory]:
    """按主键查询单条历史记录，不存在时返回 None。"""
    engine = get_engine()
    if engine is None:
        logger.error("数据库未初始化，无法查询历史")
        return None
    try:
        with Session(engine) as session:
            record = session.get(ReviewHistory, record_id)
            return record
    except Exception as exc:
        logger.error("查询历史记录 id={} 失败: {}", record_id, exc)
        return None


def update_decision(record_id: int, decision: str) -> bool:
    """更新一条记录的 user_decision，成功返回 True。"""
    engine = get_engine()
    if engine is None:
        logger.error("数据库未初始化，无法更新历史")
        return False
    if decision not in (DECISION_PENDING, DECISION_APPROVED, DECISION_REJECTED):
        logger.warning("非法决策值: {}", decision)
        return False
    try:
        with Session(engine) as session:
            record = session.get(ReviewHistory, record_id)
            if record is None:
                logger.warning("更新决策失败，记录不存在 id={}", record_id)
                return False
            record.user_decision = decision
            session.add(record)
            session.commit()
            logger.info("已更新历史 id={} 决策为 {}", record_id, decision)
            return True
    except Exception as exc:
        logger.error("更新历史决策失败: {}", exc)
        return False