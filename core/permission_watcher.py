# -*- coding: utf-8 -*-
"""权限请求监听模块（主通道）：通过 Windows UI Automation 扫描窗口。

本模块是"主通道"，周期性枚举顶层窗口并收集其控件文本，将疑似 AI 编程
助手权限请求（如 OpenCode 的授权弹窗）解析为标准化的 PermissionPrompt。

UIA 需要：
    - uiautomation
    - pywin32（pythoncom），负责 COM 线程初始化

库缺失或初始化失败时，本模块降级为不可用状态（available=False），
由调用方（app.py）决定是否停止监听，不影响主程序运行。
"""

import re
import threading
import time
from contextlib import nullcontext as _nullcontext
from typing import Callable, Optional

from loguru import logger

from core.permission_parser import PermissionParser
from core.permission_risk import score_prompt
from models.permission_prompt import PermissionPrompt

# 控件类型限制：仅收集这些类型的名称文本，减少 UIA 遍历开销
_INTERESTING_CONTROL_TYPES: tuple[str, ...] = (
    "TextControl",
    "ButtonControl",
    "EditControl",
    "DocumentControl",
    "HyperlinkControl",
    "ListItemControl",
    "CheckBoxControl",
    "RadioButtonControl",
)
# 每个窗口最多采集的控件数（防止极端窗口拖慢扫描）
_MAX_CONTROLS_PER_WINDOW: int = 200
# 文本内容最小长度（视为候选）
_MIN_TEXT_LEN: int = 8
# 去重：同一窗口 + 相同内容哈希 不再回调
_SEEN_BUDGET: int = 256


