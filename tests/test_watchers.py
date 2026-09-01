# -*- coding: utf-8 -*-
"""watcher 骨架与通道逻辑测试(不启动真实线程/UIA)。"""

from core.agent_sources import looks_like_agent_window
from core.clipboard_watcher import ClipboardWatcher
from core.decision_watcher import DecisionWatcher
from core.watchers import collect_control_texts
from models.decision_prompt import DecisionPrompt


# ----------------------------------------------------------------------
# agent_sources
# ----------------------------------------------------------------------
def test_looks_like_agent_window() -> None:
    assert looks_like_agent_window("OpenCode — main")
    assert looks_like_agent_window("ZCode — session")
    assert looks_like_agent_window("Windows 终端 — python")
    assert not looks_like_agent_window("微信")


# ----------------------------------------------------------------------
# 控件文本采集
# ----------------------------------------------------------------------
class FakeControl:
    def __init__(self, name: str, ctype: str, children: list | None = None) -> None:
        self.Name = name
        self.ControlTypeName = ctype
        self._children = children or []

    def GetChildren(self):
        return self._children


def test_collect_control_texts_filters_and_recurses() -> None:
    tree = FakeControl(
        "root", "PaneControl",
        children=[
            FakeControl("一段足够长的文本内容", "TextControl"),
            FakeControl("短", "TextControl"),  # 长度不足
            FakeControl("允许一次 Allow once", "ButtonControl"),
            FakeControl("一段足够长的文本内容", "TextControl"),  # 重复
            FakeControl("不可采集的长文本内容信息", "TitleBarControl"),  # 类型不符
            FakeControl("深层控件文本内容", "TextControl"),
        ],
    )
    texts: list[str] = []
    collect_control_texts(tree, texts)
    # 长度不足/类型不符/重复的被过滤;8 字符恰好达到 min_text_len
    assert texts == ["一段足够长的文本内容", "允许一次 Allow once", "深层控件文本内容"]


# ----------------------------------------------------------------------
# ClipboardWatcher 通道分发(不起线程,直接调 _handle_text)
# ----------------------------------------------------------------------
def _make_clip_watcher() -> tuple[ClipboardWatcher, list, list]:
    diffs: list[str] = []
    perms: list = []
    w = ClipboardWatcher(
        on_diff_detected=diffs.append,
        on_permission_detected=perms.append,
    )
    return w, diffs, perms


def test_clipboard_diff_channel_dedupes() -> None:
    w, diffs, perms = _make_clip_watcher()
    diff = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"
    w._handle_text(diff)
    w._handle_text(diff)  # 相同内容不再触发
    assert diffs == [diff]
    assert perms == []


def test_clipboard_permission_channel_baseline_and_trigger() -> None:
    w, diffs, perms = _make_clip_watcher()
    text = "OpenCode wants to execute command: rm -rf /tmp/x\nAllow once\nReject"
    w._handle_text(text)  # 首读仅基线
    assert perms == []
    w._handle_text("OpenCode wants to execute command: rm -rf /tmp/y\nAllow once\nReject")
    assert len(perms) == 1
    # 剪贴板权限通道按内容识别来源(无 Clipboard 特例)
    assert perms[0].source == "OpenCode"
    assert perms[0].risk_score > 0


def test_clipboard_ignores_plain_text() -> None:
    w, diffs, perms = _make_clip_watcher()
    w._handle_text("普通文本,什么都不像")
    assert diffs == [] and perms == []


# ----------------------------------------------------------------------
# DecisionWatcher 桥接通道(注入读取函数)
# ----------------------------------------------------------------------
def _make_prompt(question: str = "选哪个？") -> DecisionPrompt:
    from models.decision_prompt import DecisionOption

    return DecisionPrompt(
        question=question, source="ZCode",
        options=[DecisionOption(key="A", text="甲"), DecisionOption(key="B", text="乙")],
    )


def test_decision_bridge_channel_consumes_and_calls_back() -> None:
    got: list[DecisionPrompt] = []
    reader_calls: list[int] = []
    prompt = _make_prompt()

    def reader() -> DecisionPrompt | None:
        reader_calls.append(1)
        return prompt

    w = DecisionWatcher(on_decision_detected=got.append, read_bridge_decision=reader)
    w._poll_bridge_decision()
    assert got == [prompt]
    assert len(reader_calls) == 1

    # 节流期内不再读文件
    w._poll_bridge_decision()
    assert len(reader_calls) == 1

    # 越过节流后:同一问题被去重,不再回调
    w._last_bridge = 0.0
    w._poll_bridge_decision()
    assert len(reader_calls) == 2
    assert got == [prompt]


def test_decision_bridge_channel_disabled_without_reader() -> None:
    got: list = []
    w = DecisionWatcher(on_decision_detected=got.append)
    w._poll_bridge_decision()  # 无注入读取函数,空操作不抛异常
    assert got == []


# ----------------------------------------------------------------------
# bridge.read_agent_decision_prompt(桥接文件 → DecisionPrompt)
# ----------------------------------------------------------------------
def test_read_agent_decision_prompt_roundtrip(bridge_tmp) -> None:
    from bridge import store

    store.write_agent_decision(
        "打包方式？",
        [{"key": "A", "text": "单文件"}, {"key": "B", "text": "目录"}],
        context="ctx",
    )
    prompt = store.read_agent_decision_prompt()
    assert prompt is not None
    assert prompt.question == "打包方式？"
    assert [o.key for o in prompt.options] == ["A", "B"]
    assert "A) 单文件" in prompt.raw_text
    # 消费语义:读取后请求文件被清空
    assert store.read_agent_decision() is None


def test_read_agent_decision_prompt_invalid_options(bridge_tmp) -> None:
    from bridge import store

    store.write_agent_decision("问题", [{"key": "A", "text": "只有一个"}])
    assert store.read_agent_decision_prompt() is None
    assert store.read_agent_decision() is None  # 非法请求同样被消费


def test_read_agent_decision_prompt_passthrough_source(bridge_tmp) -> None:
    from bridge import store

    # 直接写文件以携带自定义 source(MCP 侧写入参数化在 Phase 2)
    store._write_json(
        store._path("agent_decision_in.json"),
        {
            "timestamp": "2026-01-01T00:00:00",
            "source": "ZCode",
            "question": "部署到哪？",
            "options": [{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}],
            "context": "",
        },
    )
    prompt = store.read_agent_decision_prompt()
    assert prompt is not None
    assert prompt.source == "ZCode"
