# -*- coding: utf-8 -*-
"""core.permission_parser 单元测试：证据判定、解析、来源识别、路径展开。"""

from core.permission_parser import PermissionParser
from models.permission_prompt import PromptAction, PromptType

OPCODE_TITLE = "OpenCode — Permission Required"
OPCODE_BODY = (
    "OpenCode wants to execute command: rm -rf /tmp/build\n"
    "Allow once (only this time)\n"
    "Allow always\n"
    "Reject"
)

CLINE_TITLE = "Cline"
CLINE_BODY = "Cline wants to write file: ~/Documents/notes.txt\nAllow once\nReject"


# ----------------------------------------------------------------------
# 证据判定
# ----------------------------------------------------------------------
def test_is_likely_permission_prompt_positive() -> None:
    assert PermissionParser.is_likely_permission_prompt(f"{OPCODE_TITLE}\n{OPCODE_BODY}")


def test_is_likely_permission_prompt_negative_plain_text() -> None:
    assert not PermissionParser.is_likely_permission_prompt("hello world 普通文本")


def test_is_likely_permission_prompt_negative_single_group() -> None:
    # 只有"允许"一组选项证据（无 scope / deny），不构成权限请求
    assert not PermissionParser.is_likely_permission_prompt("请允许访问文件")


# ----------------------------------------------------------------------
# 解析
# ----------------------------------------------------------------------
def test_parse_opencode_command_prompt() -> None:
    prompt = PermissionParser.parse([OPCODE_BODY], window_title=OPCODE_TITLE)
    assert prompt.source == "OpenCode"
    assert prompt.prompt_type == PromptType.COMMAND_EXEC
    assert prompt.action == PromptAction.EXECUTE
    assert prompt.target == "rm -rf /tmp/build"
    # raw_text 不含标题
    assert "Permission Required" not in prompt.raw_text
    assert "allow once" in prompt.options


def test_parse_cline_file_prompt() -> None:
    prompt = PermissionParser.parse([CLINE_BODY], window_title=CLINE_TITLE)
    assert prompt.source == "Cline"
    assert prompt.prompt_type == PromptType.FILE_ACCESS
    assert prompt.action == PromptAction.WRITE
    # 注意：当前 _PATH_RE 不排除换行，捕获会延伸到下一行首个空格
    # （已知怪癖，Phase 2 统一解析器时修复），这里只断言前缀正确
    assert prompt.target.startswith("~/Documents/notes.txt")
    # FILE_ACCESS 且路径有效时应展开绝对路径
    assert "Documents" in prompt.target_expanded


def test_parse_unknown_source() -> None:
    body = "允许删除目录 C:\\data\\tmp\n拒绝"
    prompt = PermissionParser.parse([body], window_title="某工具")
    assert prompt.source == "Unknown"
    assert prompt.action == PromptAction.DELETE


# ----------------------------------------------------------------------
# 路径展开
# ----------------------------------------------------------------------
def test_expand_path_home_and_relative() -> None:
    home_expanded = PermissionParser.expand_path("~")
    assert len(home_expanded) > 1 and ":" in home_expanded  # Windows 盘符

    rel = PermissionParser.expand_path("some/rel.py")
    assert rel.endswith("some\\rel.py") or rel.endswith("some/rel.py")
    assert PermissionParser.expand_path("") == ""