class PermissionWatcher(threading.Thread):
    """后台线程：周期性扫描 UIA 窗口树，识别权限请求。

    属性:
        on_prompt_detected: 识别到权限请求时的回调，参数为 PermissionPrompt。
        interval: 扫描间隔（秒）。
        available: UIA 是否可用（依赖缺失时为 False，仍可创建实例）。
        _deadpool: (hwnd, content_hash) -> timestamp 的去重缓存。
    """

    def __init__(
        self,
        on_prompt_detected: Callable[[PermissionPrompt], None],
        interval: float = 2.0,
    ) -> None:
        super().__init__(daemon=True)
        self.on_prompt_detected: Callable[[PermissionPrompt], None] = on_prompt_detected
        self.interval: float = interval
        self.available: bool = False
        self._stop_event: threading.Event = threading.Event()
        self._seen: dict[tuple[int, int], float] = {}
        self.name = "PermissionWatcher"
        self._ua: Optional[object] = None
        self._com = None  # pythoncom 模块（延迟加载）

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self) -> None:
        """初始化 UIA 依赖；失败时记录日志并保持 available=False。

        库缺失时降级；COM 初始化在 run() 的监听线程内完成
        （COM 必须在使用它的线程内初始化）。
        """
        try:
            import uiautomation as ua  # type: ignore
            import pythoncom  # type: ignore

            self._ua = ua
            self._com = pythoncom
            self.available = True
            logger.info("UIA 权限监听已初始化")
        except Exception as exc:  # 库缺失 / 环境不支持
            logger.error("UIA 权限监听不可用（可能缺少 uiautomation/pywin32）: {}", exc)
            self.available = False
            return
        super().start()

    def run(self) -> None:
        logger.info("权限监听线程启动，间隔 {} 秒", self.interval)
        try:
            # uiautomation 库要求线程内使用专用初始化上下文（内含 CoInitialize，并
            # 缓存线程参数），避免 "未调用 CoInitialize" 错误。
            initializer = self._ua.UIAutomationInitializerInThread(True)
        except Exception as exc:
            logger.debug("创建 UIA 线程初始化器失败: {}", exc)
            initializer = None

        ctx = initializer if initializer is not None else _nullcontext()
        try:
            with ctx:
                self._com.CoInitialize()
                try:
                    while not self._stop_event.is_set():
                        try:
                            self._scan_once()
                        except Exception as exc:
                            logger.debug("权限扫描异常: {}", exc)
                        self._stop_event.wait(self.interval)
                finally:
                    self._shutdown_com()
        finally:
            if initializer is not None:
                try:
                    initializer.__exit__(None, None, None)
                except Exception:
                    pass
        logger.info("权限监听线程已停止")

    def stop(self) -> None:
        logger.info("请求停止权限监听线程")
        self._stop_event.set()

    def _shutdown_com(self) -> None:
        if self._com is not None:
            try:
                self._com.CoUninitialize()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 扫描逻辑
    # ------------------------------------------------------------------
    def _scan_once(self) -> None:
        if self._ua is None:
            return
        root: object = self._ua.GetRootControl()
        if root is None:
            return
        my_pid: int = self._own_pid()
        for win in root.GetChildren():
            # 跳过 DiffGuard 自身的窗口：权限浮窗自身的按钮文本
            # （允许一次/总是允许/拒绝）恰好满足证据判定，若不排除会
            # 被识别为权限请求导致循环弹窗。
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

    @staticmethod
    def _own_pid() -> int:
        """返回本进程 PID，用于排除 DiffGuard 自身的窗口。"""
        try:
            import os

            return os.getpid()
        except Exception:
            return -1

    def _inspect_window(self, win: object) -> None:
        """分析单个顶层窗口：收集文本 -> 证据判定 -> 解析 -> 去重回调。"""
        texts: list[str] = []
        _collect_texts(win, texts, 0, self._ua)
        # 标题加进来，增加来源识别命中率
        title: str = getattr(win, "Name", "") or ""
        if not texts and not title:
            return
        combined: str = "\n".join(texts)
        if not PermissionParser.is_likely_permission_prompt(f"{title}\n{combined}"):
            return

        hwnd: int = getattr(win, "NativeWindowHandle", 0) or 0
        content_hash: int = hash(f"{title}|{combined}")
        key: tuple[int, int] = (hwnd, content_hash)
        if key in self._seen:
            return
        self._seen[key] = time.time()

        prompt: PermissionPrompt = PermissionParser.parse(
            [title] + texts, window_title=title, window_handle=hwnd or None
        )
        prompt.risk_score, prompt.breakdown = score_prompt(prompt)
        logger.info(
            "识别到权限请求: source={} type={} action={} target={} risk={}",
            prompt.source,
            prompt.prompt_type.value,
            prompt.action.value,
            prompt.target,
            prompt.risk_score,
        )
        self.on_prompt_detected(prompt)

    def _prune_seen(self) -> None:
        """清理去重缓存，防止无限增长。"""
        if len(self._seen) > _SEEN_BUDGET:
            now: float = time.time()
            self._seen = {
                k: v for k, v in self._seen.items() if now - v < 3600
            }

    # ------------------------------------------------------------------
    # 决策回写（可选）：在原始窗口中点击对应的允许/拒绝按钮
    # ------------------------------------------------------------------
    def apply_decision(self, prompt: PermissionPrompt, decision: str) -> bool:
        """根据用户决策，在产生该请求的窗口中点击对应按钮（尽力而为）。

        返回是否成功点击。仅当 UIA 可用且窗口仍存在时尝试。
        """
        if not self.available or self._ua is None or prompt.window_handle is None:
            return False

        pattern: re.Pattern[str]
        if decision == "once_allowed":
            pattern = re.compile(r"allow\s*once|仅本次允许|允许一次", re.IGNORECASE)
        elif decision == "always_allowed":
            pattern = re.compile(r"allow\s*always|总是允许|永久允许", re.IGNORECASE)
        elif decision == "rejected":
            pattern = re.compile(r"reject|deny|拒绝", re.IGNORECASE)
        else:
            return False

        try:
            win = self._ua.ControlFromHandle(prompt.window_handle)  # type: ignore
            if win is None:
                logger.warning("权限窗口已关闭，无法回写决策")
                return False
            for control in _iter_controls(win):
                if getattr(control, "ControlTypeName", "") != "ButtonControl":
                    continue
                if pattern.search(getattr(control, "Name", "") or ""):
                    control.GetInvokePattern().Invoke()
                    logger.info("已回写决策 {}，点击了按钮 '{}'", decision, control.Name)
                    return True
            logger.warning("未找到匹配的决策按钮（窗口句柄 {}）", prompt.window_handle)
        except Exception as exc:
            logger.debug("回写决策失败: {}", exc)
        return False

    # ------------------------------------------------------------------
    # 键盘注入回写（TUI 终端工具，实验性）：方向键选择 + 回车确认
    # ------------------------------------------------------------------
    def apply_decision_keyboard(self, prompt: PermissionPrompt, decision: str) -> bool:
        """针对终端类 TUI 工具（如 opencode）的键盘回写。

        通过 SetForegroundWindow + 方向键/回车模拟用户在 TUI 中的选择。
        由于 TUI 选择项顺序不固定，此处基于**位置猜测**——用户须自行
        确认焦点匹配，故默认关闭（config.keyboard_inject）。

        返回是否完成了按键序列发送（尽力而为）。
        """
        if not self.available or self._ua is None or prompt.window_handle is None:
            return False
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd: int = prompt.window_handle
            if not user32.IsWindow(hwnd):
                logger.warning("权限窗口已关闭，无法键盘回写")
                return False
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.2)

            key_down = (0)  # KeyEventF_KeyDown
            if decision == "rejected":
                # 走一次下箭头（优先命中"拒绝"），然后 Enter
                user32.keybd_event(0x28, 0, key_down, 0)
                user32.keybd_event(0x28, 0, 2, 0)
            else:
                # 允许：默认即第一个选项（Enter 直接确认）
                pass
            user32.keybd_event(0x0D, 0, key_down, 0)
            user32.keybd_event(0x0D, 0, 2, 0)
            logger.info("已通过键盘回写决策 {}（窗口句柄 {}）", decision, hwnd)
            return True
        except Exception as exc:
            logger.debug("键盘回写失败: {}", exc)
            return False


def _iter_controls(control: object):
    """深度优先遍历控件子树（带深度限制）。"""
    stack: list[tuple[object, int]] = [(control, 0)]
    while stack:
        node, depth = stack.pop()
        yield node
        if depth < 6:
            try:
                children = node.GetChildren()
            except Exception:
                children = []
            for child in children:
                stack.append((child, depth + 1))


def _collect_texts(
    control: object, texts: list[str], depth: int, ua: object
) -> None:
    """收集控件文本：仅采集感兴趣的控件类型，且限长。"""
    if len(texts) >= _MAX_CONTROLS_PER_WINDOW:
        return
    name: str = getattr(control, "Name", "") or ""
    ctype: str = getattr(control, "ControlTypeName", "") or ""
    if name and ctype in _INTERESTING_CONTROL_TYPES and len(name.strip()) >= _MIN_TEXT_LEN:
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