# -*- coding: utf-8 -*-
"""权限请求监听模块（主通道）：通过 Windows UI Automation 扫描窗口。

本模块是"主通道"，周期性枚举顶层窗口并收集其控件文本，将疑似 AI 编程
助手权限请求（如 OpenCode / ZCode 的授权弹窗）解析为标准化的
PermissionPrompt。

线程骨架、UIA/COM 会话、去重缓存与控件文本采集由 core.watchers.BaseWatcher
提供；UIA 依赖探测失败时线程仍启动但通道禁用（available=False 供 UI 展示），
不影响主程序与其余监听。

UIA 需要：
    - uiautomation
    - pywin32（pythoncom），负责 COM 线程初始化
"""

import re
from typing import Callable

from loguru import logger

from core.permission_parser import PermissionParser
from core.permission_risk import score_prompt
from core.watchers import BaseWatcher, collect_control_texts, iter_controls
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

# 扫描间隔（秒）
_SCAN_INTERVAL: float = 2.0


class PermissionWatcher(BaseWatcher):
    """后台线程：周期性扫描 UIA 窗口树，识别权限请求。

    属性:
        on_prompt_detected: 识别到权限请求时的回调，参数为 PermissionPrompt。
        interval: 扫描间隔（秒）。
        available: UIA 是否可用（依赖缺失时为 False，此时通道空转）。
    """

    def __init__(
        self,
        on_prompt_detected: Callable[[PermissionPrompt], None],
        interval: float = _SCAN_INTERVAL,
    ) -> None:
        super().__init__(interval, name="PermissionWatcher")
        self.on_prompt_detected: Callable[[PermissionPrompt], None] = on_prompt_detected
        self.available: bool = False

    def start(self) -> None:
        """探测 UIA 依赖后启动线程；探测失败仅置 available=False。"""
        self.available = self._try_init_uia()
        super().start()

    def tick(self) -> None:
        """扫描一轮顶层窗口；UIA 不可用时为空操作。"""
        if self._ua is None:
            return
        for win in self.iter_windows():
            try:
                self._inspect_window(win)
            except Exception as exc:
                logger.debug("检查窗口异常: {}", exc)
        self.prune_seen()

    def _inspect_window(self, win: object) -> None:
        """分析单个顶层窗口：收集文本 -> 证据判定 -> 解析 -> 去重回调。"""
        texts: list[str] = []
        collect_control_texts(win, texts, control_types=_INTERESTING_CONTROL_TYPES)
        # 标题加进来，增加来源识别命中率
        title: str = getattr(win, "Name", "") or ""
        if not texts and not title:
            return
        combined: str = "\n".join(texts)
        if not PermissionParser.is_likely_permission_prompt(f"{title}\n{combined}"):
            return

        hwnd: int = getattr(win, "NativeWindowHandle", 0) or 0
        content_hash: int = hash(f"{title}|{combined}")
        if not self.seen((hwnd, content_hash)):
            return

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

    # ------------------------------------------------------------------
    # 决策回写（可选）：在原始窗口中点击对应的允许/拒绝按钮
    # ------------------------------------------------------------------
    def apply_decision(self, prompt: PermissionPrompt, decision: str) -> bool:
        """根据用户决策，在产生该请求的窗口中点击对应按钮（尽力而为）。

        返回是否成功点击。仅当 UIA 可用且窗口仍存在时尝试。
        """
        if self._ua is None or prompt.window_handle is None:
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
            for control in iter_controls(win):
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
        if self._ua is None or prompt.window_handle is None:
            return False
        try:
            import ctypes
            import time

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
