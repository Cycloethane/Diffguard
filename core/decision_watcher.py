# -*- coding: utf-8 -*-
"""决策助手感知层：后台线程监听剪贴板与 Agent 窗口，识别"需要决策"的文本。

双通道：
    1. 剪贴板主通道：周期性读取剪贴板，非 diff、非权限审批文本且满足决策
       证据特征时解析并回调（用户把 Agent 的决策内容复制后立即触发）。
    2. UIA 辅助通道：周期性扫描顶层窗口控件文本，识别 Agent 窗口中的决策
       列表（尽力而为；终端类窗口常读取不到，漏报可接受）。

回调在后台线程中执行，调用方须自行切到 GUI 主线程（Tk after()）。

与 PermissionWatcher 的关系：
    - 复用其线程/去重/降级模式，但证据判定与解析完全独立（decision_parser）。
    - 可独立开关（config.decision_assistant != "off"）。
"""

import threading
import time
from contextlib import nullcontext as _nullcontext
from typing import Any, Callable, Optional

import pyperclip
from loguru import logger

from core.decision_parser import is_likely_decision, parse
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
# 去重预算
_SEEN_BUDGET: int = 256


class DecisionWatcher(threading.Thread):
    """后台线程：轮询剪贴板 + 扫描 Agent 窗口，识别决策请求。

    属性:
        on_decision_detected: 识别到决策时的回调，参数为 DecisionPrompt。
        interval: 剪贴板轮询间隔（秒）。
        available: UIA 是否可用（依赖缺失时为 False，剪贴板通道仍工作）。
    """

    def __init__(
        self,
        on_decision_detected: Callable[[DecisionPrompt], None],
        interval: float = _CLIPBOARD_INTERVAL,
    ) -> None:
        super().__init__(daemon=True)
        self.on_decision_detected: Callable[[DecisionPrompt], None] = on_decision_detected
        self.interval: float = interval
        self.available: bool = False
        self._stop_event: threading.Event = threading.Event()
        self._last_clipboard: Optional[str] = None
        self._baseline_done: bool = False
        self._seen: dict[tuple[str, str], float] = {}
        self.name = "DecisionWatcher"
        self._ua: Optional[object] = None
        self._com = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self) -> None:
        """初始化 UIA 依赖；失败仅禁用 UIA 通道，剪贴板通道照常。"""
        try:
            import uiautomation as ua  # type: ignore
            import pythoncom  # type: ignore

            self._ua = ua
            self._com = pythoncom
            self.available = True
            logger.info("决策助手 UIA 通道已初始化")
        except Exception as exc:
            logger.warning("决策助手 UIA 通道不可用（仅剪贴板通道）: {}", exc)
            self.available = False
        super().start()

    def run(self) -> None:
        logger.info("决策监听线程启动，剪贴板间隔 {} 秒", self.interval)
        last_uia: float = 0.0
        initializer = None
        if self._ua is not None:
            try:
                initializer = self._ua.UIAutomationInitializerInThread(True)
            except Exception as exc:
                logger.debug("创建 UIA 线程初始化器失败: {}", exc)
                initializer = None
        ctx = initializer if initializer is not None else _nullcontext()
        try:
            with ctx:
                if self._com is not None:
                    self._com.CoInitialize()
                try:
                    while not self._stop_event.is_set():
                        self._poll_clipboard()
                        self._poll_bridge_decision()
                        now: float = time.time()
                        if self.available and now - last_uia >= _UIA_INTERVAL:
                            try:
                                self._scan_windows()
                                last_uia = now
                            except Exception as exc:
                                logger.debug("UIA 决策扫描异常: {}", exc)
                        self._stop_event.wait(self.interval)
                finally:
                    if self._com is not None:
                        try:
                            self._com.CoUninitialize()
                        except Exception:
                            pass
        finally:
            if initializer is not None:
                try:
                    initializer.__exit__(None, None, None)
                except Exception:
                    pass
        logger.info("决策监听线程已停止")

    def stop(self) -> None:
        """请求停止监听线程。"""
        logger.info("请求停止决策监听线程")
        self._stop_event.set()

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
        if self._dedupe("clipboard", text):
            logger.info("剪贴板识别到决策请求: {}", prompt.question[:60])
            self.on_decision_detected(prompt)

    # ------------------------------------------------------------------
    # UIA 辅助通道
    # ------------------------------------------------------------------
    def _scan_windows(self) -> None:
        if self._ua is None:
            return
        root: object = self._ua.GetRootControl()
        if root is None:
            return
        my_pid: int = _own_pid()
        for win in root.GetChildren():
            try:
                if getattr(win, "ProcessId", None) == my_pid:
                    continue
            except Exception:
                pass
            try:
                self._inspect_window(win)
            except Exception as exc:
                logger.debug("检查窗口异常: {}", exc)
        self._prune_seen()

    def _inspect_window(self, win: object) -> None:
        texts: list[str] = []
        _collect_texts(win, texts, 0, self._ua)
        title: str = getattr(win, "Name", "") or ""
        if not texts and not title:
            return
        # 仅对标题含 Agent 特征的窗口做 UIA 决策扫描，减少误报
        if not _looks_like_agent_window(title):
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
        if self._dedupe("uia", key):
            logger.info("UIA 识别到决策请求: {}（来源 {}）", prompt.question[:60], prompt.source)
            self.on_decision_detected(prompt)

    # ------------------------------------------------------------------
    # 桥接文件通道（功能10：Agent 显式提交决策请求）
    # ------------------------------------------------------------------
    def _poll_bridge_decision(self) -> None:
        """轮询 bridge/agent_decision_in.json：Agent 提交的精确决策请求。

        这是比剪贴板更可靠的通道：OpenCode 通过 MCP submit_decision 或
        直接写文件提交，本方法读取后构造 DecisionPrompt 回调。
        """
        try:
            from bridge import store

            data = store.read_agent_decision()
            if not data:
                return
            question: str = str(data.get("question", "")).strip()
            options_raw: list = data.get("options", []) or []
            if not question or len(options_raw) < 2:
                store.clear_agent_decision()
                return
            options: list = []
            for o in options_raw[:12]:
                key = str(o.get("key", "") or "")
                text = str(o.get("text", "") or "")
                if key and text:
                    options.append({"key": key, "text": text})
            if len(options) < 2:
                store.clear_agent_decision()
                return
            # 构造 DecisionPrompt
            prompt = DecisionPrompt(
                question=question,
                source="OpenCode",
                options=[_make_option(opt) for opt in options],
                raw_text=question + "\n" + "\n".join(f"{o['key']}) {o['text']}" for o in options),
            )
            if not self._dedupe("bridge", question):
                store.clear_agent_decision()
                return
            logger.info("桥接通道识别到决策请求: {}", question[:60])
            self.on_decision_detected(prompt)
            store.clear_agent_decision()
        except Exception as exc:
            logger.debug("桥接决策通道异常: {}", exc)

    # ------------------------------------------------------------------
    # 去重
    # ------------------------------------------------------------------
    def _dedupe(self, channel: str, key: str) -> bool:
        """判断是否为新决策；是则记录并返回 True，否则 False。"""
        k: str = f"{channel}|{key}"
        if k in self._seen:
            return False
        self._seen[k] = time.time()
        return True

    def _prune_seen(self) -> None:
        if len(self._seen) > _SEEN_BUDGET:
            now: float = time.time()
            self._seen = {k: v for k, v in self._seen.items() if now - v < 3600}


