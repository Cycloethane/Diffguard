# -*- coding: utf-8 -*-
"""权限模块单元测试：证据判定、解析、风险评分与 ~/Windows 路径修复。"""
import pytest

from core.permission_parser import PermissionParser
from core.permission_risk import (
    _is_system_path,
    risk_level,
    score_prompt,
    sensitive_file_hit,
)
from models.permission_prompt import PermissionPrompt, PromptAction, PromptType

OPCMD = "OpenCode permission required. The agent is about to run a terminal command md"
ALLOW_WORDS = "Allow once / Always allow / Reject"


# ----------------------------------------------------------------------
# 证据判定
# ----------------------------------------------------------------------
class TestEvidence:
    def test_operation_evidence_command(self):
        assert PermissionParser.has_operation_evidence(OPCMD)

    def test_option_evidence(self):
        assert PermissionParser.has_option_evidence(ALLOW_WORDS)

    def test_likely_permission_prompt(self):
        assert PermissionParser.is_likely_permission_prompt(OPCMD + "\n" + ALLOW_WORDS)

    def test_normal_text_not_prompt(self):
        assert not PermissionParser.is_likely_permission_prompt(
            "hello world this is a test"
        )


# ----------------------------------------------------------------------
# 解析
# ----------------------------------------------------------------------
class TestParse:
    def test_parse_command_exec(self):
        p = PermissionParser.parse(
            [OPCMD, ALLOW_WORDS], window_title="OpenCode", window_handle=1234
        )
        assert p.source == "OpenCode"
        assert p.prompt_type == PromptType.COMMAND_EXEC
        assert p.action == PromptAction.EXECUTE
        assert len(p.options) >= 1


# ----------------------------------------------------------------------
# 风险评分
# ----------------------------------------------------------------------
class TestRisk:
    def test_command_exec_high_risk(self):
        p = PermissionParser.parse([OPCMD, ALLOW_WORDS], window_title="OpenCode")
        p.risk_score, p.breakdown = score_prompt(p)
        assert p.risk_score >= 60
        assert len(p.breakdown) > 0
        assert risk_level(p) == "high"

    def test_system_path_judgment(self):
        assert _is_system_path(r"C:\Windows\System32\cmd.exe")
        assert _is_system_path(r"C:\Program Files\foo\bar.exe")
        # ~/Windows 不应被误判为系统目录
        assert not _is_system_path(r"C:\Users\someone\Windows\file.txt")
        assert not _is_system_path(r"C:\Users\someone\other")

    def test_windows_tilde_no_system_bonus(self):
        q = PermissionPrompt(
            source="OpenCode",
            prompt_type=PromptType.COMMAND_EXEC,
            action=PromptAction.EXECUTE,
            target=r"~/Windows/script.bat",
            target_expanded=r"C:\Users\someone\Windows\script.bat",
            raw_text=OPCMD + "\n" + ALLOW_WORDS,
        )
        q.risk_score, q.breakdown = score_prompt(q)
        assert not any("系统目录" in b for b in q.breakdown)

    def test_real_system_path_gets_bonus(self):
        r = PermissionPrompt(
            source="OpenCode",
            prompt_type=PromptType.COMMAND_EXEC,
            action=PromptAction.EXECUTE,
            target=r"C:\Windows\System32\cmd.exe",
            target_expanded=r"C:\Windows\System32\cmd.exe",
            raw_text=OPCMD + "\n" + ALLOW_WORDS,
        )
        r.risk_score, r.breakdown = score_prompt(r)
        assert any("系统目录" in b for b in r.breakdown)

    def test_sensitive_file_detection(self):
        assert sensitive_file_hit(r"C:\x\.env") is not None
        assert sensitive_file_hit(r"C:\Users\a\.ssh\id_rsa") is not None
        assert sensitive_file_hit(r"C:\x\main.py") is None

    def test_delete_high_risk(self):
        d = PermissionPrompt(
            source="Cursor",
            prompt_type=PromptType.FILE_ACCESS,
            action=PromptAction.DELETE,
            target=r"~/logs",
            target_expanded=r"C:\Users\someone\logs",
            raw_text="delete directory ~/logs\n" + ALLOW_WORDS,
        )
        d.risk_score, d.breakdown = score_prompt(d)
        assert d.risk_score >= 65
