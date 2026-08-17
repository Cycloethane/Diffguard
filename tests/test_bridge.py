# -*- coding: utf-8 -*-
"""OpenCode 桥接层单元测试：文件级通信（决策反馈 / 审查请求 / 状态）。"""
import pytest

from bridge import store


@pytest.fixture(autouse=True)
def _clean_bridge():
    """每个用例前清理桥接文件。"""
    store.clear_all_bridge_files()
    yield
    store.clear_all_bridge_files()


class TestDecisionFeedback:
    def test_record_and_read(self):
        store.record_decision_feedback("打包方式请选择", "B", "PyInstaller 目录", "B", "OpenCode")
        fb = store.read_decision_feedback(5)
        assert len(fb) == 1
        assert fb[0]["question"] == "打包方式请选择"
        assert fb[0]["chosen"] == "B"

    def test_latest_first(self):
        store.record_decision_feedback("Q1", "A", "x", "", "OpenCode")
        store.record_decision_feedback("Q2", "B", "y", "", "OpenCode")
        fb = store.read_decision_feedback(5)
        assert fb[0]["question"] == "Q2"


class TestAgentDecision:
    def test_write_and_read(self):
        store.write_agent_decision(
            "部署环境请选择",
            [{"key": "A", "text": "Windows 服务"}, {"key": "B", "text": "Docker"}],
            "生产环境",
        )
        data = store.read_agent_decision()
        assert data is not None
        assert data["question"] == "部署环境请选择"
        assert len(data["options"]) == 2

    def test_clear(self):
        store.write_agent_decision("Q", [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}])
        store.clear_agent_decision()
        assert store.read_agent_decision() is None


class TestReviewRequests:
    def test_submit_and_read(self):
        req_id = store.submit_review_request("diff text here", "fix bug")
        assert req_id is not None
        reqs = store.read_review_requests()
        assert any(r["id"] == req_id for r in reqs)

    def test_mark_done(self):
        req_id = store.submit_review_request("diff", "t")
        store.mark_review_request_done(req_id, "报告内容")
        res = store.read_review_results(5)
        assert any(r["id"] == req_id and r["report"] == "报告内容" for r in res)


class TestStatus:
    def test_write_read_status(self):
        store.write_status(decision_assistant="on", model="deepseek")
        st = store.read_status()
        assert st.get("decision_assistant") == "on"
