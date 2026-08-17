# -*- coding: utf-8 -*-
"""前台模式小窗：置顶、无边框、可拖拽的迷你悬浮面板。

体积最小化，仅展示状态、文件数与风险进度条；通过 after() 定期从主窗口
拉取状态（主线程执行，天然线程安全）。
"""

from typing import Any

import customtkinter as ctk
from loguru import logger

from ui.risk_gauge import RiskGauge

# 默认位置（屏幕右下角附近）
_POS_X: int = 40
_POS_Y: int = 40
# 面板尺寸（刻意做小，占用面积极小）
_WIDTH: int = 240
_HEIGHT: int = 96
_POLL_MS: int = 250

class MiniOverlay(ctk.CTkToplevel):
    """极简前台悬浮窗。

    属性:
        app: 主窗口引用（通过 overlay_payload() 获取状态）。
    """

    def __init__(self, app: Any) -> None:
        """构造前台小窗。

        参数:
            app: DiffGuardApp 主窗口实例。
        """
        super().__init__(app)
        self.app: Any = app

        self.title("DiffGuard 前台")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.geometry(f"{_WIDTH}x{_HEIGHT}+{_POS_X}+{_POS_Y}")
        self.minsize(_WIDTH, _HEIGHT)

        self._build_ui()
        self._bind_drag()
        self.protocol("WM_DELETE_WINDOW", lambda: self._hide(app))
        self.after(_POLL_MS, self._poll_state)

    def _build_ui(self) -> None:
        """构建小窗内容。"""
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # 顶部一行：状态 + 文件数 + 收起
        top: ctk.CTkFrame = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 0))
        top.grid_columnconfigure(1, weight=1)

        self.state_label: ctk.CTkLabel = ctk.CTkLabel(
            top, text="● 就绪", font=ctk.CTkFont(size=11), anchor="w"
        )
        self.state_label.grid(row=0, column=0, sticky="w")

        self.count_label: ctk.CTkLabel = ctk.CTkLabel(
            top,
            text="0 文件",
            font=ctk.CTkFont(size=11),
            text_color="#9ca3af",
            anchor="e",
        )
        self.count_label.grid(row=0, column=1, sticky="e")

        # 决策徽标（检测到 Agent 决策时点亮，点击打开解析浮窗）
        self.decision_badge: ctk.CTkButton = ctk.CTkButton(
            top,
            text="🤔",
            width=26,
            height=20,
            fg_color="#d29922",
            hover_color="#b3861c",
            command=self._on_decision_badge,
        )
        self.decision_badge.grid(row=0, column=2, padx=(4, 0))
        self.decision_badge.grid_remove()

        close_btn: ctk.CTkButton = ctk.CTkButton(
            top,
            text="✕",
            width=22,
            height=18,
            fg_color="transparent",
            hover_color="#333333",
            command=lambda: self._hide(self.app),
        )
        close_btn.grid(row=0, column=3, padx=(4, 0))

        # 底部：迷你风险进度条
        self.gauge: RiskGauge = RiskGauge(self, width=_WIDTH - 16, mini=True)
        self.gauge.grid(row=1, column=0, sticky="ew", padx=8, pady=(2, 6))

    def _bind_drag(self) -> None:
        """绑定拖拽移动（整窗无边框，拖拽条为顶部区域）。"""
        for widget in (self, self.state_label, self.count_label):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)

    def _drag_start(self, event: Any) -> None:
        """记录拖拽起始点。"""
        self._drag_x: int = event.x
        self._drag_y: int = event.y

    def _drag_move(self, event: Any) -> None:
        """根据鼠标移动刷新窗口位置。"""
        try:
            x: int = self.winfo_pointerx() - self._drag_x
            y: int = self.winfo_pointery() - self._drag_y
            self.geometry(f"+{x}+{y}")
        except Exception as exc:
            logger.debug("前台小窗拖拽异常: {}", exc)

    def _poll_state(self) -> None:
        """定期从主窗口拉取状态并刷新（主线程运行）。"""
        if self.winfo_exists():
            payload = self.app.overlay_payload()
            self.state_label.configure(text=f"● {payload['status']}")
            self.count_label.configure(text=f"{payload['file_count']} 文件")
            self.gauge.set_score(payload["score"], payload["contributions"])
            pending: bool = bool(payload.get("decision_pending"))
            if pending and not self.decision_badge.winfo_ismapped():
                self.decision_badge.grid()
            elif not pending and self.decision_badge.winfo_ismapped():
                self.decision_badge.grid_remove()
        self.after(_POLL_MS, self._poll_state)

    def _on_decision_badge(self) -> None:
        """点击决策徽标：请求主窗口打开决策解析浮窗。"""
        try:
            getattr(self.app, "open_decision_alert")(self)
        except Exception:
            pass

    def _hide(self, app: Any) -> None:
        """隐藏小窗，并把主窗口的按钮状态复位。"""
        logger.info("隐藏前台小窗")
        self.withdraw()
        try:
            getattr(app, "overlay_button").configure(text="前台模式")
        except Exception:
            pass