# -*- coding: utf-8 -*-
"""core.ai_client 及其两个调用方(reviewer / decision_explainer)的测试。"""

import pytest

from core import ai_client
from core.ai_client import stream_chat, stream_lines
from core.decision_explainer import explain_decision, parse_opt_line, parse_recommend_line
from core.decision_parser import parse as parse_decision
from core.reviewer import analyze_diff
from models.config import Config


class _FakeChunk:
    def __init__(self, content: str) -> None:
        delta = type("Delta", (), {"content": content})()
        self.choices = [type("Choice", (), {"delta": delta})()]


class _FakeClient:
    """替身 OpenAI 客户端:create() 返回预设片段或抛异常。"""

    def __init__(self, chunks=None, exc: Exception | None = None) -> None:
        self._chunks = chunks or []
        self._exc = exc
        completions = self
        self.chat = type("Chat", (), {"completions": completions})()

    def create(self, **_kw):
        if self._exc is not None:
            raise self._exc

        class _Resp:
            def __init__(self, chunks):
                self._chunks = chunks

            def __iter__(self):
                return iter(self._chunks)

        return _Resp(self._chunks)


@pytest.fixture
def cfg() -> Config:
    return Config(api_key="test-key", model="test-model", provider="siliconflow")


def _install_client(monkeypatch, client: _FakeClient) -> None:
    monkeypatch.setattr(ai_client, "OpenAI", lambda **_kw: client)


# ----------------------------------------------------------------------
# stream_chat
# ----------------------------------------------------------------------
def test_stream_chat_no_api_key(cfg: Config) -> None:
    cfg.api_key = ""
    parts = list(stream_chat(cfg, "sys", "user"))
    assert len(parts) == 1
    assert parts[0].startswith("\n\n[错误] 尚未配置 API Key")
    assert parts[0].endswith("\n")


def test_stream_chat_success_yields_chunks(cfg: Config, monkeypatch) -> None:
    _install_client(monkeypatch, _FakeClient(chunks=[_FakeChunk("你好\n"), _FakeChunk("世界")]))
    assert "".join(stream_chat(cfg, "sys", "user")) == "你好\n世界"


def test_stream_chat_unknown_exception(cfg: Config, monkeypatch) -> None:
    _install_client(monkeypatch, _FakeClient(exc=RuntimeError("boom")))
    parts = list(stream_chat(cfg, "sys", "user", error_prefix="#ERR# ", error_suffix="", label="测试"))
    assert parts == ["#ERR# 测试过程发生未知异常，请查看日志。"]


def test_stream_lines_reassembles_by_line() -> None:
    lines = list(stream_lines(iter(["#QUESTION# 问题\n", "#OPT", "ION# {\"k\":1}\n尾行"])))
    assert lines == ['#QUESTION# 问题', '#OPTION# {"k":1}', "尾行"]


def test_stream_lines_drops_blank_lines() -> None:
    assert list(stream_lines(iter(["a\n\n", "\nb"]))) == ["a", "b"]


# ----------------------------------------------------------------------
# 调用方回归
# ----------------------------------------------------------------------
def test_analyze_diff_no_key_error_text() -> None:
    parts = list(analyze_diff("diff --git a b", Config(api_key="")))
    assert parts == ["\n\n[错误] 尚未配置 API Key，请在“设置”中填写后重试。\n"]


def test_explain_decision_no_key_error_line() -> None:
    prompt = parse_decision(["请选择：\nA) 甲\nB) 乙"], window_title="Clipboard")
    assert prompt is not None
    lines = list(explain_decision(prompt, Config(api_key="")))
    assert lines == ["#ERROR# 尚未配置 API Key，请在“设置”中填写后重试。"]


def test_decision_protocol_line_parsers() -> None:
    assert parse_opt_line('#OPTION# {"key":"A","text":"x","meaning":"m","risk":"low","reason":"r"}') == {
        "key": "A", "text": "x", "meaning": "m", "risk": "low", "reason": "r",
    }
    assert parse_opt_line("#OPTION# not-json") == {}
    assert parse_recommend_line('#RECOMMEND# {"option":"B","conclusion":"选B"}') == {
        "option": "B", "conclusion": "选B",
    }
    assert parse_opt_line("普通行") == {}
