# -*- coding: utf-8 -*-
"""决策模块视图：待决策状态 + 用户决策偏好统计。"""

from typing import Any

import customtkinter as ctk

from models.decision_history import decision_stats, get_recent_decisions
from ui.theme import frost, text_color, text_muted


class DecisionView(ctk.CTkFrame):
    """内嵌决策助手状态页。"""

    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text="决策助手", font=ctk.CTkFont(size=16, weight="bold"),
            text_color=text_color(True),
        ).grid(row=0, column=0, sticky="w", padx=6, pady=(0, 6))

        # 状态卡
        status = ctk.CTkFrame(self, fg_color="transparent", corner_radius=10)
        status.grid(row=1, column=0, sticky="ew", padx=2, pady=(0, 8))
        status.grid_columnconfigure(0, weight=1)

        mode: str = getattr(app.config, "decision_assistant", "off")
        pending: bool = bool(getattr(app, "_decision_pending", False))
        stats = decision_stats(100)
        info = (
            f"模式：{mode}   ·   待处理决策：{'有' if pending else '无'}   ·   "
            f"累计决策：{stats['total']}   ·   已作选择：{stats['with_choice']}"
        )
        ctk.CTkLabel(
            status, text=info, font=ctk.CTkFont(size=13), text_color=text_color(True),
            anchor="w", justify="left",
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=12)

        # 最近偏好
        self.scroll: ctk.CTkScrollableFrame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.grid(row=2, column=0, sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)
        self._row: int = 0
        self._load_prefs()

    def _load_prefs(self) -> None:
        records = get_recent_decisions(50)
        if not records:
            ctk.CTkLabel(
                self.scroll, text="暂无决策记录", text_color=text_muted(True)
            ).grid(row=0, column=0, padx=12, pady=30)
            return
        ctk.CTkLabel(
            self.scroll, text="最近的决策偏好", font=ctk.CTkFont(size=13, weight="bold"),
            text_color=text_color(True), anchor="w",
        ).grid(row=self._row, column=0, sticky="w", padx=8, pady=(4, 2))
        self._row += 1
        for rec in records:
            chosen: str = rec.user_decision or "(跳过)"
            ctk.CTkLabel(
                self.scroll,
                text=f"[{rec.timestamp:%m-%d %H:%M}] {rec.question}  →  选择 {chosen}",
                font=ctk.CTkFont(size=12), text_color=text_color(True),
                anchor="w", justify="left", wraplength=720,
            ).grid(row=self._row, column=0, sticky="ew", padx=8, pady=2)
            self._row += 1
