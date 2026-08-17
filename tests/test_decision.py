# -*- coding: utf-8 -*-
"""决策助手核心逻辑单元测试（纯逻辑，无 GUI / 无网络）。"""
import pytest

from core.decision_explainer import (
    build_system_prompt,
    parse_error_line,
    parse_opt_line,
    parse_question_line,
    parse_recommend_line,
)
from core.decision_parser import is_likely_decision, parse


# ----------------------------------------------------------------------
# 措辞水平提示词
# ----------------------------------------------------------------------
class TestSystemPrompt:
    def test_beginner_contains_plain_words(self):
        p = build_system_prompt("beginner")
        assert "零基础" in p or "大白话" in p or "比喻" in p

    def test_normal_fallback(self):
        p = build_system_prompt("normal")
        assert "普通" in p

    def test_advanced_terms(self):
        p = build_system_prompt("advanced")
        assert "进阶" in p

    def test_unknown_level_falls_back_to_normal(self):
        p = build_system_prompt("bogus")
        assert "普通" in p


# ----------------------------------------------------------------------
# 行解析协议
# ----------------------------------------------------------------------
class TestLineParsing:
    def test_opt_line(self):
        opt = parse_opt_line(
            '#OPTION# {"key":"A","text":"PyInstaller","meaning":"单文件",'
            '"risk":"low","reason":"方便"}'
        )
        assert opt["key"] == "A"
        assert opt["risk"] == "low"

    def test_opt_line_bad_json_returns_empty(self):
        assert parse_opt_line("#OPTION# not-json") == {}

    def test_recommend_line(self):
        rec = parse_recommend_line('#RECOMMEND# {"option":"B","conclusion":"选 B 更好"}')
        assert rec["option"] == "B"

    def test_question_line(self):
        assert parse_question_line("#QUESTION# 打包方式") == "打包方式"

    def test_error_line(self):
        assert parse_error_line("#ERROR# 没配置 Key") == "没配置 Key"

    def test_non_matching_returns_empty(self):
        assert parse_question_line("随便一句话") == ""
        assert parse_error_line("随便一句话") == ""


# ----------------------------------------------------------------------
# 决策文本解析管线
# ----------------------------------------------------------------------
class TestDecisionParser:
    def test_pipeline_list_options(self):
        text = "打包方式请选择：\nA) PyInstaller 单文件\nB) PyInstaller 目录\nC) Inno Setup 安装包"
        prompt = parse([text], window_title="Clipboard")
        assert prompt is not None
        assert prompt.question and "打包" in prompt.question
        assert len(prompt.options) >= 2
        assert prompt.options[0].key == "A"

    def test_rejects_plain_question(self):
        # 普通问句不是决策
        assert not is_likely_decision("今天天气怎么样？")

    def test_rejects_single_word_option(self):
        # 单字母选项不构成有效决策
        assert not is_likely_decision("A\nB")

    def test_inline_number_options(self):
        text = "请选择部署方式：1. 本地 Windows 服务 2. Docker 容器 3. 云服务器"
        prompt = parse([text], window_title="Clipboard")
        assert prompt is not None
        assert len(prompt.options) >= 2

    def test_english_options(self):
        text = "Please select a packaging tool:\nA) PyInstaller\nB) Nuitka\nC) cx_Freeze"
        prompt = parse([text], window_title="Clipboard")
        assert prompt is not None
        assert len(prompt.options) >= 2
