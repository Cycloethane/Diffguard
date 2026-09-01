# -*- coding: utf-8 -*-
"""core.risk_score 单元测试：分带、等级映射、diff 评分、文本评分。"""

from core.risk_score import (
    clamp,
    compute_risk_score,
    score_color,
    score_label,
    score_text,
    score_to_level,
)


# ----------------------------------------------------------------------
# 分带与等级
# ----------------------------------------------------------------------
def test_score_bands_color_and_label() -> None:
    assert score_color(0) == "#3b82f6"
    assert score_label(10) == "极低"
    assert score_color(25) == "#22c55e"
    assert score_label(30) == "低"
    assert score_label(50) == "中"
    assert score_color(70) == "#f97316"
    assert score_label(75) == "高"
    assert score_color(100) == "#ef4444"
    assert score_label(100) == "极高"


def test_score_to_level_thresholds() -> None:
    assert score_to_level(0) == "low"
    assert score_to_level(39) == "low"
    assert score_to_level(40) == "medium"
    assert score_to_level(59) == "medium"
    assert score_to_level(60) == "high"
    assert score_to_level(100) == "high"


def test_clamp() -> None:
    assert clamp(-5) == 0
    assert clamp(150) == 100
    assert clamp(55) == 55


# ----------------------------------------------------------------------
# diff 评分
# ----------------------------------------------------------------------
def _file(flags: list[str], additions: int = 0, deletions: int = 0) -> dict:
    return {"risk_flags": flags, "additions": additions, "deletions": deletions}


def test_compute_risk_score_empty() -> None:
    score, contributions = compute_risk_score([])
    assert score == 0
    assert contributions == []


def test_compute_risk_score_secret_flag() -> None:
    score, contributions = compute_risk_score([_file(["疑似硬编码密钥"])])
    # 标记 30 + 风险文件 2 = 32
    assert score == 32
    assert any("疑似硬编码密钥" in c for c in contributions)


def test_compute_risk_score_size_and_rewrite() -> None:
    score, contributions = compute_risk_score([_file([], deletions=100)])
    # 规模 min(15, round(2*log2(101))) = 13；删除占比 100% → +10
    assert score == 23
    assert any("删除占比" in c for c in contributions)
    assert any("变更规模" in c for c in contributions)


def test_compute_risk_score_flags_capped_at_100() -> None:
    score, _ = compute_risk_score(
        [
            _file(["疑似硬编码密钥", "配置文件变更", "文件删除", "依赖变更"]),
            _file(["疑似硬编码密钥", "配置文件变更", "文件删除"], additions=5, deletions=5),
        ]
    )
    assert score == 100


# ----------------------------------------------------------------------
# 文本评分
# ----------------------------------------------------------------------
def test_score_text_empty() -> None:
    res = score_text("")
    assert res["score"] == 0
    assert res["level"] == "low"
    assert res["findings"] == []


def test_score_text_hardcoded_secret() -> None:
    res = score_text('password = "supersecret123"')
    assert res["score"] == 40
    assert "疑似硬编码密钥" in res["findings"]


def test_score_text_danger_command() -> None:
    res = score_text("run this: rm -rf /")
    assert res["score"] == 25
    assert any("危险命令" in f for f in res["findings"])


def test_score_text_sensitive_path() -> None:
    res = score_text("cat ~/.ssh/id_rsa")
    assert res["score"] == 20
    assert "敏感路径" in res["findings"]


def test_score_text_system_dir_write() -> None:
    res = score_text("copy x C:\\Windows\\System32\\evil.dll")
    # System32 同时命中敏感路径（+20）与系统目录（+15）
    assert res["score"] == 35
    assert "敏感路径" in res["findings"]
    assert "系统目录" in res["findings"]


def test_score_text_combined_medium() -> None:
    res = score_text("rm -rf / 之后读取 .ssh/id_rsa")
    # 危险命令 25 + 敏感路径 20 = 45 → medium
    assert res["score"] == 45
    assert res["level"] == "medium"
