# -*- coding: utf-8 -*-
"""本地风险评分单元测试（score_text / risk_score 启发式）。"""
import pytest

from core.risk_score import (
    clamp,
    compute_risk_score,
    score_color,
    score_label,
    score_text,
    score_to_level,
)


class TestClamp:
    def test_clamp_lower(self):
        assert clamp(-10) == 0

    def test_clamp_upper(self):
        assert clamp(200) == 100

    def test_clamp_keep(self):
        assert clamp(50) == 50


class TestScoreText:
    def test_empty_text_low(self):
        res = score_text("")
        assert res["score"] == 0
        assert res["level"] == "low"

    def test_plain_text_low(self):
        res = score_text("hello world, this is a normal commit message")
        assert res["level"] in ("low", "medium")

    def test_secret_detected(self):
        res = score_text('password = "mysecret123"')
        assert res["score"] >= 40
        assert any("密钥" in f for f in res["findings"])

    def test_dangerous_command(self):
        res = score_text("rm -rf /")
        assert any("危险命令" in f for f in res["findings"])

    def test_combined_high(self):
        res = score_text('token = "abc123xyz"; rm -rf /')
        assert res["score"] >= 40


class TestScoreLevel:
    def test_level_mapping(self):
        assert score_to_level(10) == "low"
        assert score_to_level(45) == "medium"
        assert score_to_level(80) == "high"

    def test_color_and_label(self):
        assert score_color(10) == "#3b82f6"
        assert score_label(30) == "低"


class TestComputeRisk:
    def test_risky_files(self):
        files = [
            {"path": "app/.env", "risk_flags": ["配置文件变更"], "additions": 3, "deletions": 0},
            {"path": "x.py", "risk_flags": [], "additions": 5, "deletions": 1},
        ]
        score, contribs = compute_risk_score(files)
        assert score > 0
        assert any("配置文件变更" in c for c in contribs)

    def test_clean_files_low(self):
        files = [
            {"path": "main.py", "risk_flags": [], "additions": 2, "deletions": 0},
        ]
        score, contribs = compute_risk_score(files)
        # 少量新增只产生很小的规模加分，不应触发任何风险标记
        assert score <= 10
        assert not any("硬编码" in c or "配置" in c for c in contribs)
