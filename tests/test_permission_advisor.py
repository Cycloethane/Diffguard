# -*- coding: utf-8 -*-
"""权限顾问测试:advisor 协议解析、事件 raw 字段、门控与去重(逻辑层)。"""

import json

import pytest

from core import permission_advisor as advisor_mod
from models.config import Config


# ----------------------------------------------------------------------
# 协议解析
# ----------------------------------------------------------------------
def test_parse_lines() -> None:
    from core.permission_advisor import (
        parse_advice_line,
        parse_consequence_line,
        parse_error_line,
        parse_what_line,
    )

    assert parse_what_line("#WHAT# 删除项目的构建产物") == "删除项目的构建产物"
    assert parse_what_line("普通行") == ""
    assert parse_consequence_line("#CONSEQUENCE# 不可逆") == "不可逆"
    assert parse_advice_line('#ADVICE# {"decision":"deny","reason":"高危"}') == {
        "decision": "deny", "reason": "高危",
    }
    assert parse_advice_line("#ADVICE# not-json") == {}
    assert parse_error_line("#ERROR# 网络失败") == "网络失败"


def test_build_user_prompt_contains_context() -> None:
    from core.permission_advisor import _build_user_prompt

    event = {
        "tool": "Bash", "target": "rm -rf build", "raw": "rm -rf build && echo done",
        "score": 45, "level": "medium", "findings": ["危险命令:删除根目录"],
    }
    prompt = _build_user_prompt(event)
    assert "Bash" in prompt and "rm -rf build" in prompt and "45" in prompt
    assert "危险命令" in prompt


def test_advise_permission_streams_protocol(monkeypatch) -> None:
    """替身客户端:三行协议逐段到达,经 stream_lines 重组。"""
    from core import ai_client
    from core.permission_advisor import advise_permission

    class _Chunk:
        def __init__(self, content):
            delta = type("Delta", (), {"content": content})()
            self.choices = [type("Choice", (), {"delta": delta})()]

    class _FakeClient:
        def __init__(self):
            comps = type("C", (), {})()
            comps.create = lambda **kw: iter([
                _Chunk("#WHAT# 删除构建目录\n"),
                _Chunk("#CONSEQUENCE# 释放磁盘空间,可"),
                _Chunk("逆(可重新构建)\n"),
                _Chunk('#ADVICE# {"decision":"allow_once","reason":"影响可逆"}'),
            ])
            self.chat = type("Chat", (), {"completions": comps})()

    monkeypatch.setattr(ai_client, "OpenAI", lambda **_kw: _FakeClient())
    lines = list(advise_permission({"tool": "Bash", "raw": "rm -rf build"}, Config(api_key="k")))
    assert lines == [
        "#WHAT# 删除构建目录",
        "#CONSEQUENCE# 释放磁盘空间,可逆(可重新构建)",
        '#ADVICE# {"decision":"allow_once","reason":"影响可逆"}',
    ]


def test_advise_permission_no_key() -> None:
    from core.permission_advisor import advise_permission

    lines = list(advise_permission({"tool": "Bash"}, Config(api_key="")))
    assert lines == ["#ERROR# 尚未配置 API Key，请在“设置”中填写后重试。"]


# ----------------------------------------------------------------------
# 事件 raw 字段
# ----------------------------------------------------------------------
def test_permission_event_carries_raw(bridge_tmp) -> None:
    from bridge import store

    store.write_permission_event(
        "ZCode", "Bash", "rm -rf build", 45, "medium",
        ["危险命令"], raw="rm -rf build && echo done",
    )
    event = store.read_permission_event()
    assert event["raw"] == "rm -rf build && echo done"


def test_hook_writes_raw(monkeypatch, db_tmp, bridge_tmp) -> None:
    from bridge import store
    from bridge.hooks_runner import permission_request_main

    monkeypatch.setattr(
        "sys.stdin",
        _FakeStdin(json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/build"}})),
    )
    assert permission_request_main() == 0
    event = store.read_permission_event()
    assert event["raw"] == "rm -rf /tmp/build"
    assert event["score"] == 25  # 命中危险命令 "rm -rf /"


class _FakeStdin:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


# ----------------------------------------------------------------------
# 配置默认值
# ----------------------------------------------------------------------
def test_config_defaults() -> None:
    cfg = Config()
    assert cfg.permission_advice is True
    assert cfg.permission_advice_threshold == 20
