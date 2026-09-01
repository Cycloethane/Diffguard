# -*- coding: utf-8 -*-
"""权限模块视图：在模块容器中展示权限审批记录列表。"""

from typing import Any

import customtkinter as ctk

from models.permission_history import get_recent_permissions
from ui.theme import frost, text_color, text_muted


class PermissionHistoryView(ctk.CTkFrame):
    """内嵌权限审批记录列表。"""

    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text="权限审批记录", font=ctk.CTkFont(size=16, weight="bold"),
            text_color=text_color(True),
        ).grid(row=0, column=0, sticky="w", padx=6, pady=(0, 6))

        self.list_scroll: ctk.CTkScrollableFrame = ctk.CTkScrollableFrame(
            self, fg_color="transparent"
        )
        self.list_scroll.grid(row=1, column=0, sticky="nsew")
        self.list_scroll.grid_columnconfigure(0, weight=1)
        self._row: int = 0
        self._reload()

    def _reload(self) -> None:
        for w in self.list_scroll.winfo_children():
            w.destroy()
        self._row = 0
        records = get_recent_permissions(100)
        if not records:
            ctk.CTkLabel(
                self.list_scroll, text="暂无权限审批记录", text_color=text_muted(True)
            ).grid(row=0, column=0, padx=12, pady=30)
            return
        for rec in records:
            self._build_row(rec)

    def _build_row(self, rec: Any) -> None:
        score: int = rec.risk_score or 0
        color: str = "#DA3633" if score >= 60 else "#D29922" if score >= 40 else "#238636"
        row: ctk.CTkFrame = ctk.CTkFrame(self.list_scroll, corner_radius=8, fg_color="transparent")
        row.grid(row=self._row, column=0, sticky="ew", padx=6, pady=3)
        row.grid_columnconfigure(1, weight=1)
        self._row += 1

        ctk.CTkLabel(
            row, text=f"[{rec.timestamp:%Y-%m-%d %H:%M}]",
            font=ctk.CTkFont(size=11), text_color=text_muted(True),
        ).grid(row=0, column=0, sticky="w", padx=8, pady=(6, 0))
        ctk.CTkLabel(
            row, text=rec.target or "(unknown)",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=text_color(True),
            anchor="w", justify="left", wraplength=560,
        ).grid(row=0, column=1, sticky="ew", padx=6, pady=(6, 0))
        ctk.CTkLabel(
            row, text=str(score),
            font=ctk.CTkFont(size=12, weight="bold"), text_color=color,
        ).grid(row=0, column=2, sticky="e", padx=8, pady=(6, 0))
        ctk.CTkLabel(
            row,
            text=f"{rec.source} · {rec.action} · 决策 {rec.user_decision}",
            font=ctk.CTkFont(size=11), text_color=text_muted(True),
        ).grid(row=1, column=1, columnspan=2, sticky="ew", padx=6, pady=(0, 6))
