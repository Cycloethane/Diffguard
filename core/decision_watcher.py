# -*- coding: utf-8 -*-
"""决策助手感知层：后台线程监听剪贴板与 Agent 窗口，识别"需要决策"的文本。

三通道：
    1. 剪贴板主通道：周期性读取剪贴板，非 diff、非权限审批文本且满足决策
       证据特征时解析并回调（用户把 Agent 的决策内容复制后立即触发）。
    2. 桥接文件通道：轮询 Agent 通过 MCP / CLI / 直接写文件提交的精确
       决策请求（agent_decision_in.json）。读取函数由调用方注入
       （bridge.store.read_agent_decision_prompt），本模块不依赖 bridge 包，
       避免 core↔bridge 循环导入。
    3. UIA 辅助通道：周期性扫描顶层窗口控件文本，识别 Agent 窗口中的决策
       列表（尽力而为；终端类窗口常读取不到，漏报可接受）。

回调在后台线程中执行，调用方须自行切到 GUI 主线程（Tk after()）。
线程骨架与 UIA 设施由 core.watchers.BaseWatcher 提供。
"""

import time
from typing import Callable, Optional

import pyperclip
from loguru import logger

from core.agent_sources import looks_like_agent_window
from core.decision_parser import is_likely_decision, parse
from core.watchers import BaseWatcher, collect_control_texts
from models.decision_prompt import DecisionPrompt

# 剪贴板轮询间隔（秒）
_CLIPBOARD_INTERVAL: float = 1.5
# 桥接文件轮询间隔（秒）
_BRIDGE_INTERVAL: float = 2.0
# UIA 扫描间隔（秒）
_UIA_INTERVAL: float = 3.0
# 决策文本长度上限（与 parser 一致）
_MAX_TEXT_LEN: int = 6000
# UIA 每窗口最多采集的控件数
_MAX_CONTROLS_PER_WINDOW: int = 200
# 控件类型限制
_INTERESTING_CONTROL_TYPES: tuple[str, ...] = (
    "TextControl",
    "ButtonControl",
    "EditControl",
    "DocumentControl",
    "ListItemControl",
)


class DecisionWatcher(BaseWatcher):
    """后台线程：轮询剪贴板 + 桥接文件 + 扫描 Agent 窗口，识别决策请求。

    属性:
        on_decision_detected: 识别到决策时的回调，参数为 DecisionPrompt。
        interval: 剪贴板轮询间隔（秒）。
        read_bridge_decision: 桥接通道读取函数（返回 DecisionPrompt 并消费
            请求文件）；为 None 时桥接通道关闭。
        available: UIA 是否可用（依赖缺失时为 False，剪贴板/桥接通道仍工作）。
    """

    def __init__(
        self,
        on_decision_detected: Callable[[DecisionPrompt], None],
        interval: float = _CLIPBOARD_INTERVAL,
        read_bridge_decision: Optional[Callable[[], Optional[DecisionPrompt]]] = None,
    ) -> None:
        super().__init__(interval, name="DecisionWatcher")
        self.on_decision_detected: Callable[[DecisionPrompt], None] = on_decision_detected
        self.read_bridge_decision = read_bridge_decision
        self.available: bool = False
        self._last_clipboard: Optional[str] = None
        self._baseline_done: bool = False
        self._last_uia: float = 0.0
        self._last_bridge: float = 0.0

    def start(self) -> None:
        """初始化 UIA 依赖；失败仅禁用 UIA 通道，其余通道照常。"""
        self.available = self._try_init_uia()
        super().start()

    def tick(self) -> None:
        """每轮：剪贴板 + 桥接通道，UIA 通道按独立间隔节流。"""
        self._poll_clipboard()
        self._poll_bridge_decision()
        now: float = time.time()
        if self.available and now - self._last_uia >= _UIA_INTERVAL:
            try:
                self._scan_windows()
            except Exception as exc:
                logger.debug("UIA 决策扫描异常: {}", exc)
            self._last_uia = now

    # ------------------------------------------------------------------
    # 剪贴板通道
    # ------------------------------------------------------------------
    def _poll_clipboard(self) -> None:
        try:
            text: str = pyperclip.paste()
            if not text:
                return
            if len(text) > _MAX_TEXT_LEN:
                text = text[:_MAX_TEXT_LEN]
        except Exception as exc:
            logger.debug("读取剪贴板失败: {}", exc)
            return

        # 首读仅作基线，避免启动时残留剪贴板误弹
        if not self._baseline_done:
            self._baseline_done = True
            self._last_clipboard = text
            return
        if text == self._last_clipboard:
            return
        self._last_clipboard = text

        if not is_likely_decision(text):
            return
        prompt: Optional[DecisionPrompt] = parse(
            [text], window_title="Clipboard", window_handle=None
        )
        if prompt is None:
            return
        if self.seen(("clipboard", text)):
            logger.info("剪贴板识别到决策请求: {}", prompt.question[:60])
            self.on_decision_detected(prompt)

    # ------------------------------------------------------------------
    # 桥接文件通道（Agent 显式提交决策请求）
    # ------------------------------------------------------------------
    def _poll_bridge_decision(self) -> None:
        """按 _BRIDGE_INTERVAL 节流轮询注入的桥接读取函数。

        读取函数返回 None 表示无请求或请求非法（已被消费）；返回
        DecisionPrompt 时经去重后回调。
        """
        if self.read_bridge_decision is None:
            return
        now: float = time.time()
        if now - self._last_bridge < _BRIDGE_INTERVAL:
            return
        self._last_bridge = now
        try:
            prompt = self.read_bridge_decision()
        except Exception as exc:
            logger.debug("桥接决策通道异常: {}", exc)
            return
        if prompt is None:
            return
        if self.seen(("bridge", prompt.question)):
            logger.info("桥接通道识别到决策请求: {}", prompt.question[:60])
            self.on_decision_detected(prompt)

    # ------------------------------------------------------------------
    # UIA 辅助通道
    # ------------------------------------------------------------------
    def _scan_windows(self) -> None:
        if self._ua is None:
            return
        for win in self.iter_windows():
            try:
                self._inspect_window(win)
            except Exception as exc:
                logger.debug("检查窗口异常: {}", exc)
        self.prune_seen()

    def _inspect_window(self, win: object) -> None:
        texts: list[str] = []
        collect_control_texts(
            win, texts, control_types=_INTERESTING_CONTROL_TYPES,
            max_controls=_MAX_CONTROLS_PER_WINDOW,
        )
        title: str = getattr(win, "Name", "") or ""
        if not texts and not title:
            return
        # 仅对标题含 Agent 特征的窗口做 UIA 决策扫描，减少误报
        if not looks_like_agent_window(title):
            return
        combined: str = "\n".join(texts)
        if not is_likely_decision(f"{title}\n{combined}"):
            return
        prompt: Optional[DecisionPrompt] = parse(
            [title] + texts,
            window_title=title,
            window_handle=getattr(win, "NativeWindowHandle", 0) or None,
        )
        if prompt is None:
            return
        key: str = f"{title}|{combined}"
        if self.seen(("uia", key)):
            logger.info("UIA 识别到决策请求: {}（来源 {}）", prompt.question[:60], prompt.source)
            self.on_decision_detected(prompt)
