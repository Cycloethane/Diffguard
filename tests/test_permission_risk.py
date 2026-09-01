# -*- coding: utf-8 -*-
"""core.permission_risk 单元测试：动作基础分、目标敏感度、危险关键词。"""

from core.permission_risk import risk_level, score_prompt, sensitive_file_hit
from models.permission_prompt import PermissionPrompt, PromptAction, PromptType


def _prompt(
    action: PromptAction = PromptAction.UNKNOWN,
    prompt_type: PromptType = PromptType.UNKNOWN,
    target: str = "",
    target_expanded: str = "",
    raw_text: str = "",
) -> PermissionPrompt:
    return PermissionPrompt(
        action=action,
        prompt_type=prompt_type,
        target=target,
        target_expanded=target_expanded,
        raw_text=raw_text,
    )


def test_sensitive_file_hit() -> None:
    assert sensitive_file_hit(r"C:\Users\u\proj\.env") == ".env"
    assert sensitive_file_hit("~/.ssh/id_rsa") == "id_rsa"
    assert sensitive_file_hit(r"C:\proj\src\main.py") is None


def test_delete_in_system_dir_is_high() -> None:
    prompt = _prompt(
        action=PromptAction.DELETE,
        prompt_type=PromptType.FILE_ACCESS,
        target=r"C:\Windows\System32\evil.dll",
        target_expanded=r"C:\Windows\System32\evil.dll",
    )
    score, contributions = score_prompt(prompt)
    assert score == 65 + 30  # 删除 65 + 系统目录 30
    assert any("系统目录" in c for c in contributions)


def test_write_sensitive_file() -> None:
    prompt = _prompt(
        action=PromptAction.WRITE,
        prompt_type=PromptType.FILE_ACCESS,
        target=r"C:\Users\u\proj\.env",
        target_expanded=r"C:\Users\u\proj\.env",
    )
    score, _ = score_prompt(prompt)
    assert score == 35 + 25  # 写 35 + 敏感文件 25


def test_read_home_sensitive_subdir() -> None:
    import os

    home = os.path.expanduser("~")
    target = home + r"\Documents\plan.txt"
    prompt = _prompt(
        action=PromptAction.READ,
        prompt_type=PromptType.FILE_ACCESS,
        target=target,
        target_expanded=target,
    )
    score, contributions = score_prompt(prompt)
    assert score == 10 + 15  # 读 10 + 用户目录敏感位置 15
    assert any("用户目录敏感位置" in c for c in contributions)


def test_danger_keyword_in_raw_text() -> None:
    prompt = _prompt(
        action=PromptAction.EXECUTE,
        prompt_type=PromptType.COMMAND_EXEC,
        target="git push --force origin main",
        raw_text="execute: git push --force origin main",
    )
    score, contributions = score_prompt(prompt)
    assert score == 60 + 20  # 执行 60 + 强制覆盖 20
    assert any("危险操作" in c for c in contributions)


def test_unresolvable_file_path_conservative_bonus() -> None:
    prompt = _prompt(
        action=PromptAction.READ,
        prompt_type=PromptType.FILE_ACCESS,
        target="unknown",
        target_expanded="",
    )
    score, contributions = score_prompt(prompt)
    assert score == 10 + 10  # 读 10 + 保守加分 10
    assert any("保守加分" in c for c in contributions)


def test_risk_level_mapping() -> None:
    prompt = _prompt()
    prompt.risk_score = 39
    assert risk_level(prompt) == "low"
    prompt.risk_score = 40
    assert risk_level(prompt) == "medium"
    prompt.risk_score = 60
    assert risk_level(prompt) == "high"