# ----------------------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------------------
def _make_option(data: dict) -> Any:
    """把桥接文件中的 {key,text} 字典转为 DecisionOption。"""
    from models.decision_prompt import DecisionOption

    return DecisionOption(key=str(data.get("key", "")), text=str(data.get("text", "")))


def _own_pid() -> int:
    """返回本进程 PID，用于排除 DiffGuard 自身的窗口。"""
    try:
        import os

        return os.getpid()
    except Exception:
        return -1


# Agent 窗口标题特征词
_AGENT_TITLE_MARKERS: tuple[str, ...] = (
    "opencode",
    "open code",
    "cursor",
    "cline",
    "windsurf",
    "codex",
    "copilot",
    "gemini",
    "aider",
    "codeium",
    "trae",
    "agent",
    "终端",
    "terminal",
    "command prompt",
    "powershell",
    "cmd",
    "vscode",
)


def _looks_like_agent_window(title: str) -> bool:
    """判断窗口标题是否像 AI 编程 Agent / 终端（UIA 通道前置过滤）。"""
    lower: str = title.lower()
    return any(m in lower for m in _AGENT_TITLE_MARKERS)


def _collect_texts(
    control: object, texts: list[str], depth: int, ua: object
) -> None:
    """收集控件文本：仅采集感兴趣的控件类型，且限长。"""
    if len(texts) >= _MAX_CONTROLS_PER_WINDOW:
        return
    name: str = getattr(control, "Name", "") or ""
    ctype: str = getattr(control, "ControlTypeName", "") or ""
    if name and ctype in _INTERESTING_CONTROL_TYPES and len(name.strip()) >= 8:
        if name not in texts:
            texts.append(name)
    if depth >= 6 or len(texts) >= _MAX_CONTROLS_PER_WINDOW:
        return
    try:
        children = control.GetChildren()
    except Exception:
        children = []
    for child in children:
        _collect_texts(child, texts, depth + 1, ua)
