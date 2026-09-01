# -*- coding: utf-8 -*-
"""剪贴板监听模块：后台守护线程轮询剪贴板内容。

双通道工作：
    1. diff 通道：检测到包含 ``diff --git`` 标记且与上次不同的内容时，
       通过 on_diff_detected 通知调用方。
    2. 权限通道（辅助通道）：当剪贴板内容不包含 diff 标记但满足权限
       请求证据特征时，通过 on_permission_detected 通知调用方。
       权限文本可能来自已复制到剪贴板的审批信息（如授权通知文案），
       作为 UIA 主通道的补充。

回调在后台线程中执行，调用方需自行切换到 GUI 主线程（例如使用 Tk 的
after() 方法）以保证线程安全。
"""

from typing import Callable, Optional

import pyperclip
from loguru import logger

from core.permission_parser import PermissionParser
from core.permission_risk import score_prompt
from core.watchers import BaseWatcher
from models.permission_prompt import PermissionPrompt

# 判定剪贴板内容为 git diff 的标记
_DIFF_MARKER: str = "diff --git"
# 默认轮询间隔（秒）
_DEFAULT_INTERVAL: float = 1.0


class ClipboardWatcher(BaseWatcher):
    """后台线程，周期性读取剪贴板并触发各通道回调。

    属性:
        on_diff_detected: 检测到 git diff 时调用的回调，参数为 diff 文本。
        on_permission_detected: 检测到权限文本时调用的回调，
            参数为 PermissionPrompt（已评分）。
        interval: 轮询间隔（秒）。
    """

    def __init__(
        self,
        on_diff_detected: Callable[[str], None],
        on_permission_detected: Optional[Callable[[PermissionPrompt], None]] = None,
        interval: float = _DEFAULT_INTERVAL,
    ) -> None:
        """初始化监听线程。

        参数:
            on_diff_detected: 回调函数，签名 callable(diff_text: str)。
            on_permission_detected: 可选回调，签名 callable(prompt)。为
                None 时权限通道关闭。
            interval: 每次读取剪贴板之间的间隔秒数。
        """
        super().__init__(interval, name="ClipboardWatcher")
        self.on_diff_detected: Callable[[str], None] = on_diff_detected
        self.on_permission_detected: Optional[Callable[[PermissionPrompt], None]] = (
            on_permission_detected
        )
        self._last_content: Optional[str] = None
        self._last_permission_text: Optional[str] = None
        self._permission_baseline_done: bool = False

    def tick(self) -> None:
        """每轮读取一次剪贴板并分发到各通道。"""
        try:
            text: str = pyperclip.paste()
            if text:
                self._handle_text(text)
        except Exception as exc:
            # Windows 下剪贴板可能被其它程序占用或被拒绝访问，忽略并重试
            logger.debug("读取剪贴板失败: {}", exc)

    def _handle_text(self, text: str) -> None:
        if _DIFF_MARKER in text:
            if text != self._last_content:
                logger.info("检测到新的 git diff 剪贴板内容（{} 字符）", len(text))
                self._last_content = text
                self.on_diff_detected(text)
            return

        # 权限通道：非 diff 内容 + 满足证据特征 + 与上次不同
        if self.on_permission_detected is not None and PermissionParser.is_likely_permission_prompt(text):
            if not self._permission_baseline_done:
                # 首次读取仅供基线，避免启动时残留剪贴板内容误弹
                self._permission_baseline_done = True
                self._last_permission_text = text
                return
            if text != self._last_permission_text:
                logger.info("检测到权限请求文本（{} 字符）", len(text))
                self._last_permission_text = text
                prompt: PermissionPrompt = PermissionParser.parse(
                    [text], window_title="Clipboard", window_handle=None
                )
                prompt.risk_score, prompt.breakdown = score_prompt(prompt)
                self.on_permission_detected(prompt)
