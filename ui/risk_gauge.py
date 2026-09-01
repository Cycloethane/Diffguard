# -*- coding: utf-8 -*-
"""风险进度条组件：0-100 纯色（无渐变）进度条。

基于 customtkinter 的 CTkProgressBar，填充色始终为当前分数所在分带的
单一纯色（蓝→绿→黄→橙→红）。提供标准版与迷你版（供前台小窗复用）。
"""

from typing import Any, Optional

import customtkinter as ctk

from core.risk_score import score_color, score_label
from ui.animation import animate, interpolate_color
from ui.theme import surface_muted, text_color, text_muted

_FG: str = text_color(light=True)
_FG_MUTED: str = text_muted(light=True)
_THRESHOLDS: tuple[str, ...] = ("0", "20", "40", "60", "80", "100")


class RiskGauge(ctk.CTkFrame):
    """纯色风险进度条。

    属性:
        score: 当前风险分数（0-100）。
        contributions: 当前触发因素明细（用于展示）。
    """

    def __init__(
        self,
        master: Any,
        width: int = 320,
        mini: bool = False,
    ) -> None:
        """构造风险进度条。

        参数:
            master: 父容器。
            width: 进度条宽度。
            mini: 是否为迷你版（隐藏刻度与触发因素，用于前台小窗）。
        """
        super().__init__(master, fg_color="transparent")
        self.width: int = width
        self.mini: bool = mini
        self.score: int = 0
        self.contributions: list[str] = []
        self._display_score: int = 0
        self._display_contributions: list[str] = []

        self.grid_columnconfigure(1, weight=1) if not mini else None

        # 标题与分数
        self.title_label: ctk.CTkLabel = ctk.CTkLabel(
            self, text="风险", font=ctk.CTkFont(size=12, weight="bold")
        )
        self.score_label: ctk.CTkLabel = ctk.CTkLabel(
            self,
            text="0",
            font=ctk.CTkFont(size=13, weight="bold"),
            width=64,
            anchor="e",
        )

        # 进度条（纯色填充）
        self.progress: ctk.CTkProgressBar = ctk.CTkProgressBar(
            self,
            width=width,
            height=14 if mini else 18,
            corner_radius=7,
            progress_color=score_color(0),
        )
        self.progress.set(0.0)

        # 刻度与触发因素（仅标准版）
        self.threshold_label: Optional[ctk.CTkLabel] = None
        self.breakdown_label: Optional[ctk.CTkLabel] = None
        if not mini:
            self.threshold_label = ctk.CTkLabel(
                self,
                text=" ".join(_THRESHOLDS),
                font=ctk.CTkFont(size=9),
                text_color=_FG_MUTED,
            )
            self.breakdown_label = ctk.CTkLabel(
                self,
                text="暂无触发因素",
                font=ctk.CTkFont(size=11),
                text_color=_FG_MUTED,
                wraplength=max(260, width - 120),
                justify="left",
                anchor="w",
            )

        self._lay_out()

    def _lay_out(self) -> None:
        """按版本（标准/迷你）排布控件。"""
        if self.mini:
            self.title_label.grid(row=0, column=0, sticky="w")
            self.score_label.grid(row=0, column=1, sticky="e", padx=(6, 0))
            self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
            return

        self.title_label.grid(row=0, column=0, sticky="w")
        self.score_label.grid(row=0, column=2, sticky="e", padx=(6, 0))
        self.grid_columnconfigure(1, weight=1)
        self.progress.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(2, 0))
        if self.threshold_label is not None:
            self.threshold_label.grid(row=2, column=0, columnspan=3, sticky="ew")
        if self.breakdown_label is not None:
            self.breakdown_label.grid(
                row=3, column=0, columnspan=3, sticky="w", pady=(4, 0)
            )

    def set_score(self, score: int, contributions: Optional[list[str]] = None) -> None:
        """更新分数并刷新进度条（数字滚动 + 颜色渐变）。

        参数:
            score: 0-100 分数。
            contributions: 触发因素明细列表。
        """
        score = max(0, min(100, score))
        self.score = score
        if contributions is not None:
            self.contributions = list(contributions)

        old_score: int = getattr(self, "_display_score", 0)
        old_color: str = self.progress.cget("progress_color") or score_color(0)
        new_color: str = score_color(score)

        self._display_score = score
        self._display_contributions = list(self.contributions)

        def _step(t: float) -> None:
            cur: int = int(round(old_score + (score - old_score) * t))
            color: str = interpolate_color(old_color, new_color, t)
            self.progress.set(cur / 100.0)
            self.progress.configure(progress_color=color)
            self.score_label.configure(text=str(cur), text_color=color)
            if not self.mini:
                self._update_breakdown(cur)

        animate(self, _step, duration_ms=450)
        if not self.mini:
            self._update_breakdown(score)

    def _update_breakdown(self, score: int) -> None:
        """刷新刻度与触发因素明细（颜色随当前分数联动）。"""
        if self.threshold_label is not None:
            self.threshold_label.configure(
                text=" ".join(_THRESHOLDS),
                text_color=_FG_MUTED,
            )
        if self.breakdown_label is not None:
            text: str = (
                "  ·  ".join(self._display_contributions)
                if self._display_contributions
                else "暂无触发因素"
            )
            hint: str = f"（{score_label(score)}）"
            self.breakdown_label.configure(text=f"{text} {hint}")