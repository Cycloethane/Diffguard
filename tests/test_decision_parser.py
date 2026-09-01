# -*- coding: utf-8 -*-
"""core.decision_parser 单元测试：证据判定、选项提取、来源识别。"""

from core.decision_parser import extract_options, is_likely_decision, parse

DECISION_LIST = "请选择打包方式：\nA) PyInstaller 单文件\nB) PyInstaller 目录\nC) Inno Setup 安装包"
DECISION_DUNHAO = "请选择开发语言：Python、JavaScript、Rust"
DECISION_OR = "部署环境可以是 Docker 或 K8s 或 裸机，请选择一个"
CHATTER = "还有什么问题吗？"
PLAIN = "今天天气不错。"


# ----------------------------------------------------------------------
# 证据判定
# ----------------------------------------------------------------------
def test_is_likely_decision_list_lines() -> None:
    assert is_likely_decision(DECISION_LIST)


def test_is_likely_decision_dunhao() -> None:
    assert is_likely_decision(DECISION_DUNHAO)


def test_is_likely_decision_or_split() -> None:
    assert is_likely_decision(DECISION_OR)


def test_is_likely_decision_excluded_chatter() -> None:
    assert not is_likely_decision(CHATTER)


def test_is_likely_decision_plain_text() -> None:
    assert not is_likely_decision(PLAIN)


def test_is_likely_decision_empty() -> None:
    assert not is_likely_decision("")
    assert not is_likely_decision("请选择\n只有一个问题没有选项")


# ----------------------------------------------------------------------
# 选项提取
# ----------------------------------------------------------------------
def test_extract_options_list_lines() -> None:
    options = extract_options(DECISION_LIST)
    assert len(options) == 3
    assert [o.key for o in options] == ["A", "B", "C"]
    assert options[0].text == "PyInstaller 单文件"


def test_extract_options_dunhao() -> None:
    options = extract_options(DECISION_DUNHAO)
    assert len(options) == 3
    assert {o.text for o in options} == {"Python", "JavaScript", "Rust"}


# ----------------------------------------------------------------------
# parse 主入口
# ----------------------------------------------------------------------
def test_parse_full_prompt() -> None:
    prompt = parse([DECISION_LIST], window_title="Clipboard")
    assert prompt is not None
    assert prompt.source == "Clipboard"
    assert prompt.question == "请选择打包方式"
    assert len(prompt.options) == 3
    assert prompt.raw_text.startswith("请选择打包方式")


def test_parse_rejects_non_decision() -> None:
    assert parse([PLAIN], window_title="Clipboard") is None


def test_parse_source_from_title() -> None:
    prompt = parse([DECISION_LIST], window_title="opencode")
    assert prompt is not None
    assert prompt.source == "OpenCode"


def test_parse_empty_texts() -> None:
    assert parse([""], window_title="Clipboard") is None
