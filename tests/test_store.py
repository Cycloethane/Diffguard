# -*- coding: utf-8 -*-
"""bridge.store 单元测试：桥接文件协议读写（重定向到临时目录）。"""

from bridge import store


# ----------------------------------------------------------------------
# 决策反馈
# ----------------------------------------------------------------------
def test_decision_feedback_roundtrip_and_order(bridge_tmp) -> None:
    for i in range(3):
        assert store.record_decision_feedback(
            question=f"问题{i}", chosen="A", chosen_text="方案甲",
            recommendation="推荐A", source="Test",
        )
    feedback = store.read_decision_feedback(limit=2)
    assert len(feedback) == 2
    # 最新在前
    assert feedback[0]["question"] == "问题2"
    assert feedback[1]["question"] == "问题1"
    assert feedback[0]["chosen"] == "A"


def test_decision_feedback_truncated_to_500(bridge_tmp) -> None:
    for i in range(505):
        store.record_decision_feedback(
            question=f"q{i}", chosen="B", chosen_text="乙",
            recommendation="", source="Test",
        )
    all_feedback = store.read_decision_feedback(limit=1000)
    assert len(all_feedback) == 500
    # 保留的是最近的 500 条
    assert all_feedback[0]["question"] == "q504"


def test_read_decision_feedback_empty(bridge_tmp) -> None:
    assert store.read_decision_feedback() == []


# ----------------------------------------------------------------------
# Agent 决策请求
# ----------------------------------------------------------------------
def test_agent_decision_roundtrip(bridge_tmp) -> None:
    options = [{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}]
    assert store.write_agent_decision("选哪个？", options, context="测试")
    data = store.read_agent_decision()
    assert data is not None
    assert data["question"] == "选哪个？"
    assert data["options"] == options
    assert data["context"] == "测试"

    store.clear_agent_decision()
    assert store.read_agent_decision() is None


def test_read_agent_decision_corrupt_file(bridge_tmp) -> None:
    (bridge_tmp / "agent_decision_in.json").write_text("{not json", encoding="utf-8")
    assert store.read_agent_decision() is None


# ----------------------------------------------------------------------
# 审查请求 / 结果
# ----------------------------------------------------------------------
def test_review_request_lifecycle(bridge_tmp) -> None:
    rid1 = store.submit_review_request("diff aaa", title="第一次")
    rid2 = store.submit_review_request("diff bbb", title="第二次")
    assert rid1 == 1 and rid2 == 2

    requests = store.read_review_requests()
    assert len(requests) == 2
    assert requests[0]["status"] == "pending"

    assert store.mark_review_request_done(rid1, "报告内容")
    requests = store.read_review_requests()
    assert requests[0]["status"] == "done"

    results = store.read_review_results()
    assert len(results) == 1
    assert results[0]["id"] == rid1
    assert results[0]["report"] == "报告内容"


# ----------------------------------------------------------------------
# 状态
# ----------------------------------------------------------------------
def test_status_roundtrip(bridge_tmp) -> None:
    assert store.write_status(permission_monitor=True, mode="on")
    status = store.read_status()
    assert status["permission_monitor"] is True
    assert status["mode"] == "on"
    assert "timestamp" in status


def test_clear_all_bridge_files(bridge_tmp) -> None:
    store.write_status()
    store.write_agent_decision("q", [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}])
    store.clear_all_bridge_files()
    assert store.read_status() == {}
    assert store.read_agent_decision() is None
