# -*- coding: utf-8 -*-
"""models 数据层测试:单一 engine、三张表的保存与查询(临时数据库)。"""

import pytest

from models import db


@pytest.fixture
def db_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """把数据库文件重定向到临时目录并重置 engine 缓存。"""
    target = tmp_path / "diffguard.db"
    monkeypatch.setattr(db, "db_path", lambda: target)
    db.reset_engine()
    yield target
    db.reset_engine()


def test_engine_lazy_singleton(db_tmp) -> None:
    first = db.get_engine()
    second = db.get_engine()
    assert first is not None
    assert first is second


def test_review_history_roundtrip(db_tmp) -> None:
    from models.history import DECISION_APPROVED, get_by_id, get_recent, save_review, update_decision

    rid = save_review(
        title="修改 config", file_count=2, risk_level="medium",
        ai_report="报告", raw_diff="diff --git a/x b/x",
    )
    assert rid is not None
    recs = get_recent(10)
    assert len(recs) == 1
    assert recs[0].title == "修改 config"
    assert get_by_id(rid).id == rid
    assert update_decision(rid, DECISION_APPROVED)
    assert get_by_id(rid).user_decision == DECISION_APPROVED


def test_permission_history_roundtrip(db_tmp) -> None:
    from models.permission_history import (
        PERMISSION_REJECTED,
        get_recent_permissions,
        save_permission,
        update_permission_decision,
    )
    from models.permission_prompt import PermissionPrompt, PromptAction, PromptType

    prompt = PermissionPrompt(
        source="Test", prompt_type=PromptType.COMMAND_EXEC,
        action=PromptAction.EXECUTE, target="rm -rf /tmp/x",
        risk_score=60, breakdown=["动作:execute (+60)"], options=["allow", "reject"],
        raw_text="execute ...",
    )
    rid = save_permission(prompt)
    assert rid is not None
    recs = get_recent_permissions(10)
    assert len(recs) == 1
    assert recs[0].source == "Test"
    assert recs[0].risk_score == 60
    assert update_permission_decision(rid, PERMISSION_REJECTED)
    assert get_recent_permissions(1)[0].user_decision == PERMISSION_REJECTED


def test_decision_history_roundtrip_and_stats(db_tmp) -> None:
    from models.decision_history import decision_stats, get_recent_decisions, save_decision

    options = [{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}]
    rid = save_decision(
        source="Test", question="选哪个？", options=options,
        recommendation="B", conclusion="选乙", user_decision="B",
    )
    assert rid is not None
    recs = get_recent_decisions(10)
    assert len(recs) == 1
    assert recs[0].question == "选哪个？"

    stats = decision_stats(50)
    assert stats["total"] == 1
    assert stats["with_choice"] == 1
    assert stats["by_source"].get("Test") == 1
    assert stats["recent_preferences"][0]["chosen"] == "B"
    assert stats["recent_preferences"][0]["chosen_text"] == "乙"


def test_engine_failure_soft_degrades(monkeypatch) -> None:
    """engine 初始化失败时各查询函数软失败,不抛异常。"""
    from models import history as history_mod

    def _boom():
        raise RuntimeError("disk error")

    monkeypatch.setattr(db, "db_path", _boom)
    db.reset_engine()
    try:
        assert history_mod.save_review(
            title="t", file_count=1, risk_level="low",
            ai_report="r", raw_diff="d",
        ) is None
        assert history_mod.get_recent(5) == []
    finally:
        db.reset_engine()
