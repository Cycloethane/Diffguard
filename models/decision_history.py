# -*- coding: utf-8 -*-
"""决策历史记录模块：持久化用户在决策助手中的选择，供 AI Agent 参考。

与 history.py / permission_history.py 共用同一个 SQLite 文件（diffguard.db），
新增决策反馈表。核心用途（OpenCode 集成-决策反馈闭环）：
    - 记录每次决策的问题、AI 推荐与用户最终选择；
    - OpenCode 通过 MCP / 桥接文件读取历史，了解用户偏好，
      后续决策时自动参考（避免重复询问同类问题）。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import platformdirs
from loguru import logger
from sqlmodel import Field, Session, SQLModel, create_engine, select

# 用户决策状态常量
DECISION_PENDING: str = "pending"
DECISION_CHOSEN: str = "chosen"
DECISION_SKIPPED: str = "skipped"


def _decision_db_path() -> Path:
    """返回 SQLite 数据库文件路径（与审查历史共用）。"""
    return Path(platformdirs.user_data_dir("DiffGuard")) / "diffguard.db"


class DecisionRecord(SQLModel, table=True):
    """一条决策反馈记录。

    属性:
        id: 主键。
        timestamp: 决策完成时间。
        source: 来源（OpenCode / Cursor / Cline / Clipboard / MCP / Unknown）。
        question: 决策问题。
        options_json: 原始选项列表（JSON 字符串）。
        recommendation: AI 给出的推荐选项（可能为空）。
        conclusion: AI 的一句话结论（可能为空）。
        user_decision: 用户最终选择的关键字（如 A / B / C），跳过为空。
        raw_text: 原始决策文本（可能较长）。
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime
    source: str
    question: str
    options_json: str = "[]"
    recommendation: str = ""
    conclusion: str = ""
    user_decision: str = ""
    raw_text: str = ""


# 初始化共享数据库引擎（独立 engine，避免与其它模块耦合初始化顺序）
_decision_db_file: Path = _decision_db_path()
try:
    _decision_db_file.parent.mkdir(parents=True, exist_ok=True)
    decision_engine = create_engine(
        f"sqlite:///{_decision_db_file}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(decision_engine)
    logger.info("决策历史数据库初始化完成: {}", _decision_db_file)
except Exception as exc:
    logger.error("决策历史数据库初始化失败: {}", exc)
    decision_engine = None


def save_decision(
    source: str,
    question: str,
    options: list,
    recommendation: str = "",
    conclusion: str = "",
    user_decision: str = "",
    raw_text: str = "",
    timestamp: Optional[datetime] = None,
) -> Optional[int]:
    """保存一条决策反馈记录，返回新记录主键；失败返回 None。"""
    if decision_engine is None:
        logger.error("决策历史数据库未初始化，无法保存")
        return None
    try:
        record = DecisionRecord(
            timestamp=timestamp or datetime.now(),
            source=source,
            question=question,
            options_json=json.dumps(options, ensure_ascii=False),
            recommendation=recommendation,
            conclusion=conclusion,
            user_decision=user_decision,
            raw_text=raw_text,
        )
        with Session(decision_engine) as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            logger.info("已保存决策记录 id={} 问题={} 选择={}", record.id, record.question[:40], record.user_decision)
            return record.id
    except Exception as exc:
        logger.error("保存决策记录失败: {}", exc)
        return None


def get_recent_decisions(limit: int = 50) -> list[DecisionRecord]:
    """返回最近 limit 条决策反馈记录，按时间倒序。"""
    if decision_engine is None:
        return []
    try:
        with Session(decision_engine) as session:
            statement = select(DecisionRecord).order_by(
                DecisionRecord.timestamp.desc()
            ).limit(limit)
            return list(session.exec(statement).all())
    except Exception as exc:
        logger.error("查询决策记录失败: {}", exc)
        return []


def get_decision_by_id(record_id: int) -> Optional[DecisionRecord]:
    """按主键查询单条决策记录，不存在时返回 None。"""
    if decision_engine is None:
        return None
    try:
        with Session(decision_engine) as session:
            return session.get(DecisionRecord, record_id)
    except Exception as exc:
        logger.error("查询决策记录 id={} 失败: {}", record_id, exc)
        return None


def decision_stats(limit: int = 200) -> dict:
    """汇总最近 limit 条决策的偏好统计，供 Agent 快速了解用户习惯。"""
    records = get_recent_decisions(limit)
    made = [r for r in records if r.user_decision]
    stats = {
        "total": len(records),
        "with_choice": len(made),
        "by_source": {},
        "recent_preferences": [],
    }
    for r in made:
        stats["by_source"][r.source] = stats["by_source"].get(r.source, 0) + 1
        try:
            options = json.loads(r.options_json or "[]")
        except json.JSONDecodeError:
            options = []
        # 找到用户选择对应的选项文本，形成一条可读偏好
        chosen_text = ""
        for opt in options:
            if isinstance(opt, dict) and opt.get("key") == r.user_decision:
                chosen_text = opt.get("text", "")
                break
        stats["recent_preferences"].append(
            {
                "timestamp": r.timestamp.isoformat(),
                "question": r.question,
                "chosen": r.user_decision,
                "chosen_text": chosen_text,
                "recommendation": r.recommendation,
            }
        )
    return stats
